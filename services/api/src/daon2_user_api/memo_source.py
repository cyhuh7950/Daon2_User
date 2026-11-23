"""메모를 소스로 쓰기(WO-N1 N1-3, NB1-F2, 결정 D-10).

- 만들기: 메모의 현재 리비전 본문을 텍스트 소스로 등록하고(text_source) memo_source_links에 연결을 남긴다.
- 반영: 메모를 고친 뒤 "소스에 반영"을 눌렀을 때만, 고친 본문으로 새 소스를 만들고(만들기와 같은 업로드·문서 처리 경로)
  한 트랜잭션에서 이전 소스를 노트북에서 떼고(notebook_postgres.unbind_source와 같은 기록) 링크를 새 소스로 옮긴다.
  notebook_bindings는 소스당 한 줄·추가 전용이라, 같은 source_id에 새 버전을 붙이면 새 버전이 연결되지 않고
  소스가 목록에서 사라진다(NB1-I2 실서버 확인). 이전 소스를 쓴 스튜디오 산출물은 기존 _STALE_SQL의
  "노트북에서 뗌" 조건으로 "소스가 변경됨"이 된다.
- 메모를 지워도 소스와 연결은 남긴다(목록에는 memo_exists=false).
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from psycopg.types.json import Jsonb

from .cloud_storage import CloudAccessContext
from .studio_workspace import StudioContext, StudioError
from .text_source import TextSourceError

MEMO_SOURCE_ORIGIN = "memo"

# 링크의 소스가 이 노트북에서 아직 쓰이는지: 최신 버전이 연결돼 있고 떼지 않았으며 삭제되지 않았다.
_ACTIVE_SQL = (
    "(EXISTS(SELECT 1 FROM source_versions sv JOIN notebook_bindings b ON b.tenant_id=sv.tenant_id "
    "AND b.workspace_id=sv.workspace_id AND b.notebook_id=l.notebook_id AND b.binding_kind='source' "
    "AND b.record_id=sv.source_id AND b.version_id=sv.record_id "
    "WHERE sv.tenant_id=l.tenant_id AND sv.workspace_id=l.workspace_id AND sv.source_id=l.source_id "
    "AND NOT EXISTS(SELECT 1 FROM source_versions nv WHERE nv.tenant_id=sv.tenant_id AND nv.workspace_id=sv.workspace_id "
    "AND nv.source_id=sv.source_id AND nv.version>sv.version) "
    "AND NOT EXISTS(SELECT 1 FROM notebook_source_unbindings u WHERE u.tenant_id=b.tenant_id AND u.workspace_id=b.workspace_id "
    "AND u.notebook_id=b.notebook_id AND u.source_id=b.record_id AND u.source_version_id=b.version_id)) "
    "AND NOT EXISTS(SELECT 1 FROM deletion_requests d WHERE d.tenant_id=l.tenant_id AND d.workspace_id=l.workspace_id "
    "AND d.source_id=l.source_id AND d.source_active=false))")
_MEMO_SQL = (
    "SELECT o.type_id,o.title,o.current_revision,r.content_json FROM studio_v2_outputs o LEFT JOIN studio_v2_revisions r "
    "ON r.tenant_id=o.tenant_id AND r.workspace_id=o.workspace_id AND r.output_id=o.output_id AND r.revision_no=o.current_revision "
    "WHERE o.tenant_id=%s AND o.workspace_id=%s AND o.output_id=%s AND o.notebook_id=%s AND o.deleted_at IS NULL")
_LINK_SQL = (
    "SELECT l.source_id,l.reflected_revision_no," + _ACTIVE_SQL + " FROM memo_source_links l "
    "WHERE l.tenant_id=%s AND l.workspace_id=%s AND l.memo_output_id=%s")
_INSERT_LINK_SQL = (
    "INSERT INTO memo_source_links(tenant_id,workspace_id,notebook_id,memo_output_id,source_id,reflected_revision_no,created_by) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING source_id")
_REPLACE_LINK_SQL = (
    "UPDATE memo_source_links SET source_id=%s,reflected_revision_no=%s,created_by=%s,updated_at=now() "
    "WHERE tenant_id=%s AND workspace_id=%s AND memo_output_id=%s AND source_id=%s RETURNING 1")
# 반영 트랜잭션. sources·source_versions·notebook_bindings·notebook_source_unbindings는 앱 역할에 UPDATE가 없으므로
# UPDATE도 SELECT … FOR UPDATE도 쓰지 않는다. 직렬화는 unbind_source와 같은 노트북 advisory lock으로 한다.
_UNBIND_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))"
_LINK_ROW_SQL = ("SELECT source_id,reflected_revision_no FROM memo_source_links "
                 "WHERE tenant_id=%s AND workspace_id=%s AND memo_output_id=%s")
_CURRENT_BINDING_SQL = (
    "SELECT b.version_id FROM notebook_bindings b WHERE b.tenant_id=%s AND b.workspace_id=%s AND b.notebook_id=%s "
    "AND b.binding_kind='source' AND b.record_id=%s "
    "AND NOT EXISTS (SELECT 1 FROM notebook_source_unbindings u WHERE u.tenant_id=b.tenant_id AND u.workspace_id=b.workspace_id "
    "AND u.notebook_id=b.notebook_id AND u.source_id=b.record_id AND u.source_version_id=b.version_id)")
_UNBINDING_COUNT_SQL = ("SELECT count(*) FROM notebook_source_unbindings "
                        "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s")
_INSERT_UNBINDING_SQL = (
    "INSERT INTO notebook_source_unbindings (tenant_id,workspace_id,notebook_id,source_id,source_version_id,binding_version,"
    "actor_id,occurred_at) VALUES (%s,%s,%s,%s,%s,%s,%s,now())")
_NEXT_ACTIVITY_SQL = ("SELECT coalesce(max(sequence),0)+1 FROM notebook_activities "
                      "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s")
_INSERT_ACTIVITY_SQL = (
    "INSERT INTO notebook_activities (tenant_id,workspace_id,notebook_id,sequence,activity_kind,actor_id,occurred_at) "
    "VALUES (%s,%s,%s,%s,'context_unbound',%s,now())")
_INSERT_AUDIT_SQL = (
    "INSERT INTO audit_events (event_id,tenant_id,workspace_id,actor_id,action,target_type,target_id,outcome,trace_id,"
    "policy_version,after_value,metadata) VALUES (%s,%s,%s,%s,'notebook.source_unbound','notebook',%s,'succeeded',%s,%s,%s,%s)")
_REFLECT_LINK_SQL = (
    "UPDATE memo_source_links SET source_id=%s,reflected_revision_no=%s,updated_at=now() "
    "WHERE tenant_id=%s AND workspace_id=%s AND memo_output_id=%s AND source_id=%s AND reflected_revision_no=%s RETURNING 1")
_SOURCE_STATE_SQL = "SELECT state FROM sources WHERE tenant_id=%s AND workspace_id=%s AND record_id=%s"
_ORIGINS_SQL = (
    "SELECT l.source_id,l.memo_output_id,EXISTS(SELECT 1 FROM studio_v2_outputs o WHERE o.tenant_id=l.tenant_id "
    "AND o.workspace_id=l.workspace_id AND o.output_id=l.memo_output_id AND o.deleted_at IS NULL) "
    "FROM memo_source_links l WHERE l.tenant_id=%s AND l.workspace_id=%s AND l.notebook_id=%s")

# 텍스트 소스 오류 → 메모 공개 코드(만들기·반영 공통: 반영도 register_text_source로 새 소스를 만든다)
_CREATE_ERRORS = {"TEXT_SOURCE_EMPTY": ("MEMO_EMPTY", 422), "TEXT_SOURCE_TOO_LARGE": ("MEMO_TOO_LARGE", 413),
                  "TEXT_SOURCE_INPUT_INVALID": ("STUDIO_INPUT_INVALID", 400)}


def _markdown(content: object) -> str:
    body = content.get("body") if isinstance(content, Mapping) else None
    value = body.get("markdown") if isinstance(body, Mapping) else None
    return value if isinstance(value, str) else ""


class MemoSourceService:
    def __init__(self, cloud_store: Any, text_sources: Any) -> None:
        self._cloud_store = cloud_store
        self._text_sources = text_sources

    @staticmethod
    def _cloud(context: StudioContext, capability: str) -> CloudAccessContext:
        return CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, capability)

    @staticmethod
    def _notebook(context: StudioContext) -> str:
        if not context.notebook_id:
            raise StudioError("NOTEBOOK_SCOPE_REQUIRED", 400)
        return context.notebook_id

    @staticmethod
    def _translate(error: TextSourceError, table: Mapping[str, tuple[str, int]]) -> StudioError:
        code, status = table.get(error.code, ("STUDIO_INPUT_INVALID", 400))
        return StudioError(code, status)

    def _read(self, connection: Any, context: StudioContext, output_id: str) -> tuple[Any, Any]:
        """(링크, 메모) 순서로 읽는다. 메모가 없거나 지워졌으면 404, 메모가 아니면 422."""
        scope = (context.tenant_id, context.workspace_id)
        link = connection.execute(_LINK_SQL, (*scope, output_id)).fetchone()
        memo = connection.execute(_MEMO_SQL, (*scope, output_id, self._notebook(context))).fetchone()
        if memo is None:
            raise StudioError("STUDIO_OUTPUT_NOT_FOUND", 404)
        if memo[0] != "memo":
            raise StudioError("OUTPUT_NOT_MEMO", 422)
        return link, memo

    def create(self, context: StudioContext, output_id: str) -> dict[str, object]:
        notebook_id = self._notebook(context)
        scope = (context.tenant_id, context.workspace_id)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            link, memo = self._read(connection, context, output_id)
        if link is not None and bool(link[2]):
            raise StudioError("MEMO_SOURCE_EXISTS", 409)
        title, revision, markdown = str(memo[1]), int(memo[2]), _markdown(memo[3])
        if not markdown.strip():
            raise StudioError("MEMO_EMPTY", 422)
        previous = None if link is None else str(link[0])
        try:
            source_id, version_id = self._text_sources.register_text_source(
                context, notebook_id, title=title, text=markdown, origin=MEMO_SOURCE_ORIGIN,
                idempotency_key=f"memo-source:{output_id}:{previous or 'new'}")
        except TextSourceError as error:
            raise self._translate(error, _CREATE_ERRORS) from None
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            if previous is None:
                inserted = connection.execute(_INSERT_LINK_SQL, (*scope, notebook_id, output_id, source_id, revision,
                                                                 context.actor_id)).fetchone()
                if inserted is None:
                    current = connection.execute(_LINK_SQL, (*scope, output_id)).fetchone()
                    if current is None or str(current[0]) != source_id:
                        raise StudioError("MEMO_SOURCE_EXISTS", 409)
            elif connection.execute(_REPLACE_LINK_SQL, (source_id, revision, context.actor_id, *scope, output_id,
                                                        previous)).fetchone() is None:
                raise StudioError("MEMO_SOURCE_EXISTS", 409)
            state = connection.execute(_SOURCE_STATE_SQL, (*scope, source_id)).fetchone()
        return {"source_id": source_id, "source_version_id": version_id,
                "state": "registered" if state is None else str(state[0]), "revision_no": revision}

    def reflect(self, context: StudioContext, output_id: str) -> dict[str, object]:
        self._notebook(context)
        scope = (context.tenant_id, context.workspace_id)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            link, memo = self._read(connection, context, output_id)
        if link is None or not bool(link[2]):
            raise StudioError("MEMO_SOURCE_NOT_LINKED", 404)
        source_id, reflected, revision = str(link[0]), int(link[1]), int(memo[2])
        if revision == reflected:
            raise StudioError("MEMO_SOURCE_UNCHANGED", 409)
        markdown = _markdown(memo[3])
        if not markdown.strip():
            raise StudioError("MEMO_EMPTY", 422)

        notebook_id = str(context.notebook_id)
        try:
            new_source, new_version = self._text_sources.register_text_source(
                context, notebook_id, title=str(memo[1]), text=markdown, origin=MEMO_SOURCE_ORIGIN,
                idempotency_key=f"memo-reflect:{output_id}:{revision}")
        except TextSourceError as error:
            raise self._translate(error, _CREATE_ERRORS) from None
        result: dict[str, object] = {"source_id": new_source, "source_version_id": new_version, "revision_no": revision}
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            connection.execute(_UNBIND_LOCK_SQL, (f"unbind-notebook|{context.tenant_id}|{context.workspace_id}|{notebook_id}",))
            current = connection.execute(_LINK_ROW_SQL, (*scope, output_id)).fetchone()
            state = None if current is None else (str(current[0]), int(current[1]))
            if state == (new_source, revision):
                return result          # 같은 키의 다른 요청이 이미 반영을 끝냈다
            if state != (source_id, reflected):
                raise StudioError("MEMO_SOURCE_UNCHANGED", 409)      # 다른 리비전이 먼저 반영됐다
            self._unbind_previous(connection, context, notebook_id, source_id, output_id, revision)
            if connection.execute(_REFLECT_LINK_SQL, (new_source, revision, *scope, output_id, source_id,
                                                      reflected)).fetchone() is None:
                raise StudioError("MEMO_SOURCE_UNCHANGED", 409)      # 떼기 기록까지 트랜잭션 전체를 되돌린다
        return result

    @staticmethod
    def _unbind_previous(connection: Any, context: StudioContext, notebook_id: str, source_id: str, output_id: str,
                         revision: int) -> None:
        """이전 소스의 현재 연결을 notebook_postgres.unbind_source와 같은 방식으로 뗀다. 이미 뗐으면 아무것도 안 한다.

        unbinding_idempotency는 쓰지 않는다. 이 경로의 멱등은 memo_source_links 조건부 갱신이 보장한다.
        """
        scope = (context.tenant_id, context.workspace_id)
        binding = connection.execute(_CURRENT_BINDING_SQL, (*scope, notebook_id, source_id)).fetchone()
        if binding is None:
            return
        version_id = str(binding[0])
        binding_version = 1 + int(connection.execute(_UNBINDING_COUNT_SQL, (*scope, notebook_id)).fetchone()[0]) + 1
        connection.execute(_INSERT_UNBINDING_SQL, (*scope, notebook_id, source_id, version_id, binding_version,
                                                   context.actor_id))
        sequence = int(connection.execute(_NEXT_ACTIVITY_SQL, (*scope, notebook_id)).fetchone()[0])
        connection.execute(_INSERT_ACTIVITY_SQL, (*scope, notebook_id, sequence, context.actor_id))
        event_id = "notebook-audit-" + hashlib.sha256(
            f"memo-reflect|{context.tenant_id}|{context.workspace_id}|{output_id}|{revision}".encode()).hexdigest()[:24]
        connection.execute(_INSERT_AUDIT_SQL, (event_id, *scope, context.actor_id, notebook_id, context.trace_id,
                                               context.policy_version, Jsonb({"binding_version": binding_version}),
                                               Jsonb({"reason_code": "MEMO_SOURCE_REFLECTED"})))

    def source_link(self, context: StudioContext, output_id: str, current_revision: object) -> dict[str, object] | None:
        """메모 조회 응답의 source_link. 연결이 없거나 소스를 노트북에서 뗐으면 None."""
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            link = connection.execute(_LINK_SQL, (context.tenant_id, context.workspace_id, output_id)).fetchone()
        if link is None or not bool(link[2]):
            return None
        reflected = int(link[1])
        return {"source_id": str(link[0]), "reflected_revision_no": reflected,
                "outdated": isinstance(current_revision, int) and current_revision != reflected}

    def memo_origins(self, context: StudioContext) -> dict[str, dict[str, object]]:
        """소스 목록의 memo_origin. source_id → {memo_output_id, memo_exists}."""
        notebook_id = self._notebook(context)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            rows = connection.execute(_ORIGINS_SQL, (context.tenant_id, context.workspace_id, notebook_id)).fetchall()
        return {str(row[0]): {"memo_output_id": str(row[1]), "memo_exists": bool(row[2])} for row in rows}
