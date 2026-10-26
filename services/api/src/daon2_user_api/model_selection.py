"""노트북·사용자별 모델/추론 수준 선택. 승인된 Provider의 정확한 모델만 고를 수 있고, 추론 수준은 관리자가 확인한 것만 열린다.

선택한 모델이 더 이상 쓸 수 없으면 기본 모델로 바꾸지 않고 오류로 끝낸다(자동 전환 금지).
"""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .audit import ActorType, AuditEventDraft, AuditOutcome
from .cloud_storage import CloudAccessContext, CloudDatabaseError, PostgresCloudStore
from .workspace_model_defaults import (
    _ACTIVE_PROVIDERS, PostgresWorkspaceModelDefaultsService, WorkspaceModelDefaultsContext,
)

REASONING_LEVELS = ("none", "low", "medium", "high")
# 추론 수준을 요청에 실어 보낼 수 있는 Provider(요청 필드가 확인된 것). 그 밖의 Provider는 수준을 확인(confirm)할 수 없다.
REASONING_PROVIDERS = frozenset({"GROQ", "MISTRAL", "UPSTAGE", "OPENROUTER", "OMNIROUTE", "EOUL_GATEWAY", "CUSTOM"})
MODEL_SELECTION_PUBLIC_CODES = frozenset({
    "NOTEBOOK_NOT_FOUND", "MODEL_SELECTION_INVALID", "SELECTED_MODEL_UNAVAILABLE", "REASONING_LEVEL_UNSUPPORTED",
    "REASONING_PROVIDER_UNSUPPORTED", "MODEL_SELECTION_UNAVAILABLE", "MODEL_PROBE_FAILED",
})
# 라우터(게이트웨이)는 내부에서 선택한 수준을 실제 모델에 맞춰 매핑하므로 수준이 low·medium·high 3종으로 고정이다.
ROUTER_REASONING_LEVELS = ("low", "medium", "high")
ROUTER_PROVIDERS = frozenset({"OMNIROUTE", "EOUL_GATEWAY", "OPENROUTER"})


def is_reasoning_router(provider_code: str, base_url: str) -> bool:
    if provider_code in ROUTER_PROVIDERS:
        return True
    return provider_code == "CUSTOM" and "media-bridge-gateway" in (base_url or "").casefold()


_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class ModelSelectionError(RuntimeError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True, slots=True)
class ModelSelectionContext:
    tenant_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    policy_version: str


