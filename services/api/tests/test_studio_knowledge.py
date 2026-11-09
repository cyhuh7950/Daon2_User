"""스튜디오의 승인 지식 사용(WO-K4 4단계): 자료 계획, 근거 표시, 보고서 섹션별 검색."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from daon2_user_api.document_index_postgres import IndexedEvidenceChunk
from daon2_user_api.question_external_evidence import EvidenceTarget, ExternalEvidence, ExternalEvidenceError
from daon2_user_api.studio_generators import FlashcardsGenerator, ReportGenerator
from daon2_user_api.studio_context_builder import ContextPack
from daon2_user_api.studio_knowledge import StudioKnowledge
from daon2_user_api.studio_source_reader import SourceSection, SourceText
from daon2_user_api.studio_v2_generation import GenerationContext, GeneratorRegistry
from daon2_user_api.studio_workspace import StudioContext, StudioError

CTX = StudioContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1", "notebook-1")


def evidence(block="b1", text="평가 배점은 기술 90점이다."):
    chunk = IndexedEvidenceChunk(f"ext-{block}", "doc-1", "ver-1", 3, text, block, 0.9)
    return ExternalEvidence(chunk, "kc-rag", "p1", "프로젝트", "w1", "패키지", "doc-1", "ver-1", "run-1", block, 3, "제안요청서.pdf", text)


class Finder:
    def __init__(self, found=None, packages=True, error=None):
        self.found, self.packages, self.error, self.runs, self.limits = found, packages, error, [], []

    def prepare(self, context):
        if not self.packages:
            return None
        return EvidenceTarget(SimpleNamespace(tenant_id="t"), "kc-rag", ({"alias": "P1", "project_id": "p1", "project_name": "프로젝트", "work_package_id": "w1", "work_package_name": "제안서 작업"},))

    def run(self, target, requests, limit=5):
        self.runs.append(tuple(requests))
        self.limits.append(limit)
        if self.error:
            raise self.error
        return self.found if self.found is not None else (evidence(f"b{len(self.runs)}", f"근거 {len(self.runs)}번 본문 내용"),)


class Reader:
    def __init__(self, empty=False):
        self.empty = empty

    def read(self, context, versions, **kw):
        if not versions:
            raise StudioError("STUDIO_NO_READY_SOURCE", 409)
        if self.empty:
            return ()
        return (SourceText("src-1", "sv-1", "약관.pdf", (SourceSection("sv-1", None, "page", "1", None, "소스 본문입니다."),), False),)


class LLM:
    def __init__(self):
        self.prompts = []

    def generate(self, context, prompt, cancel_check=None):
        self.prompts.append(prompt)
        name = prompt.schema_name
        if name == "studio_knowledge_units":
            data = {"units": []}
        elif name == "authoring_unit_plan":
            data = {"requests": [{"knowledge": "rag", "package": "P1", "query": "평가 기준"}]}
        elif "개요" in prompt.user:
            data = {"title": "제목", "summary": "요약", "sections": [{"heading": "첫 섹션", "purpose": "가", "refs": []}, {"heading": "둘째 섹션", "purpose": "나", "refs": []}]}
        elif "섹션" in prompt.user:
            label = prompt.user.rsplit('<source id="', 1)[1].split('"', 1)[0]
            data = {"blocks": [{"type": "paragraph", "text": "본문 문장입니다.", "refs": [label]}]}
        else:
            label = prompt.user.rsplit('<source id="', 1)[1].split('"', 1)[0]
            data = {"cards": [{"front": "앞면", "back": "뒷면", "refs": [label]}]}
        return SimpleNamespace(data=data, usage={}, model_id="m", provider_code="CUSTOM", connection_short_code="MS")


def job(type_id, versions=("sv-1",), settings=None):
    return GenerationContext(CTX, "sv2-x", type_id, None, settings or {}, versions, "", "ko", "create", lambda p, n: None, lambda: None)


def report(finder, reader=None):
    llm = LLM()
    generator = ReportGenerator(reader or Reader(), llm)
    generator.set_knowledge(StudioKnowledge(llm, finder))
    return generator, llm


class StudioKnowledgeTests(unittest.TestCase):
    def test_empty_plan_does_not_fallback(self):
        finder, llm = Finder(), LLM()
        llm.generate = lambda context, prompt, cancel_check=None: SimpleNamespace(data={"requests": []})
        found, matched = StudioKnowledge(llm, finder).extend_if_requested(CTX, "문장을 다듬어 줘", ContextPack((), False, 0))
        self.assertEqual((found.passages, matched, finder.runs), ((), (), []))

    def test_requested_material_is_numbered_after_existing_refs(self):
        finder = Finder()
        pack, matched = StudioKnowledge(LLM(), finder).extend_if_requested(CTX, "최신 약관", ContextPack((), False, 0), first_number=7)
        self.assertEqual(len(finder.runs), 1)
        self.assertEqual([p.ref for p in pack.passages], ["S7"])
        self.assertEqual([p.ref for p in matched], ["S7"])

    def test_extend_still_falls_back_on_empty_plan(self):
        finder, llm = Finder(), LLM()
        llm.generate = lambda context, prompt, cancel_check=None: SimpleNamespace(data={"requests": []})
        job = GenerationContext(CTX, "o", "report", None, {}, (), "", "ko", "create", lambda p, n: None, lambda: None)
        StudioKnowledge(llm, finder).extend(job, "질문", ContextPack((), False, 0))
        self.assertEqual(len(finder.runs), 1)

    def test_available_follows_the_selection(self):
        self.assertTrue(StudioKnowledge(LLM(), Finder()).available(CTX))
        self.assertFalse(StudioKnowledge(LLM(), Finder(packages=False)).available(CTX))

    def test_report_searches_for_the_output_and_for_each_section(self):
        finder = Finder()
        generator, llm = report(finder)
        result = generator.generate(job("report"))
        self.assertEqual(len(finder.runs), 3)
        section_prompts = [p for p in llm.prompts if "본문을 작성하세요" in p.user]
        self.assertIn("근거 2번 본문", section_prompts[0].user)
        self.assertIn("근거 3번 본문", section_prompts[1].user)
        self.assertNotIn("근거 3번 본문", section_prompts[0].user)
        origins = {row["origin"] for row in result.evidence}
        self.assertEqual(origins, {"mcp_daon_rag"})

    def test_external_evidence_keeps_its_provenance(self):
        generator, _ = report(Finder())
        row = generator.generate(job("report")).evidence[0]
        self.assertIsNone(row["source_version_id"])
        self.assertEqual((row["external_ref"]["document_id"], row["external_ref"]["version_id"], row["external_ref"]["name"], row["locator_value"]), ("doc-1", "ver-1", "제안요청서.pdf", "3"))

    def test_labels_continue_after_the_sources(self):
        llm = LLM()
        generator = FlashcardsGenerator(Reader(), llm)
        generator.set_knowledge(StudioKnowledge(llm, Finder()))
        pack = generator._pack(job("flashcards"))  # noqa: SLF001
        self.assertEqual([p.ref for p in pack.passages], ["S1", "S2"])

    def test_nothing_changes_without_selected_knowledge(self):
        llm = LLM()
        generator = FlashcardsGenerator(Reader(), llm)
        generator.set_knowledge(StudioKnowledge(llm, Finder(packages=False)))
        self.assertEqual([p.ref for p in generator._pack(job("flashcards")).passages], ["S1"])  # noqa: SLF001
        self.assertEqual(llm.prompts, [])

    def test_knowledge_alone_is_enough(self):
        generator, _ = report(Finder(), Reader(empty=True))
        result = generator.generate(job("report", versions=()))
        self.assertTrue(result.evidence)
        self.assertEqual(result.sources, [])

    def test_no_source_and_no_knowledge_is_still_refused(self):
        llm = LLM()
        generator = FlashcardsGenerator(Reader(), llm)
        generator.set_knowledge(StudioKnowledge(llm, Finder(packages=False)))
        with self.assertRaises(StudioError) as caught:
            generator._pack(job("flashcards", versions=()))  # noqa: SLF001
        self.assertEqual(caught.exception.code, "STUDIO_NO_READY_SOURCE")

    def test_empty_plan_still_searches_because_the_output_needs_material(self):
        finder, llm = Finder(), LLM()
        original = llm.generate

        def generate(context, prompt, cancel_check=None):
            result = original(context, prompt, cancel_check)
            if prompt.schema_name == "authoring_unit_plan":
                result.data = {"requests": []}
            return result

        llm.generate = generate
        generator = FlashcardsGenerator(Reader(), llm)
        generator.set_knowledge(StudioKnowledge(llm, finder))
        generator._pack(job("flashcards"))  # noqa: SLF001
        self.assertEqual(len(finder.runs[0]), 1)

    def test_documents_are_searched_when_ontology_is_not_ready(self):
        class OntologyPlanFinder(Finder):
            def prepare(self, context):
                base = super().prepare(context)
                return EvidenceTarget(base.connector_context, base.connector_id, base.packages, "ctx", "kc-daon2")

            def run(self, target, requests, limit=5):
                self.runs.append(tuple(requests))
                return () if any(len(item) > 2 for item in requests) else (evidence("doc"),)

        finder, llm = OntologyPlanFinder(), LLM()
        original = llm.generate

        def generate(context, prompt, cancel_check=None):
            result = original(context, prompt, cancel_check)
            if prompt.schema_name == "authoring_unit_plan":
                result.data = {"requests": [{"knowledge": "ontology", "package": "P1", "query": "용어"}]}
            return result

        llm.generate = generate
        generator = FlashcardsGenerator(Reader(empty=True), llm)
        generator.set_knowledge(StudioKnowledge(llm, finder))
        pack = generator._pack(job("flashcards", versions=()))  # noqa: SLF001
        self.assertEqual(len(pack.passages), 1)
        self.assertEqual(len(finder.runs), 2)

    def test_each_planned_unit_gets_its_own_material(self):
        finder, llm = Finder(), LLM()
        original = llm.generate

        def generate(context, prompt, cancel_check=None):
            if prompt.schema_name == "studio_knowledge_units":
                llm.prompts.append(prompt)
                return SimpleNamespace(data={"units": [{"title": "평가 기준"}, {"title": "추진 일정"}, {"title": "수행 조직"}]})
            return original(context, prompt, cancel_check)

        llm.generate = generate
        generator = FlashcardsGenerator(Reader(), llm)
        generator.set_knowledge(StudioKnowledge(llm, finder))
        pack = generator._pack(job("flashcards"))  # noqa: SLF001
        self.assertEqual(len(finder.runs), 3)
        self.assertEqual(finder.limits, [3, 3, 3])
        self.assertEqual(len(pack.passages), 4)
        plans = [p.user for p in llm.prompts if p.schema_name == "authoring_unit_plan"]
        self.assertIn("평가 기준", plans[0])
        self.assertIn("수행 조직", plans[2])

    def test_report_can_stop_for_outline_confirmation(self):
        generator, llm = report(Finder())
        result = generator.generate(job("report", settings={"confirm_outline": "yes"}))
        self.assertEqual([item["heading"] for item in result.content["body"]["outline_review"]], ["첫 섹션", "둘째 섹션"])
        self.assertEqual(result.content["body"]["sections"], [])
        self.assertEqual([p for p in llm.prompts if "본문을 작성하세요" in p.user], [])

    def test_confirmed_outline_is_used_without_asking_again(self):
        generator, llm = report(Finder())
        outline = json.dumps({"title": "확정 제목", "sections": [{"heading": "사람이 정한 섹션", "purpose": "목적"}]}, ensure_ascii=False)
        result = generator.generate(job("report", settings={"confirm_outline": "no", "confirmed_outline": outline}))
        self.assertEqual(result.content["body"]["title"], "확정 제목")
        self.assertEqual([s["heading"] for s in result.content["body"]["sections"]], ["사람이 정한 섹션"])
        self.assertEqual([p for p in llm.prompts if "개요를 JSON" in p.user], [])

    def test_report_settings_accept_the_confirmation_options(self):
        from daon2_user_api.studio_v2_types import validate_settings
        _, settings = validate_settings("report", "summary", {"confirm_outline": "yes", "confirmed_outline": "{}"})
        self.assertEqual(settings["confirm_outline"], "yes")

    def test_search_failure_is_a_retryable_error(self):
        generator, _ = report(Finder(error=ExternalEvidenceError("KNOWLEDGE_EVIDENCE_UNAVAILABLE", 503, True)))
        with self.assertRaises(StudioError) as caught:
            generator.generate(job("report"))
        self.assertEqual(caught.exception.code, "PROVIDER_UNAVAILABLE")

    def test_same_evidence_keeps_one_label(self):
        finder = Finder(found=(evidence("same"),))
        generator, _ = report(finder)
        result = generator.generate(job("report"))
        self.assertEqual(len(result.evidence), 1)

    def test_registry_gives_knowledge_to_every_generator(self):
        llm = LLM()
        registry = GeneratorRegistry()
        report_generator, cards = ReportGenerator(Reader(), llm), FlashcardsGenerator(Reader(), llm)
        registry.register(report_generator)
        registry.register(cards)
        knowledge = StudioKnowledge(llm, Finder())
        registry.attach_knowledge(knowledge)
        self.assertIs(cards._knowledge, knowledge)  # noqa: SLF001
        self.assertIs(report_generator._knowledge, knowledge)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
