"""심층 조사 계약(WO-N1 N1-7 심층 조사, NB4-F2, 정정 C-5: 스튜디오 보고서 산출물로 기존 큐를 쓴다).

가짜 모델·가짜 지식 연결로 하위 질문 상한 5, 전체 도구 호출 상한 12, 인용 없는 문장 처리(근거 있는 문장처럼 저장하지 않음),
시간 상한(RESEARCH_TIMEOUT), 취소(기존 경로), research.candidates가 빠른 찾기 후보 형식인지, 진행 문구, 외부 전송 판정을 확인한다.
"""
from __future__ import annotations

import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from daon2_user_api import knowledge_connector_service as connector_module
from daon2_user_api.knowledge_connector_service import KnowledgeConnectorService
from daon2_user_api.knowledge_scope_service import KnowledgeScopeError
from daon2_user_api.source_discovery import DiscoverySearcher
from daon2_user_api.studio_research import (
    MAX_RESEARCH_TOOL_CALLS, MAX_SUB_QUESTIONS, RESEARCH_TIMEOUT_SECONDS, UNSUPPORTED_PREFIX, ResearchGenerator, is_research,
)
from daon2_user_api.studio_text_generation import StudioTextGenerator
from daon2_user_api.studio_v2_generation import GenerationContext, GeneratorRegistry, StudioCancelled
from daon2_user_api.studio_v2_postgres import PostgresStudioV2Repository
from daon2_user_api.studio_v2_queue import StudioV2Job
from daon2_user_api.studio_v2_types import STUDIO_V2_TYPES, available_types, checked_settings, validate_settings
from daon2_user_api.studio_v2_worker import StudioV2Worker
from daon2_user_api.studio_workspace import StudioContext, StudioError
from test_source_discovery import CANDIDATE_KEYS, CountingGate, FakeConnectors, _Client, package
from test_studio_v2_generation import FakeCatalog, FakeResolver, FakeTransport, model, openai_reply

CTX = StudioContext("tenant-1", "workspace-001", "user-001", "trace-1", "policy-1", "notebook-1")
QUERY = "제안서 평가 기준과 제출 서류를 조사해 주세요"
SETTINGS = {"research_query": QUERY, "research_scopes": ["knowledge", "documents"]}
MANY = [package(f"p-{i}", f"제안서{i}") for i in range(6)]


class ScriptedLLM:
    """StudioTextGenerator.generate 모양. 받은 프롬프트를 모두 기록한다."""

    def __init__(self, *responses, on_call=None):
        self.responses = list(responses)
        self.prompts = []
        self.on_call = on_call

    def generate(self, context, prompt, cancel_check=None, **_kw):
        self.prompts.append(prompt)
        if self.on_call is not None:
            self.on_call(len(self.prompts))
        data = self.responses.pop(0)
        if isinstance(data, Exception):
            raise data
        return SimpleNamespace(data=data, usage={}, model_id="m", provider_code="CUSTOM", connection_short_code="MS")


class FakeScopes:
    def __init__(self, items=(), error=None):
        self.items = list(items)
        self.error = error
        self.calls = []

    def selection(self, context, notebook_id):
        self.calls.append(notebook_id)
        if self.error is not None:
            raise self.error
        return {"items": [{"project_id": p["project_id"], "project_name": p["project_name"], "work_package_id": p["work_package_id"],
                           "work_package_name": p["work_package_name"]} for p in self.items]}


class Clock:
    def __init__(self, step=0.0):
        self.now = 1000.0
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


def plan(*questions):
    return {"sub_questions": list(questions)}


def report(*sentences, title="조사 보고서"):
    return {"title": title, "sections": [{"heading": "평가 기준", "sentences": [dict(s) for s in sentences]}]}


GOOD = report({"text": "제안서 평가 기준을 정리한 자료가 있다.", "refs": ["S1"]})
DOCS = {"research_query": QUERY, "research_scopes": ["documents"]}


def ctx(settings=None, cancel=None, progress=None):
    notes = [] if progress is None else progress
    return GenerationContext(CTX, "sv2-" + "a" * 32, "report", "briefing", dict(SETTINGS if settings is None else settings), (), "", "ko", "create",
                             lambda pct, note: notes.append((pct, note)), cancel or (lambda: None)), notes


