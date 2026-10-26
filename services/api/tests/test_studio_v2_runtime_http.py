from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from daon2_user_api.audit import AuditEventStore
from daon2_user_api.authorization import AuthorizationService, Role, SqliteAuthorizationRepository
from daon2_user_api.identity import IdentityPrincipal
from daon2_user_api.runtime import WEB_SESSION_COOKIE, RuntimeDependencies, RuntimeSettings, create_app
from daon2_user_api.studio_v2_export import StudioV2Export
from daon2_user_api.studio_workspace import StudioError
from test_identity_support import POLICY_VERSION, create_service, identity_session_view

BASE = "/api/v1/workspaces/workspace-001/notebooks/notebook-001/studio"
OID = "sv2-" + "a" * 32


class FakeV2:
    def __init__(self):
        self.calls = []
        self.fail = None

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if self.fail:
            raise StudioError(*self.fail)

    def enqueue(self, ctx, request, key):
        self._record("enqueue", ctx, request, key)
        return {"output_id": OID, "job_id": "svj-1", "status": "queued", "replayed": False}

    def list_outputs(self, ctx, cursor=None, limit=25):
        self._record("list", ctx, cursor, limit)
        return {"items": [], "next_cursor": None}

    def get_video(self, ctx, output_id):
        self._record("video", ctx, output_id)
        return {"content": bytes(range(100)), "content_type": "video/mp4", "duration_ms": 4321, "sha256": "cd" * 32, "revision_no": 1}

    def get_audio(self, ctx, output_id):
        self._record("audio", ctx, output_id)
        return {"content": bytes(range(200)), "content_type": "audio/mpeg", "duration_ms": 1234, "sha256": "ab" * 32, "revision_no": 1}

    def get_output(self, ctx, output_id, revision=None):
        self._record("get", ctx, output_id, revision)
        return {"output_id": output_id, "updated_at": "2026-10-20T00:00:00+00:00", "type_id": "memo"}

    def rename(self, ctx, output_id, title, expected):
        self._record("rename", ctx, output_id, title, expected)
        return {"output_id": output_id, "title": title, "updated_at": "2026-10-20T01:00:00+00:00"}

    def soft_delete(self, ctx, output_id):
        self._record("delete", ctx, output_id)

    def request_cancel(self, ctx, output_id):
        self._record("cancel", ctx, output_id)
        return {"output_id": output_id, "cancel_requested": True}

    def export(self, ctx, output_id, fmt, revision):
        self._record("export", ctx, output_id, fmt, revision)
        return StudioV2Export(b"# memo", "text/markdown; charset=utf-8", "memo.md", "memo.md", "0" * 64)

    def provenance(self, ctx, output_id, revision=None):
        self._record("provenance", ctx, output_id, revision)
        return {"output_id": output_id, "revision_no": revision or 1, "instruction": {"focus": None, "customization_applied": True}, "sources": []}

    def get_customization(self, ctx):
        self._record("customization_get", ctx)
        return {"instruction": "", "version": 0}

    def save_customization(self, ctx, instruction, expected):
        self._record("customization_put", ctx, instruction, expected)
        return {"instruction": instruction, "version": expected + 1}


