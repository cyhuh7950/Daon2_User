"""Studio v2 저장소(별도 studio_v2_* 테이블). WO-F1 T1-06."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from psycopg.types.json import Jsonb

from .cloud_storage import CloudAccessContext
from .studio_v2_types import STUDIO_V2_TYPES, is_available, validate_settings
from .studio_workspace import StudioContext, StudioError
from .studio_workspace_postgres import PostgresStudioWorkspaceRepository

MAX_REVISION_BYTES = 2 * 1024 * 1024
MAX_ASSET_BYTES = 32 * 1024 * 1024  # 10분 mp3(128kbps) 약 10 MiB의 여유
MAX_LIST_LIMIT = 50
TYPE_LABELS = {
    "report": "보고서", "data_table": "데이터 표", "mind_map": "마인드맵", "flashcards": "플래시카드",
    "quiz": "퀴즈", "slides": "슬라이드 자료", "infographic": "인포그래픽", "audio_overview": "오디오 개요",
    "video_overview": "동영상 개요", "memo": "메모", "authored_document": "작성 문서",
}
_ACTIVE = ("queued", "generating")


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def opaque(prefix: str, *parts: str) -> str:
    return f"{prefix}-{sha256_hex('|'.join(parts))[:32]}"


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else (None if value is None else str(value))


def _encode_cursor(created_at: datetime, output_id: str) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{output_id}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        stamp, output_id = raw.split("|", 1)
        return datetime.fromisoformat(stamp), output_id
    except (ValueError, UnicodeError):
        raise StudioError("STUDIO_INPUT_INVALID", 400) from None


_STALE_SQL = """EXISTS(SELECT 1 FROM studio_v2_sources s JOIN source_versions sv
    ON sv.tenant_id=s.tenant_id AND sv.workspace_id=s.workspace_id AND sv.record_id=s.source_version_id
  WHERE s.tenant_id=o.tenant_id AND s.workspace_id=o.workspace_id AND s.output_id=o.output_id
    AND s.revision_no=o.current_revision AND (
      EXISTS(SELECT 1 FROM source_versions nv WHERE nv.tenant_id=sv.tenant_id AND nv.workspace_id=sv.workspace_id
        AND nv.source_id=sv.source_id AND nv.version>sv.version)
      OR EXISTS(SELECT 1 FROM notebook_source_unbindings u WHERE u.tenant_id=o.tenant_id AND u.workspace_id=o.workspace_id
        AND u.notebook_id=o.notebook_id AND u.source_version_id=s.source_version_id)
      OR EXISTS(SELECT 1 FROM deletion_requests d WHERE d.tenant_id=sv.tenant_id AND d.workspace_id=sv.workspace_id
        AND d.source_id=sv.source_id AND d.source_active=false)))"""

_OUTPUT_COLUMNS = ("o.output_id,o.type_id,o.format_id,o.title,o.status,o.error_code,cardinality(o.source_version_ids),"
                   "o.current_revision,o.created_at,o.updated_at,")


def _item(row: Sequence[object]) -> dict[str, object]:
    return {"output_id": row[0], "type_id": row[1], "format_id": row[2], "title": row[3], "status": row[4],
            "error_code": row[5], "source_count": int(row[6]), "current_revision": int(row[7]),
            "created_at": _iso(row[8]), "updated_at": _iso(row[9]), "stale": bool(row[10])}


class PostgresStudioV2Repository:
    def __init__(self, cloud_store, *, clock=None) -> None:  # type: ignore[no-untyped-def]
        self._cloud_store = cloud_store
        self._scope = PostgresStudioWorkspaceRepository(None)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- 공통 ---------------------------------------------------------------
    @staticmethod
    def _cloud(context: StudioContext, capability: str) -> CloudAccessContext:
        return CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, capability)

    @staticmethod
    def _require_notebook(context: StudioContext) -> str:
        if context.notebook_id is None:
            raise StudioError("NOTEBOOK_SCOPE_REQUIRED", 400)
        return context.notebook_id

    def require_scope(self, connection, context: StudioContext, versions: Sequence[str]) -> None:
        self._scope._require_generation_scope(connection, context, versions)

    def ready_source_versions(self, connection, context: StudioContext) -> list[str]:
        rows = connection.execute(
            "SELECT nb.version_id FROM notebook_bindings nb JOIN source_versions sv "
            "ON sv.tenant_id=nb.tenant_id AND sv.workspace_id=nb.workspace_id AND sv.record_id=nb.version_id "
            "WHERE nb.tenant_id=%s AND nb.workspace_id=%s AND nb.notebook_id=%s AND nb.binding_kind='source' "
            "AND NOT EXISTS(SELECT 1 FROM notebook_source_unbindings u WHERE u.tenant_id=nb.tenant_id "
            "AND u.workspace_id=nb.workspace_id AND u.notebook_id=nb.notebook_id AND u.source_id=nb.record_id AND u.source_version_id=nb.version_id) "
            "AND NOT EXISTS(SELECT 1 FROM deletion_requests d WHERE d.tenant_id=sv.tenant_id AND d.workspace_id=sv.workspace_id "
            "AND d.source_id=sv.source_id AND d.source_active=false) "
            "AND (EXISTS(SELECT 1 FROM understanding_results ur WHERE ur.tenant_id=sv.tenant_id AND ur.workspace_id=sv.workspace_id AND ur.source_version_id=sv.record_id) "
            "OR EXISTS(SELECT 1 FROM evidence_spans es WHERE es.tenant_id=sv.tenant_id AND es.workspace_id=sv.workspace_id AND es.source_version_id=sv.record_id)) "
            "ORDER BY nb.version_id",
            (context.tenant_id, context.workspace_id, context.notebook_id)).fetchall()
        return [str(row[0]) for row in rows]

    def _owned_output(self, connection, context: StudioContext, output_id: str, *, lock: bool = False):
        notebook_id = self._require_notebook(context)
        row = connection.execute(
            "SELECT output_id,type_id,format_id,title,status,error_code,settings_json,source_version_ids,current_revision,"
            "owner_actor_id,updated_at,created_at FROM studio_v2_outputs WHERE tenant_id=%s AND workspace_id=%s "
            "AND output_id=%s AND notebook_id=%s AND deleted_at IS NULL" + (" FOR UPDATE" if lock else ""),
            (context.tenant_id, context.workspace_id, output_id, notebook_id)).fetchone()
        if row is None:
            raise StudioError("RESOURCE_UNAVAILABLE", 404)
        return row

    tts_resolver = None   # 조직별 TTS 설정 해석기(런타임이 연결한다). 없으면 배포 설정 파일만 본다

    def _tts_enabled(self, tenant_id: str) -> bool:
        resolver = self.tts_resolver
        if resolver is not None:
            return resolver.for_tenant(tenant_id) is not None
        from .tts_engines import configured_from_env
        return configured_from_env() is not None

    # -- 생성·재생성 -----------------------------------------------------------
    def enqueue(self, context: StudioContext, request: Mapping[str, object], idempotency_key: str) -> dict[str, object]:
        notebook_id = self._require_notebook(context)
        if not isinstance(idempotency_key, str) or not 16 <= len(idempotency_key) <= 128:
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        type_id = request.get("type_id")
        if type_id not in STUDIO_V2_TYPES:
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        if not is_available(str(type_id), tts_enabled=self._tts_enabled(context.tenant_id)):
            raise StudioError("STUDIO_TYPE_UNAVAILABLE", 409)
        try:
            format_id, settings = validate_settings(str(type_id), request.get("format_id"), request.get("settings") or {})  # type: ignore[arg-type]
        except ValueError:
            raise StudioError("STUDIO_INPUT_INVALID", 400) from None
        requested = request.get("source_version_ids")
        if requested is not None and (not isinstance(requested, (list, tuple)) or len(requested) > 64
                                      or any(not isinstance(v, str) for v in requested)):
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        key_sha = sha256_hex(idempotency_key)
        output_id = opaque("sv2", context.tenant_id, context.workspace_id, context.actor_id, key_sha)
        job_id = opaque("svj", output_id, key_sha)
        spec = STUDIO_V2_TYPES[str(type_id)]
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.create")) as connection:
            fingerprint_base = {"type_id": type_id, "format_id": format_id, "settings": settings, "notebook_id": notebook_id,
                                "source_version_ids": sorted(requested) if requested is not None else None}
            fingerprint = sha256_hex(canonical(fingerprint_base))
            existing = connection.execute(
                "SELECT o.output_id,o.status,o.request_fingerprint,j.job_id FROM studio_v2_outputs o LEFT JOIN studio_v2_jobs j "
                "ON j.tenant_id=o.tenant_id AND j.workspace_id=o.workspace_id AND j.output_id=o.output_id AND j.job_id=%s "
                "WHERE o.tenant_id=%s AND o.workspace_id=%s AND o.owner_actor_id=%s AND o.idempotency_key_sha256=%s",
                (job_id, context.tenant_id, context.workspace_id, context.actor_id, key_sha)).fetchone()
            if existing is not None:
                if str(existing[2]) != fingerprint:
                    raise StudioError("IDEMPOTENCY_CONFLICT", 409)
                return {"output_id": existing[0], "job_id": existing[3], "status": existing[1], "replayed": True}
            if spec.requires_llm or requested:
                versions = list(dict.fromkeys(requested)) if requested else self.ready_source_versions(connection, context)
                if not versions:
                    raise StudioError("STUDIO_NO_READY_SOURCE", 409)
                self.require_scope(connection, context, versions)
            else:
                versions = []
            title = f"{TYPE_LABELS.get(str(type_id), str(type_id))} {self._clock().strftime('%Y-%m-%d %H:%M')}"
            connection.execute(
                "INSERT INTO studio_v2_outputs(tenant_id,workspace_id,output_id,notebook_id,owner_actor_id,type_id,format_id,title,"
                "status,settings_json,source_version_ids,idempotency_key_sha256,request_fingerprint) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s,%s)",
                (context.tenant_id, context.workspace_id, output_id, notebook_id, context.actor_id, type_id, format_id, title,
                 Jsonb(settings), versions, key_sha, fingerprint))
            self._insert_job(connection, context, output_id, job_id, "create", str(type_id), format_id, settings, versions, notebook_id)
        return {"output_id": output_id, "job_id": job_id, "status": "queued", "replayed": False}

    @staticmethod
    def _insert_job(connection, context, output_id, job_id, mode, type_id, format_id, settings, versions, notebook_id) -> None:
        connection.execute(
            "INSERT INTO studio_v2_jobs(tenant_id,workspace_id,job_id,output_id,owner_actor_id,state,request_json) "
            "VALUES (%s,%s,%s,%s,%s,'queued',%s)",
            (context.tenant_id, context.workspace_id, job_id, output_id, context.actor_id,
             Jsonb({"mode": mode, "type_id": type_id, "format_id": format_id, "settings": settings,
                    "source_version_ids": list(versions), "notebook_id": notebook_id,
                    "trace_id": context.trace_id, "policy_version": context.policy_version})))

    def regenerate(self, context: StudioContext, output_id: str, settings_override: Mapping[str, object] | None,
                   idempotency_key: str) -> dict[str, object]:
        notebook_id = self._require_notebook(context)
        key_sha = sha256_hex(idempotency_key)
        job_id = opaque("svj", output_id, key_sha)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.create")) as connection:
            row = self._owned_output(connection, context, output_id, lock=True)
            type_id, format_id, status, current_settings, versions = row[1], row[2], row[4], dict(row[6] or {}), list(row[7] or [])
            replay = connection.execute("SELECT state FROM studio_v2_jobs WHERE tenant_id=%s AND workspace_id=%s AND job_id=%s",
                                        (context.tenant_id, context.workspace_id, job_id)).fetchone()
            if replay is not None:
                return {"output_id": output_id, "job_id": job_id, "status": status, "replayed": True}
            if status in _ACTIVE:
                raise StudioError("STUDIO_VERSION_CONFLICT", 409)
            if str(row[9]) != context.actor_id:
                raise StudioError("RESOURCE_UNAVAILABLE", 404)
            merged = {**current_settings, **dict(settings_override or {})}
            try:
                format_id, merged = validate_settings(str(type_id), format_id, merged)
            except ValueError:
                raise StudioError("STUDIO_INPUT_INVALID", 400) from None
            if versions:
                self.require_scope(connection, context, versions)
            connection.execute(
                "UPDATE studio_v2_outputs SET status='queued',error_code=NULL,settings_json=%s,format_id=%s,updated_at=now() "
                "WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s",
                (Jsonb(merged), format_id, context.tenant_id, context.workspace_id, output_id))
            self._insert_job(connection, context, output_id, job_id, "regenerate", str(type_id), format_id, merged, versions, notebook_id)
        return {"output_id": output_id, "job_id": job_id, "status": "queued", "replayed": False}

    # -- 조회 ---------------------------------------------------------------
    def list_outputs(self, context: StudioContext, *, cursor: str | None = None, limit: int = 25) -> dict[str, object]:
        notebook_id = self._require_notebook(context)
        if type(limit) is not int or not 1 <= limit <= MAX_LIST_LIMIT:
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        params: list[object] = [context.tenant_id, context.workspace_id, notebook_id]
        keyset = ""
        if cursor:
            created_at, last_id = _decode_cursor(cursor)
            keyset = " AND (o.created_at,o.output_id) < (%s,%s)"
            params += [created_at, last_id]
        params.append(limit + 1)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            rows = connection.execute(
                f"SELECT {_OUTPUT_COLUMNS}{_STALE_SQL} AS stale FROM studio_v2_outputs o "
                "WHERE o.tenant_id=%s AND o.workspace_id=%s AND o.notebook_id=%s AND o.deleted_at IS NULL"
                f"{keyset} ORDER BY o.created_at DESC,o.output_id DESC LIMIT %s", tuple(params)).fetchall()
        page = rows[:limit]
        items = [_item(row) for row in page]
        next_cursor = _encode_cursor(page[-1][8], str(page[-1][0])) if len(rows) > limit else None
        return {"items": items, "next_cursor": next_cursor}

    def get_output(self, context: StudioContext, output_id: str, revision: int | None = None) -> dict[str, object]:
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            head = self._owned_output(connection, context, output_id)
            stale = connection.execute(
                f"SELECT {_STALE_SQL} FROM studio_v2_outputs o WHERE o.tenant_id=%s AND o.workspace_id=%s AND o.output_id=%s",
                (context.tenant_id, context.workspace_id, output_id)).fetchone()
            number = int(head[8]) if revision is None else revision
            body = None
            evidence: list[dict[str, object]] = []
            if number > 0:
                rev = connection.execute(
                    "SELECT revision_no,revision_type,content_json,warnings_json,created_by,created_at FROM studio_v2_revisions "
                    "WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s",
                    (context.tenant_id, context.workspace_id, output_id, number)).fetchone()
                if rev is None:
                    raise StudioError("RESOURCE_UNAVAILABLE", 404)
                body = {"revision_no": int(rev[0]), "revision_type": rev[1], "content": rev[2], "warnings": rev[3],
                        "created_by": rev[4], "created_at": _iso(rev[5])}
                evidence = []
                for r in connection.execute(
                        "SELECT e.ref_id,e.source_version_id,e.evidence_span_id,e.locator_kind,e.locator_value,e.origin,e.external_ref IS NOT NULL,"
                        "COALESCE(sv.canonical_json->>'filename',e.external_ref->>'name') FROM studio_v2_evidence e "
                        "LEFT JOIN source_versions sv ON sv.tenant_id=e.tenant_id AND sv.workspace_id=e.workspace_id AND sv.record_id=e.source_version_id "
                        "WHERE e.tenant_id=%s AND e.workspace_id=%s AND e.output_id=%s AND e.revision_no=%s ORDER BY e.ref_id",
                        (context.tenant_id, context.workspace_id, output_id, number)).fetchall():
                    item = self._evidence_item(r)
                    item["source_name"] = r[7]
                    evidence.append(item)
            assets = [{"kind": r[0], "bytes": int(r[1]), "revision_no": int(r[2])} for r in connection.execute(
                "SELECT kind,bytes,revision_no FROM studio_v2_assets WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s "
                "AND cleaned_at IS NULL ORDER BY revision_no,kind", (context.tenant_id, context.workspace_id, output_id)).fetchall()]
        item = _item((head[0], head[1], head[2], head[3], head[4], head[5], len(head[7] or []), head[8], head[11], head[10],
                      bool(stale[0]) if stale else False))
        item.update({"settings": head[6], "revision": body, "evidence": evidence, "assets": assets})
        return item

    @staticmethod
    def _evidence_item(row: Sequence[object]) -> dict[str, object]:
        return {"ref_id": row[0], "source_version_id": row[1], "evidence_span_id": row[2], "locator_kind": row[3],
                "locator_value": row[4], "origin": row[5], "has_snapshot": bool(row[6])}

    # -- 수정·삭제·취소 ------------------------------------------------------------
    def rename(self, context: StudioContext, output_id: str, title: str, expected_updated_at: str | None) -> dict[str, object]:
        title = title.strip() if isinstance(title, str) else ""
        if not 1 <= len(title) <= 160:
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            row = self._owned_output(connection, context, output_id, lock=True)
            if expected_updated_at is not None and _iso(row[10]) != expected_updated_at:
                raise StudioError("STUDIO_VERSION_CONFLICT", 409)
            updated = connection.execute(
                "UPDATE studio_v2_outputs SET title=%s,updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s "
                "RETURNING updated_at", (title, context.tenant_id, context.workspace_id, output_id)).fetchone()
        return {"output_id": output_id, "title": title, "updated_at": _iso(updated[0])}

    def apply_generated_title(self, context: StudioContext, output_id: str, title: str) -> bool:
        """자동 제목(F2-02): 아직 기본 제목(유형명 + 생성 시각)인 산출물만 바꾼다. 이름을 바꾼 것은 그대로 둔다."""
        if not isinstance(title, str) or not 1 <= len(title) <= 40:
            return False
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            row = connection.execute(
                "SELECT type_id,title FROM studio_v2_outputs WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND deleted_at IS NULL",
                (context.tenant_id, context.workspace_id, output_id)).fetchone()
            if row is None:
                return False
            default = re.compile(re.escape(TYPE_LABELS.get(str(row[0]), str(row[0]))) + r" \d{4}-\d{2}-\d{2} \d{2}:\d{2}")
            if not default.fullmatch(str(row[1])):
                return False
            connection.execute(
                "UPDATE studio_v2_outputs SET title=%s WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND title=%s",
                (title, context.tenant_id, context.workspace_id, output_id, row[1]))
            return True

    def soft_delete(self, context: StudioContext, output_id: str) -> None:
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            self._owned_output(connection, context, output_id, lock=True)
            self._cancel_jobs(connection, context, output_id)
            connection.execute(
                "UPDATE studio_v2_outputs SET deleted_at=now(),updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s",
                (context.tenant_id, context.workspace_id, output_id))

    @staticmethod
    def _cancel_jobs(connection, context: StudioContext, output_id: str) -> int:
        scope = (context.tenant_id, context.workspace_id, output_id)
        queued = connection.execute(
            "UPDATE studio_v2_jobs SET state='cancelled',completed_at=now(),updated_at=now(),version=version+1 "
            "WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND state='queued' RETURNING job_id", scope).fetchall()
        running = connection.execute(
            "UPDATE studio_v2_jobs SET cancel_requested=true,updated_at=now() WHERE tenant_id=%s AND workspace_id=%s "
            "AND output_id=%s AND state IN ('leased','generating') RETURNING job_id", scope).fetchall()
        return len(queued) + len(running)

    def request_cancel(self, context: StudioContext, output_id: str) -> dict[str, object]:
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            row = self._owned_output(connection, context, output_id, lock=True)
            if row[4] not in _ACTIVE:
                raise StudioError("STUDIO_VERSION_CONFLICT", 409)
            self._cancel_jobs(connection, context, output_id)
            running = connection.execute(
                "SELECT 1 FROM studio_v2_jobs WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND state IN ('leased','generating')",
                (context.tenant_id, context.workspace_id, output_id)).fetchone()
            if running is None:
                connection.execute(
                    "UPDATE studio_v2_outputs SET status=CASE WHEN current_revision>0 THEN 'completed' ELSE 'cancelled' END,"
                    "error_code=NULL,updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s",
                    (context.tenant_id, context.workspace_id, output_id))
        return {"output_id": output_id, "cancel_requested": True}

    # -- 리비전 ---------------------------------------------------------------
    def add_revision(self, context: StudioContext, output_id: str, revision_type: str, content: Mapping[str, object], *,
                     warnings: Sequence[object] = (), generated_with: Mapping[str, object] | None = None,
                     sources: Sequence[Mapping[str, object]] = (), evidence: Sequence[Mapping[str, object]] = (),
                     assets: Sequence[Mapping[str, object]] = (), connection=None) -> int:
        if revision_type not in {"generated", "user_edit", "regenerated"} or not isinstance(content, Mapping):
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        payload = canonical(content)
        if len(payload) > MAX_REVISION_BYTES:
            raise StudioError("STUDIO_REVISION_TOO_LARGE", 413)
        digest = sha256_hex(payload)
        if connection is None:
            with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as inner:
                return self.add_revision(context, output_id, revision_type, content, warnings=warnings,
                                         generated_with=generated_with, sources=sources, evidence=evidence, assets=assets, connection=inner)
        if revision_type == "user_edit":
            row = self._owned_output(connection, context, output_id, lock=True)
            if row[4] != "completed":
                raise StudioError("STUDIO_VERSION_CONFLICT", 409)
        updated = connection.execute(
            "UPDATE studio_v2_outputs SET current_revision=current_revision+1,updated_at=now() WHERE tenant_id=%s AND workspace_id=%s "
            "AND output_id=%s AND deleted_at IS NULL RETURNING current_revision", (context.tenant_id, context.workspace_id, output_id)).fetchone()
        if updated is None:
            raise StudioError("RESOURCE_UNAVAILABLE", 404)
        number = int(updated[0])
        connection.execute(
            "INSERT INTO studio_v2_revisions(tenant_id,workspace_id,output_id,revision_no,revision_type,content_json,content_sha256,"
            "warnings_json,generated_with,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (context.tenant_id, context.workspace_id, output_id, number, revision_type, Jsonb(content), digest,
             Jsonb(list(warnings)), Jsonb(dict(generated_with or {})), context.actor_id))
        for source in sources:
            connection.execute(
                "INSERT INTO studio_v2_sources(tenant_id,workspace_id,output_id,revision_no,source_version_id,source_id,content_digest_sha256) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (context.tenant_id, context.workspace_id, output_id, number, source["source_version_id"],
                 source.get("source_id"), source.get("content_digest_sha256")))
        for ref in evidence:
            connection.execute(
                "INSERT INTO studio_v2_evidence(tenant_id,workspace_id,output_id,revision_no,ref_id,source_version_id,evidence_span_id,"
                "locator_kind,locator_value,quote_sha256,origin,external_ref) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (context.tenant_id, context.workspace_id, output_id, number, ref["ref_id"], ref.get("source_version_id"),
                 ref.get("evidence_span_id"), ref.get("locator_kind"), ref.get("locator_value"), ref.get("quote_sha256"),
                 ref.get("origin", "notebook_source"),
                 None if ref.get("external_ref") is None else Jsonb(ref["external_ref"])))
        for asset in assets:
            content_bytes = bytes(asset["content"])  # type: ignore[arg-type]
            if not content_bytes or len(content_bytes) > MAX_ASSET_BYTES or asset["kind"] not in {"mp3", "wav", "mp4"}:
                raise StudioError("STUDIO_ASSET_INVALID", 413)
            asset_id = "sva-" + secrets.token_hex(16)
            connection.execute(
                "INSERT INTO studio_v2_assets(tenant_id,workspace_id,output_id,asset_id,revision_no,kind,object_key,bytes,sha256,duration_ms,"
                "content_type,content) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (context.tenant_id, context.workspace_id, output_id, asset_id, number, asset["kind"], f"inline:{asset_id}",
                 len(content_bytes), sha256_hex(content_bytes), asset.get("duration_ms"), asset["content_type"], content_bytes))
        return number

    def get_asset(self, context: StudioContext, output_id: str, kind: str) -> dict[str, object]:
        """가장 최근 리비전의 자산(바이트 포함). 소유자 범위의 완료된 산출물만."""
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            self._owned_output(connection, context, output_id)
            row = connection.execute(
                "SELECT content,content_type,duration_ms,sha256,revision_no FROM studio_v2_assets WHERE tenant_id=%s AND workspace_id=%s "
                "AND output_id=%s AND kind=%s AND content IS NOT NULL AND cleaned_at IS NULL ORDER BY revision_no DESC LIMIT 1",
                (context.tenant_id, context.workspace_id, output_id, kind)).fetchone()
        if row is None:
            raise StudioError("RESOURCE_UNAVAILABLE", 404)
        return {"content": bytes(row[0]), "content_type": str(row[1]), "duration_ms": row[2], "sha256": str(row[3]), "revision_no": int(row[4])}

    def save_user_edit(self, context: StudioContext, output_id: str, content: Mapping[str, object], change_reason: str | None = None) -> int:
        """사용자 편집을 새 리비전으로 저장한다. 본문은 유형별 규칙으로 정리하고, 근거(evidence)·소스 연결은 직전 리비전에서 이어 받는다."""
        from .studio_user_edit import validate_user_edit
        if not isinstance(content, Mapping):
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            row = self._owned_output(connection, context, output_id, lock=True)
            if row[4] != "completed":
                raise StudioError("STUDIO_VERSION_CONFLICT", 409)
            type_id, current = str(row[1]), int(row[8])
            previous = connection.execute(
                "SELECT content_json FROM studio_v2_revisions WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s",
                (context.tenant_id, context.workspace_id, output_id, current)).fetchone()
            if previous is None or not isinstance(previous[0], Mapping):
                raise StudioError("STUDIO_VERSION_CONFLICT", 409)
            known = {str(r[0]) for r in connection.execute(
                "SELECT ref_id FROM studio_v2_evidence WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s",
                (context.tenant_id, context.workspace_id, output_id, current)).fetchall()}
            previous_body = previous[0].get("body")
            body = validate_user_edit(type_id, content.get("body"), known, previous_body if isinstance(previous_body, Mapping) else None)
            new_content = {**dict(previous[0]), "body": body}
            number = self.add_revision(context, output_id, "user_edit", new_content, warnings=[],
                                       generated_with={"edited_by": "user", "change_reason": (change_reason or "")[:200]}, connection=connection)
            params = (context.tenant_id, context.workspace_id, output_id, number, context.tenant_id, context.workspace_id, output_id, current)
            connection.execute(
                "INSERT INTO studio_v2_evidence(tenant_id,workspace_id,output_id,revision_no,ref_id,source_version_id,evidence_span_id,locator_kind,locator_value,"
                "quote_sha256,origin,external_ref) SELECT %s,%s,%s,%s,ref_id,source_version_id,evidence_span_id,locator_kind,locator_value,quote_sha256,origin,external_ref "
                "FROM studio_v2_evidence WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s ON CONFLICT DO NOTHING", params)
            connection.execute(
                "INSERT INTO studio_v2_sources(tenant_id,workspace_id,output_id,revision_no,source_version_id,source_id,content_digest_sha256) "
                "SELECT %s,%s,%s,%s,source_version_id,source_id,content_digest_sha256 FROM studio_v2_sources "
                "WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s ON CONFLICT DO NOTHING", params)
            return number

    # -- 작성(Authoring) 세션: 세션 상태는 불변 리비전으로 쌓는다 ----------------------------------
    def create_authoring_session(self, context: StudioContext, title: str, content: Mapping[str, object], idempotency_key: str) -> dict[str, object]:
        notebook_id = self._require_notebook(context)
        key_sha = sha256_hex(idempotency_key)
        output_id = opaque("sv2", context.tenant_id, context.workspace_id, context.actor_id, key_sha)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            existing = connection.execute("SELECT 1 FROM studio_v2_outputs WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s",
                                          (context.tenant_id, context.workspace_id, output_id)).fetchone()
            if existing is not None:
                return {"output_id": output_id, "replayed": True}
            connection.execute(
                "INSERT INTO studio_v2_outputs(tenant_id,workspace_id,output_id,notebook_id,owner_actor_id,type_id,title,status,settings_json,source_version_ids,"
                "idempotency_key_sha256,request_fingerprint) VALUES (%s,%s,%s,%s,%s,'authored_document',%s,'completed','{}',%s,%s,%s)",
                (context.tenant_id, context.workspace_id, output_id, notebook_id, context.actor_id, title[:160], [], key_sha, sha256_hex(canonical(content))))
            self.add_revision(context, output_id, "generated", content, connection=connection)
        return {"output_id": output_id, "replayed": False}

    def authoring_apply(self, context: StudioContext, output_id: str, expected_revision: int, mutate, *, enqueue_step: str | None = None,  # type: ignore[no-untyped-def]
                        source_version_ids: Sequence[str] = ()) -> dict[str, object]:
        """세션 최신 리비전을 읽어 mutate(content)로 새 리비전을 쌓고, 필요하면 같은 트랜잭션에서 작업을 등록한다."""
        notebook_id = self._require_notebook(context)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            row = self._owned_output(connection, context, output_id, lock=True)
            if row[1] != "authored_document":
                raise StudioError("RESOURCE_UNAVAILABLE", 404)
            if row[4] in _ACTIVE:
                raise StudioError("STUDIO_VERSION_CONFLICT", 409)
            if int(row[8]) != expected_revision:
                raise StudioError("STUDIO_VERSION_CONFLICT", 409)
            current = connection.execute(
                "SELECT content_json FROM studio_v2_revisions WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s",
                (context.tenant_id, context.workspace_id, output_id, expected_revision)).fetchone()
            import copy as _copy
            content = mutate(_copy.deepcopy(current[0]))
            if enqueue_step is not None and source_version_ids:
                self.require_scope(connection, context, list(source_version_ids))
            number = self.add_revision(context, output_id, "user_edit", content, connection=connection)
            if enqueue_step is not None:
                connection.execute("UPDATE studio_v2_outputs SET status='queued',error_code=NULL,source_version_ids=%s,updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s",
                                   (list(source_version_ids), context.tenant_id, context.workspace_id, output_id))
                self._insert_job(connection, context, output_id, opaque("svj", output_id, f"authoring-{number}"), "authoring", "authored_document", None,
                                 {"step": enqueue_step}, list(source_version_ids), notebook_id)
        return {"output_id": output_id, "revision_no": number, "state": content.get("state"), "queued": enqueue_step is not None}

    def latest_content(self, context: StudioContext, output_id: str) -> tuple[int, str, Mapping[str, object]]:
        """(리비전, 출력 상태, 내용). 세션 화면 복원과 워커가 쓴다."""
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            row = self._owned_output(connection, context, output_id)
            rev = connection.execute("SELECT content_json FROM studio_v2_revisions WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s",
                                     (context.tenant_id, context.workspace_id, output_id, row[8])).fetchone()
        if rev is None:
            raise StudioError("RESOURCE_UNAVAILABLE", 404)
        return int(row[8]), str(row[4]), rev[0]

    def provenance(self, context: StudioContext, output_id: str, revision: int | None = None) -> dict[str, object]:
        """설계서 §6.5.2. 시스템 프롬프트 원문과 generated_with는 포함하지 않는다."""
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            head = self._owned_output(connection, context, output_id)
            number = int(head[8]) if revision is None else revision
            if number <= 0:
                raise StudioError("RESOURCE_UNAVAILABLE", 404)
            if connection.execute("SELECT 1 FROM studio_v2_revisions WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s",
                                  (context.tenant_id, context.workspace_id, output_id, number)).fetchone() is None:
                raise StudioError("RESOURCE_UNAVAILABLE", 404)
            customization = connection.execute(
                "SELECT length(instruction)>0 FROM workspace_studio_v2_customization WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s",
                (context.tenant_id, context.workspace_id, context.notebook_id)).fetchone()
            sources = connection.execute(
                "SELECT s.source_version_id,s.source_id,sv.canonical_json->>'filename',"
                "EXISTS(SELECT 1 FROM source_versions nv WHERE nv.tenant_id=sv.tenant_id AND nv.workspace_id=sv.workspace_id "
                "AND nv.source_id=sv.source_id AND nv.version>sv.version) "
                "FROM studio_v2_sources s LEFT JOIN source_versions sv ON sv.tenant_id=s.tenant_id AND sv.workspace_id=s.workspace_id "
                "AND sv.record_id=s.source_version_id WHERE s.tenant_id=%s AND s.workspace_id=%s AND s.output_id=%s AND s.revision_no=%s "
                "ORDER BY s.source_version_id", (context.tenant_id, context.workspace_id, output_id, number)).fetchall()
            evidence = connection.execute(
                "SELECT ref_id,source_version_id,evidence_span_id,locator_kind,locator_value,origin,external_ref IS NOT NULL "
                "FROM studio_v2_evidence WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s AND revision_no=%s ORDER BY ref_id",
                (context.tenant_id, context.workspace_id, output_id, number)).fetchall()
        settings = dict(head[6] or {})
        return {
            "output_id": output_id, "revision_no": number, "type_id": head[1], "format_id": head[2],
            "instruction": {"focus": settings.get("focus"), "customization_applied": bool(customization and customization[0])},
            "settings": settings,
            "sources": [{"source_version_id": r[0], "source_id": r[1], "name": r[2], "changed": bool(r[3])} for r in sources],
            "evidence": [self._evidence_item(r) for r in evidence],
        }

    # -- 학습 이력 ---------------------------------------------------------------
    def record_learning_attempt(self, context: StudioContext, output_id: str, revision_no: int, kind: str,
                                payload: Mapping[str, object], idempotency_key: str) -> dict[str, object]:
        if kind not in {"flashcard", "quiz"} or not isinstance(payload, Mapping) or len(canonical(payload)) > 65536:
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        attempt_id = opaque("sva", output_id, context.actor_id, sha256_hex(idempotency_key))
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            self._owned_output(connection, context, output_id)
            connection.execute(
                "INSERT INTO studio_v2_learning_attempts(tenant_id,workspace_id,attempt_id,output_id,revision_no,user_id,kind,payload_json) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (context.tenant_id, context.workspace_id, attempt_id, output_id, revision_no, context.actor_id, kind, Jsonb(dict(payload))))
        return {"attempt_id": attempt_id}

    def list_learning_attempts(self, context: StudioContext, output_id: str, limit: int = 50) -> list[dict[str, object]]:
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            self._owned_output(connection, context, output_id)
            rows = connection.execute(
                "SELECT attempt_id,revision_no,kind,payload_json,created_at FROM studio_v2_learning_attempts WHERE tenant_id=%s "
                "AND workspace_id=%s AND output_id=%s AND user_id=%s ORDER BY created_at DESC LIMIT %s",
                (context.tenant_id, context.workspace_id, output_id, context.actor_id, min(max(limit, 1), 200))).fetchall()
        return [{"attempt_id": r[0], "revision_no": int(r[1]), "kind": r[2], "payload": r[3], "created_at": _iso(r[4])} for r in rows]

    # -- 맞춤설정 ---------------------------------------------------------------
    def get_customization(self, context: StudioContext) -> dict[str, object]:
        notebook_id = self._require_notebook(context)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.read")) as connection:
            row = connection.execute(
                "SELECT instruction,version FROM workspace_studio_v2_customization WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s",
                (context.tenant_id, context.workspace_id, notebook_id)).fetchone()
        return {"instruction": "" if row is None else row[0], "version": 0 if row is None else int(row[1])}

    def save_customization(self, context: StudioContext, instruction: str, expected_version: int) -> dict[str, object]:
        notebook_id = self._require_notebook(context)
        if not isinstance(instruction, str) or len(instruction) > 4000 or type(expected_version) is not int or expected_version < 0:
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        scope = (context.tenant_id, context.workspace_id, notebook_id)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            if expected_version == 0:
                row = connection.execute(
                    "INSERT INTO workspace_studio_v2_customization(tenant_id,workspace_id,notebook_id,instruction,version,updated_by) "
                    "VALUES (%s,%s,%s,%s,1,%s) ON CONFLICT DO NOTHING RETURNING version",
                    (*scope, instruction, context.actor_id)).fetchone()
            else:
                row = connection.execute(
                    "UPDATE workspace_studio_v2_customization SET instruction=%s,version=version+1,updated_by=%s,updated_at=now() "
                    "WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND version=%s RETURNING version",
                    (instruction, context.actor_id, *scope, expected_version)).fetchone()
        if row is None:
            raise StudioError("STUDIO_VERSION_CONFLICT", 409)
        return {"instruction": instruction, "version": int(row[0])}

    # -- 메모 ---------------------------------------------------------------
    def create_memo(self, context: StudioContext, title: str | None, markdown: str, idempotency_key: str, *,
                    refs: Sequence[Mapping[str, object]] = ()) -> dict[str, object]:
        notebook_id = self._require_notebook(context)
        if not isinstance(markdown, str) or len(markdown.encode()) > 200_000:
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        key_sha = sha256_hex(idempotency_key)
        output_id = opaque("sv2", context.tenant_id, context.workspace_id, context.actor_id, key_sha)
        title = (title or "").strip() or f"메모 {self._clock().strftime('%Y-%m-%d %H:%M')}"
        if len(title) > 160:
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        with self._cloud_store._transaction(self._cloud(context, "studio.v2.write")) as connection:
            exists = connection.execute(
                "SELECT 1 FROM studio_v2_outputs WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s",
                (context.tenant_id, context.workspace_id, output_id)).fetchone()
            if exists is not None:
                return {"output_id": output_id, "status": "completed", "replayed": True}
            ref_versions = sorted({str(r["source_version_id"]) for r in refs if r.get("source_version_id")})
            if ref_versions:
                self.require_scope(connection, context, ref_versions)
            connection.execute(
                "INSERT INTO studio_v2_outputs(tenant_id,workspace_id,output_id,notebook_id,owner_actor_id,type_id,title,status,"
                "settings_json,source_version_ids,idempotency_key_sha256,request_fingerprint) "
                "VALUES (%s,%s,%s,%s,%s,'memo',%s,'completed','{}',%s,%s,%s)",
                (context.tenant_id, context.workspace_id, output_id, notebook_id, context.actor_id, title,
                 ref_versions, key_sha,
                 sha256_hex(canonical({"memo": title, "md": markdown}))))
            self.add_revision(context, output_id, "generated", {"schema": "studio.memo.v1", "body": {"markdown": markdown,
                              "refs": [r["ref_id"] for r in refs]}, "warnings": []}, evidence=refs,
                              sources=[{"source_version_id": v} for v in ref_versions],
                              connection=connection)
        return {"output_id": output_id, "status": "completed", "replayed": False}
