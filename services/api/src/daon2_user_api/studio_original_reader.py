"""Studio 원본 파일 리더. 노트북에 연결된 활성 소스 판의 원본을 읽는다.

질문 답변의 원본 읽기(question_answering_postgres: ObjectKeyPolicy.validate_final, 크기·sha256 확인)와
StudioSourceReader의 범위(조직·워크스페이스, 삭제된 소스 제외)를 따른다. 노트북 연결·권한 검사는
생성 범위 검사(PostgresStudioWorkspaceRepository._require_generation_scope)를 그대로 쓴다.
"""

from __future__ import annotations

import hashlib
import re
from contextlib import nullcontext

from .authorization import Action
from .cloud_storage import CloudAccessContext
from .object_queue import ObjectKeyPolicy, ObjectQueueError, ObjectStorageError
from .studio_workspace import StudioContext, StudioError
from .table_reader import TableLimits

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_CONTENT_TYPE = "text/csv"
_FORMATS = {".xlsx": ("xlsx", XLSX_CONTENT_TYPE), ".csv": ("csv", CSV_CONTENT_TYPE)}
_DOCX = {".docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")

_ORIGINAL_SQL = (
    "SELECT COALESCE(sv.canonical_json->>'filename',s.canonical_json->>'filename',''),o.object_key,o.digest_sha256,"
    "o.byte_size,o.content_type FROM source_versions sv "
    "JOIN sources s ON s.tenant_id=sv.tenant_id AND s.workspace_id=sv.workspace_id AND s.record_id=sv.source_id "
    "JOIN object_records o ON o.tenant_id=sv.tenant_id AND o.workspace_id=sv.workspace_id AND o.object_id=sv.object_id "
    "WHERE sv.tenant_id=%s AND sv.workspace_id=%s AND sv.record_id=%s AND s.state='ready' AND o.status='completed' "
    "AND EXISTS(SELECT 1 FROM notebook_bindings nb WHERE nb.tenant_id=sv.tenant_id AND nb.workspace_id=sv.workspace_id "
    "AND nb.notebook_id=%s AND nb.binding_kind='source' AND nb.record_id=sv.source_id AND nb.version_id=sv.record_id "
    "AND NOT EXISTS(SELECT 1 FROM notebook_source_unbindings u WHERE u.tenant_id=nb.tenant_id AND u.workspace_id=nb.workspace_id "
    "AND u.notebook_id=nb.notebook_id AND u.source_id=nb.record_id AND u.source_version_id=nb.version_id)) "
    "AND NOT EXISTS(SELECT 1 FROM deletion_requests d WHERE d.tenant_id=sv.tenant_id AND d.workspace_id=sv.workspace_id "
    "AND d.source_id=sv.source_id AND d.source_active=false)"
)


class StudioOriginalReader:
    def __init__(self, cloud_store, object_storage, *, scope=None, limits: TableLimits = TableLimits()) -> None:  # type: ignore[no-untyped-def]
        self._store = cloud_store
        self._storage = object_storage
        if scope is None:
            from .studio_workspace_postgres import PostgresStudioWorkspaceRepository
            scope = PostgresStudioWorkspaceRepository(None)  # 범위 검사만 쓴다(PostgresStudioV2Repository와 같은 방식)
        self._scope = scope
        self._limits = limits

    def read(self, context: StudioContext, source_version_id: str, *, action: Action = Action.GENERATE) -> tuple[bytes, str, str, str]:
        """(content, file_name, source_format, sha256). 그 노트북·워크스페이스의 활성 소스 판만 읽는다."""
        return self._read(context, source_version_id, _FORMATS, self._limits.max_bytes, "TABLE_TOO_LARGE", action)

    def read_docx(self, context: StudioContext, source_version_id: str, *, action: Action, connection=None) -> bytes:  # type: ignore[no-untyped-def]
        return self._read(context, source_version_id, _DOCX, 32 * 1024 * 1024, "STUDIO_SOURCE_TOO_LARGE", action, connection)[0]

    def _read(self, context: StudioContext, source_version_id: str, formats: dict[str, tuple[str, str]], byte_limit: int,
              size_error: str, action: Action, connection=None) -> tuple[bytes, str, str, str]:  # type: ignore[no-untyped-def]
        if context.notebook_id is None:
            raise StudioError("NOTEBOOK_SCOPE_REQUIRED", 400)
        if not isinstance(source_version_id, str) or not _SAFE_ID.fullmatch(source_version_id):
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        scope = CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, "studio.v2.read")
        transaction = self._store._transaction(scope) if connection is None else nullcontext(connection)
        with transaction as connection:
            # 노트북 연결·현재 권한·소스 접근 거부·노트북 삭제를 생성 범위 검사와 같은 규칙으로 확인한다.
            self._scope._require_generation_scope(connection, context, (source_version_id,), action=action)
            row = connection.execute(_ORIGINAL_SQL, (context.tenant_id, context.workspace_id, source_version_id,
                                                     context.notebook_id)).fetchone()
        if row is None:
            raise StudioError("STUDIO_SOURCE_UNAVAILABLE", 409)
        file_name, object_key, digest, byte_size, content_type = str(row[0] or ""), str(row[1]), str(row[2]), int(row[3]), str(row[4] or "")
        suffix = file_name.lower()[file_name.rfind("."):] if "." in file_name else ""
        fmt = formats.get(suffix)
        if fmt is None or content_type.split(";", 1)[0].strip().lower() != fmt[1]:
            raise StudioError("STUDIO_INPUT_INVALID", 400)
        if byte_size > byte_limit:
            raise StudioError(size_error, 422)  # 받기 전에 거부해 메모리를 아낀다
        try:
            ObjectKeyPolicy().validate_final(CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, "object.read"),
                                             "source", object_key)
            content = self._storage.get(object_key)
        except ObjectStorageError as error:
            if error.retryable:
                raise StudioError("OBJECT_STORAGE_UNAVAILABLE", 503) from None
            raise StudioError("STUDIO_SOURCE_UNAVAILABLE", 409) from None
        except ObjectQueueError:
            raise StudioError("STUDIO_SOURCE_UNAVAILABLE", 409) from None
        actual = hashlib.sha256(content).hexdigest()
        if len(content) != byte_size or actual != digest.removeprefix("sha256:"):
            raise StudioError("STUDIO_SOURCE_UNAVAILABLE", 409)
        return content, file_name, fmt[0], actual
