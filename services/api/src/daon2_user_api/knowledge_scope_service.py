"""Daon 승인 지식 목록과 노트북별 업무 패키지 선택(WO-K2 T3, T4).

목록은 Daon2-RAG `list_knowledge_scopes`에서 매번 읽는다. 승인 문서가 1건 이상이라고 응답한 업무 패키지만 보여 주고,
승인 정보가 없는 항목은 내보내지 않는다. 선택 저장 시에도 서버가 목록을 다시 읽어 확인하고 이름은 서버 값을 쓴다.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .cloud_storage import CloudAccessContext, CloudDatabaseError
from .knowledge_connector_service import ConnectorContext, ConnectorError
from .mcp_client import McpError

MAX_SELECTED = 8
# 지식 상태 확인(WO-K6): 선택한 패키지마다 가벼운 조회 1건씩. GraphRAG는 모델을 불러 오래 걸리므로 상태 확인에 쓰지 않는다.
_STATUS_PROBES = (
    ("ontology", "ontology_search_concepts", "concepts"),
    ("ruleset", "ruleset_list", "rulesets"),
    ("approved", "approved_knowledge_search", "assets"),
)
STATUS_REUSE_SECONDS = 60  # 상태 조회는 질문과 같은 호출 한도를 쓴다. 같은 노트북·같은 선택이면 잠시 다시 쓴다.
_NOT_READY = frozenset({"NOT_READY", "SCOPE_FORBIDDEN", "MCP_FORBIDDEN"})
# Daon2 범용 토큰의 패키지 목록은 services로 서비스별 사용 가능 여부를 준다(승인 자산은 없음).
_SERVICE_KINDS = (("ontology", "ontology"), ("ruleset", "ruleset"), ("graphrag", "graphrag"))
MAX_SELECTION_BODY = 200
# 한 번에 받을 개수는 서버 도구 설명의 limit 최댓값을 따른다(Daon2 2026-11-12 권고). 모르면 50, 많아도 200. 다음 쪽은 cursor로 읽는다.
PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_PAGES = 100
# tenant_id는 없어도 된다: Daon2 범용 토큰은 서버가 tenant를 정하고, 재생성 중인 패키지는 tenant 없이 오기도 한다(2026-11-16 ysna).
_TEXT_FIELDS = ("project_id", "project_name", "work_package_id", "work_package_name")
SERVER_TENANT = "server"  # 저장 칸이 비어 있을 수 없어, 서버가 정하는 tenant를 이 표시로 남긴다
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


def _usable_row(row: Any) -> bool:
    """필수 항목이 빠진 행은 그 행만 건너뛴다. 한 행 때문에 목록 전체가 실패하지 않게 한다."""
    return isinstance(row, Mapping) and all(isinstance(row.get(field), str) and row[field] for field in _TEXT_FIELDS)


def _approved(row: Mapping[str, Any]) -> bool:
    count = row.get("approved_document_count")
    return type(count) is int and count >= 1


class KnowledgeScopeService:
    def __init__(self, store: Any, connectors: Any, shared_connector_tenant: str | None = None) -> None:
        self._store = store
        self._connectors = connectors
        self._shared_connector_tenant = shared_connector_tenant  # 조직마다 등록하지 않고 쓰는 시스템 공용 연결(WO-K4 D4)
        self._clock = time.monotonic
        self._status_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
        self._status_lock = threading.Lock()

    @staticmethod
    def _scope(context: KnowledgeScopeContext, capability: str) -> CloudAccessContext:
        return CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, capability)

    def evidence_target(self, context: KnowledgeScopeContext, exclude: frozenset[str] = frozenset()
                        ) -> tuple[ConnectorContext, str, dict[tuple[str, str], Mapping[str, Any]]] | None:
        """질문 경로가 쓴다: 호출 문맥, 실제 Daon2-RAG Connector, 지금 승인된 업무 패키지.

        exclude는 질문 도구에서 끈 연결(NB2-F1)이다. 쓸 수 있는 Daon2-RAG 연결을 모두 껐으면 None이고 아무 연결도 호출하지 않는다.
        """
        connector_context, connector = self._rag_connector(context, exclude)
        if connector is None:
            return None
        return connector_context, connector["connector_id"], self._read_approved(connector_context, connector)

    def _approved_scopes(self, context: KnowledgeScopeContext) -> dict[tuple[str, str], Mapping[str, Any]]:
        connector_context, connector = self._rag_connector(context)
        return self._read_approved(connector_context, connector)  # type: ignore[arg-type]

    def _rag_connector(self, context: KnowledgeScopeContext, exclude: frozenset[str] = frozenset()) -> tuple[ConnectorContext, Mapping[str, Any] | None]:
        """첫 번째 확인된 Daon2-RAG 연결. 연결이 하나도 없으면 오류, 있는데 exclude로 모두 껐으면 연결 자리가 None이다."""
        connector_context = ConnectorContext(context.tenant_id, context.actor_id, context.trace_id, context.workspace_id, context.policy_version, self._shared_connector_tenant)
        # 가상(시험용) 서버의 값은 승인 지식이 아니므로 쓰지 않는다.
        candidates = [item for item in self._connectors.list(connector_context)
                      if item["kind"] == "daon2_rag" and item["status"] == "verified" and not item.get("virtual")]
        if not candidates:
            raise KnowledgeScopeError("KNOWLEDGE_CONNECTOR_NOT_CONFIGURED", 409)
        return connector_context, next((item for item in candidates if item["connector_id"] not in exclude), None)

    def daon2_target(self, context: KnowledgeScopeContext, exclude: frozenset[str] = frozenset()) -> tuple[ConnectorContext, str] | None:
        """온톨로지·규칙을 읽는 실제 Daon2 연결. 없거나 질문 도구에서 껐으면(exclude) 그 지식 종류를 LLM에게 보이지 않는다."""
        connector_context = ConnectorContext(context.tenant_id, context.actor_id, context.trace_id, context.workspace_id, context.policy_version, self._shared_connector_tenant)
        connector = next((item for item in self._connectors.list(connector_context)
                          if item["kind"] == "daon2" and item["status"] == "verified" and not item.get("virtual")
                          and item["connector_id"] not in exclude), None)
        return None if connector is None else (connector_context, connector["connector_id"])

    def _page_size(self, connector_context: ConnectorContext, connector_id: str) -> int:
        reader = getattr(self._connectors, "tool_limit", None)
        try:
            maximum = reader(connector_context, connector_id, "list_knowledge_scopes") if callable(reader) else None
        except (McpError, ConnectorError):
            maximum = None
        return min(maximum, MAX_PAGE_SIZE) if maximum else PAGE_SIZE

    def _read_approved(self, connector_context: ConnectorContext, connector: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
        found: dict[tuple[str, str], Mapping[str, Any]] = {}
        cursor: str | None = None
        seen: set[str] = set()
        page_size = self._page_size(connector_context, connector["connector_id"])
        for _ in range(MAX_PAGES):
            arguments: dict[str, Any] = {"limit": page_size, **({"cursor": cursor} if cursor else {})}
            page = self._connectors.call(connector_context, connector["connector_id"], "list_knowledge_scopes", arguments).structured
            if not isinstance(page, Mapping) or not isinstance(page.get("scopes"), list):
                raise _invalid()
            for row in filter(_usable_row, page["scopes"]):
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

    def knowledge_status(self, context: KnowledgeScopeContext, notebook_id: str) -> dict[str, Any]:
        """선택한 업무 패키지별로 쓸 수 있는 지식 종류. ready·empty(준비됐지만 없음)·not_ready·unknown(확인 실패)·none(연결 없음)."""
        selected = self.selection(context, notebook_id)["items"]
        key = (context.tenant_id, context.workspace_id, notebook_id, tuple((i["project_id"], i["work_package_id"]) for i in selected))
        now = self._clock()
        with self._status_lock:
            self._status_cache = {k: v for k, v in self._status_cache.items() if v[0] > now}
            cached = self._status_cache.get(key)
        if cached is not None:
            return cached[1]
        result = self._fresh_status(context, selected)
        with self._status_lock:
            self._status_cache[key] = (now + STATUS_REUSE_SECONDS, result)
        return result

    def _fresh_status(self, context: KnowledgeScopeContext, selected: list[dict[str, Any]]) -> dict[str, Any]:
        approved = self._approved_scopes(context) if selected else {}
        daon2 = self.daon2_target(context)
        items = []
        for item in selected:
            row = approved.get((item["project_id"], item["work_package_id"]))
            kinds: dict[str, str] = {"rag": "ready" if row else "not_ready"}
            services = row.get("services") if row else None
            known = {kind: ("ready" if services.get(key) is True else "not_ready") for kind, key in _SERVICE_KINDS} if isinstance(services, Mapping) else {}
            for kind, tool, field in _STATUS_PROBES:
                kinds[kind] = "none" if daon2 is None else "unknown" if row is None else known.get(kind) or self._probe(daon2, row, item, tool, field)
            ontology = kinds["ontology"]
            kinds["graphrag"] = known.get("graphrag") if daon2 is not None and "graphrag" in known else "unknown" if ontology in {"ready", "empty"} else ontology
            items.append({**item, "document_count": row["approved_document_count"] if row else 0, "kinds": kinds})
        return {"items": items}

    def _probe(self, daon2: tuple[ConnectorContext, str], row: Mapping[str, Any], item: Mapping[str, Any], tool: str, field: str) -> str:
        scope = {**({"tenant_id": row["tenant_id"]} if row.get("tenant_id") else {}), "project_id": row["project_id"], "work_package_id": row["work_package_id"]}
        arguments: dict[str, Any] = {"scope": scope, "limit": 1}
        if tool == "ontology_search_concepts":
            arguments["query"] = (item.get("work_package_name") or "개념")[:200]
        try:
            result = self._connectors.call(daon2[0], daon2[1], tool, arguments)
        except McpError as error:
            return "not_ready" if error.code in _NOT_READY else "unknown"
        except ConnectorError:
            return "unknown"
        page = getattr(result, "structured", None)
        if getattr(result, "is_error", False) or not isinstance(page, Mapping) or page.get("provenance") != "EXPERT_APPROVED":
            return "unknown"
        if tool == "ontology_search_concepts":
            return "ready"  # 검색 결과가 비어도 패키지의 온톨로지는 준비된 상태다
        return "ready" if page.get(field) else "empty"

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
                        (context.tenant_id, context.workspace_id, notebook_id, row.get("tenant_id") or SERVER_TENANT, row["project_id"], row["project_name"],
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

    @app.get("/api/v1/workspaces/{id}/notebooks/{notebook_id}/knowledge-scopes/status")
    async def get_notebook_knowledge_status(id: str, notebook_id: str, request: Request) -> JSONResponse:
        return _ok(await asyncio.to_thread(service.knowledge_status, _context(id, Action.VIEW, request), _notebook(notebook_id)), id, request)

    @app.put("/api/v1/workspaces/{id}/notebooks/{notebook_id}/knowledge-scopes")
    async def put_notebook_knowledge_scopes(id: str, notebook_id: str, body: SelectionBody, request: Request) -> JSONResponse:
        items = [item.model_dump() for item in body.items]
        return _ok(await asyncio.to_thread(service.replace, _context(id, Action.EDIT, request), _notebook(notebook_id), items), id, request)

    @app.exception_handler(KnowledgeScopeError)
    async def knowledge_scope_error(request: Request, error: KnowledgeScopeError) -> JSONResponse:
        code = error.code if error.code in KNOWLEDGE_SCOPE_PUBLIC_CODES else "INVALID_REQUEST"
        return _error_response(error.status, code, request.state.trace_id)
