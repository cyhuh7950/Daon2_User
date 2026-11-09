"""노트북에서 선택한 업무 패키지의 Daon2-RAG 근거를 질문에 쓴다(WO-K3 1단계)."""
from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from daon2_user_api.document_index_postgres import IndexedEvidenceChunk
from daon2_user_api.knowledge_connector_service import ConnectorError
from daon2_user_api.knowledge_scope_service import KnowledgeScopeError
from daon2_user_api.mcp_client import McpError
from daon2_user_api.question_answering_postgres import PostgresQuestionAnsweringRepository, QuestionContext, QuestionRepositoryError, StoredCitation, StoredQuestionAnswer
from daon2_user_api.question_answering_service import QuestionAnsweringError, QuestionAnsweringService
from daon2_user_api.question_external_evidence import ExternalEvidence, ExternalEvidenceError, NotebookKnowledgeEvidence, merge_evidence
from test_question_answering_service import FakeCredential, FakeEgress, FakeIndex, FakeProviderSettings, FakeRepository, FakeTransport

CTX = QuestionContext("tenant-a", "ws-a", "actor-a", "trace-a", "policy-a", "nb-a")


def hit(block="b1", similarity=0.9, **over):
    return {"document_id": "doc-1", "version_id": "ver-1", "run_id": "run-1", "block_id": block, "page_no": 3, "text": f"본문 {block}",
            "text_truncated": False, "similarity": similarity, "resource_uri": "x://y", **over}


def selected(package="w1"):
    return {"project_id": "p1", "project_name": "프로젝트", "work_package_id": package, "work_package_name": f"패키지 {package}"}


class _Scopes:
    def __init__(self, items, approved=None, failure=None):
        self.items, self.failure = items, failure
        self.approved = approved if approved is not None else {(i["project_id"], i["work_package_id"]): i for i in items}

    def selection(self, _context, notebook_id):
        self.notebook_id = notebook_id
        return {"items": self.items}

    def evidence_target(self, context):
        if self.failure:
            raise self.failure
        self.context = context
        return SimpleNamespace(tenant_id="tenant-a"), "kc-rag", self.approved


class _Connectors:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def call(self, context, connector_id, tool, arguments):
        self.calls.append((connector_id, tool, dict(arguments)))
        page = self.pages[arguments["work_package_id"]]
        if isinstance(page, Exception):
            raise page
        return SimpleNamespace(structured=page, is_error=False)


def search(scopes, connectors, context=CTX, question="보장 범위는?"):
    return NotebookKnowledgeEvidence(scopes, connectors).search(context, question)


