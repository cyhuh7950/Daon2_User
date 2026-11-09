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
from daon2_user_api.question_answering import strip_citation_labels
from daon2_user_api.question_answering_postgres import PostgresQuestionAnsweringRepository, QuestionContext, QuestionRepositoryError, StoredCitation, StoredQuestionAnswer
from daon2_user_api.question_answering_service import QuestionAnsweringError, QuestionAnsweringService
from daon2_user_api.question_external_evidence import (
    ANSWER_FORMAT_RULE, APPROVED_MARK, MAX_SEARCH_QUESTION_CHARS, PLAN_OUTPUT_TOKENS, PLAN_SYSTEM, PRIORITY_RULE, EvidenceTarget, ExternalEvidence, ExternalEvidenceError, NotebookKnowledgeEvidence,
    build_plan_prompt, default_requests, merge_evidence, parse_plan, rewrite_plan_payload,
)
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
        self.assertEqual(connectors.calls[0][2]["question"], "가" * MAX_SEARCH_QUESTION_CHARS)

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

    def test_approved_knowledge_comes_first_and_takes_at_most_half(self):
        merged = merge_evidence(tuple(local(i) for i in range(8)), tuple(external(f"b{i}") for i in range(7)))
        self.assertEqual([c.chunk_id for c in merged], [*(f"ext-b{i}" for i in range(5)), *(f"chunk-{i}" for i in range(5))])
        self.assertTrue(merged[0].text.startswith(APPROVED_MARK))

    def test_mark_is_only_needed_when_mixed_with_sources(self):
        text = merge_evidence((), (external("b1"),))[0].text
        self.assertFalse(text.startswith(APPROVED_MARK))
        self.assertTrue(text.endswith("외부 b1"))

    def test_document_name_and_page_are_part_of_the_evidence_text(self):
        text = merge_evidence((), (external("b1"),))[0].text
        self.assertIn("약관.pdf", text)
        self.assertIn("3쪽", text)


def target(*names):
    packages = tuple({"alias": f"P{i + 1}", "project_id": "p1", "project_name": "프로젝트", "work_package_id": f"w{i + 1}", "work_package_name": name} for i, name in enumerate(names))
    return EvidenceTarget(SimpleNamespace(tenant_id="tenant-a"), "kc-rag", packages)


