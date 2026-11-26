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

    def test_web_page_insufficient_title_never_used(self):
        # 최종 검토 I1: 근거 부족 제목·근거 부족 절 제목은 카드 제목(→ 내려받기 파일 이름)에 쓰지 않는다.
        weak = {"type": "paragraph", "text": "x", "refs": [], "insufficient": True}
        ok = {"type": "paragraph", "text": "y", "refs": ["S1"], "insufficient": False}
        body = {"title": "2027년 보험료 12% 인상 안내", "title_insufficient": True, "request": "r", "html": "",
                "sections": [{"heading": "근거 없는 절", "blocks": [weak]}, {"heading": "보장 안내", "blocks": [ok]}]}
        content = {"schema": "studio.web_page.v1", "body": body}
        self.assertEqual(derive_title(content), "보장 안내")
        self.assertEqual(derive_title({"schema": "studio.web_page.v1", "body": {**body, "sections": [body["sections"][0]]}}), "")
        self.assertEqual(derive_title({"schema": "studio.web_page.v1", "body": {**body, "title_insufficient": False}}),
                         "2027년 보험료 12% 인상 안내")

    def test_data_aggregation_title_from_request_not_summary_list(self):
        # 실서버 확인(WO-N9): 요약이 문장 목록이라 제목이 "['건수…"로 붙던 문제.
        body = {"request": "월별·상품별 청구 건수와 지급액 합계를 표와 차트로 보여줘. 전월 대비 증감률도 알려줘.",
                "summary": ["건수(청구번호) 가장 큰 묶음: 2026-03 · 여행자보험 (608)"], "rows": [], "columns": []}
        title = derive_title({"schema": "studio.data_aggregation.v1", "body": body})
        self.assertEqual(title, "월별·상품별 청구 건수와 지급액 합계를 표와 차트로 보여줘")
        self.assertFalse(title.startswith("["))

    def test_list_summary_is_never_stringified(self):
        self.assertEqual(derive_title({"body": {"summary": ["a", "b"]}}), "")


if __name__ == "__main__":
    unittest.main()