class SearchTests(unittest.TestCase):
    def test_no_selection_makes_no_remote_call(self):
        connectors = _Connectors({})
        self.assertEqual(search(_Scopes([]), connectors), ())
        self.assertEqual(connectors.calls, [])

    def test_without_notebook_nothing_is_read(self):
        self.assertEqual(search(_Scopes([selected()]), _Connectors({}), QuestionContext("tenant-a", "ws-a", "actor-a", "trace-a", "policy-a")), ())

    def test_searches_each_selected_package_and_maps_evidence(self):
        connectors = _Connectors({"w1": {"result": [hit("b1", 0.7, document_name="약관.pdf")]}})
        found = search(_Scopes([selected("w1")]), connectors)
        self.assertEqual(connectors.calls, [("kc-rag", "search_document_evidence", {"project_id": "p1", "work_package_id": "w1", "question": "보장 범위는?", "limit": 5})])
        item = found[0]
        self.assertEqual((item.connector_id, item.document_id, item.document_version_id, item.block_id, item.page, item.text, item.document_name, item.work_package_name),
                         ("kc-rag", "doc-1", "ver-1", "b1", 3, "본문 b1", "약관.pdf", "패키지 w1"))
        self.assertIsInstance(item.chunk, IndexedEvidenceChunk)
        self.assertTrue(item.chunk.chunk_id.startswith("ext-"))
        self.assertEqual((item.chunk.page, item.chunk.text, item.chunk.score), (3, "본문 b1", 0.7))

    def test_long_question_is_cut_to_the_server_limit(self):
        connectors = _Connectors({"w1": {"result": [hit()]}})
        search(_Scopes([selected("w1")]), connectors, question="  " + "가" * 800 + "  ")
        self.assertEqual(connectors.calls[0][2]["question"], "가" * 500)

    def test_package_no_longer_approved_is_not_searched(self):
        connectors = _Connectors({"w2": {"result": [hit()]}})
        items = [selected("w1"), selected("w2")]
        found = search(_Scopes(items, approved={("p1", "w2"): items[1]}), connectors)
        self.assertEqual([c[2]["work_package_id"] for c in connectors.calls], ["w2"])
        self.assertEqual(len(found), 1)

    def test_keeps_best_five_across_packages_without_duplicates(self):
        pages = {"w1": {"result": [hit(f"a{i}", 0.1 * i) for i in range(1, 5)]}, "w2": {"result": [hit("a4", 0.4), hit("z", 0.95), hit("y", 0.85)]}}
        found = search(_Scopes([selected("w1"), selected("w2")]), _Connectors(pages))
        self.assertEqual([i.block_id for i in found], ["z", "y", "a4", "a3", "a2"])

    def test_remote_failure_is_a_distinct_retryable_error(self):
        for failure in (McpError("MCP_UNAVAILABLE", retryable=True), ConnectorError("CONNECTOR_EGRESS_DENIED", 403)):
            with self.subTest(failure=failure), self.assertRaises(ExternalEvidenceError) as caught:
                search(_Scopes([selected()]), _Connectors({"w1": failure}))
            self.assertEqual(caught.exception.code, "KNOWLEDGE_EVIDENCE_UNAVAILABLE")

    def test_malformed_response_fails_closed(self):
        for page in ({}, {"result": "x"}, {"result": [{"block_id": "b"}]}, {"result": [hit(text="")]}, {"result": [hit(page_no=0)]}, {"result": [hit(similarity="high")]}):
            with self.subTest(page=page), self.assertRaises(ExternalEvidenceError) as caught:
                search(_Scopes([selected()]), _Connectors({"w1": page}))
            self.assertEqual(caught.exception.code, "KNOWLEDGE_EVIDENCE_UNAVAILABLE")

    def test_missing_connector_is_reported(self):
        with self.assertRaises(ExternalEvidenceError) as caught:
            search(_Scopes([selected()], failure=KnowledgeScopeError("KNOWLEDGE_CONNECTOR_NOT_CONFIGURED", 409)), _Connectors({}))
        self.assertEqual((caught.exception.code, caught.exception.status), ("KNOWLEDGE_CONNECTOR_NOT_CONFIGURED", 409))


def external(block="b1", score=0.9):
    return ExternalEvidence(IndexedEvidenceChunk(f"ext-{block}", "doc-1", "ver-1", 3, f"외부 {block}", block, score), "kc-rag", "p1", "프로젝트", "w1", "패키지",
                            "doc-1", "ver-1", "run-1", block, 3, "약관.pdf", f"외부 {block}")


def local(n):
    return IndexedEvidenceChunk(f"chunk-{n}", "source-cp3", "source-version-cp3", 1, f"로컬 {n}", f"span-{n}", 1.0)


class MergeTests(unittest.TestCase):
    def test_no_external_leaves_local_untouched(self):
        chunks = tuple(local(i) for i in range(8))
        self.assertEqual(merge_evidence(chunks, ()), chunks)

    def test_external_takes_at_most_half(self):
        merged = merge_evidence(tuple(local(i) for i in range(8)), tuple(external(f"b{i}") for i in range(7)))
        self.assertEqual([c.chunk_id for c in merged], [*(f"chunk-{i}" for i in range(5)), *(f"ext-b{i}" for i in range(5))])


