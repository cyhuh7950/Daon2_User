"""노트북 개요: HTTP 경로·권한·응답 상태·오류 코드(WO-N1 NB2-F2)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from daon2_user_api.audit import AuditEventStore
from daon2_user_api.authorization import Action, AuthorizationError, AuthorizationService, Role, SqliteAuthorizationRepository
from daon2_user_api.identity import IdentityPrincipal
from daon2_user_api.notebook_overview import NotebookOverviewService, register_notebook_overview_routes
from daon2_user_api.runtime import WEB_SESSION_COOKIE, RuntimeDependencies, RuntimeSettings, create_app
from test_identity_support import POLICY_VERSION, create_service, identity_session_view
from test_notebook_overview import FakeDb

PATH = "/api/v1/workspaces/workspace-001/notebooks/notebook-1/overview"
KEYS = ["state", "summary", "questions", "citations", "stale", "generated_at", "error_code"]


class NotebookOverviewRuntimeHttpTests(unittest.IsolatedAsyncioTestCase):
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
        settings = RuntimeSettings.for_test(database_path=db_path, policy_version=POLICY_VERSION)
        self.dependencies = RuntimeDependencies(
            settings=settings, identity_service=identity, authorization_service=self.authorization, audit_store=audit,
            identity_repository=identity_repository, authorization_repository=repository)
        app = create_app(self.dependencies)
        self.db = FakeDb()
        register_notebook_overview_routes(app, self.dependencies, NotebookOverviewService(self.db))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")
        self.cookies = {WEB_SESSION_COOKIE: "opaque"}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.dependencies.close()
        self.directory.cleanup()

    def authenticated(self):
        return patch.object(self.identity, "describe_access", return_value=identity_session_view(self.principal))

    def key(self, notebook="notebook-1"):
        return ("tenant-001", "workspace-001", notebook)

    async def test_get_auto_queues_once_and_regenerate_conflicts_while_queued(self):
        with self.authenticated():
            got = await self.client.get(PATH, cookies=self.cookies)
            again = await self.client.get(PATH, cookies=self.cookies)
            regen = await self.client.post(PATH + "/regenerate", cookies=self.cookies, json={})
        self.assertEqual((got.status_code, again.status_code), (200, 200))
        self.assertEqual(got.headers["cache-control"], "no-store")
        self.assertTrue(got.headers["etag"])
        self.assertEqual(got.headers["etag"], again.headers["etag"])
        self.assertEqual(list(got.json()["data"]), KEYS)
        self.assertEqual(got.json()["data"]["state"], "queued")
        self.assertEqual(got.json()["meta"]["workspace_id"], "workspace-001")
        self.assertEqual(self.db.rows[self.key()]["requested_by"], "user-001")
        self.assertEqual((regen.status_code, regen.json()["error"]["code"]), (409, "OVERVIEW_IN_PROGRESS"))

    async def test_none_without_ready_sources(self):
        with self.authenticated():
            got = await self.client.get(PATH.replace("notebook-1", "notebook-2"), cookies=self.cookies)
            regen = await self.client.post(PATH.replace("notebook-1", "notebook-2") + "/regenerate", cookies=self.cookies, json={})
        self.assertEqual((got.status_code, got.json()["data"]["state"]), (200, "none"))
        self.assertEqual((regen.status_code, regen.json()["error"]["code"]), (409, "OVERVIEW_NO_READY_SOURCE"))
        self.assertEqual(self.db.rows, {})

    async def test_regenerate_finished_overview_is_202(self):
        with self.authenticated():
            await self.client.get(PATH, cookies=self.cookies)
            self.db.rows[self.key()]["state"] = "failed"
            regen = await self.client.post(PATH + "/regenerate", cookies=self.cookies, json={})
        self.assertEqual((regen.status_code, regen.json()["data"]["state"]), (202, "queued"))
        self.assertEqual(regen.headers["cache-control"], "no-store")
        self.assertTrue(regen.headers["etag"])

    async def test_get_needs_view_and_regenerate_needs_edit(self):
        original, seen = self.authorization.authorize_action, []

        def viewer(**kwargs):
            seen.append(kwargs["action"])
            if kwargs["action"] is not Action.VIEW:
                raise AuthorizationError("ACTION_DENIED", 403)
            return original(**kwargs)

        with self.authenticated(), patch.object(self.authorization, "authorize_action", side_effect=viewer):
            got = await self.client.get(PATH, cookies=self.cookies)
            self.db.rows[self.key()]["state"] = "ready"
            regen = await self.client.post(PATH + "/regenerate", cookies=self.cookies, json={})
        self.assertEqual((got.status_code, regen.status_code), (200, 403))
        self.assertEqual(seen, [Action.VIEW, Action.EDIT])
        self.assertEqual(self.db.rows[self.key()]["state"], "ready")

    async def test_denied_workspace_gets_403_and_nothing_is_created(self):
        with self.authenticated(), patch.object(self.authorization, "authorize_action", side_effect=AuthorizationError("ACTION_DENIED", 403)):
            got = await self.client.get(PATH, cookies=self.cookies)
        self.assertEqual(got.status_code, 403)
        self.assertEqual(self.db.rows, {})

    async def test_unknown_notebook_is_404_and_db_failure_is_503(self):
        with self.authenticated():
            missing = await self.client.get(PATH.replace("notebook-1", "notebook-x"), cookies=self.cookies)
            self.db.fail = True
            down = await self.client.get(PATH, cookies=self.cookies)
        self.assertEqual((missing.status_code, missing.json()["error"]["code"]), (404, "NOTEBOOK_NOT_FOUND"))
        self.assertEqual((down.status_code, down.json()["error"]["code"]), (503, "OVERVIEW_UNAVAILABLE"))

    async def test_bad_inputs_are_rejected(self):
        with self.authenticated():
            query = await self.client.get(PATH + "?x=1", cookies=self.cookies)
            bad_id = await self.client.get(PATH.replace("notebook-1", "bad id"), cookies=self.cookies)
            method = await self.client.delete(PATH, cookies=self.cookies)
        self.assertIn(query.status_code, {400, 422})
        self.assertIn(bad_id.status_code, {400, 404, 422})
        self.assertIn(method.status_code, {404, 405})
        self.assertEqual(self.db.rows, {})

    async def test_unauthenticated_is_401(self):
        response = await self.client.get(PATH)
        self.assertEqual(response.status_code, 401)


class NotebookOverviewRegistrationTests(unittest.TestCase):
    def test_runtime_opens_overview_routes_only_with_studio_v2_and_cloud_store(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "runtime.sqlite3"
            audit = AuditEventStore()
            identity, identity_repository, _, clock = create_service(db_path, audit_store=audit)
            repository = SqliteAuthorizationRepository(db_path)
            authorization = AuthorizationService(repository=repository, audit_store=audit, clock=clock, identity_service=identity)
            found = []
            for extra in ({"studio_v2_service": object()}, {}):
                dependencies = RuntimeDependencies(
                    settings=RuntimeSettings.for_test(database_path=db_path, policy_version=POLICY_VERSION), identity_service=identity,
                    authorization_service=authorization, audit_store=audit, identity_repository=identity_repository,
                    authorization_repository=repository, cloud_store=FakeDb(), knowledge_connector_service=object(), **extra)
                app = create_app(dependencies)
                found.append(sorted((method, route.path) for route in app.routes for method in getattr(route, "methods", ())
                                    if "/overview" in getattr(route, "path", "")))
                dependencies.close()
        self.assertEqual(found[0], [("GET", "/api/v1/workspaces/{id}/notebooks/{notebook_id}/overview"),
                                    ("POST", "/api/v1/workspaces/{id}/notebooks/{notebook_id}/overview/regenerate")])
        self.assertEqual(found[1], [])


if __name__ == "__main__":
    unittest.main()
