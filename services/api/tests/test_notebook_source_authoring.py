"""노트북 기준 문서의 입력 역할과 작성 작업 검수."""

import copy
import io
import json
import re
from contextlib import nullcontext
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from daon2_user_api import runtime
from daon2_user_api.authoring import session
from daon2_user_api.authoring.export import authored_elements
from daon2_user_api.authoring.pipeline import AuthoringPipeline
from daon2_user_api.authoring.service import AuthoringGenerator, AuthoringService, _view
from daon2_user_api.authoring.templates import AuthoringError, TemplateRegistry
from daon2_user_api.studio_context_builder import build_pack
from daon2_user_api.studio_source_reader import SourceSection, SourceText, StudioSourceReader
from daon2_user_api.studio_v2_export import export_v2
from daon2_user_api.studio_v2_generation import GeneratorRegistry
from daon2_user_api.studio_v2_queue import StudioV2Job
from daon2_user_api.studio_v2_routes import register_authoring_routes
from daon2_user_api.studio_v2_worker import StudioV2Worker
from daon2_user_api.studio_workspace import StudioContext, StudioError
from test_docx_source import docx_bytes


@pytest.mark.parametrize(("template_id", "answers", "versions"), [
    ("reference_proposal_draft", [
        {"key": "reference_proposals", "source_version_ids": ["proposal-v1"]},
        {"key": "purpose", "value": "새 고객용 운영 제안서를 작성"},
    ], ["proposal-v1"]),
    ("rfp_response_proposal", [
        {"key": "rfp_document", "source_version_ids": ["rfp-v1"]},
        {"key": "reference_proposals", "source_version_ids": ["proposal-v1"]},
    ], ["rfp-v1", "proposal-v1"]),
    ("insurance_terms_draft", [
        {"key": "base_terms", "source_version_ids": ["terms-v1"]},
        {"key": "product_type", "value": "자동차보험"},
        {"key": "changes", "value": "지급 기한 변경"},
    ], ["terms-v1"]),
])
def test_current_sessions_queue_reference_sources(template_id, answers, versions):
    template = TemplateRegistry().get(template_id)
    current = session.new_session(template, mode="agent", notebook_references=True)
    updated = session.apply_answers(template, current, answers, skip_remaining=True)
    assert updated["state"] == "analyzing"
    assert session.generation_versions(template, updated) == versions


def test_terms_requires_one_base_and_previous_session_still_reads():
    template = TemplateRegistry().get("insurance_terms_draft")
    previous = session.new_session(template, mode="agent")
    current = session.new_session(template, mode="agent", notebook_references=True)
    assert [question["key"] for question in previous["pending_questions"]] == ["product_type"]
    assert "base_terms" in {question["key"] for question in current["pending_questions"]}
    with pytest.raises(AuthoringError, match="AUTHORING_INPUT_INVALID"):
        session.apply_answers(template, current, [{"key": "base_terms", "source_version_ids": ["one", "two"]}])


def test_terms_product_choices_follow_the_requested_order():
    template = TemplateRegistry().get("insurance_terms_draft")
    expected = [
        "연금보험", "저축보험", "종신보험", "정기보험", "암 보험", "건강보험", "치아보험", "자녀보험",
        "실손보험", "여행보험", "생활보험", "화재보험", "자동차보험", "운전자보험", "팻 보험", "기타",
    ]
    current = session.new_session(template, mode="agent", notebook_references=True)
    question = next(question for question in current["pending_questions"] if question["key"] == "product_type")
    assert question["required"] is True
    assert question["choices"] == expected
    for product in expected:
        updated = session.apply_answers(template, current, [{"key": "product_type", "value": product}])
        assert updated["inputs"]["product_type"] == product


def test_legacy_medical_insurance_answer_can_continue():
    template = TemplateRegistry().get("insurance_terms_draft")
    current = session.new_session(template, mode="agent", notebook_references=True)
    legacy_answer = {"key": "product_type", "value": "실손의료보험"}
    remaining = [
        {"key": "base_terms", "source_version_ids": ["terms-v1"]},
        {"key": "changes", "value": "지급 절차를 변경"},
    ]
    submitted = session.apply_answers(template, current, [legacy_answer, *remaining])
    assert submitted["inputs"]["product_type"] == "실손보험"
    assert submitted["state"] == "analyzing"

    current["inputs"]["product_type"] = legacy_answer["value"]
    resumed = session.apply_answers(template, current, remaining)
    assert resumed["state"] == "analyzing"
    assert resumed["inputs"]["product_type"] == "실손의료보험"


def test_rfp_cannot_also_be_its_own_reference():
    template = TemplateRegistry().get("rfp_response_proposal")
    current = session.new_session(template, mode="agent", notebook_references=True)
    answers = [{"key": key, "source_version_ids": ["rfp-v1"]} for key in ("rfp_document", "reference_proposals")]
    with pytest.raises(AuthoringError, match="AUTHORING_SOURCE_ROLE_CONFLICT"):
        session.apply_answers(template, current, answers)


