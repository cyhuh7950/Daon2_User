"""소스 묶음 저장·조회(WO-N1 N1-5, NB3-F2). 결정 D-11: 노트북 공유, 정정 C-4: 질문 상한 8개 그대로.

- 묶음은 화면 편의다. 질문 범위 계산(질문 서비스)은 이 모듈을 쓰지 않고 바뀌지 않는다.
- 표는 `source_groups`(이름·순서)와 `source_group_members`(소스 → 묶음, 소스 하나는 묶음 하나에만)다.
- "노트북에 있는 소스"는 노트북 소스 목록 판정(`notebook_postgres.read_selected_context`)과 같은 규칙이다:
  notebook_bindings에 소스로 연결되어 있고, 떼지 않았고(notebook_source_unbindings 없음), 삭제 요청이 없고
  (deletion_requests.source_active=false 없음), 조회하는 사용자의 접근 거부(identity_auth_source_access.allowed=0)가 없다.
  조회는 이 규칙을 통과하지 못한 소스를 결과에서 뺄 뿐 묶음 행을 지우지 않는다.
- 정본 표(sources·source_versions·notebook_bindings·notebook_source_unbindings)는 읽기만 한다. 앱 역할에 UPDATE가
  없으므로 SELECT … FOR UPDATE도 쓰지 않는다. 변경 직렬화는 노트북 단위 pg_advisory_xact_lock으로 한다.
- 동시 변경은 If-Match로 막는다. ETag는 조회 결과(묶음·순서·보이는 소스)에서 만든다. 만들기(POST)는 Idempotency-Key로
  같은 키·같은 이름이면 같은 묶음을 돌려준다(group_id를 키에서 정한다).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from .audit import ActorType, AuditEventDraft, AuditOutcome
from .cloud_storage import CloudAccessContext, CloudDatabaseError

MAX_GROUPS = 50
MAX_NAME = 80
MAX_MEMBERS = 500
SOURCE_GROUPS_PUBLIC_CODES = frozenset({
    "NOTEBOOK_NOT_FOUND", "SOURCE_GROUP_NOT_FOUND", "SOURCE_GROUP_LIMIT", "SOURCE_GROUP_INVALID",
    "SOURCE_NOT_IN_NOTEBOOK", "SOURCE_GROUP_ETAG_MISMATCH", "SOURCE_GROUP_IDEMPOTENCY_KEY_REUSED", "SOURCE_GROUPS_UNAVAILABLE",
})
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_GROUP_ID = re.compile(r"^sg-[0-9a-f]{32}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# 노트북 단위 직렬화. 정본 표에는 행 잠금을 걸지 않는다.
_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))"
_NOTEBOOK_SQL = "SELECT 1 FROM notebooks WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s"
_GROUPS_SQL = ("SELECT group_id,name,position FROM source_groups WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s "
               "ORDER BY position,created_at,group_id")
# 노트북 소스 목록 판정과 같은 조건(b = notebook_bindings 행). %s 하나는 조회하는 사용자다.
_BINDING_ACTIVE = (
    "b.binding_kind='source' "
    "AND NOT EXISTS (SELECT 1 FROM notebook_source_unbindings u WHERE u.tenant_id=b.tenant_id AND u.workspace_id=b.workspace_id "
    "AND u.notebook_id=b.notebook_id AND u.source_id=b.record_id AND u.source_version_id=b.version_id) "
    "AND NOT EXISTS (SELECT 1 FROM deletion_requests dr WHERE dr.tenant_id=b.tenant_id AND dr.workspace_id=b.workspace_id "
    "AND dr.source_id=b.record_id AND dr.source_active=false) "
    "AND NOT EXISTS (SELECT 1 FROM identity_auth_source_access a WHERE a.tenant_id=b.tenant_id AND a.workspace_id=b.workspace_id "
    "AND a.user_id=%s AND a.source_version_id=b.version_id AND a.allowed=0)")
_VISIBLE_MEMBERS_SQL = (
    "SELECT m.group_id,m.source_id FROM source_group_members m "
    "WHERE m.tenant_id=%s AND m.workspace_id=%s AND m.notebook_id=%s "
    "AND EXISTS (SELECT 1 FROM notebook_bindings b WHERE b.tenant_id=m.tenant_id AND b.workspace_id=m.workspace_id "
    "AND b.notebook_id=m.notebook_id AND b.record_id=m.source_id AND " + _BINDING_ACTIVE + ") "
    "ORDER BY m.group_id,m.position,m.source_id")
_IN_NOTEBOOK_SQL = (
    "SELECT DISTINCT b.record_id FROM notebook_bindings b WHERE b.tenant_id=%s AND b.workspace_id=%s AND b.notebook_id=%s "
    "AND " + _BINDING_ACTIVE + " AND b.record_id=ANY(%s)")
_GROUP_SQL = "SELECT notebook_id,name FROM source_groups WHERE tenant_id=%s AND workspace_id=%s AND group_id=%s"
_COUNT_GROUPS_SQL = ("SELECT count(*),coalesce(max(position)+1,0) FROM source_groups "
                     "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s")
_INSERT_GROUP_SQL = ("INSERT INTO source_groups(tenant_id,workspace_id,notebook_id,group_id,name,position,created_by) "
                     "VALUES (%s,%s,%s,%s,%s,%s,%s)")
_RENAME_SQL = ("UPDATE source_groups SET name=%s,updated_at=now() "
               "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND group_id=%s")
_POSITION_SQL = ("UPDATE source_groups SET position=%s,updated_at=now() "
                 "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND group_id=%s")
_TOUCH_SQL = ("UPDATE source_groups SET updated_at=now() "
              "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND group_id=%s")
# 묶음을 지우면 source_group_members는 FK cascade로 함께 지워진다(소스 자체는 그대로).
_DELETE_GROUP_SQL = "DELETE FROM source_groups WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND group_id=%s"
_MOVED_SQL = ("SELECT count(*) FROM source_group_members WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s "
              "AND group_id<>%s AND source_id=ANY(%s)")
_CLEAR_MEMBERS_SQL = ("DELETE FROM source_group_members WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s "
                      "AND (group_id=%s OR source_id=ANY(%s))")
_INSERT_MEMBER_SQL = ("INSERT INTO source_group_members(tenant_id,workspace_id,notebook_id,group_id,source_id,position) "
                      "VALUES (%s,%s,%s,%s,%s,%s)")


class SourceGroupsError(RuntimeError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True, slots=True)
class SourceGroupsContext:
    tenant_id: str
    workspace_id: str
    actor_id: str
    trace_id: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class SourceGroupsResult:
    """data: 응답 data. etag: 이 변경 뒤 묶음 목록의 ETag. replayed·moved·removed: 감사·응답 meta용 개수."""

    data: Mapping[str, Any]
    etag: str
    replayed: bool = False
    moved: int = 0
    removed: int = 0
    fields: tuple[str, ...] = field(default=())


def _etag(data: Mapping[str, Any]) -> str:
    seed = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return '"sg-' + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32] + '"'


def _name(value: Any) -> str:
    if not isinstance(value, str) or _CONTROL.search(value):
        raise SourceGroupsError("SOURCE_GROUP_INVALID", 422)
    name = value.strip()
    if not 1 <= len(name) <= MAX_NAME:
        raise SourceGroupsError("SOURCE_GROUP_INVALID", 422)
    return name


def _source_ids(value: Any) -> list[str]:
    if (not isinstance(value, (list, tuple)) or len(value) > MAX_MEMBERS
            or any(not isinstance(item, str) or not _SAFE.fullmatch(item) for item in value) or len(set(value)) != len(value)):
        raise SourceGroupsError("SOURCE_GROUP_INVALID", 422)
    return list(value)


class SourceGroupsService:
    def __init__(self, store: Any) -> None:
        self._store = store

    def _tx(self, context: SourceGroupsContext, capability: str):  # type: ignore[no-untyped-def]
        return self._store._transaction(CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, capability))  # noqa: SLF001

    @staticmethod
    def _require_notebook(connection: Any, c: SourceGroupsContext, notebook_id: str) -> None:
        if connection.execute(_NOTEBOOK_SQL, (c.tenant_id, c.workspace_id, notebook_id)).fetchone() is None:
            raise SourceGroupsError("NOTEBOOK_NOT_FOUND", 404)

    @staticmethod
    def _lock(connection: Any, c: SourceGroupsContext, notebook_id: str) -> None:
        connection.execute(_LOCK_SQL, (f"source-groups|{c.tenant_id}|{c.workspace_id}|{notebook_id}",))

    @staticmethod
    def _view(connection: Any, c: SourceGroupsContext, notebook_id: str) -> dict[str, Any]:
        key = (c.tenant_id, c.workspace_id, notebook_id)
        groups = connection.execute(_GROUPS_SQL, key).fetchall()
        members: dict[str, list[str]] = {}
        for group_id, source_id in connection.execute(_VISIBLE_MEMBERS_SQL, key + (c.actor_id,)).fetchall():
            members.setdefault(str(group_id), []).append(str(source_id))
        return {"groups": [{"group_id": str(g), "name": str(n), "position": int(p), "source_ids": members.get(str(g), [])}
                           for g, n, p in groups]}

    def _begin_change(self, connection: Any, c: SourceGroupsContext, notebook_id: str, group_id: str,
                      expected_etag: str) -> dict[str, Any]:
        """잠금 → 노트북 → 묶음 → If-Match 순으로 확인하고 지금 조회 결과를 돌려준다."""
        self._lock(connection, c, notebook_id)
        self._require_notebook(connection, c, notebook_id)
        row = connection.execute(_GROUP_SQL, (c.tenant_id, c.workspace_id, group_id)).fetchone()
        if row is None or str(row[0]) != notebook_id:
            raise SourceGroupsError("SOURCE_GROUP_NOT_FOUND", 404)
        view = self._view(connection, c, notebook_id)
        if expected_etag != _etag(view):
            raise SourceGroupsError("SOURCE_GROUP_ETAG_MISMATCH", 412)
        return view

    def _finish(self, connection: Any, c: SourceGroupsContext, notebook_id: str, **extra: Any) -> SourceGroupsResult:
        view = self._view(connection, c, notebook_id)
        return SourceGroupsResult(view, _etag(view), **extra)

    def list(self, context: SourceGroupsContext, notebook_id: str) -> SourceGroupsResult:
        try:
            with self._tx(context, "source_groups.read") as connection:
                self._require_notebook(connection, context, notebook_id)
                return self._finish(connection, context, notebook_id)
        except CloudDatabaseError:
            raise SourceGroupsError("SOURCE_GROUPS_UNAVAILABLE", 503) from None

    def create(self, context: SourceGroupsContext, notebook_id: str, *, name: Any, idempotency_key: str) -> SourceGroupsResult:
        name = _name(name)
        c = context
        group_id = "sg-" + hashlib.sha256(
            f"{c.tenant_id}|{c.workspace_id}|{notebook_id}|{c.actor_id}|{idempotency_key}".encode("utf-8")).hexdigest()[:32]
        try:
            with self._tx(c, "source_groups.write") as connection:
                self._lock(connection, c, notebook_id)
                self._require_notebook(connection, c, notebook_id)
                existing = connection.execute(_GROUP_SQL, (c.tenant_id, c.workspace_id, group_id)).fetchone()
                if existing is not None:
                    if str(existing[0]) != notebook_id or str(existing[1]) != name:
                        raise SourceGroupsError("SOURCE_GROUP_IDEMPOTENCY_KEY_REUSED", 409)
                    view = self._view(connection, c, notebook_id)
                    return SourceGroupsResult({"group_id": group_id}, _etag(view), replayed=True)
                count, next_position = connection.execute(_COUNT_GROUPS_SQL, (c.tenant_id, c.workspace_id, notebook_id)).fetchone()
                if int(count) >= MAX_GROUPS:
                    raise SourceGroupsError("SOURCE_GROUP_LIMIT", 409)
                connection.execute(_INSERT_GROUP_SQL, (c.tenant_id, c.workspace_id, notebook_id, group_id, name,
                                                       int(next_position), c.actor_id))
                view = self._view(connection, c, notebook_id)
                return SourceGroupsResult({"group_id": group_id}, _etag(view))
        except CloudDatabaseError:
            raise SourceGroupsError("SOURCE_GROUPS_UNAVAILABLE", 503) from None

    def update(self, context: SourceGroupsContext, notebook_id: str, group_id: str, *, expected_etag: str,
               name: Any = None, position: Any = None) -> SourceGroupsResult:
        if name is None and position is None:
            raise SourceGroupsError("SOURCE_GROUP_INVALID", 422)
        new_name = None if name is None else _name(name)
        if position is not None and (type(position) is not int or not 0 <= position < MAX_GROUPS):
            raise SourceGroupsError("SOURCE_GROUP_INVALID", 422)
        c = context
        try:
            with self._tx(c, "source_groups.write") as connection:
                view = self._begin_change(connection, c, notebook_id, group_id, expected_etag)
                fields: list[str] = []
                if new_name is not None:
                    connection.execute(_RENAME_SQL, (new_name, c.tenant_id, c.workspace_id, notebook_id, group_id))
                    fields.append("name")
                if position is not None:
                    order = [g["group_id"] for g in view["groups"] if g["group_id"] != group_id]
                    order.insert(min(position, len(order)), group_id)
                    current = {g["group_id"]: g["position"] for g in view["groups"]}
                    for index, item in enumerate(order):
                        if current[item] != index:
                            connection.execute(_POSITION_SQL, (index, c.tenant_id, c.workspace_id, notebook_id, item))
                    fields.append("position")
                return self._finish(connection, c, notebook_id, fields=tuple(fields))
        except CloudDatabaseError:
            raise SourceGroupsError("SOURCE_GROUPS_UNAVAILABLE", 503) from None

    def delete(self, context: SourceGroupsContext, notebook_id: str, group_id: str, *, expected_etag: str) -> SourceGroupsResult:
        c = context
        try:
            with self._tx(c, "source_groups.write") as connection:
                view = self._begin_change(connection, c, notebook_id, group_id, expected_etag)
                released = next(len(g["source_ids"]) for g in view["groups"] if g["group_id"] == group_id)
                connection.execute(_DELETE_GROUP_SQL, (c.tenant_id, c.workspace_id, notebook_id, group_id))
                return self._finish(connection, c, notebook_id, removed=released)
        except CloudDatabaseError:
            raise SourceGroupsError("SOURCE_GROUPS_UNAVAILABLE", 503) from None

    def set_members(self, context: SourceGroupsContext, notebook_id: str, group_id: str, source_ids: Sequence[str], *,
                    expected_etag: str) -> SourceGroupsResult:
        ids = _source_ids(source_ids)
        c = context
        key = (c.tenant_id, c.workspace_id, notebook_id)
        try:
            with self._tx(c, "source_groups.write") as connection:
                self._begin_change(connection, c, notebook_id, group_id, expected_etag)
                if ids:
                    found = {str(row[0]) for row in connection.execute(_IN_NOTEBOOK_SQL, key + (c.actor_id, ids)).fetchall()}
                    if found != set(ids):
                        raise SourceGroupsError("SOURCE_NOT_IN_NOTEBOOK", 422)
                moved = int(connection.execute(_MOVED_SQL, key + (group_id, ids)).fetchone()[0]) if ids else 0
                connection.execute(_CLEAR_MEMBERS_SQL, key + (group_id, ids))
                for index, source_id in enumerate(ids):
                    connection.execute(_INSERT_MEMBER_SQL, key + (group_id, source_id, index))
                connection.execute(_TOUCH_SQL, (c.tenant_id, c.workspace_id, notebook_id, group_id))
                return self._finish(connection, c, notebook_id, moved=moved)
        except CloudDatabaseError:
            raise SourceGroupsError("SOURCE_GROUPS_UNAVAILABLE", 503) from None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceGroupCreateBody(_Strict):
    name: StrictStr = Field(max_length=400)


class SourceGroupUpdateBody(_Strict):
    name: StrictStr | None = Field(default=None, max_length=400)
    position: StrictInt | None = None


class SourceGroupMembersBody(_Strict):
    source_ids: list[StrictStr] = Field(max_length=MAX_MEMBERS)


def register_source_groups_routes(app: FastAPI, dependencies: Any, service: SourceGroupsService) -> None:
    from .authorization import Action
    from .runtime import _egress_idempotency_key, _error_response, _principal, _require_query_keys

    def _check(id: str, notebook_id: str, request: Request, action: Any, group_id: str | None = None) -> SourceGroupsContext:
        _require_query_keys(request, frozenset())
        if not _SAFE.fullmatch(id) or not _SAFE.fullmatch(notebook_id) or (group_id is not None and not _GROUP_ID.fullmatch(group_id)):
            raise HTTPException(status_code=400)
        principal = _principal(request, dependencies)
        policy_version = dependencies.settings.policy_version
        # 결정 D-11: 조회는 노트북 보기, 만들기·수정·삭제·이동은 노트북 편집 권한.
        dependencies.authorization_service.authorize_action(
            principal=principal, workspace_id=id, action=action, trace_id=request.state.trace_id, policy_version=policy_version)
        return SourceGroupsContext(principal.tenant_id, id, principal.user_id, request.state.trace_id, policy_version)

    def _fail(error: SourceGroupsError, request: Request) -> JSONResponse:
        code = error.code if error.code in SOURCE_GROUPS_PUBLIC_CODES else "INVALID_REQUEST"
        return _error_response(error.status, code, request.state.trace_id)

    def _ok(result: SourceGroupsResult, id: str, request: Request, status: int = 200, **meta: Any) -> JSONResponse:
        response = JSONResponse({"data": dict(result.data), "meta": {"trace_id": request.state.trace_id, "workspace_id": id, **meta}},
                                status_code=status)
        response.headers["ETag"] = result.etag
        response.headers["Cache-Control"] = "no-store"
        return response

    def _audit(context: SourceGroupsContext, notebook_id: str, action: str, metadata: Mapping[str, Any]) -> None:
        # 묶음 ID와 개수만 남긴다(묶음 이름·소스 제목은 남기지 않는다).
        dependencies.audit_store.append(AuditEventDraft(
            event_id="sg-" + secrets.token_hex(16), occurred_at=datetime.now(timezone.utc), actor_id=context.actor_id,
            actor_type=ActorType.USER, tenant_id=context.tenant_id, workspace_id=context.workspace_id,
            action="notebook.source_group." + action, target_type="notebook", target_id=notebook_id,
            outcome=AuditOutcome.SUCCEEDED, trace_id=context.trace_id, policy_version=context.policy_version,
            metadata=dict(metadata)))

    base = "/api/v1/workspaces/{id}/notebooks/{notebook_id}/source-groups"

    @app.get(base)
    async def list_source_groups(id: str, notebook_id: str, request: Request) -> JSONResponse:
        context = _check(id, notebook_id, request, Action.VIEW)
        try:
            result = await asyncio.to_thread(service.list, context, notebook_id)
        except SourceGroupsError as error:
            return _fail(error, request)
        return _ok(result, id, request)

    @app.post(base, status_code=201)
    async def create_source_group(id: str, notebook_id: str, body: SourceGroupCreateBody, request: Request,
                                  idempotency_key: str = Header(alias="Idempotency-Key")) -> JSONResponse:
        _egress_idempotency_key(idempotency_key)
        context = _check(id, notebook_id, request, Action.EDIT)
        try:
            result = await asyncio.to_thread(service.create, context, notebook_id, name=body.name, idempotency_key=idempotency_key)
        except SourceGroupsError as error:
            return _fail(error, request)
        if not result.replayed:
            _audit(context, notebook_id, "create", {"group_id": result.data["group_id"]})
        return _ok(result, id, request, status=200 if result.replayed else 201, replayed=result.replayed)

    @app.patch(base + "/{group_id}")
    async def update_source_group(id: str, notebook_id: str, group_id: str, body: SourceGroupUpdateBody, request: Request,
                                  if_match: str = Header(alias="If-Match")) -> JSONResponse:
        context = _check(id, notebook_id, request, Action.EDIT, group_id)
        sent = body.model_fields_set
        try:
            result = await asyncio.to_thread(
                service.update, context, notebook_id, group_id, expected_etag=if_match,
                name=body.name if "name" in sent else None, position=body.position if "position" in sent else None)
        except SourceGroupsError as error:
            return _fail(error, request)
        _audit(context, notebook_id, "update", {"group_id": group_id, "fields": list(result.fields)})
        return _ok(result, id, request)

    @app.delete(base + "/{group_id}")
    async def delete_source_group(id: str, notebook_id: str, group_id: str, request: Request,
                                  if_match: str = Header(alias="If-Match")) -> JSONResponse:
        context = _check(id, notebook_id, request, Action.EDIT, group_id)
        try:
            result = await asyncio.to_thread(service.delete, context, notebook_id, group_id, expected_etag=if_match)
        except SourceGroupsError as error:
            return _fail(error, request)
        _audit(context, notebook_id, "delete", {"group_id": group_id, "released_count": result.removed})
        return _ok(result, id, request)

    @app.put(base + "/{group_id}/members")
    async def set_source_group_members(id: str, notebook_id: str, group_id: str, body: SourceGroupMembersBody, request: Request,
                                       if_match: str = Header(alias="If-Match")) -> JSONResponse:
        context = _check(id, notebook_id, request, Action.EDIT, group_id)
        try:
            result = await asyncio.to_thread(service.set_members, context, notebook_id, group_id, body.source_ids,
                                             expected_etag=if_match)
        except SourceGroupsError as error:
            return _fail(error, request)
        _audit(context, notebook_id, "members", {"group_id": group_id, "source_count": len(body.source_ids),
                                                 "moved_count": result.moved})
        return _ok(result, id, request)
