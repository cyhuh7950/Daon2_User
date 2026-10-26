"""MCP 클라이언트 ↔ 가상 서버 통합 시험(같은 프로세스, 로컬 포트). WO-M0 T-M0-04/06."""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mcp-virtual"))

from mcp_virtual.fixtures import COLLECTIONS, FORBIDDEN_COLLECTION  # noqa: E402
from mcp_virtual.server import make_token, serve  # noqa: E402

from daon2_user_api.mcp_client import HttpJsonRpcTransport, McpClient, McpError  # noqa: E402

KEY = b"virtual-test-key-0123456789abcdef0123"
PAIRS = [dict(c) for c in COLLECTIONS]


class Running:
    def __init__(self, kind, **options):
        self.httpd = serve(kind, "127.0.0.1", 0, KEY, **options)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def client(self, aud, *, pairs=PAIRS, token=None, allowed=None, **kw):
        token = token if token is not None else make_token(KEY, aud=aud, pairs=pairs)
        return McpClient(HttpJsonRpcTransport(f"http://127.0.0.1:{self.port}/mcp", token=token, timeout_seconds=5, **kw), allowed_tools=allowed)


A = COLLECTIONS[0]


class McpClientTests(unittest.TestCase):
    def test_discover_and_tools_list_for_2026_server(self):
        with Running("rag") as s:
            client = s.client("knowledge-rag-virtual")
            self.assertEqual(client.connect().protocol_version, "2026-07-28")
            names = {t["name"] for t in client.list_tools()}
            self.assertEqual(names, {"search_document_evidence", "get_document_evidence", "list_documents", "get_document_outline",
                                     "read_document_section", "get_document_version_status"})

    def test_initialize_fallback_for_2025_server_with_session(self):
        with Running("rag", protocol="2025-06-18") as s:
            conn = s.client("knowledge-rag-virtual").connect()
            self.assertEqual((conn.protocol_version, conn.session_id), ("2025-06-18", "virtual-session"))

    def test_search_is_deterministic_and_resource_uri_reads_back(self):
        with Running("rag") as s:
            client = s.client("knowledge-rag-virtual")
            client.connect()
            args = {**A, "question": "보험금 지급 시기 청구서류 접수", "limit": 5}
            first = client.call_tool("search_document_evidence", args).structured["results"]
            second = client.call_tool("search_document_evidence", args).structured["results"]
            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first), 2)
            self.assertEqual([r["score"] for r in first], sorted((r["score"] for r in first), reverse=True))
            self.assertIn("3일", first[0]["excerpt"])
            content = client.read_resource(first[0]["resource_uri"])["contents"][0]
            self.assertEqual(content["text"], first[0]["excerpt"])

    def test_outline_and_section_reading(self):
        with Running("rag") as s:
            client = s.client("knowledge-rag-virtual")
            client.connect()
            docs = client.call_tool("list_documents", {**A, "document_type": "insurance_terms"}).structured["documents"]
            self.assertEqual(len(docs), 3)
            outline = client.call_tool("get_document_outline", {**A, "document_id": docs[0]["document_id"]}).structured
            self.assertEqual(len(outline["nodes"]), 7)
            section = client.call_tool("read_document_section", {**A, "document_id": docs[0]["document_id"], "node_id": outline["nodes"][2]["node_id"]}).structured
            self.assertTrue(any("지급" in b["text"] for b in section["blocks"]))
            self.assertIsNone(section["next_cursor"])

    def test_scope_is_enforced_and_hides_foreign_documents(self):
        with Running("rag") as s:
            client = s.client("knowledge-rag-virtual")
            client.connect()
            with self.assertRaises(McpError) as caught:
                client.call_tool("list_documents", dict(FORBIDDEN_COLLECTION))
            self.assertEqual(caught.exception.code, "SCOPE_FORBIDDEN")
            other = COLLECTIONS[2]
            docs = client.call_tool("list_documents", dict(other)).structured["documents"]
            with self.assertRaises(McpError) as caught:
                client.call_tool("get_document_outline", {**A, "document_id": docs[0]["document_id"]})  # 다른 컬렉션의 문서
            self.assertEqual(caught.exception.code, "NOT_FOUND")

    def test_authentication_and_audience(self):
        with Running("rag") as s:
            for token in ("garbage", make_token(KEY, aud="wrong-audience", pairs=PAIRS), make_token(b"another-key-0123456789abcdef012345", aud="knowledge-rag-virtual"),
                          make_token(KEY, aud="knowledge-rag-virtual", ttl=-10)):
                with self.assertRaises(McpError) as caught:
                    s.client("knowledge-rag-virtual", token=token).connect()
                self.assertEqual(caught.exception.code, "MCP_UNAUTHENTICATED")
            with self.assertRaises(McpError):
                McpClient(HttpJsonRpcTransport(f"http://127.0.0.1:{s.port}/mcp", timeout_seconds=5)).connect()

    def test_client_enforces_allowed_tools_arguments_and_limits(self):
        with Running("rag") as s:
            client = s.client("knowledge-rag-virtual", allowed=["list_documents"])
            client.connect()
            with self.assertRaises(McpError) as caught:
                client.call_tool("search_document_evidence", {**A, "question": "x"})
            self.assertEqual(caught.exception.code, "MCP_TOOL_NOT_ALLOWED")
            with self.assertRaises(McpError) as caught:
                client.call_tool("list_documents", {"project_id": "p"})  # work_package_id 누락
            self.assertEqual(caught.exception.code, "MCP_ARGUMENTS_INVALID")
            limited = McpClient(HttpJsonRpcTransport(f"http://127.0.0.1:{s.port}/mcp", token=make_token(KEY, aud="knowledge-rag-virtual", pairs=PAIRS), timeout_seconds=5), per_minute=2)
            limited.connect()
            limited.call_tool("list_documents", dict(A))
            limited.call_tool("list_documents", dict(A))
            with self.assertRaises(McpError) as caught:
                limited.call_tool("list_documents", dict(A))
            self.assertEqual((caught.exception.code, caught.exception.retryable), ("LIMIT_EXCEEDED", True))

    def test_response_size_limit_and_redirect_and_token_not_in_repr(self):
        with Running("rag") as s:
            client = s.client("knowledge-rag-virtual", max_response_bytes=200)
            client.connect()
            with self.assertRaises(McpError) as caught:
                client.list_tools()
            self.assertEqual(caught.exception.code, "MCP_RESPONSE_TOO_LARGE")
            transport = HttpJsonRpcTransport("http://127.0.0.1:1/mcp", token="super-secret-token")
            self.assertNotIn("super-secret-token", repr(transport))
            with self.assertRaises(McpError) as caught:
                transport.request("ping")
            self.assertEqual(caught.exception.code, "MCP_UNAVAILABLE")
        for bad in ("ftp://x/mcp", "http://user:pw@x/mcp", "not a url"):
            with self.assertRaises(McpError):
                HttpJsonRpcTransport(bad)

    def test_fault_injection(self):
        with Running("rag", faults=True) as s:
            def call(fault):
                client = s.client("knowledge-rag-virtual", extra_headers={"X-Virtual-Fault": fault})
                client.connect()
                return client.call_tool("list_documents", dict(A))
            with self.assertRaises(McpError) as caught:
                call("not_ready")
            self.assertEqual((caught.exception.code, caught.exception.retryable), ("NOT_READY", True))
            self.assertEqual(call("empty").structured["documents"], [])
            with self.assertRaises(McpError) as caught:
                call("invalid_schema")
            self.assertEqual(caught.exception.code, "MCP_RESPONSE_INVALID")
            with self.assertRaises(McpError) as caught:
                s.client("knowledge-rag-virtual", extra_headers={"X-Virtual-Fault": "forbidden"}).connect()
            self.assertEqual(caught.exception.code, "MCP_FORBIDDEN")
        with Running("rag", faults=False) as s:  # 시험 모드가 아니면 헤더를 무시한다.
            client = s.client("knowledge-rag-virtual", extra_headers={"X-Virtual-Fault": "not_ready"})
            client.connect()
            self.assertGreater(len(client.call_tool("list_documents", dict(A)).structured["documents"]), 0)

    def test_stale_detection_via_version_bump(self):
        with Running("rag", admin_token="admin-secret") as s:
            client = s.client("knowledge-rag-virtual")
            client.connect()
            doc = client.call_tool("list_documents", dict(A)).structured["documents"][0]
            args = {**A, "document_id": doc["document_id"], "version_id": doc["version_id"]}
            self.assertFalse(client.call_tool("get_document_version_status", args).structured["changed"])
            s.httpd.virtual.bump_version(doc["document_id"])
            status = client.call_tool("get_document_version_status", args).structured
            self.assertTrue(status["changed"])
            self.assertNotEqual(status["current_version_id"], doc["version_id"])

    def test_ops_server_ontology_rulesets_and_evaluation(self):
        with Running("ops") as s:
            client = s.client("knowledge-ops-virtual", pairs=[])
            client.connect()
            concepts = client.call_tool("ontology_search_concepts", {"query": "보험금"}).structured["concepts"]
            self.assertEqual(concepts[0]["label"], "보험금")
            self.assertEqual(client.call_tool("ontology_get_concept", {"concept_id": concepts[0]["concept_id"]}).structured["concept"]["kind"], "payment")
            rulesets = client.call_tool("ruleset_list", {"applies_to": "proposal"}).structured["rulesets"]
            self.assertEqual([r["ruleset_id"] for r in rulesets], ["rs-proposal-sections"])
            draft = {"sections": [{"id": "s1", "title": "1. 사업의 이해", "text": "본문"}, {"id": "s2", "title": "가격", "text": "총 사업비"}]}
            results = client.call_tool("ruleset_evaluate", {"ruleset_id": "rs-proposal-sections", "draft": draft}).structured["results"]
            status = {r["rule_id"]: r["status"] for r in results}
            self.assertEqual(status["rule-p1"], "pass")
            self.assertEqual(status["rule-p3"], "fail")
            self.assertEqual(len(results), 7)
            found = client.call_tool("approved_knowledge_search", {"query": "보험금 지급 한도"}).structured["items"]
            self.assertTrue(found and found[0]["score"] > 0)

    def test_contract_test_suite_passes_against_virtual_servers(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("contract_tests", Path(__file__).resolve().parents[2] / "mcp-virtual" / "contract_tests.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for kind, aud, protocol in (("rag", "knowledge-rag-virtual", "2026-07-28"), ("rag", "knowledge-rag-virtual", "2025-06-18"), ("ops", "knowledge-ops-virtual", "2025-06-18")):
            with Running(kind, protocol=protocol) as s:
                token = make_token(KEY, aud=aud, pairs=PAIRS)
                report = module.run(f"http://127.0.0.1:{s.port}/mcp", token, kind, dict(A))
                failed = [r for r in report["results"] if not r["passed"]]
                self.assertTrue(report["passed"], failed)
                self.assertEqual(report["required_passed"], report["required_total"])

    def test_virtual_server_refuses_production(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"ENV": "production"}):
            with self.assertRaisesRegex(RuntimeError, "VIRTUAL_MCP_FORBIDDEN_IN_PRODUCTION"):
                serve("rag", "127.0.0.1", 0, KEY)


if __name__ == "__main__":
    unittest.main()