PROPOSAL = "시범 운영에서는 단계별 인수 목록을 사용한다."
RFP = "서비스 전환 계획을 제출해야 한다."
TERMS = ("별빛 자동차보험 약관\n제1장 총칙\n계약자는 보험계약의 내용을 확인할 수 있다.\n"
         "제2장 보장내용\n보장 범위는 보험증권에 적는다.\n제3장 보험금의 지급\n"
         "보험금은 서류를 받은 후 심사한다. 지급이 늦어지면 서면으로 통지한다. 증서는 인편으로 배달한다.\n"
         "제4장 면책\n계약이 정한 면책 사유를 통지한다.")
MODIFIED = "지급이 늦어지면 전자우편으로 통지한다."
ADDED = "계약자는 온라인 창구에서 진행 상태를 확인할 수 있다."
RETAINED = "증서는 인편으로 배달한다."
EDITORIAL = "증서의 인편 배달 조항을 삭제한다."
PATH = "/api/v1/workspaces/ws-test/notebooks/nb-test/studio/authoring/sessions"


class FixtureSources:
    documents = {
        "rfp-v1": ("요구서.pdf", RFP),
        "proposal-v1": ("기존 제안서.docx", PROPOSAL),
        "terms-v1": ("기준 약관.txt", TERMS),
    }

    def read(self, context, ids, **options):
        return tuple(SourceText(version, version, self.documents[version][0],
                                (SourceSection(version, None, "page", "7", None, self.documents[version][1]),), False)
                     for version in ids)


class FixtureModel:
    def __init__(self):
        self.prompts = []
        self.conflicting_terms = False
        self.repair_terms = False
        self.review_unavailable = False
        self.unmatched_review_quotes = 0
        self.split_payment = False
        self.repeat_chapter_heading = False

    def generate(self, context, prompt, cancel_check=None):
        self.prompts.append(prompt)
        name = prompt.schema_name
        if name == "authoring_outline":
            data = {"sections": [{"key": "payment", "title": "보험금의 지급", "subsections": [
                {"title": "청구 절차", "purpose": "청구 서류 심사"},
                {"title": "지급 지연 통지", "purpose": "전자우편 통지"},
            ]}] if self.split_payment else []}
        elif name == "authoring_unit":
            def ref(text):
                return re.search(r'<source id="(S[0-9]+)"[^>]*>\n[^<]*' + re.escape(text), prompt.user).group(1)

            if "[기준 약관 구간]" in prompt.user:
                assert "전자우편" in prompt.user
                cited = ref(TERMS)
                paragraphs = [{"text": text, "refs": [cited]} for text in ("보험금은 서류를 받은 후 심사한다.", MODIFIED, ADDED)]
                if self.repeat_chapter_heading:
                    paragraphs[0]["text"] = "### 제 3 장 보험금의 지급\n" + paragraphs[0]["text"]
                if self.conflicting_terms and not (self.repair_terms and "[검수 결과와 고쳐 쓸 본문]" in prompt.user):
                    paragraphs.extend({"text": text, "refs": [cited]} for text in (RETAINED, EDITORIAL))
            else:
                paragraphs = [{"text": PROPOSAL, "refs": [ref(PROPOSAL)]}]
                if "요구서.pdf" in prompt.user:
                    paragraphs.append({"text": RFP, "refs": [ref(RFP)]})
            data = {"paragraphs": paragraphs, "summary": "작성 완료", "terms": []}
        elif name == "authoring_terms_body_review":
            if self.review_unavailable:
                raise StudioError("STUDIO_VALIDATION_FAILED", 502)
            rows = json.loads(prompt.user.split("[검사할 본문]\n", 1)[1])
            assert rows and {row["section_title"] for row in rows} == {"제3장 보험금의 지급"}
            assert "확정한 각 문단의 section_title" in prompt.system
            if self.unmatched_review_quotes:
                self.unmatched_review_quotes -= 1
                data = {"issues": [{"unit_key": rows[0]["unit_key"], "quote": "기준 문서에만 있는 문장",
                                    "reason": "저장된 초안과 대조할 수 없는 인용"}]}
                return SimpleNamespace(data=data)
            data = {"issues": [{"unit_key": row["unit_key"], "quote": row["text"], "reason": "삭제 요청한 인편 배달을 본문에 유지했습니다."}
                               for row in rows if row["text"] == RETAINED]}
        else:
            data = {"items": []}
        return SimpleNamespace(data=data, provider_code="FIXTURE", model_id="fixture", connection_short_code="FIXTURE")


