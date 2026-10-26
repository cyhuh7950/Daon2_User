from __future__ import annotations

import io
import sys
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mcp-virtual"))

from mcp_virtual.fixtures import COLLECTIONS, build_documents  # noqa: E402
from mcp_virtual.server import VirtualServer, make_token  # noqa: E402

from daon2_user_api.authoring import session as S  # noqa: E402
from daon2_user_api.authoring.export import authored_elements, authored_slides  # noqa: E402
from daon2_user_api.authoring.pipeline import AuthoringPipeline  # noqa: E402
from daon2_user_api.authoring.rfp import merge, rule_candidates  # noqa: E402
from daon2_user_api.authoring.service import AuthoringGenerator  # noqa: E402
from daon2_user_api.authoring.templates import AuthoringError, TemplateRegistry, parse_template  # noqa: E402
from daon2_user_api.knowledge_connector_service import ConnectorError  # noqa: E402
from daon2_user_api.studio_source_reader import SourceSection, SourceText  # noqa: E402
from daon2_user_api.studio_v2_export import export_v2  # noqa: E402
from daon2_user_api.studio_v2_generation import GenerationContext, StudioCancelled  # noqa: E402
from daon2_user_api.studio_workspace import StudioContext  # noqa: E402

CTX = StudioContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1", "notebook-1")
REGISTRY = TemplateRegistry()
TEMPLATE = REGISTRY.get("rfp_response_proposal")
KEY = b"authoring-test-key-0123456789abcdef"
RFP_DOC = next(d for d in build_documents() if d["document_type"] == "rfp" and d["title"].endswith("제안요청서") and "고객관리" in d["title"])
PROPOSAL_COLLECTION = COLLECTIONS[1]
KNOWLEDGE_REF = {"connector_id": "kc-" + "a" * 32, **PROPOSAL_COLLECTION}


class FakeConnectors:
    """가상 RAG 서버와 가상 Daon2 서버의 도구를 같은 프로세스에서 직접 호출한다."""

    def __init__(self, rag_ok=True):
        self.rag = VirtualServer("rag", KEY)
        self.ops = VirtualServer("ops", KEY)
        self.rag_ok = rag_ok
        self.claims = {"pairs": [dict(c) for c in COLLECTIONS]}
        self.calls = []

    def list(self, ctx):
        return [{"connector_id": "kc-" + "b" * 32, "kind": "daon2", "status": "verified"},
                {"connector_id": "kc-" + "b" * 32, "kind": "law", "status": "verified"}]  # 가상 Daon2 서버가 법령 도구도 제공한다

    def call(self, ctx, connector_id, tool, args):
        self.calls.append((connector_id, tool))
        if not self.rag_ok and connector_id == KNOWLEDGE_REF["connector_id"]:
            raise ConnectorError("CONNECTOR_NOT_FOUND", 404)
        server = self.ops if connector_id == "kc-" + "b" * 32 else self.rag
        return SimpleNamespace(structured=server._call_tool(tool, args, self.claims, "")["structuredContent"])  # noqa: SLF001


class FakeReader:
    def read(self, context, versions, **kw):
        sections = tuple(SourceSection(versions[0], None, "section", f"s{i}", None, b["text"]) for i, b in enumerate(RFP_DOC["blocks"], 1))
        return (SourceText("src-1", versions[0], "rfp.txt", sections, False),)


class ScriptedLLM:
    def __init__(self, responder):
        self.responder = responder
        self.prompts = []

    def generate(self, context, prompt, cancel_check=None):
        self.prompts.append(prompt)
        return SimpleNamespace(data=self.responder(prompt), usage={}, model_id="m", provider_code="CUSTOM", connection_short_code="MS")


def responder(prompt):
    name = prompt.schema_name
    if name == "rfp_requirements":
        return {"requirements": [{"text": "시스템은 장애 발생 시 30분 이내에 복구해야 한다.", "mandatory": True, "category": "가용성"}]}
    if name == "authoring_plan":
        return {"sections": [{"key": "approach", "purpose": "요구사항별 수행 방법", "knowledge_refs": ["K1"], "requirement_ids": ["REQ-001", "REQ-002"]}]}
    if name == "authoring_section":
        return {"paragraphs": [{"text": "시스템은 사용자 인증을 위해 다중 인증 방식을 지원하고 모든 개인정보를 암호화하여 저장한다.", "refs": ["S2", "K1", "S99"]},
                               {"text": "제안사는 신속한 대응 체계를 갖춘다.", "refs": []}], "open_items": ["제안사 소개 보완"]}
    raise AssertionError(name)


