"""WO-N8 웹 페이지 생성기(1단계 내용 JSON → 2단계 HTML, 한 번 재시도, 진행 문구)."""

from __future__ import annotations

import json
import unittest

from daon2_user_api.studio_generators import WebPageGenerator, build_registry, render_web_page_html
from daon2_user_api.studio_text_generation import StudioTextGenerator
from daon2_user_api.studio_workspace import StudioError
from test_studio_v2_generation import (
    CTX, FakeCatalog, FakeReader, FakeResolver, FakeTransport, ScriptedLLM, gen_ctx, model, openai_reply,
)

STAGE1 = {
    "title": "보험 안내",
    "sections": [
        {"heading": "지급", "blocks": [
            {"type": "paragraph", "text": "보험금은 3일 이내에 지급한다.", "refs": ["S1"]},
            {"type": "metric", "label": "지급 한도", "value": "1,000,000원", "refs": ["S1"]},
            {"type": "paragraph", "text": "근거없는비밀문장 777", "refs": ["S99"]},
        ]},
        {"heading": "면책", "blocks": [
            {"type": "bullets", "items": ["면책 기간 90일"], "refs": ["S2"]},
        ]},
    ],
}
GOOD = ("<html><body><h1>보험 안내</h1><h2>지급</h2><p data-ref=\"S1\">보험금은 3일 이내에 지급한다.</p>"
        "<p>지급 한도 1,000,000원</p><h2>면책</h2><ul><li data-ref=\"S2\">면책 기간 90일</li></ul></body></html>")
BAD = GOOD.replace("</ul>", "</ul><p>추가 수치 4,500명</p>")
SETTINGS = {"page_request": "보험 안내 페이지를 만들어 주세요"}


def run(*responses, settings=None):
    llm = ScriptedLLM(*responses)
    ctx, progress = gen_ctx("web_page", SETTINGS if settings is None else settings)
    result = WebPageGenerator(FakeReader(), llm).generate(ctx)
    return result, llm, progress


class WebPageGeneratorTests(unittest.TestCase):
    def test_two_stage_success_stores_sections_and_html(self):
        result, llm, _ = run(STAGE1, {"html": GOOD})
        body = result.content["body"]
        self.assertIn("Content-Security-Policy", body["html"])
        self.assertIn("data-daon-bridge", body["html"])
        self.assertEqual([s["heading"] for s in body["sections"]], ["지급", "면책"])
        self.assertEqual(body["request"], SETTINGS["page_request"])
        self.assertEqual(result.content["schema"], "studio.web_page.v1")
        self.assertEqual(len(llm.prompts), 2)
        stage2 = llm.prompts[1]
        self.assertEqual(stage2.json_schema["required"], ["html"])
        self.assertEqual(stage2.max_output_tokens, 8000)
        self.assertNotEqual(stage2.prompt_version, llm.prompts[0].prompt_version)
        self.assertEqual({e["ref_id"] for e in result.evidence}, {"S1", "S2"})

    def test_stage2_prompt_excludes_insufficient_blocks(self):
        _, llm, _ = run(STAGE1, {"html": GOOD})
        stage2 = llm.prompts[1].system + llm.prompts[1].user
        self.assertNotIn("근거없는비밀문장", stage2)
        self.assertNotIn("<source", stage2)
        self.assertNotIn("청구서류 접수일부터", stage2)  # 소스 원문(블록에 쓰지 않은 부분)
        self.assertNotIn("사고 발생 시 즉시 통지", stage2)
        self.assertIn("면책 기간 90일", stage2)
        self.assertIn(SETTINGS["page_request"], stage2)
        self.assertIn("<script>", llm.prompts[1].system)  # 스크립트 금지 지시
        self.assertIn("data-tab", llm.prompts[1].system)

    def test_stage2_retry_once_then_success(self):
        result, llm, _ = run(STAGE1, {"html": BAD}, {"html": GOOD})
        self.assertEqual(len(llm.prompts), 3)
        self.assertIn("4500", llm.prompts[2].user)  # 넘친 숫자를 재시도 안내에 붙인다
        self.assertNotIn("4,500명", result.content["body"]["html"])

    def test_stage2_fails_after_second_failure(self):
        with self.assertRaisesRegex(StudioError, "STUDIO_VALIDATION_FAILED"):
            run(STAGE1, {"html": BAD}, {"html": BAD})

    def test_missing_heading_retry_lists_heading(self):
        stage1 = json.loads(json.dumps(STAGE1))
        stage1["sections"][1]["heading"] = "제외 조건"
        good = GOOD.replace("<h2>면책</h2>", "<h2>제외 조건</h2>")
        no_heading = GOOD.replace("<h2>면책</h2>", "")
        _, llm, _ = run(stage1, {"html": no_heading}, {"html": good})
        self.assertEqual(len(llm.prompts), 3)
        self.assertIn("제외 조건", llm.prompts[2].user.split("[직전 결과 검사 실패]")[1])

    def test_all_insufficient_fails_without_stage2_call(self):
        data = {"title": "t", "sections": [{"heading": "h", "blocks": [{"type": "paragraph", "text": "근거 없음", "refs": ["S77"]}]}]}
        llm = ScriptedLLM(data)
        with self.assertRaisesRegex(StudioError, "STUDIO_VALIDATION_FAILED"):
            WebPageGenerator(FakeReader(), llm).generate(gen_ctx("web_page", SETTINGS)[0])
        self.assertEqual(len(llm.prompts), 1)

    def test_render_without_verified_sections_does_not_call_model(self):
        llm = ScriptedLLM()
        body = {"title": "t", "sections": [{"heading": "h", "blocks": [{"type": "paragraph", "text": "x", "refs": [], "insufficient": True}]}]}
        with self.assertRaisesRegex(StudioError, "STUDIO_VALIDATION_FAILED"):
            render_web_page_html(llm, CTX, body, "요청", cancel_check=lambda: None)
        self.assertEqual(llm.prompts, [])

    def test_empty_request_rejected(self):
        for settings in ({}, {"page_request": "   "}):
            llm = ScriptedLLM(STAGE1)
            with self.assertRaises(StudioError) as caught:
                WebPageGenerator(FakeReader(), llm).generate(gen_ctx("web_page", settings)[0])
            self.assertEqual(caught.exception.code, "STUDIO_INPUT_INVALID")
            self.assertEqual(llm.prompts, [])

    def test_progress_notes(self):
        _, _, progress = run(STAGE1, {"html": GOOD})
        notes = [note for _, note in progress]
        self.assertIn("내용 만드는 중", notes)
        self.assertIn("페이지 만드는 중", notes)
        self.assertLess(notes.index("내용 만드는 중"), notes.index("페이지 만드는 중"))

    def test_registered_in_registry(self):
        registry = build_registry(FakeReader(), ScriptedLLM())
        self.assertIsInstance(registry.get("web_page"), WebPageGenerator)

    def test_llm_call_count_equals_egress_decisions(self):
        from daon2_user_api.studio_egress import EgressDecision
        sizes = []

        class Gate:
            def authorize(self, context, model_, size):
                sizes.append(size)
                return EgressDecision(True, "policy_allowed")
        resolver = FakeResolver({"ms": model("CUSTOM", "https://media.example/v1", kind="external_api")})
        transport = FakeTransport([openai_reply(STAGE1), openai_reply({"html": BAD}), openai_reply({"html": GOOD})])
        llm = StudioTextGenerator(resolver, FakeCatalog([("ms", "m", "MS")]), transport=transport, egress_gate=Gate())
        result = WebPageGenerator(FakeReader(), llm).generate(gen_ctx("web_page", SETTINGS)[0])
        self.assertIn("data-daon-bridge", result.content["body"]["html"])
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(len(sizes), len(transport.calls))
        sent = transport.calls[1][2]["response_format"]["json_schema"]["schema"]
        self.assertEqual(json.loads(json.dumps(sent))["required"], ["html"])