class ModelSelectionService:
    def __init__(self, store: PostgresCloudStore) -> None:
        self._store = store
        self._auto_prober = None

    def set_auto_prober(self, prober) -> None:
        """prober(tenant, workspace, actor, connection_id, model_id): 아직 확인하지 않은 모델을 고르는 순간 추론 수준을 실제 요청으로 확인한다."""
        self._auto_prober = prober

    @staticmethod
    def _scope(context: ModelSelectionContext, op: str) -> CloudAccessContext:
        return CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, op)

    def _defaults_context(self, context: ModelSelectionContext) -> WorkspaceModelDefaultsContext:
        return WorkspaceModelDefaultsContext(
            context.tenant_id, context.workspace_id, context.actor_id, context.trace_id, context.policy_version)

    def _available(self, connection: Any, context: ModelSelectionContext) -> tuple[list[dict[str, object]], dict[str, object] | None]:
        snapshot = PostgresWorkspaceModelDefaultsService._snapshot(connection, self._defaults_context(context))
        providers = _ACTIVE_PROVIDERS["text_generation"]
        levels = {
            (str(row[0]), str(row[1])): [str(item) for item in (row[2] or ())]
            for row in connection.execute("SELECT connection_id,model_id,confirmed_reasoning_levels FROM system_provider_models").fetchall()
        }
        base_urls = {str(row[0]): str(row[1] or "") for row in connection.execute(
            "SELECT connection_id,base_url FROM system_provider_connections").fetchall()}
        checked = {
            (str(row[0]), str(row[1]))
            for row in connection.execute("SELECT connection_id,model_id FROM system_provider_models WHERE reasoning_probed_at IS NOT NULL").fetchall()
        }
        available = [
            {"connection_id": item["connection_id"], "provider_code": item["provider_code"], "display_name": item["display_name"],
             "model_id": item["model_id"],
             "router": is_reasoning_router(item["provider_code"], base_urls.get(item["connection_id"], "")),
             "reasoning_checked": is_reasoning_router(item["provider_code"], base_urls.get(item["connection_id"], ""))
             or (item["connection_id"], item["model_id"]) in checked or item["provider_code"] not in REASONING_PROVIDERS,
             "reasoning_levels": list(ROUTER_REASONING_LEVELS) if is_reasoning_router(item["provider_code"], base_urls.get(item["connection_id"], ""))
             else levels.get((item["connection_id"], item["model_id"]), []) if item["provider_code"] in REASONING_PROVIDERS else []}
            for item in snapshot["available_models"]  # type: ignore[union-attr]
            if "text_generation" in item["effective_capabilities"] and item["provider_code"] in providers
        ]
        default = next((item for item in snapshot["defaults"] if item["capability"] == "text_generation"), None)  # type: ignore[union-attr]
        return available, ({"connection_id": default["connection_id"], "model_id": default["model_id"]} if default else None)

    @staticmethod
    def _require_notebook(connection: Any, context: ModelSelectionContext, notebook_id: str) -> None:
        if connection.execute(
            "SELECT 1 FROM notebooks WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s",
            (context.tenant_id, context.workspace_id, notebook_id)).fetchone() is None:
            raise ModelSelectionError("NOTEBOOK_NOT_FOUND", 404)

    def get(self, context: ModelSelectionContext, notebook_id: str) -> dict[str, object]:
        try:
            with self._store._transaction(self._scope(context, "model_selection.read")) as connection:
                self._require_notebook(connection, context, notebook_id)
                row = connection.execute(
                    "SELECT connection_id,model_id,reasoning_level FROM notebook_model_selections "
                    "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND user_id=%s",
                    (context.tenant_id, context.workspace_id, notebook_id, context.actor_id)).fetchone()
                available, default = self._available(connection, context)
        except CloudDatabaseError:
            raise ModelSelectionError("MODEL_SELECTION_UNAVAILABLE", 503) from None
        selection = None if row is None else {"connection_id": str(row[0]), "model_id": str(row[1]), "reasoning_level": row[2]}
        return {"selection": selection, "available": available, "default": default, "levels": list(REASONING_LEVELS)}

    def put(self, context: ModelSelectionContext, notebook_id: str, *, connection_id: str | None,
            model_id: str | None, reasoning_level: str | None) -> dict[str, object]:
        if (connection_id is None) != (model_id is None) or (connection_id is None and reasoning_level is not None):
            raise ModelSelectionError("MODEL_SELECTION_INVALID", 400)
        if reasoning_level is not None and reasoning_level not in REASONING_LEVELS:
            raise ModelSelectionError("REASONING_LEVEL_UNSUPPORTED", 409)
        try:
            with self._store._transaction(self._scope(context, "model_selection.write")) as connection:
                self._require_notebook(connection, context, notebook_id)
                if connection_id is None:
                    connection.execute(
                        "DELETE FROM notebook_model_selections WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND user_id=%s",
                        (context.tenant_id, context.workspace_id, notebook_id, context.actor_id))
                else:
                    available, _ = self._available(connection, context)
                    match = next((item for item in available
                                  if item["connection_id"] == connection_id and item["model_id"] == model_id), None)
                    if match is None:
                        raise ModelSelectionError("SELECTED_MODEL_UNAVAILABLE", 409)
                    if reasoning_level is not None and reasoning_level not in match["reasoning_levels"]:  # type: ignore[operator]
                        raise ModelSelectionError("REASONING_LEVEL_UNSUPPORTED", 409)
                    connection.execute(
                        "INSERT INTO notebook_model_selections(tenant_id,workspace_id,notebook_id,user_id,connection_id,model_id,reasoning_level,updated_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (tenant_id,workspace_id,notebook_id,user_id) "
                        "DO UPDATE SET connection_id=EXCLUDED.connection_id,model_id=EXCLUDED.model_id,"
                        "reasoning_level=EXCLUDED.reasoning_level,updated_at=now()",
                        (context.tenant_id, context.workspace_id, notebook_id, context.actor_id, connection_id, model_id, reasoning_level))
        except CloudDatabaseError:
            raise ModelSelectionError("MODEL_SELECTION_UNAVAILABLE", 503) from None
        if connection_id is not None and self._auto_prober is not None and not match["reasoning_checked"]:
            try:
                self._auto_prober(context.tenant_id, context.workspace_id, context.actor_id, connection_id, model_id)
            except Exception:  # 확인 실패는 선택을 막지 않는다. 수준은 계속 '확인 전'으로 남는다.
                pass
        return self.get(context, notebook_id)

    def read_selection(self, tenant_id: str, workspace_id: str, notebook_id: str, actor_id: str) -> dict[str, object] | None:
        """질문 실행 경로가 쓴다. 저장된 선택이 없으면 None(= 작업공간 기본 모델)."""
        try:
            with self._store._transaction(CloudAccessContext(tenant_id, workspace_id, actor_id, "model_selection.read")) as connection:
                row = connection.execute(
                    "SELECT connection_id,model_id,reasoning_level FROM notebook_model_selections "
                    "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND user_id=%s",
                    (tenant_id, workspace_id, notebook_id, actor_id)).fetchone()
        except CloudDatabaseError:
            raise ModelSelectionError("MODEL_SELECTION_UNAVAILABLE", 503) from None
        return None if row is None else {"connection_id": str(row[0]), "model_id": str(row[1]), "reasoning_level": row[2]}

    def confirm_reasoning_levels(self, tenant_id: str, actor_id: str, connection_id: str, model_id: str,
                                 levels: Sequence[str]) -> dict[str, object]:
        """관리자가 모델이 지원하는 추론 수준을 확인해 등록한다. 요청 필드가 확인된 Provider만 가능하다."""
        clean = list(dict.fromkeys(levels))
        if any(item not in REASONING_LEVELS for item in clean):
            raise ModelSelectionError("REASONING_LEVEL_UNSUPPORTED", 400)
        try:
            with self._store._transaction(CloudAccessContext(tenant_id, f"system:{tenant_id}", actor_id, "provider_admin.write")) as connection:
                row = connection.execute(
                    "SELECT c.provider_code FROM system_provider_models m JOIN system_provider_connections c ON c.connection_id=m.connection_id "
                    "WHERE m.connection_id=%s AND m.model_id=%s", (connection_id, model_id)).fetchone()
                if row is None:
                    raise ModelSelectionError("SELECTED_MODEL_UNAVAILABLE", 404)
                if clean and str(row[0]) not in REASONING_PROVIDERS:
                    raise ModelSelectionError("REASONING_PROVIDER_UNSUPPORTED", 409)
                connection.execute(
                    "UPDATE system_provider_models SET confirmed_reasoning_levels=%s,reasoning_probed_at=now(),updated_at=now(),updated_by=%s "
                    "WHERE connection_id=%s AND model_id=%s", (clean, actor_id, connection_id, model_id))
        except CloudDatabaseError:
            raise ModelSelectionError("MODEL_SELECTION_UNAVAILABLE", 503) from None
        return {"connection_id": connection_id, "model_id": model_id, "reasoning_levels": clean}


