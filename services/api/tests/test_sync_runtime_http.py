from __future__ import annotations

import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

import httpx

from test_identity_support import FakeVerifiedOidcProvider, POLICY_VERSION, TRACE_ID, create_service
from daon2_user_api.audit import AuditEventStore
from daon2_user_api.authorization import AuthorizationService, Role, SqliteAuthorizationRepository
from daon2_user_api.identity import ClientKind, DevicePlatform
from daon2_user_api.runtime import WEB_SESSION_COOKIE, RuntimeDependencies, RuntimeSettings, create_app


class SyncRuntimeHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        database_path = Path(self.directory.name) / "runtime.sqlite3"
        audit = AuditEventStore()
        identity, identity_repository, _, clock = create_service(database_path, audit_store=audit)
        login = identity.begin_oidc_login(
            issuer="https://login.example.com", client_id="daon-web",
            audience="daon2-user-api", redirect_uri="https://app.example.com/auth/callback",
            client_kind=ClientKind.WEB, tenant_id="tenant-001",
            trace_id=TRACE_ID, policy_version=POLICY_VERSION,
        )
        provider = FakeVerifiedOidcProvider()
        provider.expected_nonce = login.nonce
        self.session = identity.complete_oidc_login(
            state=login.state, authorization_code=provider.authorization_code,
            code_verifier=login.code_verifier, client_id="daon-web",
            redirect_uri="https://app.example.com/auth/callback", provider=provider,
            platform=DevicePlatform.WEB, trace_id=TRACE_ID, policy_version=POLICY_VERSION,
        )
        authorization_repository = SqliteAuthorizationRepository(database_path)
        authorization_repository.bootstrap_workspace(
            tenant_id=self.session.tenant_id, workspace_id="workspace-sync-runtime",
            owner_user_id=self.session.user_id, owner_role=Role.ORGANIZATION_ADMIN,
            workspace_kind="organization", data_area="cloud_sync",
            cost_limit_cents=1000, now=clock(),
        )
        authorization = AuthorizationService(
            repository=authorization_repository, audit_store=audit,
            clock=clock, identity_service=identity,
        )
        self.identity = identity
        self.dependencies = RuntimeDependencies(
            settings=RuntimeSettings.for_test(
                database_path=database_path, policy_version=POLICY_VERSION
            ),
            identity_service=identity, authorization_service=authorization,
            audit_store=audit, identity_repository=identity_repository,
            authorization_repository=authorization_repository,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(self.dependencies)),
            base_url="https://api.test.invalid",
            cookies={WEB_SESSION_COOKIE: self.session.access_token},
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        self.dependencies.close()
        self.directory.cleanup()

    async def test_preview_requires_step_up_approval_then_transfers_exact_manifest(self) -> None:
        await self._verify_sync_flow("source_version")

    async def test_local_file_preview_requires_step_up_and_verifies_file_before_transfer(self) -> None:
        await self._verify_sync_flow("local_file")

    async def _verify_sync_flow(self, kind: str) -> None:
        content = b"runtime-sync"
        digest = hashlib.sha256(content).hexdigest()
        item = {
            "item_id": "runtime-item", "item_kind": kind,
            "local_object_id": "runtime-local-object", "digest_sha256": digest,
            "byte_size": len(content), "content_type": "text/plain",
        }
        preview_url = "/api/v1/workspaces/workspace-sync-runtime/sync-operations"
        create_headers = {"Idempotency-Key": "sync-create-runtime", "If-Match": "*"}
        if kind == "source_version":
            item["source_version_id"] = "runtime-source-version"
        else:
            for extra in (
                {"source_version_id": "fake-cloud-version"},
                {"content_base64": base64.b64encode(content).decode()},
                {"base_cloud_version_id": "fake-cloud-version", "base_cloud_digest": digest},
            ):
                invalid = await self.client.post(preview_url, headers=create_headers, json={
                    "target_area": "cloud_sync", "items": [item | extra],
                })
                self.assertIn(invalid.status_code, (400, 422), invalid.text)
        created = await self.client.post(
            preview_url, headers=create_headers, json={"target_area": "cloud_sync", "items": [item]},
        )
        self.assertEqual(created.status_code, 201, created.text)
        operation_id = created.json()["data"]["operation_id"]
        self.assertEqual(created.json()["data"]["target_versions"], [])
        transfer_url = f"/api/v1/sync-operations/{operation_id}/transfer-batches"
        payload = {"items": [{"item_id": "runtime-item", "content_base64": base64.b64encode(content).decode()}]}
        premature = await self.client.post(
            transfer_url, headers={"Idempotency-Key": "sync-unapproved", "If-Match": created.headers["etag"]}, json=payload,
        )
        self.assertEqual(premature.status_code, 403, premature.text)
        listed = await self.client.get(
            "/api/v1/workspaces/workspace-sync-runtime/sync-operations"
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["data"]["operations"][0]["operation_id"], operation_id)
        self.assertEqual(listed.json()["data"]["operations"][0]["item_ids"], ["runtime-item"])
        denied = await self.client.post(
            f"/api/v1/sync-operations/{operation_id}/approve",
            headers={"Idempotency-Key": "sync-approve-denied", "If-Match": created.headers["etag"]},
            json={"approved_item_ids": ["runtime-item"], "step_up_authorization_id": "invalid-step-up"},
        )
        self.assertEqual(denied.status_code, 403)
        step_up = self.identity.issue_step_up(
            access_token=self.session.access_token, action_group="data_area_move",
            target_id=operation_id, policy_version=POLICY_VERSION, trace_id=TRACE_ID,
        )
        approved = await self.client.post(
            f"/api/v1/sync-operations/{operation_id}/approve",
            headers={"Idempotency-Key": "sync-approve-runtime", "If-Match": created.headers["etag"]},
            json={"approved_item_ids": ["runtime-item"],
                  "step_up_authorization_id": step_up.authorization},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["data"]["target_versions"], [])
        if kind == "local_file":
            bad = await self.client.post(
                transfer_url, headers={"Idempotency-Key": "sync-batch-bad-file", "If-Match": approved.headers["etag"]},
                json={"items": [{"item_id": "runtime-item", "content_base64": base64.b64encode(b"x" * len(content)).decode()}]},
            )
            self.assertEqual(bad.status_code, 400, bad.text)
        transferred = await self.client.post(
            transfer_url,
            headers={"Idempotency-Key": "sync-batch-runtime", "If-Match": approved.headers["etag"]},
            json=payload,
        )
        self.assertEqual(transferred.status_code, 200, transferred.text)
        self.assertEqual(transferred.json()["operation"]["state"], "reindex_requested")
        self.assertEqual(transferred.json()["operation"]["source_mutations"], 0)
        self.assertEqual(transferred.json()["operation"]["target_versions"][0]["digest_sha256"], digest)


if __name__ == "__main__":
    unittest.main()
