"""소스 묶음: HTTP 경로·권한·헤더·오류 코드·감사(WO-N1 NB3-F2, 결정 D-11)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from daon2_user_api.audit import AuditEventStore
from daon2_user_api.authorization import Action, AuthorizationError, AuthorizationService, Role, SqliteAuthorizationRepository
from daon2_user_api.identity import IdentityPrincipal
from daon2_user_api.runtime import WEB_SESSION_COOKIE, RuntimeDependencies, RuntimeSettings, create_app
from daon2_user_api.source_groups import SourceGroupsService, register_source_groups_routes
from test_identity_support import POLICY_VERSION, create_service, identity_session_view
from test_source_groups import FakeDb

BASE = "/api/v1/workspaces/workspace-001/notebooks/notebook-1/source-groups"


class SourceGroupsRuntimeHttpTests(unittest.IsolatedAsyncioTestCase):
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
        self.db.notebooks = {"notebook-1"}
        register_source_groups_routes(app, self.dependencies, SourceGroupsService(self.db))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")
        self.cookies = {WEB_SESSION_COOKIE: "opaque"}
        self.n = 0

    async def asyncTearDown(self):
        await self.client.aclose()
        self.dependencies.close()
        self.directory.cleanup()

    def authenticated(self):
        return patch.object(self.identity, "describe_access", return_value=identity_session_view(self.principal))

    def events(self):
        return [e for e in self.audit._events if e.action.startswith("notebook.source_group.")]

    def key(self):
        self.n += 1
        return {"Idempotency-Key": f"source-group-key-{self.n:08d}"}

    async def current(self):
        response = await self.client.get(BASE, cookies=self.cookies)
        return response.headers["etag"]

    async def test_full_round_trip_with_audit_ids_and_counts_only(self):
        with self.authenticated():
            empty = await self.client.get(BASE, cookies=self.cookies)
            created = await self.client.post(BASE, cookies=self.cookies, headers=self.key(), json={"name": "계약 조건"})
            gid = created.json()["data"]["group_id"]
            members = await self.client.put(f"{BASE}/{gid}/members", cookies=self.cookies,
                                            headers={"If-Match": created.headers["etag"]}, json={"source_ids": ["src-b", "src-a"]})
            renamed = await self.client.patch(f"{BASE}/{gid}", cookies=self.cookies,
                                              headers={"If-Match": members.headers["etag"]}, json={"name": "가격", "position": 0})
            listed = await self.client.get(BASE, cookies=self.cookies)
            deleted = await self.client.delete(f"{BASE}/{gid}", cookies=self.cookies, headers={"If-Match": listed.headers["etag"]})
        self.assertEqual((empty.status_code, created.status_code, members.status_code, renamed.status_code, listed.status_code,
                          deleted.status_code), (200, 201, 200, 200, 200, 200))
        self.assertEqual(empty.json()["data"], {"groups": []})
        self.assertEqual(empty.headers["cache-control"], "no-store")
        self.assertEqual(set(created.json()["data"]), {"group_id"})
        self.assertFalse(created.json()["meta"]["replayed"])
        self.assertEqual(members.json()["data"]["groups"][0]["source_ids"], ["src-b", "src-a"])
        self.assertEqual(listed.json()["data"], {"groups": [{"group_id": gid, "name": "가격", "position": 0, "source_ids": ["src-b", "src-a"]}]})
        self.assertEqual(renamed.headers["etag"], listed.headers["etag"])
        self.assertEqual(deleted.json()["data"], {"groups": []})
        self.assertEqual(listed.json()["meta"]["workspace_id"], "workspace-001")
        events = self.events()
        self.assertEqual([e.action for e in events], ["notebook.source_group.create", "notebook.source_group.members",
                                                      "notebook.source_group.update", "notebook.source_group.delete"])
        for event in events:
            self.assertEqual((event.target_type, event.target_id, event.actor_id), ("notebook", "notebook-1", "user-001"))
            self.assertEqual(event.metadata["group_id"], gid)
            self.assertNotIn("계약", str(event.metadata))   # 묶음 이름(사용자 글)은 남기지 않는다
            self.assertNotIn("가격", str(event.metadata))
        self.assertEqual(dict(events[1].metadata), {"group_id": gid, "source_count": 2, "moved_count": 0})
        self.assertEqual((events[2].metadata["group_id"], list(events[2].metadata["fields"])), (gid, ["name", "position"]))
        self.assertEqual(dict(events[3].metadata), {"group_id": gid, "released_count": 2})

    async def test_post_replay_returns_200_with_same_group(self):
        headers = {"Idempotency-Key": "source-group-key-replay"}
        with self.authenticated():
            first = await self.client.post(BASE, cookies=self.cookies, headers=headers, json={"name": "묶음"})
            again = await self.client.post(BASE, cookies=self.cookies, headers=headers, json={"name": "묶음"})
            reused = await self.client.post(BASE, cookies=self.cookies, headers=headers, json={"name": "다름"})
        self.assertEqual((first.status_code, again.status_code), (201, 200))
        self.assertEqual(first.json()["data"], again.json()["data"])
        self.assertTrue(again.json()["meta"]["replayed"])
        self.assertEqual((reused.status_code, reused.json()["error"]["code"]), (409, "SOURCE_GROUP_IDEMPOTENCY_KEY_REUSED"))
        self.assertEqual(len(self.events()), 1)

    async def test_viewer_can_read_but_every_change_is_403(self):
        with self.authenticated():
            created = await self.client.post(BASE, cookies=self.cookies, headers=self.key(), json={"name": "A"})
        gid, etag = created.json()["data"]["group_id"], created.headers["etag"]
        before, seen = len(self.events()), []
        original = self.authorization.authorize_action

        def viewer(**kwargs):
            seen.append(kwargs["action"])
            if kwargs["action"] is not Action.VIEW:
                raise AuthorizationError("ACTION_DENIED", 403)
            return original(**kwargs)

        with self.authenticated(), patch.object(self.authorization, "authorize_action", side_effect=viewer):
            got = await self.client.get(BASE, cookies=self.cookies)
            post = await self.client.post(BASE, cookies=self.cookies, headers=self.key(), json={"name": "B"})
            patch_ = await self.client.patch(f"{BASE}/{gid}", cookies=self.cookies, headers={"If-Match": etag}, json={"name": "C"})
            put = await self.client.put(f"{BASE}/{gid}/members", cookies=self.cookies, headers={"If-Match": etag}, json={"source_ids": ["src-a"]})
            delete = await self.client.delete(f"{BASE}/{gid}", cookies=self.cookies, headers={"If-Match": etag})
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["data"]["groups"][0]["name"], "A")
        self.assertEqual([r.status_code for r in (post, patch_, put, delete)], [403, 403, 403, 403])
        self.assertEqual(seen, [Action.VIEW, Action.EDIT, Action.EDIT, Action.EDIT, Action.EDIT])
        self.assertEqual(len(self.db.groups), 1)
        self.assertEqual(self.db.groups[gid]["name"], "A")
        self.assertEqual((self.db.members, len(self.events())), ({}, before))

    async def test_error_codes(self):
        with self.authenticated():
            created = await self.client.post(BASE, cookies=self.cookies, headers=self.key(), json={"name": "A"})
            gid, etag = created.json()["data"]["group_id"], created.headers["etag"]
            outside = await self.client.put(f"{BASE}/{gid}/members", cookies=self.cookies, headers={"If-Match": etag},
                                            json={"source_ids": ["src-x"]})
            stale = await self.client.patch(f"{BASE}/{gid}", cookies=self.cookies, headers={"If-Match": '"sg-' + "0" * 32 + '"'},
                                            json={"name": "B"})
            missing = await self.client.delete(f"{BASE}/sg-{'1' * 32}", cookies=self.cookies, headers={"If-Match": etag})
            long_name = await self.client.post(BASE, cookies=self.cookies, headers=self.key(), json={"name": "가" * 81})
            no_notebook = await self.client.get(BASE.replace("notebook-1", "notebook-x"), cookies=self.cookies)
        self.assertEqual((outside.status_code, outside.json()["error"]["code"]), (422, "SOURCE_NOT_IN_NOTEBOOK"))
        self.assertEqual((stale.status_code, stale.json()["error"]["code"]), (412, "SOURCE_GROUP_ETAG_MISMATCH"))
        self.assertEqual((missing.status_code, missing.json()["error"]["code"]), (404, "SOURCE_GROUP_NOT_FOUND"))
        self.assertEqual(long_name.status_code, 422)
        self.assertEqual((no_notebook.status_code, no_notebook.json()["error"]["code"]), (404, "NOTEBOOK_NOT_FOUND"))
        self.assertEqual(len(self.events()), 1)

    async def test_limit_is_409(self):
        with self.authenticated():
            for index in range(50):
                ok = await self.client.post(BASE, cookies=self.cookies, headers=self.key(), json={"name": f"묶음 {index}"})
                self.assertEqual(ok.status_code, 201)
            over = await self.client.post(BASE, cookies=self.cookies, headers=self.key(), json={"name": "초과"})
        self.assertEqual((over.status_code, over.json()["error"]["code"]), (409, "SOURCE_GROUP_LIMIT"))

    async def test_required_headers_and_strict_inputs(self):
        with self.authenticated():
            created = await self.client.post(BASE, cookies=self.cookies, headers=self.key(), json={"name": "A"})
            gid, etag = created.json()["data"]["group_id"], created.headers["etag"]
            no_key = await self.client.post(BASE, cookies=self.cookies, json={"name": "B"})
            short_key = await self.client.post(BASE, cookies=self.cookies, headers={"Idempotency-Key": "short"}, json={"name": "B"})
            no_match_patch = await self.client.patch(f"{BASE}/{gid}", cookies=self.cookies, json={"name": "B"})
            no_match_put = await self.client.put(f"{BASE}/{gid}/members", cookies=self.cookies, json={"source_ids": []})
            no_match_delete = await self.client.delete(f"{BASE}/{gid}", cookies=self.cookies)
            extra = await self.client.post(BASE, cookies=self.cookies, headers=self.key(), json={"name": "B", "x": 1})
            query = await self.client.get(BASE + "?x=1", cookies=self.cookies)
            bad_gid = await self.client.patch(f"{BASE}/not-a-group", cookies=self.cookies, headers={"If-Match": etag}, json={"name": "B"})
            bad_member = await self.client.put(f"{BASE}/{gid}/members", cookies=self.cookies, headers={"If-Match": etag},
                                               json={"source_ids": "src-a"})
        for response in (no_key, short_key, no_match_patch, no_match_put, no_match_delete, extra, query, bad_gid, bad_member):
            self.assertIn(response.status_code, {400, 422}, response.text)
        self.assertEqual(len(self.db.groups), 1)
        self.assertEqual(self.db.groups[gid]["name"], "A")

    async def test_database_down_is_503(self):
        self.db.fail = True
        with self.authenticated():
            response = await self.client.get(BASE, cookies=self.cookies)
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (503, "SOURCE_GROUPS_UNAVAILABLE"))


if __name__ == "__main__":
    unittest.main()