def _reasoning_tokens(response: Mapping[str, object]) -> int | None:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return None
    for key in ("completion_tokens_details", "output_tokens_details"):
        details = usage.get(key)
        if isinstance(details, Mapping) and isinstance(details.get("reasoning_tokens"), int):
            return int(details["reasoning_tokens"])
    return None


def probe_reasoning_levels(
    service: "ModelSelectionService", resolver: Any, transport: Any, *, tenant_id: str, workspace_id: str,
    actor_id: str, connection_id: str, model_id: str,
) -> dict[str, object]:
    """모델이 추론 수준 요청을 실제로 받아 주는지 아주 작은 요청으로 수준마다 시험하고, 받아 준 수준만 확인(confirm)으로 저장한다.

    '받아 줌'은 요청 필드를 거부하지 않았다는 뜻이다. 제공자가 reasoning 토큰을 돌려주면 그 수도 함께 기록한다.
    """
    from .question_answering import _append_provider_path
    from .workspace_model_defaults import WorkspaceModelContext, WorkspaceModelUnavailable

    results: dict[str, dict[str, object]] = {}
    try:
        with resolver.resolve(
            WorkspaceModelContext(tenant_id, workspace_id, actor_id), "text_generation",
            connection_id=connection_id, model_id=model_id,
        ) as selected:
            if selected.provider_code not in REASONING_PROVIDERS or selected.adapter_type == "anthropic_compatible":
                raise ModelSelectionError("REASONING_PROVIDER_UNSUPPORTED", 409)
            key = selected.credential_text(required=selected.provider_code != "CUSTOM")
            responses_api = selected.provider_code == "OMNIROUTE"
            path = "/v1/responses" if responses_api else "/v1/chat/completions" if selected.provider_code == "EOUL_GATEWAY" else "/chat/completions"
            url = _append_provider_path(selected.base_url, path)

            def call(level: str | None) -> Mapping[str, object]:
                if responses_api:
                    payload: dict[str, object] = {"model": selected.model_id, "input": "1+1=", "max_output_tokens": 256}
                    if level:
                        payload["reasoning_effort"] = level
                else:
                    payload = {"model": selected.model_id, "messages": [{"role": "user", "content": "1+1="}], "max_tokens": 256}
                    if level:
                        payload["reasoning_effort"] = level
                if key is None:
                    return transport.post_json_no_auth(url=url, payload=payload, timeout_seconds=30)
                return transport.post_json(url=url, api_key=key, payload=payload, timeout_seconds=30)

            try:
                call(None)
            except Exception as error:  # 수준과 무관하게 모델 자체가 응답하지 않는다.
                raise ModelSelectionError("MODEL_PROBE_FAILED", 502) from error
            for level in REASONING_LEVELS:
                for attempt in range(3):
                    try:
                        response = call(level)
                        results[level] = {"accepted": True, "reasoning_tokens": _reasoning_tokens(response)}
                        break
                    except Exception as error:
                        code = str(getattr(error, "code", "") or "REJECTED")
                        results[level] = {"accepted": False, "code": code[:64]}
                        # 일시적 오류(한도·지연)는 거부와 구별한다: 잠시 쉬고 다시 시도한다. 명시적 거부(REJECTED)는 그대로 둔다.
                        if "UNAVAILABLE" not in code or attempt == 2:
                            break
                        time.sleep(2 * (attempt + 1))
                time.sleep(0.5)
    except WorkspaceModelUnavailable as error:
        raise ModelSelectionError("SELECTED_MODEL_UNAVAILABLE", 409) from error
    accepted = [level for level in REASONING_LEVELS if results[level]["accepted"]]
    service.confirm_reasoning_levels(tenant_id, actor_id, connection_id, model_id, accepted)
    return {"connection_id": connection_id, "model_id": model_id, "results": results, "confirmed": accepted}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SelectionBody(_Strict):
    connection_id: str | None = Field(default=None, max_length=256)
    model_id: str | None = Field(default=None, max_length=256)
    reasoning_level: str | None = Field(default=None, max_length=16)


