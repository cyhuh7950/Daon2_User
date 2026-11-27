"""Index an approved, finalized local file inside its selected notebook."""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone

from pypdf import PdfReader

from .cloud_storage import CloudAccessContext, CloudDatabaseError, PostgresCloudStore
from .data_canon import CanonError, CanonicalContext, PostgresDataCanonStore
from .notebook import NotebookContext, NotebookError
from .notebook_postgres import PostgresNotebookRepository
from .object_queue import ObjectRecord, ObjectStoragePort
from .source_ingest import SourceIngestor, SourceRejected
from .sync import SyncContext, SyncError, SyncItemInput
from .text_source import (
    TextSourceError, TextSourceService, _BOUND_SQL, _DELETED_SQL, _EVIDENCE_SQL, _INDEX_SQL,
    _SOURCE_ADVISORY_LOCK_SQL, _TRANSITION_SQL,
)


_EXTENSIONS = {"text/plain": "txt", "text/markdown": "md", "application/pdf": "pdf"}


def _original_pages(content: bytes, content_type: str) -> tuple[tuple[int, str], ...]:
    try:
        if content_type == "application/pdf":
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted or len(reader.pages) > 100:
                raise ValueError
            pages = tuple((index, page.extract_text() or "") for index, page in enumerate(reader.pages, 1))
        else:
            pages = ((1, content.decode("utf-8-sig")),)
    except Exception:
        raise SyncError("SYNC_ORIGINAL_TEXT_UNAVAILABLE", 422) from None
    if (not any(text.strip() for _, text in pages)
        or any("\x00" in text for _, text in pages)
        or sum(len(text) for _, text in pages) > 524_288):
        raise SyncError("SYNC_ORIGINAL_TEXT_UNAVAILABLE", 422)
    return pages


class SyncSourceIndexer:
    def __init__(self, cloud: PostgresCloudStore, canon: PostgresDataCanonStore, storage: ObjectStoragePort) -> None:
        self._cloud = cloud
        self._canon = canon
        self._storage = storage
        self._notebooks = PostgresNotebookRepository(cloud)

    def __call__(self, context: SyncContext, notebook_id: str, item: SyncItemInput, record: ObjectRecord) -> None:
        scope = (context.tenant_id, context.workspace_id)
        cap = CloudAccessContext(*scope, context.actor_id, "source.write")
        canon = CanonicalContext(*scope, context.actor_id, "source.write", context.trace_id)
        source_id = "src-" + record.object_id
        version_id = "sv-" + record.object_id
        index_id = "sync-text-index-" + record.object_id
        filename = f"동기화-{item.digest_sha256[:12]}.{_EXTENSIONS[item.content_type]}"
        try:
            self._notebooks.get(NotebookContext(*scope, context.actor_id, context.trace_id, context.policy_version), notebook_id)
            with self._cloud._transaction(cap) as connection:
                deleting = connection.execute(
                    "SELECT 1 FROM notebook_deletion_requests WHERE notebook_id=%s "
                    "AND state IN ('accepted','deleting','completed')",
                    (notebook_id,),
                ).fetchone()
                if deleting is not None:
                    raise SyncError("NOTEBOOK_NOT_FOUND", 404)
            content = self._storage.get(record.object_key)
            if len(content) != item.byte_size or hashlib.sha256(content).hexdigest() != item.digest_sha256:
                raise SyncError("SYNC_CONTENT_DIGEST_MISMATCH", 409)
            SourceIngestor().register_file(filename, item.content_type, content)
            pages = _original_pages(content, item.content_type)
            self._canon.register_uploaded_source(
                canon, notebook_id=notebook_id, source_id=source_id, source_version_id=version_id,
                object_id=record.object_id, filename=filename,
                digest_sha256=item.digest_sha256, byte_size=item.byte_size, content_type=item.content_type,
                created_at=datetime.now(timezone.utc), deletion_policy="retain_after_notebook_delete",
            )
            with self._cloud._transaction(cap) as connection:
                connection.execute(_SOURCE_ADVISORY_LOCK_SQL, (f"text-source-version|{scope[0]}|{scope[1]}|{source_id}",))
                if (connection.execute(_DELETED_SQL, (*scope, source_id)).fetchone() is not None
                    or connection.execute(_BOUND_SQL, (*scope, notebook_id, source_id, version_id)).fetchone() is None):
                    raise SyncError("SYNC_SOURCE_UNAVAILABLE", 409)
                state, revision = connection.execute("SELECT state,version FROM sources WHERE record_id=%s", (source_id,)).fetchone()
                if state == "ready" and connection.execute("SELECT 1 FROM index_versions WHERE record_id=%s", (index_id,)).fetchone():
                    return
                if state != "registered":
                    raise SyncError("SYNC_INDEX_STATE_INVALID", 409)
                checked = connection.execute(_TRANSITION_SQL, (
                    "Source", source_id, revision, "security_check", "sync-check-" + record.object_id,
                    "SYNC_ORIGINAL_TEXT_VALIDATED", context.trace_id, context.policy_version,
                )).fetchone()
                if checked is None or checked[2] != "succeeded":
                    raise SyncError("SYNC_INDEX_STATE_INVALID", 409)
                chunks = []
                kind = "source_pdf_verbatim" if item.content_type == "application/pdf" else "text_source_verbatim_fact"
                for page, body in pages:
                    for start in range(0, len(body), 1024):
                        passage = body[start:start + 1024]
                        if not passage.strip():
                            continue
                        suffix = hashlib.sha256(f"{version_id}|{page}|{start}".encode()).hexdigest()[:32]
                        chunk = {"chunk_id": "sync-chunk-" + suffix, "evidence_span_id": "sync-span-" + suffix,
                                 "source_id": source_id, "source_version_id": version_id,
                                 "page": page, "text": passage, "evidence_kind": kind}
                        chunks.append(chunk)
                        TextSourceService._insert(connection, context, _EVIDENCE_SQL, chunk["evidence_span_id"],
                            {"source_id": source_id, "source_version_id": version_id,
                             "page": page, "text": passage, "kind": kind}, version_id)
                TextSourceService._insert(connection, context, _INDEX_SQL, index_id,
                    {"source_id": source_id, "source_version_id": version_id, "strategy": "sync_original_text",
                     "chunks": chunks, "lineage": {"content_digest_sha256": item.digest_sha256}}, version_id)
                TextSourceService._make_ready(connection, context, source_id, version_id, int(checked[1]))
        except NotebookError as error:
            raise SyncError(error.code, error.status) from None
        except TextSourceError as error:
            raise SyncError(error.code, error.status) from None
        except SourceRejected:
            raise SyncError("SYNC_ORIGINAL_TEXT_UNAVAILABLE", 422) from None
        except (CanonError, CloudDatabaseError):
            raise SyncError("SYNC_INDEX_UNAVAILABLE", 503, retryable=True) from None