class FixtureRepository:
    """라우트·작성 서비스·워커 간 계약의 저장소 및 큐 대역."""

    output_id = "output-fixture"

    def __init__(self):
        self.content, self.revision, self.status = {}, 0, "completed"
        self.jobs, self.allowed = [], set(FixtureSources.documents)
        self.evidence, self.sources = [], []
        self.error_code = None

    def create_authoring_session(self, context, title, content, idempotency_key):
        self.add_revision(context, self.output_id, "generated", content)
        return {"output_id": self.output_id}

    def latest_content(self, context, output_id):
        content = copy.deepcopy(self.content)
        if self.error_code:
            content["error_code"] = self.error_code
        return self.revision, self.status, content

    def require_scope(self, connection, context, versions):
        if not set(versions) <= self.allowed:
            raise StudioError("NOTEBOOK_SCOPE_MISMATCH", 409)

    def authoring_apply(self, context, output_id, expected_revision, mutate, *, enqueue_step=None,
                        source_version_ids=(), reference_version_ids=()):
        assert expected_revision == self.revision
        versions = source_version_ids if enqueue_step else reference_version_ids
        self.require_scope(None, context, versions)
        self.authoring_merge(context, output_id, mutate)
        if enqueue_step:
            self.status = "queued"
            request = {"notebook_id": context.notebook_id, "source_version_ids": list(versions), "mode": "authoring",
                       "type_id": "authored_document", "settings": {"step": enqueue_step}}
            self.jobs.append(StudioV2Job(context.tenant_id, context.workspace_id, enqueue_step, output_id, context.actor_id, 1, 3, 1, request))
        return {"revision_no": self.revision, "queued": bool(enqueue_step), "state": self.content["state"]}

    def authoring_merge(self, context, output_id, mutate):
        self.add_revision(context, output_id, "generated", mutate(copy.deepcopy(self.content)))
        return copy.deepcopy(self.content)

    def add_revision(self, context, output_id, revision_type, content, *, sources=(), evidence=(), **kwargs):
        self.revision += 1
        self.content, self.sources, self.evidence = copy.deepcopy(content), list(sources), list(evidence)

    def get_customization(self, context):
        return {"instruction": ""}


@pytest.fixture
def writing(monkeypatch):
    app = FastAPI()
    monkeypatch.setattr(runtime, "_principal", lambda request, deps: SimpleNamespace(tenant_id="tenant-test", user_id="actor-test"))
    dependencies = SimpleNamespace(settings=SimpleNamespace(policy_version="test"),
                                   authorization_service=SimpleNamespace(authorize_action=lambda **_: None))

    @app.middleware("http")
    async def trace(request: Request, call_next):
        request.state.trace_id = "trace-authoring-fixture"
        return await call_next(request)

    @app.exception_handler(StudioError)
    async def studio_error(request: Request, error: StudioError):
        return runtime._error_response(error.status, error.code, request.state.trace_id)

    repository, model = FixtureRepository(), FixtureModel()
    templates, generators = TemplateRegistry(), GeneratorRegistry()
    pipeline = AuthoringPipeline(templates, FixtureSources(), model, None, repository.latest_content, checkpoint=repository.authoring_merge)
    generators.register(AuthoringGenerator(pipeline))
    register_authoring_routes(app, dependencies, AuthoringService(repository, templates))

    def finish(job, worker_id, *, state, error_code=None):
        repository.status, repository.error_code = state, error_code

    queue = SimpleNamespace(start=lambda job, worker_id: job, heartbeat=lambda *args, **kwargs: False, finish=finish)
    worker = StudioV2Worker(queue, repository, generators, SimpleNamespace(_transaction=lambda _: nullcontext()), worker_id="test-worker")
    with TestClient(app, headers={"Idempotency-Key": "test-authoring-flow-key"}) as client:
        yield client, repository, model, worker