class ConfirmBody(_Strict):
    connection_id: str = Field(min_length=1, max_length=256)
    model_id: str = Field(min_length=1, max_length=256)
    levels: list[str] = Field(max_length=4)


class ProbeBody(_Strict):
    workspace_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    connection_id: str = Field(min_length=1, max_length=256)
    model_id: str = Field(min_length=1, max_length=256)


def register_model_selection_routes(app: FastAPI, dependencies: Any, service: ModelSelectionService,
                                    resolver: Any = None, transport: Any = None) -> None:
    from .authorization import Action
    from .runtime import _principal, _require_query_keys

    if resolver is not None and transport is not None:
        service.set_auto_prober(lambda tenant, workspace, actor, connection, model: probe_reasoning_levels(
            service, resolver, transport, tenant_id=tenant, workspace_id=workspace, actor_id=actor,
            connection_id=connection, model_id=model))

    def _context(principal: Any, workspace_id: str, request: Request) -> ModelSelectionContext:
        return ModelSelectionContext(principal.tenant_id, workspace_id, principal.user_id,
                                     request.state.trace_id, dependencies.settings.policy_version)

    def _check(id: str, notebook_id: str, request: Request) -> Any:
        _require_query_keys(request, frozenset())
        if not _SAFE.fullmatch(notebook_id):
            raise HTTPException(status_code=400)
        principal = _principal(request, dependencies)
        dependencies.authorization_service.authorize_action(
            principal=principal, workspace_id=id, action=Action.VIEW,
            trace_id=request.state.trace_id, policy_version=dependencies.settings.policy_version)
        return principal

    def _fail(error: ModelSelectionError, request: Request) -> JSONResponse:
        from .runtime import _error_response
        code = error.code if error.code in MODEL_SELECTION_PUBLIC_CODES else "INVALID_REQUEST"
        return _error_response(error.status, code, request.state.trace_id)

    @app.get("/api/v1/workspaces/{id}/notebooks/{notebook_id}/model-selection")
    async def get_model_selection(id: str, notebook_id: str, request: Request) -> JSONResponse:
        principal = _check(id, notebook_id, request)
        try:
            data = await asyncio.to_thread(service.get, _context(principal, id, request), notebook_id)
        except ModelSelectionError as error:
            return _fail(error, request)
        return JSONResponse({"data": data, "meta": {"trace_id": request.state.trace_id, "workspace_id": id}})

    @app.put("/api/v1/workspaces/{id}/notebooks/{notebook_id}/model-selection")
    async def put_model_selection(id: str, notebook_id: str, body: SelectionBody, request: Request) -> JSONResponse:
        principal = _check(id, notebook_id, request)
        try:
            data = await asyncio.to_thread(
                service.put, _context(principal, id, request), notebook_id,
                connection_id=body.connection_id, model_id=body.model_id, reasoning_level=body.reasoning_level)
        except ModelSelectionError as error:
            return _fail(error, request)
        return JSONResponse({"data": data, "meta": {"trace_id": request.state.trace_id, "workspace_id": id}})

    @app.post("/api/v1/admin/model-reasoning/probe")
    async def probe_model_reasoning(body: ProbeBody, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        principal = _principal(request, dependencies)
        if principal.user_id not in dependencies.settings.system_admin_user_ids:
            raise HTTPException(status_code=403)
        if resolver is None or transport is None:
            raise HTTPException(status_code=503)
        try:
            data = await asyncio.to_thread(
                probe_reasoning_levels, service, resolver, transport, tenant_id=principal.tenant_id,
                workspace_id=body.workspace_id, actor_id=principal.user_id,
                connection_id=body.connection_id, model_id=body.model_id)
        except ModelSelectionError as error:
            return _fail(error, request)
        dependencies.audit_store.append(AuditEventDraft(
            event_id="ms-" + secrets.token_hex(16), occurred_at=datetime.now(timezone.utc), actor_id=principal.user_id,
            actor_type=ActorType.USER, tenant_id=principal.tenant_id, workspace_id=None, action="provider_model.reasoning_probed",
            target_type="provider_model", target_id=f"{body.connection_id}:{body.model_id}", outcome=AuditOutcome.SUCCEEDED,
            trace_id=request.state.trace_id, policy_version=dependencies.settings.policy_version,
            metadata={"confirmed": data["confirmed"]}))
        return JSONResponse({"data": data, "meta": {"trace_id": request.state.trace_id}})

    @app.put("/api/v1/admin/model-reasoning")
    async def confirm_model_reasoning(body: ConfirmBody, request: Request) -> JSONResponse:
        _require_query_keys(request, frozenset())
        principal = _principal(request, dependencies)
        if principal.user_id not in dependencies.settings.system_admin_user_ids:
            raise HTTPException(status_code=403)
        try:
            data = await asyncio.to_thread(
                service.confirm_reasoning_levels, principal.tenant_id, principal.user_id,
                body.connection_id, body.model_id, body.levels)
        except ModelSelectionError as error:
            return _fail(error, request)
        dependencies.audit_store.append(AuditEventDraft(
            event_id="ms-" + secrets.token_hex(16), occurred_at=datetime.now(timezone.utc), actor_id=principal.user_id,
            actor_type=ActorType.USER, tenant_id=principal.tenant_id, workspace_id=None, action="provider_model.reasoning_confirmed",
            target_type="provider_model", target_id=f"{body.connection_id}:{body.model_id}", outcome=AuditOutcome.SUCCEEDED,
            trace_id=request.state.trace_id, policy_version=dependencies.settings.policy_version,
            metadata={"levels": data["reasoning_levels"]}))
        return JSONResponse({"data": data, "meta": {"trace_id": request.state.trace_id}})
