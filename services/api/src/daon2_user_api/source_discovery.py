"""자료 찾기 · 빠른 찾기(WO-N1 N1-7, NB4-F1). 결정 D-02: 웹은 없고 내부(승인 지식·지식 연결)만 찾는다. 정정 C-6.

범위(scope)
- knowledge: Daon2 승인 지식. Daon2-RAG `list_knowledge_scopes`(승인 업무 패키지 목록)에서 이름이 맞는 패키지를 고르고,
  Daon2 연결의 `approved_knowledge_search`로 패키지 안 승인 자산을 찾는다. 후보는 업무 패키지(add_scope)다.
- documents: Daon2-RAG 문서. 노트북이 고른 업무 패키지(없으면 이름이 맞는 승인 패키지)에서 `search_document_evidence`로 찾는다.
  후보는 문서(add_source)이고, 추가는 `get_document_text`로 본문을 받아 텍스트 소스(text_source)로 등록한다.

규칙
- 지식 연결 호출은 모두 knowledge_connector_service.call(호출 직전 ConnectorEgressGate 판정)을 거친다. 다른 경로는 없다.
- 검색 한 번의 도구 호출은 최대 MAX_TOOL_CALLS(4)회, 후보는 최대 MAX_CANDIDATES(20)개다.
- 허용 도구에 없는 도구는 부르지 않고 그 범위를 사용할 수 없음(TOOL_NOT_ALLOWED)으로 돌려준다. 가상(시험용) 연결은 쓰지 않는다.
- 한 범위가 실패해도 다른 범위의 결과는 돌려준다(unavailable에 DISCOVERY_CONNECTOR_FAILED).
- 자동 추가는 없다. 추가는 사람이 고른 ref 하나씩이며, 서버가 ref를 다시 확인한다.
- 감사 기록·오류 응답·로그에는 검색어·본문·연결 주소를 남기지 않는다(범위·개수·ID·결과 코드만).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .audit import ActorType, AuditEventDraft, AuditOutcome
from .cloud_storage import CloudDatabaseError
from .knowledge_connector_service import ConnectorContext, ConnectorError
from .knowledge_scope_service import MAX_SELECTED, KnowledgeScopeContext, KnowledgeScopeError, _approved, _usable_row
from .mcp_client import McpError
from .question_external_evidence import DAON2_APPROVED, MAX_SEARCH_QUESTION_CHARS, NotebookKnowledgeEvidence
from .source_upload import SourceUploadError
from .text_source import TEXT_SOURCE_MAX_BYTES, TextSourceError

DiscoveryContext = KnowledgeScopeContext  # tenant_id·workspace_id·actor_id·trace_id·policy_version

SCOPES = ("knowledge", "documents")
MAX_QUERY_CHARS = 500
MAX_CANDIDATES = 20
MAX_TOOL_CALLS = 4
PREVIEW_CHARS = 300
TITLE_CHARS = 200
LABEL_CHARS = 120
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
# 텍스트 소스 상한(NB4-F1b 이후 2 MiB)과 같다. 둘 중 작은 값을 넘으면 같은 413으로 막는다.
EFFECTIVE_DOCUMENT_BYTES = min(MAX_DOCUMENT_BYTES, TEXT_SOURCE_MAX_BYTES)
CATALOG_PAGE_SIZE = 50
EVIDENCE_LIMIT = 5
ASSET_LIMIT = 2
ASSET_QUERY_CHARS = 200
DOCUMENT_PAGE_SIZE = 200      # list_approved_documents 최대(Daon2-RAG _MAX_DOCUMENT_PAGE)
MAX_DOCUMENT_PAGES = 10
TEXT_PAGE_BLOCKS = 100        # get_document_text 최대(Daon2-RAG _MAX_TEXT_BLOCK_PAGE)
MAX_TEXT_PAGES = 64
DISCOVERY_ORIGIN = "research"

RAG, DAON2 = "daon2_rag", "daon2"
# 범위별로 필요한 (연결 종류, 도구). 문서 후보는 추가(본문 읽기)까지 할 수 있어야 의미가 있으므로 읽기 도구도 요구한다.
SEARCH_TOOLS: Mapping[str, tuple[tuple[str, frozenset[str]], ...]] = {
    "knowledge": ((DAON2, frozenset({"approved_knowledge_search"})), (RAG, frozenset({"list_knowledge_scopes"}))),
    "documents": ((RAG, frozenset({"search_document_evidence", "list_approved_documents", "get_document_text"})),),
}
ADD_TOOLS: Mapping[str, tuple[str, frozenset[str]]] = {
    "knowledge_package": (RAG, frozenset({"list_knowledge_scopes"})),
    "document": (RAG, frozenset({"list_approved_documents", "get_document_text"})),
}
REF_SCOPE = {"knowledge_package": "knowledge", "document": "documents"}
# 그 패키지만 건너뛰는 응답(지식 미준비·범위 밖·허용 도구 아님·한도). 장애로 보지 않는다.
SKIP_CODES = frozenset({"NOT_READY", "SCOPE_FORBIDDEN", "MCP_FORBIDDEN", "MCP_TOOL_NOT_ALLOWED", "MCP_RATE_LIMITED"})
FAILED = "DISCOVERY_CONNECTOR_FAILED"
SOURCE_DISCOVERY_PUBLIC_CODES = frozenset({
    "NOTEBOOK_NOT_FOUND", "DISCOVERY_REQUEST_INVALID", "DISCOVERY_REF_INVALID", "DISCOVERY_SCOPE_UNAVAILABLE", FAILED,
    "DISCOVERY_REF_NOT_FOUND", "DISCOVERY_SCOPE_LIMIT", "DISCOVERY_DOCUMENT_TOO_LARGE", "DISCOVERY_DOCUMENT_CHANGED",
    "DISCOVERY_DOCUMENT_EMPTY", "DISCOVERY_DOCUMENT_INVALID", "DISCOVERY_UNAVAILABLE",
})
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_TEXT_ERRORS = {"TEXT_SOURCE_TOO_LARGE": ("DISCOVERY_DOCUMENT_TOO_LARGE", 413), "TEXT_SOURCE_EMPTY": ("DISCOVERY_DOCUMENT_EMPTY", 422)}


class DiscoveryError(RuntimeError):
    def __init__(self, code: str, status: int = 400, unavailable: list[dict[str, str]] | None = None, calls: int = 0,
                 diagnostic: dict[str, str] | None = None) -> None:
        super().__init__(code)
        self.code, self.status = code, status
        self.unavailable = unavailable or []
        self.calls = calls
        # 연결 실패 진단(실패한 도구 이름·오류 코드, 안전한 토큰만). 응답 details.connector로 나간다.
        self.diagnostic = diagnostic


_SAFE_DIAGNOSTIC = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _diagnostic(tool: str, code: object) -> dict[str, str]:
    safe = code if isinstance(code, str) and _SAFE_DIAGNOSTIC.fullmatch(code) else "UNKNOWN"
    return {"tool": tool, "code": safe}


class _Malformed(Exception):
    """연결 응답의 모양이 계약과 다르다(신뢰하지 않는 데이터)."""


class CallBudget:
    """도구 호출 수 상한. take()가 False면 더 부르지 않는다. 심층 조사(NB4-F2)는 하나를 여러 검색에 나눠 쓴다."""

    def __init__(self, limit: int) -> None:
        self.limit, self.used = limit, 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


class _SearchBudget(CallBudget):
    """검색 한 번의 상한(4)과 함께 쓰는 상위 상한(있으면)을 같이 센다."""

    def __init__(self, limit: int, shared: CallBudget | None) -> None:
        super().__init__(min(limit, shared.remaining) if shared is not None else limit)
        self._shared = shared

    def take(self) -> bool:
        if not super().take():
            return False
        if self._shared is not None and not self._shared.take():
            self.used -= 1
            self.limit = self.used
            return False
        return True


@dataclass(frozen=True)
class DiscoveryResult:
    candidates: list[dict[str, Any]]
    unavailable: list[dict[str, str]]
    ran: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    calls: int = 0

    def data(self) -> dict[str, Any]:
        return {"candidates": self.candidates, "unavailable": self.unavailable}


@dataclass(frozen=True)
class AddResult:
    data: dict[str, Any]
    audit: dict[str, Any] = field(default_factory=dict)


def _clean(value: Any, limit: int) -> str:
    """연결이 준 글(신뢰하지 않음): 제어 문자를 빼고 공백을 하나로 모은 뒤 자른다."""
    text = " ".join(_CONTROL.sub(" ", value).split()) if isinstance(value, str) else ""
    return text[:limit]


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def _tokens(query: str) -> list[str]:
    return [token for token in dict.fromkeys(query.lower().split()) if token]


def _name_score(tokens: Sequence[str], package: Mapping[str, Any]) -> int:
    name = f"{package.get('project_name') or ''} {package.get('work_package_name') or ''}".lower()
    return sum(1 for token in tokens if token in name)


def _ranked(packages: Sequence[Mapping[str, Any]], tokens: Sequence[str]) -> list[tuple[int, Mapping[str, Any]]]:
    scored = [(_name_score(tokens, item), index, item) for index, item in enumerate(packages)]
    return [(score, item) for score, _index, item in sorted(scored, key=lambda row: (-row[0], row[1]))]


def _structured(result: Any) -> Mapping[str, Any]:
    structured = getattr(result, "structured", None)
    if getattr(result, "is_error", False) or not isinstance(structured, Mapping):
        raise _Malformed()
    return structured


def _ids_ok(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 256 and not _CONTROL.search(value)


def parse_ref(ref: Any) -> dict[str, str]:
    """화면이 돌려준 ref(신뢰하지 않음)의 모양만 확인한다. 접근 권한은 add가 다시 확인한다."""
    if not isinstance(ref, Mapping) or ref.get("kind") not in REF_SCOPE:
        raise DiscoveryError("DISCOVERY_REF_INVALID", 400)
    keys = ["kind", "project_id", "work_package_id"] + (["document_id", "document_version"] if ref["kind"] == "document" else [])
    if set(ref) != set(keys) or not all(_ids_ok(ref[key]) for key in keys[1:]):
        raise DiscoveryError("DISCOVERY_REF_INVALID", 400)
    return {key: str(ref[key]) for key in keys}


class DiscoverySearcher:
    """빠른 찾기의 검색 단계. 심층 조사(NB4-F2)가 하위 질문마다 다시 쓴다.

    search(context, query, scopes, selected=노트북 승인 지식 범위 항목, budget=공유 상한) -> DiscoveryResult
    """

    def __init__(self, connectors: Any, shared_connector_tenant: str | None = None) -> None:
        self._connectors = connectors
        self._shared_connector_tenant = shared_connector_tenant

    # ------------------------------------------------------------ 연결 고르기
    def connector_context(self, context: DiscoveryContext) -> ConnectorContext:
        return ConnectorContext(context.tenant_id, context.actor_id, context.trace_id, context.workspace_id, context.policy_version,
                                self._shared_connector_tenant)

    def connector_rows(self, context: DiscoveryContext) -> list[Mapping[str, Any]]:
        try:
            rows = self._connectors.list(self.connector_context(context))
        except (CloudDatabaseError, ConnectorError, McpError):
            raise DiscoveryError("DISCOVERY_UNAVAILABLE", 503) from None
        # 가상(시험용) 서버는 승인 지식이 아니므로 쓰지 않는다(지식 범위·질문 도구와 같다).
        return [row for row in rows if isinstance(row, Mapping) and not row.get("virtual")]

    @staticmethod
    def pick(rows: Sequence[Mapping[str, Any]], kind: str, tools: frozenset[str]) -> tuple[str | None, str | None]:
        """(connector_id, None) 또는 (None, 사용할 수 없는 이유). 확인된 연결 중 필요한 도구가 모두 허용된 첫 연결."""
        same = [row for row in rows if row.get("kind") == kind]
        if not same:
            return None, "CONNECTOR_NOT_CONFIGURED"
        ready = [row for row in same if row.get("status") == "verified"]
        if not ready:
            return None, "CONNECTOR_DISABLED" if any(row.get("status") == "disabled" for row in same) else "CONNECTOR_NOT_READY"
        usable = next((row for row in ready if tools <= set(row.get("allowed_tools") or ())), None)
        return (str(usable["connector_id"]), None) if usable is not None else (None, "TOOL_NOT_ALLOWED")

    def resolve(self, rows: Sequence[Mapping[str, Any]], scope: str) -> tuple[dict[str, str], str | None]:
        found: dict[str, str] = {}
        for kind, tools in SEARCH_TOOLS[scope]:
            connector_id, reason = self.pick(rows, kind, tools)
            if reason is not None:
                return {}, reason
            found[kind] = str(connector_id)
        return found, None

    # ------------------------------------------------------------ 검색
    def search(self, context: DiscoveryContext, query: str, scopes: Sequence[str], *, selected: Sequence[Mapping[str, Any]] = (),
               budget: CallBudget | None = None) -> DiscoveryResult:
        requested = list(dict.fromkeys(scopes))
        rows = self.connector_rows(context)
        unavailable: dict[str, str] = {}
        runnable: dict[str, dict[str, str]] = {}
        for scope in requested:
            connectors, reason = self.resolve(rows, scope)
            if reason is None:
                runnable[scope] = connectors
            else:
                unavailable[scope] = reason
        limit = _SearchBudget(MAX_TOOL_CALLS, budget)
        state = _Search(self._connectors, self.connector_context(context), query, list(selected))
        found: dict[str, list[dict[str, Any]]] = {}
        ran, failed = [], []
        # 문서 범위를 먼저 돌린다: 필요한 호출 수가 고른 패키지 수로 정해져 있어, 남은 몫을 승인 지식이 쓴다.
        order = [scope for scope in ("documents", "knowledge") if scope in runnable]
        for index, scope in enumerate(order):
            share = _SearchBudget(limit.remaining // (len(order) - index), None)
            try:
                found[scope] = state.run(scope, runnable[scope], _Linked(share, limit))
                ran.append(scope)
            except (McpError, ConnectorError, _Malformed):
                unavailable[scope] = FAILED
                failed.append(scope)
        candidates = _interleave([found.get(scope, []) for scope in requested])[:MAX_CANDIDATES]
        return DiscoveryResult(candidates, [{"scope": scope, "reason": unavailable[scope]} for scope in requested if scope in unavailable],
                               tuple(ran), tuple(failed), limit.used)


class _Linked:
    """범위 몫과 검색 전체 상한을 함께 센다."""

    def __init__(self, share: CallBudget, whole: CallBudget) -> None:
        self._share, self._whole = share, whole

    @property
    def remaining(self) -> int:
        return min(self._share.remaining, self._whole.remaining)

    def take(self) -> bool:
        if self.remaining < 1:
            return False
        if not self._whole.take():
            return False
        self._share.take()
        return True


def _interleave(groups: Iterable[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    queues = [list(group) for group in groups]
    out: list[dict[str, Any]] = []
    while any(queues):
        for queue in queues:
            if queue:
                out.append(queue.pop(0))
    return out


class _Search:
    def __init__(self, connectors: Any, connector_context: ConnectorContext, query: str, selected: list[Mapping[str, Any]]) -> None:
        self._connectors = connectors
        self._context = connector_context
        self._query = query
        self._tokens = _tokens(query)
        self._selected = selected
        self._catalog: list[Mapping[str, Any]] | None = None

    def run(self, scope: str, connectors: Mapping[str, str], budget: Any) -> list[dict[str, Any]]:
        return self._documents(connectors[RAG], budget) if scope == "documents" else self._knowledge(connectors[RAG], connectors[DAON2], budget)

    def _call(self, budget: Any, connector_id: str, tool: str, arguments: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if not budget.take():
            return None
        return _structured(self._connectors.call(self._context, connector_id, tool, arguments))

    def _catalog_rows(self, rag: str, budget: Any) -> list[Mapping[str, Any]] | None:
        """승인 업무 패키지(승인 문서 1건 이상) 첫 쪽. 호출 상한 때문에 다음 쪽은 읽지 않는다."""
        if self._catalog is None:
            page = self._call(budget, rag, "list_knowledge_scopes", {"limit": CATALOG_PAGE_SIZE})
            if page is None:
                return None
            if not isinstance(page.get("scopes"), list):
                raise _Malformed()
            self._catalog = [row for row in page["scopes"] if _usable_row(row) and _approved(row)]
        return self._catalog

    # documents ----------------------------------------------------------------
    def _documents(self, rag: str, budget: Any) -> list[dict[str, Any]]:
        if self._selected:
            packages = [item for _score, item in _ranked(self._selected, self._tokens)]
        else:
            catalog = self._catalog_rows(rag, budget) or []
            ranked = _ranked(catalog, self._tokens)
            matched = [item for score, item in ranked if score > 0]
            packages = matched or [item for _score, item in ranked]
        best: dict[str, dict[str, Any]] = {}
        succeeded, errors = 0, 0
        for package in packages:
            if budget.remaining < 1:
                break
            try:
                page = self._call(budget, rag, "search_document_evidence", {
                    "project_id": package["project_id"], "work_package_id": package["work_package_id"],
                    "question": self._query[:MAX_SEARCH_QUESTION_CHARS], "limit": EVIDENCE_LIMIT})
                rows = None if page is None else page.get("result")
                if not isinstance(rows, list):
                    raise _Malformed()
            except McpError as error:
                errors += error.code not in SKIP_CODES  # 지식 미준비·범위 밖은 그 패키지만 건너뛴다
                continue
            except (ConnectorError, _Malformed):
                errors += 1
                continue
            succeeded += 1
            for row in rows:
                self._keep_document(best, package, row)
        if errors and not succeeded:
            raise _Malformed()  # 시도한 패키지가 모두 실패했다: 이 범위는 실패로 알린다
        ordered = sorted(best.values(), key=lambda item: -item["_score"])
        return [{key: value for key, value in item.items() if key != "_score"} for item in ordered]

    @staticmethod
    def _keep_document(best: dict[str, dict[str, Any]], package: Mapping[str, Any], row: Any) -> None:
        if not isinstance(row, Mapping) or not all(_ids_ok(row.get(key)) for key in ("document_id", "version_id")):
            return
        similarity, page = row.get("similarity"), row.get("page_no")
        score = float(similarity) if isinstance(similarity, (int, float)) and not isinstance(similarity, bool) else 0.0
        document_id = str(row["document_id"])
        current = best.get(document_id)
        if current is not None and current["_score"] >= score:
            return
        page_text = f"{page}쪽 " if type(page) is int and page >= 1 else ""
        work_package = _clean(package.get("work_package_name"), LABEL_CHARS) or "업무 패키지"
        best[document_id] = {
            "candidate_id": "doc-" + _digest(str(package["project_id"]), str(package["work_package_id"]), document_id),
            "kind": "document", "title": _clean(row.get("document_name"), TITLE_CHARS) or "문서",
            "origin_label": f"문서 근거 · {work_package}"[:LABEL_CHARS],
            "reason": f"{page_text}내용이 검색어와 관련 있습니다",
            "preview": _clean(row.get("text"), PREVIEW_CHARS), "action": "add_source",
            "ref": {"kind": "document", "project_id": str(package["project_id"]), "work_package_id": str(package["work_package_id"]),
                    "document_id": document_id, "document_version": str(row["version_id"])},
            "_score": score,
        }

    # knowledge ----------------------------------------------------------------
    def _knowledge(self, rag: str, daon2: str, budget: Any) -> list[dict[str, Any]]:
        catalog = self._catalog_rows(rag, budget)
        if catalog is None:
            return []
        ranked = _ranked(catalog, self._tokens)
        assets: dict[tuple[str, str], list[str]] = {}
        for _score, package in ranked:
            if budget.remaining < 1:
                break
            scope = {**({"tenant_id": package["tenant_id"]} if isinstance(package.get("tenant_id"), str) and package["tenant_id"] else {}),
                     "project_id": package["project_id"], "work_package_id": package["work_package_id"]}
            try:
                found = self._call(budget, daon2, "approved_knowledge_search",
                                   {"scope": scope, "query": self._query[:ASSET_QUERY_CHARS], "limit": ASSET_LIMIT})
            except (McpError, ConnectorError, _Malformed):
                continue  # 승인 자산 검색이 안 돼도 패키지 이름 일치 후보는 그대로 쓴다
            if found is None:
                break
            titles = self._asset_titles(found)
            if titles:
                assets[(package["project_id"], package["work_package_id"])] = titles
        out = []
        for index, (score, package) in enumerate(ranked):
            key = (package["project_id"], package["work_package_id"])
            titles = assets.get(key, [])
            if not titles and score < 1:
                continue
            title = _clean(f"{package['project_name']} / {package['work_package_name']}", TITLE_CHARS)
            preview = " · ".join(titles) if titles else f"{title} · 승인 문서 {package['approved_document_count']}건"
            out.append(((0 if titles else 1, -score, index), {
                "candidate_id": "kp-" + _digest(*key), "kind": "knowledge_package", "title": title, "origin_label": "승인 지식",
                "reason": f"승인 자산 {len(titles)}건이 검색어와 관련 있습니다" if titles else "업무 패키지 이름이 검색어와 일치합니다",
                "preview": _clean(preview, PREVIEW_CHARS), "action": "add_scope",
                "ref": {"kind": "knowledge_package", "project_id": key[0], "work_package_id": key[1]}}))
        return [item for _key, item in sorted(out, key=lambda row: row[0])]

    @staticmethod
    def _asset_titles(found: Mapping[str, Any]) -> list[str]:
        if found.get("provenance") != DAON2_APPROVED or not isinstance(found.get("assets"), list):
            return []
        titles = []
        for row in found["assets"]:
            if isinstance(row, Mapping) and NotebookKnowledgeEvidence._asset_usable(row):  # noqa: SLF001
                name = next((row[key] for key in ("asset_name", "title", "name") if isinstance(row.get(key), str) and row[key].strip()), "승인 자산")
                titles.append(_clean(name, 80))
        return titles


class SourceDiscoveryService:
    def __init__(self, connectors: Any, scopes: Any, text_sources: Any = None, shared_connector_tenant: str | None = None) -> None:
        self._connectors = connectors
        self._scopes = scopes
        self._text_sources = text_sources
        self.searcher = DiscoverySearcher(connectors, shared_connector_tenant)

    def _selection(self, context: DiscoveryContext, notebook_id: str) -> list[Mapping[str, Any]]:
        try:
            return list(self._scopes.selection(context, notebook_id)["items"])
        except KnowledgeScopeError as error:
            if error.code == "NOTEBOOK_NOT_FOUND":
                raise DiscoveryError("NOTEBOOK_NOT_FOUND", 404) from None
            raise DiscoveryError("DISCOVERY_UNAVAILABLE", 503) from None

    # ------------------------------------------------------------ 검색
    def search(self, context: DiscoveryContext, notebook_id: str, query: Any, scopes: Any) -> DiscoveryResult:
        if (not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS or not isinstance(scopes, (list, tuple))
                or not scopes or len(set(scopes)) != len(scopes) or any(scope not in SCOPES for scope in scopes)):
            raise DiscoveryError("DISCOVERY_REQUEST_INVALID", 400)
        selected = self._selection(context, notebook_id)
        result = self.searcher.search(context, query.strip(), list(scopes), selected=selected)
        if not result.ran:
            code, status = (FAILED, 502) if result.failed else ("DISCOVERY_SCOPE_UNAVAILABLE", 422)
            raise DiscoveryError(code, status, result.unavailable, result.calls)
        return result

    # ------------------------------------------------------------ 추가
    def add(self, context: DiscoveryContext, notebook_id: str, ref: Any, *, idempotency_key: str | None = None) -> AddResult:
        parsed = parse_ref(ref)
        selected = self._selection(context, notebook_id)
        kind, tools = ADD_TOOLS[parsed["kind"]]
        connector_id, reason = self.searcher.pick(self.searcher.connector_rows(context), kind, tools)
        if reason is not None:
            raise DiscoveryError("DISCOVERY_SCOPE_UNAVAILABLE", 422, [{"scope": REF_SCOPE[parsed["kind"]], "reason": reason}])
        if parsed["kind"] == "knowledge_package":
            return self._add_scope(context, notebook_id, parsed, selected)
        return self._add_source(context, notebook_id, parsed, str(connector_id), idempotency_key)

    def _add_scope(self, context: DiscoveryContext, notebook_id: str, ref: Mapping[str, str], selected: list[Mapping[str, Any]]) -> AddResult:
        audit = {"added": "scope", "kind": ref["kind"], "project_id": ref["project_id"], "work_package_id": ref["work_package_id"]}
        keys = [{"project_id": item["project_id"], "work_package_id": item["work_package_id"]} for item in selected]
        wanted = {"project_id": ref["project_id"], "work_package_id": ref["work_package_id"]}
        if wanted in keys:
            return AddResult({"added": "scope"}, {**audit, "already_present": True})
        if len(keys) >= MAX_SELECTED:
            raise DiscoveryError("DISCOVERY_SCOPE_LIMIT", 409)
        try:
            # 기존 저장 경로: 서버가 Daon2-RAG 승인 목록을 다시 읽어 확인하고 이름은 서버 값을 쓴다.
            self._scopes.replace(context, notebook_id, [*keys, wanted])
        except KnowledgeScopeError as error:
            raise self._scope_error(error) from None
        except (McpError, ConnectorError):
            raise DiscoveryError(FAILED, 502) from None
        return AddResult({"added": "scope"}, {**audit, "already_present": False})

    @staticmethod
    def _scope_error(error: KnowledgeScopeError) -> DiscoveryError:
        mapping = {"NOTEBOOK_NOT_FOUND": ("NOTEBOOK_NOT_FOUND", 404), "KNOWLEDGE_SCOPE_NOT_AVAILABLE": ("DISCOVERY_REF_NOT_FOUND", 404),
                   "KNOWLEDGE_SCOPE_SELECTION_INVALID": ("DISCOVERY_SCOPE_LIMIT", 409),
                   "KNOWLEDGE_CONNECTOR_NOT_CONFIGURED": ("DISCOVERY_SCOPE_UNAVAILABLE", 422),
                   "KNOWLEDGE_SCOPE_RESPONSE_INVALID": (FAILED, 502)}
        code, status = mapping.get(error.code, ("DISCOVERY_UNAVAILABLE", 503))
        return DiscoveryError(code, status)

    def _connector_call(self, context: DiscoveryContext, connector_id: str, tool: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            result = self._connectors.call(self.searcher.connector_context(context), connector_id, tool, arguments)
        except (McpError, ConnectorError) as error:
            raise DiscoveryError(FAILED, 502, diagnostic=_diagnostic(tool, getattr(error, "code", None))) from None
        try:
            return _structured(result)
        except _Malformed:
            code = "TOOL_ERROR" if getattr(result, "is_error", False) else "RESPONSE_INVALID"
            raise DiscoveryError(FAILED, 502, diagnostic=_diagnostic(tool, code)) from None

    def _page_size(self, context: DiscoveryContext, connector_id: str, tool: str, default: int) -> int:
        """서버가 도구 설명에 알린 limit 최댓값과 기본값 중 작은 값. 모르면 기본값.

        배포된 Daon2-RAG의 최댓값이 기본값보다 작으면 MCP 클라이언트가 MCP_ARGUMENTS_INVALID로 막는다(NB4-I1 실서버).
        """
        reader = getattr(self._connectors, "tool_limit", None)
        try:
            maximum = reader(self.searcher.connector_context(context), connector_id, tool) if callable(reader) else None
        except (McpError, ConnectorError):
            maximum = None
        return min(maximum, default) if isinstance(maximum, int) and not isinstance(maximum, bool) and maximum >= 1 else default

    def _approved_document(self, context: DiscoveryContext, connector_id: str, ref: Mapping[str, str]) -> Mapping[str, Any]:
        """ref의 문서가 그 업무 패키지의 RAG 승인 문서인지 다시 확인한다(목록에 없으면 404)."""
        cursor: str | None = None
        page_size = self._page_size(context, connector_id, "list_approved_documents", DOCUMENT_PAGE_SIZE)
        for _ in range(MAX_DOCUMENT_PAGES * max(1, DOCUMENT_PAGE_SIZE // page_size)):
            arguments: dict[str, Any] = {"project_id": ref["project_id"], "work_package_id": ref["work_package_id"], "limit": page_size}
            if cursor:
                arguments["cursor"] = cursor
            page = self._connector_call(context, connector_id, "list_approved_documents", arguments)
            documents = page.get("documents")
            if not isinstance(documents, list):
                raise DiscoveryError(FAILED, 502)
            found = next((row for row in documents if isinstance(row, Mapping) and row.get("document_id") == ref["document_id"]), None)
            if found is not None:
                return found
            cursor = page.get("next_cursor")
            if not isinstance(cursor, str) or not cursor:
                break
        raise DiscoveryError("DISCOVERY_REF_NOT_FOUND", 404)

    def _read_text(self, context: DiscoveryContext, connector_id: str, document_id: str) -> tuple[str, str, str]:
        """(본문, 문서 이름, 버전). 바이트 상한을 넘는 순간 읽기를 멈추고 413이다."""
        parts: list[str] = []
        size, name, version, run = 0, "", "", None
        cursor: str | None = None
        page_blocks = self._page_size(context, connector_id, "get_document_text", TEXT_PAGE_BLOCKS)
        # 쪽당 블록이 적어도 전체 읽기 상한(MAX_TEXT_PAGES × TEXT_PAGE_BLOCKS 블록)은 같게 둔다.
        for _ in range(-(-MAX_TEXT_PAGES * TEXT_PAGE_BLOCKS // page_blocks)):
            arguments: dict[str, Any] = {"document_id": document_id, "limit": page_blocks}
            if cursor:
                arguments["cursor"] = cursor
            page = self._connector_call(context, connector_id, "get_document_text", arguments)
            blocks = page.get("blocks")
            if not isinstance(blocks, list) or page.get("document_id") != document_id:
                raise DiscoveryError(FAILED, 502)
            if run is None:
                run, name, version = page.get("run_id"), _clean(page.get("document_name"), TITLE_CHARS), str(page.get("version_id") or "")
            elif page.get("run_id") != run:
                raise DiscoveryError("DISCOVERY_DOCUMENT_CHANGED", 409)
            for block in blocks:
                text = block.get("text") if isinstance(block, Mapping) else None
                if isinstance(text, str) and text.strip():
                    size += len(text.encode("utf-8")) + (2 if parts else 0)
                    if size > EFFECTIVE_DOCUMENT_BYTES:
                        raise DiscoveryError("DISCOVERY_DOCUMENT_TOO_LARGE", 413)
                    parts.append(text)
            cursor = page.get("next_cursor")
            if cursor is None:
                return "\n\n".join(parts), name, version
            if not isinstance(cursor, str) or not cursor:
                raise DiscoveryError(FAILED, 502)
        raise DiscoveryError("DISCOVERY_DOCUMENT_TOO_LARGE", 413)

    def _add_source(self, context: DiscoveryContext, notebook_id: str, ref: Mapping[str, str], connector_id: str,
                    idempotency_key: str | None) -> AddResult:
        if self._text_sources is None:
            raise DiscoveryError("DISCOVERY_UNAVAILABLE", 503)
        listed = self._approved_document(context, connector_id, ref)
        chars = listed.get("char_count")
        if isinstance(chars, int) and not isinstance(chars, bool) and chars > EFFECTIVE_DOCUMENT_BYTES:
            raise DiscoveryError("DISCOVERY_DOCUMENT_TOO_LARGE", 413)  # 글자 수가 이미 바이트 상한보다 크다
        text, name, version = self._read_text(context, connector_id, ref["document_id"])
        version = version or str(listed.get("version_id") or ref["document_version"])
        title = name or _clean(listed.get("document_name"), TITLE_CHARS) or "Daon2-RAG 문서"
        seed = secrets.token_hex(16) if not idempotency_key else idempotency_key
        key = "discovery:" + hashlib.sha256("|".join((notebook_id, ref["document_id"], version, seed)).encode("utf-8")).hexdigest()[:48]
        try:
            source_id, _version_id = self._text_sources.register_text_source(
                context, notebook_id, title=title, text=text, origin=DISCOVERY_ORIGIN, idempotency_key=key)
        except TextSourceError as error:
            code, status = _TEXT_ERRORS.get(error.code, ("DISCOVERY_DOCUMENT_INVALID", 422))
            raise DiscoveryError(code, status) from None
        except SourceUploadError:
            raise DiscoveryError("DISCOVERY_UNAVAILABLE", 503) from None
        discovery = {"connector_kind": RAG, "document_id": ref["document_id"], "document_version": version}
        return AddResult({"added": "source", "source_id": source_id},
                         {"added": "source", "kind": ref["kind"], "project_id": ref["project_id"], "work_package_id": ref["work_package_id"],
                          "discovery": discovery, "source_id": source_id})


# ------------------------------------------------------------------ HTTP
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchBody(_Strict):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    scopes: list[str] = Field(min_length=1, max_length=len(SCOPES))

    @field_validator("query")
    @classmethod
    def _query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("blank")
        return value

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(scope not in SCOPES for scope in value):
            raise ValueError("scope")
        return value


class AddBody(_Strict):
    ref: dict[str, Any]


def register_source_discovery_routes(app: FastAPI, dependencies: Any, service: SourceDiscoveryService) -> None:
    from .authorization import Action
    from .runtime import _error_response, _json_with_etag, _principal, _require_query_keys

    def _check(id: str, notebook_id: str, action: Action, request: Request) -> DiscoveryContext:
        _require_query_keys(request, frozenset())
        if not _SAFE.fullmatch(notebook_id):
            raise HTTPException(status_code=400)
        principal = _principal(request, dependencies)
        policy_version = dependencies.settings.policy_version
        dependencies.authorization_service.authorize_action(
            principal=principal, workspace_id=id, action=action, trace_id=request.state.trace_id, policy_version=policy_version)
        return DiscoveryContext(principal.tenant_id, id, principal.user_id, request.state.trace_id, policy_version)

    def _audit(context: DiscoveryContext, notebook_id: str, action: str, outcome: AuditOutcome, metadata: Mapping[str, Any]) -> None:
        dependencies.audit_store.append(AuditEventDraft(
            event_id="sd-" + secrets.token_hex(16), occurred_at=datetime.now(timezone.utc), actor_id=context.actor_id,
            actor_type=ActorType.USER, tenant_id=context.tenant_id, workspace_id=context.workspace_id, action=action,
            target_type="notebook", target_id=notebook_id, outcome=outcome, trace_id=context.trace_id,
            policy_version=context.policy_version, metadata=dict(metadata)))

    def _fail(error: DiscoveryError, request: Request) -> JSONResponse:
        code = error.code if error.code in SOURCE_DISCOVERY_PUBLIC_CODES else "INVALID_REQUEST"
        details = {**({"unavailable": error.unavailable} if error.unavailable else {}),
                   **({"connector": error.diagnostic} if error.diagnostic else {})} or None
        return _error_response(error.status, code, request.state.trace_id, retryable=error.status in {502, 503}, details=details)

    def _ok(data: Mapping[str, Any], id: str, request: Request) -> JSONResponse:
        # ETag는 응답 데이터에서 만든다(같은 결과면 같은 값). 검색 결과는 저장하지 않으므로 캐시하지 않는다.
        seed = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        response = _json_with_etag({"data": dict(data), "meta": {"trace_id": request.state.trace_id, "workspace_id": id}}, seed)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/v1/workspaces/{id}/notebooks/{notebook_id}/source-discovery/search")
    async def search_source_discovery(id: str, notebook_id: str, body: SearchBody, request: Request) -> JSONResponse:
        context = _check(id, notebook_id, Action.VIEW, request)  # 찾기만 하므로 노트북 보기 권한
        try:
            result = await asyncio.to_thread(service.search, context, notebook_id, body.query, body.scopes)
        except DiscoveryError as error:
            if error.code in {"DISCOVERY_SCOPE_UNAVAILABLE", FAILED}:
                # 검색어는 남기지 않는다: 범위·이유·호출 수만.
                _audit(context, notebook_id, "source_discovery.search", AuditOutcome.FAILED,
                       {"scopes": list(body.scopes), "candidate_count": 0, "unavailable": error.unavailable, "tool_calls": error.calls,
                        "error_code": error.code})
            return _fail(error, request)
        _audit(context, notebook_id, "source_discovery.search", AuditOutcome.SUCCEEDED,
               {"scopes": list(body.scopes), "candidate_count": len(result.candidates), "unavailable": result.unavailable,
                "tool_calls": result.calls})
        return _ok(result.data(), id, request)

    @app.post("/api/v1/workspaces/{id}/notebooks/{notebook_id}/source-discovery/add")
    async def add_source_discovery(id: str, notebook_id: str, body: AddBody, request: Request,
                                   idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128)) -> JSONResponse:
        context = _check(id, notebook_id, Action.EDIT, request)  # 노트북을 바꾸므로 편집 권한
        try:
            result = await asyncio.to_thread(service.add, context, notebook_id, body.ref, idempotency_key=idempotency_key)
        except DiscoveryError as error:
            return _fail(error, request)
        _audit(context, notebook_id, "source_discovery.add", AuditOutcome.SUCCEEDED, result.audit)
        return _ok(result.data, id, request)
