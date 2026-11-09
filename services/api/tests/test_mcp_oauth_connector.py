"""토큰 발급형 Connector: 발급 요청 형식, 캐시, 오류, 비밀값 비노출(WO-K2 T2)."""
from __future__ import annotations

import io
import json
import unittest
import urllib.error
from contextlib import contextmanager
from urllib.parse import parse_qs

from daon2_user_api.knowledge_connector_service import ConnectorContext, ConnectorError, KnowledgeConnectorService
from daon2_user_api.mcp_client import ClientCredentialsTokenSource, HttpJsonRpcTransport, McpError
from daon2_user_api.provider_credentials import ProviderCredentialCipher

SECRET = "client-secret-value-for-test"
OAUTH = {"token_url": "https://issuer.example.com/oauth/token", "client_id": "stc_test", "client_secret": SECRET,
         "resource": "https://rag.example.com/mcp", "scope": "rag.mcp.evidence.read"}


class _Response(io.BytesIO):
    status = 200
    headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Opener:
    def __init__(self, *results):
        self.results, self.requests = list(results), []

    def open(self, request, timeout):  # noqa: A003
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return _Response(result)


def token_body(token="issued-token", expires_in=300):
    return json.dumps({"access_token": token, "token_type": "Bearer", "expires_in": expires_in}).encode()


def source(opener, clock=lambda: 1000.0):
    return ClientCredentialsTokenSource(**OAUTH, opener=opener, clock=clock)


def http_error(status):
    return urllib.error.HTTPError("https://issuer.example.com", status, "x", {}, io.BytesIO(b"{}"))


class TokenSourceTests(unittest.TestCase):
    def test_requests_one_resource_and_scope_as_form(self):
        opener = _Opener(token_body())
        self.assertEqual(source(opener).token(), "issued-token")
        request = opener.requests[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/x-www-form-urlencoded")
        form = parse_qs(request.data.decode())
        self.assertEqual(form, {"grant_type": ["client_credentials"], "client_id": ["stc_test"], "client_secret": [SECRET],
                                "resource": ["https://rag.example.com/mcp"], "scope": ["rag.mcp.evidence.read"]})

    def test_reuses_token_until_shortly_before_expiry(self):
        now = [1000.0]
        opener = _Opener(token_body("first", 300), token_body("second", 300))
        tokens = source(opener, clock=lambda: now[0])
        self.assertEqual(tokens.token(), "first")
        now[0] = 1260.0
        self.assertEqual(tokens.token(), "first")
        now[0] = 1275.0
        self.assertEqual(tokens.token(), "second")
        self.assertEqual(len(opener.requests), 2)

    def test_lifetime_longer_than_limit_is_capped(self):
        now = [1000.0]
        opener = _Opener(token_body("first", 86400), token_body("second", 300))
        tokens = source(opener, clock=lambda: now[0])
        tokens.token()
        now[0] = 1275.0
        self.assertEqual(tokens.token(), "second")

    def test_rejected_credentials_are_not_retryable(self):
        for status in (400, 401, 403):
            with self.subTest(status=status), self.assertRaises(McpError) as caught:
                source(_Opener(http_error(status))).token()
            self.assertEqual((caught.exception.code, caught.exception.retryable), ("MCP_TOKEN_REJECTED", False))

    def test_issuer_failure_is_retryable(self):
        for failure in (http_error(503), urllib.error.URLError("down"), TimeoutError()):
            with self.subTest(failure=failure), self.assertRaises(McpError) as caught:
                source(_Opener(failure)).token()
            self.assertEqual((caught.exception.code, caught.exception.retryable), ("MCP_TOKEN_UNAVAILABLE", True))

    def test_malformed_token_response_is_rejected(self):
        for body in (b"not json", b"[]", b"{}", json.dumps({"access_token": "x", "expires_in": 0}).encode(),
                     json.dumps({"access_token": "", "expires_in": 60}).encode()):
            with self.subTest(body=body), self.assertRaises(McpError) as caught:
                source(_Opener(body)).token()
            self.assertEqual(caught.exception.code, "MCP_TOKEN_INVALID")

    def test_repr_hides_secret(self):
        self.assertNotIn(SECRET, repr(source(_Opener())))

    def test_transport_sends_issued_token(self):
        calls = []
        transport = HttpJsonRpcTransport("https://rag.example.com/mcp", token_provider=lambda: calls.append(1) or "issued-token")
        opener = _Opener(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode())
        transport._opener = opener  # noqa: SLF001
        transport.request("tools/list")
        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer issued-token")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("issued-token", repr(transport))


class _Connection:
    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=()):
        self.store.statements.append((sql, params))
        return self

    def fetchone(self):
        return self.store.row()


class _Store:
    def __init__(self):
        self.statements = []
        self.sealed = None

    @contextmanager
    def _transaction(self, _scope):
        yield _Connection(self)

    def row(self):
        sql, params = self.statements[-1]
        if sql.startswith("INSERT"):
            self.sealed = params
        p = self.sealed
        base = (p[1], p[2], p[3], p[4], None, p[10], [], False, "unverified", None, None, 1, p[6] is not None, {})
        if "auth_kind" in sql and sql.startswith("SELECT"):
            return (*base, p[6], p[7], p[8], p[9], p[5])
        return base


