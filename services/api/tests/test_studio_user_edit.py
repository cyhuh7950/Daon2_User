"""사용자 편집 정리(S2-11): 유형별 구조 규칙과 근거 라벨 정리."""
from __future__ import annotations

import unittest

from daon2_user_api.studio_user_edit import EDITABLE_TYPES, validate_user_edit
from daon2_user_api.studio_workspace import StudioError

KNOWN = {"S1", "S2"}


class UserEditTests(unittest.TestCase):
    def test_report_edit_keeps_known_refs_only_and_trims_blocks(self):
        body = {"title": " 제목 ", "summary": "요약", "sections": [
            {"heading": "1장", "blocks": [{"type": "paragraph", "text": "수정한 문장", "refs": ["S1", "S9", "S1"]},
                                         {"type": "bullets", "items": ["가", " ", "나"], "refs": ["S2"]},
                                         {"type": "table", "rows": [["a", "b"], ["1", "2"]], "refs": []},
                                         {"type": "paragraph", "text": "   ", "refs": []}]},
            {"heading": "", "blocks": [{"type": "paragraph", "text": "제목 없는 섹션은 버린다", "refs": []}]}]}
        cleaned = validate_user_edit("report", body, KNOWN)
        self.assertEqual(cleaned["title"], "제목")
        self.assertEqual(len(cleaned["sections"]), 1)
        blocks = cleaned["sections"][0]["blocks"]
        self.assertEqual([b["type"] for b in blocks], ["paragraph", "bullets", "table"])
        self.assertEqual(blocks[0]["refs"], ["S1"])  # 알 수 없는 S9는 제거, 중복은 한 번
        self.assertEqual(blocks[1]["items"], ["가", "나"])

    def test_report_rejects_unknown_block_type_and_empty_result(self):
        with self.assertRaises(StudioError):
            validate_user_edit("report", {"sections": [{"heading": "h", "blocks": [{"type": "script", "text": "x"}]}]}, KNOWN)
        with self.assertRaises(StudioError):
            validate_user_edit("report", {"sections": []}, KNOWN)

    def test_flashcards_slides_and_quiz_rules(self):
        cards = validate_user_edit("flashcards", {"cards": [{"front": "앞", "back": "뒤", "refs": ["S2", "S7"], "hint": "힌트"}, {"front": "", "back": "x"}]}, KNOWN)
        self.assertEqual(cards["cards"], [{"front": "앞", "back": "뒤", "refs": ["S2"], "hint": "힌트"}])
        slides = validate_user_edit("slides", {"title": "덱", "slides": [{"layout": "weird", "title": "표지", "bullets": ["a", ""], "notes": "노트", "refs": ["S1"]}]}, KNOWN)
        self.assertEqual(slides["slides"][0]["layout"], "bullets")
        self.assertEqual(slides["slides"][0]["bullets"], ["a"])
        quiz = {"questions": [{"q": "질문?", "options": ["가", "나", "다", "라"], "answer_index": 2, "explanation": "해설", "refs": ["S1"]}]}
        self.assertEqual(validate_user_edit("quiz", quiz, KNOWN)["questions"][0]["answer_index"], 2)
        for bad in ({"questions": [{"q": "질문?", "options": ["가", "나", "다"], "answer_index": 0}]},
                    {"questions": [{"q": "질문?", "options": ["가", "나", "다", "라"], "answer_index": 4}]},
                    {"questions": [{"q": "질문?", "options": ["가", "가", "다", "라"], "answer_index": 0}]},
                    {"questions": [{"q": "", "options": ["가", "나", "다", "라"], "answer_index": 0}]}):
            with self.assertRaises(StudioError):
                validate_user_edit("quiz", bad, KNOWN)
        with self.assertRaises(StudioError):
            validate_user_edit("slides", {"slides": [{"title": "", "bullets": []}]}, KNOWN)

    def test_memo_keeps_other_body_fields_and_unsupported_types_are_rejected(self):
        self.assertEqual(validate_user_edit("memo", {"markdown": "안녕"}, set(), {"markdown": "옛", "title": "메모"}), {"markdown": "안녕", "title": "메모"})
        with self.assertRaises(StudioError):
            validate_user_edit("memo", {"markdown": 3}, set())
        for type_id in ("data_table", "mind_map", "infographic"):
            self.assertNotIn(type_id, EDITABLE_TYPES)
            with self.assertRaises(StudioError):
                validate_user_edit(type_id, {"x": 1}, KNOWN)
        with self.assertRaises(StudioError):
            validate_user_edit("report", "not-a-mapping", KNOWN)


if __name__ == "__main__":
    unittest.main()
