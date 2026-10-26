"""지식 Connector 서비스: 실DB(DAON_STUDIO_V2_TEST_DSN, 마이그레이션 0075 적용) + 같은 프로세스의 가상 MCP 서버."""
from __future__ import annotations

import os
import sys
import threading
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mcp-virtual"))

from daon2_user_api.cloud_storage import PostgresCloudStore  # noqa: E402
from daon2_user_api.knowledge_connector_service import ConnectorContext, ConnectorError, KnowledgeConnectorService, validate_endpoint  # noqa: E402
from daon2_user_api.mcp_client import McpError  # noqa: E402
from daon2_user_api.provider_credentials import ProviderCredentialCipher  # noqa: E402

DSN = os.environ.get("DAON_STUDIO_V2_TEST_DSN")
KEY = b"connector-test-key-0123456789abcdef01"


class SettingsFromEnvTests(unittest.TestCase):
    def test_virtual_qa_switch_only_relaxes_production_when_explicit(self):
        from unittest import mock

        from daon2_user_api.knowledge_connector_service import settings_from_env
        with mock.patch.dict(os.environ, {"DAON_RUNTIME_PROFILE": "production"}, clear=True):
            self.assertTrue(settings_from_env()["production"])
        with mock.patch.dict(os.environ, {"DAON_RUNTIME_PROFILE": "production", "DAON_MCP_ALLOW_VIRTUAL_QA": "yes"}, clear=True):
            self.assertTrue(settings_from_env()["production"])
        with mock.patch.dict(os.environ, {"DAON_RUNTIME_PROFILE": "production", "DAON_MCP_ALLOW_VIRTUAL_QA": "true"}, clear=True):
            self.assertFalse(settings_from_env()["production"])


class EndpointValidationTests(unittest.TestCase):
    def test_endpoint_rules(self):
        self.assertEqual(validate_endpoint("https://example.com/mcp", allow_private=False), "https://example.com/mcp")
        for bad in ("ftp://x/mcp", "http://u:p@example.com/mcp", "https://example.com/mcp?x=1", "https://example.com/mcp#f", "nonsense", "http:///x"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ConnectorError, "CONNECTOR_ENDPOINT_INVALID"):
                    validate_endpoint(bad, allow_private=True)
        for private in ("http://127.0.0.1:8641/mcp", "http://10.0.0.5/mcp", "http://192.168.1.2/mcp", "http://[::1]/mcp"):
            with self.subTest(private=private):
                with self.assertRaisesRegex(ConnectorError, "CONNECTOR_ENDPOINT_PRIVATE_DENIED"):
                    validate_endpoint(private, allow_private=False)
                self.assertEqual(validate_endpoint(private, allow_private=True), private)


