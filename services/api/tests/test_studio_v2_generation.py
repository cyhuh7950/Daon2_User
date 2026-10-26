from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from daon2_user_api.document_understanding_adapter import DocumentUnderstandingError
from daon2_user_api.studio_context_builder import build_pack
from daon2_user_api.studio_generators import (
    DataTableGenerator, FlashcardsGenerator, MindMapGenerator, QuizGenerator, ReportGenerator, SlidesGenerator,
)
from daon2_user_api.studio_source_reader import SourceSection, SourceText, split_sections
from daon2_user_api.studio_text_generation import StudioModelCatalog, StudioPrompt, StudioTextGenerator
from daon2_user_api.studio_v2_generation import GenerationContext, StudioCancelled
from daon2_user_api.studio_workspace import StudioContext, StudioError
from daon2_user_api.workspace_model_defaults import WorkspaceModelUnavailable

CTX = StudioContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1", "notebook-1")
TEXT_A = "보험금은 청구서류 접수일부터 3일 이내에 지급한다. 지급 한도는 1,000,000원이다."
TEXT_B = "면책 기간은 계약일부터 90일이다. 사고 발생 시 즉시 통지해야 한다."


def source(name="약관.pdf", version="sv-1", texts=(TEXT_A, TEXT_B)):
    sections = tuple(SourceSection(version, None, "page", str(i), None, t) for i, t in enumerate(texts, 1))
    return SourceText("src-1", version, name, sections, False)


class FakeReader:
    def __init__(self, sources=None):
        self._sources = sources or (source(),)

    def read(self, context, versions, **kw):
        return self._sources


class ScriptedLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def generate(self, context, prompt, cancel_check=None):
        self.prompts.append(prompt)
        data = self.responses.pop(0)
        return SimpleNamespace(data=data, usage={}, model_id="m", provider_code="CUSTOM", connection_short_code="MS")


def gen_ctx(type_id, settings=None, fmt=None, cancel=None):
    progress = []
    return GenerationContext(CTX, "sv2-x", type_id, fmt, settings or {}, ("sv-1",), "", "ko", "create",
                             lambda pct, note: progress.append((pct, note)), cancel or (lambda: None)), progress


class SectionSplitTests(unittest.TestCase):
    def test_pages_become_page_sections_with_span_lookup(self):
        sections, truncated = split_sections("sv-1", {"page_texts": ["첫 쪽", "둘째 쪽"]}, max_chars=1000, spans_by_page={2: "span-2"})
        self.assertEqual([(s.locator_kind, s.locator_value, s.evidence_span_id) for s in sections],
                         [("page", "1", None), ("page", "2", "span-2")])
        self.assertFalse(truncated)

    def test_markdown_headings_become_sections_and_limit_truncates(self):
        parser = {"markdown": "# 총칙\n내용 하나\n\n# 보장\n내용 둘"}
        sections, _ = split_sections("sv-1", parser, max_chars=1000)
        self.assertEqual([s.heading for s in sections], ["총칙", "보장"])
        sections, truncated = split_sections("sv-1", parser, max_chars=12)
        self.assertTrue(truncated)
        self.assertLessEqual(len(sections), 1)

    def test_long_page_is_chunked(self):
        sections, _ = split_sections("sv-1", {"page_texts": ["가" * 7000]}, max_chars=100_000)
        self.assertGreaterEqual(len(sections), 3)
        self.assertTrue(all(s.locator_value == "1" for s in sections))