class StudioV2RuntimeHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        db_path = Path(self.directory.name) / "runtime.sqlite3"
        audit = AuditEventStore()
        identity, identity_repository, _, clock = create_service(db_path, audit_store=audit)
        repository = SqliteAuthorizationRepository(db_path)
        self.principal = IdentityPrincipal("user-001", "session-001", "device-001", "tenant-001")
        repository.bootstrap_workspace(
            tenant_id="tenant-001", workspace_id="workspace-001", owner_user_id="user-001", owner_role=Role.PERSONAL_OWNER,
            workspace_kind="personal", data_area="cloud_sync", cost_limit_cents=1000, now=clock())
        authorization = AuthorizationService(repository=repository, audit_store=audit, clock=clock, identity_service=identity)
        self.identity = identity
        self.audit = audit
        self.v2 = FakeV2()
        settings = RuntimeSettings.for_test(database_path=db_path, policy_version=POLICY_VERSION)
        self.dependencies = RuntimeDependencies(
            settings=settings, identity_service=identity, authorization_service=authorization, audit_store=audit,
            identity_repository=identity_repository, authorization_repository=repository, studio_v2_service=self.v2)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.dependencies)), base_url="http://127.0.0.1")
        self.cookies = {WEB_SESSION_COOKIE: "opaque"}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.dependencies.close()
        self.directory.cleanup()

    def authenticated(self):
        return patch.object(self.identity, "describe_access", return_value=identity_session_view(self.principal))

    async def test_types_create_list_get_rename_delete_cancel_export(self):
        key = {"Idempotency-Key": "studio-v2-key-000001"}
        match = {"If-Match": '"studio-v2:' + OID + ':2026-10-20T00:00:00+00:00"'}
        with self.authenticated():
            types = await self.client.get(BASE + "/types", cookies=self.cookies)
            created = await self.client.post(BASE + "/outputs", cookies=self.cookies, headers=key, json={"type_id": "report"})
            listed = await self.client.get(BASE + "/outputs?limit=10", cookies=self.cookies)
            got = await self.client.get(BASE + "/outputs/" + OID + "?revision=2", cookies=self.cookies)
            renamed = await self.client.patch(BASE + "/outputs/" + OID, cookies=self.cookies, json={"title": "새 제목"}, headers=match)
            cancelled = await self.client.post(BASE + "/outputs/" + OID + "/cancel", cookies=self.cookies, json={})
            exported = await self.client.get(BASE + "/outputs/" + OID + "/exports/md", cookies=self.cookies)
            deleted = await self.client.delete(BASE + "/outputs/" + OID, cookies=self.cookies)
        self.assertEqual([r.status_code for r in (types, created, listed, got, renamed, cancelled, exported, deleted)],
                         [200, 202, 200, 200, 200, 202, 200, 204])
        self.assertEqual(len(types.json()["data"]["types"]), 11)
        self.assertEqual(created.json()["data"], {"output_id": OID, "job_id": "svj-1", "status": "queued"})
        self.assertEqual(self.v2.calls[0][2], {"type_id": "report"})
        self.assertEqual(self.v2.calls[2][3], 2)
        self.assertEqual(self.v2.calls[3][4], "2026-10-20T00:00:00+00:00")
        self.assertEqual(exported.content, b"# memo")
        self.assertEqual(exported.headers["cache-control"], "no-store")
        self.assertIn("attachment", exported.headers["content-disposition"])

    async def test_audio_route_serves_mp3_with_single_range_support(self):
        with self.authenticated():
            full = await self.client.get(BASE + "/outputs/" + OID + "/audio", cookies=self.cookies)
            part = await self.client.get(BASE + "/outputs/" + OID + "/audio", cookies=self.cookies, headers={"Range": "bytes=10-19"})
            tail = await self.client.get(BASE + "/outputs/" + OID + "/audio", cookies=self.cookies, headers={"Range": "bytes=-5"})
            bad = await self.client.get(BASE + "/outputs/" + OID + "/audio", cookies=self.cookies, headers={"Range": "bytes=500-"})
            ignored = await self.client.get(BASE + "/outputs/" + OID + "/audio", cookies=self.cookies, headers={"Range": "items=1-2"})
            with_query = await self.client.get(BASE + "/outputs/" + OID + "/audio?x=1", cookies=self.cookies)
            self.v2.fail = ("RESOURCE_UNAVAILABLE", 404)
            missing = await self.client.get(BASE + "/outputs/" + OID + "/audio", cookies=self.cookies)
        self.assertEqual((full.status_code, len(full.content), full.headers["content-type"]), (200, 200, "audio/mpeg"))
        self.assertEqual(full.headers["accept-ranges"], "bytes")
        self.assertEqual(full.headers["x-media-duration-ms"], "1234")
        self.assertIn("no-store", full.headers["cache-control"])
        self.assertEqual((part.status_code, part.content, part.headers["content-range"]), (206, bytes(range(10, 20)), "bytes 10-19/200"))
        self.assertEqual((tail.status_code, tail.content), (206, bytes(range(195, 200))))
        self.assertEqual((bad.status_code, bad.headers["content-range"]), (416, "bytes */200"))
        self.assertEqual((ignored.status_code, len(ignored.content)), (200, 200))
        self.assertEqual(with_query.status_code, 400)
        self.assertEqual(missing.status_code, 404)

    async def test_video_route_serves_mp4_and_vtt_is_an_allowed_export_format(self):
        with self.authenticated():
            full = await self.client.get(BASE + "/outputs/" + OID + "/video", cookies=self.cookies)
            part = await self.client.get(BASE + "/outputs/" + OID + "/video", cookies=self.cookies, headers={"Range": "bytes=0-9"})
            vtt = await self.client.get(BASE + "/outputs/" + OID + "/exports/vtt", cookies=self.cookies)
        self.assertEqual((full.status_code, len(full.content), full.headers["content-type"]), (200, 100, "video/mp4"))
        self.assertEqual(full.headers["x-media-duration-ms"], "4321")
        self.assertEqual((part.status_code, part.headers["content-range"]), (206, "bytes 0-9/100"))
        self.assertNotEqual(vtt.status_code, 400)   # 형식 이름은 허용(유형 지원 여부는 서비스가 판단한다)

    async def test_sharing_is_notebook_scoped_and_provenance_hides_prompt_text(self):
        with self.authenticated():
            sharing = await self.client.get(BASE + "/outputs/" + OID + "/sharing", cookies=self.cookies)
            provenance = await self.client.get(BASE + "/outputs/" + OID + "/provenance?revision=2", cookies=self.cookies)
            bad_query = await self.client.get(BASE + "/outputs/" + OID + "/sharing?x=1", cookies=self.cookies)
        self.assertEqual(sharing.status_code, 200)
        self.assertEqual(sharing.json()["data"], {"scope": "notebook", "public_link": False, "notebook_id": "notebook-001"})
        self.assertEqual(provenance.status_code, 200)
        data = provenance.json()["data"]
        self.assertEqual(data["instruction"], {"focus": None, "customization_applied": True})
        self.assertNotIn("system_prompt", str(data))  # 시스템 프롬프트 원문은 응답에 없다
        self.assertEqual([c for c in self.v2.calls if c[0] == "provenance"][0][3], 2)
        self.assertEqual(bad_query.status_code, 400)

    async def test_export_requires_step_up_only_when_the_organization_enabled_it(self):
        url = BASE + "/outputs/" + OID + "/exports/md"
        with self.authenticated():
            before = await self.client.get(url, cookies=self.cookies)
        self.assertEqual(before.status_code, 200)  # 기본 설정: 추가 인증 없음
        self.dependencies.identity_repository.add_step_up_action("tenant-001", "studio_export_download")
        from daon2_user_api.identity import IdentityError
        calls = []

        def consume(**kwargs):
            calls.append(kwargs)
            if kwargs["step_up_authorization"] != "valid-grant":
                raise IdentityError("STEP_UP_REQUIRED", 403)

        with self.authenticated(), patch.object(self.identity, "consume_step_up", side_effect=consume):
            missing = await self.client.get(url, cookies=self.cookies)
            forged = await self.client.get(url, cookies=self.cookies, headers={"x-daon-step-up-authorization": "x" * 48})
            granted = await self.client.get(url, cookies=self.cookies, headers={"x-daon-step-up-authorization": "valid-grant"})
        self.assertEqual((missing.status_code, forged.status_code, granted.status_code), (403, 403, 200))
        self.assertEqual(missing.json()["error"]["code"], "STEP_UP_REQUIRED")
        self.assertEqual({(c["action_group"], c["target_id"]) for c in calls}, {("studio_export_download", OID)})
        self.assertEqual([c[0] for c in self.v2.calls].count("export"), 2)  # 거부된 두 요청은 렌더링까지 가지 않는다(앞선 1건 + 승인 1건)

    async def test_export_policy_admin_route_only_for_admins_and_cannot_be_turned_off(self):
        with self.authenticated():
            denied = await self.client.get("/api/v1/admin/export-policy", cookies=self.cookies)
        self.assertEqual(denied.status_code, 403)
        admin = IdentityPrincipal("admin", "session-admin", "device-admin", "tenant-001")
        with patch.object(self.identity, "describe_access", return_value=identity_session_view(admin)):
            before = await self.client.get("/api/v1/admin/export-policy", cookies=self.cookies)
            enabled = await self.client.put("/api/v1/admin/export-policy", cookies=self.cookies, json={"require_step_up": True})
            off = await self.client.put("/api/v1/admin/export-policy", cookies=self.cookies, json={"require_step_up": False})
            after = await self.client.get("/api/v1/admin/export-policy", cookies=self.cookies)
        self.assertEqual(before.json()["data"], {"require_step_up": False, "can_disable": False})
        self.assertEqual(enabled.json()["data"]["require_step_up"], True)
        self.assertEqual(off.status_code, 403)  # 조직 step-up 목록은 되돌릴 수 없다
        self.assertEqual(after.json()["data"]["require_step_up"], True)

    async def test_hidden_output_is_not_found_for_other_owners(self):
        self.v2.fail = ("RESOURCE_UNAVAILABLE", 404)
        with self.authenticated():
            got = await self.client.get(BASE + "/outputs/" + OID, cookies=self.cookies)
            sharing = await self.client.get(BASE + "/outputs/" + OID + "/sharing", cookies=self.cookies)
        self.assertEqual([got.status_code, sharing.status_code], [404, 404])

    async def test_user_without_workspace_access_is_forbidden_on_every_studio_route(self):
        """ST-T13: Notebook(Workspace) 권한이 없는 사용자는 조회·생성·내려받기 모두 403이고 서비스는 호출되지 않는다."""
        stranger = IdentityPrincipal("user-999", "session-999", "device-999", "tenant-001")
        key = {"Idempotency-Key": "studio-v2-key-000099"}
        with patch.object(self.identity, "describe_access", return_value=identity_session_view(stranger)):
            responses = [
                await self.client.get(BASE + "/types", cookies=self.cookies),
                await self.client.get(BASE + "/outputs", cookies=self.cookies),
                await self.client.get(BASE + "/outputs/" + OID, cookies=self.cookies),
                await self.client.get(BASE + "/outputs/" + OID + "/exports/md", cookies=self.cookies),
                await self.client.get(BASE + "/outputs/" + OID + "/audio", cookies=self.cookies),
                await self.client.post(BASE + "/outputs", cookies=self.cookies, headers=key, json={"type_id": "report"}),
                await self.client.delete(BASE + "/outputs/" + OID, cookies=self.cookies),
            ]
        self.assertEqual([r.status_code for r in responses], [403] * 7)
        self.assertEqual(self.v2.calls, [])

    async def test_validation_idempotency_and_unknown_fields(self):
        with self.authenticated():
            missing_key = await self.client.post(BASE + "/outputs", cookies=self.cookies, json={"type_id": "report"})
            extra = await self.client.post(BASE + "/outputs", cookies=self.cookies, headers={"Idempotency-Key": "studio-v2-key-000002"},
                                           json={"type_id": "report", "unexpected": 1})
            bad_query = await self.client.get(BASE + "/outputs?evil=1", cookies=self.cookies)
            bad_format = await self.client.get(BASE + "/outputs/sv2-1/exports/exe", cookies=self.cookies)
            bad_revision = await self.client.get(BASE + "/outputs/sv2-1?revision=abc", cookies=self.cookies)
        self.assertEqual([r.status_code for r in (missing_key, extra, bad_query, bad_format, bad_revision)], [400, 400, 400, 400, 400])
        self.assertEqual(self.v2.calls, [])

    async def test_unauthenticated_requests_are_rejected(self):
        response = await self.client.get(BASE + "/types")
        self.assertIn(response.status_code, (401, 403))

    async def test_studio_v2_error_codes_are_public(self):
        for code, status in (("STUDIO_NO_READY_SOURCE", 409), ("STUDIO_TYPE_UNAVAILABLE", 409), ("STUDIO_VERSION_CONFLICT", 409),
                             ("STUDIO_REVISION_TOO_LARGE", 413), ("EXPORT_FORMAT_UNSUPPORTED", 400), ("RESOURCE_UNAVAILABLE", 404)):
            self.v2.fail = (code, status)
            with self.authenticated():
                response = await self.client.post(BASE + "/outputs", cookies=self.cookies,
                                                  headers={"Idempotency-Key": "studio-v2-key-000003"}, json={"type_id": "report"})
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["error"]["code"], code)

    async def test_customization_etag_roundtrip(self):
        with self.authenticated():
            got = await self.client.get(BASE + "/customization", cookies=self.cookies)
            put = await self.client.put(BASE + "/customization", cookies=self.cookies, json={"instruction": "존댓말"},
                                        headers={"If-Match": got.headers["etag"]})
        self.assertEqual(got.headers["etag"], '"studio-v2-customization:notebook-001:0"')
        self.assertEqual(put.json()["data"], {"instruction": "존댓말", "version": 1})


if __name__ == "__main__":
    unittest.main()
