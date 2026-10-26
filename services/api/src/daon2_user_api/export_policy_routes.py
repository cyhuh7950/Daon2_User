"""내보내기 추가 인증 정책(WO-F1B, F1-08 / ST-T27). 조직 관리자가 켜면 Studio 산출물 내려받기에 비밀번호 재확인(step-up)이 필요하다.

기존 조직 step-up 행동 목록(`tenant_step_up_actions`)을 그대로 쓴다. 이 목록은 조직 보안 정책이라 한 번 더한 항목은 되돌릴 수 없다(제거는 `STEP_UP_ACTION_REMOVE_DENIED`).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

EXPORT_STEP_UP_GROUP = "studio_export_download"


class ExportPolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    require_step_up: bool


def register_export_policy_routes(app: FastAPI, dependencies: Any) -> None:
    from .runtime import _principal, _require_query_keys

    def _admin(request: Request):  # type: ignore[no-untyped-def]
        principal = _principal(request, dependencies)
        if principal.user_id not in dependencies.settings.system_admin_user_ids:
            raise HTTPException(status_code=403)
        return principal

    @app.get("/api/v1/admin/export-policy")
    async def get_export_policy(request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        principal = _admin(request)
        enabled = await asyncio.to_thread(dependencies.identity_service.requires_step_up, principal.tenant_id, EXPORT_STEP_UP_GROUP)
        return JSONResponse({"data": {"require_step_up": bool(enabled), "can_disable": False}, "meta": {"trace_id": request.state.trace_id}})

    @app.put("/api/v1/admin/export-policy")
    async def put_export_policy(body: ExportPolicyBody, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        principal = _admin(request)
        service = dependencies.identity_service
        repository = dependencies.identity_repository
        if body.require_step_up:
            await asyncio.to_thread(repository.add_step_up_action, principal.tenant_id, EXPORT_STEP_UP_GROUP)
        elif await asyncio.to_thread(service.requires_step_up, principal.tenant_id, EXPORT_STEP_UP_GROUP):
            await asyncio.to_thread(repository.remove_step_up_action, principal.tenant_id, EXPORT_STEP_UP_GROUP)  # 정책상 항상 거부된다
        enabled = await asyncio.to_thread(service.requires_step_up, principal.tenant_id, EXPORT_STEP_UP_GROUP)
        from .audit import ActorType, AuditEventDraft, AuditOutcome
        import secrets
        from datetime import datetime, timezone
        dependencies.audit_store.append(AuditEventDraft(
            event_id="ep-" + secrets.token_hex(16), occurred_at=datetime.now(timezone.utc), actor_id=principal.user_id, actor_type=ActorType.USER,
            tenant_id=principal.tenant_id, workspace_id=None, action="export_policy.update", target_type="export_policy", target_id=principal.tenant_id,
            outcome=AuditOutcome.SUCCEEDED, trace_id=request.state.trace_id, policy_version=dependencies.settings.policy_version,
            metadata={"require_step_up": bool(enabled)}))
        return JSONResponse({"data": {"require_step_up": bool(enabled), "can_disable": False}, "meta": {"trace_id": request.state.trace_id}})
