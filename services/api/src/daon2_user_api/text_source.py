"""텍스트로 소스 등록(WO-N1 NB1-F2, 정정 C-1). 메모를 소스로(N1-3)와 자료 찾기(NB4-F1)가 함께 쓴다.

- register_text_source: 글을 UTF-8 `.txt`(text/plain)로 만들어 파일 업로드와 같은 경로로 등록한다.
  객체 대기열 저장 → canon 등록·노트북 연결 → 문서 처리 작업 제출. 문서 처리 작업은 기존 TXT와 똑같이 처리한다.
- append_text_version: 같은 source_id에 새 소스 버전을 붙인다(data_canon.append_source_version).
  준비된(ready) 소스의 상태 기계(canon_transition_rules)에는 ready→processing이 없으므로, 새 버전은
  같은 트랜잭션에서 원문 그대로의 구간(text_source_verbatim_fact)으로 색인한다. TXT 처리 결과의 원문 구간과 같은 형태다.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Callable

from psycopg.types.json import Jsonb

from .cloud_storage import CloudAccessContext
from .data_canon import CanonicalContext, canonical_json_bytes
from .document_processing import DocumentProcessingContext, text_source_format
from .source_ingest import SourceIngestor, SourceRejected

TEXT_SOURCE_MAX_BYTES = 32 * 1024          # TXT 이해(text_document_understanding)의 상한과 같다
TEXT_SOURCE_ORIGINS = frozenset({"memo", "research"})
TEXT_CONTENT_TYPE = "text/plain"
_CHUNK_CHARS = 1024
_FILENAME_UNSAFE = re.compile(r"[/\\\x00-\x1f\x7f]")
_BUSY_STATES = frozenset({"registered", "security_check", "processing", "indexing"})
_GONE_STATES = frozenset({"expired", "disabled", "deleting", "deleted"})
_RECOVERABLE_STATES = frozenset({"failed", "waiting_model", "partial_understanding", "needs_review"})

# canon 표(sources)는 앱 역할에 UPDATE 권한이 없어 FOR UPDATE를 쓸 수 없다(NB1-I2 실서버 DATABASE_ACCESS_DENIED).
# 같은 소스에 동시에 새 버전을 붙이지 않도록 트랜잭션 advisory lock으로 직렬화한 뒤 읽는다.
_SOURCE_ADVISORY_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))"
_LOCK_SOURCE_SQL = ("SELECT state,version FROM sources WHERE tenant_id=%s AND workspace_id=%s AND record_id=%s")
_DELETED_SQL = ("SELECT 1 FROM deletion_requests WHERE tenant_id=%s AND workspace_id=%s AND source_id=%s AND source_active=false LIMIT 1")
_LATEST_VERSION_SQL = ("SELECT record_id,version,canonical_json FROM source_versions WHERE tenant_id=%s AND workspace_id=%s "
                       "AND source_id=%s ORDER BY version DESC LIMIT 1")
_BOUND_SQL = ("SELECT 1 FROM notebook_bindings b WHERE b.tenant_id=%s AND b.workspace_id=%s AND b.notebook_id=%s "
              "AND b.binding_kind='source' AND b.record_id=%s AND b.version_id=%s "
              "AND NOT EXISTS(SELECT 1 FROM notebook_source_unbindings u WHERE u.tenant_id=b.tenant_id AND u.workspace_id=b.workspace_id "
              "AND u.notebook_id=b.notebook_id AND u.source_id=b.record_id AND u.source_version_id=b.version_id)")
_BIND_SQL = (
    "WITH inserted AS (INSERT INTO notebook_bindings "
    "(tenant_id,workspace_id,notebook_id,binding_kind,record_id,version_id,created_by,created_at) "
    "VALUES (%s,%s,%s,'source',%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING 1) "
    "INSERT INTO notebook_activities "
    "(tenant_id,workspace_id,notebook_id,sequence,activity_kind,actor_id,occurred_at) "
    "SELECT %s,%s,%s,coalesce((SELECT max(sequence) FROM notebook_activities WHERE "
    "tenant_id=%s AND workspace_id=%s AND notebook_id=%s),0)+1,'context_bound',%s,%s FROM inserted")
_CANON_COLUMNS = ("(tenant_id,workspace_id,record_id,aggregate_id,version,schema_version,canonical_json,canonical_text,"
                  "digest_sha256,created_by,trace_id,source_version_id) VALUES (%s,%s,%s,%s,1,1,%s,%s,%s,%s,%s,%s)")
_EVIDENCE_SQL = "INSERT INTO evidence_spans" + _CANON_COLUMNS
_INDEX_SQL = "INSERT INTO index_versions" + _CANON_COLUMNS
_TRANSITION_SQL = "SELECT state,version,outcome,error_code FROM transition_canon_state(%s,%s,%s,%s,%s,%s,%s,%s)"


class TextSourceError(RuntimeError):
    def __init__(self, code: str, status: int) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


def text_filename(title: object) -> str:
    """소스 목록에 보일 파일 이름. 경로·제어 문자를 빼고 120자로 자른 뒤 `.txt`를 붙인다."""
    clean = " ".join(_FILENAME_UNSAFE.sub("", title if isinstance(title, str) else "").split())[:120].strip()
    return f"{clean or '텍스트 소스'}.txt"


def _encode(text: object) -> bytes:
    if not isinstance(text, str) or "\x00" in text:
        raise TextSourceError("TEXT_SOURCE_INPUT_INVALID", 400)
    if not text.strip():
        raise TextSourceError("TEXT_SOURCE_EMPTY", 422)
    try:
        content = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise TextSourceError("TEXT_SOURCE_INPUT_INVALID", 400) from None
    if len(content) > TEXT_SOURCE_MAX_BYTES:
        raise TextSourceError("TEXT_SOURCE_TOO_LARGE", 413)
    return content


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def verbatim_chunks(source_id: str, source_version_id: str, text: str) -> list[dict[str, object]]:
    """원문 code point를 그대로 보존하는 1024자 구간(TXT 처리의 원문 구간과 같은 종류)."""
    chunks: list[dict[str, object]] = []
    for start in range(0, len(text), _CHUNK_CHARS):
        passage = text[start:start + _CHUNK_CHARS]
        if not passage.strip():
            continue
        suffix = _sha(f"{source_version_id}|{start}")[:32]
        chunks.append({"chunk_id": f"text-chunk-{suffix}", "source_id": source_id, "source_version_id": source_version_id,
                       "page": 1, "text": passage, "evidence_span_id": f"text-span-{suffix}",
                       "evidence_kind": "text_source_verbatim_fact"})
    return chunks


class TextSourceService:
    """context는 tenant_id·workspace_id·actor_id·trace_id·policy_version·notebook_id를 가진 객체(StudioContext 등)."""

    def __init__(self, *, upload_service: Any, processing_service: Any, cloud_store: Any,
                 clock: Callable[[], datetime] | None = None) -> None:
        self._upload = upload_service
        self._processing = processing_service
        self._cloud_store = cloud_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def register_text_source(self, context: Any, notebook_id: str, *, title: str, text: str, origin: str,
                             idempotency_key: str | None = None) -> tuple[str, str]:
        """새 텍스트 소스를 만들고 (source_id, source_version_id)를 돌려준다.

        같은 idempotency_key로 다시 부르면 같은 소스를 돌려준다(재시도 안전). 키가 없으면 매번 새 소스다.
        같은 내용의 다른 소스(업로드 중복 제거)에는 붙지 않는다.
        """
        if origin not in TEXT_SOURCE_ORIGINS or not isinstance(notebook_id, str) or not notebook_id:
            raise TextSourceError("TEXT_SOURCE_INPUT_INVALID", 400)
        content = _encode(text)
        filename = text_filename(title)
        try:
            SourceIngestor().register_file(filename, TEXT_CONTENT_TYPE, content)
        except SourceRejected:
            raise TextSourceError("TEXT_SOURCE_INPUT_INVALID", 400) from None
        key = idempotency_key or f"text-source:{origin}:{secrets.token_hex(16)}"
        result = self._upload.register_source(
            tenant_id=context.tenant_id, workspace_id=context.workspace_id, notebook_id=notebook_id,
            actor_id=context.actor_id, filename=filename, content=content, idempotency_key=key,
            trace_id=context.trace_id, content_type=TEXT_CONTENT_TYPE, deduplicate=False)
        self._processing.submit(
            DocumentProcessingContext(context.tenant_id, context.workspace_id, context.actor_id,
                                      context.trace_id, context.policy_version),
            result.source_version_id, notebook_id=notebook_id)
        return result.source_id, result.source_version_id

    def append_text_version(self, context: Any, source_id: str, text: str, *, idempotency_key: str | None = None,
                            within: Callable[[Any, str], None] | None = None) -> str:
        """context.notebook_id 노트북에 연결된 텍스트 소스에 새 버전을 붙이고 source_version_id를 돌려준다.

        within(connection, source_version_id)은 같은 트랜잭션 안에서 불린다(예외를 내면 새 버전도 되돌린다).
        """
        notebook_id = getattr(context, "notebook_id", None)
        if not isinstance(notebook_id, str) or not notebook_id or not isinstance(source_id, str) or not source_id:
            raise TextSourceError("TEXT_SOURCE_INPUT_INVALID", 400)
        content = _encode(text)
        digest = _sha(content)
        key = idempotency_key or f"text-version:{source_id}:{digest}"
        object_id = self._upload.store_object(
            tenant_id=context.tenant_id, workspace_id=context.workspace_id, actor_id=context.actor_id,
            content=content, content_type=TEXT_CONTENT_TYPE, idempotency_key=key, trace_id=context.trace_id)
        version_id = f"sv-{object_id}"
        scope = (context.tenant_id, context.workspace_id)
        with self._cloud_store._transaction(CloudAccessContext(*scope, context.actor_id, "source.write")) as connection:
            connection.execute(_SOURCE_ADVISORY_LOCK_SQL, (f"text-source-version|{context.tenant_id}|{context.workspace_id}|{source_id}",))
            source = connection.execute(_LOCK_SOURCE_SQL, (*scope, source_id)).fetchone()
            if source is None or str(source[0]) in _GONE_STATES:
                raise TextSourceError("TEXT_SOURCE_NOT_FOUND", 404)
            if connection.execute(_DELETED_SQL, (*scope, source_id)).fetchone() is not None:
                raise TextSourceError("TEXT_SOURCE_NOT_FOUND", 404)
            latest = connection.execute(_LATEST_VERSION_SQL, (*scope, source_id)).fetchone()
            if latest is None:
                raise TextSourceError("TEXT_SOURCE_NOT_FOUND", 404)
            latest_id, latest_number, previous = str(latest[0]), int(latest[1]), latest[2] if isinstance(latest[2], dict) else {}
            if connection.execute(_BOUND_SQL, (*scope, notebook_id, source_id, latest_id)).fetchone() is None:
                raise TextSourceError("TEXT_SOURCE_NOT_FOUND", 404)
            if latest_id == version_id:      # 같은 키의 재시도: 이미 붙였다
                if within is not None:
                    within(connection, version_id)
                return version_id
            filename = str(previous.get("filename", ""))
            if previous.get("content_type") != TEXT_CONTENT_TYPE or text_source_format(filename, TEXT_CONTENT_TYPE) != "txt":
                raise TextSourceError("TEXT_SOURCE_NOT_TEXT", 409)
            state = str(source[0])
            if state in _BUSY_STATES:
                raise TextSourceError("SOURCE_PROCESSING_ACTIVE", 409)
            payload: dict[str, object] = {
                "filename": filename, "content_type": TEXT_CONTENT_TYPE, "byte_size": len(content), "object_id": object_id,
                "content_digest_sha256": digest,
                "deletion_policy": str(previous.get("deletion_policy") or "delete_with_notebook"),
            }
            canon = CanonicalContext(*scope, context.actor_id, "source.write", context.trace_id)
            now = self._clock()
            self._upload.canon_store.append_source_version_in_transaction(
                connection, canon, source_version_id=version_id, source_id=source_id, version_number=latest_number + 1,
                previous_version_id=latest_id, canonical_payload=payload,
                digest_sha256=_sha(canonical_json_bytes(payload)), created_at=now)
            connection.execute(_BIND_SQL, (*scope, notebook_id, source_id, version_id, context.actor_id, now,
                                           *scope, notebook_id, *scope, notebook_id, context.actor_id, now))
            self._index(connection, context, source_id, version_id, latest_id, digest, text)
            if state in _RECOVERABLE_STATES:
                self._make_ready(connection, context, source_id, version_id, int(source[1]))
            if within is not None:
                within(connection, version_id)
        return version_id

    @staticmethod
    def _insert(connection: Any, context: Any, sql: str, record_id: str, payload: dict[str, object], version_id: str) -> None:
        encoded = canonical_json_bytes(payload).decode("utf-8")
        connection.execute(sql, (context.tenant_id, context.workspace_id, record_id, record_id, Jsonb(payload), encoded,
                                 _sha(encoded), context.actor_id, context.trace_id, version_id))

    def _index(self, connection: Any, context: Any, source_id: str, version_id: str, previous_id: str, digest: str, text: str) -> None:
        chunks = verbatim_chunks(source_id, version_id, text)
        if not chunks:
            raise TextSourceError("TEXT_SOURCE_EMPTY", 422)
        for chunk in chunks:
            self._insert(connection, context, _EVIDENCE_SQL, str(chunk["evidence_span_id"]),
                         {"source_id": source_id, "source_version_id": version_id, "page": 1, "text": chunk["text"],
                          "kind": "text_source_verbatim_fact"}, version_id)
        self._insert(connection, context, _INDEX_SQL, "text-index-" + version_id[3:],
                     {"source_id": source_id, "source_version_id": version_id, "strategy": "text_source_version_snapshot",
                      "chunks": chunks, "lineage": {"previous_version_id": previous_id, "content_digest_sha256": digest}},
                     version_id)

    @staticmethod
    def _make_ready(connection: Any, context: Any, source_id: str, version_id: str, version: int) -> None:
        """실패 등으로 멈춘 소스를 새 버전 색인과 함께 준비 상태로 옮긴다(기존 허용 전이만 쓴다)."""
        for target in ("processing", "indexing", "ready"):
            row = connection.execute(_TRANSITION_SQL, (
                "Source", source_id, version, target, "text-transition-" + _sha(f"{version_id}|{target}")[:32],
                "TEXT_SOURCE_VERSION_INDEXED", context.trace_id, context.policy_version)).fetchone()
            if row is None or row[2] != "succeeded":
                raise TextSourceError("SOURCE_PROCESSING_ACTIVE", 409)
            version = int(row[1])