def generator(llm, connectors=None, scopes=None, clock=None, timeout=RESEARCH_TIMEOUT_SECONDS):
    fake = connectors if connectors is not None else FakeConnectors()
    return ResearchGenerator(llm, DiscoverySearcher(fake), scopes or FakeScopes(), clock=clock or Clock(), timeout_seconds=timeout), fake


def blocks(result):
    return [b for s in result.content["body"]["sections"] for b in s["blocks"]]


class ResearchSettingsTests(unittest.TestCase):
    def test_report_schema_has_hidden_research_settings(self):
        properties = STUDIO_V2_TYPES["report"].settings_schema["properties"]
        self.assertEqual(properties["research_query"]["maxLength"], 500)
        self.assertTrue(properties["research_query"]["hidden"])
        self.assertEqual(properties["research_scopes"]["type"], "array")
        self.assertEqual(properties["research_scopes"]["items"]["enum"], ["knowledge", "documents"])
        self.assertTrue(properties["research_scopes"]["hidden"])
        report_type = next(t for t in available_types() if t["type_id"] == "report")
        self.assertIn("research_query", report_type["settings_schema"]["properties"])

    def test_valid_research_settings_are_kept(self):
        fmt, clean = validate_settings("report", None, {**SETTINGS, "focus": "평가"})
        self.assertEqual(fmt, "summary")
        self.assertEqual(clean, {**SETTINGS, "focus": "평가"})
        self.assertTrue(is_research(clean))
        _, one = validate_settings("report", "briefing", {"research_query": "보험", "research_scopes": ["documents"]})
        self.assertEqual(one["research_scopes"], ["documents"])

    def test_invalid_research_settings_are_400(self):
        bad = [
            {"research_query": QUERY},
            {"research_scopes": ["documents"]},
            {"research_query": "   ", "research_scopes": ["documents"]},
            {"research_query": "가" * 501, "research_scopes": ["documents"]},
            {"research_query": QUERY, "research_scopes": []},
            {"research_query": QUERY, "research_scopes": ["web"]},
            {"research_query": QUERY, "research_scopes": ["documents", "documents"]},
            {"research_query": QUERY, "research_scopes": "documents"},
            {"research_query": QUERY, "research_scopes": ["documents", 1]},
            {**SETTINGS, "confirm_outline": "yes"},
            {**SETTINGS, "confirmed_outline": json.dumps({"title": "t", "sections": [{"heading": "h"}]})},
        ]
        for settings in bad:
            with self.subTest(settings=settings):
                with self.assertRaises(StudioError) as caught:
                    checked_settings("report", None, settings)
                self.assertEqual((caught.exception.code, caught.exception.status), ("STUDIO_INPUT_INVALID", 400))

    def test_research_settings_only_on_report(self):
        with self.assertRaises(ValueError):
            validate_settings("slides", None, SETTINGS)

    def test_plain_report_settings_are_unchanged(self):
        self.assertFalse(is_research({"focus": "x"}))
        self.assertEqual(validate_settings("report", None, {"confirm_outline": "yes"}), ("summary", {"confirm_outline": "yes"}))
        self.assertEqual(validate_settings("report", None, {**SETTINGS, "confirm_outline": "no"})[1]["confirm_outline"], "no")


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return _Rows([])


class _Store:
    def __init__(self):
        self.connection = _Connection()

    from contextlib import contextmanager

    @contextmanager
    def _transaction(self, context):
        yield self.connection


class ResearchEnqueueTests(unittest.TestCase):
    def repo(self):
        store = _Store()
        repo = PostgresStudioV2Repository(store)
        repo.tts_resolver = SimpleNamespace(for_tenant=lambda tenant: None)
        return repo, store

    def test_research_without_ready_sources_is_queued_with_no_source_versions(self):
        repo, store = self.repo()
        receipt = repo.enqueue(CTX, {"type_id": "report", "settings": SETTINGS}, "research-key-000001")
        self.assertEqual(receipt["status"], "queued")
        sqls = [sql for sql, _ in store.connection.statements]
        self.assertFalse(any("notebook_bindings" in sql for sql in sqls))  # 준비된 소스를 찾지 않는다
        insert = next(params for sql, params in store.connection.statements if sql.startswith("INSERT INTO studio_v2_outputs"))
        self.assertEqual(insert[9], [])
        job = next(params for sql, params in store.connection.statements if sql.startswith("INSERT INTO studio_v2_jobs"))
        self.assertEqual(job[5].obj["settings"]["research_query"], QUERY)
        self.assertEqual(job[5].obj["source_version_ids"], [])

    def test_research_with_source_versions_is_400(self):
        repo, store = self.repo()
        with self.assertRaises(StudioError) as caught:
            repo.enqueue(CTX, {"type_id": "report", "settings": SETTINGS, "source_version_ids": ["sv-1"]}, "research-key-000002")
        self.assertEqual((caught.exception.code, caught.exception.status), ("STUDIO_INPUT_INVALID", 400))
        self.assertEqual(store.connection.statements, [])

    def test_plain_report_without_sources_still_needs_a_ready_source(self):
        repo, _ = self.repo()
        with self.assertRaises(StudioError) as caught:
            repo.enqueue(CTX, {"type_id": "report", "settings": {}}, "research-key-000003")
        self.assertEqual(caught.exception.code, "STUDIO_NO_READY_SOURCE")