@pytest.mark.parametrize(("template", "answers", "versions"), [
    ("reference_proposal_draft", [{"key": "reference_proposals", "source_version_ids": ["proposal-v1"]},
                                 {"key": "purpose", "value": "새 고객의 운영 절차를 제안"}], ["proposal-v1"]),
    ("rfp_response_proposal", [{"key": "rfp_document", "source_version_ids": ["rfp-v1"]},
                               {"key": "reference_proposals", "source_version_ids": ["proposal-v1"]}], ["rfp-v1", "proposal-v1"]),
    ("insurance_terms_draft", [{"key": "base_terms", "source_version_ids": ["terms-v1"]},
                               {"key": "product_type", "value": "자동차보험"},
                               {"key": "changes", "value": "지급 지연 시 전자우편으로 통지하고 온라인 확인 창구를 신설"}], ["terms-v1"]),
])
def test_three_paths_through_routes_worker_reload_references_and_docx(writing, template, answers, versions):
    client, repo, model, worker = writing
    opened = client.post(PATH, json={"template_id": template})
    assert opened.status_code == 201, opened.text
    output = PATH + "/" + opened.json()["data"]["output_id"]
    receipt = client.post(output + "/answers", json={"expected_revision": 1, "answers": answers, "skip_remaining": True})
    assert receipt.status_code == 202, receipt.text
    job = repo.jobs.pop()
    assert job.request_json["source_version_ids"] == versions
    worker._process(job)

    review = client.get(output).json()["data"]
    assert review["state"] == "review", review["error_code"]
    assert FixtureSources.documents[versions[-1]][1] in next(prompt.user for prompt in model.prompts if prompt.schema_name == "authoring_outline")
    assert bool(review["requirements"]) == (template == "rfp_response_proposal")
    plan_sections = review["plan"]["sections"]
    selected = [section for section in plan_sections if section["key"] == "payment"] if template == "insurance_terms_draft" else plan_sections[:1]
    receipt = client.put(output + "/review", json={"expected_revision": review["revision_no"], "confirm": True,
                                                 "plan_sections": selected, "output_formats": ["docx"]})
    assert receipt.status_code == 202, receipt.text
    job = repo.jobs.pop()
    assert job.request_json["source_version_ids"] == versions
    worker._process(job)

    completed = client.get(output).json()["data"]
    assert completed["state"] == "completed", completed["error_code"]
    assert [source["source_version_id"] for source in repo.sources] == versions
    assert {item["source_version_id"] for item in repo.evidence} == set(versions)
    assert {item["locator_value"] for item in repo.evidence} == {"7"}
    exported = export_v2("docx", {"output_id": repo.output_id, "title": completed["document"]["title"], "type_id": "authored_document",
                                  "revision": {"content": completed}, "evidence": repo.evidence}).content
    with ZipFile(io.BytesIO(exported)) as archive:
        body = archive.read("word/document.xml").decode()
    if template == "insurance_terms_draft":
        assert completed["document"]["title"] == "보험 약관 초안"
        assert "보험 약관 초안 초안" not in body
        changes = next(check for check in completed["document"]["checks"] if check["id"] == "terms_change_summary")
        assert changes["summary"] == {"unchanged": 1, "modified": 1, "new": 1, "delete_suggested": 1}
        assert completed["document"]["sections"][-1]["delete_suggested"] == ["증서는 인편으로 배달한다."]
        assert "전자우편" in body and "삭제 제안" in body
        # 근거 부록은 위치와 파일명을 가리키며, 작성하지 않은 조항을 본문에 싣지 않는다.
        assert not any(marker in body for marker in ("제1장 총칙", "제2장 보장내용", "제4장 면책"))
    else:
        assert PROPOSAL in body
        assert ("부록 A. 요구사항 대응표" in body) == (template == "rfp_response_proposal")
        assert "price_schedule: [작성 필요]" in completed["document"]["open_items"]
        assert "미결 항목 없음" not in body
        if template == "rfp_response_proposal":
            coverage = completed["document"]["coverage"]
            assert coverage
            assert {row["section_key"] for row in coverage} <= {section["key"] for section in completed["document"]["sections"]}


@pytest.mark.parametrize(("claim", "warning"), [
    ("이 사업은 목록 999건을 처리한다.", "ANCHOR_MISMATCH"),
    ("현행 검색과 반출 과정에 일부 불편이 있다.", "UNSUPPORTED_SOURCE_CLAIM"),
    ("현행 검색 절차를 검토하고 개선안을 제안한다.", None),
    ("현행 검색과 반출은 별도 화면에서 처리한다.", None),
])
def test_proposal_grounding_requires_correction_before_resume(writing, monkeypatch, claim, warning):
    client, repo, model, worker = writing
    generate = model.generate
    calls = []

    def generate_with_claim(context, prompt, cancel_check=None):
        result = generate(context, prompt, cancel_check)
        if prompt.schema_name == "authoring_unit":
            calls.append(prompt.user)
            if len(calls) == 2 or "[근거 검사 후 수정]" in prompt.user:
                result.data["paragraphs"][0]["text"] = claim
        return result

    monkeypatch.setattr(model, "generate", generate_with_claim)
    opened = client.post(PATH, json={"template_id": "reference_proposal_draft"})
    output = PATH + "/" + opened.json()["data"]["output_id"]
    assert client.post(output + "/answers", json={"expected_revision": 1, "skip_remaining": True, "answers": [
        {"key": "reference_proposals", "source_version_ids": ["proposal-v1"]},
        {"key": "purpose", "value": "도서관 업무 절차 개선. 현행 검색과 반출은 별도 화면에서 처리한다."},
    ]}).status_code == 202
    worker._process(repo.jobs.pop())
    review = client.get(output).json()["data"]
    assert client.put(output + "/review", json={"expected_revision": review["revision_no"], "confirm": True,
                                                "plan_sections": review["plan"]["sections"][:2]}).status_code == 202
    worker._process(repo.jobs.pop())
    current = client.get(output).json()["data"]
    assert len(calls) >= 2
    if warning is None:
        assert current["state"] == "completed"
        return
    assert current["state"] == "paused"
    assert current["units"][0]["status"] == "done"
    unit = current["units"][1]
    assert unit["status"] == "needs_review"
    assert [item["code"] for item in unit["warnings"]] == [warning]
    control = output + "/control"
    assert client.post(control, json={"action": "resume", "expected_revision": current["revision_no"]}).status_code == 409
    assert not repo.jobs
    assert client.get(output).json()["data"] == current
    assert client.put(output + "/units/" + unit["key"], json={"expected_revision": current["revision_no"],
                                                              "paragraphs": [claim, "다른 문장 추가"]}).status_code == 422
    assert client.put(output + "/units/" + unit["key"], json={"expected_revision": current["revision_no"],
                                                              "paragraphs": [PROPOSAL]}).status_code == 202
    edited = client.get(output).json()["data"]
    assert client.post(control, json={"action": "resume", "expected_revision": edited["revision_no"]}).status_code == 202
    worker._process(repo.jobs.pop())
    final = client.get(output).json()["data"]
    assert final["state"] == "completed"
    assert final["units"][0] == current["units"][0]
    assert final["units"][1]["paragraphs"] == [{"text": PROPOSAL, "refs": [], "origin": "user"}]
    assert not final["units"][1]["warnings"]
    assert len(calls) == 3