def ctx_for(step):
    progress = []
    return GenerationContext(CTX, "sv2-x", "authored_document", None, {"step": step}, ("sv-rfp",), "", "ko", "create", lambda p, n: progress.append((p, n)), lambda: None), progress


def session_after_answers():
    session = S.new_session(TEMPLATE, request_text="RFP 제안서")
    session = S.apply_answers(TEMPLATE, session, [{"key": "rfp_document", "source_version_id": "sv-rfp"}, {"key": "reference_proposals", "knowledge_ref": {**KNOWLEDGE_REF, "document_ids": [d["document_id"] for d in build_documents() if d["document_type"] == "proposal"][:2]}}])
    return S.apply_answers(TEMPLATE, session, [], skip_remaining=True)


class TemplateTests(unittest.TestCase):
    def test_registry_lists_classifies_and_validates(self):
        self.assertEqual([t["template_id"] for t in REGISTRY.list()][0], "rfp_response_proposal")
        self.assertEqual(REGISTRY.classify("RFP에 대응하는 제안서를 써 줘"), ["rfp_response_proposal"])
        self.assertEqual(REGISTRY.classify("날씨 알려줘"), [])
        with self.assertRaises(AuthoringError) as unknown:
            REGISTRY.get("nope")
        self.assertEqual(unknown.exception.status, 404)
        base = {"template_id": "t", "title": "t", "version": 1, "inputs": [{"key": "rfp_document", "kind": "source_ref", "question": "q", "required": True}], "knowledge": [], "sections": [{"key": "a", "title": "A"}], "checks": [], "output": {"formats": ["docx"], "default": ["docx"]}}
        parse_template(base)
        for bad in ({**base, "sections": []}, {**base, "output": {"formats": ["xls"], "default": []}}, {**base, "template_id": "Bad Id"},
                    {**base, "inputs": [{"key": "x", "kind": "weird", "question": "q", "required": True}]},
                    {**base, "knowledge": [{"tool": "drop_database"}]}):
            with self.assertRaises(AuthoringError):
                parse_template(bad)


class SessionTests(unittest.TestCase):
    def test_required_questions_then_one_optional_offer_then_analyzing(self):
        session = S.new_session(TEMPLATE)
        self.assertEqual([q["key"] for q in session["pending_questions"]], ["rfp_document", "reference_proposals"])
        self.assertEqual([r["request"] for r in session["requests"]], ["select_source", "select_knowledge"])
        session = S.apply_answers(TEMPLATE, session, [{"key": "rfp_document", "source_version_id": "sv-rfp"}])
        self.assertEqual([q["key"] for q in session["pending_questions"]], ["reference_proposals"])
        session = S.apply_answers(TEMPLATE, session, [{"key": "reference_proposals", "knowledge_ref": {**KNOWLEDGE_REF, "document_ids": ["doc-1"]}}])
        self.assertEqual((session["state"], [q["key"] for q in session["pending_questions"]]), ("collecting", ["proposer_profile", "price_schedule"]))
        session = S.apply_answers(TEMPLATE, session, [{"key": "proposer_profile", "value": "회사 소개"}])  # 한 번만 제안하고 나머지는 건너뛴 것으로 본다
        self.assertEqual(session["state"], "analyzing")
        self.assertEqual(session["inputs"]["proposer_profile"], "회사 소개")
        self.assertEqual([a["key"] for a in session["assumptions"]], ["price_schedule"])

    def test_skip_rules_and_validation(self):
        session = S.new_session(TEMPLATE)
        with self.assertRaises(AuthoringError):
            S.apply_answers(TEMPLATE, session, [{"key": "rfp_document", "skip": True}])  # 필수는 건너뛸 수 없다
        for bad in ({"key": "unknown", "value": "x"}, {"key": "rfp_document", "source_version_id": "bad id"},
                    {"key": "reference_proposals", "knowledge_ref": {"connector_id": "c", "project_id": "p", "work_package_id": "w", "document_ids": []}}):
            with self.assertRaises(AuthoringError):
                S.apply_answers(TEMPLATE, session, [bad])
        done = session_after_answers()
        self.assertEqual(done["state"], "analyzing")
        self.assertEqual({a["key"] for a in done["assumptions"]}, {"proposer_profile", "price_schedule"})
        with self.assertRaises(AuthoringError) as wrong:
            S.apply_answers(TEMPLATE, done, [{"key": "proposer_profile", "value": "x"}])
        self.assertEqual(wrong.exception.code, "AUTHORING_STATE_INVALID")

    def test_state_transitions_are_closed(self):
        done = session_after_answers()
        self.assertEqual(S.transition(done, "review")["state"], "review")
        for target in ("generating", "completed"):
            with self.assertRaises(AuthoringError):
                S.transition(done, target)

    def test_review_edit_validation(self):
        cleaned = S.validate_review_edit([{"text": "추가 요구", "mandatory": False}, {"id": "REQ-009", "text": "보안 요구"}])
        self.assertEqual([r["id"] for r in cleaned], ["REQ-001", "REQ-009"])
        for bad in ([{"text": ""}], [{"id": "REQ-1", "text": "a"}, {"id": "REQ-1", "text": "b"}], "x", [{"text": "x" * 1001}]):
            with self.assertRaises(AuthoringError):
                S.validate_review_edit(bad)


