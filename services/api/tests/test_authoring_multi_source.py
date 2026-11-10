from __future__ import annotations

import unittest
from types import SimpleNamespace

from daon2_user_api.authoring import session as S
from daon2_user_api.authoring.rfp import MAX_WINDOWS, scan_requirements
from daon2_user_api.authoring.templates import AuthoringError
from daon2_user_api.studio_source_reader import SourceSection, SourceText

try:
    from tests.test_authoring import CTX, REGISTRY, TEMPLATE, ctx_for
except ModuleNotFoundError:
    from test_authoring import CTX, REGISTRY, TEMPLATE, ctx_for


BUDGET = 1000


def source(version: str, name: str, *texts: str, truncated: bool = False) -> SourceText:
    return SourceText("src-" + version, version, name,
                      tuple(SourceSection(version, None, "page", str(i), None, text) for i, text in enumerate(texts, 1)), truncated)


class Llm:
    def __init__(self, replies=None, fail_on=()):
        self.prompts, self.replies, self.fail_on = [], dict(replies or {}), set(fail_on)

    def generate(self, context, prompt, cancel_check=None):
        self.prompts.append(prompt.user)
        number = len(self.prompts)
        if number in self.fail_on:
            raise RuntimeError("provider down")
        return SimpleNamespace(data={"requirements": [{"text": text, "mandatory": True, "category": ""} for text in self.replies.get(number, [])]})


def scan(sources, llm=None, **options):
    return scan_requirements(sources, llm or Llm(), CTX, budget_chars=BUDGET, **options)


class ScanRequirementsTests(unittest.TestCase):
    def test_every_part_of_a_long_file_is_read(self):
        texts = [f"{'가' * 700}\n항목 {n} 내용을 반드시 제출해야 한다" for n in range(5)]
        llm = Llm()
        requirements, warnings = scan([source("v1", "rfp.pdf", *texts)], llm)
        self.assertEqual(len(llm.prompts), 5)
        self.assertEqual(len(requirements), 5)
        self.assertIn("항목 4", requirements[-1]["text"])
        self.assertEqual(warnings, [])

    def test_sections_that_fit_share_one_call(self):
        llm = Llm()
        scan([source("v1", "rfp.pdf", "짧은 첫 구간", "짧은 둘째 구간")], llm)
        self.assertEqual(len(llm.prompts), 1)

    def test_each_file_is_read_and_its_name_is_recorded(self):
        llm = Llm()
        requirements, _ = scan([source("v1", "공고서.pdf", "보안 점검 결과를 제출해야 한다"), source("v2", "안내서.pdf", "교육 계획을 포함해야 한다")], llm)
        self.assertEqual(len(llm.prompts), 2)
        self.assertEqual([r["source_name"] for r in requirements], ["공고서.pdf", "안내서.pdf"])

    def test_same_requirement_in_two_files_is_kept_once(self):
        line = "제안사는 사업 수행 계획서를 기한 내에 제출해야 한다"
        requirements, _ = scan([source("v1", "a.pdf", line), source("v2", "b.pdf", "  " + line + "  ")])
        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0]["source_name"], "a.pdf")

    def test_similar_wording_across_files_is_merged(self):
        requirements, _ = scan([source("v1", "a.pdf", "제안사는 사업 수행 계획서를 기한 내에 제출해야 한다"),
                                source("v2", "b.pdf", "제안사는 사업 수행 계획서를 기한 내에 반드시 제출해야 한다")])
        self.assertEqual(len(requirements), 1)

    def test_a_short_requirement_is_not_lost_inside_a_longer_one_from_another_file(self):
        requirements, _ = scan([source("v1", "a.pdf", "제안사는 사업 수행 계획서와 보안 계획서와 교육 계획서를 기한 내에 제출해야 한다"),
                                source("v2", "b.pdf", "보안 계획서를 제출해야 한다")])
        self.assertEqual(len(requirements), 2)

    def test_model_findings_are_added_without_repeating_rules(self):
        llm = Llm({1: ["제안사는 사업 수행 계획서를 제출해야 한다", "하자 보수 기간은 일년으로 한다"]})
        requirements, _ = scan([source("v1", "a.pdf", "제안사는 사업 수행 계획서를 제출해야 한다")], llm)
        self.assertEqual(len(requirements), 2)
        self.assertEqual(requirements[1]["source_name"], "a.pdf")

    def test_original_ids_colliding_between_files_stay_unique(self):
        requirements, _ = scan([source("v1", "a.pdf", "SFR-001 첫 파일의 기능 요구사항 설명"), source("v2", "b.pdf", "SFR-001 둘째 파일의 전혀 다른 성능 조건")])
        self.assertEqual(len({r["id"] for r in requirements}), 2)
        self.assertEqual(requirements[0]["id"], "SFR-001")

    def test_a_failed_model_call_keeps_rule_results_and_warns(self):
        llm = Llm(fail_on={1})
        requirements, warnings = scan([source("v1", "a.pdf", "보안 점검 결과를 제출해야 한다")], llm)
        self.assertEqual(len(requirements), 1)
        self.assertEqual(warnings, ["REQUIREMENTS_MODEL_PARTIAL:1"])

    def test_truncated_file_and_window_limit_are_reported(self):
        texts = ["가" * 900 for _ in range(MAX_WINDOWS + 3)]
        llm = Llm()
        _, warnings = scan([source("v1", "긴파일.pdf", *texts, truncated=True)], llm)
        self.assertEqual(len(llm.prompts), MAX_WINDOWS)
        self.assertIn("REQUIREMENTS_SOURCE_TRUNCATED:긴파일.pdf", warnings)
        self.assertIn(f"REQUIREMENTS_WINDOW_LIMIT:{MAX_WINDOWS}", warnings)

    def test_cancel_is_checked_for_each_part(self):
        class Stop(Exception):
            pass
        calls = []

        def cancel():
            calls.append(1)
            if len(calls) == 2:
                raise Stop
        llm = Llm()
        with self.assertRaises(Stop):
            scan([source("v1", "a.pdf", "가" * 900, "나" * 900, "다" * 900)], llm, cancel_check=cancel)
        self.assertEqual(len(llm.prompts), 1)


