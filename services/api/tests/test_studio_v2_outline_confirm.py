"""슬라이드·동영상 개요 생성 전 구성 확인(WO-N1 NB3-F1): 설정 스키마, 확정 목록 검증(OUTLINE_INVALID), 슬라이드 멈춤·확정."""
from __future__ import annotations

import contextlib
import json
import unittest
from datetime import datetime, timezone

from daon2_user_api.studio_generators import SlidesGenerator
from daon2_user_api.studio_v2_postgres import PostgresStudioV2Repository
from daon2_user_api.studio_v2_types import (
    OUTLINE_LIMITS, STUDIO_V2_TYPES, OutlineInvalid, available_types, checked_settings, parse_confirmed_outline, validate_settings,
)
from daon2_user_api.studio_workspace import StudioError
from test_studio_v2_generation import CTX, FakeReader, ScriptedLLM, gen_ctx


def slides_outline(count=3, **extra):
    return json.dumps({"title": "발표", "slides": [{"title": f"장 {i + 1}", "points": [f"요지 {i + 1}"]} for i in range(count)], **extra},
                      ensure_ascii=False)


def video_outline(count=3):
    return json.dumps({"title": "영상", "scenes": [{"title": f"장면 {i + 1}", "narration_summary": f"내레이션 {i + 1}입니다."} for i in range(count)]},
                      ensure_ascii=False)


class OutlineSettingsSchemaTests(unittest.TestCase):
    def test_slides_and_video_expose_the_same_confirmation_options_as_report(self):
        for type_id in ("slides", "video_overview"):
            with self.subTest(type_id=type_id):
                properties = STUDIO_V2_TYPES[type_id].settings_schema["properties"]
                self.assertEqual(properties["confirm_outline"], {"type": "string", "enum": ["no", "yes"]})
                self.assertTrue(properties["confirmed_outline"]["hidden"])
                self.assertEqual(properties["confirmed_outline"]["type"], "string")
        by_id = {item["type_id"]: item for item in available_types(tts_enabled=True)}
        self.assertIn("confirm_outline", by_id["slides"]["settings_schema"]["properties"])

    def test_default_settings_are_unchanged(self):
        self.assertEqual(validate_settings("slides", None, {}), (None, {}))
        self.assertEqual(validate_settings("video_overview", None, {"length": "short"}), (None, {"length": "short"}))
        self.assertEqual(validate_settings("slides", None, {"confirm_outline": "yes"})[1], {"confirm_outline": "yes"})
        with self.assertRaisesRegex(ValueError, "STUDIO_INPUT_INVALID"):
            validate_settings("slides", None, {"confirm_outline": "maybe"})

    def test_limits_follow_the_plan(self):
        self.assertEqual(OUTLINE_LIMITS["slides"], 30)
        self.assertEqual(OUTLINE_LIMITS["video_overview"], 20)


class ConfirmedOutlineValidationTests(unittest.TestCase):
    def test_valid_lists_are_accepted_and_normalized(self):
        _, settings = validate_settings("slides", None, {"confirm_outline": "no", "confirmed_outline": slides_outline(30)})
        data = json.loads(settings["confirmed_outline"])
        self.assertEqual(len(data["slides"]), 30)
        self.assertEqual(data["slides"][0], {"title": "장 1", "points": ["요지 1"]})
        _, settings = validate_settings("video_overview", None, {"confirmed_outline": video_outline(20)})
        self.assertEqual(json.loads(settings["confirmed_outline"])["scenes"][19], {"title": "장면 20", "narration_summary": "내레이션 20입니다."})
        # 제목 앞뒤 공백은 지우고, 요지가 없는 장도 허용한다
        raw = json.dumps({"slides": [{"title": "  표지  "}]}, ensure_ascii=False)
        self.assertEqual(parse_confirmed_outline("slides", raw), {"title": "", "slides": [{"title": "표지", "points": []}]})

    def test_invalid_lists_are_outline_invalid(self):
        cases = {
            "empty slides": ("slides", json.dumps({"slides": []})),
            "31 slides": ("slides", slides_outline(31)),
            "empty slide title": ("slides", json.dumps({"slides": [{"title": "  ", "points": []}]})),
            "missing slide title": ("slides", json.dumps({"slides": [{"points": ["a"]}]})),
            "not json": ("slides", "{not json"),
            "wrong key": ("slides", json.dumps({"scenes": [{"title": "a"}]})),
            "points not list": ("slides", json.dumps({"slides": [{"title": "a", "points": "b"}]})),
            "empty scenes": ("video_overview", json.dumps({"scenes": []})),
            "21 scenes": ("video_overview", video_outline(21)),
            "empty scene title": ("video_overview", json.dumps({"scenes": [{"title": "", "narration_summary": "x"}]})),
            "scene not object": ("video_overview", json.dumps({"scenes": ["장면"]})),
        }
        for name, (type_id, raw) in cases.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(OutlineInvalid, "OUTLINE_INVALID"):
                    validate_settings(type_id, None, {"confirm_outline": "no", "confirmed_outline": raw})

    def test_checked_settings_maps_outline_errors_to_422(self):
        with self.assertRaises(StudioError) as caught:
            checked_settings("slides", None, {"confirmed_outline": slides_outline(31)})
        self.assertEqual((caught.exception.code, caught.exception.status), ("OUTLINE_INVALID", 422))
        with self.assertRaises(StudioError) as caught:
            checked_settings("slides", None, {"nope": 1})
        self.assertEqual((caught.exception.code, caught.exception.status), ("STUDIO_INPUT_INVALID", 400))
        self.assertEqual(checked_settings("report", None, {}), ("summary", {}))

    def test_report_outline_rules_are_unchanged(self):
        _, settings = validate_settings("report", "summary", {"confirm_outline": "yes", "confirmed_outline": "{}"})
        self.assertEqual(settings["confirmed_outline"], "{}")