class ResearchFlowTests(unittest.TestCase):
    def test_plan_find_write_with_progress_and_candidates(self):
        llm = ScriptedLLM(plan("평가 기준", "제출 서류"), GOOD)
        research, fake = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]))
        context, notes = ctx()
        result = research.generate(context)
        self.assertEqual([note for _pct, note in notes], ["계획", "찾기 1/2", "찾기 2/2", "작성"])
        pcts = [pct for pct, _ in notes]
        self.assertEqual(pcts, sorted(pcts))
        self.assertTrue(all(0 <= pct <= 99 for pct in pcts))
        info = result.content["research"]
        self.assertEqual(info["query"], QUERY)
        self.assertEqual(info["sub_questions"], ["평가 기준", "제출 서류"])
        self.assertTrue(info["candidates"])
        for candidate in info["candidates"]:
            self.assertEqual(set(candidate), CANDIDATE_KEYS)
        self.assertEqual(len({c["candidate_id"] for c in info["candidates"]}), len(info["candidates"]))
        self.assertEqual(info["tool_calls"], len(fake.calls))
        self.assertEqual(info["unavailable"], [])
        self.assertEqual(result.content["schema"], "studio.report.v1")
        self.assertEqual(result.content["body"]["title"], "조사 보고서")
        self.assertEqual(result.sources, [])
        # 하위 질문마다 같은 검색 함수를 부른다(검색어는 하위 질문)
        questions = [args["question"] for _, tool, args in fake.calls if tool == "search_document_evidence"]
        self.assertIn("평가 기준", questions)
        self.assertIn("제출 서류", questions)

    def test_evidence_rows_point_to_the_found_material(self):
        llm = ScriptedLLM(plan("평가 기준"), GOOD)
        research, _ = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]))
        result = research.generate(ctx()[0])
        candidates = result.content["research"]["candidates"]
        self.assertEqual([e["ref_id"] for e in result.evidence], ["S1"])
        row = result.evidence[0]
        first = candidates[0]
        self.assertIsNone(row["source_version_id"])
        self.assertEqual(row["origin"], "mcp_daon_rag" if first["kind"] == "document" else "mcp_daon")
        self.assertEqual(row["external_ref"]["candidate_id"], first["candidate_id"])
        self.assertEqual(row["external_ref"]["name"], first["title"])
        self.assertEqual(row["external_ref"]["excerpt"], first["preview"])
        self.assertIn("S1", llm.prompts[1].user)
        self.assertIn(first["preview"], llm.prompts[1].user)

    def test_sub_questions_are_capped_at_five(self):
        llm = ScriptedLLM(plan(*[f"질문 {i}" for i in range(9)]), GOOD)
        research, fake = generator(llm, connectors=FakeConnectors(catalog=MANY), scopes=FakeScopes())
        result = research.generate(ctx()[0])
        self.assertEqual(MAX_SUB_QUESTIONS, 5)
        self.assertEqual(result.content["research"]["sub_questions"], [f"질문 {i}" for i in range(5)])

    def test_empty_plan_uses_the_question_itself(self):
        llm = ScriptedLLM(plan(" ", ""), GOOD)
        research, _ = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]))
        result = research.generate(ctx()[0])
        self.assertEqual(result.content["research"]["sub_questions"], [QUERY])

    def test_total_tool_calls_never_exceed_twelve(self):
        llm = ScriptedLLM(plan(*[f"제안서 질문 {i}" for i in range(5)]), GOOD)
        connectors = FakeConnectors(catalog=MANY)
        for i in range(6):
            connectors.evidence[(f"p-{i}", f"제안서{i}")] = [{"document_id": f"doc-{i}", "version_id": f"v-{i}", "block_id": "b", "text": "평가 기준은 기술 70점, 가격 30점이다.",
                                                         "page_no": 1, "similarity": 0.5, "document_name": f"문서 {i}"}]
        research, fake = generator(llm, connectors=connectors, scopes=FakeScopes(MANY))
        context, notes = ctx()
        result = research.generate(context)
        self.assertEqual(MAX_RESEARCH_TOOL_CALLS, 12)
        self.assertEqual(len(fake.calls), 12)
        self.assertEqual(result.content["research"]["tool_calls"], 12)
        # 상한에 닿으면 남은 하위 질문은 찾지 않는다
        self.assertEqual([n for _p, n in notes if n.startswith("찾기")], ["찾기 1/5", "찾기 2/5", "찾기 3/5"])

    def test_candidates_are_capped_and_unique(self):
        llm = ScriptedLLM(plan("제안서 하나", "제안서 둘"), GOOD)
        connectors = FakeConnectors(catalog=MANY)
        research, _ = generator(llm, connectors=connectors, scopes=FakeScopes())
        result = research.generate(ctx()[0])
        ids = [c["candidate_id"] for c in result.content["research"]["candidates"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(len(ids), 40)

    def test_scope_unavailable_everywhere_fails_without_model_write(self):
        llm = ScriptedLLM(plan("평가 기준"), GOOD)
        research, _ = generator(llm, connectors=FakeConnectors(rows=()))
        with self.assertRaises(StudioError) as caught:
            research.generate(ctx()[0])
        self.assertEqual(caught.exception.code, "DISCOVERY_SCOPE_UNAVAILABLE")
        self.assertEqual(len(llm.prompts), 1)

    def test_connector_failure_everywhere_fails(self):
        from daon2_user_api.mcp_client import McpError
        llm = ScriptedLLM(plan("평가 기준"), GOOD)
        connectors = FakeConnectors()
        connectors.fail["list_knowledge_scopes"] = McpError("MCP_UNAVAILABLE")
        connectors.fail["search_document_evidence"] = McpError("MCP_UNAVAILABLE")
        research, _ = generator(llm, connectors=connectors, scopes=FakeScopes([package("p-bid", "제안서")]))
        with self.assertRaises(StudioError) as caught:
            research.generate(ctx()[0])
        self.assertEqual(caught.exception.code, "DISCOVERY_CONNECTOR_FAILED")

    def test_partial_scope_is_reported_in_unavailable(self):
        llm = ScriptedLLM(plan("평가 기준"), GOOD)
        connectors = FakeConnectors(rows=(FakeConnectors().rows[0],))  # Daon2 연결 없음 → knowledge 사용 불가
        research, _ = generator(llm, connectors=connectors, scopes=FakeScopes([package("p-bid", "제안서")]))
        result = research.generate(ctx()[0])
        self.assertEqual(result.content["research"]["unavailable"], [{"scope": "knowledge", "reason": "CONNECTOR_NOT_CONFIGURED"}])

    def test_no_material_found_fails(self):
        llm = ScriptedLLM(plan("평가 기준"), GOOD)
        connectors = FakeConnectors(catalog=[])
        connectors.evidence = {}
        research, _ = generator(llm, connectors=connectors, scopes=FakeScopes([package("p-x", "없음")]))
        with self.assertRaises(StudioError) as caught:
            research.generate(ctx()[0])
        self.assertEqual(caught.exception.code, "RESEARCH_NO_EVIDENCE")
        self.assertEqual(len(llm.prompts), 1)

    def test_selection_error_maps_to_studio_error(self):
        research, _ = generator(ScriptedLLM(plan("x"), GOOD), scopes=FakeScopes(error=KnowledgeScopeError("KNOWLEDGE_SCOPE_UNAVAILABLE", 503)))
        with self.assertRaises(StudioError) as caught:
            research.generate(ctx()[0])
        self.assertEqual(caught.exception.code, "DISCOVERY_UNAVAILABLE")

    def test_notebook_knowledge_selection_is_passed_to_the_search(self):
        scopes = FakeScopes([package("p-ins", "약관")])
        llm = ScriptedLLM(plan("약관"), report({"text": "지급 한도가 있다.", "refs": ["S1"]}))
        research, fake = generator(llm, scopes=scopes)
        research.generate(ctx()[0])
        self.assertEqual(scopes.calls, ["notebook-1"])
        searched = {(a["project_id"], a["work_package_id"]) for _, tool, a in fake.calls if tool == "search_document_evidence"}
        self.assertEqual(searched, {("p-ins", "약관")})


class UnsupportedSentenceTests(unittest.TestCase):
    def run_with(self, *sentences):
        llm = ScriptedLLM(plan("평가 기준"), report(*sentences))
        research, _ = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]))
        return research.generate(ctx(DOCS)[0])  # S1 = 문서 후보(미리보기 "평가 기준은 기술 70점, 가격 30점이다.")

    def test_sentence_without_citation_is_marked_and_has_no_refs(self):
        result = self.run_with({"text": "평가 기준은 기술 70점, 가격 30점이다.", "refs": ["S1"]}, {"text": "업계 평균보다 엄격하다.", "refs": []})
        found = blocks(result)
        self.assertEqual(found[0], {"type": "paragraph", "text": "평가 기준은 기술 70점, 가격 30점이다.", "refs": ["S1"]})
        self.assertEqual(found[1], {"type": "paragraph", "text": UNSUPPORTED_PREFIX + "업계 평균보다 엄격하다.", "refs": []})
        self.assertIn({"code": "UNSUPPORTED_CLAIM", "path": "sections[0].blocks[1]"}, result.warnings)
        self.assertEqual([e["ref_id"] for e in result.evidence], ["S1"])

    def test_unknown_label_is_not_a_citation(self):
        result = self.run_with({"text": "평가 기준은 기술 70점이다.", "refs": ["S1"]}, {"text": "심사위원은 5명이다.", "refs": ["S99"]})
        second = blocks(result)[1]
        self.assertEqual(second["refs"], [])
        self.assertTrue(second["text"].startswith(UNSUPPORTED_PREFIX))

    def test_number_not_in_the_cited_material_is_not_supported(self):
        result = self.run_with({"text": "평가 기준은 기술 70점이다.", "refs": ["S1"]}, {"text": "가격 점수는 45점이다.", "refs": ["S1"]})
        second = blocks(result)[1]
        self.assertEqual(second["refs"], [])
        self.assertTrue(second["text"].startswith(UNSUPPORTED_PREFIX))

    def test_every_block_with_refs_is_grounded_and_every_other_block_is_marked(self):
        result = self.run_with({"text": "평가 기준은 기술 70점이다.", "refs": ["S1", "S77"]}, {"text": "근거 부족: 이미 표시한 문장", "refs": []},
                               {"text": "추측 문장", "refs": None})
        for block in blocks(result):
            if block["refs"]:
                self.assertFalse(block["text"].startswith(UNSUPPORTED_PREFIX))
            else:
                self.assertTrue(block["text"].startswith(UNSUPPORTED_PREFIX))
                self.assertFalse(block["text"].startswith(UNSUPPORTED_PREFIX * 2))
        self.assertEqual(blocks(result)[0]["refs"], ["S1"])

    def test_report_with_no_grounded_sentence_fails(self):
        with self.assertRaises(StudioError) as caught:
            self.run_with({"text": "근거 없는 문장", "refs": []})
        self.assertEqual(caught.exception.code, "STUDIO_VALIDATION_FAILED")

    def test_summary_is_never_stored_uncited(self):
        result = self.run_with({"text": "평가 기준은 기술 70점이다.", "refs": ["S1"]})
        self.assertEqual(result.content["body"]["summary"], "")

    def test_writer_prompt_forbids_uncited_claims(self):
        llm = ScriptedLLM(plan("평가 기준"), GOOD)
        research, _ = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]))
        research.generate(ctx()[0])
        system = llm.prompts[1].system
        self.assertIn("refs", system)
        self.assertIn("데이터", system)  # 근거 구간 안의 지시문은 따르지 않는다


