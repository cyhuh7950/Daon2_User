from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from daon2_user_api.audit import AuditEventStore
from daon2_user_api.authorization import AuthorizationService, Role, SqliteAuthorizationRepository
from daon2_user_api.identity import IdentityPrincipal
from daon2_user_api.knowledge_connector_service import ConnectorError
from daon2_user_api.runtime import WEB_SESSION_COOKIE, RuntimeDependencies, RuntimeSettings, create_app
from test_identity_support import POLICY_VERSION, create_service, identity_session_view

CID = "kc-" + "a" * 32
ITEM = {"connector_id": CID, "kind": "daon2_rag", "name": "가상 RAG", "endpoint_url": "http://x:8641/mcp", "protocol_version": None,
        "allowed_tools": ["list_documents"], "allowed_scopes": [], "virtual": True, "status": "unverified", "last_checked_at": None,
        "error_code": None, "version": 1, "has_credential": True}


class FakeService:
    def __init__(self):
        self.calls = []
        self.fail = None

    def _do(self, name, *args):
        self.calls.append((name, *args))
        if self.fail:
            raise ConnectorError(*self.fail)

    def list(self, ctx):
        self._do("list")
        return [dict(ITEM)]

    def register(self, ctx, spec):
        self._do("register", spec)
        return dict(ITEM)

    def verify(self, ctx, cid):
        self._do("verify", cid)
        return {**ITEM, "status": "verified"}

    def set_allowed_tools(self, ctx, cid, tools, version):
        self._do("tools", cid, tools, version)
        return {**ITEM, "version": version + 1}

    def disconnect(self, ctx, cid):
        self._do("disconnect", cid)


class ConnectorRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        db = Path(self.directory.name) / "runtime.sqlite3"
        audit = AuditEventStore()
        identity, identity_repository, _, clock = create_service(db, audit_store=audit)
        repository = SqliteAuthorizationRepository(db)
        self.principal = IdentityPrincipal("user-001", "session-001", "device-001", "tenant-001")
        repository.bootstrap_workspace(tenant_id="tenant-001", workspace_id="workspace-001", owner_user_id="user-001", owner_role=Role.PERSONAL_OWNER,
                                       workspace_kind="personal", data_area="cloud_sync", cost_limit_cents=1000, now=clock())
        authorization = AuthorizationService(repository=repository, audit_store=audit, clock=clock, identity_service=identity)
        self.identity, self.audit, self.service = identity, audit, FakeService()
        self.make = lambda admin: RuntimeDependencies(
            settings=RuntimeSettings.for_test(database_path=db, policy_version=POLICY_VERSION,
                                              system_admin_user_ids=frozenset({"user-001"} if admin else {"admin"})),
            identity_service=identity, authorization_service=authorization, audit_store=audit, identity_repository=identity_repository,
            authorization_repository=repository, knowledge_connector_service=self.service)
        self.cookies = {WEB_SESSION_COOKIE: "opaque"}
        self.clients = []

    async def client(self, admin):
        deps = self.make(admin)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(deps)), base_url="http://127.0.0.1")
        self.clients.append((client, deps))
        return client

    async def asyncTearDown(self):
        for client, deps in self.clients:
            await client.aclose()
            deps.close()
        self.directory.cleanup()

    def authenticated(self):
        return patch.object(self.identity, "describe_access", return_value=identity_session_view(self.principal))

    async def test_admin_crud_and_audit(self):
        client = await self.client(True)
        key = {"Idempotency-Key": "connector-key-000001"}
        with self.authenticated():
            created = await client.post("/api/v1/admin/knowledge-connectors", cookies=self.cookies, headers=key,
                                        json={"kind": "daon2_rag", "name": "가상 RAG", "endpoint_url": "http://x:8641/mcp", "token": "secret-token-123", "virtual": True})
            verified = await client.post(f"/api/v1/admin/knowledge-connectors/{CID}/verify", cookies=self.cookies, json={})
            patched = await client.patch(f"/api/v1/admin/knowledge-connectors/{CID}", cookies=self.cookies, json={"allowed_tools": ["list_documents"]},
                                         headers={"If-Match": f'"knowledge-connector:{CID}:1"'})
            deleted = await client.delete(f"/api/v1/admin/knowledge-connectors/{CID}", cookies=self.cookies)
            listed = await client.get("/api/v1/knowledge-connectors", cookies=self.cookies)
        self.assertEqual([r.status_code for r in (created, verified, patched, deleted, listed)], [201, 200, 200, 204, 200])
        self.assertEqual(patched.headers["etag"], f'"knowledge-connector:{CID}:2"')
        self.assertEqual(self.service.calls[0][1]["token"], "secret-token-123")
        self.assertNotIn("secret-token-123", created.text)
        self.assertIn("endpoint_url", listed.json()["data"]["connectors"][0])
        events = self.audit.list(tenant_id="tenant-001", limit=50).items
        actions = [e.action for e in events]
        for expected in ("knowledge_connector.register", "knowledge_connector.verify", "knowledge_connector.disconnect"):
            self.assertIn(expected, actions)
        self.assertTrue(all("secret-token" not in str(e) for e in events))

    async def test_non_admin_cannot_manage_and_sees_limited_list(self):
        client = await self.client(False)
        with self.authenticated():
            denied = await client.post("/api/v1/admin/knowledge-connectors", cookies=self.cookies, headers={"Idempotency-Key": "connector-key-000002"},
                                       json={"kind": "daon2_rag", "name": "x", "endpoint_url": "http://x:8641/mcp"})
            verify = await client.post(f"/api/v1/admin/knowledge-connectors/{CID}/verify", cookies=self.cookies, json={})
            listed = await client.get("/api/v1/knowledge-connectors", cookies=self.cookies)
        self.assertEqual((denied.status_code, verify.status_code, listed.status_code), (403, 403, 200))
        self.assertEqual(set(listed.json()["data"]["connectors"][0]), {"connector_id", "kind", "name", "status", "virtual", "allowed_scopes"})
        self.assertEqual([c[0] for c in self.service.calls], ["list"])

    async def test_validation_and_error_codes(self):
        client = await self.client(True)
        key = {"Idempotency-Key": "connector-key-000003"}
        with self.authenticated():
            bad = await client.post("/api/v1/admin/knowledge-connectors", cookies=self.cookies, headers=key, json={"kind": "daon2_rag", "name": "x", "endpoint_url": "http://x:8641/mcp", "extra": 1})
            bad_id = await client.post("/api/v1/admin/knowledge-connectors/not-an-id/verify", cookies=self.cookies, json={})
            no_match = await client.patch(f"/api/v1/admin/knowledge-connectors/{CID}", cookies=self.cookies, json={"allowed_tools": []}, headers={"If-Match": "bogus"})
            for code, status in (("CONNECTOR_VERSION_CONFLICT", 409), ("CONNECTOR_NOT_FOUND", 404), ("VIRTUAL_CONNECTOR_FORBIDDEN_IN_PRODUCTION", 403), ("SOMETHING_INTERNAL", 400)):
                self.service.fail = (code, status)
                response = await client.post(f"/api/v1/admin/knowledge-connectors/{CID}/verify", cookies=self.cookies, json={})
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json()["error"]["code"], code if code != "SOMETHING_INTERNAL" else "INVALID_REQUEST")
        self.assertEqual((bad.status_code, bad_id.status_code, no_match.status_code), (400, 400, 400))


if __name__ == "__main__":
    unittest.main()