class _Rows:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        return _Rows(self.rows.pop(0) if self.rows else None)


class _Store:
    def __init__(self, rows):
        self.connection = _Connection(rows)

    @contextlib.contextmanager
    def _transaction(self, context):
        yield self.connection


class RegenerateOutlineValidationTests(unittest.TestCase):
    def test_regenerate_with_an_invalid_list_is_422_and_queues_nothing(self):
        now = datetime(2026, 11, 24, tzinfo=timezone.utc)
        row = ("sv2-" + "a" * 32, "slides", None, "슬라이드", "completed", None, {"confirm_outline": "yes"}, [], 1, CTX.actor_id, now, now)
        store = _Store([row, None])
        repo = PostgresStudioV2Repository(store)
        with self.assertRaises(StudioError) as caught:
            repo.regenerate(CTX, row[0], {"confirm_outline": "no", "confirmed_outline": json.dumps({"slides": []})}, "regen-key-0000000001")
        self.assertEqual((caught.exception.code, caught.exception.status), ("OUTLINE_INVALID", 422))
        self.assertFalse(any(sql.startswith(("UPDATE", "INSERT")) for sql in store.connection.statements))

    def test_create_with_an_invalid_list_is_422(self):
        repo = PostgresStudioV2Repository(_Store([]))
        repo.tts_resolver = None
        with self.assertRaises(StudioError) as caught:
            repo.enqueue(CTX, {"type_id": "slides", "settings": {"confirmed_outline": slides_outline(31)}}, "create-key-00000001")
        self.assertEqual((caught.exception.code, caught.exception.status), ("OUTLINE_INVALID", 422))


SLIDES_OUTLINE_REPLY = {"title": "보험 안내", "slides": [
    {"title": "보험 안내", "points": []},
    {"title": "지급 기한", "points": ["접수일부터 3일 이내"]},
    {"title": "면책 기간", "points": ["계약일부터 90일"]}]}


