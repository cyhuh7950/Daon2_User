"""자료 찾기 · 빠른 찾기 계약(WO-N1 N1-7, NB4-F1, 결정 D-02 웹 제외, 정정 C-6).

가짜 지식 연결로 범위별 호출, 검색 한 번의 도구 호출 상한 4, 한 범위 실패 시 부분 결과, add_scope 중복,
add_source 크기 초과, 권한(검색 보기·추가 편집), 감사에 검색어 없음, 외부 전송 판정 호출 수 = 도구 호출 수를 확인한다.
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx

from daon2_user_api import knowledge_connector_service as connector_module
from daon2_user_api import source_discovery
from daon2_user_api.audit import AuditEventStore
from daon2_user_api.authorization import Action, AuthorizationError, AuthorizationService, Role, SqliteAuthorizationRepository
from daon2_user_api.identity import IdentityPrincipal
from daon2_user_api.knowledge_connector_service import ConnectorError, KnowledgeConnectorService
from daon2_user_api.knowledge_scope_service import KnowledgeScopeContext, KnowledgeScopeService
from daon2_user_api.mcp_client import McpError, McpToolResult
from daon2_user_api.runtime import WEB_SESSION_COOKIE, RuntimeDependencies, RuntimeSettings, create_app
from daon2_user_api.source_discovery import (
    EFFECTIVE_DOCUMENT_BYTES, MAX_CANDIDATES, MAX_DOCUMENT_BYTES, MAX_TOOL_CALLS, CallBudget, DiscoveryError, DiscoverySearcher, SourceDiscoveryService,
    register_source_discovery_routes,
)
from daon2_user_api.text_source import TEXT_SOURCE_MAX_BYTES, TextSourceError, _encode
from test_identity_support import POLICY_VERSION, create_service, identity_session_view

CTX = KnowledgeScopeContext("tenant-1", "workspace-001", "user-001", "trace-1", "policy-1")
NB = "notebook-1"
RAG_TOOLS = ["search_document_evidence", "list_approved_documents", "get_document_text", "get_document_evidence", "list_knowledge_scopes"]
RAG = {"connector_id": "kc-rag", "kind": "daon2_rag", "name": "Daon2-RAG", "status": "verified", "virtual": False, "allowed_tools": RAG_TOOLS}
DAON2 = {"connector_id": "kc-daon2", "kind": "daon2", "name": "Daon2", "status": "verified", "virtual": False,
         "allowed_tools": ["approved_knowledge_search", "approved_knowledge_read", "ontology_search_concepts", "ruleset_list"]}
CANDIDATE_KEYS = {"candidate_id", "kind", "title", "origin_label", "reason", "preview", "action", "ref"}
QUERY = "제안서 평가 기준을 알려 주세요"


def package(project, wp, *, approved=3, tenant="src-tenant"):
    return {"tenant_id": tenant, "project_id": project, "project_name": f"{project} 사업", "work_package_id": wp,
            "work_package_name": f"{wp} 패키지", "approved_document_count": approved}


CATALOG = [package("p-bid", "제안서"), package("p-ins", "약관"), package("p-hr", "인사", approved=0)]


def evidence(doc, block, *, similarity=0.8, text="평가 기준은 기술 70점, 가격 30점이다.", page=2, name=None):
    return {"document_id": doc, "version_id": f"v-{doc}", "run_id": f"r-{doc}", "block_id": block, "text": text,
            "page_no": page, "similarity": similarity, "document_name": name or f"{doc} 문서"}


class FakeConnectors:
    """KnowledgeConnectorService의 list/call 모양. 호출을 모두 기록한다."""

    def __init__(self, rows=(RAG, DAON2), catalog=CATALOG):
        self.rows = [copy.deepcopy(row) for row in rows]
        self.catalog = list(catalog)
        self.calls: list[tuple[str, str, dict]] = []
        self.contexts = []
        self.fail: dict[str, Exception] = {}
        self.evidence: dict[tuple[str, str], list[dict]] = {
            ("p-bid", "제안서"): [evidence("doc-a", "b1"), evidence("doc-a", "b2", similarity=0.9), evidence("doc-b", "b3", similarity=0.5)],
            ("p-ins", "약관"): [evidence("doc-c", "b4", similarity=0.7)],
        }
        self.assets: dict[str, list[dict]] = {"p-bid": [{"asset_id": "as-1", "version_id": "av-1", "asset_name": "제안서 작성 안내"}]}
        self.documents: dict[tuple[str, str], list[dict]] = {
            ("p-bid", "제안서"): [{"document_id": "doc-a", "document_name": "평가 기준서", "version_id": "v-doc-a", "run_id": "r-doc-a",
                                    "block_count": 3, "char_count": 60}],
        }
        self.text_pages: dict[str, list[dict]] = {
            "doc-a": [{"document_id": "doc-a", "document_name": "평가 기준서", "version_id": "v-doc-a", "run_id": "r-doc-a", "total_blocks": 3,
                       "blocks": [{"block_id": "b1", "page_no": 1, "text": "1장 평가 기준"}, {"block_id": "b2", "page_no": 1, "text": "기술 70점"}],
                       "next_cursor": "c1"},
                      {"document_id": "doc-a", "document_name": "평가 기준서", "version_id": "v-doc-a", "run_id": "r-doc-a", "total_blocks": 3,
                       "blocks": [{"block_id": "b3", "page_no": 2, "text": "가격 30점"}], "next_cursor": None}],
        }

    def list(self, context):  # noqa: A003
        self.contexts.append(context)
        return [copy.deepcopy(row) for row in self.rows]

    def call(self, context, connector_id, tool, arguments):
        self.contexts.append(context)
        self.calls.append((connector_id, tool, copy.deepcopy(dict(arguments))))
        if tool in self.fail:
            raise self.fail[tool]
        return McpToolResult(self.respond(tool, dict(arguments)), False, "2026-07-28")

    def respond(self, tool, args):
        if tool == "list_knowledge_scopes":
            return {"scopes": list(self.catalog), "next_cursor": None}
        if tool == "search_document_evidence":
            return {"result": list(self.evidence.get((args["project_id"], args["work_package_id"]), []))}
        if tool == "approved_knowledge_search":
            return {"provenance": "EXPERT_APPROVED", "assets": list(self.assets.get(args["scope"]["project_id"], []))}
        if tool == "list_approved_documents":
            return {"documents": list(self.documents.get((args["project_id"], args["work_package_id"]), [])), "next_cursor": None}
        if tool == "get_document_text":
            pages = self.text_pages[args["document_id"]]
            index = 0 if args.get("cursor") is None else int(args["cursor"][1:])
            return pages[index]
        raise AssertionError(f"unexpected tool {tool}")

    def tools(self):
        return [tool for _, tool, _ in self.calls]


class ScopeStore:
    """KnowledgeScopeService가 쓰는 SQL만 흉내 낸다(notebooks, notebook_knowledge_scopes)."""

    def __init__(self, selected=()):
        self.notebooks = {NB}
        self.rows: dict[str, list[tuple]] = {NB: [(p["project_id"], p["project_name"], p["work_package_id"], p["work_package_name"]) for p in selected]}
        self.writes: list[str] = []

    @contextmanager
    def _transaction(self, scope):
        yield _ScopeConnection(self)


class _ScopeConnection:
    def __init__(self, store):
        self.store, self.result = store, None

    def execute(self, sql, params=()):
        store = self.store
        if sql.startswith("SELECT 1 FROM notebooks"):
            self.result = [(1,)] if params[2] in store.notebooks else []
        elif sql.startswith("SELECT project_id,project_name"):
            self.result = list(store.rows.get(params[2], []))
        elif sql.startswith("DELETE FROM notebook_knowledge_scopes"):
            store.writes.append("delete")
            store.rows[params[2]] = []
        elif sql.startswith("INSERT INTO notebook_knowledge_scopes"):
            store.writes.append("insert")
            store.rows[params[2]].append((params[4], params[5], params[6], params[7]))
        else:
            raise AssertionError(sql)
        return self

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return self.result


class FakeTextSources:
    def __init__(self):
        self.registered: list[dict] = []

    def register_text_source(self, context, notebook_id, *, title, text, origin, idempotency_key=None):
        _encode(text)  # 실제 도우미와 같은 크기·빈 글 검사(2 MiB 넘으면 TEXT_SOURCE_TOO_LARGE)
        self.registered.append({"notebook_id": notebook_id, "title": title, "text": text, "origin": origin, "key": idempotency_key,
                                "actor": context.actor_id})
        return f"src-{len(self.registered)}", f"sv-{len(self.registered)}"


def make_service(connectors=None, selected=(), text_sources=None):
    connectors = connectors or FakeConnectors()
    store = ScopeStore(selected)
    service = SourceDiscoveryService(connectors, KnowledgeScopeService(store, connectors), text_sources or FakeTextSources())
    return service, connectors, store


class SearchTests(unittest.TestCase):
    def test_documents_scope_searches_selected_packages_and_groups_by_document(self):
        service, connectors, _ = make_service(selected=[package("p-bid", "제안서"), package("p-ins", "약관")])
        result = service.search(CTX, NB, QUERY, ["documents"])
        self.assertEqual(connectors.calls, [
            ("kc-rag", "search_document_evidence", {"project_id": "p-bid", "work_package_id": "제안서", "question": QUERY, "limit": 5}),
            ("kc-rag", "search_document_evidence", {"project_id": "p-ins", "work_package_id": "약관", "question": QUERY, "limit": 5})])
        self.assertEqual(result.unavailable, [])
        self.assertEqual([c["ref"]["document_id"] for c in result.candidates], ["doc-a", "doc-c", "doc-b"])
        first = result.candidates[0]
        self.assertEqual(set(first), CANDIDATE_KEYS)
        self.assertEqual((first["kind"], first["action"], first["title"]), ("document", "add_source", "doc-a 문서"))
        self.assertEqual(first["ref"], {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a",
                                        "document_version": "v-doc-a"})
        self.assertLessEqual(len(first["preview"]), 300)
        self.assertIn("2쪽", first["reason"])
        self.assertTrue(all(context.workspace_id == "workspace-001" for context in connectors.contexts))

    def test_long_question_is_cut_for_document_search_and_preview_is_bounded(self):
        connectors = FakeConnectors()
        connectors.evidence[("p-bid", "제안서")] = [evidence("doc-a", "b1", text="가" * 900)]
        service, connectors, _ = make_service(connectors, selected=[package("p-bid", "제안서")])
        result = service.search(CTX, NB, "질" * 500, ["documents"])
        self.assertEqual(len(connectors.calls[0][2]["question"]), 100)
        self.assertEqual(len(result.candidates[0]["preview"]), 300)

    def test_knowledge_scope_reads_catalog_then_searches_assets_of_matching_packages(self):
        service, connectors, _ = make_service()
        result = service.search(CTX, NB, "제안서 작성", ["knowledge"])
        # 승인 문서가 있는 패키지는 둘이므로 목록 1회 + 승인 자산 검색 2회다(상한 4 안).
        self.assertEqual(connectors.tools(), ["list_knowledge_scopes", "approved_knowledge_search", "approved_knowledge_search"])
        self.assertEqual(connectors.calls[0][:2], ("kc-rag", "list_knowledge_scopes"))
        self.assertEqual(connectors.calls[1][0], "kc-daon2")
        self.assertEqual(connectors.calls[1][2]["scope"], {"tenant_id": "src-tenant", "project_id": "p-bid", "work_package_id": "제안서"})
        kinds = {c["kind"] for c in result.candidates}
        self.assertEqual(kinds, {"knowledge_package"})
        top = result.candidates[0]
        self.assertEqual(set(top), CANDIDATE_KEYS)
        self.assertEqual((top["action"], top["ref"]), ("add_scope", {"kind": "knowledge_package", "project_id": "p-bid", "work_package_id": "제안서"}))
        self.assertIn("제안서 작성 안내", top["preview"])
        # 승인 문서가 없는 패키지(approved 0)는 후보가 아니다.
        self.assertNotIn("p-hr", [c["ref"]["project_id"] for c in result.candidates])

    def test_one_search_never_uses_more_than_four_tool_calls(self):
        connectors = FakeConnectors(catalog=[package(f"p{i}", f"제안서{i}") for i in range(12)])
        selected = [package(f"p{i}", f"제안서{i}") for i in range(8)]
        for i in range(8):
            connectors.evidence[(f"p{i}", f"제안서{i}")] = [evidence(f"doc-{i}-{j}", f"b{j}") for j in range(5)]
        service, connectors, _ = make_service(connectors, selected=selected)
        result = service.search(CTX, NB, "제안서", ["knowledge", "documents"])
        self.assertEqual(MAX_TOOL_CALLS, 4)
        self.assertEqual(len(connectors.calls), 4)
        self.assertEqual(result.calls, 4)
        self.assertEqual(set(connectors.tools()), {"list_knowledge_scopes", "approved_knowledge_search", "search_document_evidence"})
        self.assertLessEqual(len(result.candidates), MAX_CANDIDATES)
        self.assertEqual(MAX_CANDIDATES, 20)

    def test_candidates_are_capped_at_twenty(self):
        connectors = FakeConnectors()
        connectors.evidence[("p-bid", "제안서")] = [evidence(f"doc-{i}", f"b{i}") for i in range(30)]
        service, _, _ = make_service(connectors, selected=[package("p-bid", "제안서")])
        self.assertEqual(len(service.search(CTX, NB, "제안서", ["documents"]).candidates), 20)

    def test_shared_budget_across_searches_for_research_reuse(self):
        connectors = FakeConnectors()
        searcher = DiscoverySearcher(connectors)
        budget = CallBudget(5)
        selected = [package("p-bid", "제안서"), package("p-ins", "약관")]
        searcher.search(CTX, "제안서", ["documents"], selected=selected, budget=budget)
        searcher.search(CTX, "약관", ["documents"], selected=selected, budget=budget)
        searcher.search(CTX, "평가", ["documents"], selected=selected, budget=budget)
        self.assertEqual((budget.used, len(connectors.calls)), (5, 5))

    def test_failed_scope_is_reported_and_other_scope_results_are_kept(self):
        connectors = FakeConnectors()
        connectors.fail["list_knowledge_scopes"] = McpError("MCP_UNAVAILABLE", retryable=True)
        service, _, _ = make_service(connectors, selected=[package("p-bid", "제안서")])
        result = service.search(CTX, NB, "제안서", ["knowledge", "documents"])
        self.assertEqual(result.unavailable, [{"scope": "knowledge", "reason": "DISCOVERY_CONNECTOR_FAILED"}])
        self.assertTrue(result.candidates)
        self.assertEqual({c["kind"] for c in result.candidates}, {"document"})

    def test_all_requested_scopes_failing_is_502(self):
        connectors = FakeConnectors()
        connectors.fail["search_document_evidence"] = ConnectorError("CONNECTOR_EGRESS_DENIED", 403)
        service, _, _ = make_service(connectors, selected=[package("p-bid", "제안서")])
        with self.assertRaises(DiscoveryError) as caught:
            service.search(CTX, NB, "제안서", ["documents"])
        self.assertEqual((caught.exception.code, caught.exception.status), ("DISCOVERY_CONNECTOR_FAILED", 502))
        self.assertEqual(caught.exception.unavailable, [{"scope": "documents", "reason": "DISCOVERY_CONNECTOR_FAILED"}])

    def test_no_usable_scope_is_422_and_nothing_is_called(self):
        cases = [
            ((), "CONNECTOR_NOT_CONFIGURED"),
            (({**RAG, "status": "disabled"},), "CONNECTOR_DISABLED"),
            (({**RAG, "status": "failed"},), "CONNECTOR_NOT_READY"),
            (({**RAG, "virtual": True},), "CONNECTOR_NOT_CONFIGURED"),
            (({**RAG, "allowed_tools": ["search_document_evidence", "list_knowledge_scopes"]},), "TOOL_NOT_ALLOWED"),
        ]
        for rows, reason in cases:
            with self.subTest(reason=reason):
                service, connectors, _ = make_service(FakeConnectors(rows=rows), selected=[package("p-bid", "제안서")])
                with self.assertRaises(DiscoveryError) as caught:
                    service.search(CTX, NB, "제안서", ["documents"])
                self.assertEqual((caught.exception.code, caught.exception.status), ("DISCOVERY_SCOPE_UNAVAILABLE", 422))
                self.assertEqual(caught.exception.unavailable, [{"scope": "documents", "reason": reason}])
                self.assertEqual(connectors.calls, [])

    def test_knowledge_needs_daon2_connection_and_unavailable_scope_does_not_block_the_other(self):
        service, connectors, _ = make_service(FakeConnectors(rows=(RAG,)), selected=[package("p-bid", "제안서")])
        result = service.search(CTX, NB, "제안서", ["knowledge", "documents"])
        self.assertEqual(result.unavailable, [{"scope": "knowledge", "reason": "CONNECTOR_NOT_CONFIGURED"}])
        self.assertNotIn("approved_knowledge_search", connectors.tools())
        self.assertNotIn("list_knowledge_scopes", connectors.tools())

    def test_documents_without_selected_packages_search_matching_catalog_packages(self):
        service, connectors, _ = make_service()
        result = service.search(CTX, NB, "약관", ["documents"])
        self.assertEqual(connectors.tools()[0], "list_knowledge_scopes")
        self.assertEqual(connectors.calls[1][2]["project_id"], "p-ins")
        self.assertEqual([c["ref"]["document_id"] for c in result.candidates], ["doc-c"])

    def test_skipped_package_errors_are_not_failures(self):
        connectors = FakeConnectors()
        connectors.fail["approved_knowledge_search"] = McpError("SCOPE_FORBIDDEN")
        service, _, _ = make_service(connectors)
        result = service.search(CTX, NB, "제안서", ["knowledge"])
        self.assertEqual(result.unavailable, [])
        self.assertEqual(result.candidates[0]["ref"]["project_id"], "p-bid")  # 이름 일치 후보는 그대로

    def test_unknown_notebook_is_404(self):
        service, connectors, _ = make_service()
        with self.assertRaises(DiscoveryError) as caught:
            service.search(CTX, "notebook-x", "제안서", ["documents"])
        self.assertEqual((caught.exception.code, caught.exception.status), ("NOTEBOOK_NOT_FOUND", 404))
        self.assertEqual(connectors.calls, [])


class AddTests(unittest.TestCase):
    def test_add_scope_appends_package_with_existing_replace(self):
        service, connectors, store = make_service(selected=[package("p-ins", "약관")])
        result = service.add(CTX, NB, {"kind": "knowledge_package", "project_id": "p-bid", "work_package_id": "제안서"})
        self.assertEqual(result.data, {"added": "scope"})
        self.assertEqual(sorted(row[0] for row in store.rows[NB]), ["p-bid", "p-ins"])
        self.assertIn("list_knowledge_scopes", connectors.tools())
        self.assertEqual(result.audit["added"], "scope")

    def test_add_scope_twice_is_200_without_writes(self):
        service, connectors, store = make_service(selected=[package("p-bid", "제안서")])
        result = service.add(CTX, NB, {"kind": "knowledge_package", "project_id": "p-bid", "work_package_id": "제안서"})
        self.assertEqual(result.data, {"added": "scope"})
        self.assertEqual(store.writes, [])
        self.assertTrue(result.audit["already_present"])

    def test_add_scope_rechecks_approval_and_limit(self):
        service, _, store = make_service()
        with self.assertRaises(DiscoveryError) as missing:
            service.add(CTX, NB, {"kind": "knowledge_package", "project_id": "p-hr", "work_package_id": "인사"})
        self.assertEqual((missing.exception.code, missing.exception.status), ("DISCOVERY_REF_NOT_FOUND", 404))
        full, _, _ = make_service(FakeConnectors(catalog=[package(f"p{i}", f"w{i}") for i in range(9)]),
                                  selected=[package(f"p{i}", f"w{i}") for i in range(8)])
        with self.assertRaises(DiscoveryError) as limit:
            full.add(CTX, NB, {"kind": "knowledge_package", "project_id": "p8", "work_package_id": "w8"})
        self.assertEqual((limit.exception.code, limit.exception.status), ("DISCOVERY_SCOPE_LIMIT", 409))
        self.assertEqual(store.writes, [])

    def test_add_source_reads_whole_text_and_registers_text_source(self):
        texts = FakeTextSources()
        service, connectors, _ = make_service(text_sources=texts)
        ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        result = service.add(CTX, NB, ref, idempotency_key="discovery-key-0001")
        self.assertEqual(result.data, {"added": "source", "source_id": "src-1"})
        self.assertEqual(connectors.calls, [
            ("kc-rag", "list_approved_documents", {"project_id": "p-bid", "work_package_id": "제안서", "limit": 200}),
            ("kc-rag", "get_document_text", {"document_id": "doc-a", "limit": 100}),
            ("kc-rag", "get_document_text", {"document_id": "doc-a", "limit": 100, "cursor": "c1"})])
        registered = texts.registered[0]
        self.assertEqual((registered["origin"], registered["title"], registered["notebook_id"]), ("research", "평가 기준서", NB))
        self.assertEqual(registered["text"], "1장 평가 기준\n\n기술 70점\n\n가격 30점")
        self.assertTrue(registered["key"].startswith("discovery:"))
        self.assertNotIn("discovery-key-0001", registered["key"])
        self.assertEqual(result.audit["discovery"], {"connector_kind": "daon2_rag", "document_id": "doc-a", "document_version": "v-doc-a"})
        self.assertEqual(result.audit["source_id"], "src-1")

    def test_add_source_over_two_mib_is_413_before_reading_text(self):
        connectors = FakeConnectors()
        connectors.documents[("p-bid", "제안서")][0]["char_count"] = MAX_DOCUMENT_BYTES + 1
        service, connectors, _ = make_service(connectors)
        ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        with self.assertRaises(DiscoveryError) as caught:
            service.add(CTX, NB, ref)
        self.assertEqual((caught.exception.code, caught.exception.status), ("DISCOVERY_DOCUMENT_TOO_LARGE", 413))
        self.assertNotIn("get_document_text", connectors.tools())
        self.assertEqual(MAX_DOCUMENT_BYTES, 2 * 1024 * 1024)

    def test_add_source_stops_reading_when_text_grows_past_the_limit(self):
        connectors = FakeConnectors()
        connectors.documents[("p-bid", "제안서")][0].pop("char_count")
        big = {"document_id": "doc-a", "document_name": "큰 문서", "version_id": "v-doc-a", "run_id": "r-doc-a", "total_blocks": 999,
               "blocks": [{"block_id": "b", "page_no": 1, "text": "가" * 300_000}], "next_cursor": "c1"}
        connectors.text_pages["doc-a"] = [big] * 20
        texts = FakeTextSources()
        service, connectors, _ = make_service(connectors, text_sources=texts)
        ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        with self.assertRaises(DiscoveryError) as caught:
            service.add(CTX, NB, ref)
        self.assertEqual((caught.exception.code, caught.exception.status), ("DISCOVERY_DOCUMENT_TOO_LARGE", 413))
        self.assertLess(connectors.tools().count("get_document_text"), 20)
        self.assertEqual(texts.registered, [])

    def test_add_source_over_text_source_limit_is_also_413(self):
        # 텍스트 소스 상한(NB4-F1b 이후 2 MiB)을 넘는 본문도 같은 413이다.
        connectors = FakeConnectors()
        connectors.documents[("p-bid", "제안서")][0]["char_count"] = None
        connectors.text_pages["doc-a"] = [{**connectors.text_pages["doc-a"][1], "blocks": [{"block_id": "b", "page_no": 1, "text": "a" * (TEXT_SOURCE_MAX_BYTES + 10)}]}]
        service, _, _ = make_service(connectors)
        ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        with self.assertRaises(DiscoveryError) as caught:
            service.add(CTX, NB, ref)
        self.assertEqual((caught.exception.code, caught.exception.status), ("DISCOVERY_DOCUMENT_TOO_LARGE", 413))

    def test_add_source_registers_a_document_larger_than_32_kib(self):
        # NB4-F1b: 텍스트 소스 상한이 2 MiB라 32 KiB를 넘는 승인 문서도 소스로 추가된다.
        self.assertEqual(EFFECTIVE_DOCUMENT_BYTES, MAX_DOCUMENT_BYTES)
        connectors = FakeConnectors()
        connectors.documents[("p-bid", "제안서")][0]["char_count"] = 120_000
        block = "가나다라 마바사 " * 400
        connectors.text_pages["doc-a"] = [{**connectors.text_pages["doc-a"][1],
                                           "blocks": [{"block_id": f"b{i}", "page_no": 1, "text": block} for i in range(30)] +
                                                     [{"block_id": "tail", "page_no": 2, "text": "맨 끝 표식 ZEBRA-TAIL-77"}]}]
        texts = FakeTextSources()
        service, _, _ = make_service(connectors, text_sources=texts)
        ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        result = service.add(CTX, NB, ref, idempotency_key="discovery-key-0002")
        self.assertEqual(result.data, {"added": "source", "source_id": "src-1"})
        text = texts.registered[0]["text"]
        self.assertGreater(len(text.encode("utf-8")), 32 * 1024)
        self.assertTrue(text.endswith("ZEBRA-TAIL-77"))

    def test_add_source_rechecks_that_document_belongs_to_the_package(self):
        service, connectors, _ = make_service()
        ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-z", "document_version": "v-z"}
        with self.assertRaises(DiscoveryError) as caught:
            service.add(CTX, NB, ref)
        self.assertEqual((caught.exception.code, caught.exception.status), ("DISCOVERY_REF_NOT_FOUND", 404))
        self.assertNotIn("get_document_text", connectors.tools())

    def test_add_source_without_needed_tools_is_422(self):
        rows = ({**RAG, "allowed_tools": ["search_document_evidence", "list_knowledge_scopes"]},)
        service, connectors, _ = make_service(FakeConnectors(rows=rows))
        ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        with self.assertRaises(DiscoveryError) as caught:
            service.add(CTX, NB, ref)
        self.assertEqual((caught.exception.code, caught.exception.status), ("DISCOVERY_SCOPE_UNAVAILABLE", 422))
        self.assertEqual(connectors.calls, [])

    def test_add_source_connector_failure_is_502(self):
        connectors = FakeConnectors()
        connectors.fail["get_document_text"] = McpError("MCP_UNAVAILABLE", retryable=True)
        service, _, _ = make_service(connectors)
        ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        with self.assertRaises(DiscoveryError) as caught:
            service.add(CTX, NB, ref)
        self.assertEqual((caught.exception.code, caught.exception.status), ("DISCOVERY_CONNECTOR_FAILED", 502))

    def test_add_source_connector_failure_names_the_tool_and_code(self):
        connectors = FakeConnectors()
        connectors.fail["list_approved_documents"] = McpError("MCP_ARGUMENTS_INVALID")
        service, _, _ = make_service(connectors)
        ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        with self.assertRaises(DiscoveryError) as caught:
            service.add(CTX, NB, ref)
        self.assertEqual(caught.exception.diagnostic, {"tool": "list_approved_documents", "code": "MCP_ARGUMENTS_INVALID"})

    def test_add_source_tool_error_result_is_reported_as_tool_error(self):
        connectors = FakeConnectors()
        original = connectors.call

        def tool_error(context, connector_id, tool, arguments):
            if tool == "get_document_text":
                return McpToolResult({"error": "mcp_evidence_not_found"}, True, "2026-07-28")
            return original(context, connector_id, tool, arguments)
        connectors.call = tool_error
        service, _, _ = make_service(connectors)
        ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        with self.assertRaises(DiscoveryError) as caught:
            service.add(CTX, NB, ref)
        self.assertEqual(caught.exception.diagnostic, {"tool": "get_document_text", "code": "TOOL_ERROR"})

    def test_invalid_ref_is_rejected(self):
        service, connectors, _ = make_service()
        for ref in ({"kind": "web", "project_id": "p", "work_package_id": "w"}, {"kind": "document", "project_id": "p", "work_package_id": "w"},
                    {"kind": "knowledge_package", "project_id": "", "work_package_id": "w"}, "nope"):
            with self.subTest(ref=ref):
                with self.assertRaises(DiscoveryError) as caught:
                    service.add(CTX, NB, ref)
                self.assertEqual(caught.exception.status, 400)
        self.assertEqual(connectors.calls, [])


class CountingGate:
    def __init__(self):
        self.calls = 0

    def authorize(self, context, connector, size_bytes):
        self.calls += 1
        return True, "ALLOWED"


class _Client:
    _connection = object()

    def __init__(self, fake):
        self.fake = fake

    def call_tool(self, name, arguments, **_options):
        self.fake.calls.append(("client", name, dict(arguments)))
        return McpToolResult(self.fake.respond(name, dict(arguments)), False, "2026-07-28")


class EgressGateTests(unittest.TestCase):
    """실제 KnowledgeConnectorService.call을 거친다: 도구 호출마다 외부 전송 판정이 한 번씩 있어야 한다."""

    def connector_service(self):
        fake = FakeConnectors()
        gate = CountingGate()
        service = KnowledgeConnectorService(None, None, egress_gate=gate)
        views = {row["connector_id"]: {**row, "endpoint_url": f"https://{row['connector_id']}.example.com/mcp", "allowed_scopes": [], "version": 1}
                 for row in fake.rows}
        service.list = lambda context: [copy.deepcopy(row) for row in fake.rows]  # type: ignore[method-assign]
        service._client = lambda context, connector_id: (_Client(fake), dict(views[connector_id]))  # type: ignore[method-assign]  # noqa: SLF001
        return service, fake, gate

    def test_every_search_tool_call_passes_the_egress_gate(self):
        service, fake, gate = self.connector_service()
        discovery = SourceDiscoveryService(service, KnowledgeScopeService(ScopeStore([package("p-bid", "제안서")]), service), FakeTextSources())
        with patch.object(connector_module, "_is_private_host", return_value=False):
            discovery.search(CTX, NB, "제안서", ["knowledge", "documents"])
        self.assertEqual(len(fake.calls), 4)
        self.assertEqual(gate.calls, len(fake.calls))

    def test_every_add_source_tool_call_passes_the_egress_gate(self):
        service, fake, gate = self.connector_service()
        discovery = SourceDiscoveryService(service, KnowledgeScopeService(ScopeStore(), service), FakeTextSources())
        ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        with patch.object(connector_module, "_is_private_host", return_value=False):
            discovery.add(CTX, NB, ref)
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(gate.calls, len(fake.calls))

    def test_denied_egress_means_no_tool_call(self):
        service, fake, gate = self.connector_service()
        gate.authorize = lambda *args: (False, "EGRESS_DESTINATION_DENIED")  # type: ignore[method-assign]
        discovery = SourceDiscoveryService(service, KnowledgeScopeService(ScopeStore([package("p-bid", "제안서")]), service), FakeTextSources())
        with patch.object(connector_module, "_is_private_host", return_value=False):
            with self.assertRaises(DiscoveryError) as caught:
                discovery.search(CTX, NB, "제안서", ["documents"])
        self.assertEqual(caught.exception.code, "DISCOVERY_CONNECTOR_FAILED")
        self.assertEqual(fake.calls, [])


BASE = "/api/v1/workspaces/workspace-001/notebooks/notebook-1/source-discovery"
KEY = {"Idempotency-Key": "discovery-key-test"}


class SourceDiscoveryHttpTests(unittest.IsolatedAsyncioTestCase):
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
        self.connectors = FakeConnectors()
        self.store = ScopeStore([package("p-bid", "제안서")])
        self.texts = FakeTextSources()
        register_source_discovery_routes(app, self.dependencies, SourceDiscoveryService(
            self.connectors, KnowledgeScopeService(self.store, self.connectors), self.texts))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")
        self.cookies = {WEB_SESSION_COOKIE: "opaque"}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.dependencies.close()
        self.directory.cleanup()

    def authenticated(self):
        return patch.object(self.identity, "describe_access", return_value=identity_session_view(self.principal))

    def events(self):
        return [e for e in self.audit._events if e.action.startswith("source_discovery.")]

    async def test_search_returns_candidates_and_audit_has_no_query(self):
        with self.authenticated():
            response = await self.client.post(f"{BASE}/search", cookies=self.cookies, json={"query": QUERY, "scopes": ["knowledge", "documents"]})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body["data"]), {"candidates", "unavailable"})
        self.assertEqual(body["meta"]["workspace_id"], "workspace-001")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(response.headers["etag"])
        self.assertTrue(all(set(c) == CANDIDATE_KEYS for c in body["data"]["candidates"]))
        events = self.events()
        self.assertEqual([e.action for e in events], ["source_discovery.search"])
        event = events[0]
        self.assertEqual((event.target_type, event.target_id, event.actor_id), ("notebook", "notebook-1", "user-001"))
        self.assertEqual(list(event.metadata["scopes"]), ["knowledge", "documents"])  # 감사 저장소는 목록을 튜플로 고정한다
        self.assertEqual(event.metadata["candidate_count"], len(body["data"]["candidates"]))
        self.assertEqual(event.metadata["tool_calls"], len(self.connectors.calls))
        for part in ("제안서", "평가", "기준", QUERY):
            self.assertNotIn(part, str(event.metadata))
            self.assertNotIn(part, str(event))

    async def test_add_connector_failure_reports_tool_and_code(self):
        self.connectors.fail["list_approved_documents"] = McpError("MCP_ARGUMENTS_INVALID")
        doc_ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        with self.authenticated():
            failed = await self.client.post(f"{BASE}/add", cookies=self.cookies, headers={"Idempotency-Key": "discovery-key-diag"},
                                            json={"ref": doc_ref})
        self.assertEqual((failed.status_code, failed.json()["error"]["code"]), (502, "DISCOVERY_CONNECTOR_FAILED"))
        self.assertEqual(failed.json()["error"]["details"]["connector"], {"tool": "list_approved_documents", "code": "MCP_ARGUMENTS_INVALID"})

    async def test_search_errors_are_safe_codes_and_audited_without_query(self):
        self.connectors.fail["search_document_evidence"] = McpError("MCP_UNAVAILABLE", retryable=True)
        with self.authenticated():
            failed = await self.client.post(f"{BASE}/search", cookies=self.cookies, json={"query": "비밀 검색어", "scopes": ["documents"]})
            self.connectors.rows = []
            unavailable = await self.client.post(f"{BASE}/search", cookies=self.cookies, json={"query": "비밀 검색어", "scopes": ["documents"]})
            too_long = await self.client.post(f"{BASE}/search", cookies=self.cookies, json={"query": "가" * 501, "scopes": ["documents"]})
            blank = await self.client.post(f"{BASE}/search", cookies=self.cookies, json={"query": "   ", "scopes": ["documents"]})
            web = await self.client.post(f"{BASE}/search", cookies=self.cookies, json={"query": "x", "scopes": ["web"]})
            none = await self.client.post(f"{BASE}/search", cookies=self.cookies, json={"query": "x", "scopes": []})
            extra = await self.client.post(f"{BASE}/search", cookies=self.cookies, json={"query": "x", "scopes": ["documents"], "auto_add": True})
            missing = await self.client.post(BASE.replace("notebook-1", "notebook-x") + "/search", cookies=self.cookies,
                                             json={"query": "x", "scopes": ["documents"]})
        self.assertEqual((failed.status_code, failed.json()["error"]["code"]), (502, "DISCOVERY_CONNECTOR_FAILED"))
        self.assertEqual((unavailable.status_code, unavailable.json()["error"]["code"]), (422, "DISCOVERY_SCOPE_UNAVAILABLE"))
        self.assertEqual(unavailable.json()["error"]["details"]["unavailable"], [{"scope": "documents", "reason": "CONNECTOR_NOT_CONFIGURED"}])
        self.assertEqual([r.status_code for r in (too_long, blank, web, none, extra)], [400, 400, 400, 400, 400])
        self.assertEqual((missing.status_code, missing.json()["error"]["code"]), (404, "NOTEBOOK_NOT_FOUND"))
        self.assertNotIn("비밀", failed.text + unavailable.text)
        events = self.events()
        self.assertEqual([e.outcome.value for e in events], ["failed", "failed"])
        self.assertNotIn("비밀", str(events))

    async def test_add_requires_edit_and_search_needs_only_view(self):
        seen = []
        original = self.authorization.authorize_action

        def viewer(**kwargs):
            seen.append(kwargs["action"])
            if kwargs["action"] is not Action.VIEW:
                raise AuthorizationError("ACTION_DENIED", 403)
            return original(**kwargs)

        ref = {"kind": "knowledge_package", "project_id": "p-ins", "work_package_id": "약관"}
        with self.authenticated(), patch.object(self.authorization, "authorize_action", side_effect=viewer):
            search = await self.client.post(f"{BASE}/search", cookies=self.cookies, json={"query": "제안서", "scopes": ["documents"]})
            add = await self.client.post(f"{BASE}/add", cookies=self.cookies, headers=KEY, json={"ref": ref})
        self.assertEqual((search.status_code, add.status_code), (200, 403))
        self.assertEqual(seen, [Action.VIEW, Action.EDIT])
        self.assertEqual(self.store.writes, [])
        self.assertEqual([e.action for e in self.events()], ["source_discovery.search"])

    async def test_add_scope_and_source_round_trip_with_audit(self):
        scope_ref = {"kind": "knowledge_package", "project_id": "p-ins", "work_package_id": "약관"}
        doc_ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        with self.authenticated():
            added = await self.client.post(f"{BASE}/add", cookies=self.cookies, headers=KEY, json={"ref": scope_ref})
            no_key = await self.client.post(f"{BASE}/add", cookies=self.cookies, json={"ref": scope_ref})
            again = await self.client.post(f"{BASE}/add", cookies=self.cookies, headers=KEY, json={"ref": scope_ref})
            source = await self.client.post(f"{BASE}/add", cookies=self.cookies, headers={"Idempotency-Key": "discovery-key-0001"},
                                            json={"ref": doc_ref})
            bad = await self.client.post(f"{BASE}/add", cookies=self.cookies, headers=KEY, json={"ref": {"kind": "web"}})
        self.assertEqual((added.status_code, added.json()["data"]), (200, {"added": "scope"}))
        self.assertEqual((again.status_code, again.json()["data"]), (200, {"added": "scope"}))
        self.assertEqual((source.status_code, source.json()["data"]), (200, {"added": "source", "source_id": "src-1"}))
        self.assertEqual((bad.status_code, no_key.status_code), (400, 400))
        events = self.events()
        self.assertEqual([e.action for e in events], ["source_discovery.add"] * 3)
        self.assertEqual(events[2].metadata["discovery"], {"connector_kind": "daon2_rag", "document_id": "doc-a", "document_version": "v-doc-a"})
        self.assertEqual(events[2].metadata["source_id"], "src-1")
        self.assertNotIn("기술 70점", str(events))

    async def test_runtime_registers_routes_with_knowledge_connectors(self):
        shared = {"settings": self.dependencies.settings, "identity_service": self.identity, "authorization_service": self.authorization,
                  "audit_store": self.audit, "identity_repository": self.dependencies.identity_repository,
                  "authorization_repository": self.dependencies.authorization_repository}
        # 저장소는 setUp 것을 같이 쓰므로 여기서 닫지 않는다(tearDown이 닫는다).
        paths = {getattr(route, "path", "") for route in create_app(RuntimeDependencies(**shared, knowledge_connector_service=FakeConnectors())).routes}
        bare_paths = {getattr(route, "path", "") for route in create_app(RuntimeDependencies(**shared)).routes}
        for suffix in ("search", "add"):
            self.assertIn(f"/api/v1/workspaces/{{id}}/notebooks/{{notebook_id}}/source-discovery/{suffix}", paths)
            self.assertNotIn(f"/api/v1/workspaces/{{id}}/notebooks/{{notebook_id}}/source-discovery/{suffix}", bare_paths)

    async def test_add_too_large_is_413(self):
        self.connectors.documents[("p-bid", "제안서")][0]["char_count"] = MAX_DOCUMENT_BYTES + 1
        doc_ref = {"kind": "document", "project_id": "p-bid", "work_package_id": "제안서", "document_id": "doc-a", "document_version": "v-doc-a"}
        with self.authenticated():
            response = await self.client.post(f"{BASE}/add", cookies=self.cookies, headers=KEY, json={"ref": doc_ref})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (413, "DISCOVERY_DOCUMENT_TOO_LARGE"))
        self.assertEqual(self.texts.registered, [])


if __name__ == "__main__":
    unittest.main()