class ExportTests(unittest.TestCase):
    def test_research_report_exports_with_the_existing_report_exporters(self):
        from daon2_user_api.studio_v2_export import export_v2
        llm = ScriptedLLM(plan("평가 기준"), report({"text": "평가 기준은 기술 70점, 가격 30점이다.", "refs": ["S1"]}, {"text": "추측 문장", "refs": []}))
        research, _ = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]))
        result = research.generate(ctx(DOCS)[0])
        output = {"output_id": "sv2-" + "a" * 32, "type_id": "report", "title": "조사 보고서", "revision": {"revision_no": 1, "content": result.content},
                  "evidence": [{**row, "has_snapshot": True, "source_name": row["external_ref"]["name"]} for row in result.evidence]}
        markdown = export_v2("md", output).content.decode("utf-8")
        self.assertIn("평가 기준은 기술 70점", markdown)
        self.assertIn(UNSUPPORTED_PREFIX + "추측 문장", markdown)
        for name in ("docx", "pdf"):
            self.assertGreater(len(export_v2(name, output).content), 100)


class TimeoutAndCancelTests(unittest.TestCase):
    def test_timeout_before_writing_fails_with_research_timeout(self):
        clock = Clock()
        llm = ScriptedLLM(plan("평가 기준", "제출 서류"), GOOD, on_call=lambda n: setattr(clock, "now", clock.now + (601 if n == 1 else 0)))
        research, fake = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]), clock=clock)
        with self.assertRaises(StudioError) as caught:
            research.generate(ctx()[0])
        self.assertEqual(caught.exception.code, "RESEARCH_TIMEOUT")
        self.assertEqual(len(llm.prompts), 1)
        self.assertEqual(fake.calls, [])

    def test_slow_search_stops_the_remaining_steps(self):
        clock = Clock()
        connectors = FakeConnectors()
        original = connectors.call

        def slow(*args):
            clock.now += 400
            return original(*args)
        connectors.call = slow
        llm = ScriptedLLM(plan("평가 기준", "제출 서류", "일정"), GOOD)
        research, _ = generator(llm, connectors=connectors, scopes=FakeScopes([package("p-bid", "제안서")]), clock=clock)
        with self.assertRaises(StudioError) as caught:
            research.generate(ctx()[0])
        self.assertEqual(caught.exception.code, "RESEARCH_TIMEOUT")
        self.assertEqual(len(llm.prompts), 1)

    def test_model_calls_get_the_remaining_time_as_timeout(self):
        clock = Clock()
        llm = ScriptedLLM(plan("평가 기준"), GOOD, on_call=lambda n: setattr(clock, "now", clock.now + 100))
        research, _ = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]), clock=clock)
        research.generate(ctx()[0])
        self.assertLessEqual(llm.prompts[0].timeout_seconds, 600)
        self.assertLess(llm.prompts[1].timeout_seconds, llm.prompts[0].timeout_seconds)

    def test_model_failure_after_the_deadline_is_research_timeout(self):
        clock = Clock()

        def late(n):
            if n == 2:
                clock.now += 700
        llm = ScriptedLLM(plan("평가 기준"), StudioError("PROVIDER_UNAVAILABLE", 503), on_call=late)
        research, _ = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]), clock=clock)
        with self.assertRaises(StudioError) as caught:
            research.generate(ctx()[0])
        self.assertEqual(caught.exception.code, "RESEARCH_TIMEOUT")

    def test_model_failure_before_the_deadline_keeps_its_code(self):
        llm = ScriptedLLM(StudioError("PROVIDER_UNAVAILABLE", 503))
        research, _ = generator(llm)
        with self.assertRaises(StudioError) as caught:
            research.generate(ctx()[0])
        self.assertEqual(caught.exception.code, "PROVIDER_UNAVAILABLE")

    def test_cancel_during_finding_stops_without_writing(self):
        state = {"n": 0}

        def cancel():
            state["n"] += 1
            if state["n"] >= 2:
                raise StudioCancelled()
        llm = ScriptedLLM(plan("평가 기준", "제출 서류"), GOOD)
        research, fake = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]))
        with self.assertRaises(StudioCancelled):
            research.generate(ctx(cancel=cancel)[0])
        self.assertEqual(len(llm.prompts), 1)

    def test_cancel_via_progress_is_the_existing_path(self):
        def progress(pct, note):
            if note.startswith("찾기"):
                raise StudioCancelled()
        llm = ScriptedLLM(plan("평가 기준"), GOOD)
        research, fake = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]))
        context = GenerationContext(CTX, "sv2-x", "report", None, SETTINGS, (), "", "ko", "create", progress, lambda: None)
        with self.assertRaises(StudioCancelled):
            research.generate(context)
        self.assertEqual(fake.calls, [])


