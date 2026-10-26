"""지식 Connector 관리 라우트(관리자 전용, 플래그 DAON_KNOWLEDGE_CONNECTORS_ENABLED 뒤). WO-M0 T-M0-07."""

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
from .knowledge_connector_service import ConnectorContext, ConnectorError
from .mcp_client import McpError

KNOWLEDGE_CONNECTOR_PUBLIC_CODES = frozenset({
    "CONNECTOR_KIND_INVALID", "CONNECTOR_NAME_INVALID", "CONNECTOR_ENDPOINT_INVALID", "CONNECTOR_ENDPOINT_PRIVATE_DENIED", "CONNECTOR_TOOL_NOT_ALLOWED",
    "CONNECTOR_SCOPE_INVALID", "CONNECTOR_CREDENTIAL_INVALID", "CONNECTOR_NOT_FOUND", "CONNECTOR_VERSION_CONFLICT", "CONNECTOR_DISABLED",
    "CONNECTOR_SCOPE_DENIED", "CONNECTOR_CREDENTIAL_UNAVAILABLE", "VIRTUAL_CONNECTOR_FORBIDDEN_IN_PRODUCTION", "CONNECTOR_LIMITS_INVALID", "CONNECTOR_EGRESS_DENIED",
})
_ID = re.compile(r"^kc-[0-9a-f]{32}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterBody(_Strict):
    kind: str = Field(max_length=32)
    name: str = Field(min_length=1, max_length=120)
    endpoint_url: str = Field(min_length=8, max_length=2048)
    token: str | None = Field(default=None, min_length=8, max_length=8192)
    allowed_tools: list[str] | None = Field(default=None, max_length=32)
    allowed_scopes: list[dict[str, str]] | None = Field(default=None, max_length=64)
    virtual: bool = False


class ToolsBody(_Strict):
    allowed_tools: list[str] | None = Field(default=None, max_length=32)
    limits: dict[str, int] | None = None


def register_knowledge_connector_routes(app: FastAPI, dependencies: Any, service: Any) -> None:
    from .runtime import _principal, _require_query_keys, _studio_idempotency_key  # noqa: F401  (지연 import)

    def _admin(request: Request) -> ConnectorContext:
        principal = _principal(request, dependencies)
        if principal.user_id not in dependencies.settings.system_admin_user_ids:
            raise HTTPException(status_code=403)
        return ConnectorContext(principal.tenant_id, principal.user_id, request.state.trace_id)

    def _viewer(request: Request) -> ConnectorContext:
        principal = _principal(request, dependencies)
        return ConnectorContext(principal.tenant_id, principal.user_id, request.state.trace_id)

    def _meta(request: Request) -> dict[str, object]:
        return {"trace_id": request.state.trace_id}

    def _audit(ctx: ConnectorContext, action: str, target: str, outcome: AuditOutcome = AuditOutcome.SUCCEEDED, **meta: object) -> None:
        dependencies.audit_store.append(AuditEventDraft(
            event_id="kc-" + secrets.token_hex(16), occurred_at=datetime.now(timezone.utc), actor_id=ctx.actor_id, actor_type=ActorType.USER,
            tenant_id=ctx.tenant_id, workspace_id=None, action=action, target_type="knowledge_connector", target_id=target, outcome=outcome,
            trace_id=ctx.trace_id, policy_version=dependencies.settings.policy_version, metadata=dict(meta)))

    def _id(value: str) -> str:
        if _ID.fullmatch(value) is None:
            raise HTTPException(status_code=400)
        return value

    @app.get("/api/v1/knowledge-connectors")
    async def list_connectors(request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _viewer(request)
        items = await asyncio.to_thread(service.list, ctx)
        # 일반 사용자에게는 연결 상태와 이름만 보여 준다(주소·허용 범위는 관리자만).
        if ctx.actor_id not in dependencies.settings.system_admin_user_ids:
            items = [{k: i[k] for k in ("connector_id", "kind", "name", "status", "virtual", "allowed_scopes")} for i in items]
        return JSONResponse({"data": {"connectors": items}, "meta": _meta(request)})

    @app.get("/api/v1/knowledge-connectors/{connector_id}/documents")
    async def connector_documents(connector_id: str, request: Request) -> JSONResponse:
        """작성 화면의 '기존 제안서 선택' 목록. 서버가 허용한 컬렉션(project_id·work_package_id)만 조회한다."""
        _require_query_keys(request, frozenset({"project_id", "work_package_id", "document_type"}))
        ctx = _viewer(request)
        q = request.query_params
        if not q.get("project_id") or not q.get("work_package_id"):
            raise HTTPException(status_code=400)
        args = {"project_id": q["project_id"], "work_package_id": q["work_package_id"], **({"document_type": q["document_type"]} if q.get("document_type") else {})}
        result = await asyncio.to_thread(service.call, ctx, _id(connector_id), "list_documents", args)
        return JSONResponse({"data": {"documents": result.structured["documents"]}, "meta": _meta(request)})

    @app.post("/api/v1/admin/knowledge-connectors", status_code=201)
    async def register_connector(body: RegisterBody, request: Request, idempotency_key: str = Header(alias="Idempotency-Key")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        _studio_idempotency_key(idempotency_key)
        ctx = _admin(request)
        spec = body.model_dump(exclude_none=True)
        created = await asyncio.to_thread(service.register, ctx, spec)
        _audit(ctx, "knowledge_connector.register", created["connector_id"], kind=body.kind, virtual=body.virtual)
        return JSONResponse({"data": created, "meta": _meta(request)}, status_code=201)

    @app.post("/api/v1/admin/knowledge-connectors/{connector_id}/verify")
    async def verify_connector(connector_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _admin(request)
        result = await asyncio.to_thread(service.verify, ctx, _id(connector_id))
        _audit(ctx, "knowledge_connector.verify", connector_id, status=result["status"], reason_code=result["error_code"])
        return JSONResponse({"data": result, "meta": _meta(request)})

    @app.patch("/api/v1/admin/knowledge-connectors/{connector_id}")
    async def update_connector(connector_id: str, body: ToolsBody, request: Request, if_match: str = Header(alias="If-Match")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        ctx = _admin(request)
        match = re.fullmatch(r'"knowledge-connector:kc-[0-9a-f]{32}:(\d+)"', if_match)
        if match is None:
            raise HTTPException(status_code=400)
        if body.allowed_tools is None and body.limits is None:
            raise HTTPException(status_code=400)
        version = int(match.group(1))
        result = None
        if body.allowed_tools is not None:
            result = await asyncio.to_thread(service.set_allowed_tools, ctx, _id(connector_id), body.allowed_tools, version)
            version = result["version"]
        if body.limits is not None:
            result = await asyncio.to_thread(service.set_limits, ctx, _id(connector_id), body.limits, version)
        _audit(ctx, "knowledge_connector.update", connector_id, tools=len(body.allowed_tools or ()), limits=len(body.limits or ()))
        response = JSONResponse({"data": result, "meta": _meta(request)})
        response.headers["ETag"] = f'"knowledge-connector:{connector_id}:{result["version"]}"'
        return response

    @app.delete("/api/v1/admin/knowledge-connectors/{connector_id}", status_code=204)
    async def disconnect_connector(connector_id: str, request: Request) -> Response:
        _require_query_keys(request, frozenset())
        ctx = _admin(request)
        await asyncio.to_thread(service.disconnect, ctx, _id(connector_id))
        _audit(ctx, "knowledge_connector.disconnect", connector_id)
        return Response(status_code=204)

    @app.exception_handler(ConnectorError)
    async def connector_error(request: Request, error: ConnectorError) -> JSONResponse:
        from .runtime import _error_response
        code = error.code if error.code in KNOWLEDGE_CONNECTOR_PUBLIC_CODES else "INVALID_REQUEST"
        return _error_response(error.status, code, request.state.trace_id)

    @app.exception_handler(McpError)
    async def mcp_error(request: Request, error: McpError) -> JSONResponse:
        from .runtime import _error_response
        return _error_response(503 if error.retryable else 502, "KNOWLEDGE_SERVER_UNAVAILABLE", request.state.trace_id, retryable=error.retryable)