@unittest.skipUnless(DSN, "DAON_STUDIO_V2_TEST_DSN required")
class KnowledgeConnectorServiceIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from mcp_virtual.fixtures import COLLECTIONS
        from mcp_virtual.server import make_token, serve
        cls.store = PostgresCloudStore(DSN)
        cls.cipher = ProviderCredentialCipher(KEY * 2, encryption_key_version=1)
        cls.tenant = "it-tenant-" + uuid.uuid4().hex[:8]
        cls.ctx = ConnectorContext(cls.tenant, "it-admin")
        cls.httpd = serve("rag", "127.0.0.1", 0, b"virtual-secret-key-0123456789abcdef0")
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}/mcp"
        cls.pairs = [dict(c) for c in COLLECTIONS]
        cls.token = make_token(b"virtual-secret-key-0123456789abcdef0", aud="knowledge-rag-virtual", pairs=cls.pairs)
        cls.collection = cls.pairs[0]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.close()

    def service(self, **kw):
        return KnowledgeConnectorService(self.store, self.cipher, **kw)

    def register(self, service, **over):
        spec = {"kind": "daon2_rag", "name": "가상 RAG", "endpoint_url": self.url, "token": self.token, "virtual": True,
                "allowed_scopes": [self.collection], **over}
        return service.register(self.ctx, spec)

    def test_register_verify_call_and_disconnect(self):
        service = self.service()
        created = self.register(service)
        self.assertEqual((created["status"], created["virtual"], created["has_credential"]), ("unverified", True, True))
        self.assertNotIn(self.token, str(created))
        self.assertIn(created["connector_id"], [c["connector_id"] for c in service.list(self.ctx)])
        verified = service.verify(self.ctx, created["connector_id"])
        self.assertEqual((verified["status"], verified["protocol_version"], verified["error_code"]), ("verified", "2026-07-28", None))
        result = service.call(self.ctx, created["connector_id"], "list_documents", dict(self.collection))
        self.assertTrue(result.structured["documents"])
        with self.assertRaises(ConnectorError) as scope:
            service.call(self.ctx, created["connector_id"], "list_documents", {"project_id": "proj-beta", "work_package_id": "wp-contracts"})
        self.assertEqual(scope.exception.code, "CONNECTOR_SCOPE_DENIED")
        service.disconnect(self.ctx, created["connector_id"])
        with self.assertRaises(ConnectorError) as gone:
            service.get(self.ctx, created["connector_id"])
        self.assertEqual(gone.exception.status, 404)

    def test_credential_is_encrypted_at_rest_and_tenant_isolated(self):
        import psycopg
        service = self.service()
        created = self.register(service)
        with psycopg.connect(DSN) as connection:  # 앱 역할 DSN이라도 RLS 때문에 GUC 없이는 행이 보이지 않는다.
            self.assertEqual(connection.execute("SELECT count(*) FROM knowledge_connectors").fetchone()[0], 0)
        other = ConnectorContext("another-tenant", "x")
        self.assertEqual(service.list(other), [])
        with self.assertRaises(ConnectorError):
            service.get(other, created["connector_id"])
        with self.store._transaction(service._scope(self.ctx, "connector.read")) as connection:  # noqa: SLF001
            blob = bytes(connection.execute("SELECT credential_ciphertext FROM knowledge_connectors WHERE connector_id=%s", (created["connector_id"],)).fetchone()[0])
        self.assertNotIn(self.token.encode(), blob)
        service.disconnect(self.ctx, created["connector_id"])

    def test_tool_allow_list_is_enforced_and_editable_with_version(self):
        service = self.service()
        created = self.register(service, allowed_tools=["list_documents"])
        with self.assertRaises(McpError) as denied:
            service.call(self.ctx, created["connector_id"], "search_document_evidence", {**self.collection, "question": "x"})
        self.assertEqual(denied.exception.code, "MCP_TOOL_NOT_ALLOWED")
        updated = service.set_allowed_tools(self.ctx, created["connector_id"], ["list_documents", "search_document_evidence"], created["version"])
        self.assertEqual(updated["version"], created["version"] + 1)
        self.assertTrue(service.call(self.ctx, created["connector_id"], "search_document_evidence", {**self.collection, "question": "보험금 지급"}).structured["results"])
        with self.assertRaises(ConnectorError) as stale:
            service.set_allowed_tools(self.ctx, created["connector_id"], ["list_documents"], created["version"])
        self.assertEqual(stale.exception.code, "CONNECTOR_VERSION_CONFLICT")
        with self.assertRaises(ConnectorError):
            service.set_allowed_tools(self.ctx, created["connector_id"], ["ruleset_get"], updated["version"])
        service.disconnect(self.ctx, created["connector_id"])

    def test_call_limits_are_validated_versioned_and_applied_to_the_client(self):
        service = self.service()
        created = self.register(service)
        self.assertEqual(created["limits"], {})
        updated = service.set_limits(self.ctx, created["connector_id"], {"max_concurrent": 2, "calls_per_minute": 1}, created["version"])
        self.assertEqual(updated["limits"], {"max_concurrent": 2, "calls_per_minute": 1})
        self.assertEqual(updated["version"], created["version"] + 1)
        for bad in ({"max_concurrent": 99}, {"timeout_seconds": 0}, {"nope": 1}, {"max_response_bytes": True}, "x"):
            with self.subTest(bad=bad), self.assertRaises(ConnectorError) as raised:
                service.set_limits(self.ctx, created["connector_id"], bad, updated["version"])
            self.assertEqual(raised.exception.code, "CONNECTOR_LIMITS_INVALID")
        with self.assertRaises(ConnectorError) as stale:
            service.set_limits(self.ctx, created["connector_id"], {}, created["version"])
        self.assertEqual(stale.exception.code, "CONNECTOR_VERSION_CONFLICT")
        service.call(self.ctx, created["connector_id"], "list_documents", dict(self.collection))
        with self.assertRaises(McpError):  # 분당 1회 한도를 넘으면 두 번째 호출이 거부된다
            service.call(self.ctx, created["connector_id"], "list_documents", dict(self.collection))
        service.disconnect(self.ctx, created["connector_id"])

    def test_production_blocks_virtual_and_private_endpoints_need_opt_in(self):
        with self.assertRaises(ConnectorError) as virtual:
            self.register(self.service(production=True))
        self.assertEqual(virtual.exception.code, "VIRTUAL_CONNECTOR_FORBIDDEN_IN_PRODUCTION")
        with self.assertRaises(ConnectorError) as private:
            self.register(self.service(), virtual=False)
        self.assertEqual(private.exception.code, "CONNECTOR_ENDPOINT_PRIVATE_DENIED")
        created = self.register(self.service(allow_private=True), virtual=False)
        self.assertFalse(created["virtual"])
        self.service(allow_private=True).disconnect(self.ctx, created["connector_id"])

    def test_verify_records_failure_without_leaking_token(self):
        service = self.service()
        created = self.register(service, endpoint_url="http://127.0.0.1:1/mcp")
        failed = service.verify(self.ctx, created["connector_id"])
        self.assertEqual((failed["status"], failed["error_code"]), ("failed", "MCP_UNAVAILABLE"))
        service.disconnect(self.ctx, created["connector_id"])

    def test_invalid_registrations(self):
        service = self.service()
        for over in ({"kind": "nope"}, {"name": ""}, {"allowed_tools": ["delete_everything"]}, {"allowed_scopes": "x"}, {"token": "short"}, {"endpoint_url": "ftp://x"}):
            with self.subTest(over=over):
                with self.assertRaises(ConnectorError):
                    self.register(service, **over)


if __name__ == "__main__":
    unittest.main()
