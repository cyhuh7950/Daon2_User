"""TTS 엔진 관리 라우트(WO-F7T): 관리자 전용, ETag 동시성, 입력 검증, 오류 코드, 키 비노출."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from daon2_user_api.audit import AuditEventStore
from daon2_user_api.authorization import AuthorizationService, Role, SqliteAuthorizationRepository
from daon2_user_api.identity import IdentityPrincipal
from daon2_user_api.runtime import WEB_SESSION_COOKIE, RuntimeDependencies, RuntimeSettings, create_app
from daon2_user_api.tts_engine_service import TtsEngineError
from test_identity_support import POLICY_VERSION, create_service, identity_session_view

ENGINE_ID = "te-" + "a" * 32
BASE = "/api/v1/admin/tts-engines"


def view(**over):
    base = {"engine_id": ENGINE_ID, "slug": "supertonic", "label": "Supertonic", "base_url": "https://tts.example.com", "provider_kind": "external_api",
            "language": "ko", "timeout_seconds": 120, "voices": {"A": "F1", "B": "M1"}, "voice_choices": ["F1", "M1"], "status": "unverified",
            "last_checked_at": None, "error_code": None, "is_default": True, "version": 1, "has_credential": True, "source": "settings"}
    return {**base, **over}


class FakeService:
    def __init__(self):
        self.calls = []
        self.fail = None
        self.config = None   # for_tenant가 돌려줄 조직별 TtsConfig(None이면 엔진 없음)
        self.resolved = []

    def for_tenant(self, tenant_id):
        self.resolved.append(tenant_id)
        return self.config

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if self.fail:
            raise TtsEngineError(*self.fail)

    def list(self, ctx):
        self._record("list", ctx)
        return [view(), view(engine_id=None, slug="deploy", source="deployment", status="deployment", version=0)]

    def register(self, ctx, spec):
        self._record("register", ctx, spec)
        return view(slug=spec["slug"])

    def verify(self, ctx, engine_id):
        self._record("verify", ctx, engine_id)
        return view(status="verified", version=2)

    def update(self, ctx, engine_id, patch, version):
        self._record("update", ctx, engine_id, patch, version)
        return view(version=version + 1)

    def disconnect(self, ctx, engine_id):
        self._record("disconnect", ctx, engine_id)


class TtsEngineRoutesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        db_path = Path(self.directory.name) / "runtime.sqlite3"
        audit = AuditEventStore()
        identity, identity_repository, _, clock = create_service(db_path, audit_store=audit)
        repository = SqliteAuthorizationRepository(db_path)
        self.user = IdentityPrincipal("user-001", "session-001", "device-001", "tenant-001")
        self.admin = IdentityPrincipal("admin", "session-admin", "device-admin", "tenant-001")
        repository.bootstrap_workspace(
            tenant_id="tenant-001", workspace_id="workspace-001", owner_user_id="user-001", owner_role=Role.PERSONAL_OWNER,
            workspace_kind="personal", data_area="cloud_sync", cost_limit_cents=1000, now=clock())
        authorization = AuthorizationService(repository=repository, audit_store=audit, clock=clock, identity_service=identity)
        self.identity, self.audit = identity, audit
        self.service = FakeService()
        self.dependencies = RuntimeDependencies(
            settings=RuntimeSettings.for_test(database_path=db_path, policy_version=POLICY_VERSION), identity_service=identity,
            authorization_service=authorization, audit_store=audit, identity_repository=identity_repository,
            authorization_repository=repository, studio_v2_service=SimpleNamespace(), tts_engine_service=self.service)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.dependencies)), base_url="http://127.0.0.1")
        self.cookies = {WEB_SESSION_COOKIE: "opaque"}
        self.key = {"Idempotency-Key": "tts-engine-key-000001"}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.dependencies.close()
        self.directory.cleanup()

    def as_(self, principal):
        return patch.object(self.identity, "describe_access", return_value=identity_session_view(principal))

    async def test_every_route_is_admin_only(self):
        match = {"If-Match": f'"tts-engine:{ENGINE_ID}:1"'}
        with self.as_(self.user):
            responses = [
                await self.client.get(BASE, cookies=self.cookies),
                await self.client.post(BASE, cookies=self.cookies, headers=self.key, json={"slug": "a", "label": "A", "base_url": "https://tts.example.com", "voices": {"A": "F1", "B": "M1"}}),
                await self.client.post(f"{BASE}/{ENGINE_ID}/verify", cookies=self.cookies, json={}),
                await self.client.patch(f"{BASE}/{ENGINE_ID}", cookies=self.cookies, headers=match, json={"label": "x"}),
                await self.client.delete(f"{BASE}/{ENGINE_ID}", cookies=self.cookies),
            ]
        self.assertEqual([r.status_code for r in responses], [403] * 5)
        self.assertEqual(self.service.calls, [])

    async def test_admin_flow_and_responses_never_carry_a_key(self):
        spec = {"slug": "supertonic", "label": "Supertonic", "base_url": "https://tts.example.com", "api_key": "secret-key-12345", "voices": {"A": "F1", "B": "M1"}}
        with self.as_(self.admin):
            listed = await self.client.get(BASE, cookies=self.cookies)
            created = await self.client.post(BASE, cookies=self.cookies, headers=self.key, json=spec)
            verified = await self.client.post(f"{BASE}/{ENGINE_ID}/verify", cookies=self.cookies, json={})
            patched = await self.client.patch(f"{BASE}/{ENGINE_ID}", cookies=self.cookies, headers={"If-Match": f'"tts-engine:{ENGINE_ID}:3"'},
                                              json={"is_default": True, "api_key": "another-secret-1"})
            deleted = await self.client.delete(f"{BASE}/{ENGINE_ID}", cookies=self.cookies)
        self.assertEqual([r.status_code for r in (listed, created, verified, patched, deleted)], [200, 201, 200, 200, 204])
        self.assertEqual([e["source"] for e in listed.json()["data"]["engines"]], ["settings", "deployment"])
        self.assertEqual(created.headers["etag"], f'"tts-engine:{ENGINE_ID}:1"')
        self.assertEqual(verified.headers["etag"], f'"tts-engine:{ENGINE_ID}:2"')
        self.assertEqual(patched.headers["etag"], f'"tts-engine:{ENGINE_ID}:4"')
        for response in (listed, created, verified, patched):
            self.assertNotIn("secret-key", response.text)
            self.assertNotIn("api_key", response.text)
        self.assertEqual(self.service.calls[1][2], spec)                                    # 서비스가 받은 본문(키는 서비스에서 바로 암호화된다)
        self.assertEqual(self.service.calls[3][2:], (ENGINE_ID, {"is_default": True, "api_key": "another-secret-1"}, 3))
        for event in self.audit.events() if hasattr(self.audit, "events") else []:
            self.assertNotIn("secret-key", str(event))

    async def test_input_checks(self):
        spec = {"slug": "a", "label": "A", "base_url": "https://tts.example.com", "voices": {"A": "F1", "B": "M1"}}
        match = {"If-Match": f'"tts-engine:{ENGINE_ID}:1"'}
        with self.as_(self.admin):
            no_key = await self.client.post(BASE, cookies=self.cookies, json=spec)
            extra = await self.client.post(BASE, cookies=self.cookies, headers=self.key, json={**spec, "unknown": 1})
            bad_timeout = await self.client.post(BASE, cookies=self.cookies, headers=self.key, json={**spec, "timeout_seconds": 3})
            short_key = await self.client.post(BASE, cookies=self.cookies, headers=self.key, json={**spec, "api_key": "short"})
            bad_id = await self.client.post(f"{BASE}/not-an-id/verify", cookies=self.cookies, json={})
            no_etag = await self.client.patch(f"{BASE}/{ENGINE_ID}", cookies=self.cookies, json={"label": "x"})
            bad_etag = await self.client.patch(f"{BASE}/{ENGINE_ID}", cookies=self.cookies, headers={"If-Match": "W/1"}, json={"label": "x"})
            other_etag = await self.client.patch(f"{BASE}/{ENGINE_ID}", cookies=self.cookies, headers={"If-Match": '"tts-engine:te-' + "c" * 32 + ':1"'}, json={"label": "x"})
            empty = await self.client.patch(f"{BASE}/{ENGINE_ID}", cookies=self.cookies, headers=match, json={})
            query = await self.client.get(BASE + "?x=1", cookies=self.cookies)
        self.assertTrue(all(r.status_code in (400, 422) for r in (no_key, extra, bad_timeout, short_key, bad_id, no_etag, bad_etag, other_etag, empty, query)),
                        [r.status_code for r in (no_key, extra, bad_timeout, short_key, bad_id, no_etag, bad_etag, other_etag, empty, query)])
        self.assertEqual(self.service.calls, [])

    async def test_generation_types_follow_the_tenant_engine_configuration(self):
        """화면에서 등록한 엔진이 생성 설정의 선택지가 되고, 엔진이 없으면 오디오 타일은 비활성이다."""
        from daon2_user_api.tts_engines import TtsConfig, TtsEngine
        engines = {slug: TtsEngine(slug, slug.title(), f"https://{slug}.example.com", "k" * 8, "external_api", "ko", 120.0, {"A": "F1", "B": "M1"}, ("F1", "F2", "M1"), source="settings")
                   for slug in ("supertonic", "qwen")}
        types_url = "/api/v1/workspaces/workspace-001/notebooks/notebook-001/studio/types"
        self.service.config = TtsConfig(engines, "supertonic", 600.0)
        with self.as_(self.user):
            on = await self.client.get(types_url, cookies=self.cookies)
            self.service.config = None
            off = await self.client.get(types_url, cookies=self.cookies)
        audio = {t["type_id"]: t for t in on.json()["data"]["types"]}["audio_overview"]
        self.assertTrue(audio["available"])
        self.assertEqual(audio["settings_schema"]["properties"]["engine"]["enum"], ["supertonic", "qwen"])
        self.assertEqual(audio["settings_schema"]["properties"]["engine"]["default"], "supertonic")
        self.assertEqual(audio["settings_schema"]["properties"]["voice_a"]["enum"], ["F1", "F2", "M1"])
        self.assertFalse({t["type_id"]: t for t in off.json()["data"]["types"]}["audio_overview"]["available"])
        self.assertEqual(self.service.resolved, ["tenant-001", "tenant-001"])
        self.assertNotIn("kkkkkkkk", on.text)             # 엔진 키는 생성 설정 응답에 없다

    async def test_service_errors_become_public_codes(self):
        match = {"If-Match": f'"tts-engine:{ENGINE_ID}:1"'}
        spec = {"slug": "a", "label": "A", "base_url": "https://tts.example.com", "voices": {"A": "F1", "B": "M1"}}
        cases = (("TTS_ENGINE_SLUG_EXISTS", 409), ("TTS_ENGINE_NOT_FOUND", 404), ("TTS_ENGINE_ENDPOINT_PRIVATE_DENIED", 403), ("TTS_ENGINE_VERSION_CONFLICT", 409))
        for code, status in cases:
            self.service.fail = (code, status)
            with self.subTest(code=code), self.as_(self.admin):
                response = await self.client.post(BASE, cookies=self.cookies, headers=self.key, json=spec)
            self.assertEqual((response.status_code, response.json()["error"]["code"]), (status, code))
        self.service.fail = ("SOMETHING_INTERNAL_DETAIL", 400)
        with self.as_(self.admin):
            hidden = await self.client.patch(f"{BASE}/{ENGINE_ID}", cookies=self.cookies, headers=match, json={"label": "x"})
        self.assertEqual(hidden.json()["error"]["code"], "INVALID_REQUEST")        # 내부 코드는 밖으로 나가지 않는다


if __name__ == "__main__":
    unittest.main()