class ContextBuilderTests(unittest.TestCase):
    def test_small_input_is_complete_and_labelled(self):
        pack = build_pack((source(),), budget_chars=10_000)
        self.assertEqual([p.ref for p in pack.passages], ["S1", "S2"])
        self.assertFalse(pack.truncated)
        self.assertIn('<source id="S1"', pack.render())

    def test_large_input_prefers_focus_and_keeps_order(self):
        texts = [f"일반 문단 {i} " + "가" * 400 for i in range(40)] + ["면책 기간 90일 특약 " + "나" * 100]
        pack = build_pack((source(texts=texts),), budget_chars=3000, focus="면책 기간")
        self.assertTrue(pack.truncated)
        self.assertTrue(any("면책 기간" in p.text for p in pack.passages))
        locators = [int(p.locator_value) for p in pack.passages]
        self.assertEqual(locators, sorted(locators))
        self.assertLessEqual(sum(len(p.text) for p in pack.passages), 3000 + 600)

    def test_evidence_rows_only_for_used_valid_refs(self):
        pack = build_pack((source(),), budget_chars=10_000)
        rows = pack.evidence_rows(["S2", "S9", "S2"])
        self.assertEqual([r["ref_id"] for r in rows], ["S2"])
        self.assertEqual(rows[0]["origin"], "notebook_source")