class FakeQueue:
    def __init__(self, cancel_on=None):
        self.notes = []
        self.finished = []
        self.retried = []
        self.cancel_on = cancel_on

    def start(self, job, worker):
        return job

    def heartbeat(self, job, worker, *, extend_seconds=900, progress_pct=None, note=None):
        if note is not None:
            self.notes.append((progress_pct, note))
        return self.cancel_on is not None and note is not None and note.startswith(self.cancel_on)

    def finish(self, job, worker, *, state, error_code=None):
        self.finished.append((state, error_code))

    def retry(self, job, worker, *, error_code):
        self.retried.append(error_code)
        return True


class WorkerRepo:
    def __init__(self):
        self.revisions = []

    def require_scope(self, *a):
        raise AssertionError("심층 조사는 노트북 소스 범위를 읽지 않는다")

    def get_customization(self, context):
        return {"instruction": ""}

    def add_revision(self, context, output_id, kind, content, **kw):
        self.revisions.append((kind, content, kw))

    def apply_generated_title(self, context, output_id, title):
        return True


class _Cloud:
    from contextlib import contextmanager

    @contextmanager
    def _transaction(self, scope):
        yield None


JOB = StudioV2Job("tenant-1", "workspace-001", "svj-1", "sv2-" + "a" * 32, "user-001", 1, 3, 1,
                  {"mode": "create", "type_id": "report", "format_id": "briefing", "settings": SETTINGS, "source_version_ids": [], "notebook_id": "notebook-1",
                   "trace_id": "trace-1", "policy_version": "policy-1"})


