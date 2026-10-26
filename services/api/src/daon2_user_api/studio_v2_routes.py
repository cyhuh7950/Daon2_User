"""Studio v2 HTTP 라우트(플래그 DAON_STUDIO_V2_ENABLED 뒤). WO-F1 T1-09.

runtime.py의 보조 함수는 등록 시점에 지연 import한다(순환 import 방지).
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .audit import ActorType, AuditEventDraft, AuditOutcome
from .authorization import Action
from .studio_v2_types import available_types
from .studio_workspace import StudioContext, StudioError

STUDIO_V2_PUBLIC_CODES = frozenset({
    "AUTHORING_STATE_INVALID", "AUTHORING_INPUT_INVALID", "AUTHORING_TEMPLATE_UNKNOWN", "AUTHORING_KNOWLEDGE_UNAVAILABLE", "AUTHORING_PLAN_REQUIRED",
    "STUDIO_NO_READY_SOURCE", "STUDIO_TYPE_UNAVAILABLE", "STUDIO_VERSION_CONFLICT", "STUDIO_VALIDATION_FAILED",
    "STUDIO_GENERATION_FAILED", "STUDIO_CANCELLED", "STUDIO_EXTERNAL_PROVIDER_UNSUPPORTED", "STUDIO_REVISION_TOO_LARGE",
    "STUDIO_SOURCE_TOO_LARGE", "NOTEBOOK_SCOPE_REQUIRED", "NOTEBOOK_SCOPE_MISMATCH",
})
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_EXPORT_FORMATS = frozenset({"docx", "pdf", "md", "txt", "xlsx", "csv", "json", "svg", "png", "pptx", "mp3", "wav", "mp4", "vtt"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateBody(_Strict):
    type_id: str = Field(min_length=1, max_length=64)
    format_id: str | None = Field(default=None, max_length=64)
    settings: dict[str, Any] | None = None
    source_version_ids: list[str] | None = Field(default=None, max_length=64)


class RenameBody(_Strict):
    title: str = Field(min_length=1, max_length=160)


class RevisionBody(_Strict):
    content: dict[str, Any]
    change_reason: str | None = Field(default=None, max_length=200)


class RegenerateBody(_Strict):
    settings: dict[str, Any] | None = None


class LearningBody(_Strict):
    revision_no: int = Field(ge=1)
    kind: str
    payload: dict[str, Any]


class CustomizationBody(_Strict):
    instruction: str = Field(max_length=4000)


class MemoBody(_Strict):
    title: str | None = Field(default=None, max_length=160)
    markdown: str | None = Field(default=None, max_length=200_000)
    from_run_result_id: str | None = Field(default=None, max_length=256)


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """단일 `bytes=a-b` 범위만 지원한다. 잘못된 형식은 None(전체 응답), 범위 밖은 ValueError."""
    if not header:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if not match or (match.group(1) == "" and match.group(2) == ""):
        return None
    if match.group(1) == "":
        length = int(match.group(2))
        if length == 0:
            raise ValueError
        return max(0, size - length), size - 1
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else size - 1
    if start >= size or end < start:
        raise ValueError
    return start, min(end, size - 1)


def register_studio_v2_routes(app: FastAPI, dependencies: Any, service: Any, license_check: Any = None, authoring: Any = None, tts_resolver: Any = None) -> None:
    from .tts_engines import configured_from_env
    file_tts = configured_from_env()
    """`service`는 PostgresStudioV2Repository + export(context, output_id, format, revision)를 가진 객체."""
    from .runtime import _error_response, _principal, _require_query_keys, _studio_idempotency_key  # noqa: F401

    base = "/api/v1/workspaces/{id}/notebooks/{notebook_id}/studio"

    def _ctx(request: Request, id: str, notebook_id: str, action: Action) -> StudioContext:
        for value in (id, notebook_id):
            if _ID.fullmatch(value) is None:
                raise HTTPException(status_code=400)
        principal = _principal(request, dependencies)
        dependencies.authorization_service.authorize_action(
            principal=principal, workspace_id=id, action=action, trace_id=request.state.trace_id,
            policy_version=dependencies.settings.policy_version)
        return StudioContext(principal.tenant_id, id, principal.user_id, request.state.trace_id,
                             dependencies.settings.policy_version, notebook_id)

    def _meta(request: Request, id: str) -> dict[str, object]:
        return {"trace_id": request.state.trace_id, "workspace_id": id}

    def _output_id(value: str) -> str:
        if _ID.fullmatch(value) is None:
            raise HTTPException(status_code=400)
        return value

    def _revision(request: Request) -> int | None:
        raw = request.query_params.get("revision")
        if raw is None:
            return None
        if not raw.isdigit() or not 1 <= int(raw) <= 100_000:
            raise HTTPException(status_code=400)
        return int(raw)

    def _audit(ctx: StudioContext, action: str, target: str, outcome: AuditOutcome = AuditOutcome.SUCCEEDED,
               metadata: Mapping[str, object] | None = None) -> None:
        # 본문·제목·지시문은 기록하지 않는다.
        dependencies.audit_store.append(AuditEventDraft(
            event_id="sv2-" + secrets.token_hex(16), occurred_at=datetime.now(timezone.utc), actor_id=ctx.actor_id,
            actor_type=ActorType.USER, tenant_id=ctx.tenant_id, workspace_id=ctx.workspace_id, action=action,
            target_type="studio_v2_output", target_id=target, outcome=outcome, trace_id=ctx.trace_id,
            policy_version=ctx.policy_version, metadata=dict(metadata or {"notebook_id": ctx.notebook_id})))

    async def run(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return await asyncio.to_thread(fn, *args, **kwargs)

    @app.get(base + "/types")
    async def studio_v2_types(id: str, notebook_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        tts = await run(tts_resolver.for_tenant, ctx.tenant_id) if tts_resolver is not None else file_tts
        # 사용자별 동시 생성 한도(워커와 같은 환경 변수). 화면이 "대기 중"과 "생성 중"을 구분하는 데 쓴다.
        limits = {"user_concurrency": max(1, int(os.environ.get("DAON_STUDIO_V2_USER_CONCURRENCY", "2")))}
        return JSONResponse({"data": {"types": available_types(authoring_enabled=authoring is not None, tts_enabled=tts is not None,
                                                                                 tts_settings=tts.settings_overlay() if tts else None), "limits": limits}, "meta": _meta(request, id)})

    @app.post(base + "/outputs", status_code=202)
    async def studio_v2_create(id: str, notebook_id: str, body: CreateBody, request: Request,
                               idempotency_key: str = Header(alias="Idempotency-Key")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        _studio_idempotency_key(idempotency_key)
        ctx = _ctx(request, id, notebook_id, Action.EDIT)
        if license_check is not None:
            await run(license_check, _principal(request, dependencies), id, request)
        result = await run(service.enqueue, ctx, body.model_dump(exclude_none=True), idempotency_key)
        if not result["replayed"]:
            _audit(ctx, "studio_v2.output.create", str(result["output_id"]),
                   metadata={"notebook_id": notebook_id, "type_id": body.type_id})
        return JSONResponse({"data": {k: result[k] for k in ("output_id", "job_id", "status")},
                             "meta": {**_meta(request, id), "replayed": result["replayed"]}},
                            status_code=200 if result["replayed"] else 202)

    @app.get(base + "/outputs")
    async def studio_v2_list(id: str, notebook_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset({"cursor", "limit"}))
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        limit_raw = request.query_params.get("limit", "25")
        if not limit_raw.isdigit():
            raise HTTPException(status_code=400)
        page = await run(service.list_outputs, ctx, cursor=request.query_params.get("cursor"), limit=int(limit_raw))
        if hasattr(service, "apply_knowledge_stale"):
            service.apply_knowledge_stale(ctx, page["items"])
        response = JSONResponse({"data": page, "meta": _meta(request, id)})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get(base + "/outputs/{output_id}")
    async def studio_v2_get(id: str, notebook_id: str, output_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset({"revision"}))
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        data = await run(service.get_output, ctx, _output_id(output_id), _revision(request))
        if not data.get("stale") and hasattr(service, "knowledge_changed"):
            data["stale"] = await run(service.knowledge_changed, ctx, _output_id(output_id), _revision(request))
        response = JSONResponse({"data": data, "meta": _meta(request, id)})
        response.headers["ETag"] = f'"studio-v2:{data["output_id"]}:{data["updated_at"]}"'
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.patch(base + "/outputs/{output_id}")
    async def studio_v2_rename(id: str, notebook_id: str, output_id: str, body: RenameBody, request: Request,
                               if_match: str | None = Header(default=None, alias="If-Match")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.EDIT)
        expected = None
        if if_match:
            match = re.fullmatch(r'"studio-v2:[^:]+:(.+)"', if_match)
            if match is None:
                raise HTTPException(status_code=400)
            expected = match.group(1)
        data = await run(service.rename, ctx, _output_id(output_id), body.title, expected)
        _audit(ctx, "studio_v2.output.rename", data["output_id"])
        response = JSONResponse({"data": data, "meta": _meta(request, id)})
        response.headers["ETag"] = f'"studio-v2:{data["output_id"]}:{data["updated_at"]}"'
        return response

    @app.delete(base + "/outputs/{output_id}", status_code=204)
    async def studio_v2_delete(id: str, notebook_id: str, output_id: str, request: Request) -> Response:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.EDIT)
        await run(service.soft_delete, ctx, _output_id(output_id))
        _audit(ctx, "studio_v2.output.delete", output_id)
        return Response(status_code=204)

    @app.post(base + "/outputs/{output_id}/revisions", status_code=201)
    async def studio_v2_revision(id: str, notebook_id: str, output_id: str, body: RevisionBody, request: Request,
                                 idempotency_key: str = Header(alias="Idempotency-Key")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        _studio_idempotency_key(idempotency_key)
        ctx = _ctx(request, id, notebook_id, Action.EDIT)
        number = await run(service.save_user_edit, ctx, _output_id(output_id), body.content, body.change_reason)
        return JSONResponse({"data": {"output_id": output_id, "revision_no": number}, "meta": _meta(request, id)}, status_code=201)

    @app.post(base + "/outputs/{output_id}/regenerate", status_code=202)
    async def studio_v2_regenerate(id: str, notebook_id: str, output_id: str, body: RegenerateBody, request: Request,
                                   idempotency_key: str = Header(alias="Idempotency-Key")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        _studio_idempotency_key(idempotency_key)
        ctx = _ctx(request, id, notebook_id, Action.EDIT)
        result = await run(service.regenerate, ctx, _output_id(output_id), body.settings, idempotency_key)
        return JSONResponse({"data": {k: result[k] for k in ("output_id", "job_id", "status")},
                             "meta": {**_meta(request, id), "replayed": result["replayed"]}}, status_code=202)

    @app.post(base + "/outputs/{output_id}/cancel", status_code=202)
    async def studio_v2_cancel(id: str, notebook_id: str, output_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.EDIT)
        result = await run(service.request_cancel, ctx, _output_id(output_id))
        return JSONResponse({"data": result, "meta": _meta(request, id)}, status_code=202)

    @app.get(base + "/outputs/{output_id}/provenance")
    async def studio_v2_provenance(id: str, notebook_id: str, output_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset({"revision"}))
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        data = await run(service.provenance, ctx, _output_id(output_id), _revision(request))
        return JSONResponse({"data": data, "meta": _meta(request, id)})

    @app.get(base + "/outputs/{output_id}/exports/{format_name}")
    async def studio_v2_export(id: str, notebook_id: str, output_id: str, format_name: str, request: Request) -> Response:
        _require_query_keys(request, frozenset({"revision"}))
        if format_name not in _EXPORT_FORMATS:
            raise HTTPException(status_code=400)
        ctx = _ctx(request, id, notebook_id, Action.VIEW)  # 기본은 승인·step-up 없음(D2). 조직이 내보내기 추가 인증을 켠 경우에만 요구한다(ST-T27).
        from .export_policy_routes import EXPORT_STEP_UP_GROUP
        if dependencies.identity_service.requires_step_up(ctx.tenant_id, EXPORT_STEP_UP_GROUP):
            from .runtime import _credential
            access_token, _client = _credential(request)
            dependencies.identity_service.consume_step_up(
                step_up_authorization=request.headers.get("x-daon-step-up-authorization"), access_token=access_token,
                action_group=EXPORT_STEP_UP_GROUP, target_id=output_id, policy_version=dependencies.settings.policy_version, trace_id=request.state.trace_id)
        exported = await run(service.export, ctx, _output_id(output_id), format_name, _revision(request))
        _audit(ctx, "studio_v2.output.export", output_id, metadata={"notebook_id": notebook_id, "format": format_name})
        return Response(exported.content, media_type=exported.media_type, headers={
            "Content-Disposition": f'attachment; filename="{exported.ascii_filename}"; filename*=UTF-8\'\'{exported.quoted_filename}',
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store", "ETag": f'"sha256:{exported.sha256}"'})

    async def _serve_media(id: str, notebook_id: str, output_id: str, request: Request, getter: Any, media_type: str) -> Response:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        asset = await run(getter, ctx, _output_id(output_id))
        body: bytes = asset["content"]  # type: ignore[assignment]
        headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                   "ETag": f'"sha256:{asset["sha256"]}"', "X-Media-Duration-Ms": str(asset.get("duration_ms") or 0)}
        try:
            span = _parse_range(request.headers.get("range"), len(body))
        except ValueError:
            return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{len(body)}"})
        if span is None:
            return Response(body, media_type=media_type, headers=headers)
        start, end = span
        return Response(body[start:end + 1], status_code=206, media_type=media_type,
                        headers={**headers, "Content-Range": f"bytes {start}-{end}/{len(body)}"})

    @app.get(base + "/outputs/{output_id}/audio")
    async def studio_v2_audio(id: str, notebook_id: str, output_id: str, request: Request) -> Response:
        return await _serve_media(id, notebook_id, output_id, request, service.get_audio, "audio/mpeg")

    @app.get(base + "/outputs/{output_id}/video")
    async def studio_v2_video(id: str, notebook_id: str, output_id: str, request: Request) -> Response:
        return await _serve_media(id, notebook_id, output_id, request, service.get_video, "video/mp4")

    @app.get(base + "/outputs/{output_id}/sharing")
    async def studio_v2_sharing(id: str, notebook_id: str, output_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        await run(service.get_output, ctx, _output_id(output_id), None)
        # 접근 대상은 노트북 권한을 따른다(별도 공개 링크 없음).
        return JSONResponse({"data": {"scope": "notebook", "public_link": False, "notebook_id": notebook_id},
                             "meta": _meta(request, id)})

    @app.post(base + "/outputs/{output_id}/learning-attempts", status_code=201)
    async def studio_v2_attempt_create(id: str, notebook_id: str, output_id: str, body: LearningBody, request: Request,
                                       idempotency_key: str = Header(alias="Idempotency-Key")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        _studio_idempotency_key(idempotency_key)
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        data = await run(service.record_learning_attempt, ctx, _output_id(output_id), body.revision_no, body.kind,
                         body.payload, idempotency_key)
        return JSONResponse({"data": data, "meta": _meta(request, id)}, status_code=201)

    @app.get(base + "/outputs/{output_id}/learning-attempts")
    async def studio_v2_attempt_list(id: str, notebook_id: str, output_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        items = await run(service.list_learning_attempts, ctx, _output_id(output_id))
        return JSONResponse({"data": {"items": items}, "meta": _meta(request, id)})

    @app.get(base + "/customization")
    async def studio_v2_customization_get(id: str, notebook_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        data = await run(service.get_customization, ctx)
        response = JSONResponse({"data": data, "meta": _meta(request, id)})
        response.headers["ETag"] = f'"studio-v2-customization:{notebook_id}:{data["version"]}"'
        return response

    @app.put(base + "/customization")
    async def studio_v2_customization_put(id: str, notebook_id: str, body: CustomizationBody, request: Request,
                                          if_match: str | None = Header(default=None, alias="If-Match")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.EDIT)
        expected = 0
        if if_match:
            match = re.fullmatch(r'"studio-v2-customization:[^:]+:(\d+)"', if_match)
            if match is None:
                raise HTTPException(status_code=400)
            expected = int(match.group(1))
        data = await run(service.save_customization, ctx, body.instruction, expected)
        response = JSONResponse({"data": data, "meta": _meta(request, id)})
        response.headers["ETag"] = f'"studio-v2-customization:{notebook_id}:{data["version"]}"'
        return response

    @app.post(base + "/memos", status_code=201)
    async def studio_v2_memo(id: str, notebook_id: str, body: MemoBody, request: Request,
                             idempotency_key: str = Header(alias="Idempotency-Key")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        _studio_idempotency_key(idempotency_key)
        ctx = _ctx(request, id, notebook_id, Action.EDIT)
        if body.from_run_result_id is not None:
            data = await run(service.create_memo_from_run_result, ctx, body.from_run_result_id, body.title, idempotency_key)
        else:
            data = await run(service.create_memo, ctx, body.title, body.markdown or "", idempotency_key)
        return JSONResponse({"data": data, "meta": _meta(request, id)}, status_code=201)

    @app.get(base + "/outputs/{output_id}/evidence/{ref_id}/content")
    async def studio_v2_evidence_content(id: str, notebook_id: str, output_id: str, ref_id: str, request: Request) -> Response:
        _require_query_keys(request, frozenset({"revision"}))
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        if _ID.fullmatch(ref_id) is None:
            raise HTTPException(status_code=400)
        content = await run(service.evidence_content, ctx, _output_id(output_id), ref_id, _revision(request))
        return Response(content.body, media_type=content.media_type, headers={**content.headers, "Cache-Control": "no-store",
                                                                           "X-Content-Type-Options": "nosniff"})


class SessionCreateBody(_Strict):
    template_id: str | None = Field(default=None, max_length=64)
    request_text: str | None = Field(default=None, max_length=500)


class AnswersBody(_Strict):
    expected_revision: int = Field(ge=1)
    answers: list[dict[str, Any]] = Field(max_length=10)
    skip_remaining: bool = False


class ReviewBody(_Strict):
    expected_revision: int = Field(ge=1)
    requirements: list[dict[str, Any]] | None = Field(default=None, max_length=300)
    plan_sections: list[dict[str, Any]] | None = Field(default=None, max_length=30)
    output_formats: list[str] | None = Field(default=None, max_length=4)
    confirm: bool = False


_TEMPLATE_ADMIN_CODES = frozenset({"AUTHORING_TEMPLATE_INVALID", "AUTHORING_TEMPLATE_EXISTS", "AUTHORING_TEMPLATE_VERSION_CONFLICT", "AUTHORING_TEMPLATE_UNAVAILABLE"})


def register_authoring_routes(app: FastAPI, dependencies: Any, authoring: Any, enqueue_license_check: Any = None) -> None:
    """작성(Authoring) 라우트. 세션 상태는 산출물 리비전으로 저장된다(WO-A1)."""
    from .authoring.templates import AuthoringError
    from .runtime import _error_response, _principal, _require_query_keys, _studio_idempotency_key

    base = "/api/v1/workspaces/{id}/notebooks/{notebook_id}/studio/authoring"

    def _ctx(request: Request, id: str, notebook_id: str, action: Action) -> StudioContext:
        for value in (id, notebook_id):
            if _ID.fullmatch(value) is None:
                raise HTTPException(status_code=400)
        principal = _principal(request, dependencies)
        dependencies.authorization_service.authorize_action(principal=principal, workspace_id=id, action=action, trace_id=request.state.trace_id,
                                                            policy_version=dependencies.settings.policy_version)
        return StudioContext(principal.tenant_id, id, principal.user_id, request.state.trace_id, dependencies.settings.policy_version, notebook_id)

    def _out(value: str) -> str:
        if _ID.fullmatch(value) is None:
            raise HTTPException(status_code=400)
        return value

    meta = lambda request, id: {"trace_id": request.state.trace_id, "workspace_id": id}  # noqa: E731

    @app.exception_handler(AuthoringError)
    async def authoring_error(request: Request, error: AuthoringError) -> JSONResponse:
        code, _, reason = error.code.partition(":")
        public = code if code in STUDIO_V2_PUBLIC_CODES or code in _TEMPLATE_ADMIN_CODES else "INVALID_REQUEST"
        # 관리자 템플릿 검증 오류만 위치 사유(예: sections[2].key)를 함께 돌려준다.
        details = {"reason": reason} if reason and request.url.path.startswith("/api/v1/admin/") and re.fullmatch(r"[A-Za-z0-9_.\[\]]{1,80}", reason) else None
        return _error_response(error.status, public, request.state.trace_id, details=details)

    @app.get(base + "/templates")
    async def authoring_templates(id: str, notebook_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        return JSONResponse({"data": {"templates": authoring.templates(ctx.tenant_id)}, "meta": meta(request, id)})

    @app.post(base + "/sessions", status_code=201)
    async def authoring_create(id: str, notebook_id: str, body: SessionCreateBody, request: Request,
                               idempotency_key: str = Header(alias="Idempotency-Key")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        _studio_idempotency_key(idempotency_key)
        ctx = _ctx(request, id, notebook_id, Action.EDIT)
        if body.template_id is None and not body.request_text:
            raise HTTPException(status_code=400)
        if enqueue_license_check is not None:
            await asyncio.to_thread(enqueue_license_check, _principal(request, dependencies), id, request)
        data = await asyncio.to_thread(authoring.create, ctx, body.template_id, body.request_text, idempotency_key)
        return JSONResponse({"data": data, "meta": meta(request, id)}, status_code=201 if data.get("created") else 200)

    @app.get(base + "/sessions/{output_id}")
    async def authoring_get(id: str, notebook_id: str, output_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.VIEW)
        data = await asyncio.to_thread(authoring.get, ctx, _out(output_id))
        response = JSONResponse({"data": data, "meta": meta(request, id)})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post(base + "/sessions/{output_id}/answers", status_code=202)
    async def authoring_answers(id: str, notebook_id: str, output_id: str, body: AnswersBody, request: Request,
                                idempotency_key: str = Header(alias="Idempotency-Key")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        _studio_idempotency_key(idempotency_key)
        ctx = _ctx(request, id, notebook_id, Action.EDIT)
        data = await asyncio.to_thread(authoring.answers, ctx, _out(output_id), body.expected_revision, body.answers, body.skip_remaining)
        return JSONResponse({"data": data, "meta": meta(request, id)}, status_code=202)

    @app.put(base + "/sessions/{output_id}/review", status_code=202)
    async def authoring_review(id: str, notebook_id: str, output_id: str, body: ReviewBody, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _ctx(request, id, notebook_id, Action.EDIT)
        data = await asyncio.to_thread(authoring.review, ctx, _out(output_id), body.expected_revision, requirements=body.requirements,
                                       plan_sections=body.plan_sections, output_formats=body.output_formats, confirm=body.confirm)
        return JSONResponse({"data": data, "meta": meta(request, id)}, status_code=202)