class _Transport(FakeTransport):
    def __init__(self, cited):
        super().__init__()
        self.cited, self.payloads = cited, []

    def post_json(self, **kwargs):
        self.calls += 1
        self.payloads.append(kwargs["payload"])
        return {"choices": [{"message": {"content": json.dumps({"answer": "답변", "cited_chunk_ids": self.cited, "insufficient": False}, ensure_ascii=False)}}]}


class _Repository(FakeRepository):
    def persist_completed(self, context, **kwargs):
        self.persisted = kwargs
        self.completed = StoredQuestionAnswer(kwargs["run_id"], "result-a", kwargs["result"].answer, False, ())
        return self.completed


class ServiceTests(unittest.TestCase):
    def service(self, found, cited, chunks=()):
        self.repository, self.transport, self.calls = _Repository(), _Transport(cited), []

        def lookup(context, question):
            self.calls.append(question)
            if isinstance(found, Exception):
                raise found
            return found

        service = QuestionAnsweringService(FakeProviderSettings(), self.repository, FakeIndex(chunks), FakeCredential(), self.transport, FakeEgress())
        service.set_external_evidence(lookup)
        return service

    def ask_without_source(self, service, question="보장 범위는 어떻게 되나요?"):
        return service.ask(CTX, source_id=None, source_version_id=None, question=question, run_id="run-a", context_mode="general_ungrounded")

    def test_selected_knowledge_answers_without_any_source(self):
        self.ask_without_source(self.service((external(),), ["ext-b1"]))
        self.assertEqual(self.transport.calls, 1)
        self.assertIn("외부 b1", json.dumps(self.transport.payloads[0], ensure_ascii=False))
        saved = self.repository.persisted
        self.assertEqual((saved["evidence"], saved["result"].cited_chunk_ids, saved["context_mode"], saved["context_sources"]), ((), (), "general_ungrounded", ()))
        self.assertEqual([i.block_id for i in saved["external_citations"]], ["b1"])

    def test_only_cited_external_evidence_is_saved(self):
        self.ask_without_source(self.service((external("b1"), external("b2")), ["ext-b2"]))
        self.assertEqual([i.block_id for i in self.repository.persisted["external_citations"]], ["b2"])

    def test_source_and_external_citations_are_split(self):
        chunk = local(1)
        service = self.service((external(),), ["chunk-1", "ext-b1"], chunks=(chunk,))
        service.ask(CTX, source_id="source-cp3", source_version_id="source-version-cp3", question="보장 범위는 어떻게 되나요?", run_id="run-a")
        saved = self.repository.persisted
        self.assertEqual((saved["evidence"], saved["result"].cited_chunk_ids), ((chunk,), ("chunk-1",)))
        self.assertEqual([i.block_id for i in saved["external_citations"]], ["b1"])

    def test_without_external_nothing_extra_reaches_storage(self):
        chunk = local(1)
        self.service((), ["chunk-1"], chunks=(chunk,)).ask(CTX, source_id="source-cp3", source_version_id="source-version-cp3", question="보장 범위는 어떻게 되나요?", run_id="run-a")
        self.assertNotIn("external_citations", self.repository.persisted)

    def test_failure_stops_the_question_before_the_model(self):
        with self.assertRaises(QuestionAnsweringError) as caught:
            self.ask_without_source(self.service(ExternalEvidenceError("KNOWLEDGE_EVIDENCE_UNAVAILABLE", 503, True), []))
        self.assertEqual((caught.exception.code, caught.exception.status, caught.exception.retryable), ("KNOWLEDGE_EVIDENCE_UNAVAILABLE", 503, True))
        self.assertEqual(self.transport.calls, 0)

    def test_greeting_does_not_search_knowledge(self):
        service = self.service((external(),), [])
        self.assertEqual(service._external_evidence(CTX, "안녕하세요"), ())  # noqa: SLF001
        self.assertEqual(self.calls, [])

    def test_authorization_and_question_use_the_same_search_result(self):
        service = self.service((external(),), ["ext-b1"])
        prepared = service.prepare_authorization(CTX, source_id=None, source_version_id=None, question="보장 범위는 어떻게 되나요?", context_mode="general_ungrounded")
        self.assertIn("외부 b1".encode("utf-8"), prepared.provider_payload if isinstance(prepared.provider_payload, bytes) else b"")
        self.ask_without_source(service)
        self.assertEqual(len(self.calls), 1)


