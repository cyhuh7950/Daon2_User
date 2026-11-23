"""노트북·사용자별 질문 도구 켜고 끄기(WO-N1 N1-2). 결정 D-02: 웹 도구는 없다(내부 도구만).

도구는 승인 지식(`approved_knowledge`)과 지식 연결(`connector:<connector_id>`, 종류 daon2_rag·daon2·law)이다.
저장값은 사용자가 직접 바꾼 도구만 담는다. 저장값이 없는 도구는 켜짐이 기본이므로, 행이 없으면 지금까지와 같은 동작이다.
질문 처리 경로는 화면이 보낸 값이 아니라 `read_state`로 서버 저장값을 읽어 적용한다.
"""

from __future__ import annotations

import asyncio
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .answer_process import is_safe_text
from .audit import ActorType, AuditEventDraft, AuditOutcome
from .cloud_storage import CloudAccessContext, CloudDatabaseError
from .knowledge_connector_service import KINDS, ConnectorContext, ConnectorError

APPROVED_KNOWLEDGE = "approved_knowledge"
CONNECTOR_PREFIX = "connector:"
APPROVED_LABEL = "승인 지식"
# 관리자가 붙인 연결 이름이 주소처럼 보이면(답변 과정 블록에 남길 수 없으면) 종류 이름을 쓴다.
KIND_LABELS: Mapping[str, str] = {"daon2_rag": "문서 근거", "daon2": "Daon2 지식", "law": "법령"}
MAX_TOOL_CHANGES = 64
QUESTION_TOOLS_PUBLIC_CODES = frozenset({
    "NOTEBOOK_NOT_FOUND", "QUESTION_TOOL_UNKNOWN", "QUESTION_TOOLS_INVALID", "QUESTION_TOOLS_UNAVAILABLE",
})
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")

_NOTEBOOK_SQL = "SELECT 1 FROM notebooks WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s"
_SCOPE_SQL = "SELECT 1 FROM notebook_knowledge_scopes WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s LIMIT 1"
_STORED_SQL = ("SELECT enabled_json FROM notebook_question_tools "
               "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND actor_id=%s")
# 여러 창에서 따로 바꿔도 서로 지우지 않게 DB에서 합친다(나중 값이 이긴다).
_UPSERT_SQL = ("INSERT INTO notebook_question_tools(tenant_id,workspace_id,notebook_id,actor_id,enabled_json,updated_at) "
               "VALUES (%s,%s,%s,%s,%s,now()) ON CONFLICT (tenant_id,workspace_id,notebook_id,actor_id) "
               "DO UPDATE SET enabled_json=notebook_question_tools.enabled_json||EXCLUDED.enabled_json,updated_at=now() "
               "RETURNING enabled_json")


class QuestionToolsError(RuntimeError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True, slots=True)
class QuestionToolsContext:
    tenant_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class QuestionToolState:
    """질문 처리에 적용할 상태.

    approved_knowledge: 승인 지식을 꺼 두지 않았는가(저장값, 없으면 켬). 범위가 없어도 지식 패키지 입력은 지금처럼 쓴다.
    disabled_connectors: 사용자가 끈 지식 연결 ID. 이 연결은 질문 경로에서 호출하지 않는다.
    labels: 답변 과정 scope.tools에 남길 켜진 도구 라벨(조회 응답의 enabled=true와 같은 목록).
    """

    approved_knowledge: bool
    disabled_connectors: frozenset[str]
    labels: tuple[str, ...]


def enabled_ids(data: Mapping[str, Any]) -> list[str]:
    return [str(item["id"]) for item in data["tools"] if item["enabled"]]


def _label(connector: Mapping[str, Any]) -> str:
    name = connector.get("name")
    return name if is_safe_text(name, limit=120) else KIND_LABELS[str(connector["kind"])]


