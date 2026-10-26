"""작성 세션 서비스(API 계층 로직)와 워커용 생성기 어댑터. WO-A1 T-A1-03/04."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..studio_v2_generation import GenerationContext, GenerationResult
from ..studio_workspace import StudioContext, StudioError
from . import session as S
from .pipeline import AuthoringPipeline
from .templates import AuthoringError, TemplateRegistry

TYPE_ID = "authored_document"


def _view(content: Mapping[str, Any], revision: int, status: str) -> dict[str, Any]:
    keys = ("template_id", "analysis", "style", "output_choices", "state", "request_text", "inputs", "assumptions", "pending_questions", "requests", "requirements", "plan", "output_formats",
            "error_code", "document", "analysis_warnings")
    data = {k: content.get(k) for k in keys}
    data["knowledge_count"] = len(content.get("knowledge") or [])
    data["revision_no"] = revision
    data["job_status"] = status
    return data


class AuthoringService:
    def __init__(self, studio, registry: TemplateRegistry) -> None:  # type: ignore[no-untyped-def]
        self._studio = studio
        self._registry = registry

    def templates(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return self._registry.list(tenant_id)

    def create(self, context: StudioContext, template_id: str | None, request_text: str | None, idempotency_key: str) -> dict[str, Any]:
        if template_id is None:
            candidates = self._registry.classify(request_text or "", context.tenant_id)
            if len(candidates) != 1:
                return {"template_candidates": candidates or [t["template_id"] for t in self._registry.list(context.tenant_id)], "created": False}
            template_id = candidates[0]
        template = self._registry.get(template_id, context.tenant_id)
        session = S.new_session(template, request_text=request_text)
        made = self._studio.create_authoring_session(context, template.title, session, idempotency_key)
        revision, status, content = self._studio.latest_content(context, made["output_id"])
        return {"created": True, "output_id": made["output_id"], **_view(content, revision, status)}

    def get(self, context: StudioContext, output_id: str) -> dict[str, Any]:
        revision, status, content = self._studio.latest_content(context, output_id)
        if content.get("schema") != S.SESSION_SCHEMA:
            raise StudioError("RESOURCE_UNAVAILABLE", 404)
        return {"output_id": output_id, **_view(content, revision, status)}

    def answers(self, context: StudioContext, output_id: str, expected_revision: int, answers: Sequence[Mapping[str, Any]], skip_remaining: bool) -> dict[str, Any]:
        _, _, current = self._studio.latest_content(context, output_id)
        template = self._registry.get(current["template_id"], context.tenant_id, current.get("template_version"))
        updated = S.apply_answers(template, current, answers, skip_remaining=skip_remaining)
        analyzing = updated["state"] == "analyzing"
        versions = [updated["inputs"][template.source_input]["source_version_id"]] if analyzing and template.source_input and template.source_input in updated["inputs"] else []
        result = self._studio.authoring_apply(context, output_id, expected_revision, lambda _content: updated, enqueue_step="analyze" if analyzing else None,
                                              source_version_ids=versions)
        return {"output_id": output_id, **result}

    def review(self, context: StudioContext, output_id: str, expected_revision: int, *, requirements: Sequence[Mapping[str, Any]] | None,
               plan_sections: Sequence[Mapping[str, Any]] | None, output_formats: Sequence[str] | None, confirm: bool) -> dict[str, Any]:
        _, _, current = self._studio.latest_content(context, output_id)
        if current["state"] != "review":
            raise AuthoringError("AUTHORING_STATE_INVALID", 409)
        template = self._registry.get(current["template_id"], context.tenant_id, current.get("template_version"))
        cleaned = S.validate_review_edit(requirements) if requirements is not None else current["requirements"]
        ids = {r["id"] for r in cleaned}
        plan = dict(current["plan"])
        if plan_sections is not None:
            by_key = {s["key"]: s for s in plan["sections"]}
            new_sections = []
            for item in plan_sections:
                base = by_key.get(item.get("key"))
                title = str(item.get("title") or (base or {}).get("title") or "").strip()
                key = str(item.get("key") or "")
                if not title or not key.replace("_", "").isalnum():
                    raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
                new_sections.append({"key": key, "title": title[:120], "purpose": str(item.get("purpose") or (base or {}).get("purpose") or "")[:300],
                                     "knowledge_refs": (base or {}).get("knowledge_refs", []),
                                     "requirement_ids": [r for r in item.get("requirement_ids", (base or {}).get("requirement_ids", [])) if r in ids]})
            if not new_sections or len({s["key"] for s in new_sections}) != len(new_sections):
                raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
            plan["sections"] = new_sections
        else:  # 삭제된 요구사항 ID는 계획에서도 뺀다.
            plan["sections"] = [{**s, "requirement_ids": [r for r in s["requirement_ids"] if r in ids]} for s in plan["sections"]]
        formats = list(output_formats) if output_formats is not None else current["output_formats"]
        if not formats or not set(formats) <= set(template.output["formats"]):
            raise AuthoringError("AUTHORING_INPUT_INVALID", 422)
        if confirm:
            assigned = {r for s in plan["sections"] for r in s["requirement_ids"]}
            if ids - assigned and plan["sections"]:
                plan["sections"][0]["requirement_ids"] = list(dict.fromkeys(plan["sections"][0]["requirement_ids"] + sorted(ids - assigned)))

        def mutate(content: dict[str, Any]) -> dict[str, Any]:
            content.update({"requirements": cleaned, "plan": plan, "output_formats": formats})
            return S.transition(content, "generating") if confirm else content

        versions = [current["inputs"][template.source_input]["source_version_id"]] if template.source_input else []
        result = self._studio.authoring_apply(context, output_id, expected_revision, mutate, enqueue_step="generate" if confirm else None,
                                              source_version_ids=versions if confirm else ())
        return {"output_id": output_id, **result}


class AuthoringGenerator:
    """워커가 쓰는 생성기. 작업의 step(analyze|generate)에 맞춰 세션을 다음 상태로 옮긴다."""

    type_id = TYPE_ID

    def __init__(self, pipeline: AuthoringPipeline) -> None:
        self._pipeline = pipeline

    def generate(self, ctx: GenerationContext) -> GenerationResult:
        _, _, session = self._pipeline._get_session(ctx.context, ctx.output_id)  # noqa: SLF001
        session = dict(session)
        step = ctx.settings.get("step")
        if step == "analyze" and session["state"] == "analyzing":
            updated = self._pipeline.analyze(ctx, session)
            ctx.progress(95, "분석 완료")
            return GenerationResult(content={**updated, "language": "ko", "warnings": []}, generated_with={"prompt_version": "authoring-analyze-v1"})
        if step == "generate" and session["state"] == "generating":
            return self._pipeline.generate(ctx, session)
        raise StudioError("STUDIO_VERSION_CONFLICT", 409)
