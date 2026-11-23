"""메모를 소스로: HTTP 경로·권한·오류 코드·감사·응답 위치(WO-N1 NB1-F2)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from daon2_user_api.audit import AuditEventStore
from daon2_user_api.authorization import Action, AuthorizationError, AuthorizationService, Role, SqliteAuthorizationRepository
from daon2_user_api.identity import IdentityPrincipal
from daon2_user_api.runtime import WEB_SESSION_COOKIE, RuntimeDependencies, RuntimeSettings, create_app
from daon2_user_api.studio_report import WorkspaceSourceProjection
from daon2_user_api.studio_workspace import StudioError
from test_identity_support import POLICY_VERSION, create_service, identity_session_view
from test_studio_v2_runtime_http import FakeV2

BASE = "/api/v1/workspaces/workspace-001/notebooks/notebook-001/studio"
OID = "sv2-" + "a" * 32


class FakeMemoSources:
    def __init__(self):
        self.calls: list[tuple] = []
        self.fail = None

    def _record(self, *call):
        self.calls.append(call)
        if self.fail:
            raise StudioError(*self.fail)

    def create(self, ctx, output_id):
        self._record("create", ctx, output_id)
        return {"source_id": "src-memo", "source_version_id": "sv-memo-1", "state": "processing", "revision_no": 3}

    def reflect(self, ctx, output_id):
        self._record("reflect", ctx, output_id)
        return {"source_id": "src-memo", "source_version_id": "sv-memo-2", "revision_no": 4}

    def source_link(self, ctx, output_id, current_revision):
        self._record("link", ctx, output_id, current_revision)
        return {"source_id": "src-memo", "reflected_revision_no": 3, "outdated": True}

    def memo_origins(self, ctx):
        self._record("origins", ctx)
        return {"src-memo": {"memo_output_id": OID, "memo_exists": False}}


class MemoV2(FakeV2):
    def __init__(self, type_id="memo"):
        super().__init__()
        self.type_id = type_id

    def get_output(self, ctx, output_id, revision=None):
        self._record("get", ctx, output_id, revision)
        return {"output_id": output_id, "updated_at": "2026-10-20T00:00:00+00:00", "type_id": self.type_id, "current_revision": 4,
                "stale": False}


class MemoSourceRuntimeHttpTests(unittest.IsolatedAsyncioTestCase):
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
        self.authorization = AuthorizationService(repository=repository, audit_store=audit, clock=clock, identity_service=identity)
        self.identity = identity
        self.audit = audit
        self.v2 = MemoV2()
        self.memo = FakeMemoSources()
        settings = RuntimeSettings.for_test(database_path=db_path, policy_version=POLICY_VERSION)
        self.dependencies = RuntimeDependencies(
            settings=settings, identity_service=identity, authorization_service=self.authorization, audit_store=audit,
            identity_repository=identity_repository, authorization_repository=repository, studio_v2_service=self.v2,
            memo_source_service=self.memo)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.dependencies)), base_url="http://127.0.0.1")
        self.cookies = {WEB_SESSION_COOKIE: "opaque"}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.dependencies.close()
        self.directory.cleanup()

    def authenticated(self):
        return patch.object(self.identity, "describe_access", return_value=identity_session_view(self.principal))

    def events(self, action):
        return [event for event in self.audit._events if event.action == action]

    async def test_create_and_reflect_routes(self):
        with self.authenticated():
            created = await self.client.post(BASE + f"/outputs/{OID}/source", cookies=self.cookies, json={})
            reflected = await self.client.post(BASE + f"/outputs/{OID}/source/reflect", cookies=self.cookies, json={})
        self.assertEqual((created.status_code, reflected.status_code), (201, 200))
        self.assertEqual(created.json()["data"], {"source_id": "src-memo", "source_version_id": "sv-memo-1", "state": "processing"})
        self.assertEqual(reflected.json()["data"], {"source_id": "src-memo", "source_version_id": "sv-memo-2"})
        self.assertEqual([c[0] for c in self.memo.calls], ["create", "reflect"])
        self.assertEqual(self.memo.calls[0][1].notebook_id, "notebook-001")

    async def test_audit_records_only_ids_and_revisions(self):
        with self.authenticated():
            await self.client.post(BASE + f"/outputs/{OID}/source", cookies=self.cookies, json={})
            await self.client.post(BASE + f"/outputs/{OID}/source/reflect", cookies=self.cookies, json={})
        created, reflected = self.events("studio.memo.source_created"), self.events("studio.memo.source_reflected")
        self.assertEqual((len(created), len(reflected)), (1, 1))
        self.assertEqual(created[0].target_id, OID)
        self.assertEqual(dict(created[0].metadata), {"notebook_id": "notebook-001", "source_id": "src-memo",
                                                     "source_version_id": "sv-memo-1", "revision_no": 3})
        self.assertEqual(dict(reflected[0].metadata), {"notebook_id": "notebook-001", "source_id": "src-memo",
                                                       "source_version_id": "sv-memo-2", "revision_no": 4})

    async def test_create_and_reflect_require_edit_and_viewer_gets_403(self):
        original = self.authorization.authorize_action
        seen = []

        def viewer(**kwargs):
            seen.append(kwargs["action"])
            if kwargs["action"] is not Action.VIEW:
                raise AuthorizationError("ACTION_DENIED", 403)
            return original(**kwargs)

        with self.authenticated(), patch.object(self.authorization, "authorize_action", side_effect=viewer):
            created = await self.client.post(BASE + f"/outputs/{OID}/source", cookies=self.cookies, json={})
            reflected = await self.client.post(BASE + f"/outputs/{OID}/source/reflect", cookies=self.cookies, json={})
            got = await self.client.get(BASE + f"/outputs/{OID}", cookies=self.cookies)
        self.assertEqual([r.status_code for r in (created, reflected, got)], [403, 403, 200])
        self.assertEqual(seen, [Action.EDIT, Action.EDIT, Action.VIEW])
        self.assertEqual([c[0] for c in self.memo.calls], ["link"])
        self.assertEqual(self.events("studio.memo.source_created"), [])

    async def test_memo_detail_carries_source_link(self):
        with self.authenticated():
            got = await self.client.get(BASE + f"/outputs/{OID}", cookies=self.cookies)
        self.assertEqual(got.json()["data"]["source_link"], {"source_id": "src-memo", "reflected_revision_no": 3, "outdated": True})
        self.assertEqual(self.memo.calls[-1][2:], (OID, 4))

    async def test_non_memo_detail_has_no_source_link(self):
        self.v2.type_id = "report"
        with self.authenticated():
            got = await self.client.get(BASE + f"/outputs/{OID}", cookies=self.cookies)
        self.assertNotIn("source_link", got.json()["data"])
        self.assertEqual(self.memo.calls, [])

    async def test_error_codes_are_public(self):
        for code, status in (("STUDIO_OUTPUT_NOT_FOUND", 404), ("OUTPUT_NOT_MEMO", 422), ("MEMO_SOURCE_EXISTS", 409),
                             ("MEMO_EMPTY", 422), ("MEMO_SOURCE_NOT_LINKED", 404), ("MEMO_SOURCE_UNCHANGED", 409),
                             ("MEMO_TOO_LARGE", 413), ("SOURCE_PROCESSING_ACTIVE", 409)):
            self.memo.fail = (code, status)
            with self.subTest(code=code), self.authenticated():
                path = BASE + f"/outputs/{OID}/source" + ("/reflect" if code in {"MEMO_SOURCE_NOT_LINKED", "MEMO_SOURCE_UNCHANGED"} else "")
                response = await self.client.post(path, cookies=self.cookies, json={})
                self.assertEqual((response.status_code, response.json()["error"]["code"]), (status, code))
        self.assertEqual(self.events("studio.memo.source_created"), [])

    async def test_bad_output_id_and_unknown_body_are_rejected(self):
        with self.authenticated():
            bad = await self.client.post(BASE + "/outputs/bad id/source", cookies=self.cookies, json={})
            extra = await self.client.post(BASE + f"/outputs/{OID}/source", cookies=self.cookies, json={"x": 1})
            query = await self.client.post(BASE + f"/outputs/{OID}/source?x=1", cookies=self.cookies, json={})
        self.assertEqual([r.status_code for r in (bad, extra, query)], [400, 400, 400])
        self.assertEqual(self.memo.calls, [])

    async def test_source_list_marks_memo_sources_only(self):
        sources = (WorkspaceSourceProjection("src-memo", "sv-memo-1", "회의 메모.txt", "ready", "completed", "completed"),
                   WorkspaceSourceProjection("src-pdf", "sv-pdf-1", "a.pdf", "ready", "completed", "completed"))
        self.dependencies.studio_report_repository = SimpleNamespace(list_sources=lambda ctx: sources)
        notebook = SimpleNamespace(read_selected_context=lambda ctx, nid: SimpleNamespace(
            sources=(("src-memo", "sv-memo-1"), ("src-pdf", "sv-pdf-1")), etag='"notebook-binding:1"'), get=lambda *a: None)
        self.dependencies.notebook_service = notebook
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.dependencies)), base_url="http://127.0.0.1")
        try:
            with self.authenticated():
                listed = await client.get("/api/v1/workspaces/workspace-001/sources?notebook_id=notebook-001", cookies=self.cookies)
        finally:
            await client.aclose()
        self.assertEqual(listed.status_code, 200)
        memo, pdf = listed.json()["data"]["sources"]
        self.assertEqual(memo["memo_origin"], {"memo_output_id": OID, "memo_exists": False})
        self.assertNotIn("memo_origin", pdf)
        self.assertEqual(len(pdf), 6)
        self.assertEqual(self.memo.calls[-1][1].notebook_id, "notebook-001")


    async def test_source_list_still_works_when_memo_links_cannot_be_read(self):
        """0084 적용 전 DB 등에서 연결을 못 읽어도 소스 목록 자체는 기존 그대로 나온다."""
        from daon2_user_api.cloud_storage import CloudDatabaseError
        source = WorkspaceSourceProjection("src-pdf", "sv-pdf-1", "a.pdf", "ready", "completed", "completed")
        self.dependencies.studio_report_repository = SimpleNamespace(list_sources=lambda ctx: (source,))
        self.dependencies.notebook_service = SimpleNamespace(read_selected_context=lambda ctx, nid: SimpleNamespace(
            sources=(("src-pdf", "sv-pdf-1"),), etag='"notebook-binding:1"'), get=lambda *a: None)

        def broken(ctx):
            raise CloudDatabaseError("DATABASE_UNAVAILABLE", retryable=True)

        self.memo.memo_origins = broken
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.dependencies)), base_url="http://127.0.0.1")
        try:
            with self.authenticated():
                listed = await client.get("/api/v1/workspaces/workspace-001/sources?notebook_id=notebook-001", cookies=self.cookies)
        finally:
            await client.aclose()
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["data"]["sources"][0]), 6)


    async def test_memo_detail_still_works_when_memo_link_cannot_be_read(self):
        from daon2_user_api.cloud_storage import CloudDatabaseError

        def broken(ctx, output_id, current_revision):
            raise CloudDatabaseError("DATABASE_UNAVAILABLE", retryable=True)

        self.memo.source_link = broken
        with self.authenticated():
            got = await self.client.get(BASE + f"/outputs/{OID}", cookies=self.cookies)
        self.assertEqual(got.status_code, 200)
        self.assertIsNone(got.json()["data"]["source_link"])


if __name__ == "__main__":
    unittest.main()