class PlainReport:
    type_id = "report"

    def __init__(self):
        self.calls = 0

    def generate(self, ctx):
        self.calls += 1
        raise AssertionError("일반 보고서 생성기를 쓰면 안 된다")


class WorkerTests(unittest.TestCase):
    def registry(self, research):
        registry = GeneratorRegistry()
        plain = PlainReport()
        registry.register(plain)
        if research is not None:
            registry.attach_research(research)
        return registry, plain

    def test_research_settings_route_to_the_research_generator_and_record_progress(self):
        research, _ = generator(ScriptedLLM(plan("평가 기준"), GOOD), scopes=FakeScopes([package("p-bid", "제안서")]))
        registry, plain = self.registry(research)
        queue, repo = FakeQueue(), WorkerRepo()
        StudioV2Worker(queue, repo, registry, _Cloud(), worker_id="w")._process(JOB)  # noqa: SLF001
        self.assertEqual(queue.finished, [("completed", None)])
        self.assertEqual([n for _p, n in queue.notes], ["계획", "찾기 1/1", "작성"])
        self.assertEqual(repo.revisions[0][1]["research"]["query"], QUERY)
        self.assertEqual(repo.revisions[0][2]["sources"], [])
        self.assertEqual(plain.calls, 0)

    def test_plain_report_still_uses_the_report_generator(self):
        registry, _ = self.registry(None)
        self.assertIsInstance(registry.resolve("report", {"focus": "x"}), PlainReport)

    def test_research_without_generator_is_type_unavailable(self):
        registry, _ = self.registry(None)
        queue = FakeQueue()
        StudioV2Worker(queue, WorkerRepo(), registry, _Cloud(), worker_id="w")._process(JOB)  # noqa: SLF001
        self.assertEqual(queue.finished, [("failed", "STUDIO_TYPE_UNAVAILABLE")])

    def test_timeout_fails_without_retry(self):
        clock = Clock()
        llm = ScriptedLLM(plan("평가 기준"), GOOD, on_call=lambda n: setattr(clock, "now", clock.now + 601))
        research, _ = generator(llm, scopes=FakeScopes([package("p-bid", "제안서")]), clock=clock)
        registry, _ = self.registry(research)
        queue = FakeQueue()
        StudioV2Worker(queue, WorkerRepo(), registry, _Cloud(), worker_id="w")._process(JOB)  # noqa: SLF001
        self.assertEqual(queue.finished, [("failed", "RESEARCH_TIMEOUT")])
        self.assertEqual(queue.retried, [])

    def test_cancel_request_finishes_as_cancelled(self):
        research, _ = generator(ScriptedLLM(plan("평가 기준"), GOOD), scopes=FakeScopes([package("p-bid", "제안서")]))
        registry, _ = self.registry(research)
        queue, repo = FakeQueue(cancel_on="찾기"), WorkerRepo()
        StudioV2Worker(queue, repo, registry, _Cloud(), worker_id="w")._process(JOB)  # noqa: SLF001
        self.assertEqual(queue.finished, [("cancelled", None)])
        self.assertEqual(repo.revisions, [])