class SlidesOutlineConfirmTests(unittest.TestCase):
    def test_confirmation_stops_with_the_slide_list_after_one_short_call(self):
        llm = ScriptedLLM(SLIDES_OUTLINE_REPLY)
        result = SlidesGenerator(FakeReader(), llm).generate(gen_ctx("slides", {"confirm_outline": "yes"})[0])
        body = result.content["body"]
        self.assertEqual(body["slides"], [])
        self.assertEqual(body["outline_review"], [{"title": "보험 안내", "points": []}, {"title": "지급 기한", "points": ["접수일부터 3일 이내"]},
                                                  {"title": "면책 기간", "points": ["계약일부터 90일"]}])
        self.assertEqual(body["title"], "보험 안내")
        self.assertEqual(len(llm.prompts), 1)
        self.assertIn("points", json.dumps(llm.prompts[0].json_schema))

    def test_confirmed_list_is_generated_with_the_same_titles_in_order(self):
        confirmed = {"title": "고친 발표", "slides": [{"title": "고친 표지", "points": []}, {"title": "기한 정리", "points": ["3일 이내 지급"]},
                                                     {"title": "새로 넣은 장", "points": ["즉시 통지"]}]}
        reply = {"title": "x", "slides": [
            {"layout": "title", "title": "고친 표지", "bullets": [], "refs": []},
            {"layout": "bullets", "title": "다르게 붙인 제목", "bullets": ["청구서류 접수일부터 3일 이내에 지급한다."], "refs": ["S1"]}]}
        llm = ScriptedLLM(reply)
        settings = {"confirm_outline": "no", "confirmed_outline": json.dumps(confirmed, ensure_ascii=False)}
        result = SlidesGenerator(FakeReader(), llm).generate(gen_ctx("slides", settings)[0])
        slides = result.content["body"]["slides"]
        self.assertEqual([s["title"] for s in slides], ["고친 표지", "기한 정리", "새로 넣은 장"])
        self.assertEqual(slides[0]["layout"], "title")
        self.assertEqual(slides[1]["bullets"], ["청구서류 접수일부터 3일 이내에 지급한다."])
        self.assertEqual(slides[2]["bullets"], ["즉시 통지"])  # 모델이 빠뜨린 장은 확정한 요지로 채운다
        self.assertNotIn("outline_review", result.content["body"])
        self.assertEqual(result.content["body"]["title"], "고친 발표")
        self.assertEqual(len(llm.prompts), 1)
        self.assertIn("기한 정리", llm.prompts[0].user)
        self.assertIn("새로 넣은 장", llm.prompts[0].user)

    def test_confirmed_list_can_go_beyond_the_default_twenty_slides(self):
        confirmed = {"slides": [{"title": f"장 {i + 1}", "points": [f"요지 {i + 1}"]} for i in range(25)]}
        reply = {"slides": [{"layout": "bullets", "title": f"장 {i + 1}", "bullets": ["면책 기간은 계약일부터 90일이다."], "refs": ["S1"]} for i in range(25)]}
        result = SlidesGenerator(FakeReader(), ScriptedLLM(reply)).generate(
            gen_ctx("slides", {"confirmed_outline": json.dumps(confirmed, ensure_ascii=False)})[0])
        self.assertEqual([s["title"] for s in result.content["body"]["slides"]], [f"장 {i + 1}" for i in range(25)])

    def test_confirmation_off_keeps_the_single_full_call(self):
        reply = {"title": "발표", "slides": [{"layout": "title", "title": "표지", "bullets": [], "refs": []},
                                           {"layout": "bullets", "title": "지급", "bullets": ["3일 이내"], "refs": ["S1"]}]}
        llm = ScriptedLLM(reply)
        result = SlidesGenerator(FakeReader(), llm).generate(gen_ctx("slides", {"confirm_outline": "no"})[0])
        self.assertEqual([s["title"] for s in result.content["body"]["slides"]], ["표지", "지급"])
        self.assertNotIn("outline_review", result.content["body"])
        self.assertEqual(len(llm.prompts), 1)


if __name__ == "__main__":
    unittest.main()


class OutlineRefLabelTests(unittest.TestCase):
    """후속 A-3: 구성 검토 요지 끝에 모델이 붙인 "[S1]" 같은 근거 표시가 글자로 보였다. 구성 목록에서는 지운다."""

    def test_strip_ref_labels_removes_only_source_labels(self):
        from daon2_user_api.studio_v2_types import strip_ref_labels
        self.assertEqual(strip_ref_labels("상해 의료비 300만 원 한도 [S1]"), "상해 의료비 300만 원 한도")
        self.assertEqual(strip_ref_labels("지급 기한 [S1, S2] 안내 (S3)"), "지급 기한 안내")
        self.assertEqual(strip_ref_labels("3조 [별표 1] 참고"), "3조 [별표 1] 참고")
        self.assertEqual(strip_ref_labels("ISO S3 등급"), "ISO S3 등급")

    def test_slide_outline_titles_and_points_have_no_ref_labels(self):
        reply = {"title": "보험 안내 [S1]", "slides": [
            {"title": "지급 기한 [S2]", "points": ["접수일부터 3일 이내 [S2]", "[S1]"]}]}
        body = SlidesGenerator(FakeReader(), ScriptedLLM(reply)).generate(gen_ctx("slides", {"confirm_outline": "yes"})[0]).content["body"]
        self.assertEqual(body["title"], "보험 안내")
        self.assertEqual(body["outline_review"], [{"title": "지급 기한", "points": ["접수일부터 3일 이내"]}])

    def test_video_outline_review_uses_the_same_cleanup(self):
        import inspect
        from daon2_user_api import studio_video
        self.assertIn("strip_ref_labels", inspect.getsource(studio_video.VideoOverviewGenerator.generate))