class _Reply:
    def __init__(self, data):  # type: ignore[no-untyped-def]
        self.data, self.usage, self.model_id, self.provider_code, self.connection_short_code = data, {}, "m", "CUSTOM", "MS"


class FormatLLM(ScriptedLLM):
    """응답 자리에 예외를 두면 그 예외를 낸다(2단계 형식 오류 흉내)."""

    def generate(self, context, prompt, cancel_check=None):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        data = self.responses.pop(0)
        if isinstance(data, Exception):
            raise data
        return _Reply(data)


def run_format(*responses):  # type: ignore[no-untyped-def]
    llm = FormatLLM(*responses)
    result = WebPageGenerator(FakeReader(), llm).generate(gen_ctx("web_page", SETTINGS)[0])
    return result, llm


class Stage2FormatErrorTests(unittest.TestCase):
    """최종 검토 I6: 2단계 응답 형식 오류도 한 번뿐인 재시도 안에서 센다."""

    def test_format_error_then_success(self):
        result, llm = run_format(STAGE1, StudioError("STUDIO_VALIDATION_FAILED", 502), {"html": GOOD})
        self.assertEqual(len(llm.prompts), 3)
        self.assertIn("[직전 결과 검사 실패]", llm.prompts[2].user)
        self.assertIn("data-daon-bridge", result.content["body"]["html"])

    def test_format_error_twice_fails(self):
        with self.assertRaises(StudioError) as caught:
            run_format(STAGE1, StudioError("STUDIO_VALIDATION_FAILED", 502), StudioError("STUDIO_VALIDATION_FAILED", 502))
        self.assertEqual(caught.exception.code, "STUDIO_VALIDATION_FAILED")

    def test_format_error_then_check_failure_fails_without_third_call(self):
        llm = FormatLLM(STAGE1, StudioError("STUDIO_VALIDATION_FAILED", 502), {"html": BAD}, {"html": GOOD})
        with self.assertRaisesRegex(StudioError, "STUDIO_VALIDATION_FAILED"):
            WebPageGenerator(FakeReader(), llm).generate(gen_ctx("web_page", SETTINGS)[0])
        self.assertEqual(len(llm.prompts), 3)

    def test_provider_unavailable_is_not_retried(self):
        llm = FormatLLM(STAGE1, StudioError("PROVIDER_UNAVAILABLE", 503), {"html": GOOD})
        with self.assertRaises(StudioError) as caught:
            WebPageGenerator(FakeReader(), llm).generate(gen_ctx("web_page", SETTINGS)[0])
        self.assertEqual((caught.exception.code, len(llm.prompts)), ("PROVIDER_UNAVAILABLE", 2))


if __name__ == "__main__":
    unittest.main()
