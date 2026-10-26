"""제목 자동 생성(F2-02)."""
import unittest

from daon2_user_api.studio_title import TITLE_MAX, derive_title


class TitleTests(unittest.TestCase):
    def test_prefers_body_title_and_clips_to_forty(self):
        self.assertEqual(derive_title({"body": {"title": "  분기   실적 보고 "}}), "분기 실적 보고")
        long = derive_title({"body": {"title": "가" * 100}})
        self.assertEqual(len(long), TITLE_MAX)

    def test_falls_back_to_summary_sentence_root_label_or_first_item(self):
        self.assertEqual(derive_title({"body": {"title": "", "summary": "첫 문장입니다. 둘째 문장."}}), "첫 문장입니다")
        self.assertEqual(derive_title({"body": {"root": "n1", "nodes": [{"id": "n2", "label": "다른"}, {"id": "n1", "label": "핵심 주제"}]}}), "핵심 주제")
        self.assertEqual(derive_title({"body": {"cards": [{"front": "용어 A", "back": "x"}]}}), "용어 A")
        self.assertEqual(derive_title({"body": {"questions": [{"q": "무엇인가?"}]}}), "무엇인가?")

    def test_empty_when_nothing_usable(self):
        self.assertEqual(derive_title({"body": {}}), "")
        self.assertEqual(derive_title({}), "")
        self.assertEqual(derive_title({"body": "x"}), "")


if __name__ == "__main__":
    unittest.main()