@pytest.mark.parametrize("template", ["rfp_response_proposal", "reference_proposal_draft"])
def test_proposal_automatically_repairs_grounding_before_storing_a_unit(writing, monkeypatch, template):
    client, repo, model, worker = writing
    generate = model.generate
    prompts = []

    def generate_with_claim(context, prompt, cancel_check=None):
        result = generate(context, prompt, cancel_check)
        if prompt.schema_name == "authoring_unit":
            prompts.append(prompt.user)
            if len(prompts) == 1:
                result.data["paragraphs"][0]["text"] = "현재 장비 999대가 고장 상태이다."
        return result

    monkeypatch.setattr(model, "generate", generate_with_claim)
    opened = client.post(PATH, json={"template_id": template}).json()["data"]
    output = PATH + "/" + opened["output_id"]
    answers = [{"key": "reference_proposals", "source_version_ids": ["proposal-v1"]}]
    if template == "rfp_response_proposal":
        answers.insert(0, {"key": "rfp_document", "source_version_ids": ["rfp-v1"]})
    else:
        answers.append({"key": "purpose", "value": "도서관 업무 절차 개선"})
    assert client.post(output + "/answers", json={"expected_revision": 1, "answers": answers,
                                                 "skip_remaining": True}).status_code == 202
    worker._process(repo.jobs.pop())
    review = client.get(output).json()["data"]
    assert client.put(output + "/review", json={"expected_revision": review["revision_no"], "confirm": True,
                                                "plan_sections": review["plan"]["sections"][:1]}).status_code == 202
    worker._process(repo.jobs.pop())
    completed = client.get(output).json()["data"]
    assert completed["state"] == "completed"
    assert "[근거 검사 후 수정]" in prompts[1]
    assert "ANCHOR_MISMATCH" in prompts[1]
    assert "UNSUPPORTED_SOURCE_CLAIM" in prompts[1]
    assert "999대" not in str(completed["document"])


def test_rfp_quantity_anchors_keep_units_when_translating_english_evidence():
    from daon2_user_api.document_understanding_adapter import _evidence_anchors

    source = _evidence_anchors("Digitize 240 catalogue records. Verify 30 samples. Delivery in eight weeks. Retain the three-phase structure.")
    assert _evidence_anchors("목록 240건, 표본 30건, 8주, 3단계").issubset(source)
    for wrong in ("목록 241건", "표본 31건", "8개월", "4단계"):
        assert not _evidence_anchors(wrong).issubset(source)


def test_docx_uses_existing_subsection_for_legacy_coverage():
    sections = [
        {"key": "schedule__u1", "title": "운영 개요", "paragraphs": [{"text": "사용자를 안내한다."}]},
        {"key": "schedule__u2", "title": "검수 일정", "paragraphs": [{"text": "8주 안에 납품을 완료한다."}]},
    ]
    doc = {"title": "제안서", "sections": sections, "coverage": [
        {"requirement_id": "REQ-001", "text": "8주 안에 납품한다.", "section_key": "schedule", "status": "covered"},
    ]}
    output = {"type_id": "authored_document", "output_id": "fixture", "title": doc["title"], "revision": {"content": {"document": doc}}}
    table = next(entry[1] for entry in authored_elements(output) if entry[0] == "table")
    assert table[1][2] == "검수 일정"
    view = _view({"document": doc}, 37, "completed")["document"]
    assert view["coverage"][0]["section_key"] == "schedule__u2"
    assert doc["coverage"][0]["section_key"] == "schedule"
    with ZipFile(io.BytesIO(export_v2("docx", output).content)) as archive:
        body = archive.read("word/document.xml").decode()
    assert "검수 일정</w:t>" in body
    assert "<w:tblHeader/>" in body
    assert "<w:cantSplit/>" in body
    assert "<w:pageBreakBefore/>" in body
    assert '<w:br w:type="page"/>' not in body


@pytest.mark.parametrize(("analysis", "key"), [("rfp_requirements", "proposer_profile"), ("base_document", "price_schedule")])
def test_legacy_proposal_docx_keeps_skipped_inputs_open(analysis, key):
    doc = {"title": "제안서", "analysis": analysis, "sections": [], "open_items": [],
           "assumptions": [{"key": key, "reason": "user_skipped", "default": "[작성 필요]"}]}
    output = {"type_id": "authored_document", "output_id": "fixture", "title": doc["title"], "revision": {"content": {"document": doc}}}
    with ZipFile(io.BytesIO(export_v2("docx", output).content)) as archive:
        body = archive.read("word/document.xml").decode()
    assert f"{key}: [작성 필요]" in body
    assert body.count(f"{key}:") == 1
    assert "미결 항목 없음" not in body
    view = _view({"document": doc}, 37, "completed")["document"]
    assert view["open_items"] == [f"{key}: [작성 필요]"]
    assert doc["open_items"] == []