class SessionInputTests(unittest.TestCase):
    def fresh(self):
        return S.new_session(TEMPLATE, request_text="RFP 제안서")

    def test_several_files_can_be_chosen(self):
        session = S.apply_answers(TEMPLATE, self.fresh(), [{"key": "rfp_document", "source_version_ids": ["sv-a", "sv-b", "sv-a"]}])
        self.assertEqual(session["inputs"]["rfp_document"], {"source_version_ids": ["sv-a", "sv-b"]})
        self.assertEqual(S.source_versions(session["inputs"]["rfp_document"]), ["sv-a", "sv-b"])

    def test_single_file_answer_still_works(self):
        session = S.apply_answers(TEMPLATE, self.fresh(), [{"key": "rfp_document", "source_version_id": "sv-a"}])
        self.assertEqual(S.source_versions(session["inputs"]["rfp_document"]), ["sv-a"])

    def test_sessions_saved_before_this_change_still_read(self):
        self.assertEqual(S.source_versions({"source_version_id": "sv-old"}), ["sv-old"])

    def test_invalid_file_lists_are_rejected(self):
        for bad in ([], ["bad id"], "sv-a", [1], [f"sv-{n}" for n in range(11)]):
            with self.subTest(bad=bad), self.assertRaises(AuthoringError):
                S.apply_answers(TEMPLATE, self.fresh(), [{"key": "rfp_document", "source_version_ids": bad}])

    def test_review_keeps_the_source_file_name(self):
        cleaned = S.validate_review_edit([{"id": "REQ-001", "text": "내용", "source_name": "공고서.pdf"}, {"id": "REQ-002", "text": "추가"}])
        self.assertEqual(cleaned[0]["source_name"], "공고서.pdf")
        self.assertNotIn("source_name", cleaned[1])

    def test_review_accepts_a_long_requirement_list(self):
        self.assertEqual(len(S.validate_review_edit([{"id": f"REQ-{n}", "text": "내용"} for n in range(1000)])), 1000)
        with self.assertRaises(AuthoringError):
            S.validate_review_edit([{"id": f"REQ-{n}", "text": "내용"} for n in range(1001)])


class PipelineTests(unittest.TestCase):
    def pipeline(self, reader, llm):
        from daon2_user_api.authoring.pipeline import AuthoringPipeline
        return AuthoringPipeline(REGISTRY, reader, llm, SimpleNamespace(), lambda *_: {}, context_chars=BUDGET)

    def test_agent_analysis_reads_every_chosen_file_in_full(self):
        calls = []

        class Reader:
            def read(self, context, versions, **options):
                calls.append((list(versions), options))
                return (source("sv-a", "a.pdf", "보안 점검 결과를 제출해야 한다"), source("sv-b", "b.pdf", "교육 계획을 포함해야 한다", truncated=True))

        class OutlineLlm(Llm):
            def generate(self, context, prompt, cancel_check=None):
                if prompt.schema_name == "authoring_outline":
                    return SimpleNamespace(data={})
                return super().generate(context, prompt, cancel_check)
        session = S.new_session(TEMPLATE, request_text="RFP", mode="agent")
        session = S.apply_answers(TEMPLATE, session, [{"key": "rfp_document", "source_version_ids": ["sv-a", "sv-b"]}], skip_remaining=True)
        result = self.pipeline(Reader(), OutlineLlm()).analyze(ctx_for("analyze")[0], session)
        self.assertEqual(calls[0][0], ["sv-a", "sv-b"])
        self.assertEqual(calls[0][1]["max_chars_per_source"], MAX_WINDOWS * BUDGET)
        self.assertEqual({r["source_name"] for r in result["requirements"]}, {"a.pdf", "b.pdf"})
        self.assertEqual(result["analysis_warnings"], ["REQUIREMENTS_SOURCE_TRUNCATED:b.pdf"])
        self.assertEqual(result["state"], "review")

    def test_writing_prompt_keeps_the_requirement_list_bounded(self):
        from daon2_user_api.authoring import pipeline as P
        from daon2_user_api.studio_context_builder import ContextPack

        class Stop(Exception):
            pass
        seen = []

        class CaptureLlm:
            def generate(self, context, prompt, cancel_check=None):
                seen.append(prompt.user)
                raise Stop
        pipeline = self.pipeline(SimpleNamespace(), CaptureLlm())
        pipeline._gather_unit = lambda *_: []
        requirements = [{"id": f"REQ-{n}", "text": f"요구사항 번호 {n} " + "가" * 80} for n in range(500)]
        unit = {"key": "u1", "section_key": "s1", "section_title": "절", "title": "소목차", "purpose": "목적", "target_chars": 500, "status": "pending"}
        session = {"units": [unit], "inputs": {}, "requirements": requirements, "plan": {"sections": [{"key": "s1", "requirement_ids": [r["id"] for r in requirements]}]}}
        with self.assertRaises(Stop):
            pipeline._write_unit(ctx_for("generate")[0], session, TEMPLATE, unit, ContextPack((), False, 0), [])
        self.assertIn("요구사항 번호 0 ", seen[0])
        self.assertNotIn("요구사항 번호 499 ", seen[0])
        self.assertLess(len(seen[0]), P.UNIT_REQUIREMENT_CHARS + 2000)


if __name__ == "__main__":
    unittest.main()