class EgressTests(unittest.TestCase):
    """모델 호출은 StudioEgressGate, 도구 호출은 ConnectorEgressGate(knowledge_connector_service.call)를 거친다."""

    def connector_service(self):
        fake = FakeConnectors()
        gate = CountingGate()
        service = KnowledgeConnectorService(None, None, egress_gate=gate)
        views = {row["connector_id"]: {**row, "endpoint_url": f"https://{row['connector_id']}.example.com/mcp", "allowed_scopes": [], "version": 1}
                 for row in fake.rows}
        service.list = lambda context: [copy.deepcopy(row) for row in fake.rows]  # type: ignore[method-assign]
        service._client = lambda context, connector_id: (_Client(fake), dict(views[connector_id]))  # type: ignore[method-assign]  # noqa: SLF001
        return service, fake, gate

    def test_every_tool_call_and_every_model_call_pass_their_gates(self):
        from daon2_user_api.studio_egress import EgressDecision
        service, fake, connector_gate = self.connector_service()
        model_sizes = []

        class StudioGate:
            def authorize(self, context, model_, size):
                model_sizes.append(size)
                return EgressDecision(True, "policy_allowed")
        resolver = FakeResolver({"ms": model("CUSTOM", "https://media.example/v1", kind="external_api")})
        transport = FakeTransport([openai_reply(plan("평가 기준", "제출 서류")), openai_reply(GOOD)])
        llm = StudioTextGenerator(resolver, FakeCatalog([("ms", "m", "MS")]), transport=transport, egress_gate=StudioGate())
        research = ResearchGenerator(llm, DiscoverySearcher(service), FakeScopes([package("p-bid", "제안서")]), clock=Clock())
        with patch.object(connector_module, "_is_private_host", return_value=False):
            result = research.generate(ctx()[0])
        self.assertGreater(len(fake.calls), 0)
        self.assertEqual(connector_gate.calls, len(fake.calls))
        self.assertEqual(len(model_sizes), len(transport.calls))
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(result.content["research"]["tool_calls"], len(fake.calls))

    def test_denied_model_egress_means_no_model_call(self):
        from daon2_user_api.studio_egress import EgressDecision

        class Deny:
            def authorize(self, context, model_, size):
                return EgressDecision(False, "EGRESS_POLICY_DENIED")
        resolver = FakeResolver({"ms": model("CUSTOM", "https://media.example/v1", kind="external_api")})
        transport = FakeTransport([])
        llm = StudioTextGenerator(resolver, FakeCatalog([("ms", "m", "MS")]), transport=transport, egress_gate=Deny())
        connectors = FakeConnectors()
        research = ResearchGenerator(llm, DiscoverySearcher(connectors), FakeScopes(), clock=Clock())
        with self.assertRaises(StudioError):
            research.generate(ctx()[0])
        self.assertEqual(transport.calls, [])
        self.assertEqual(connectors.calls, [])


class OutputProgressTests(unittest.TestCase):
    def test_list_items_carry_progress_of_the_running_job(self):
        from daon2_user_api.studio_v2_postgres import _item
        now = "2026-11-24T00:00:00+00:00"
        row = ("sv2-" + "a" * 32, "report", "briefing", "조사", "generating", None, 0, 0, now, now, False, {"pct": 40, "note": "찾기 2/5"})
        self.assertEqual(_item(row)["progress"], {"pct": 40, "note": "찾기 2/5"})
        self.assertIsNone(_item(row[:11] + (None,))["progress"])

    def test_list_query_reads_the_running_job_progress(self):
        from daon2_user_api.studio_v2_postgres import _PROGRESS_SQL
        self.assertIn("studio_v2_jobs", _PROGRESS_SQL)
        self.assertIn("progress_note", _PROGRESS_SQL)
        self.assertIn("'leased','generating'", _PROGRESS_SQL)
        self.assertIn("chat_edit", _PROGRESS_SQL)  # 대화 수정 작업의 진행은 카드 진행이 아니다


if __name__ == "__main__":
    unittest.main()