class PlanTests(unittest.TestCase):
    def test_prompt_has_question_history_and_aliases_but_no_ids(self):
        text = build_plan_prompt("평가 기준은?", (("이전 질문", "이전 답변"),), target("제안서 작업"))
        for part in ("평가 기준은?", "이전 질문", "이전 답변", "P1", "제안서 작업", "rag"):
            self.assertIn(part, text)
        self.assertNotIn("w1", text)

    def test_valid_plan(self):
        raw = json.dumps({"needs": "기준", "requests": [{"knowledge": "rag", "package": "P2", "query": " 평가 기준 "}]}, ensure_ascii=False)
        self.assertEqual(parse_plan(raw, target("A", "B")), (("P2", "평가 기준"),))

    def test_fenced_json_is_accepted(self):
        self.assertEqual(parse_plan('```json\n{"requests":[{"knowledge":"rag","package":"P1","query":"x"}]}\n```', target("A")), (("P1", "x"),))

    def test_plan_returned_as_python_text_is_accepted(self):
        self.assertEqual(parse_plan(str({"requests": [{"knowledge": "rag", "package": "P1", "query": "x"}]}), target("A")), (("P1", "x"),))

    def test_empty_requests_mean_no_search(self):
        self.assertEqual(parse_plan('{"requests":[]}', target("A")), ())

    def test_unreadable_plan_is_none(self):
        for raw in ("문장", "[]", '{"needs":"x"}', '{"requests":"x"}'):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_plan(raw, target("A")))

    def test_unknown_choices_are_dropped_and_all_dropped_is_none(self):
        raw = json.dumps({"requests": [{"knowledge": "secret", "package": "P1", "query": "a"}, {"knowledge": "rag", "package": "P9", "query": "b"}, {"knowledge": "rag", "package": "P1", "query": "c"}]})
        self.assertEqual(parse_plan(raw, target("A")), (("P1", "c"),))
        self.assertIsNone(parse_plan(json.dumps({"requests": [{"knowledge": "secret", "package": "P1", "query": "a"}]}), target("A")))

    def test_all_packages_expand_and_calls_are_capped(self):
        requests = [{"knowledge": "rag", "package": "all", "query": q} for q in ("a", "b", "c", "d")]
        parsed = parse_plan(json.dumps({"requests": requests}), target(*"ABCD"))
        self.assertEqual(len(parsed), 8)
        self.assertEqual(sorted({q for _, q in parsed}), ["a", "b"])

    def test_query_is_cut_to_server_limit(self):
        parsed = parse_plan(json.dumps({"requests": [{"knowledge": "rag", "package": "P1", "query": "가" * 800}]}, ensure_ascii=False), target("A"))
        self.assertEqual(parsed[0][1], "가" * MAX_SEARCH_QUESTION_CHARS)

    def test_default_requests_search_each_package_with_the_question(self):
        self.assertEqual(default_requests(target("A", "B"), " 질문 "), (("P1", "질문"), ("P2", "질문")))

    def test_rewrite_keeps_schema_rules_and_replaces_user_text(self):
        for payload in ({"messages": [{"role": "system", "content": "기존"}, {"role": "user", "content": "원문"}]}, {"input": [{"role": "system", "content": "기존"}, {"role": "user", "content": "원문"}]}):
            with self.subTest(payload=list(payload)):
                out = rewrite_plan_payload(payload, "새 사용자 내용")
                items = out.get("messages") or out["input"]
                self.assertEqual(items[0]["content"], PLAN_SYSTEM)
                self.assertEqual(items[1]["content"], "새 사용자 내용")

    def test_rewrite_handles_top_level_system_and_small_output_limits(self):
        out = rewrite_plan_payload({"system": "기존 Return only a JSON object matching this schema: {}", "messages": [{"role": "user", "content": "원문"}], "options": {"num_predict": 64}}, "새 내용")
        self.assertEqual(out["system"], PLAN_SYSTEM + " Return only a JSON object matching this schema: {}")
        self.assertEqual(out["options"]["num_predict"], PLAN_OUTPUT_TOKENS)

    def test_finder_runs_only_the_requested_searches(self):
        connectors = _Connectors({"w1": {"result": [hit("b1")]}, "w2": {"result": [hit("b2")]}})
        finder = NotebookKnowledgeEvidence(_Scopes([]), connectors)
        found = finder.run(target("A", "B"), (("P2", "검색어"),))
        self.assertEqual([c[2] for c in connectors.calls], [{"project_id": "p1", "work_package_id": "w2", "question": "검색어", "limit": 5}])
        self.assertEqual([i.work_package_id for i in found], ["w2"])
        self.assertEqual(found[0].work_package_name, "B")

    def test_prepare_returns_none_without_usable_packages(self):
        self.assertIsNone(NotebookKnowledgeEvidence(_Scopes([]), _Connectors({})).prepare(CTX))
        self.assertIsNone(NotebookKnowledgeEvidence(_Scopes([selected("w1")], approved={}), _Connectors({})).prepare(CTX))

    def test_prepare_gives_aliases_to_approved_packages(self):
        items = [selected("w1"), selected("w2")]
        tgt = NotebookKnowledgeEvidence(_Scopes(items, approved={("p1", "w2"): items[1]}), _Connectors({})).prepare(CTX)
        self.assertEqual([(p["alias"], p["work_package_id"]) for p in tgt.packages], [("P1", "w2")])


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


