"""TTS 엔진 관리 라우트(시스템 관리자 전용). WO-F7T. 응답에는 API 키가 없고 `has_credential`만 있다."""

from __future__ import annotations

import asyncio
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .audit import ActorType, AuditEventDraft, AuditOutcome
from .tts_engine_service import TtsAdminContext, TtsEngineError

TTS_ENGINE_PUBLIC_CODES = frozenset({
    "TTS_ENGINE_SLUG_INVALID", "TTS_ENGINE_SLUG_EXISTS", "TTS_ENGINE_LABEL_INVALID", "TTS_ENGINE_ENDPOINT_INVALID", "TTS_ENGINE_ENDPOINT_PRIVATE_DENIED",
    "TTS_ENGINE_KIND_INVALID", "TTS_ENGINE_LANGUAGE_INVALID", "TTS_ENGINE_TIMEOUT_INVALID", "TTS_ENGINE_VOICE_INVALID", "TTS_ENGINE_CREDENTIAL_INVALID",
    "TTS_ENGINE_CREDENTIAL_UNAVAILABLE", "TTS_ENGINE_NOT_FOUND", "TTS_ENGINE_VERSION_CONFLICT", "TTS_ENGINE_INPUT_INVALID", "TTS_ENGINE_DISABLED",
})
_ID = re.compile(r"^te-[0-9a-f]{32}$")
_ETAG = re.compile(r'^"tts-engine:te-[0-9a-f]{32}:(\d+)"$')


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoicesBody(_Strict):
    A: str = Field(min_length=1, max_length=40)
    B: str = Field(min_length=1, max_length=40)


class RegisterBody(_Strict):
    slug: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=60)
    base_url: str = Field(min_length=8, max_length=2048)
    api_key: str | None = Field(default=None, min_length=8, max_length=4096)
    provider_kind: str | None = Field(default=None, max_length=32)
    language: str | None = Field(default=None, max_length=16)
    timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    voices: VoicesBody
    voice_choices: list[str] | None = Field(default=None, max_length=64)


class PatchBody(_Strict):
    label: str | None = Field(default=None, min_length=1, max_length=60)
    base_url: str | None = Field(default=None, min_length=8, max_length=2048)
    api_key: str | None = Field(default=None, min_length=8, max_length=4096)
    provider_kind: str | None = Field(default=None, max_length=32)
    timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    voices: VoicesBody | None = None
    voice_choices: list[str] | None = Field(default=None, max_length=64)
    is_default: bool | None = None
    enabled: bool | None = None


def register_tts_engine_routes(app: FastAPI, dependencies: Any, service: Any) -> None:
    from .runtime import _principal, _require_query_keys, _studio_idempotency_key

    def _admin(request: Request) -> TtsAdminContext:
        principal = _principal(request, dependencies)
        if principal.user_id not in dependencies.settings.system_admin_user_ids:
            raise HTTPException(status_code=403)
        return TtsAdminContext(principal.tenant_id, principal.user_id, request.state.trace_id)

    def _meta(request: Request) -> dict[str, object]:
        return {"trace_id": request.state.trace_id}

    def _audit(ctx: TtsAdminContext, action: str, target: str, **meta: object) -> None:
        dependencies.audit_store.append(AuditEventDraft(
            event_id="te-" + secrets.token_hex(16), occurred_at=datetime.now(timezone.utc), actor_id=ctx.actor_id, actor_type=ActorType.USER,
            tenant_id=ctx.tenant_id, workspace_id=None, action=action, target_type="tts_engine", target_id=target, outcome=AuditOutcome.SUCCEEDED,
            trace_id=ctx.trace_id, policy_version=dependencies.settings.policy_version, metadata=dict(meta)))

    def _id(value: str) -> str:
        if _ID.fullmatch(value) is None:
            raise HTTPException(status_code=400)
        return value

    def _etag(view: dict[str, Any]) -> str:
        return f'"tts-engine:{view["engine_id"]}:{view["version"]}"'

    @app.get("/api/v1/admin/tts-engines")
    async def list_tts_engines(request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _admin(request)
        items = await asyncio.to_thread(service.list, ctx)
        return JSONResponse({"data": {"engines": items}, "meta": _meta(request)})

    @app.post("/api/v1/admin/tts-engines", status_code=201)
    async def register_tts_engine(body: RegisterBody, request: Request, idempotency_key: str = Header(alias="Idempotency-Key")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        _studio_idempotency_key(idempotency_key)
        ctx = _admin(request)
        spec = body.model_dump(exclude_none=True)
        created = await asyncio.to_thread(service.register, ctx, spec)
        _audit(ctx, "tts_engine.register", created["engine_id"], slug=created["slug"], provider_kind=created["provider_kind"])
        response = JSONResponse({"data": created, "meta": _meta(request)}, status_code=201)
        response.headers["ETag"] = _etag(created)
        return response

    @app.post("/api/v1/admin/tts-engines/{engine_id}/verify")
    async def verify_tts_engine(engine_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _admin(request)
        result = await asyncio.to_thread(service.verify, ctx, _id(engine_id))
        _audit(ctx, "tts_engine.verify", engine_id, status=result["status"], reason_code=result["error_code"])
        response = JSONResponse({"data": result, "meta": _meta(request)})
        response.headers["ETag"] = _etag(result)
        return response

    @app.patch("/api/v1/admin/tts-engines/{engine_id}")
    async def update_tts_engine(engine_id: str, body: PatchBody, request: Request, if_match: str = Header(alias="If-Match")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _admin(request)
        match = _ETAG.fullmatch(if_match)
        if match is None or f"tts-engine:{engine_id}:" not in if_match:
            raise HTTPException(status_code=400)
        patch = body.model_dump(exclude_none=True)
        if not patch:
            raise HTTPException(status_code=400)
        result = await asyncio.to_thread(service.update, ctx, _id(engine_id), patch, int(match.group(1)))
        _audit(ctx, "tts_engine.update", engine_id, fields=sorted(k for k in patch if k != "api_key"), key_replaced="api_key" in patch)
        response = JSONResponse({"data": result, "meta": _meta(request)})
        response.headers["ETag"] = _etag(result)
        return response

    @app.delete("/api/v1/admin/tts-engines/{engine_id}", status_code=204)
    async def disconnect_tts_engine(engine_id: str, request: Request) -> Response:
        _require_query_keys(request, frozenset())
        ctx = _admin(request)
        await asyncio.to_thread(service.disconnect, ctx, _id(engine_id))
        _audit(ctx, "tts_engine.disconnect", engine_id)
        return Response(status_code=204)

    @app.exception_handler(TtsEngineError)
    async def tts_engine_error(request: Request, error: TtsEngineError) -> JSONResponse:
        from .runtime import _error_response
        code = error.code if error.code in TTS_ENGINE_PUBLIC_CODES else "INVALID_REQUEST"
        return _error_response(error.status, code, request.state.trace_id)