class RfpTests(unittest.TestCase):
    def test_rule_candidates_and_merge(self):
        body = "\n".join(b["text"] for b in RFP_DOC["blocks"])
        found = rule_candidates([("S1", body)])
        ids = [r["id"] for r in found if r["id"]]
        self.assertIn("REQ-001", ids)
        self.assertGreaterEqual(len(found), 8)
        self.assertTrue(next(r for r in found if r["id"] == "REQ-001")["mandatory"])
        merged = merge(found, [{"text": "시스템 가용성은 연 99.9% 이상이어야 한다", "mandatory": True}, {"text": "전혀 새로운 요구사항 문장입니다", "mandatory": False, "category": "기타"}], "S1")
        self.assertEqual(len(merged), len(found) + 1)  # 중복은 병합된다
        self.assertEqual(len({r["id"] for r in merged}), len(merged))
        self.assertTrue(any(r["text"].startswith("전혀 새로운") and r["id"].startswith("REQ-") for r in merged))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.connectors = FakeConnectors()
        self.llm = ScriptedLLM(responder)
        self.session_store = {}
        self.pipeline = AuthoringPipeline(REGISTRY, FakeReader(), self.llm, self.connectors, lambda ctx, oid: (1, "completed", self.session_store["s"]), context_chars=16000)

    def analyze(self):
        session = session_after_answers()
        ctx, progress = ctx_for("analyze")
        reviewed = self.pipeline.analyze(ctx, session)
        return reviewed, progress

    def test_analyze_extracts_requirements_collects_knowledge_and_plans_every_requirement(self):
        reviewed, progress = self.analyze()
        self.assertEqual(reviewed["state"], "review")
        ids = [r["id"] for r in reviewed["requirements"]]
        self.assertIn("REQ-001", ids)
        self.assertTrue(any("30분 이내" in r["text"] for r in reviewed["requirements"]))
        planned = [rid for s in reviewed["plan"]["sections"] for rid in s["requirement_ids"]]
        self.assertEqual(sorted(planned), sorted(ids))  # 모든 요구사항이 정확히 한 섹션 이상에 배정된다
        self.assertEqual([s["key"] for s in reviewed["plan"]["sections"]], [s["key"] for s in TEMPLATE.sections])
        self.assertTrue(reviewed["knowledge"] and reviewed["knowledge"][0]["ref"] == "K1")
        self.assertIn("get_document_outline", [c[1] for c in self.connectors.calls])
        self.assertTrue(progress)

    def test_required_knowledge_failure_is_a_safe_error(self):
        self.pipeline = AuthoringPipeline(REGISTRY, FakeReader(), self.llm, FakeConnectors(rag_ok=False), lambda *a: None)
        with self.assertRaises(AuthoringError) as failed:
            self.pipeline.analyze(*[ctx_for("analyze")[0], session_after_answers()])
        self.assertEqual(failed.exception.code, "AUTHORING_KNOWLEDGE_UNAVAILABLE")

    def test_generate_builds_document_with_coverage_checks_and_evidence(self):
        reviewed, _ = self.analyze()
        generating = S.transition(reviewed, "generating")
        self.session_store["s"] = generating
        generator = AuthoringGenerator(self.pipeline)
        ctx, progress = ctx_for("generate")
        result = generator.generate(ctx)
        content = result.content
        self.assertEqual(content["state"], "completed")
        document = content["document"]
        self.assertEqual(len(document["sections"]), len(TEMPLATE.sections))
        first = document["sections"][0]["paragraphs"]
        self.assertEqual(first[0]["refs"], ["S2", "K1"])  # 존재하지 않는 S99는 제거된다
        self.assertEqual(first[1]["origin"], "new")
        self.assertEqual(len(document["coverage"]), len(reviewed["requirements"]))
        self.assertTrue(all(c["status"] in {"covered", "partial", "missing"} for c in document["coverage"]))
        ruleset = next(c for c in document["checks"] if c["id"] == "proposal_required_sections")
        self.assertEqual(ruleset["status"], "done")
        self.assertEqual(len(ruleset["results"]), 7)
        self.assertEqual(document["notice"], "AI 작성 초안, 전문가 검토 필요")
        self.assertTrue(any("proposer_profile" in item for item in document["open_items"]))
        origins = {e["ref_id"]: e["origin"] for e in result.evidence}
        self.assertEqual(origins["S2"], "notebook_source")
        self.assertEqual(origins["K1"], "mcp_daon_rag")
        k1 = next(e for e in result.evidence if e["ref_id"] == "K1")
        self.assertIn("excerpt", k1["external_ref"])
        self.assertTrue(progress[-1][0] <= 99)

    def test_generation_can_be_cancelled_between_sections(self):
        reviewed, _ = self.analyze()
        self.session_store["s"] = S.transition(reviewed, "generating")
        ctx, _ = ctx_for("generate")
        calls = []

        def cancel():
            calls.append(1)
            if len(calls) >= 3:
                raise StudioCancelled()
        from dataclasses import replace
        with self.assertRaises(StudioCancelled):
            AuthoringGenerator(self.pipeline).generate(replace(ctx, cancel_check=cancel))

    def test_generator_rejects_wrong_state(self):
        self.session_store["s"] = session_after_answers()
        with self.assertRaises(Exception):
            AuthoringGenerator(self.pipeline).generate(ctx_for("generate")[0])