class QuestionToolsService:
    def __init__(self, store: Any, connectors: Any = None, shared_connector_tenant: str | None = None) -> None:
        self._store = store
        self._connectors = connectors
        self._shared_connector_tenant = shared_connector_tenant  # 지식 범위·질문 경로와 같은 시스템 공용 연결 기준

    def _connector_rows(self, tenant_id: str, workspace_id: str, actor_id: str, trace_id: str, policy_version: str) -> list[Mapping[str, Any]]:
        """질문 경로가 쓸 수 있는 지식 연결. 가상(시험용) 연결은 질문 근거로 쓰지 않으므로 도구로도 내놓지 않는다."""
        if self._connectors is None:
            return []
        context = ConnectorContext(tenant_id, actor_id, trace_id, workspace_id, policy_version, self._shared_connector_tenant)
        try:
            rows = self._connectors.list(context)
        except (CloudDatabaseError, ConnectorError):
            raise QuestionToolsError("QUESTION_TOOLS_UNAVAILABLE", 503) from None
        return [row for row in rows if row.get("kind") in KINDS and not row.get("virtual")]

    @staticmethod
    def _tools(connectors: Sequence[Mapping[str, Any]], has_scope: bool, stored: Mapping[str, Any]) -> list[dict[str, Any]]:
        def item(tool_id: str, kind: str, label: str, reason: str | None, **extra: Any) -> dict[str, Any]:
            chosen = stored.get(tool_id, True) is True
            entry: dict[str, Any] = {"id": tool_id, "kind": kind, **extra, "label": label,
                                     "available": reason is None, "enabled": chosen and reason is None}
            if reason is not None:
                entry["reason"] = reason
            return entry

        tools = [item(APPROVED_KNOWLEDGE, APPROVED_KNOWLEDGE, APPROVED_LABEL, None if has_scope else "NO_SCOPE_SELECTED")]
        for row in connectors:
            status = row.get("status")
            reason = None if status == "verified" else "CONNECTOR_DISABLED" if status == "disabled" else "CONNECTOR_NOT_READY"
            tools.append(item(CONNECTOR_PREFIX + str(row["connector_id"]), "connector", _label(row), reason, connector_kind=row["kind"]))
        return tools

    @staticmethod
    def _stored(connection: Any, tenant_id: str, workspace_id: str, notebook_id: str, actor_id: str) -> dict[str, Any]:
        row = connection.execute(_STORED_SQL, (tenant_id, workspace_id, notebook_id, actor_id)).fetchone()
        value = None if row is None else row[0]
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _has_scope(connection: Any, tenant_id: str, workspace_id: str, notebook_id: str) -> bool:
        return connection.execute(_SCOPE_SQL, (tenant_id, workspace_id, notebook_id)).fetchone() is not None

    @staticmethod
    def _require_notebook(connection: Any, context: QuestionToolsContext, notebook_id: str) -> None:
        if connection.execute(_NOTEBOOK_SQL, (context.tenant_id, context.workspace_id, notebook_id)).fetchone() is None:
            raise QuestionToolsError("NOTEBOOK_NOT_FOUND", 404)

    def _connectors_for(self, context: QuestionToolsContext) -> list[Mapping[str, Any]]:
        return self._connector_rows(context.tenant_id, context.workspace_id, context.actor_id, context.trace_id, context.policy_version)

    def get(self, context: QuestionToolsContext, notebook_id: str) -> dict[str, Any]:
        connectors = self._connectors_for(context)
        try:
            with self._store._transaction(CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, "question_tools.read")) as connection:  # noqa: SLF001
                self._require_notebook(connection, context, notebook_id)
                stored = self._stored(connection, context.tenant_id, context.workspace_id, notebook_id, context.actor_id)
                has_scope = self._has_scope(connection, context.tenant_id, context.workspace_id, notebook_id)
        except CloudDatabaseError:
            raise QuestionToolsError("QUESTION_TOOLS_UNAVAILABLE", 503) from None
        return {"tools": self._tools(connectors, has_scope, stored)}

    def put(self, context: QuestionToolsContext, notebook_id: str, enabled: Mapping[str, bool]) -> dict[str, Any]:
        if (not isinstance(enabled, Mapping) or len(enabled) > MAX_TOOL_CHANGES
                or any(not isinstance(key, str) or type(value) is not bool for key, value in enabled.items())):
            raise QuestionToolsError("QUESTION_TOOLS_INVALID", 422)
        connectors = self._connectors_for(context)
        known = {APPROVED_KNOWLEDGE, *(CONNECTOR_PREFIX + str(row["connector_id"]) for row in connectors)}
        if any(key not in known for key in enabled):
            raise QuestionToolsError("QUESTION_TOOL_UNKNOWN", 422)
        try:
            with self._store._transaction(CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, "question_tools.write")) as connection:  # noqa: SLF001
                self._require_notebook(connection, context, notebook_id)
                if enabled:
                    row = connection.execute(_UPSERT_SQL, (context.tenant_id, context.workspace_id, notebook_id, context.actor_id,
                                                           Jsonb(dict(enabled)))).fetchone()
                    stored = dict(row[0]) if row is not None and isinstance(row[0], Mapping) else dict(enabled)
                else:
                    stored = self._stored(connection, context.tenant_id, context.workspace_id, notebook_id, context.actor_id)
                has_scope = self._has_scope(connection, context.tenant_id, context.workspace_id, notebook_id)
        except CloudDatabaseError:
            raise QuestionToolsError("QUESTION_TOOLS_UNAVAILABLE", 503) from None
        return {"tools": self._tools(connectors, has_scope, stored)}

    def read_state(self, tenant_id: str, workspace_id: str, notebook_id: str, actor_id: str,
                   trace_id: str = "question-tools", policy_version: str = "question-tools") -> QuestionToolState:
        """질문 처리 경로가 쓴다. 읽지 못하면 예외: 꺼 둔 도구를 모르는 채로 호출하지 않는다."""
        connectors = self._connector_rows(tenant_id, workspace_id, actor_id, trace_id, policy_version)
        try:
            with self._store._transaction(CloudAccessContext(tenant_id, workspace_id, actor_id, "question_tools.read")) as connection:  # noqa: SLF001
                stored = self._stored(connection, tenant_id, workspace_id, notebook_id, actor_id)
                has_scope = self._has_scope(connection, tenant_id, workspace_id, notebook_id)
        except CloudDatabaseError:
            raise QuestionToolsError("QUESTION_TOOLS_UNAVAILABLE", 503) from None
        tools = self._tools(connectors, has_scope, stored)
        return QuestionToolState(
            approved_knowledge=stored.get(APPROVED_KNOWLEDGE, True) is True,
            disabled_connectors=frozenset(str(row["connector_id"]) for row in connectors
                                          if stored.get(CONNECTOR_PREFIX + str(row["connector_id"]), True) is not True),
            labels=tuple(item["label"] for item in tools if item["enabled"]),
        )


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionToolsBody(_Strict):
    enabled: dict[str, StrictBool] = Field(max_length=MAX_TOOL_CHANGES)