class OAuthConnectorServiceTests(unittest.TestCase):
    def setUp(self):
        self.store = _Store()
        self.cipher = ProviderCredentialCipher(b"connector-test-key-0123456789abcdef01" * 2, encryption_key_version=1)
        self.service = KnowledgeConnectorService(self.store, self.cipher)
        self.ctx = ConnectorContext("tenant-a", "admin-a")
        self.spec = {"kind": "daon2_rag", "name": "RAG", "endpoint_url": "https://rag.example.com/mcp", "oauth": dict(OAUTH)}

    def test_register_seals_all_oauth_values_and_view_hides_them(self):
        view = self.service.register(self.ctx, self.spec)
        params = self.store.sealed
        self.assertEqual(params[5], "oauth_client_credentials")
        self.assertNotIn(SECRET.encode(), bytes(params[6]))
        self.assertNotIn(SECRET, repr(view))
        self.assertNotIn("stc_test", repr(view))
        self.assertTrue(view["has_credential"])

    def test_register_rejects_token_together_with_oauth(self):
        with self.assertRaisesRegex(ConnectorError, "CONNECTOR_CREDENTIAL_INVALID"):
            self.service.register(self.ctx, {**self.spec, "token": "fixed-token-value"})

    def test_register_rejects_incomplete_oauth(self):
        for key in OAUTH:
            with self.subTest(key=key), self.assertRaises(ConnectorError) as caught:
                self.service.register(self.ctx, {**self.spec, "oauth": {k: v for k, v in OAUTH.items() if k != key}})
            self.assertEqual(caught.exception.code, "CONNECTOR_CREDENTIAL_INVALID")

    def test_register_rejects_private_token_url(self):
        with self.assertRaisesRegex(ConnectorError, "CONNECTOR_ENDPOINT_PRIVATE_DENIED"):
            self.service.register(self.ctx, {**self.spec, "oauth": {**OAUTH, "token_url": "http://127.0.0.1:9/oauth/token"}})

    def test_client_is_built_with_token_source(self):
        created = self.service.register(self.ctx, self.spec)
        client, view = self.service._client(self.ctx, created["connector_id"])  # noqa: SLF001
        self.assertEqual(view["token_url"], OAUTH["token_url"])
        self.assertNotIn(SECRET, repr(client._transport))  # noqa: SLF001
        self.assertIsNotNone(client._transport._token_provider)  # noqa: SLF001

    def test_list_knowledge_scopes_is_allowed_for_rag(self):
        created = self.service.register(self.ctx, {**self.spec, "allowed_tools": ["list_knowledge_scopes"]})
        self.assertEqual(created["allowed_tools"], ["list_knowledge_scopes"])

    def _with_stub_client(self, scopes, egress=None):
        calls = []

        class Client:
            _connection = object()

            def call_tool(self, tool, arguments):
                calls.append((tool, arguments))
                return "result"

        view = {"status": "verified", "virtual": False, "endpoint_url": "https://rag.example.com/mcp", "allowed_scopes": scopes,
                "token_url": OAUTH["token_url"]}
        self.service._client = lambda *_: (Client(), view)  # noqa: SLF001
        self.service._egress_gate = egress  # noqa: SLF001
        return calls

    def test_nested_scope_is_checked_against_allowed_pairs(self):
        calls = self._with_stub_client([{"project_id": "p1", "work_package_id": "w1"}])
        allowed = {"scope": {"tenant_id": "t", "project_id": "p1", "work_package_id": "w1"}, "limit": 5}
        self.assertEqual(self.service.call(self.ctx, "kc", "approved_knowledge_search", allowed), "result")
        with self.assertRaisesRegex(ConnectorError, "CONNECTOR_SCOPE_DENIED"):
            self.service.call(self.ctx, "kc", "approved_knowledge_search", {"scope": {"tenant_id": "t", "project_id": "p2", "work_package_id": "w1"}})
        self.assertEqual(len(calls), 1)

    def test_token_host_must_pass_egress_gate(self):
        checked = []

        class Gate:
            def authorize(self, _context, connector, _size):
                checked.append(connector["endpoint_url"])
                return "issuer.example.com" not in connector["endpoint_url"], "HOST_NOT_ALLOWED"

        self._with_stub_client([], egress=Gate())
        import daon2_user_api.knowledge_connector_service as module
        original, module._is_private_host = module._is_private_host, lambda _host: False  # noqa: SLF001
        self.addCleanup(setattr, module, "_is_private_host", original)
        with self.assertRaisesRegex(ConnectorError, "CONNECTOR_EGRESS_DENIED"):
            self.service.call(self.ctx, "kc", "list_knowledge_scopes", {"limit": 1})
        self.assertEqual(checked, ["https://rag.example.com/mcp", OAUTH["token_url"]])


if __name__ == "__main__":
    unittest.main()
