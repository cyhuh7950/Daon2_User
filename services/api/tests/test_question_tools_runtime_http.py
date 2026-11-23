"""질문 도구: HTTP 경로·권한·오류 코드·감사(WO-N1 NB2-F1)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from daon2_user_api.audit import AuditEventStore
from daon2_user_api.authorization import Action, AuthorizationError, AuthorizationService, Role, SqliteAuthorizationRepository
from daon2_user_api.identity import IdentityPrincipal
from daon2_user_api.question_tools import QuestionToolsService, register_question_tools_routes
from daon2_user_api.runtime import WEB_SESSION_COOKIE, RuntimeDependencies, RuntimeSettings, create_app
from test_identity_support import POLICY_VERSION, create_service, identity_session_view
from test_question_tools import FakeConnectors, FakeDb

PATH = "/api/v1/workspaces/workspace-001/notebooks/notebook-1/question-tools"


class QuestionToolsRuntimeHttpTests(unittest.IsolatedAsyncioTestCase):
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
        self.identity, self.audit = identity, audit
        settings = RuntimeSettings.for_test(database_path=db_path, policy_version=POLICY_VERSION)
        self.dependencies = RuntimeDependencies(
            settings=settings, identity_service=identity, authorization_service=self.authorization, audit_store=audit,
            identity_repository=identity_repository, authorization_repository=repository)
        app = create_app(self.dependencies)
        self.db = FakeDb()
        register_question_tools_routes(app, self.dependencies, QuestionToolsService(self.db, FakeConnectors()))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")
        self.cookies = {WEB_SESSION_COOKIE: "opaque"}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.dependencies.close()
        self.directory.cleanup()

    def authenticated(self):
        return patch.object(self.identity, "describe_access", return_value=identity_session_view(self.principal))

    def events(self):
        return [event for event in self.audit._events if event.action == "notebook.question_tools.update"]

    async def test_get_and_put_round_trip_with_audit_of_enabled_ids_only(self):
        with self.authenticated():
            got = await self.client.get(PATH, cookies=self.cookies)
            put = await self.client.put(PATH, cookies=self.cookies, json={"enabled": {"connector:kc-rag": False}})
            again = await self.client.get(PATH, cookies=self.cookies)
        self.assertEqual((got.status_code, put.status_code, again.status_code), (200, 200, 200))
        self.assertEqual(got.headers["cache-control"], "no-store")
        self.assertTrue(got.headers["etag"])
        self.assertEqual(put.headers["etag"], again.headers["etag"])
        self.assertNotEqual(got.headers["etag"], put.headers["etag"])
        self.assertEqual([item["id"] for item in got.json()["data"]["tools"]],
                         ["approved_knowledge", "connector:kc-rag", "connector:kc-daon2", "connector:kc-law"])
        self.assertEqual(put.json()["data"], again.json()["data"])
        self.assertFalse(next(t for t in put.json()["data"]["tools"] if t["id"] == "connector:kc-rag")["enabled"])
        self.assertEqual(put.json()["meta"]["workspace_id"], "workspace-001")
        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].target_type, events[0].target_id), ("notebook", "notebook-1"))
        self.assertEqual(list(events[0].metadata["enabled"]), ["approved_knowledge", "connector:kc-daon2"])
        # 저장 키는 인증된 사용자 기준이다.
        self.assertEqual(list(self.db.rows), [("notebook-1", "user-001")])

    async def test_view_permission_is_enough(self):
        original, seen = self.authorization.authorize_action, []

        def viewer(**kwargs):
            seen.append(kwargs["action"])
            if kwargs["action"] is not Action.VIEW:
                raise AuthorizationError("ACTION_DENIED", 403)
            return original(**kwargs)

        with self.authenticated(), patch.object(self.authorization, "authorize_action", side_effect=viewer):
            got = await self.client.get(PATH, cookies=self.cookies)
            put = await self.client.put(PATH, cookies=self.cookies, json={"enabled": {"approved_knowledge": False}})
        self.assertEqual((got.status_code, put.status_code), (200, 200))
        self.assertEqual(seen, [Action.VIEW, Action.VIEW])

    async def test_denied_workspace_gets_403_and_nothing_is_saved(self):
        with self.authenticated(), patch.object(self.authorization, "authorize_action", side_effect=AuthorizationError("ACTION_DENIED", 403)):
            put = await self.client.put(PATH, cookies=self.cookies, json={"enabled": {"approved_knowledge": False}})
        self.assertEqual(put.status_code, 403)
        self.assertEqual((self.db.rows, self.events()), ({}, []))

    async def test_unknown_tool_is_422_without_audit(self):
        with self.authenticated():
            response = await self.client.put(PATH, cookies=self.cookies, json={"enabled": {"web": True}})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (422, "QUESTION_TOOL_UNKNOWN"))
        self.assertEqual((self.db.rows, self.events()), ({}, []))

    async def test_unknown_notebook_is_404(self):
        with self.authenticated():
            response = await self.client.get(PATH.replace("notebook-1", "notebook-x"), cookies=self.cookies)
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (404, "NOTEBOOK_NOT_FOUND"))

    async def test_bad_inputs_are_rejected(self):
        with self.authenticated():
            not_bool = await self.client.put(PATH, cookies=self.cookies, json={"enabled": {"approved_knowledge": 1}})
            extra = await self.client.put(PATH, cookies=self.cookies, json={"enabled": {}, "x": 1})
            query = await self.client.get(PATH + "?x=1", cookies=self.cookies)
            bad_id = await self.client.get(PATH.replace("notebook-1", "bad id"), cookies=self.cookies)
        for response in (not_bool, extra, query, bad_id):
            self.assertIn(response.status_code, {400, 422})
        self.assertEqual(self.db.rows, {})


if __name__ == "__main__":
    unittest.main()
