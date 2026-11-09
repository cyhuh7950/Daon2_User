"""소목차 단위 작성 엔진(WO-K4 3단계): 자료 계획, 작성, 저장, 일시 정지와 재개."""
from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace

from daon2_user_api.authoring import session as S
from daon2_user_api.authoring.agent import NO_MATERIAL, build_units, reconcile_units
from daon2_user_api.authoring.pipeline import AuthoringPipeline
from daon2_user_api.authoring.service import AuthoringGenerator, AuthoringService
from daon2_user_api.authoring.templates import AuthoringError, TemplateRegistry
from daon2_user_api.document_index_postgres import IndexedEvidenceChunk
from daon2_user_api.question_external_evidence import EvidenceTarget, ExternalEvidence, ExternalEvidenceError
from daon2_user_api.studio_v2_generation import GenerationContext, StudioCancelled
from daon2_user_api.studio_workspace import StudioContext

CTX = StudioContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1", "notebook-1")
REGISTRY = TemplateRegistry()
GENERAL = REGISTRY.get("general_document")


def evidence(block="b1", text="평가 기준은 기술 90점과 가격 10점이다."):
    chunk = IndexedEvidenceChunk(f"ext-{block}", "doc-1", "ver-1", 3, text, block, 0.9)
    return ExternalEvidence(chunk, "kc-rag", "p1", "프로젝트", "w1", "패키지", "doc-1", "ver-1", "run-1", block, 3, "제안요청서.pdf", text)


class Finder:
    def __init__(self, found=None, error=None):
        self.found, self.error, self.runs, self.limits = (evidence(),) if found is None else found, error, [], []

    def prepare(self, context):
        package = {"alias": "P1", "project_id": "p1", "project_name": "프로젝트", "work_package_id": "w1", "work_package_name": "제안서 작업"}
        return EvidenceTarget(SimpleNamespace(tenant_id="tenant-1"), "kc-rag", (package,))

    def run(self, target, requests, limit=5):
        self.runs.append(tuple(requests))
        self.limits.append(limit)
        if self.error:
            raise self.error
        return self.found


OUTLINE = {"sections": [{"key": "s1", "title": "1. 개요", "purpose": "배경", "subsections": [
    {"title": "1.1 배경", "purpose": "사업 배경", "target_chars": 400},
    {"title": "1.2 목적", "purpose": "사업 목적", "target_chars": 400}]},
    {"key": "s2", "title": "2. 평가", "purpose": "평가", "subsections": [{"title": "2.1 평가 기준", "purpose": "기준", "target_chars": 700}]}]}


class LLM:
    def __init__(self, paragraphs=None, plan=None):
        self.prompts, self.paragraphs, self.fail_titles = [], paragraphs, set()
        self.plan = {"needs": "기준", "requests": [{"knowledge": "rag", "package": "P1", "query": "평가 기준"}]} if plan is None else plan

    def generate(self, context, prompt, cancel_check=None):
        self.prompts.append(prompt)
        name = prompt.schema_name
        if name == "authoring_outline":
            data = copy.deepcopy(OUTLINE)
        elif name == "authoring_unit_plan":
            data = self.plan
        elif name == "authoring_unit":
            title = prompt.user.split("\n", 1)[0]
            if any(item in title for item in self.fail_titles):
                from daon2_user_api.studio_workspace import StudioError
                raise StudioError("STUDIO_VALIDATION_FAILED", 502)
            data = {"paragraphs": self.paragraphs if self.paragraphs is not None else [{"text": "평가 기준은 기술 90점이다.", "refs": ["K1"]}],
                    "open_items": [], "summary": f"요약-{title}", "terms": ["평가 기준"]}
        else:
            raise AssertionError(name)
        return SimpleNamespace(data=data, usage={}, model_id="m", provider_code="CUSTOM", connection_short_code="MS")


class Store:
    def __init__(self, session):
        self.session, self.revisions = session, 0

    def latest(self, context, output_id):
        return self.revisions, "generating", copy.deepcopy(self.session)

    def merge(self, context, output_id, mutate):
        self.session = mutate(copy.deepcopy(self.session))
        self.revisions += 1
        return copy.deepcopy(self.session)