class GeneratorTests(unittest.TestCase):
    def test_report_two_phase_with_ref_cleaning_and_anchor_warning(self):
        llm = ScriptedLLM(
            {"title": "약관 요약", "summary": "요약", "sections": [{"heading": "지급", "purpose": "지급 기준", "refs": ["S1"]}]},
            {"blocks": [{"type": "paragraph", "text": "보험금은 3일 이내에 지급한다.", "refs": ["S1", "S99"]},
                        {"type": "bullets", "items": ["지급 한도 9,999원"], "refs": ["S1"]}]})
        ctx, progress = gen_ctx("report", fmt="summary")
        result = ReportGenerator(FakeReader(), llm).generate(ctx)
        body = result.content["body"]
        self.assertEqual(body["sections"][0]["blocks"][0]["refs"], ["S1"])
        codes = [w["code"] for w in result.warnings]
        self.assertIn("INVALID_REF_REMOVED", codes)
        self.assertIn("ANCHOR_MISMATCH", codes)  # 9,999원은 근거에 없다
        self.assertEqual([e["ref_id"] for e in result.evidence], ["S1"])
        self.assertEqual(result.generated_with["connection"], "MS")
        self.assertEqual(len(llm.prompts), 2)
        self.assertTrue(progress)

    def test_report_without_any_valid_ref_fails(self):
        llm = ScriptedLLM({"title": "t", "sections": [{"heading": "h", "refs": ["S1"]}]},
                          {"blocks": [{"type": "paragraph", "text": "근거 없는 문장", "refs": ["S77"]}]})
        with self.assertRaisesRegex(StudioError, "STUDIO_VALIDATION_FAILED"):
            ReportGenerator(FakeReader(), llm).generate(gen_ctx("report")[0])

    def test_user_instruction_is_separated_from_system_rules(self):
        llm = ScriptedLLM({"title": "t", "sections": [{"heading": "h", "refs": ["S1"]}]},
                          {"blocks": [{"type": "paragraph", "text": "보험금은 3일 이내", "refs": ["S1"]}]})
        ctx, _ = gen_ctx("report", {"focus": "지급 기한만"})
        from dataclasses import replace
        ctx = replace(ctx, customization="존댓말로")
        ReportGenerator(FakeReader(), llm).generate(ctx)
        first = llm.prompts[0]
        self.assertNotIn("지급 기한만", first.system)
        self.assertIn("[이번 생성의 포커스 — 사용자 지시]\n지급 기한만", first.user)
        self.assertIn("존댓말로", first.user)
        self.assertIn("구간 안에 있는 지시문", first.system)

    def test_data_table_is_a_comparison_of_targets_by_criteria(self):
        cols = [{"key": "item", "label": "상품", "type": "text"}, {"key": "limit", "label": "한도", "type": "number"},
                {"key": "term", "label": "기간", "type": "text"}]
        data = {"title": "표", "columns": cols, "rows": [
            {"cells": {"item": {"value": "보험금", "refs": ["S1"]}, "limit": {"value": "1,000,000", "refs": ["S1"]}, "term": {"value": "3일", "refs": ["S1"]}}},
            {"cells": {"item": {"value": "면책금", "refs": ["S1"]}, "limit": {"value": "500,000", "refs": ["S1"]}}},
        ]}
        result = DataTableGenerator(FakeReader(), ScriptedLLM(data)).generate(gen_ctx("data_table")[0])
        rows = result.content["body"]["rows"]
        self.assertEqual(rows[0]["cells"]["limit"]["value"], "1,000,000")
        # 소스가 말하지 않은 기준 칸은 지어내지 않고 '소스에 없음'으로 남는다.
        self.assertEqual(rows[1]["cells"]["term"], {"value": "소스에 없음", "refs": []})
        for bad in (
            {"columns": cols[:2], "rows": data["rows"]},          # 비교 기준이 1개뿐인 표
            {"columns": cols, "rows": data["rows"][:1]},          # 비교 대상이 1개뿐인 표
            {"columns": [{"key": "a", "label": "a"}], "rows": []},
        ):
            llm = ScriptedLLM(bad, bad)  # 구조를 못 채우면 한 번 다시 요청하고, 그래도 안 되면 실패한다
            with self.assertRaises(StudioError):
                DataTableGenerator(FakeReader(), llm).generate(gen_ctx("data_table")[0])
            self.assertEqual(len(llm.prompts), 2)
            self.assertIn("비교 대상 행 2개 이상", llm.prompts[1].user)
        retried = ScriptedLLM({"columns": cols[:2], "rows": data["rows"]}, data)
        result = DataTableGenerator(FakeReader(), retried).generate(gen_ctx("data_table")[0])
        self.assertEqual(len(result.content["body"]["rows"]), 2)

    def test_mind_map_builds_single_rooted_tree(self):
        data = {"nodes": [{"id": "r", "label": "약관", "parent": None}, {"id": "a", "label": "지급", "parent": "r", "refs": ["S1"]},
                          {"id": "b", "label": "면책", "parent": "r", "refs": ["S2"]}, {"id": "c", "label": "고아", "parent": "nope", "refs": ["S2"]}]}
        result = MindMapGenerator(FakeReader(), ScriptedLLM(data)).generate(gen_ctx("mind_map")[0])
        body = result.content["body"]
        self.assertEqual(body["root"], "r")
        parents = {n["id"]: n["parent"] for n in body["nodes"]}
        self.assertEqual(parents["r"], None)
        self.assertEqual(parents["c"], "r")  # 부모가 없는 노드는 루트에 붙는다

    def test_flashcards_dedupe_and_requires_refs(self):
        data = {"cards": [{"front": "지급 기한", "back": "3일", "refs": ["S1"]}, {"front": "지급  기한", "back": "중복", "refs": ["S1"]},
                          {"front": "면책", "back": "90일", "refs": ["S2"], "hint": "계약일"}]}
        result = FlashcardsGenerator(FakeReader(), ScriptedLLM(data)).generate(gen_ctx("flashcards", {"count": 5})[0])
        self.assertEqual([c["front"] for c in result.content["body"]["cards"]], ["지급 기한", "면책"])

    def test_quiz_rejects_bad_options(self):
        good = {"q": "지급 기한은?", "options": ["3일", "5일", "7일", "10일"], "answer_index": 0, "explanation": "3일 이내", "refs": ["S1"]}
        bad = {"q": "x", "options": ["a", "a", "b", "c"], "answer_index": 1, "refs": ["S1"]}
        result = QuizGenerator(FakeReader(), ScriptedLLM({"questions": [good, bad]})).generate(gen_ctx("quiz", {"count": 5})[0])
        self.assertEqual(len(result.content["body"]["questions"]), 1)

    def test_quiz_item_requires_question_answer_and_explanation(self):
        base = {"q": "지급 기한은?", "options": ["3일", "5일", "7일", "10일"], "answer_index": 0, "refs": ["S1"]}
        result = QuizGenerator(FakeReader(), ScriptedLLM({"questions": [{**base, "explanation": "3일 이내"}, base]})).generate(gen_ctx("quiz", {"count": 5})[0])
        questions = result.content["body"]["questions"]
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["explanation"], "3일 이내")

    def test_slides_after_the_cover_are_chapters_with_key_points(self):
        data = {"title": "발표", "slides": [{"layout": "title", "title": "표지", "bullets": [], "refs": []},
                                          {"layout": "bullets", "title": "빈 챕터", "bullets": [], "refs": ["S1"]},
                                          {"layout": "bullets", "title": "지급", "bullets": ["3일 이내 지급"], "refs": ["S1"]}]}
        result = SlidesGenerator(FakeReader(), ScriptedLLM(data)).generate(gen_ctx("slides", {"length": "short"})[0])
        self.assertEqual([slide["title"] for slide in result.content["body"]["slides"]], ["표지", "지급"])

    def test_slides_first_slide_is_title_and_limits_bullets(self):
        data = {"title": "발표", "slides": [{"layout": "bullets", "title": "표지", "bullets": [], "refs": []},
                                          {"layout": "bullets", "title": "지급", "bullets": [f"항목 {i}" for i in range(9)], "refs": ["S1"], "notes": "노트"}]}
        result = SlidesGenerator(FakeReader(), ScriptedLLM(data)).generate(gen_ctx("slides", {"length": "short"})[0])
        slides = result.content["body"]["slides"]
        self.assertEqual(slides[0]["layout"], "title")
        self.assertEqual(len(slides[1]["bullets"]), 5)

    def test_cancel_check_stops_generation(self):
        def cancel():
            raise StudioCancelled()
        with self.assertRaises(StudioCancelled):
            MindMapGenerator(FakeReader(), ScriptedLLM({})).generate(gen_ctx("mind_map", cancel=cancel)[0])