def _generate_payment_terms(writing):
    client, repo, _, worker = writing
    opened = client.post(PATH, json={"template_id": "insurance_terms_draft"})
    assert opened.status_code == 201, opened.text
    output = PATH + "/" + opened.json()["data"]["output_id"]
    receipt = client.post(output + "/answers", json={"expected_revision": 1, "skip_remaining": True, "answers": [
        {"key": "base_terms", "source_version_ids": ["terms-v1"]},
        {"key": "product_type", "value": "자동차보험"},
        {"key": "changes", "value": "전자우편으로 통지하고 인편 배달을 삭제"},
    ]})
    assert receipt.status_code == 202, receipt.text
    worker._process(repo.jobs.pop())
    review = client.get(output).json()["data"]
    sections = [section for section in review["plan"]["sections"] if section["key"] == "payment"]
    receipt = client.put(output + "/review", json={"expected_revision": review["revision_no"], "confirm": True,
                                                 "plan_sections": sections, "output_formats": ["docx"]})
    assert receipt.status_code == 202, receipt.text
    worker._process(repo.jobs.pop())
    return output, client.get(output).json()["data"]


def test_notebook_terms_writes_selected_chapter_once_even_if_outline_splits_it(writing):
    _, _, model, _ = writing
    model.split_payment = True
    _, completed = _generate_payment_terms(writing)

    assert completed["state"] == "completed"
    assert [unit["section_key"] for unit in completed["units"]] == ["payment"]
    body = [p["text"] for unit in completed["units"] for p in unit["paragraphs"]]
    assert body.count(MODIFIED) == 1


def test_terms_chapter_heading_only_appears_as_the_section_title(writing):
    _, repo, model, _ = writing
    model.repeat_chapter_heading = True

    _, completed = _generate_payment_terms(writing)

    assert completed["state"] == "completed"
    section, = completed["document"]["sections"]
    assert section["title"] == "제3장 보험금의 지급"
    assert section["paragraphs"][0]["text"] == "보험금은 서류를 받은 후 심사한다."
    assert section["delete_suggested"] == ["증서는 인편으로 배달한다."]
    exported = export_v2("docx", {"output_id": repo.output_id, "title": completed["document"]["title"],
                                  "type_id": "authored_document", "revision": {"content": completed},
                                  "evidence": repo.evidence}).content
    with ZipFile(io.BytesIO(exported)) as archive:
        docx = archive.read("word/document.xml").decode()
    assert "제 3 장 보험금의 지급" not in docx
    assert "보험금은 서류를 받은 후 심사한다." in docx


def test_terms_chapter_heading_strips_joined_article_prefix_but_preserves_references():
    from daon2_user_api.authoring.diff import strip_repeated_chapter_heading

    title = "제3장 보험금의 지급"
    assert strip_repeated_chapter_heading("제3장 보험금의 지급 제11조 보험금 청구", title) == "제11조 보험금 청구"
    paragraph = "제3장 보험금의 지급 규정을 따릅니다."
    assert strip_repeated_chapter_heading(paragraph, title) == paragraph
    assert strip_repeated_chapter_heading("제4장 면책", title) == "제4장 면책"


def test_terms_review_detects_repeated_numbered_headings_without_model_findings():
    from daon2_user_api.authoring.terms_review import review_terms_body

    ctx = SimpleNamespace(context=None, cancel_check=lambda: None)
    model = SimpleNamespace(generate=lambda *args, **kwargs: SimpleNamespace(data={"issues": []}))
    unit = {"key": "payment-1", "section_title": "보험금의 지급", "title": "지급",
            "paragraphs": [{"text": "제11조(보험금 청구)\n서류를 확인한다."},
                           {"text": "제11조의2(지급 절차)\n절차를 안내한다."},
                           {"text": "제11조 (청구 서류 심사)\n서류를 심사한다."},
                           {"text": "제11조에 따른 서류를 제출한다."}]}
    findings = review_terms_body(ctx, model, changes="기준 약관의 심사 절차를 유지한다.",
                                 units=[unit], context_chars=10000)
    assert [(issue["unit_key"], issue["quote"]) for issue in findings] == [
        ("payment-1", "제11조 (청구 서류 심사)"),
    ]