def register_question_tools_routes(app: FastAPI, dependencies: Any, service: QuestionToolsService) -> None:
    from .authorization import Action
    from .runtime import _error_response, _json_with_etag, _principal, _require_query_keys

    def _check(id: str, notebook_id: str, request: Request) -> QuestionToolsContext:
        _require_query_keys(request, frozenset())
        if not _SAFE.fullmatch(notebook_id):
            raise HTTPException(status_code=400)
        principal = _principal(request, dependencies)
        policy_version = dependencies.settings.policy_version
        # 자기 선택만 읽고 쓰므로 노트북 보기 권한이면 된다(모델 선택과 같다).
        dependencies.authorization_service.authorize_action(
            principal=principal, workspace_id=id, action=Action.VIEW,
            trace_id=request.state.trace_id, policy_version=policy_version)
        return QuestionToolsContext(principal.tenant_id, id, principal.user_id, request.state.trace_id, policy_version)

    def _fail(error: QuestionToolsError, request: Request) -> JSONResponse:
        code = error.code if error.code in QUESTION_TOOLS_PUBLIC_CODES else "INVALID_REQUEST"
        return _error_response(error.status, code, request.state.trace_id)

    def _ok(data: Mapping[str, Any], id: str, request: Request) -> JSONResponse:
        # ETag는 도구 목록(켜짐·사용 가능 여부 포함)에서 만든다. 같은 목록이면 같은 값이다.
        seed = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        response = _json_with_etag({"data": data, "meta": {"trace_id": request.state.trace_id, "workspace_id": id}}, seed)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/workspaces/{id}/notebooks/{notebook_id}/question-tools")
    async def get_question_tools(id: str, notebook_id: str, request: Request) -> JSONResponse:
        context = _check(id, notebook_id, request)
        try:
            data = await asyncio.to_thread(service.get, context, notebook_id)
        except QuestionToolsError as error:
            return _fail(error, request)
        return _ok(data, id, request)

    @app.put("/api/v1/workspaces/{id}/notebooks/{notebook_id}/question-tools")
    async def put_question_tools(id: str, notebook_id: str, body: QuestionToolsBody, request: Request) -> JSONResponse:
        context = _check(id, notebook_id, request)
        try:
            data = await asyncio.to_thread(service.put, context, notebook_id, body.enabled)
        except QuestionToolsError as error:
            return _fail(error, request)
        # 켜진 도구 ID만 남긴다(질문·이름·연결 주소는 남기지 않는다).
        dependencies.audit_store.append(AuditEventDraft(
            event_id="qt-" + secrets.token_hex(16), occurred_at=datetime.now(timezone.utc), actor_id=context.actor_id,
            actor_type=ActorType.USER, tenant_id=context.tenant_id, workspace_id=id, action="notebook.question_tools.update",
            target_type="notebook", target_id=notebook_id, outcome=AuditOutcome.SUCCEEDED,
            trace_id=context.trace_id, policy_version=context.policy_version,
            metadata={"enabled": enabled_ids(data)}))
        return _ok(data, id, request)