class FakeCatalog(StudioModelCatalog):
    def __init__(self, candidates):
        self._c = candidates

    def candidates(self, context):
        return self._c


class FakeResolver:
    def __init__(self, models, unavailable=()):
        self.models = models
        self.unavailable = set(unavailable)
        self.calls = []

    @contextmanager
    def resolve(self, context, capability, *, connection_id=None, model_id=None):
        self.calls.append(connection_id)
        if connection_id in self.unavailable:
            raise WorkspaceModelUnavailable("PROVIDER_CREDENTIAL_REQUIRED")
        yield self.models[connection_id]


def model(code, base, key="k", kind="local"):
    return SimpleNamespace(provider_code=code, model_id=f"{code}-model", base_url=base, credential_text=lambda required=False: key, provider_kind=kind)


class FakeTransport:
    def __init__(self, behaviours):
        self.behaviours = behaviours
        self.calls = []

    def _next(self, kind, url, payload):
        self.calls.append((kind, url, payload))
        behaviour = self.behaviours.pop(0)
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour

    def post_json(self, *, url, api_key, payload, timeout_seconds):
        return self._next("auth", url, payload)

    def post_json_no_auth(self, *, url, payload, timeout_seconds):
        return self._next("noauth", url, payload)


def openai_reply(data):
    return {"choices": [{"message": {"content": json.dumps(data)}}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}}


PROMPT = StudioPrompt("sys", "user", {"type": "object"}, 100)