def test_terms_body_conflict_pauses_until_edited_and_rechecked(writing):
    client, repo, model, worker = writing
    model.conflicting_terms = True
    output, paused = _generate_payment_terms(writing)
    assert (paused["state"], paused["pause_reason"], paused["document"]) == ("paused", "terms_review", None)
    issue, = paused["terms_review"]
    assert issue["quote"] == RETAINED
    receipt = client.post(output + "/control", json={"action": "resume", "expected_revision": paused["revision_no"]})
    assert receipt.status_code == 409, receipt.text
    assert "AUTHORING_TERMS_REVIEW_REQUIRED" in receipt.text
    assert not repo.jobs
    receipt = client.put(output + "/units/" + issue["unit_key"],
                         json={"expected_revision": paused["revision_no"], "paragraphs": [MODIFIED]})
    assert receipt.status_code == 202, receipt.text
    edited = client.get(output).json()["data"]
    receipt = client.post(output + "/control", json={"action": "resume", "expected_revision": edited["revision_no"]})
    assert receipt.status_code == 202, receipt.text
    worker._process(repo.jobs.pop())
    completed = client.get(output).json()["data"]
    assert completed["state"] == "completed"
    assert not completed["terms_review"]
    assert [prompt.schema_name for prompt in model.prompts].count("authoring_terms_body_review") == 3
    exported = export_v2("docx", {"output_id": repo.output_id, "title": completed["document"]["title"],
                                  "type_id": "authored_document", "revision": {"content": completed},
                                  "evidence": repo.evidence}).content
    with ZipFile(io.BytesIO(exported)) as archive:
        body = archive.read("word/document.xml").decode()
    assert MODIFIED in body
    # 기준 조항은 변경 추적에 표시될 수 있지만 편집 지시 문장은 내보내지 않는다.
    assert EDITORIAL not in body


def test_terms_body_repair_is_checked_before_completing(writing):
    _, _, model, _ = writing
    model.conflicting_terms = True
    model.repair_terms = True
    _, completed = _generate_payment_terms(writing)
    assert completed["state"] == "completed"
    assert not completed["terms_review"]
    assert [prompt.schema_name for prompt in model.prompts].count("authoring_terms_body_review") == 2
    assert all(RETAINED not in p["text"] and EDITORIAL not in p["text"]
               for unit in completed["units"] for p in unit["paragraphs"])


def test_terms_review_accepts_only_matching_words_when_the_model_flattens_whitespace():
    from daon2_user_api.authoring.terms_review import review_terms_body

    original = "제13조 청구 결과\n인편으로 전달한다."
    context = SimpleNamespace(context=None, cancel_check=lambda: None)
    model = SimpleNamespace(generate=lambda *args, **kwargs: SimpleNamespace(data={"issues": [
        {"unit_key": "payment-1", "quote": "제13조 청구 결과 인편으로 전달한다.", "reason": "삭제 요청과 충돌"},
    ]}))
    units = [{"key": "payment-1", "section_title": "보험금의 지급", "title": "청구 결과",
              "paragraphs": [{"text": original}]}]
    issues = review_terms_body(context, model, changes="인편 전달을 삭제한다.", units=units, context_chars=10000)
    assert issues == [{"unit_key": "payment-1", "quote": original, "reason": "삭제 요청과 충돌"}]


def test_terms_review_does_not_require_obsolete_delivery_method_in_the_current_clause():
    from daon2_user_api.authoring.terms_review import review_terms_body

    current = "제12조 지급 지연 안내\n지급이 늦어지면 이메일로 안내한다."
    outdated = "제13조 청구 결과\n청구 결과는 인편으로 배달한다."
    context = SimpleNamespace(context=None, cancel_check=lambda: None)
    model = SimpleNamespace(generate=lambda *args, **kwargs: SimpleNamespace(data={"issues": [
        {"unit_key": "payment-1", "quote": current, "reason": "변경 전 방식이 본문에 없어 전후 대조가 어렵습니다.",
         "kind": "before_value_missing", "previous_text": "우편", "replacement_text": "이메일"},
        {"unit_key": "payment-1", "quote": outdated, "reason": "삭제 요청한 인편 배달을 본문에 유지했습니다."},
    ]}))
    unit = {"key": "payment-1", "section_title": "제3장 보험금의 지급", "title": "지급",
            "paragraphs": [{"text": current}, {"text": outdated}]}
    findings = review_terms_body(context, model, changes="우편 대신 이메일로 안내하고 인편 배달은 삭제한다.",
                                 units=[unit], context_chars=10000)
    assert [issue["quote"] for issue in findings] == [outdated]


def test_terms_body_review_retries_saved_text_when_verifier_unavailable(writing):
    client, repo, model, worker = writing
    model.review_unavailable = True
    output, paused = _generate_payment_terms(writing)
    assert (paused["state"], paused["pause_reason"], paused["document"]) == ("paused", "terms_review_unavailable", None)
    model.review_unavailable = False
    count = [prompt.schema_name for prompt in model.prompts].count("authoring_unit")
    receipt = client.post(output + "/control", json={"action": "resume", "expected_revision": paused["revision_no"]})
    assert receipt.status_code == 202, receipt.text
    worker._process(repo.jobs.pop())
    assert client.get(output).json()["data"]["state"] == "completed"
    assert [prompt.schema_name for prompt in model.prompts].count("authoring_unit") == count


@pytest.mark.parametrize(("invalid_replies", "expected_state"), [(1, "completed"), (2, "paused")])
def test_terms_body_review_rechecks_unmatched_quote_once(writing, invalid_replies, expected_state):
    _, _, model, _ = writing
    model.unmatched_review_quotes = invalid_replies

    _, result = _generate_payment_terms(writing)

    assert result["state"] == expected_state
    assert result["units"][0]["locked"] is False
    assert [prompt.schema_name for prompt in model.prompts].count("authoring_unit") == 1
    assert [prompt.schema_name for prompt in model.prompts].count("authoring_terms_body_review") == 2
    if expected_state == "paused":
        assert (result["pause_reason"], result["document"]) == ("terms_review_unavailable", None)