class _Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self):
        self.statements, self.citation_row = [], None

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        if sql.startswith("SELECT state,version,outcome,error_code"):
            return _Cursor([(params[3], 2, "succeeded", None)])
        if sql.startswith("SELECT project_name"):
            return _Cursor([self.citation_row] if self.citation_row else [])
        return _Cursor()


class _Store:
    def __init__(self):
        self.connection = _Connection()

    @contextmanager
    def _transaction(self, _context):
        yield self.connection


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.store = _Store()
        self.repository = PostgresQuestionAnsweringRepository(self.store, None)

    def persist(self, external_citations):
        from daon2_user_api.question_answering import GroundedTextResult, TextModelSelection
        selection = TextModelSelection("EOUL_GATEWAY", "https://gw.example.com", "profile-a", "deployment-a", "model-a", 1, "external_api", "connection-a", 1, 1, "gateway", False)
        return self.repository.persist_completed(CTX, run_id="run-a", source_id=None, source_version_id=None, question="질문", selection=selection, evidence=(),
                                                 result=GroundedTextResult("답변", (), False, {}), provider_called=False, context_mode="general_ungrounded", context_sources=(), external_citations=external_citations)

    def test_external_citation_is_stored_and_returned(self):
        stored = self.persist((external(),))
        citation = stored.citations[0]
        self.assertTrue(citation.citation_id.startswith("extcit-"))
        self.assertEqual((citation.source_id, citation.source_version_id, citation.evidence_span_id, citation.page, citation.origin, citation.context_item_id, citation.locator),
                         ("doc-1", "ver-1", "b1", 3, "mcp_daon_rag", "w1", {"kind": "section", "value": "b1"}))
        insert = next(p for s, p in self.store.connection.statements if s.startswith("INSERT INTO question_external_citations"))
        self.assertIn("외부 b1", insert)
        self.assertIn("nb-a", insert)

    def test_external_citation_requires_a_notebook(self):
        from dataclasses import replace
        self.repository._cloud_store = self.store  # noqa: SLF001
        from daon2_user_api.question_answering import GroundedTextResult, TextModelSelection
        selection = TextModelSelection("EOUL_GATEWAY", "https://gw.example.com", "profile-a", "deployment-a", "model-a", 1, "external_api", "connection-a", 1, 1, "gateway", False)
        with self.assertRaises(QuestionRepositoryError):
            self.repository.persist_completed(replace(CTX, notebook_id=None), run_id="run-a", source_id=None, source_version_id=None, question="질문", selection=selection, evidence=(),
                                              result=GroundedTextResult("답변", (), False, {}), context_mode="general_ungrounded", context_sources=(), external_citations=(external(),))

    def test_snapshot_is_read_back_as_text_with_provenance(self):
        self.store.connection.citation_row = ("프로젝트", "패키지", "약관.pdf", 3, "저장된 본문", "b1", "doc-1", "ver-1")
        content, locator = self.repository.read_citation_content(CTX, "extcit-abc")
        self.assertEqual(locator, {"kind": "section", "value": "b1"})
        self.assertEqual(content.media_type, "text/plain")
        text = content.content.decode("utf-8")
        for part in ("패키지", "약관.pdf", "3", "저장된 본문"):
            self.assertIn(part, text)

    def test_unknown_snapshot_is_not_disclosed(self):
        with self.assertRaises(QuestionRepositoryError) as caught:
            self.repository.read_citation_content(CTX, "extcit-missing")
        self.assertEqual((caught.exception.code, caught.exception.status), ("CITATION_CONTENT_UNAVAILABLE", 404))


if __name__ == "__main__":
    unittest.main()
