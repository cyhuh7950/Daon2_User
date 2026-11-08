"""Daon 승인 지식 패키지 가져오기(시스템 관리자).

Daon 2 / 2.5 / 3 같은 생산자가 승인한 지식을 이 시스템에 들이는 정식 경로다. 승인 지식 목록·질문 선택이 읽는 구조
(knowledge_registrations + approved output_versions + ready Source/index)를 앱의 Studio 저장 구조와 같은 도우미로 한 트랜잭션에 만든다.

이 시스템은 가져온 지식의 검토·승인을 직접 하지 않는다. 승인은 생산자가 했다는 관리자 증명(`import.basis`)이며, 레코드에
`import.origin=admin_import`, 가져온 사람, 근거 설명을 남긴다. 같은 package_id를 같은 내용으로 다시 가져오면 아무것도 바꾸지 않고
기존 결과를 돌려주고, 다른 내용이면 거부한다(새 판본은 새 package_id).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .cloud_storage import CloudAccessContext, CloudDatabaseError
from .studio_workspace import StudioContext, StudioError
from .studio_workspace_postgres import PostgresStudioWorkspaceRepository as _Studio

PRODUCERS = frozenset({"daon2", "daon2_5", "daon3"})
CONTENT_TYPES = frozenset({"text/markdown", "text/plain"})
MAX_CONTENT_CHARS = 200_000
MAX_CHUNK_CHARS = 1_500
_PACKAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,31}$")
_CAPABILITY = "studio.knowledge_registration"
_OPERATION = "studio.knowledge_package_import"


class KnowledgePackageImportError(RuntimeError):
    def __init__(self, code: str, status: int = 400) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class KnowledgePackageImport:
    package_id: str
    producer: str
    producer_version: str
    title: str
    content: str
    effective_at: datetime
    expires_at: datetime
    basis: str
    content_type: str = "text/markdown"

    def validated(self, now: datetime) -> "KnowledgePackageImport":
        if _PACKAGE_ID.fullmatch(self.package_id) is None:
            raise KnowledgePackageImportError("KNOWLEDGE_PACKAGE_ID_INVALID")
        if self.producer not in PRODUCERS:
            raise KnowledgePackageImportError("KNOWLEDGE_PACKAGE_PRODUCER_INVALID")
        if _VERSION.fullmatch(self.producer_version) is None:
            raise KnowledgePackageImportError("KNOWLEDGE_PACKAGE_VERSION_INVALID")
        if self.content_type not in CONTENT_TYPES:
            raise KnowledgePackageImportError("KNOWLEDGE_PACKAGE_CONTENT_TYPE_INVALID")
        if not (1 <= len(self.title.strip()) <= 200) or not (1 <= len(self.basis.strip()) <= 500):
            raise KnowledgePackageImportError("KNOWLEDGE_PACKAGE_TEXT_INVALID")
        if not self.content.strip() or len(self.content) > MAX_CONTENT_CHARS:
            raise KnowledgePackageImportError("KNOWLEDGE_PACKAGE_CONTENT_INVALID")
        for stamp in (self.effective_at, self.expires_at):
            if stamp.tzinfo is None:
                raise KnowledgePackageImportError("KNOWLEDGE_PACKAGE_PERIOD_INVALID")
        if self.expires_at <= self.effective_at or self.expires_at <= now:
            raise KnowledgePackageImportError("KNOWLEDGE_PACKAGE_PERIOD_INVALID")
        return self


def split_chunks(content: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """제목(#, ##, ###) 경계로 나누고, 한 구간이 limit를 넘으면 빈 줄 단위로 더 나눈다. 모든 글자가 어느 한 구간에 들어간다."""
    sections: list[str] = []
    current: list[str] = []
    for line in content.splitlines():
        if re.match(r"^#{1,3} ", line) and current:
            sections.append("\n".join(current).strip())
            current = []
        current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    chunks: list[str] = []
    for section in sections:
        if not section:
            continue
        if len(section) <= limit:
            chunks.append(section)
            continue
        buffer = ""
        for paragraph in re.split(r"\n\s*\n", section):
            while len(paragraph) > limit:
                if buffer:
                    chunks.append(buffer)
                    buffer = ""
                chunks.append(paragraph[:limit])
                paragraph = paragraph[limit:]
            if buffer and len(buffer) + len(paragraph) + 2 > limit:
                chunks.append(buffer)
                buffer = ""
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if buffer:
            chunks.append(buffer)
    return chunks


class PostgresKnowledgePackageImporter:
    def __init__(self, cloud_store: Any, clock=None) -> None:  # type: ignore[no-untyped-def]
        self._cloud_store = cloud_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def import_package(self, context: StudioContext, request: KnowledgePackageImport) -> dict[str, object]:
        request = request.validated(self._clock())
        package_bytes = request.content.encode("utf-8")
        digest = hashlib.sha256(package_bytes).hexdigest()
        scope = (context.tenant_id, context.workspace_id, "knowledge-package-import", request.package_id)
        opaque = _Studio._opaque
        ids = {name: opaque(name, *scope) for name in (
            "settings", "generation", "output", "output-version", "source", "source-version", "knowledge-registration",
            "index-version")}
        chunks = split_chunks(request.content)
        try:
            with self._cloud_store._transaction(CloudAccessContext(
                    context.tenant_id, context.workspace_id, context.actor_id, _CAPABILITY)) as connection:
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("|".join(scope),))
                existing = connection.execute(
                    "SELECT canonical_json->>'package_digest',state FROM knowledge_registrations "
                    "WHERE tenant_id=%s AND workspace_id=%s AND canonical_json->>'package_id'=%s",
                    (context.tenant_id, context.workspace_id, request.package_id)).fetchall()
                if existing:
                    if len(existing) == 1 and existing[0][0] == digest and existing[0][1] == "registered":
                        return self._result(request, ids, digest, len(package_bytes), len(chunks), replay=True)
                    raise KnowledgePackageImportError("KNOWLEDGE_PACKAGE_CONFLICT", 409)
                self._write(connection, context, request, ids, digest, len(package_bytes), chunks)
                connection.execute(
                    "INSERT INTO audit_events (event_id,tenant_id,workspace_id,actor_id,action,target_type,target_id,outcome,"
                    "trace_id,policy_version,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,'succeeded',%s,%s,%s)",
                    (opaque("audit", *scope, context.trace_id), context.tenant_id, context.workspace_id, context.actor_id,
                     _OPERATION, "knowledge_registration", ids["knowledge-registration"], context.trace_id,
                     context.policy_version, json.dumps({"package_id": request.package_id, "producer": request.producer,
                                                         "package_digest": digest})))
                return self._result(request, ids, digest, len(package_bytes), len(chunks), replay=False)
        except (KnowledgePackageImportError, StudioError):
            raise
        except CloudDatabaseError as error:
            raise KnowledgePackageImportError(error.code, 503) from None

    @staticmethod
    def _result(request, ids, digest, size, chunk_count, *, replay):  # type: ignore[no-untyped-def]
        return {
            "package_id": request.package_id, "producer": request.producer, "producer_version": request.producer_version,
            "authority": "approved", "package_digest": digest, "byte_size": size, "chunks": chunk_count,
            "knowledge_registration_id": ids["knowledge-registration"], "output_version_id": ids["output-version"],
            "registered_source_version_id": ids["source-version"], "replayed": replay,
        }

    @staticmethod
    def _write(connection, context, request, ids, digest, size, chunks) -> None:  # type: ignore[no-untyped-def]
        insert, transition, opaque = _Studio._insert, _Studio._transition, _Studio._opaque
        scope = (context.tenant_id, context.workspace_id, "knowledge-package-import", request.package_id)
        origin = {"origin": "admin_import", "imported_by": context.actor_id, "basis": request.basis.strip()}
        settings = {"output_type": "knowledge_package", "title": request.title.strip(), "purpose": "approved_knowledge_import",
                    "model_selection": {"mode": "imported"}, "import": origin}
        insert(connection, context, "generation_settings_snapshots", ids["settings"], settings)
        insert(connection, context, "generation_requests", ids["generation"], settings, state="configuring",
               extra_columns=("generation_settings_snapshot_id",), extra_values=(ids["settings"],))
        generation_version = transition(connection, context, "GenerationRequest", ids["generation"], 1, "confirmed",
                                        opaque("transition", *scope, "confirmed"))
        transition(connection, context, "GenerationRequest", ids["generation"], generation_version, "submitted",
                   opaque("transition", *scope, "submitted"))
        insert(connection, context, "studio_outputs", ids["output"],
               {"output_type": "knowledge_package", "title": request.title.strip(), "purpose": "approved_knowledge_import"},
               extra_columns=("generation_request_id",), extra_values=(ids["generation"],))
        content = {"title": request.title.strip(), "body": request.content, "content_type": request.content_type}
        version_payload = {**settings, "content": content, "previous_version_id": None, "revision_type": "initial",
                           "change_reason": "approved_knowledge_import", "approval_required": False,
                           "metadata": {"output_type": "knowledge_package", "package_id": request.package_id}}
        insert(connection, context, "output_versions", ids["output-version"], version_payload, state="generating",
               extra_columns=("studio_output_id", "generation_settings_snapshot_id"),
               extra_values=(ids["output"], ids["settings"]))
        version = 1
        for target in ("draft", "review_requested", "in_review", "approved"):
            version = transition(connection, context, "OutputVersion", ids["output-version"], version, target,
                                 opaque("transition", *scope, f"output-{target}"))
        registration = {
            "output_version_id": ids["output-version"], "package_id": request.package_id, "producer": request.producer,
            "producer_version": request.producer_version, "authority": "approved", "package_digest": digest,
            "byte_size": size, "content_type": request.content_type,
            "effective_at": request.effective_at.isoformat(), "expires_at": request.expires_at.isoformat(),
            "import": origin,
        }
        source_payload = {"kind": "studio_output", "derived_output_version_id": ids["output-version"],
                          "filename": f"{request.package_id}.knowledge.md", "searchable": True, "import": origin}
        insert(connection, context, "sources", ids["source"], source_payload, state="registered")
        source_state = 1
        for target in ("security_check", "processing", "indexing", "ready"):
            source_state = transition(connection, context, "Source", ids["source"], source_state, target,
                                      opaque("transition", *scope, f"source-{target}"))
        insert(connection, context, "source_versions", ids["source-version"], source_payload,
               extra_columns=("source_id",), extra_values=(ids["source"],))
        index_chunks = []
        for number, text in enumerate(chunks, start=1):
            chunk_id = opaque("knowledge-chunk", *scope, str(number))
            span_id = opaque("knowledge-span", *scope, str(number))
            insert(connection, context, "evidence_spans", span_id,
                   {"source_id": ids["source"], "source_version_id": ids["source-version"],
                    "output_version_id": ids["output-version"], "page": number, "text": text,
                    "kind": "approved_knowledge_snapshot"},
                   extra_columns=("source_version_id",), extra_values=(ids["source-version"],))
            index_chunks.append({"chunk_id": chunk_id, "source_id": ids["source"], "source_version_id": ids["source-version"],
                                 "page": number, "text": text, "evidence_span_id": span_id})
        insert(connection, context, "index_versions", ids["index-version"],
               {"source_id": ids["source"], "source_version_id": ids["source-version"],
                "strategy": "approved_knowledge_snapshot", "chunks": index_chunks,
                "lineage": {"output_version_id": ids["output-version"],
                            "knowledge_registration_id": ids["knowledge-registration"]}},
               extra_columns=("source_version_id",), extra_values=(ids["source-version"],))
        insert(connection, context, "knowledge_registrations", ids["knowledge-registration"], registration,
               state="requested", extra_columns=("output_version_id", "registered_source_version_id"),
               extra_values=(ids["output-version"], ids["source-version"]))
        transition(connection, context, "KnowledgeRegistration", ids["knowledge-registration"], 1, "registered",
                   opaque("transition", *scope, "registered"))


def default_period(now: datetime, years: int = 10) -> tuple[datetime, datetime]:
    return now - timedelta(minutes=1), now + timedelta(days=365 * years)
