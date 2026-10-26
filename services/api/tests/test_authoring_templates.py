"""약관·계약서 템플릿(WO-A1 A2): 기준 문서 기반 분석, 변경 표시, 법령 대조. 가상 MCP 서버를 같은 프로세스에서 직접 호출한다."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_authoring import (  # noqa: E402
    COLLECTIONS, CTX, REGISTRY, FakeConnectors, FakeReader, ScriptedLLM, build_documents, ctx_for,
)

from daon2_user_api.authoring import session as S  # noqa: E402
from daon2_user_api.authoring.diff import similarity, split_sentences, summarize, tag_section  # noqa: E402
from daon2_user_api.authoring.pipeline import AuthoringPipeline  # noqa: E402
from daon2_user_api.authoring.service import AuthoringGenerator  # noqa: E402
from daon2_user_api.authoring.templates import AuthoringError, parse_template  # noqa: E402

TERMS_DOC = next(d for d in build_documents() if d["document_type"] == "insurance_terms" and "자동차" in d["title"])
CONTRACT_DOC = next(d for d in build_documents() if d["document_type"] == "contract" and "용역" in d["title"])
CONNECTOR = "kc-" + "a" * 32


def blocks_after(document, heading_part):
    """개요 노드(제목에 heading_part 포함)의 본문 블록 텍스트(제목 블록 제외)."""
    texts = {b["block_id"]: b["text"] for b in document["blocks"]}
    node = next(n for n in document["outline"] if heading_part in n["title"])
    return [texts[b] for b in node["block_ids"][1:]]


PREMIUM = blocks_after(TERMS_DOC, "보험료")
UNCHANGED = PREMIUM[0]
MODIFIED = UNCHANGED.replace("매월 말일", "매월 25일")


def terms_responder(prompt):
    if prompt.schema_name == "authoring_section":
        if "제5장 보험료" in prompt.user:
            return {"paragraphs": [{"text": UNCHANGED, "refs": ["K1"]}, {"text": MODIFIED + " 연체 이자는 별도로 정한다.", "refs": ["K1"]},
                                   {"text": "자동이체 할인 조항을 새로 둔다.", "refs": []}], "open_items": []}
        return {"paragraphs": [{"text": "이 장의 내용은 기준 약관을 따른다.", "refs": []}], "open_items": []}
    raise AssertionError(prompt.schema_name)


def contract_responder(prompt):
    if prompt.schema_name == "authoring_section":
        laws = re.findall(r'id="(L\d+)"', prompt.user)
        refs = laws[:1] if "[작성할 섹션] 제3조(대금)" in prompt.user else []
        return {"paragraphs": [{"text": "계약 대금은 [작성 필요]원으로 한다.", "refs": refs}], "open_items": ["대금 금액 입력"]}
    if prompt.schema_name == "law_crosscheck":
        return {"rows": [{"index": 0, "relation": "possible_conflict", "note": "조문이 정한 한도와 다를 수 있다."}, {"index": 1, "relation": "bogus"}]}
    raise AssertionError(prompt.schema_name)


def make_pipeline(responder):
    store = {}
    llm = ScriptedLLM(responder)
    connectors = FakeConnectors()
    pipeline = AuthoringPipeline(REGISTRY, FakeReader(), llm, connectors, lambda ctx, oid: (1, "completed", store["s"]), context_chars=16000)
    return pipeline, store, llm, connectors


def answered(template_id, answers):
    template = REGISTRY.get(template_id)
    session = S.new_session(template, request_text="초안")
    session = S.apply_answers(template, session, answers)
    return template, S.apply_answers(template, session, [], skip_remaining=True)


class DiffTests(unittest.TestCase):
    def test_sentence_tags_and_delete_suggestions(self):
        base = ["회사는 보험금을 지급한다.", "면책 기간은 90일로 한다.", "분쟁은 계약자 주소지 법원에서 해결한다."]
        paragraphs, removed = tag_section(["회사는 보험금을 지급한다. 면책 기간은 30일로 한다.", "새로운 환급 조항을 둔다."], base)
        self.assertEqual([p["tag"] for p in paragraphs], ["modified", "new"])
        self.assertEqual([s["tag"] for s in paragraphs[0]["sentences"]], ["unchanged", "modified"])
        self.assertEqual(paragraphs[0]["sentences"][1]["base"], "면책 기간은 90일로 한다.")
        self.assertEqual(removed, ["분쟁은 계약자 주소지 법원에서 해결한다."])
        section = {"paragraphs": [{"diff": p} for p in paragraphs], "delete_suggested": removed}
        self.assertEqual(summarize([section]), {"unchanged": 1, "modified": 1, "new": 1, "delete_suggested": 1})

    def test_normalization_ignores_spacing_and_punctuation(self):
        self.assertEqual(similarity("보험료를  납입한다.", "보험료를 납입한다"), 1.0)
        self.assertEqual(split_sentences("가나다라. 마바사아\n자차카타"), ["가나다라.", "마바사아", "자차카타"])


class TemplateRegistryTests(unittest.TestCase):
    def test_three_templates_with_distinct_analysis_and_classification(self):
        self.assertEqual([t["template_id"] for t in REGISTRY.list()], ["rfp_response_proposal", "insurance_terms_draft", "contract_draft"])
        self.assertEqual(REGISTRY.get("insurance_terms_draft").analysis, "base_document")
        self.assertEqual(REGISTRY.get("contract_draft").style, "contract")
        self.assertIsNone(REGISTRY.get("contract_draft").source_input)
        self.assertEqual(REGISTRY.classify("보험 약관 초안"), ["insurance_terms_draft"])
        self.assertEqual(REGISTRY.classify("용역 계약서 만들어줘"), ["contract_draft"])

    def test_base_document_template_needs_a_required_knowledge_input_and_valid_style(self):
        base = {"template_id": "t", "title": "t", "version": 1, "analysis": "base_document", "inputs": [], "knowledge": [],
                "sections": [{"key": "a", "title": "A"}], "checks": [], "output": {"formats": ["docx"], "default": ["docx"]}}
        with self.assertRaises(AuthoringError):
            parse_template(base)
        with self.assertRaises(AuthoringError):
            parse_template({**base, "style": "poem", "inputs": [{"key": "b", "kind": "knowledge_ref", "question": "q", "required": True}]})
        parse_template({**base, "inputs": [{"key": "b", "kind": "knowledge_ref", "question": "q", "required": True}]})


class TermsTests(unittest.TestCase):
    def setUp(self):
        self.pipeline, self.store, self.llm, self.connectors = make_pipeline(terms_responder)
        self.template, self.session = answered("insurance_terms_draft", [
            {"key": "product_type", "value": "자동차보험"},
            {"key": "base_terms", "knowledge_ref": {"connector_id": CONNECTOR, **COLLECTIONS[0], "document_ids": [TERMS_DOC["document_id"]]}}])

    def test_session_collects_choice_and_base_document_without_a_rfp_source(self):
        self.assertEqual(self.session["state"], "analyzing")
        self.assertEqual(self.session["inputs"]["product_type"], "자동차보험")
        with self.assertRaises(AuthoringError):
            S.apply_answers(self.template, S.new_session(self.template), [{"key": "product_type", "value": "해상보험"}])

    def test_analyze_has_no_requirements_and_assigns_base_clauses_by_section_hints(self):
        reviewed = self.pipeline.analyze(ctx_for("analyze")[0], self.session)
        self.assertEqual((reviewed["state"], reviewed["requirements"]), ("review", []))
        sections = {s["key"]: s for s in reviewed["plan"]["sections"]}
        self.assertEqual(list(sections), [s["key"] for s in self.template.sections])
        self.assertTrue(sections["premium"]["knowledge_refs"])
        self.assertTrue(all(s["requirement_ids"] == [] for s in sections.values()))
        self.assertNotIn("search_law", [c[1] for c in self.connectors.calls])  # 약관은 법령 검색을 하지 않는다
        self.assertNotIn("extract", " ".join(p.schema_name for p in self.llm.prompts))  # 요구사항 추출 호출 없음
        self.assertFalse([p for p in self.llm.prompts if p.schema_name in {"rfp_requirements", "authoring_plan"}])

    def generate(self):
        reviewed = self.pipeline.analyze(ctx_for("analyze")[0], self.session)
        self.store["s"] = S.transition(reviewed, "generating")
        return AuthoringGenerator(self.pipeline).generate(ctx_for("generate")[0])

    def test_generated_terms_carry_change_marks_deletions_and_rule_check(self):
        result = self.generate()
        document = result.content["document"]
        self.assertEqual((document["style"], document["coverage"], result.sources), ("terms", [], []))
        premium = next(s for s in document["sections"] if s["key"] == "premium")
        self.assertEqual([p["diff"]["tag"] for p in premium["paragraphs"]], ["unchanged", "modified", "new"])
        self.assertTrue(premium["delete_suggested"])  # 새 초안이 잇지 않은 기준 문장
        summary = next(c for c in document["checks"] if c["id"] == "terms_change_summary")["summary"]
        self.assertGreaterEqual(summary["unchanged"], 1)
        self.assertGreaterEqual(summary["modified"], 1)
        self.assertGreaterEqual(summary["new"], 1)
        ruleset = next(c for c in document["checks"] if c["id"] == "terms_required_clauses")
        self.assertEqual((ruleset["status"], len(ruleset["results"])), ("done", 7))
        self.assertFalse([c for c in document["checks"] if c["id"] in {"rfp_requirement_coverage", "law_crosscheck"}])
        self.assertEqual({e["origin"] for e in result.evidence}, {"mcp_daon_rag"})
        self.assertIn("기준 약관", self.llm.prompts[-1].system)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.pipeline, self.store, self.llm, self.connectors = make_pipeline(contract_responder)
        self.template, self.session = answered("contract_draft", [
            {"key": "contract_type", "value": "용역계약"},
            {"key": "base_contract", "knowledge_ref": {"connector_id": CONNECTOR, **COLLECTIONS[2], "document_ids": [CONTRACT_DOC["document_id"]]}}])

    def test_analyze_adds_law_articles_per_section_from_the_law_tool(self):
        reviewed = self.pipeline.analyze(ctx_for("analyze")[0], self.session)
        laws = [k for k in reviewed["knowledge"] if k["ref"].startswith("L")]
        self.assertTrue(laws)
        self.assertIn("search_law", [c[1] for c in self.connectors.calls])
        self.assertTrue(all(k.get("section_key") and k["text"] for k in laws))
        planned = [r for s in reviewed["plan"]["sections"] for r in s["knowledge_refs"] if r.startswith("L")]
        self.assertTrue(planned)

    def test_generate_builds_law_crosscheck_with_safe_relations_and_law_evidence(self):
        reviewed = self.pipeline.analyze(ctx_for("analyze")[0], self.session)
        self.store["s"] = S.transition(reviewed, "generating")
        result = AuthoringGenerator(self.pipeline).generate(ctx_for("generate")[0])
        document = result.content["document"]
        self.assertIn("법률 자문이 아닌", document["notice"])
        law = next(c for c in document["checks"] if c["id"] == "law_crosscheck")
        self.assertEqual(law["status"], "done")
        self.assertIn("법률 자문이 아닌", law["notice"])
        self.assertTrue(law["rows"])
        relations = {r["relation"] for r in law["rows"]}
        self.assertLessEqual(relations, {"related", "possible_conflict"})  # 알 수 없는 값은 related로 낮춘다
        self.assertEqual(law["rows"][0]["relation"], "possible_conflict")
        self.assertEqual(law["summary"]["possible_conflict"], 1)
        self.assertTrue(any(e["origin"] == "mcp_law" and e["external_ref"]["tool"] == "get_law_text" for e in result.evidence))
        self.assertTrue(next(c for c in document["checks"] if c["id"] == "contract_required_clauses")["status"] == "done")

    def test_without_a_law_connector_the_law_check_is_skipped_not_failed(self):
        self.connectors.list = lambda ctx: [{"connector_id": "kc-" + "b" * 32, "kind": "daon2", "status": "verified"}]  # 법령 종류 Connector 없음
        reviewed = self.pipeline.analyze(ctx_for("analyze")[0], self.session)
        self.assertIn("LAW_CONNECTOR_UNAVAILABLE", reviewed["analysis_warnings"])
        self.store["s"] = S.transition(reviewed, "generating")
        document = AuthoringGenerator(self.pipeline).generate(ctx_for("generate")[0]).content["document"]
        law = next(c for c in document["checks"] if c["id"] == "law_crosscheck")
        self.assertEqual((law["status"], law["reason"]), ("skipped", "no_law_articles"))


class ExportTests(unittest.TestCase):
    @staticmethod
    def docx_text(result):
        import io
        import zipfile
        from xml.etree import ElementTree

        from daon2_user_api.studio_v2_export import export_v2
        evidence = [{"ref_id": e["ref_id"], "origin": e["origin"], "locator_kind": e["locator_kind"], "locator_value": e["locator_value"], "source_name": "기준 문서"} for e in result.evidence]
        output = {"output_id": "sv2-x", "type_id": "authored_document", "title": "초안", "status": "completed", "evidence": evidence, "revision": {"revision_no": 3, "content": result.content}}
        archive = zipfile.ZipFile(io.BytesIO(export_v2("docx", output).content))
        for name in archive.namelist():
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(archive.read(name))
        return archive.read("word/document.xml").decode()

    def test_terms_docx_marks_changes_deletions_and_summary_without_requirement_appendix(self):
        test = TermsTests("test_generated_terms_carry_change_marks_deletions_and_rule_check")
        test.setUp()
        text = self.docx_text(test.generate())
        for needle in ("[수정]", "[신규]", "삭제 제안", "기준 약관 대비 변경 요약", "부록 B. 근거 목록", "부록 C. 가정과 미결 항목"):
            self.assertIn(needle, text, needle)
        self.assertNotIn("부록 A. 요구사항 대응표", text)

    def test_contract_docx_has_law_crosscheck_table_and_disclaimer(self):
        test = ContractTests("test_generate_builds_law_crosscheck_with_safe_relations_and_law_evidence")
        test.setUp()
        reviewed = test.pipeline.analyze(ctx_for("analyze")[0], test.session)
        test.store["s"] = S.transition(reviewed, "generating")
        text = self.docx_text(AuthoringGenerator(test.pipeline).generate(ctx_for("generate")[0]))
        for needle in ("법령 대조표", "법률 자문이 아닌", "충돌 가능(확인 필요)", "관련 법령 조문"):
            self.assertIn(needle, text, needle)


class ExportFormatRestrictionTests(unittest.TestCase):
    def test_formats_the_template_does_not_offer_are_rejected_but_pdf_stays_available(self):
        from daon2_user_api.studio_v2_service import StudioV2Service
        from daon2_user_api.studio_workspace import StudioError

        class Service(StudioV2Service):
            def __init__(self, choices):
                self.choices = choices

            def get_output(self, context, output_id, revision=None):  # type: ignore[no-untyped-def]
                content = {"template_id": "x", "document": None}
                if self.choices is not None:
                    content["output_choices"] = self.choices
                return {"output_id": output_id, "type_id": "authored_document", "title": "t", "status": "completed", "evidence": [],
                        "revision": {"revision_no": 1, "content": content}}

        with self.assertRaises(StudioError) as rejected:
            Service(["docx"]).export(CTX, "sv2-x", "pptx", None)
        self.assertEqual((rejected.exception.code, rejected.exception.status), ("EXPORT_FORMAT_UNSUPPORTED", 400))
        self.assertTrue(Service(["docx"]).export(CTX, "sv2-x", "docx", None))
        self.assertTrue(Service(["docx"]).export(CTX, "sv2-x", "pdf", None))
        self.assertTrue(Service(None).export(CTX, "sv2-x", "pptx", None))  # 제안서 등 기존 세션(선택지 정보 없음)은 그대로


if __name__ == "__main__":
    unittest.main()
