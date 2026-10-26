"""노트북 복사와 채팅 기록 비움(WO-F3, F3-02·F3-03).

- 복사: 새 Notebook을 만들고 Source는 **같은 Source 버전을 새로 연결(binding)**, 메모·산출물은 완료된 것의 최신 리비전만 새 `output_id`로 복제한다.
  채팅·학습 시도·작업(job)은 복사하지 않는다. 요청자가 볼 수 없는 Source(접근 거부)와 그 Source에 기대는 산출물은 건너뛰고 건수를 알린다.
- 채팅 기록 비움: 요청자 본인의 비움 시각만 기록한다(`notebook_chat_clears`). 실행 기록(`runs`)은 비용·감사 근거라서 지우지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from psycopg.types.json import Jsonb

from .cloud_storage import CloudAccessContext, CloudDatabaseError, PostgresCloudStore
from .notebook import NotebookContext, NotebookError

MAX_SOURCES = 100
MAX_OUTPUTS = 200
_KEY = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class NotebookCopyService:
    def __init__(self, store: PostgresCloudStore, *, creation_enforcer=None, clock=None) -> None:  # type: ignore[no-untyped-def]
        self._store = store
        self._creation_enforcer = creation_enforcer
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _scope(context: NotebookContext) -> CloudAccessContext:
        return CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, "notebook.read_or_write")

    # ------------------------------------------------------------------ 채팅 기록 비움
    def clear_chat_history(self, context: NotebookContext, notebook_id: str) -> None:
        try:
            with self._store._transaction(self._scope(context)) as connection:
                active = connection.execute(
                    "SELECT 1 FROM notebooks n WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND NOT EXISTS("
                    "SELECT 1 FROM notebook_deletion_requests d WHERE d.tenant_id=n.tenant_id AND d.workspace_id=n.workspace_id "
                    "AND d.notebook_id=n.notebook_id AND d.state IN ('accepted','deleting','completed'))",
                    (context.tenant_id, context.workspace_id, notebook_id)).fetchone()
                if active is None:
                    raise NotebookError("NOTEBOOK_NOT_FOUND", 404)
                connection.execute(
                    "INSERT INTO notebook_chat_clears(tenant_id,workspace_id,notebook_id,user_id,cleared_at) VALUES (%s,%s,%s,%s,clock_timestamp()) "
                    "ON CONFLICT (tenant_id,workspace_id,notebook_id,user_id) DO UPDATE SET cleared_at=clock_timestamp()",
                    (context.tenant_id, context.workspace_id, notebook_id, context.actor_id))
                self._audit(connection, context, "notebook.chat_history.clear", notebook_id, _sha(f"clear|{notebook_id}|{self._clock().isoformat()}")[:24], {})
        except NotebookError:
            raise
        except CloudDatabaseError as error:
            raise NotebookError("NOTEBOOK_UNAVAILABLE", 503) from error

    def list_chat_turns(self, context: NotebookContext, notebook_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """요청자 본인의 질문·답변·실패를 시간순으로 돌려준다. 비움 시각 이후만, 접근이 막힌 근거의 답변은 내용을 숨긴다."""
        limit = max(1, min(int(limit), 200))
        try:
            with self._store._transaction(self._scope(context)) as connection:
                if connection.execute(
                    "SELECT 1 FROM notebooks WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s",
                    (context.tenant_id, context.workspace_id, notebook_id)).fetchone() is None:
                    raise NotebookError("NOTEBOOK_NOT_FOUND", 404)
                rows = connection.execute(
                    "SELECT r.record_id,r.created_at,r.state,r.canonical_json,rr.record_id,rr.canonical_json,"
                    "(EXISTS (SELECT 1 FROM citations bc JOIN deletion_requests dr ON dr.tenant_id=bc.tenant_id "
                    "AND dr.workspace_id=bc.workspace_id AND dr.source_id=bc.canonical_json->>'source_id' "
                    "AND dr.source_active=false WHERE bc.tenant_id=rr.tenant_id AND bc.workspace_id=rr.workspace_id "
                    "AND bc.run_result_id=rr.record_id) OR EXISTS (SELECT 1 FROM identity_auth_source_access a "
                    "WHERE a.tenant_id=r.tenant_id AND a.workspace_id=r.workspace_id AND a.user_id=%s AND a.allowed=0 "
                    "AND (a.source_version_id=r.canonical_json->>'source_version_id' OR EXISTS (SELECT 1 FROM citations dc "
                    "WHERE dc.tenant_id=rr.tenant_id AND dc.workspace_id=rr.workspace_id AND dc.run_result_id=rr.record_id "
                    "AND dc.source_version_id=a.source_version_id))))  "
                    "FROM notebook_bindings nb JOIN runs r ON r.tenant_id=nb.tenant_id AND r.workspace_id=nb.workspace_id "
                    "AND r.conversation_id=nb.record_id AND r.created_by=%s AND r.state IN ('completed','failed') "
                    "LEFT JOIN run_results rr ON rr.tenant_id=r.tenant_id AND rr.workspace_id=r.workspace_id AND rr.run_id=r.record_id "
                    "WHERE nb.tenant_id=%s AND nb.workspace_id=%s AND nb.notebook_id=%s AND nb.binding_kind='conversation_thread' "
                    "AND r.created_at>COALESCE((SELECT k.cleared_at FROM notebook_chat_clears k WHERE k.tenant_id=r.tenant_id "
                    "AND k.workspace_id=r.workspace_id AND k.notebook_id=nb.notebook_id AND k.user_id=%s),'-infinity'::timestamptz) "
                    "ORDER BY r.created_at DESC,r.record_id DESC LIMIT %s",
                    (context.actor_id, context.actor_id, context.tenant_id, context.workspace_id, notebook_id,
                     context.actor_id, limit)).fetchall()
                result_ids = [str(row[4]) for row in rows if row[4] is not None and not row[6]]
                citation_rows = connection.execute(
                    "SELECT run_result_id,record_id,canonical_json FROM citations WHERE tenant_id=%s AND workspace_id=%s "
                    "AND run_result_id=ANY(%s) ORDER BY record_id",
                    (context.tenant_id, context.workspace_id, result_ids)).fetchall() if result_ids else []
        except NotebookError:
            raise
        except CloudDatabaseError as error:
            raise NotebookError("NOTEBOOK_UNAVAILABLE", 503) from error
        citations: dict[str, list[dict[str, Any]]] = {}
        for result_id, citation_id, payload in citation_rows:
            data = dict(payload)
            citations.setdefault(str(result_id), []).append({
                "citation_id": str(citation_id), "source_id": data.get("source_id"),
                "source_version_id": data.get("source_version_id"), "evidence_span_id": data.get("evidence_span_id"),
                "page": data.get("page"), "origin": data.get("origin", "raw_source"),
                "context_item_id": data.get("context_item_id", data.get("source_version_id")),
                "locator": data.get("locator") or {"kind": "page", "value": str(data.get("page"))},
            })
        turns: list[dict[str, Any]] = []
        for run_id, created_at, state, run_json, result_id, result_json, blocked in reversed(rows):
            run_payload = dict(run_json or {})
            turn: dict[str, Any] = {
                "run_id": str(run_id), "created_at": created_at.isoformat(), "state": str(state),
                "question": str(run_payload.get("question") or ""), "context_mode": str(run_payload.get("context_mode") or "raw_only"),
                "answer": None, "unavailable": bool(blocked),
            }
            if result_id is not None and result_json is not None and not blocked:
                payload = dict(result_json)
                turn["answer"] = {
                    "run_id": str(run_id), "run_result_id": str(result_id), "answer": str(payload.get("answer") or ""),
                    "insufficient": bool(payload.get("insufficient")), "citations": citations.get(str(result_id), []),
                }
            turns.append(turn)
        return turns

    # ------------------------------------------------------------------ 복사
    def copy(self, context: NotebookContext, notebook_id: str, *, title: str | None, include: Mapping[str, bool], idempotency_key: str) -> dict[str, Any]:
        if not _KEY.fullmatch(idempotency_key or ""):
            raise NotebookError("IDEMPOTENCY_KEY_INVALID", 400)
        options = {k: bool(include.get(k, k != "sources")) for k in ("sources", "memos", "outputs", "customization")}
        clean_title = title.strip() if isinstance(title, str) else None
        if clean_title is not None and not 1 <= len(clean_title) <= 160:
            raise NotebookError("NOTEBOOK_TITLE_INVALID", 400)
        fingerprint = _sha(json.dumps({"n": notebook_id, "t": clean_title, "i": options}, sort_keys=True, ensure_ascii=False))
        key_hash = _sha(idempotency_key)
        try:
            with self._store._transaction(self._scope(context)) as connection:
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                                   (f"{context.tenant_id}|{context.workspace_id}|{context.actor_id}|copy|{key_hash}",))
                previous = connection.execute(
                    "SELECT request_fingerprint,result_json FROM notebook_copy_requests WHERE tenant_id=%s AND workspace_id=%s AND actor_id=%s AND idempotency_key_sha256=%s",
                    (context.tenant_id, context.workspace_id, context.actor_id, key_hash)).fetchone()
                if previous is not None:
                    if previous[0] != fingerprint:
                        raise NotebookError("IDEMPOTENCY_KEY_REUSED", 409)
                    return {**dict(previous[1]), "replayed": True}
                source = connection.execute(
                    "SELECT m.title,m.description FROM notebooks n JOIN notebook_metadata_versions m ON m.tenant_id=n.tenant_id AND m.workspace_id=n.workspace_id "
                    "AND m.notebook_id=n.notebook_id AND m.is_current WHERE n.tenant_id=%s AND n.workspace_id=%s AND n.notebook_id=%s AND NOT EXISTS("
                    "SELECT 1 FROM notebook_deletion_requests d WHERE d.tenant_id=n.tenant_id AND d.workspace_id=n.workspace_id AND d.notebook_id=n.notebook_id "
                    "AND d.state IN ('accepted','deleting','completed'))", (context.tenant_id, context.workspace_id, notebook_id)).fetchone()
                if source is None:
                    raise NotebookError("NOTEBOOK_NOT_FOUND", 404)
                if self._creation_enforcer is not None:
                    self._creation_enforcer(connection, context.tenant_id, "notebook.create", {"notebooks": 1})
                now = self._clock()
                new_id = "notebook-" + _sha(f"copy|{context.tenant_id}|{context.workspace_id}|{context.actor_id}|{idempotency_key}")[:32]
                new_title = clean_title or f"{source[0]} 사본"[:160]
                connection.execute("INSERT INTO notebooks (tenant_id,workspace_id,notebook_id,created_by,created_at) VALUES (%s,%s,%s,%s,%s)",
                                   (context.tenant_id, context.workspace_id, new_id, context.actor_id, now))
                connection.execute(
                    "INSERT INTO notebook_metadata_versions (tenant_id,workspace_id,notebook_id,version,title,description,is_current,updated_by,updated_at) "
                    "VALUES (%s,%s,%s,1,%s,%s,true,%s,%s)", (context.tenant_id, context.workspace_id, new_id, new_title, source[1], context.actor_id, now))
                connection.execute(
                    "INSERT INTO notebook_activities (tenant_id,workspace_id,notebook_id,sequence,activity_kind,actor_id,occurred_at) VALUES (%s,%s,%s,1,'created',%s,%s)",
                    (context.tenant_id, context.workspace_id, new_id, context.actor_id, now))
                copied = {"sources": 0, "memos": 0, "outputs": 0, "customization": 0}
                skipped = {"sources": 0, "memos": 0, "outputs": 0}
                denied = self._denied_versions(connection, context)
                sequence = 1
                bound_sources = connection.execute(
                    "SELECT count(*) FROM notebook_bindings b WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND binding_kind='source' "
                    "AND NOT EXISTS (SELECT 1 FROM notebook_source_unbindings u WHERE u.tenant_id=b.tenant_id AND u.workspace_id=b.workspace_id "
                    "AND u.notebook_id=b.notebook_id AND u.source_id=b.record_id AND u.source_version_id=b.version_id)",
                    (context.tenant_id, context.workspace_id, notebook_id)).fetchone()[0]
                # Source 복사는 결정 대기: 노트북 삭제 함수가 Notebook 간 공유 Source를 막아(DELETE_SHARED_DATA_BLOCKED) 연결 복사를 쓸 수 없다.
                # Source를 복제하는 방식이 정해질 때까지 Source가 있는 노트북에서 Source 포함 복사는 거부한다.
                if options["sources"] and bound_sources:
                    raise NotebookError("NOTEBOOK_COPY_SOURCES_UNSUPPORTED", 409)
                skipped["sources"] = int(bound_sources)
                if options["memos"] or options["outputs"]:
                    outputs = connection.execute(
                        "SELECT output_id,type_id,format_id,title,settings_json,source_version_ids,current_revision FROM studio_v2_outputs "
                        "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND deleted_at IS NULL AND status='completed' AND current_revision>0 ORDER BY created_at",
                        (context.tenant_id, context.workspace_id, notebook_id)).fetchall()
                    wanted = [o for o in outputs if (o[1] == "memo" and options["memos"]) or (o[1] != "memo" and options["outputs"])]
                    if len(wanted) > MAX_OUTPUTS:
                        raise NotebookError("NOTEBOOK_COPY_TOO_LARGE", 409)
                    for output_id, type_id, format_id, out_title, settings, versions, revision in wanted:
                        bucket = "memos" if type_id == "memo" else "outputs"
                        if any(v in denied for v in versions or ()) or versions:  # 원본 Source가 새 노트북에 없으면 근거를 볼 수 없으므로 건너뛴다
                            skipped[bucket] += 1
                            continue
                        self._copy_output(connection, context, new_id, output_id, type_id, format_id, out_title, settings, versions, revision, idempotency_key)
                        copied[bucket] += 1
                if options["customization"]:
                    row = connection.execute(
                        "SELECT instruction FROM workspace_studio_v2_customization WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s",
                        (context.tenant_id, context.workspace_id, notebook_id)).fetchone()
                    if row is not None and row[0]:
                        connection.execute(
                            "INSERT INTO workspace_studio_v2_customization(tenant_id,workspace_id,notebook_id,instruction,version,updated_by) VALUES (%s,%s,%s,%s,1,%s)",
                            (context.tenant_id, context.workspace_id, new_id, row[0], context.actor_id))
                        copied["customization"] = 1
                result = {"notebook_id": new_id, "title": new_title, "copied": copied, "skipped": skipped}
                connection.execute(
                    "INSERT INTO notebook_copy_requests(tenant_id,workspace_id,actor_id,idempotency_key_sha256,request_fingerprint,source_notebook_id,new_notebook_id,result_json) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (context.tenant_id, context.workspace_id, context.actor_id, key_hash, fingerprint, notebook_id, new_id, Jsonb(result)))
                self._audit(connection, context, "notebook.copy", new_id, key_hash[:24], {"source_notebook_id": notebook_id, **{f"copied_{k}": v for k, v in copied.items()}})
                return {**result, "replayed": False}
        except NotebookError:
            raise
        except CloudDatabaseError as error:
            raise NotebookError("NOTEBOOK_UNAVAILABLE", 503) from error

    @staticmethod
    def _denied_versions(connection, context: NotebookContext) -> set[str]:  # type: ignore[no-untyped-def]
        rows = connection.execute(
            "SELECT source_version_id FROM identity_auth_source_access WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s AND allowed=0",
            (context.tenant_id, context.workspace_id, context.actor_id)).fetchall()
        return {str(r[0]) for r in rows}

    @staticmethod
    def _copy_output(connection, context, new_notebook_id, output_id, type_id, format_id, title, settings, versions, revision, key) -> None:  # type: ignore[no-untyped-def]
        new_output = "sv2-" + _sha(f"copy|{new_notebook_id}|{output_id}")[:32]
        connection.execute(
            "INSERT INTO studio_v2_outputs(tenant_id,workspace_id,output_id,notebook_id,owner_actor_id,type_id,format_id,title,status,settings_json,source_version_ids,"
            "current_revision,idempotency_key_sha256,request_fingerprint) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'completed',%s,%s,1,%s,%s)",
            (context.tenant_id, context.workspace_id, new_output, new_notebook_id, context.actor_id, type_id, format_id, title, Jsonb(settings), list(versions or ()),
             _sha(f"copy-output|{key}|{output_id}"), "copy"))
        connection.execute(
            "INSERT INTO studio_v2_revisions(tenant_id,workspace_id,output_id,revision_no,revision_type,content_json,content_sha256,warnings_json,generated_with,created_by) "
            "SELECT tenant_id,workspace_id,%s,1,revision_type,content_json,content_sha256,warnings_json,generated_with,%s FROM studio_v2_revisions "
            "WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s",
            (new_output, context.actor_id, context.tenant_id, context.workspace_id, output_id, revision))
        connection.execute(
            "INSERT INTO studio_v2_sources(tenant_id,workspace_id,output_id,revision_no,source_version_id,source_id,content_digest_sha256) "
            "SELECT tenant_id,workspace_id,%s,1,source_version_id,source_id,content_digest_sha256 FROM studio_v2_sources WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s",
            (new_output, context.tenant_id, context.workspace_id, output_id, revision))
        connection.execute(
            "INSERT INTO studio_v2_evidence(tenant_id,workspace_id,output_id,revision_no,ref_id,source_version_id,evidence_span_id,locator_kind,locator_value,quote_sha256,origin,external_ref) "
            "SELECT tenant_id,workspace_id,%s,1,ref_id,source_version_id,evidence_span_id,locator_kind,locator_value,quote_sha256,origin,external_ref FROM studio_v2_evidence "
            "WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s",
            (new_output, context.tenant_id, context.workspace_id, output_id, revision))

    @staticmethod
    def _audit(connection, context: NotebookContext, action: str, target_id: str, suffix: str, metadata: Mapping[str, Any]) -> None:  # type: ignore[no-untyped-def]
        connection.execute(
            "INSERT INTO audit_events (event_id,tenant_id,workspace_id,actor_id,action,target_type,target_id,outcome,trace_id,policy_version,after_value,metadata) "
            "VALUES (%s,%s,%s,%s,%s,'notebook',%s,'succeeded',%s,%s,%s,%s)",
            ("notebook-audit-" + _sha(f"{action}|{context.tenant_id}|{context.actor_id}|{suffix}")[:24], context.tenant_id, context.workspace_id, context.actor_id,
             action, target_id, context.trace_id, context.policy_version, Jsonb({}), Jsonb(dict(metadata))))