class CitationLabelTests(unittest.TestCase):
    def test_labels_and_their_brackets_are_removed(self):
        self.assertEqual(strip_citation_labels("내용입니다 (ext-0, ext-1). 끝 [ext-2]", {"ext-0", "ext-1", "ext-2"}), "내용입니다 . 끝")

    def test_other_text_is_untouched(self):
        self.assertEqual(strip_citation_labels("next-0 항목 2건", {"ext-0"}), "next-0 항목 2건")

    def _answer(self, text):
        repository, transport = _Repository(), _Transport(["ext-b1"])
        transport.post_json = lambda **kwargs: {"choices": [{"message": {"content": json.dumps({"answer": text, "cited_chunk_ids": ["ext-b1"], "insufficient": False}, ensure_ascii=False)}}]}
        service = QuestionAnsweringService(FakeProviderSettings(), repository, FakeIndex(()), FakeCredential(), transport, FakeEgress())
        service.set_external_evidence(lambda context, question: (external(),))
        service.ask(CTX, source_id=None, source_version_id=None, question="보장 범위는 어떻게 되나요?", run_id="run-a", context_mode="general_ungrounded")
        return repository.persisted["result"].answer

    def test_label_in_answer_no_longer_fails_and_is_not_shown(self):
        self.assertEqual(self._answer("보장 내용입니다 (ext-b1)"), "보장 내용입니다")

    def test_number_missing_from_evidence_still_fails(self):
        with self.assertRaises(QuestionAnsweringError) as caught:
            self._answer("보장 금액은 999만원입니다 (ext-b1)")
        self.assertEqual(caught.exception.code, "TEXT_GENERATION_GROUNDING_INVALID")


class _PlanTransport(FakeTransport):
    def __init__(self, plan, cited):
        super().__init__()
        self.plan, self.cited, self.payloads = plan, cited, []

    def post_json(self, **kwargs):
        self.calls += 1
        self.payloads.append(kwargs["payload"])
        if self.calls == 1 and self.plan is not None:
            return {"choices": [{"message": {"content": json.dumps({"answer": self.plan}, ensure_ascii=False)}}]}
        return {"choices": [{"message": {"content": json.dumps({"answer": "답변", "cited_chunk_ids": self.cited, "insufficient": False}, ensure_ascii=False)}}]}


class _PlanEgress(FakeEgress):
    def __init__(self, allowed=True):
        self.allowed, self.plan_checks = allowed, []

    def authorize_plan(self, context, selection, provider_payload):
        self.plan_checks.append(provider_payload)
        return self.allowed


class _Planner:
    def __init__(self, packages=True):
        self.packages, self.runs = packages, []

    def prepare(self, context):
        return target("제안서 작업") if self.packages else None

    def run(self, tgt, requests):
        self.runs.append(tuple(requests))
        return (external(),) if requests else ()


PLAN = json.dumps({"needs": "기준", "requests": [{"knowledge": "rag", "package": "P1", "query": "평가 기준과 배점"}]}, ensure_ascii=False)
QUESTION = "제안서 작업을 확인해"