class ExportTests(unittest.TestCase):
    def output(self):
        pipeline = PipelineTests("test_analyze_extracts_requirements_collects_knowledge_and_plans_every_requirement")
        pipeline.setUp()
        reviewed, _ = pipeline.analyze()
        pipeline.session_store["s"] = S.transition(reviewed, "generating")
        result = AuthoringGenerator(pipeline.pipeline).generate(ctx_for("generate")[0])
        evidence = [{"ref_id": e["ref_id"], "origin": e["origin"], "locator_kind": e["locator_kind"], "locator_value": e["locator_value"],
                     "source_name": "rfp.txt" if e["origin"] == "notebook_source" else "기존 제안서"} for e in result.evidence]
        return {"output_id": "sv2-x", "type_id": "authored_document", "title": "RFP 대응 제안서 초안", "status": "completed", "evidence": evidence,
                "revision": {"revision_no": 3, "content": result.content}}

    def test_docx_has_cover_toc_sections_and_three_appendices(self):
        output = self.output()
        data = export_v2("docx", output).content
        archive = zipfile.ZipFile(io.BytesIO(data))
        for name in archive.namelist():
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(archive.read(name))
        text = archive.read("word/document.xml").decode()
        for needle in ("AI 작성 초안, 전문가 검토 필요", "목차", "1. 사업의 이해", "부록 A. 요구사항 대응표", "부록 B. 근거 목록", "부록 C. 가정과 미결 항목", "[작성 필요]"):
            self.assertIn(needle, text, needle)

    def test_pptx_is_derived_from_the_document_only(self):
        output = self.output()
        slides = authored_slides(output)
        self.assertEqual(slides[0]["layout"], "title")
        self.assertEqual(len(slides), len(TEMPLATE.sections) + 2)
        self.assertEqual(slides[-1]["layout"], "table")
        self.assertIn("전문가 검토", slides[-1]["notes"])
        data = export_v2("pptx", output).content
        archive = zipfile.ZipFile(io.BytesIO(data))
        self.assertEqual(len([n for n in archive.namelist() if n.startswith("ppt/slides/slide")]), len(slides))
        self.assertIn("전문가 검토", archive.read(f"ppt/notesSlides/notesSlide{len(slides)}.xml").decode())

    def test_unfinished_session_exports_a_notice_instead_of_crashing(self):
        output = {"output_id": "sv2-x", "type_id": "authored_document", "title": "작성 중", "status": "completed", "evidence": [],
                  "revision": {"revision_no": 1, "content": S.new_session(TEMPLATE)}}
        self.assertTrue(authored_elements(output)[1][1].startswith("아직"))


if __name__ == "__main__":
    unittest.main()
