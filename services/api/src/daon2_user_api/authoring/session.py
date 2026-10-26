"""작성 세션 상태 기계(순수 함수). 단계 전환은 코드가 결정한다(LLM은 판단하지 않는다). WO-A1 T-A1-03.

상태: collecting → analyzing → review → generating → completed (오류 failed, 취소 cancelled)
세션은 studio_v2_revisions의 불변 리비전(스키마 studio.authoring_session.v1)으로 쌓인다.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Mapping, Sequence

from .templates import AuthoringError, AuthoringTemplate

SESSION_SCHEMA = "studio.authoring_session.v1"
STATES = ("collecting", "analyzing", "review", "generating", "completed", "failed", "cancelled")
MAX_QUESTIONS = 3
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_TRANSITIONS = {"collecting": {"analyzing", "cancelled"}, "analyzing": {"review", "failed", "cancelled"}, "review": {"generating", "analyzing", "cancelled"},
                "generating": {"completed", "failed", "cancelled"}, "failed": {"analyzing", "generating"}, "completed": set(), "cancelled": set()}


def transition(session: Mapping[str, Any], new_state: str) -> dict[str, Any]:
    if new_state not in _TRANSITIONS.get(session["state"], set()):
        raise AuthoringError("AUTHORING_STATE_INVALID", 409)
    updated = copy.deepcopy(dict(session))
    updated["state"] = new_state
    return updated


def _question(item: Mapping[str, Any]) -> dict[str, Any]:
    return {"key": item["key"], "question": item["question"], "kind": item["kind"], "required": bool(item["required"]), "choices": list(item.get("choices", [])),
            "document_type": item.get("document_type")}


def pending(template: AuthoringTemplate, session: Mapping[str, Any]) -> list[dict[str, Any]]:
    """아직 확정되지 않은 입력 중 다음에 물을 최대 3개. 필수가 먼저, 선택 입력은 필수가 다 찬 뒤 한 번만 제안한다."""
    done = set(session["inputs"]) | {a["key"] for a in session["assumptions"]}
    required = [i for i in template.inputs if i["required"] and i["key"] not in done]
    if required:
        return [_question(i) for i in required[:MAX_QUESTIONS]]
    optional = [i for i in template.inputs if not i["required"] and i["key"] not in done]
    return [_question(i) for i in optional[:MAX_QUESTIONS]]


def requests_for(questions: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """source_ref/knowledge_ref는 질문 대신 자료 요청으로 표현한다."""
    mapping = {"source_ref": "select_source", "knowledge_ref": "select_knowledge"}
    return [{"request": mapping[q["kind"]], "key": q["key"]} for q in questions if q["kind"] in mapping]


def new_session(template: AuthoringTemplate, *, request_text: str | None = None) -> dict[str, Any]:
    session: dict[str, Any] = {"schema": SESSION_SCHEMA, "template_id": template.template_id, "template_version": template.version, "analysis": template.analysis, "style": template.style, "output_choices": list(template.output["formats"]), "state": "collecting",
                               "request_text": (request_text or "")[:500], "inputs": {}, "assumptions": [], "pending_questions": [], "requests": [],
                               "requirements": [], "plan": None, "output_formats": list(template.output["default"]), "error_code": None}
    session["pending_questions"] = pending(template, session)
    session["requests"] = requests_for(session["pending_questions"])
    return session


def validate_value(item: Mapping[str, Any], answer: Mapping[str, Any]) -> Any:
    kind = item["kind"]
    if kind in ("text", "structured"):
        value = answer.get("value")
        if not isinstance(value, str) or not value.strip() or len(value) > 4000:
            raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
        return value.strip()
    if kind == "choice":
        if answer.get("value") not in item.get("choices", []):
            raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
        return answer["value"]
    if kind == "source_ref":
        version = answer.get("source_version_id")
        if not isinstance(version, str) or not _ID.fullmatch(version):
            raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
        return {"source_version_id": version}
    if kind == "knowledge_ref":
        ref = answer.get("knowledge_ref")
        if not isinstance(ref, Mapping) or not all(isinstance(ref.get(k), str) and ref[k] for k in ("connector_id", "project_id", "work_package_id")):
            raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
        docs = ref.get("document_ids")
        if not isinstance(docs, list) or not 1 <= len(docs) <= 10 or any(not isinstance(d, str) or not _ID.fullmatch(d) for d in docs):
            raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
        return {"connector_id": ref["connector_id"], "project_id": ref["project_id"], "work_package_id": ref["work_package_id"], "document_ids": list(dict.fromkeys(docs))}
    raise AuthoringError("AUTHORING_INPUT_INVALID", 422)


def apply_answers(template: AuthoringTemplate, session: Mapping[str, Any], answers: Sequence[Mapping[str, Any]], *, skip_remaining: bool = False) -> dict[str, Any]:
    """답변을 반영한다. 확정된 키는 다시 묻지 않고, 건너뛴 선택 입력은 가정으로 기록한다. 필수가 모두 차면 analyzing으로 전환."""
    if session["state"] != "collecting":
        raise AuthoringError("AUTHORING_STATE_INVALID", 409)
    updated = copy.deepcopy(dict(session))
    valid_keys = {i["key"] for i in template.inputs}
    for answer in answers:
        key = answer.get("key")
        if key not in valid_keys:
            raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
        item = template.input(key)
        if answer.get("skip") is True:
            if item["required"]:
                raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
            updated["assumptions"].append({"key": key, "reason": "user_skipped", "default": "[작성 필요]"})
            continue
        updated["inputs"][key] = validate_value(item, answer)
        updated["assumptions"] = [a for a in updated["assumptions"] if a["key"] != key]
    if skip_remaining:
        for item in template.inputs:
            if not item["required"] and item["key"] not in updated["inputs"] and all(a["key"] != item["key"] for a in updated["assumptions"]):
                updated["assumptions"].append({"key": item["key"], "reason": "user_skipped", "default": "[작성 필요]"})
    questions = pending(template, updated)
    if any(q["required"] for q in questions):
        updated["pending_questions"], updated["requests"] = questions, requests_for(questions)
        return updated
    if questions and not updated.get("optional_offered"):
        # 필수가 다 찼으면 선택 입력을 한 번만 제안한다(건너뛰기 허용).
        updated["optional_offered"] = True
        updated["pending_questions"], updated["requests"] = questions, requests_for(questions)
        return updated
    for question in questions:  # 이미 제안했는데 답하지 않은 선택 입력은 건너뛴 것으로 본다.
        updated["assumptions"].append({"key": question["key"], "reason": "user_skipped", "default": "[작성 필요]"})
    updated["pending_questions"], updated["requests"] = [], []
    updated["state"] = "analyzing"
    return updated


def validate_review_edit(requirements: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """사용자가 수정한 요구사항 목록을 정규화·검증한다."""
    if not isinstance(requirements, (list, tuple)) or len(requirements) > 300:
        raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
    cleaned, seen = [], set()
    for index, req in enumerate(requirements, 1):
        text = req.get("text") if isinstance(req, Mapping) else None
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
        rid = str(req.get("id") or f"REQ-{index:03d}")
        if not _ID.fullmatch(rid) or rid in seen:
            raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
        seen.add(rid)
        cleaned.append({"id": rid, "text": text.strip(), "mandatory": bool(req.get("mandatory", True)), "category": str(req.get("category", ""))[:60],
                        "refs": [r for r in req.get("refs", []) if isinstance(r, str)][:8]})
    return cleaned
