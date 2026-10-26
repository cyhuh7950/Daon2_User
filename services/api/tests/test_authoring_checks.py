"""작성 점검(F6-13): 근거 무결성·용어 일관성."""
import unittest

from daon2_user_api.authoring.checks import evidence_integrity, term_consistency


def section(key, *paragraphs):
    return {"key": key, "title": key.upper(), "paragraphs": [{"text": t, "refs": r} for t, r in paragraphs]}


class EvidenceIntegrityTests(unittest.TestCase):
    def test_flags_missing_and_unknown_refs_but_not_placeholders(self):
        result = evidence_integrity([section("a", ("근거 있는 문장", ["S1"]), ("근거 없는 문장", []), ("모르는 근거", ["K9"]), ("[작성 필요]", []))], {"S1", "K1"})
        self.assertEqual(result["summary"], {"verified": 1, "unverified": 2})
        self.assertEqual([(i["paragraph_index"], i["reason"]) for i in result["items"]], [(1, "no_ref"), (2, "unknown_ref")])

    def test_all_verified(self):
        result = evidence_integrity([section("a", ("문장", ["S1", "K1"]))], {"S1", "K1"})
        self.assertEqual(result["summary"]["unverified"], 0)
        self.assertEqual(result["items"], [])


class TermConsistencyTests(unittest.TestCase):
    CONCEPTS = [{"concept_id": "c1", "label": "보험금", "synonyms": ["보상금"]},
                {"concept_id": "c2", "label": "계약자", "synonyms": ["보험계약자", "계약"]},
                {"concept_id": "c3", "label": "해지환급금", "synonyms": ["환급금"]}]

    def test_mixed_and_synonym_only(self):
        sections = [section("a", ("보험금을 청구하면 보상금을 지급한다.", []), ("보험계약자는 환급금을 받는다.", []))]
        result = term_consistency(sections, self.CONCEPTS)
        found = {(i["preferred"], i["found"]): i["kind"] for i in result["items"]}
        self.assertEqual(found[("보험금", "보상금")], "mixed")
        self.assertEqual(found[("해지환급금", "환급금")], "synonym_only")
        self.assertEqual(found[("계약자", "보험계약자")], "synonym_only")  # '계약자'는 동의어 안의 부분 문자열이라 기준 용어 사용이 아니다
        self.assertEqual(result["summary"]["mixed"], 1)
        self.assertEqual(result["items"][0]["kind"], "mixed")  # 혼용이 먼저 나온다

    def test_short_synonyms_and_clean_text_are_ignored(self):
        result = term_consistency([section("a", ("보험금 지급 계약", []))], self.CONCEPTS)
        self.assertEqual(result["items"], [])


if __name__ == "__main__":
    unittest.main()