def job(step):
    return GenerationContext(CTX, "sv2-x", "authored_document", None, {"step": step}, (), "", "ko", "create", lambda p, n: None, lambda: None)


def collected(target_pages=1):
    session = S.new_session(GENERAL, request_text="AI 사업 제안서", mode="agent", target_pages=target_pages)
    return S.apply_answers(GENERAL, session, [{"key": "document_goal", "value": "AI 사업 제안"}], skip_remaining=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.llm, self.finder = LLM(), Finder()
        self.store = None

    def pipeline(self):
        return AuthoringPipeline(REGISTRY, None, self.llm, None, lambda ctx, oid: self.store.latest(ctx, oid), evidence=self.finder,
                                 checkpoint=lambda ctx, oid, mutate: self.store.merge(ctx, oid, mutate))

    def analyzed(self, **kw):
        return self.pipeline().analyze(job("analyze"), collected(**kw))

    def generating(self, **kw):
        session = S.transition(self.analyzed(**kw), "generating")
        self.store = Store(session)
        return session

    def run_job(self):
        result = AuthoringGenerator(self.pipeline()).generate(job("generate"))
        self.store.session = dict(result.content)
        return result


class OutlineTests(Base):
    def test_llm_builds_the_outline_when_there_is_no_template(self):
        session = self.analyzed()
        self.assertEqual(session["state"], "review")
        self.assertEqual([u["title"] for u in session["units"]], ["1.1 배경", "1.2 목적", "2.1 평가 기준"])
        self.assertEqual({u["status"] for u in session["units"]}, {"pending"})
        self.assertEqual([s["title"] for s in session["plan"]["sections"]], ["1. 개요", "2. 평가"])

    def test_target_pages_set_the_total_size(self):
        outline = {"sections": [{"title": "본문", "subsections": [{"title": f"소목차 {i}", "target_chars": 500} for i in range(1, 9)]}]}
        units = build_units(GENERAL, outline, target_pages=5)
        self.assertAlmostEqual(sum(u["target_chars"] for u in units), 7500, delta=30)

    def test_one_unit_stays_within_what_one_call_can_write(self):
        outline = {"sections": [{"title": "본문", "subsections": [{"title": "하나뿐", "target_chars": 500}]}]}
        self.assertEqual(build_units(GENERAL, outline, target_pages=10)[0]["target_chars"], 2400)

    def test_required_template_sections_cannot_be_removed_and_get_llm_subsections(self):
        template = REGISTRY.get("rfp_response_proposal")
        outline = {"sections": [{"key": "understanding", "title": "엉뚱한 제목", "purpose": "목적", "subsections": [{"title": "배경", "purpose": "p", "target_chars": 300}]}]}
        units = build_units(template, outline, target_pages=None)
        self.assertEqual(len({u["section_key"] for u in units}), len(template.sections))
        first = next(u for u in units if u["section_key"] == "understanding")
        self.assertEqual((first["title"], first["section_title"]), ("배경", "1. 사업의 이해"))

    def test_unusable_outline_falls_back_to_template_sections(self):
        units = build_units(REGISTRY.get("rfp_response_proposal"), {"sections": "bad"}, target_pages=None)
        self.assertEqual(len(units), 6)

    def test_reconcile_follows_confirmed_sections(self):
        units = self.analyzed()["units"]
        kept = reconcile_units(units, [{"key": "s2", "title": "2. 평가", "purpose": "p"}, {"key": "new", "title": "3. 추가", "purpose": "q"}])
        self.assertEqual([u["section_key"] for u in kept], ["s2", "new"])
        self.assertEqual(kept[1]["title"], "3. 추가")


class WritingTests(Base):
    def test_each_unit_asks_for_material_then_writes_from_it(self):
        self.generating()
        result = self.run_job()
        self.assertEqual(result.content["state"], "completed")
        self.assertEqual(len(self.finder.runs), 3)
        self.assertEqual(self.finder.runs[0], (("P1", "평가 기준"),))
        write_prompts = [p for p in self.llm.prompts if p.schema_name == "authoring_unit"]
        self.assertIn("평가 기준은 기술 90점과 가격 10점이다.", write_prompts[0].user)
        self.assertEqual([e["origin"] for e in result.evidence], ["mcp_daon_rag"])
        document = result.content["document"]
        self.assertEqual([s["title"] for s in document["sections"]], ["1.1 배경", "1.2 목적", "2.1 평가 기준"])

    def test_larger_units_get_more_evidence(self):
        self.generating(target_pages=None)
        self.store.session["units"][0]["target_chars"] = 2400
        self.run_job()
        self.assertEqual(self.finder.limits[0], 10)

    def test_empty_plan_searches_with_the_subsection_title(self):
        self.llm.plan = {"requests": []}
        self.generating()
        self.run_job()
        self.assertIn("1.1 배경", self.finder.runs[0][0][1])

    def test_too_long_unit_is_asked_once_to_shorten(self):
        long_text = "평가 기준은 기술 90점이다. " * 200
        short = [{"text": "평가 기준은 기술 90점이다.", "refs": ["K1"]}]
        llm = self.llm
        original = llm.generate

        def generate(context, prompt, cancel_check=None):
            result = original(context, prompt, cancel_check)
            if prompt.schema_name == "authoring_unit":
                result.data["paragraphs"] = short if "[분량 초과]" in prompt.user else [{"text": long_text, "refs": ["K1"]}]
            return result

        llm.generate = generate
        self.generating()
        result = self.run_job()
        writes = [p for p in llm.prompts if p.schema_name == "authoring_unit"]
        self.assertEqual(len(writes), 6)
        self.assertEqual(result.content["units"][0]["paragraphs"][0]["text"], short[0]["text"])

    def test_inline_labels_become_references_and_are_not_shown(self):
        self.llm.paragraphs = [{"text": "기술 90점이다.[K1] 가격은 10점이다 [K1, K1]", "refs": []}]
        self.generating()
        paragraph = self.run_job().content["units"][0]["paragraphs"][0]
        self.assertEqual((paragraph["text"], paragraph["refs"]), ("기술 90점이다. 가격은 10점이다", ["K1"]))

    def test_earlier_summary_and_terms_reach_the_next_unit(self):
        self.generating()
        self.run_job()
        second = [p for p in self.llm.prompts if p.schema_name == "authoring_unit"][1]
        self.assertIn("요약-", second.user)
        self.assertIn("평가 기준", second.user)

    def test_finished_units_are_not_written_again_after_a_restart(self):
        self.generating()
        self.store.session["units"][0].update({"status": "done", "paragraphs": [{"text": "저장된 본문", "refs": [], "origin": "new"}], "summary": "앞 요약", "terms": []})
        result = self.run_job()
        self.assertEqual(len([p for p in self.llm.prompts if p.schema_name == "authoring_unit"]), 2)
        self.assertEqual(result.content["document"]["sections"][0]["paragraphs"][0]["text"], "저장된 본문")

    def test_document_keeps_the_required_checks(self):
        self.generating()
        ids = [check["id"] for check in self.run_job().content["document"]["checks"]]
        self.assertIn("term_consistency", ids)
        self.assertIn("required_clauses", ids)

    def test_every_unit_is_saved_as_it_finishes(self):
        self.generating()
        self.run_job()
        self.assertEqual(self.store.revisions, 3)

    def test_cancel_stops_the_job(self):
        self.generating()
        from dataclasses import replace
        def cancel():
            raise StudioCancelled()
        with self.assertRaises(StudioCancelled):
            AuthoringGenerator(self.pipeline()).generate(replace(job("generate"), cancel_check=cancel))


class InterventionTests(Base):
    def test_pause_stops_after_the_current_unit_and_resume_continues(self):
        self.generating()
        original = self.store.merge

        def pause_after_first(ctx, oid, mutate):
            merged = original(ctx, oid, mutate)
            self.store.session["pause_requested"] = True
            return copy.deepcopy(self.store.session)

        pipeline = AuthoringPipeline(REGISTRY, None, self.llm, None, lambda ctx, oid: self.store.latest(ctx, oid), evidence=self.finder, checkpoint=pause_after_first)
        result = AuthoringGenerator(pipeline).generate(job("generate"))
        self.store.session = dict(result.content)
        self.assertEqual(result.content["state"], "paused")
        self.assertEqual([u["status"] for u in result.content["units"]], ["done", "pending", "pending"])
        self.store.session = S.resume(self.store.session)
        self.assertFalse(self.store.session["pause_requested"])
        final = self.run_job()
        self.assertEqual(final.content["state"], "completed")
        self.assertEqual(len([p for p in self.llm.prompts if p.schema_name == "authoring_unit"]), 3)

    def test_missing_material_stops_for_a_person(self):
        self.finder.found = ()
        self.llm.paragraphs = [{"text": "확인되지 않은 내용", "refs": []}]
        self.generating()
        result = self.run_job()
        self.assertEqual((result.content["state"], result.content["pause_reason"]), ("paused", "needs_review"))
        unit = result.content["units"][0]
        self.assertEqual(unit["status"], "needs_review")
        self.assertIn(NO_MATERIAL, unit["paragraphs"][0]["text"])
        self.assertEqual([u["status"] for u in result.content["units"][1:]], ["pending", "pending"])

    def test_resume_accepts_the_reviewed_unit_and_moves_on(self):
        self.finder.found = ()
        self.llm.paragraphs = [{"text": "확인되지 않은 내용", "refs": []}]
        self.generating()
        self.run_job()
        resumed = S.resume(self.store.session)
        self.assertEqual(resumed["units"][0]["status"], "done")
        self.assertEqual(resumed["state"], "generating")

    def test_edited_unit_is_kept_and_reaches_the_next_summary(self):
        self.generating()
        self.store.session = S.edit_unit(S.transition(self.store.session, "paused"), self.store.session["units"][0]["key"], ["사람이 고친 본문"])
        self.store.session = S.resume(self.store.session)
        result = self.run_job()
        first = result.content["document"]["sections"][0]
        self.assertEqual(first["paragraphs"][0]["text"], "사람이 고친 본문")
        self.assertTrue(result.content["units"][0]["locked"])
        self.assertIn("사람이 고친 본문", [p for p in self.llm.prompts if p.schema_name == "authoring_unit"][0].user)

    def test_failed_unit_does_not_discard_the_others(self):
        self.llm.fail_titles = {"1.2 목적"}
        self.generating()
        result = self.run_job()
        self.assertEqual([u["status"] for u in result.content["units"]], ["done", "failed", "done"])
        self.assertEqual((result.content["state"], result.content["pause_reason"]), ("paused", "unit_failed"))
        self.llm.fail_titles = set()
        self.store.session = S.resume(self.store.session)
        self.assertEqual(self.run_job().content["state"], "completed")

    def test_knowledge_failure_only_fails_that_unit(self):
        self.finder.error = ExternalEvidenceError("KNOWLEDGE_EVIDENCE_UNAVAILABLE", 503, True)
        self.generating()
        result = self.run_job()
        self.assertEqual({u["status"] for u in result.content["units"]}, {"failed"})
        self.assertEqual(result.content["units"][0]["error_code"], "KNOWLEDGE_EVIDENCE_UNAVAILABLE")

    def test_outline_change_reopens_only_affected_units(self):
        session = self.generating()
        for unit in session["units"]:
            unit.update({"status": "done", "paragraphs": [{"text": "본문", "refs": [], "origin": "new"}]})
        session["units"][2]["locked"] = True
        paused = S.transition(session, "paused")
        keys = [u["key"] for u in paused["units"]]
        change = [{"key": keys[0]}, {"key": keys[1], "title": "1.2 바뀐 목적"}, {"key": keys[2]}]
        self.assertEqual(S.outline_impact(paused, change), [keys[1]])
        updated = S.apply_outline(paused, change)
        self.assertEqual([u["status"] for u in updated["units"]], ["done", "pending", "done"])
        self.assertEqual(updated["units"][1]["title"], "1.2 바뀐 목적")

    def test_one_finished_unit_can_be_written_again(self):
        session = S.transition(self.generating(), "paused")
        session["units"][0].update({"status": "done", "paragraphs": [{"text": "이전 본문", "refs": [], "origin": "new"}], "summary": "요약"})
        updated = S.redo_unit(session, session["units"][0]["key"])
        self.assertEqual((updated["units"][0]["status"], updated["units"][0]["paragraphs"]), ("pending", []))

    def test_unit_fixed_by_a_person_is_not_rewritten(self):
        session = S.transition(self.generating(), "paused")
        session["units"][0].update({"status": "done", "locked": True})
        with self.assertRaises(AuthoringError):
            S.redo_unit(session, session["units"][0]["key"])

    def test_finished_document_can_be_reopened(self):
        session = self.generating()
        for unit in session["units"]:
            unit["status"] = "done"
        finished = S.transition(session, "completed")
        finished["document"] = {"sections": []}
        reopened = S.reopen(finished)
        self.assertEqual((reopened["state"], reopened["pause_reason"]), ("paused", "user"))

    def test_only_writing_mode_documents_can_be_reopened(self):
        with self.assertRaises(AuthoringError):
            S.reopen({"state": "completed", "mode": "legacy"})

    def test_paused_session_only_moves_through_allowed_states(self):
        session = S.transition(self.generating(), "paused")
        self.assertEqual(S.transition(session, "generating")["state"], "generating")
        with self.assertRaises(AuthoringError):
            S.transition(session, "completed")


class ServiceTests(Base):
    class Studio:
        def __init__(self, session):
            self.session, self.applied, self.merged = session, [], 0

        def latest_content(self, context, output_id):
            return 7, "generating", copy.deepcopy(self.session)

        def authoring_merge(self, context, output_id, mutate):
            self.merged += 1
            self.session = mutate(copy.deepcopy(self.session))
            return copy.deepcopy(self.session)

        def authoring_apply(self, context, output_id, expected_revision, mutate, *, enqueue_step=None, source_version_ids=()):
            self.session = mutate(copy.deepcopy(self.session))
            self.applied.append(enqueue_step)
            return {"revision_no": expected_revision + 1, "state": self.session["state"], "queued": enqueue_step is not None}

    def service(self, session):
        self.studio = self.Studio(session)
        return AuthoringService(self.studio, REGISTRY)

    def test_pause_is_accepted_while_the_job_runs(self):
        service = self.service(self.generating())
        service.control(CTX, "sv2-x", "pause", None)
        self.assertTrue(self.studio.session["pause_requested"])
        self.assertEqual(self.studio.merged, 1)

    def test_resume_requeues_the_job(self):
        session = S.transition(self.generating(), "paused")
        service = self.service(session)
        service.control(CTX, "sv2-x", "resume", 7)
        self.assertEqual(self.studio.applied, ["generate"])
        self.assertEqual(self.studio.session["state"], "generating")

    def test_pause_outside_generation_is_refused(self):
        service = self.service(self.analyzed())
        with self.assertRaises(AuthoringError):
            service.control(CTX, "sv2-x", "pause", None)

    def test_redo_requests_only_that_unit(self):
        session = S.transition(self.generating(), "paused")
        session["units"][0]["status"] = "done"
        service = self.service(session)
        service.control(CTX, "sv2-x", "redo", 7, unit_key=session["units"][0]["key"])
        self.assertEqual(self.studio.session["units"][0]["status"], "pending")
        self.assertEqual(self.studio.applied, [None])

    def test_reopen_returns_a_finished_document_to_paused(self):
        session = self.generating()
        finished = S.transition(session, "completed")
        service = self.service(finished)
        service.control(CTX, "sv2-x", "reopen", 7)
        self.assertEqual(self.studio.session["state"], "paused")

    def test_outline_preview_does_not_change_the_session(self):
        session = S.transition(self.generating(), "paused")
        for unit in session["units"]:
            unit["status"] = "done"
        service = self.service(session)
        key = session["units"][0]["key"]
        change = [{"key": key, "title": "새 제목"}, *[{"key": u["key"]} for u in session["units"][1:]]]
        result = service.outline(CTX, "sv2-x", 7, change, confirm=False)
        self.assertEqual(result["affected"], [key])
        self.assertEqual(self.studio.applied, [])
        self.assertEqual(self.studio.session["units"][0]["status"], "done")


if __name__ == "__main__":
    unittest.main()
