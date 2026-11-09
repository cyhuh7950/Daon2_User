"""Daon 승인 지식 목록과 노트북별 업무 패키지 선택(WO-K2 T3, T4).

목록은 Daon2-RAG `list_knowledge_scopes`에서 매번 읽는다. 승인 문서가 1건 이상이라고 응답한 업무 패키지만 보여 주고,
승인 정보가 없는 항목은 내보내지 않는다. 선택 저장 시에도 서버가 목록을 다시 읽어 확인하고 이름은 서버 값을 쓴다.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .cloud_storage import CloudAccessContext, CloudDatabaseError
from .knowledge_connector_service import ConnectorContext

MAX_SELECTED = 8
MAX_SELECTION_BODY = 200
PAGE_SIZE = 200
MAX_PAGES = 100
_TEXT_FIELDS = ("tenant_id", "project_id", "project_name", "work_package_id", "work_package_name")
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
KNOWLEDGE_SCOPE_PUBLIC_CODES = frozenset({
    "NOTEBOOK_NOT_FOUND", "KNOWLEDGE_CONNECTOR_NOT_CONFIGURED", "KNOWLEDGE_SCOPE_RESPONSE_INVALID", "KNOWLEDGE_SCOPE_NOT_AVAILABLE",
    "KNOWLEDGE_SCOPE_SELECTION_INVALID", "KNOWLEDGE_SCOPE_UNAVAILABLE",
})


class KnowledgeScopeError(RuntimeError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True, slots=True)
class KnowledgeScopeContext:
    tenant_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    policy_version: str


def _invalid() -> KnowledgeScopeError:
    return KnowledgeScopeError("KNOWLEDGE_SCOPE_RESPONSE_INVALID", 502)


def _checked_row(row: Any) -> Mapping[str, Any]:
    if not isinstance(row, Mapping) or any(not isinstance(row.get(field), str) or not row[field] for field in _TEXT_FIELDS):
        raise _invalid()
    return row


def _approved(row: Mapping[str, Any]) -> bool:
    count = row.get("approved_document_count")
    return type(count) is int and count >= 1


class KnowledgeScopeService:
    def __init__(self, store: Any, connectors: Any, shared_connector_tenant: str | None = None) -> None:
        self._store = store
        self._connectors = connectors
        self._shared_connector_tenant = shared_connector_tenant  # 조직마다 등록하지 않고 쓰는 시스템 공용 연결(WO-K4 D4)

    @staticmethod
    def _scope(context: KnowledgeScopeContext, capability: str) -> CloudAccessContext:
        return CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, capability)

    def evidence_target(self, context: KnowledgeScopeContext) -> tuple[ConnectorContext, str, dict[tuple[str, str], Mapping[str, Any]]]:
        """질문 경로가 쓴다: 호출 문맥, 실제 Daon2-RAG Connector, 지금 승인된 업무 패키지."""
        connector_context, connector = self._rag_connector(context)
        return connector_context, connector["connector_id"], self._read_approved(connector_context, connector)

    def _approved_scopes(self, context: KnowledgeScopeContext) -> dict[tuple[str, str], Mapping[str, Any]]:
        return self._read_approved(*self._rag_connector(context))

    def _rag_connector(self, context: KnowledgeScopeContext) -> tuple[ConnectorContext, Mapping[str, Any]]:
        connector_context = ConnectorContext(context.tenant_id, context.actor_id, context.trace_id, context.workspace_id, context.policy_version, self._shared_connector_tenant)
        # 가상(시험용) 서버의 값은 승인 지식이 아니므로 쓰지 않는다.
        connector = next((item for item in self._connectors.list(connector_context)
                          if item["kind"] == "daon2_rag" and item["status"] == "verified" and not item.get("virtual")), None)
        if connector is None:
            raise KnowledgeScopeError("KNOWLEDGE_CONNECTOR_NOT_CONFIGURED", 409)
        return connector_context, connector

    def daon2_target(self, context: KnowledgeScopeContext) -> tuple[ConnectorContext, str] | None:
        """온톨로지·규칙을 읽는 실제 Daon2 연결. 없으면 그 지식 종류를 LLM에게 보이지 않는다."""
        connector_context = ConnectorContext(context.tenant_id, context.actor_id, context.trace_id, context.workspace_id, context.policy_version, self._shared_connector_tenant)
        connector = next((item for item in self._connectors.list(connector_context)
                          if item["kind"] == "daon2" and item["status"] == "verified" and not item.get("virtual")), None)
        return None if connector is None else (connector_context, connector["connector_id"])

    def _read_approved(self, connector_context: ConnectorContext, connector: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
        found: dict[tuple[str, str], Mapping[str, Any]] = {}
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(MAX_PAGES):
            arguments: dict[str, Any] = {"limit": PAGE_SIZE, **({"cursor": cursor} if cursor else {})}
            page = self._connectors.call(connector_context, connector["connector_id"], "list_knowledge_scopes", arguments).structured
            if not isinstance(page, Mapping) or not isinstance(page.get("scopes"), list):
                raise _invalid()
            for row in map(_checked_row, page["scopes"]):
                if _approved(row):
                    found[(row["project_id"], row["work_package_id"])] = row
            cursor = page.get("next_cursor")
            if cursor is None:
                return found
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise _invalid()
            seen.add(cursor)
        raise _invalid()

    def catalog(self, context: KnowledgeScopeContext) -> dict[str, Any]:
        projects: dict[str, dict[str, Any]] = {}
        rows = sorted(self._approved_scopes(context).values(), key=lambda r: (r["project_name"], r["project_id"], r["work_package_name"], r["work_package_id"]))
        for row in rows:
            project = projects.setdefault(row["project_id"], {"project_id": row["project_id"], "project_name": row["project_name"], "work_packages": []})
            project["work_packages"].append({"work_package_id": row["work_package_id"], "work_package_name": row["work_package_name"], "updated_at": row.get("updated_at")})
        return {"projects": list(projects.values())}

    @staticmethod
    def _require_notebook(connection: Any, context: KnowledgeScopeContext, notebook_id: str) -> None:
        if connection.execute("SELECT 1 FROM notebooks WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s",
                              (context.tenant_id, context.workspace_id, notebook_id)).fetchone() is None:
            raise KnowledgeScopeError("NOTEBOOK_NOT_FOUND", 404)

    def selection(self, context: KnowledgeScopeContext, notebook_id: str) -> dict[str, Any]:
        try:
            with self._store._transaction(self._scope(context, "knowledge_scope.read")) as connection:  # noqa: SLF001
                self._require_notebook(connection, context, notebook_id)
                rows = connection.execute(
                    "SELECT project_id,project_name,work_package_id,work_package_name FROM notebook_knowledge_scopes "
                    "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s ORDER BY project_name,work_package_name",
                    (context.tenant_id, context.workspace_id, notebook_id)).fetchall()
        except CloudDatabaseError:
            raise KnowledgeScopeError("KNOWLEDGE_SCOPE_UNAVAILABLE", 503) from None
        return {"items": [{"project_id": r[0], "project_name": r[1], "work_package_id": r[2], "work_package_name": r[3]} for r in rows]}

    def replace(self, context: KnowledgeScopeContext, notebook_id: str, items: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        keys = [(item["project_id"], item["work_package_id"]) for item in items]
        if len(keys) > MAX_SELECTED or len(set(keys)) != len(keys):
            raise KnowledgeScopeError("KNOWLEDGE_SCOPE_SELECTION_INVALID")
        approved = self._approved_scopes(context) if keys else {}
        if any(key not in approved for key in keys):
            raise KnowledgeScopeError("KNOWLEDGE_SCOPE_NOT_AVAILABLE", 409)
        try:
            with self._store._transaction(self._scope(context, "knowledge_scope.write")) as connection:  # noqa: SLF001
                self._require_notebook(connection, context, notebook_id)
                connection.execute("DELETE FROM notebook_knowledge_scopes WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s",
                                   (context.tenant_id, context.workspace_id, notebook_id))
                for key in keys:
                    row = approved[key]
                    connection.execute(
                        "INSERT INTO notebook_knowledge_scopes(tenant_id,workspace_id,notebook_id,source_tenant_id,project_id,project_name,work_package_id,work_package_name,selected_by) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (context.tenant_id, context.workspace_id, notebook_id, row["tenant_id"], row["project_id"], row["project_name"],
                         row["work_package_id"], row["work_package_name"], context.actor_id))
        except CloudDatabaseError:
            raise KnowledgeScopeError("KNOWLEDGE_SCOPE_UNAVAILABLE", 503) from None
        return self.selection(context, notebook_id)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScopeItem(_Strict):
    project_id: str = Field(min_length=1, max_length=256)
    work_package_id: str = Field(min_length=1, max_length=256)


class SelectionBody(_Strict):
    items: list[ScopeItem] = Field(max_length=MAX_SELECTION_BODY)


def register_knowledge_scope_routes(app: FastAPI, dependencies: Any, service: KnowledgeScopeService) -> None:
    from .authorization import Action
    from .runtime import _error_response, _principal, _require_query_keys

    def _context(id: str, action: Action, request: Request) -> KnowledgeScopeContext:
        _require_query_keys(request, frozenset())
        principal = _principal(request, dependencies)
        policy_version = dependencies.settings.policy_version
        dependencies.authorization_service.authorize_action(principal=principal, workspace_id=id, action=action,
                                                            trace_id=request.state.trace_id, policy_version=policy_version)
        return KnowledgeScopeContext(principal.tenant_id, id, principal.user_id, request.state.trace_id, policy_version)

    def _ok(data: Mapping[str, Any], id: str, request: Request) -> JSONResponse:
        return JSONResponse({"data": data, "meta": {"trace_id": request.state.trace_id, "workspace_id": id}})

    def _notebook(notebook_id: str) -> str:
        if not _SAFE.fullmatch(notebook_id):
            raise HTTPException(status_code=400)
        return notebook_id

    @app.get("/api/v1/workspaces/{id}/daon-knowledge-scopes")
    async def list_daon_knowledge_scopes(id: str, request: Request) -> JSONResponse:
        return _ok(await asyncio.to_thread(service.catalog, _context(id, Action.VIEW, request)), id, request)

    @app.get("/api/v1/workspaces/{id}/notebooks/{notebook_id}/knowledge-scopes")
    async def get_notebook_knowledge_scopes(id: str, notebook_id: str, request: Request) -> JSONResponse:
        return _ok(await asyncio.to_thread(service.selection, _context(id, Action.VIEW, request), _notebook(notebook_id)), id, request)

    @app.put("/api/v1/workspaces/{id}/notebooks/{notebook_id}/knowledge-scopes")
    async def put_notebook_knowledge_scopes(id: str, notebook_id: str, body: SelectionBody, request: Request) -> JSONResponse:
        items = [item.model_dump() for item in body.items]
        return _ok(await asyncio.to_thread(service.replace, _context(id, Action.EDIT, request), _notebook(notebook_id), items), id, request)

    @app.exception_handler(KnowledgeScopeError)
    async def knowledge_scope_error(request: Request, error: KnowledgeScopeError) -> JSONResponse:
        code = error.code if error.code in KNOWLEDGE_SCOPE_PUBLIC_CODES else "INVALID_REQUEST"
        return _error_response(error.status, code, request.state.trace_id)
