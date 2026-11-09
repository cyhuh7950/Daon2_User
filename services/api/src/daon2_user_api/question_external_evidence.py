"""노트북에서 선택한 업무 패키지의 Daon2-RAG 근거를 질문 근거로 가져온다(WO-K3 1단계).

서버에 저장된 선택만 쓰고, 호출 직전에 승인 문서 수를 다시 확인한다. 응답 본문은 신뢰하지 않는 데이터로만 다룬다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from .document_index_postgres import IndexedEvidenceChunk
from .knowledge_connector_service import ConnectorError
from .knowledge_scope_service import KnowledgeScopeContext, KnowledgeScopeError
from .mcp_client import McpError

PER_PACKAGE_LIMIT = 5
EXTERNAL_LIMIT = 5
LOCAL_LIMIT_WITH_EXTERNAL = 5
_TEXT_FIELDS = ("document_id", "version_id", "run_id", "block_id", "text")


class ExternalEvidenceError(RuntimeError):
    def __init__(self, code: str, status: int = 503, retryable: bool = False) -> None:
        super().__init__(code)
        self.code, self.status, self.retryable = code, status, retryable


@dataclass(frozen=True, slots=True)
class ExternalEvidence:
    chunk: IndexedEvidenceChunk
    connector_id: str
    project_id: str
    project_name: str
    work_package_id: str
    work_package_name: str
    document_id: str
    document_version_id: str
    understanding_run_id: str
    block_id: str
    page: int
    document_name: str | None
    text: str


def merge_evidence(local: tuple[IndexedEvidenceChunk, ...], external: tuple[ExternalEvidence, ...]) -> tuple[IndexedEvidenceChunk, ...]:
    """점수 척도가 달라 점수로 섞지 않는다. 승인 지식이 있으면 소스와 승인 지식을 각각 최대 5건 쓴다."""
    if not external:
        return local
    return (*local[:LOCAL_LIMIT_WITH_EXTERNAL], *(item.chunk for item in external[:EXTERNAL_LIMIT]))


def _unavailable() -> ExternalEvidenceError:
    return ExternalEvidenceError("KNOWLEDGE_EVIDENCE_UNAVAILABLE", 503, True)


def _parsed(row: Any) -> tuple[Mapping[str, Any], float]:
    if not isinstance(row, Mapping) or any(not isinstance(row.get(name), str) or not row[name] for name in _TEXT_FIELDS):
        raise _unavailable()
    page, similarity = row.get("page_no"), row.get("similarity")
    if type(page) is not int or page < 1 or isinstance(similarity, bool) or not isinstance(similarity, (int, float)):
        raise _unavailable()
    return row, float(similarity)


class NotebookKnowledgeEvidence:
    def __init__(self, scopes: Any, connectors: Any) -> None:
        self._scopes = scopes
        self._connectors = connectors

    def search(self, context: Any, question: str) -> tuple[ExternalEvidence, ...]:
        if context.notebook_id is None:
            return ()
        scope_context = KnowledgeScopeContext(context.tenant_id, context.workspace_id, context.actor_id, context.trace_id, context.policy_version)
        try:
            selected = self._scopes.selection(scope_context, context.notebook_id)["items"]
            if not selected:
                return ()
            connector_context, connector_id, approved = self._scopes.evidence_target(scope_context)
            found: dict[str, ExternalEvidence] = {}
            for item in selected:
                if (item["project_id"], item["work_package_id"]) not in approved:
                    continue
                result = self._connectors.call(connector_context, connector_id, "search_document_evidence", {
                    "project_id": item["project_id"], "work_package_id": item["work_package_id"], "question": question, "limit": PER_PACKAGE_LIMIT})
                rows = result.structured.get("result") if isinstance(result.structured, Mapping) and not result.is_error else None
                if not isinstance(rows, list):
                    raise _unavailable()
                for row, similarity in map(_parsed, rows):
                    evidence = self._evidence(connector_id, item, row, similarity)
                    current = found.get(evidence.block_id)
                    if current is None or current.chunk.score < similarity:
                        found[evidence.block_id] = evidence
        except KnowledgeScopeError as error:
            if error.code == "KNOWLEDGE_CONNECTOR_NOT_CONFIGURED":
                raise ExternalEvidenceError(error.code, error.status) from None
            raise _unavailable() from None
        except (McpError, ConnectorError):
            raise _unavailable() from None
        return tuple(sorted(found.values(), key=lambda value: (-value.chunk.score, value.block_id))[:EXTERNAL_LIMIT])

    @staticmethod
    def _evidence(connector_id: str, item: Mapping[str, str], row: Mapping[str, Any], similarity: float) -> ExternalEvidence:
        name = row.get("document_name")
        chunk_id = "ext-" + hashlib.sha256("|".join((connector_id, row["version_id"], row["block_id"])).encode("utf-8")).hexdigest()[:32]
        chunk = IndexedEvidenceChunk(chunk_id, row["document_id"], row["version_id"], row["page_no"], row["text"], row["block_id"], similarity)
        return ExternalEvidence(chunk, connector_id, item["project_id"], item["project_name"], item["work_package_id"], item["work_package_name"],
                                row["document_id"], row["version_id"], row["run_id"], row["block_id"], row["page_no"], name if isinstance(name, str) and name else None, row["text"])
