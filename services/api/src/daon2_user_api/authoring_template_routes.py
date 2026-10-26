"""조직 작성 템플릿 관리 라우트(관리자 전용, WO-A3 F6-14). 지식 Connector 관리와 같은 관리자 권한을 쓴다."""

from __future__ import annotations

import asyncio
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from .audit import ActorType, AuditEventDraft, AuditOutcome

_ID = re.compile(r"^org_[a-z0-9_]{1,60}$")


class _DefinitionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition: dict[str, Any]


def register_authoring_template_routes(app: FastAPI, dependencies: Any, store: Any) -> None:
    from .runtime import _principal, _require_query_keys

    def _admin(request: Request):  # type: ignore[no-untyped-def]
        principal = _principal(request, dependencies)
        if principal.user_id not in dependencies.settings.system_admin_user_ids:
            raise HTTPException(status_code=403)
        return principal

    def _audit(principal: Any, request: Request, action: str, target: str, **meta: object) -> None:
        dependencies.audit_store.append(AuditEventDraft(
            event_id="at-" + secrets.token_hex(16), occurred_at=datetime.now(timezone.utc), actor_id=principal.user_id, actor_type=ActorType.USER,
            tenant_id=principal.tenant_id, workspace_id=None, action=action, target_type="authoring_template", target_id=target, outcome=AuditOutcome.SUCCEEDED,
            trace_id=request.state.trace_id, policy_version=dependencies.settings.policy_version, metadata=dict(meta)))

    def _template_id(value: str) -> str:
        if _ID.fullmatch(value) is None:
            raise HTTPException(status_code=400)
        return value

    def _meta(request: Request) -> dict[str, object]:
        return {"trace_id": request.state.trace_id}

    @app.get("/api/v1/admin/authoring-templates")
    async def list_templates(request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        principal = _admin(request)
        items = await asyncio.to_thread(store.list_all, principal.tenant_id, principal.user_id)
        return JSONResponse({"data": {"templates": items}, "meta": _meta(request)})

    @app.post("/api/v1/admin/authoring-templates", status_code=201)
    async def register_template(body: _DefinitionBody, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        principal = _admin(request)
        created = await asyncio.to_thread(store.register, principal.tenant_id, principal.user_id, body.definition)
        _audit(principal, request, "authoring_template.register", created["template_id"], version=1)
        return JSONResponse({"data": created, "meta": _meta(request)}, status_code=201)

    @app.get("/api/v1/admin/authoring-templates/{template_id}")
    async def export_template(template_id: str, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset({"version"}))
        principal = _admin(request)
        raw_version = request.query_params.get("version")
        version = int(raw_version) if raw_version and raw_version.isdigit() else None
        definition = await asyncio.to_thread(store.export, principal.tenant_id, principal.user_id, _template_id(template_id), version)
        return JSONResponse({"data": {"definition": definition}, "meta": _meta(request)})

    @app.put("/api/v1/admin/authoring-templates/{template_id}")
    async def update_template(template_id: str, body: _DefinitionBody, request: Request, if_match: str = Header(alias="If-Match")) -> JSONResponse:
        _require_query_keys(request, frozenset())
        principal = _admin(request)
        match = re.fullmatch(r'"authoring-template:org_[a-z0-9_]{1,60}:(\d+)"', if_match)
        if match is None:
            raise HTTPException(status_code=400)
        result = await asyncio.to_thread(store.new_version, principal.tenant_id, principal.user_id, _template_id(template_id), body.definition, int(match.group(1)))
        _audit(principal, request, "authoring_template.update", template_id, version=result["version"])
        response = JSONResponse({"data": result, "meta": _meta(request)})
        response.headers["ETag"] = f'"authoring-template:{template_id}:{result["version"]}"'
        return response

    for action, status in (("disable", "disabled"), ("enable", "active")):
        def make(action: str, status: str):  # type: ignore[no-untyped-def]
            async def handler(template_id: str, request: Request) -> JSONResponse:
                _require_query_keys(request, frozenset())
                principal = _admin(request)
                result = await asyncio.to_thread(store.set_status, principal.tenant_id, principal.user_id, _template_id(template_id), status)
                _audit(principal, request, f"authoring_template.{action}", template_id, version=result["version"])
                return JSONResponse({"data": result, "meta": _meta(request)})
            return handler
        app.add_api_route(f"/api/v1/admin/authoring-templates/{{template_id}}/{action}", make(action, status), methods=["POST"])