class TextGenerationTests(unittest.TestCase):
    def test_priority_order_and_failover_to_next_provider(self):
        resolver = FakeResolver({"c-ms": model("CUSTOM", "https://media.example/v1"), "c-us": model("UPSTAGE", "https://api.upstage.example/v1"),
                                 "c-ol": model("OLLAMA", "https://ollama.example")}, unavailable={"c-us"})
        transport = FakeTransport([DocumentUnderstandingError("UNDERSTANDING_PROVIDER_UNAVAILABLE", status=503, retryable=True),
                                   {"message": {"content": json.dumps({"ok": True})}, "prompt_eval_count": 3, "eval_count": 4}])
        generator = StudioTextGenerator(resolver, FakeCatalog([("c-ms", "m", "MS"), ("c-us", "m", "US"), ("c-ol", "m", "OL")]), transport=transport)
        result = generator.generate(CTX, PROMPT)
        self.assertEqual(resolver.calls, ["c-ms", "c-us", "c-ol"])
        self.assertEqual((result.connection_short_code, result.provider_code, dict(result.data)), ("OL", "OLLAMA", {"ok": True}))
        self.assertEqual(transport.calls[0][1], "https://media.example/v1/chat/completions")
        self.assertEqual(transport.calls[1][1], "https://ollama.example/api/chat")
        self.assertEqual(transport.calls[1][2]["format"], {"type": "object"})
        self.assertEqual(result.usage, {"prompt_tokens": 3, "completion_tokens": 4})

    def test_json_retry_once_then_next_provider(self):
        resolver = FakeResolver({"a": model("CUSTOM", "https://a.example/v1"), "b": model("OMNIROUTE", "https://b.example/v1")})
        transport = FakeTransport([openai_reply("not json"), {"choices": [{"message": {"content": "still bad"}}]}, openai_reply({"x": 1})])
        result = StudioTextGenerator(resolver, FakeCatalog([("a", "m", "MS"), ("b", "m", "AF")]), transport=transport).generate(CTX, PROMPT)
        self.assertEqual(result.connection_short_code, "AF")
        self.assertIn("형식 오류", transport.calls[1][2]["messages"][1]["content"])

    def test_json_retry_succeeds_on_same_provider(self):
        resolver = FakeResolver({"a": model("CUSTOM", "https://a.example/v1")})
        transport = FakeTransport([openai_reply("bad"), openai_reply({"x": 1})])
        result = StudioTextGenerator(resolver, FakeCatalog([("a", "m", "MS")]), transport=transport).generate(CTX, PROMPT)
        self.assertEqual(dict(result.data), {"x": 1})
        self.assertEqual(len(transport.calls), 2)

    def test_all_providers_failing_raises_unavailable(self):
        resolver = FakeResolver({"a": model("CUSTOM", "https://a.example/v1")})
        transport = FakeTransport([DocumentUnderstandingError("UNDERSTANDING_PROVIDER_UNAVAILABLE", status=503, retryable=True)])
        with self.assertRaisesRegex(StudioError, "PROVIDER_UNAVAILABLE"):
            StudioTextGenerator(resolver, FakeCatalog([("a", "m", "MS")]), transport=transport).generate(CTX, PROMPT)
        with self.assertRaisesRegex(StudioError, "PROVIDER_UNAVAILABLE"):
            StudioTextGenerator(resolver, FakeCatalog([]), transport=transport).generate(CTX, PROMPT)

    def test_authenticated_call_uses_key_and_keyless_does_not(self):
        resolver = FakeResolver({"a": model("CUSTOM", "https://a.example/v1", key="secret"), "b": model("CUSTOM", "https://b.example/v1", key=None)})
        transport = FakeTransport([openai_reply({"x": 1}), openai_reply({"x": 1})])
        generator = StudioTextGenerator(resolver, FakeCatalog([("a", "m", "MS")]), transport=transport)
        generator.generate(CTX, PROMPT)
        StudioTextGenerator(resolver, FakeCatalog([("b", "m", "MS")]), transport=transport).generate(CTX, PROMPT)
        self.assertEqual([c[0] for c in transport.calls], ["auth", "noauth"])

    def test_external_provider_needs_gate_and_policy_else_falls_back_to_local(self):
        from daon2_user_api.studio_egress import EgressDecision
        resolver = FakeResolver({"ms": model("CUSTOM", "https://media.example/v1", kind="external_api"),
                                 "ol": model("OLLAMA", "https://ollama.example", kind="local")})
        catalog = FakeCatalog([("ms", "m", "MS"), ("ol", "m", "OL")])
        # 게이트가 없으면 외부는 쓰지 않는다
        transport = FakeTransport([{"message": {"content": json.dumps({"ok": 1})}}])
        result = StudioTextGenerator(resolver, catalog, transport=transport).generate(CTX, PROMPT)
        self.assertEqual(result.connection_short_code, "OL")
        # 정책이 거부하면 다음 후보
        class Deny:
            def authorize(self, context, model, size):
                return EgressDecision(False, "EGRESS_POLICY_DENIED")
        transport = FakeTransport([{"message": {"content": json.dumps({"ok": 1})}}])
        result = StudioTextGenerator(resolver, catalog, transport=transport, egress_gate=Deny()).generate(CTX, PROMPT)
        self.assertEqual(result.connection_short_code, "OL")
        self.assertEqual(len(transport.calls), 1)

    def test_external_provider_allowed_masks_personal_data_and_reports_size(self):
        from daon2_user_api.studio_egress import EgressDecision
        sizes = []
        class Allow:
            def authorize(self, context, model, size):
                sizes.append(size)
                return EgressDecision(True, "policy_allowed", masked=True)
        resolver = FakeResolver({"ms": model("CUSTOM", "https://media.example/v1", kind="external_api")})
        transport = FakeTransport([openai_reply({"x": 1})])
        prompt = StudioPrompt("sys", "연락처 010-1234-5678, 이메일 a@b.co, 주민 900101-1234567", {"type": "object"}, 100)
        result = StudioTextGenerator(resolver, FakeCatalog([("ms", "m", "MS")]), transport=transport, egress_gate=Allow()).generate(CTX, prompt)
        sent = transport.calls[0][2]["messages"][1]["content"]
        self.assertNotIn("010-1234-5678", sent)
        self.assertNotIn("a@b.co", sent)
        self.assertNotIn("900101-1234567", sent)
        self.assertIn("[전화번호]", sent)
        self.assertEqual(result.usage.get("masked"), 1)
        self.assertGreater(sizes[0], 0)

    def test_gate_checks_policy_destination_kind_and_size(self):
        from daon2_user_api.studio_egress import StudioEgressGate
        def effective(**kw):
            base = dict(mode="allow_approved_external", allowed_provider_kinds=("external_api",), allowed_destinations=("media.example",),
                        max_bytes=1000, masking_required=True, redaction_required=False, required_approver="none")
            base.update(kw)
            return SimpleNamespace(**base)
        class Service:
            def __init__(self, eff):
                self.eff = eff
            def get_effective(self, ctx):
                return self.eff
        ext = model("CUSTOM", "https://media.example/v1", kind="external_api")
        self.assertTrue(StudioEgressGate(Service(effective())).authorize(CTX, ext, 500).allowed)
        self.assertTrue(StudioEgressGate(Service(effective())).authorize(CTX, ext, 500).masked)
        for eff, size, reason in ((effective(mode="deny_external"), 10, "EGRESS_POLICY_DENIED"),
                                  (effective(allowed_destinations=("other.example",)), 10, "EGRESS_DESTINATION_DENIED"),
                                  (effective(allowed_provider_kinds=()), 10, "EGRESS_DESTINATION_DENIED"),
                                  (effective(required_approver="organization_admin"), 10, "EGRESS_APPROVAL_REQUIRED"),  # 추가 인증 후 허용: 백그라운드 생성은 외부 전송 안 함
                                  (effective(), 5000, "EGRESS_MAX_BYTES_EXCEEDED")):
            decision = StudioEgressGate(Service(eff)).authorize(CTX, ext, size)
            self.assertEqual((decision.allowed, decision.reason), (False, reason))
        self.assertTrue(StudioEgressGate(None).authorize(CTX, model("OLLAMA", "https://o.example"), 10**9).allowed)
        self.assertFalse(StudioEgressGate(None).authorize(CTX, ext, 1).allowed)

    def test_catalog_priority_env(self):
        import os
        from unittest import mock
        from daon2_user_api.studio_text_generation import provider_priority
        self.assertEqual(provider_priority(), ("MS", "US", "AF", "OL"))
        with mock.patch.dict(os.environ, {"DAON_STUDIO_PROVIDER_PRIORITY": "ol, ms"}):
            self.assertEqual(provider_priority(), ("OL", "MS"))
        with mock.patch.dict(os.environ, {"DAON_STUDIO_PROVIDER_PRIORITY": "TOOLONG"}):
            with self.assertRaises(ValueError):
                provider_priority()


if __name__ == "__main__":
    unittest.main()