class PlannedServiceTests(unittest.TestCase):
    def service(self, plan=PLAN, *, allowed=True, packages=True, chunks=(), history=None):
        self.repository, self.transport, self.egress, self.planner, self.audits = _Repository(), _PlanTransport(plan, ["ext-b1"]), _PlanEgress(allowed), _Planner(packages), []
        service = QuestionAnsweringService(FakeProviderSettings(), self.repository, FakeIndex(chunks), FakeCredential(), self.transport, self.egress)
        service.set_external_evidence(self.planner.run, planner=self.planner, history=history, plan_audit=lambda context, selection: self.audits.append(context.notebook_id))
        return service

    def ask(self, service, question=QUESTION):
        return service.ask(CTX, source_id=None, source_version_id=None, question=question, run_id="run-a", context_mode="general_ungrounded")

    def test_llm_chooses_what_is_searched_before_it_answers(self):
        self.ask(self.service())
        self.assertEqual(self.planner.runs, [(("P1", "평가 기준과 배점"),)])
        self.assertEqual(self.transport.calls, 2)
        first = json.dumps(self.transport.payloads[0], ensure_ascii=False)
        self.assertIn("제안서 작업", first)
        self.assertNotIn("외부 b1", first)
        self.assertIn("외부 b1", json.dumps(self.transport.payloads[1], ensure_ascii=False))
        self.assertEqual(self.audits, ["nb-a"])

    def test_plan_call_needs_its_own_egress_approval(self):
        self.ask(self.service(None, allowed=False))
        self.assertEqual(len(self.egress.plan_checks), 1)
        self.assertEqual(self.transport.calls, 1)
        self.assertEqual(self.planner.runs, [(("P1", QUESTION),)])
        self.assertEqual(self.audits, [])

    def test_unreadable_plan_falls_back_to_the_user_sentence(self):
        self.ask(self.service("문장으로 답함"))
        self.assertEqual(self.planner.runs, [(("P1", QUESTION),)])

    def test_llm_may_decide_no_search_is_needed(self):
        service = self.service(json.dumps({"requests": []}))
        self.assertEqual(service._external_evidence(CTX, QUESTION), ())  # noqa: SLF001
        self.assertEqual(self.planner.runs, [()])

    def test_no_selected_package_means_no_plan_call(self):
        service = self.service(packages=False)
        self.assertEqual(service._external_evidence(CTX, QUESTION), ())  # noqa: SLF001
        self.assertEqual(self.transport.calls, 0)

    def test_greeting_makes_no_plan_call(self):
        service = self.service()
        self.assertEqual(service._external_evidence(CTX, "안녕하세요"), ())  # noqa: SLF001
        self.assertEqual(self.transport.calls, 0)

    def test_recent_conversation_reaches_the_plan(self):
        self.ask(self.service(history=lambda context: (("이전 질문입니다", "이전 답변입니다"),)))
        self.assertIn("이전 질문입니다", json.dumps(self.transport.payloads[0], ensure_ascii=False))

    def test_history_failure_does_not_stop_the_question(self):
        def broken(context):
            raise RuntimeError("x")
        self.ask(self.service(history=broken))
        self.assertEqual(self.planner.runs, [(("P1", "평가 기준과 배점"),)])

    def test_plan_is_made_once_for_authorization_and_question(self):
        service = self.service()
        service.prepare_authorization(CTX, source_id=None, source_version_id=None, question=QUESTION, context_mode="general_ungrounded")
        self.ask(service)
        self.assertEqual(len(self.planner.runs), 1)
        self.assertEqual(len(self.egress.plan_checks), 1)

    def test_mixed_evidence_tells_the_model_to_prefer_approved_knowledge(self):
        service = self.service(chunks=(local(1),))
        service.ask(CTX, source_id="source-cp3", source_version_id="source-version-cp3", question="보장 범위는 어떻게 되나요?", run_id="run-a")
        answer_call = json.dumps(self.transport.payloads[1], ensure_ascii=False)
        self.assertIn(APPROVED_MARK, answer_call)
        self.assertIn(PRIORITY_RULE, answer_call)

    def test_answer_rules_apply_when_knowledge_is_used(self):
        self.ask(self.service())
        self.assertIn(ANSWER_FORMAT_RULE, json.dumps(self.transport.payloads[1], ensure_ascii=False))
        self.assertNotIn(PRIORITY_RULE, json.dumps(self.transport.payloads[1], ensure_ascii=False))

    def test_source_only_question_is_unchanged(self):
        chunk = local(1)
        transport = _Transport(["chunk-1"])
        service = QuestionAnsweringService(FakeProviderSettings(), _Repository(), FakeIndex((chunk,)), FakeCredential(), transport, FakeEgress())
        service.ask(CTX, source_id="source-cp3", source_version_id="source-version-cp3", question="보장 범위는 어떻게 되나요?", run_id="run-a")
        self.assertNotIn(PRIORITY_RULE, json.dumps(transport.payloads[0], ensure_ascii=False))


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