def test_worker_rechecks_access_revoked_after_queue(writing):
    client, repo, model, worker = writing
    opened = client.post(PATH, json={"template_id": "reference_proposal_draft"}).json()["data"]
    output = PATH + "/" + opened["output_id"]
    response = client.post(output + "/answers", json={"expected_revision": 1, "skip_remaining": True, "answers": [
        {"key": "reference_proposals", "source_version_ids": ["proposal-v1"]}, {"key": "purpose", "value": "새 제안서"},
    ]})
    assert response.status_code == 202
    repo.allowed.clear()
    worker._process(repo.jobs.pop())
    snapshot = client.get(output).json()["data"]
    assert snapshot["job_status"] == "failed"
    assert snapshot["error_code"] == "NOTEBOOK_SCOPE_MISMATCH"
    assert model.prompts == []


def test_docx_reference_reads_real_original_and_reopens_its_locator(monkeypatch):
    from daon2_user_api.authorization import Action
    from daon2_user_api.studio_original_reader import StudioOriginalReader

    sample = docx_bytes("<w:p><w:r><w:t>앞부분 제안</w:t></w:r></w:p><w:p><w:r><w:t>후반부 운영 인수</w:t></w:r></w:p>")
    calls = []

    def read_original(self, context, version, *, action, connection):
        calls.append((version, action))
        return sample

    class Connection:
        def execute(self, sql, args):
            return SimpleNamespace(fetchone=lambda: ("source-id", "기존 제안서.docx", {"block_evidence": []}), fetchall=lambda: [])

    monkeypatch.setattr(StudioOriginalReader, "read_docx", read_original)
    store = SimpleNamespace(_transaction=lambda _: nullcontext(Connection()))
    reader = StudioSourceReader(store, object_storage=object())
    context = StudioContext("tenant", "workspace", "actor", "trace", "policy", "notebook")
    source, = reader.read(context, ["docx-v1"], require_body=True)
    assert [section.text for section in source.sections] == ["앞부분 제안", "후반부 운영 인수"]
    later = source.sections[-1]
    assert reader.read_section(context, "docx-v1", later.locator_kind, later.locator_value) == ("기존 제안서.docx", "후반부 운영 인수")
    assert calls == [("docx-v1", Action.GENERATE), ("docx-v1", Action.VIEW)]


def test_terms_diff_excludes_unseen_clauses_and_tracks_changed_numbers():
    parts = (SourceSection("terms-v1", None, "page", "1", None, "표준계약에서 연체 이율은 연 5.5퍼센트로 정한다."),
             SourceSection("terms-v1", None, "page", "2", None, "구두 배서는 별도 심사를 받는다."))
    references = build_pack([SourceText("terms", "terms-v1", "기준약관.pdf", parts, True)], stable_ref_offset=0)
    sections = [{"paragraphs": [{"text": "표준계약에서 연체 이율은 연 55퍼센트로 정한다."}]}]
    check = AuthoringPipeline._compare_terms({"units": [{"reference_refs": ["S1"]}]}, sections, references)
    assert check["summary"] == {"unchanged": 0, "modified": 1, "new": 0, "delete_suggested": 0}
    assert check["source_truncated"] and check["uncompared_passages"] == 1


def test_terms_deletion_scope_tracks_boundaries_in_unconsulted_passages():
    parts = (
        SourceSection("terms-v1", None, "page", "1", None, "제3장 보험금의 지급\n증서는 인편으로 배달한다."),
        SourceSection("terms-v1", None, "page", "2", None, "제4장 면책\n다른 절의 첫 조항이다."),
        SourceSection("terms-v1", None, "page", "3", None, "다른 절의 후속 조항이다."),
    )
    references = build_pack([SourceText("terms", "terms-v1", "기준약관.pdf", parts, False)], stable_ref_offset=0)
    selected = {"key": "payment", "title": "제3장 보험금의 지급"}
    current = {"plan": {"sections": [selected]}, "units": [{"section_key": "payment", "reference_refs": ["S1", "S3"]}]}
    sections = [{"paragraphs": [{"text": "온라인 진행 상황 확인 창구를 연다."}]}]
    AuthoringPipeline._compare_terms(current, sections, references)
    assert sections[0]["delete_suggested"] == ["증서는 인편으로 배달한다."]


def test_terms_deletion_scope_requires_a_matching_source_chapter():
    source = SourceSection("terms-v1", None, "page", "1", None, "증서는 인편으로 배달한다.")
    references = build_pack([SourceText("terms", "terms-v1", "기준약관.pdf", (source,), False)])
    selected = {"key": "payment", "title": "제3장 보험금의 지급"}
    current = {"plan": {"sections": [selected]}, "units": [{"section_key": "payment", "reference_refs": ["S1"]}]}
    sections = [{"paragraphs": [{"text": "온라인 진행 상황 확인 창구를 연다."}]}]
    check = AuthoringPipeline._compare_terms(current, sections, references)
    assert check["summary"]["delete_suggested"] == 0
    assert "delete_suggested" not in sections[0]
