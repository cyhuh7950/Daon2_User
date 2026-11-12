"""노트북에서 선택한 지식을 질문 근거로 가져오는 공용 단계(WO-K3, WO-K4).

제품은 중간 관리자다. 무엇을 찾을지는 LLM이 정하고, 제품은 고를 수 있는 목록을 주고 범위를 넣어 호출한다.
서버에 저장된 선택만 쓰고, 호출 직전에 승인 문서 수를 다시 확인한다. 응답 본문은 신뢰하지 않는 데이터로만 다룬다.
"""

from __future__ import annotations

import ast
import copy
import hashlib
from datetime import datetime, timezone
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .document_index_postgres import IndexedEvidenceChunk
from .knowledge_connector_service import ConnectorError
from .knowledge_scope_service import KnowledgeScopeContext, KnowledgeScopeError
from .mcp_client import McpError

PER_PACKAGE_LIMIT = 5
EXTERNAL_LIMIT = 5
LOCAL_LIMIT_WITH_EXTERNAL = 5
MAX_SEARCH_QUESTION_CHARS = 100  # Daon2-RAG는 500자까지 받지만 실제 시험에서 150자부터 임베딩이 실패했다
MAX_PLAN_QUERIES = 3
MAX_PLAN_CALLS = 8
PLAN_OUTPUT_TOKENS = 512
ALL_PACKAGES = "all"
APPROVED_MARK = "[승인 지식] "
# LLM에게 보여 주는 지식 선택지. 승인된 지식 종류만 넣는다. 단계별로 늘린다(WO-K4 7절).
KNOWLEDGE_KINDS: Mapping[str, str] = {
    "rag": "승인 문서의 원문 근거를 문장으로 검색한다.",
    "ontology": "업무 용어의 정의와 상위·하위 개념을 찾는다. 검색어는 찾을 용어 하나만 쓴다.",
    "ruleset": "승인된 업무 규칙의 조건과 결과를 찾는다.",
    "graphrag": "승인 그래프에서 개념과 관계를 따라가며 답을 찾는다. 여러 사실을 잇거나 흐름·관계를 묻는 질문에 쓴다.",
    "approved": "전문가가 게시한 승인 지식 자산(정리된 안내·답변)을 찾는다.",
    "judgment": "질문의 상황이 승인된 업무 규칙을 충족하는지 판정한다. '~이면 되나요', '~해도 되나요'처럼 판단을 묻는 질문에 쓴다. 검색어에는 판단할 상황을 쓴다.",
}
DAON2_ITEM_LIMIT = 2
MAX_CONCEPT_QUERIES = 8
MAX_CONCEPT_CALLS = 20
DAON2_TEXT_LIMIT = 4000
DAON2_APPROVED = "EXPERT_APPROVED"
# 그 업무 패키지에 게시된 지식이 없거나(NOT_READY), 그 조합이 Daon2에 없는 경우(SCOPE_FORBIDDEN, Daon2 2026-11-12 배포 이후)라 장애로 보지 않는다.
DAON2_NOT_READY = frozenset({"NOT_READY", "SCOPE_FORBIDDEN"})
# GraphRAG는 모델을 불러 오래 걸리고 실패도 잦다. 실패하면 그 요청만 건너뛰고 다른 지식으로 답한다.
# 이 기능 이전에 등록된 연결은 허용 도구에 새 도구가 없을 수 있다. 그 지식 종류만 건너뛴다.
DAON2_SKIP = DAON2_NOT_READY | {"MCP_TOOL_NOT_ALLOWED"}
# GraphRAG는 모델을 불러 오래 걸리고 실패 원인이 다양하다(게이트웨이 502/504 등). 어떤 실패든 그 요청만 건너뛴다.
SKIP_ANY_FAILURE = frozenset({"graphrag"})
# 승인 자산은 Daon2가 승인·게시한 것만 검색하지만, 명백히 승인이 아닌 상태는 한 번 더 거른다.
UNAPPROVED_ASSET_STATES = frozenset({"DRAFT", "PENDING", "REJECTED", "REVOKED", "EXPIRED", "WITHDRAWN", "ARCHIVED"})
GRAPHRAG_EVIDENCE_LIMIT = 5
TRAVERSE_NODE_LIMIT = 10
JUDGMENT_RULE_LIMIT = 3
JUDGMENT_FACT_LIMIT = 20
JUDGMENT_RESULT = {"satisfied": "충족", "not_satisfied": "미충족", "needs_review": "확인 필요"}
UNPAGED_EVIDENCE = ("온톨로지 · ", "규칙 · ", "GraphRAG · ", "승인 자산 · ", "규칙 판정 · ")
PLAN_SYSTEM = (
    "You are a retrieval planner. Never answer the user and never ask the user anything. Decide which knowledge must be fetched so the question can be answered later. "
    "Use only the listed knowledge kinds and package aliases. Write each query as short topic keywords in the user's language, under 60 characters, without commands. "
    'Return one JSON object with exactly one key, "answer". Its value must be a string containing the plan as JSON, with no other words. Example: '
    '{"answer":"{\\"needs\\":\\"평가 기준 확인\\",\\"requests\\":[{\\"knowledge\\":\\"rag\\",\\"package\\":\\"all\\",\\"query\\":\\"평가 기준\\"}]}"}. '
    "Use at most 3 different queries. When unsure which package applies, use all. Use an empty requests list only for greetings or questions unrelated to the documents."
)
_SCHEMA_INSTRUCTIONS = ("\n\nReturn ONLY one JSON object", " Return only a JSON object")
FACTS_SYSTEM = (
    "You are a fact extractor. Never answer the user and never ask the user anything. Read the user's question and decide the value of each listed condition only when the question states it. "
    "Skip a condition the question does not state; never guess. Use true or false for boolean conditions, a number for numbers, and short text otherwise. "
    'Return one JSON object with exactly one key, "answer". Its value must be a string containing the facts as JSON, with no other words. Example: '
    '{"answer":"{\\"facts\\":[{\\"id\\":\\"F1\\",\\"value\\":false}]}"}.'
)
PRIORITY_RULE = (
    f"Evidence whose text starts with {APPROVED_MARK.strip()} is approved Daon knowledge. "
    "When it conflicts with other evidence, follow the approved knowledge and state the conflict in the answer."
)
ANSWER_FORMAT_RULE = (
    "Write lists with plain hyphen bullets and never number headings or items. Use numbers, dates and codes only exactly as they appear "
    "in the evidence you cite, cite every chunk whose numbers you use, and never write chunk_id values in the answer text."
)
ANSWER_RETRY_RULE = (
    "Your previous answer was rejected because it contained numbers, dates or codes that do not appear in the text of the evidence it cited. "
    "Write the answer again as a JSON object in the required format. Use only values that appear verbatim in the cited evidence text. "
    "Do not add counts you calculated, numbered lists or chunk_id values."
)
_TEXT_FIELDS = ("document_id", "version_id", "run_id", "block_id", "text")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


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


@dataclass(frozen=True, slots=True)
class EvidenceTarget:
    connector_context: Any
    connector_id: str
    packages: tuple[Mapping[str, str], ...]
    daon2_context: Any = None
    daon2_connector_id: str | None = None

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(kind for kind in KNOWLEDGE_KINDS if kind == "rag" or self.daon2_connector_id is not None)


def _evidence_title(item: ExternalEvidence) -> str:
    name = item.document_name or "문서"
    return name if name.startswith(UNPAGED_EVIDENCE) else f"{name} {item.page}쪽"


def merge_evidence(local: tuple[IndexedEvidenceChunk, ...], external: tuple[ExternalEvidence, ...]) -> tuple[IndexedEvidenceChunk, ...]:
    """승인 지식을 앞에 둔다. 점수 척도가 달라 섞어 정렬하지 않고 각각 최대 5건 쓴다."""
    if not external:
        return local
    mark = APPROVED_MARK if local else ""
    # 문서 이름과 쪽수를 근거 본문에 넣어 LLM이 출처를 말할 수 있게 한다. 인용 검증은 본문을 기준으로 그대로 동작한다.
    chunks = tuple(replace(item.chunk, text=f"{mark}[{_evidence_title(item)}] {item.chunk.text}") for item in external[:EXTERNAL_LIMIT])
    return (*chunks, *local[:LOCAL_LIMIT_WITH_EXTERNAL])


def build_plan_prompt(question: str, history: Sequence[tuple[str, str]], target: EvidenceTarget) -> str:
    """LLM에게 줄 내용. 식별자와 토큰은 넣지 않고 별칭만 준다. 문서 본문도 넣지 않는다."""
    lines = ["[사용할 수 있는 지식 종류]", *(f"- {kind}: {KNOWLEDGE_KINDS[kind]}" for kind in target.kinds), "", "[선택된 업무 패키지]"]
    lines += [f"- {package['alias']}: {package['project_name']} / {package['work_package_name']}" for package in target.packages]
    if history:
        lines += ["", "[최근 대화]"]
        for asked, answered in history[-3:]:
            lines += [f"질문: {asked[:300]}", f"답변: {answered[:400]}"]
    return "\n".join([*lines, "", "[이번 질문]", question.strip()])


def default_requests(target: EvidenceTarget, question: str) -> tuple[tuple[str, str], ...]:
    """LLM 판단을 받지 못하면 사용자 문장으로 각 업무 패키지를 찾는다."""
    text = question.strip()[:MAX_SEARCH_QUESTION_CHARS]
    return tuple((package["alias"], text) for package in target.packages)


def _load_plan(raw: str) -> Any:
    """어댑터가 객체를 문자열로 바꿔 주면 작은따옴표 형식이 되므로 그 형식도 읽는다."""
    text = _FENCE.sub("", raw.strip()) if isinstance(raw, str) else ""
    for reader in (json.loads, ast.literal_eval):
        try:
            return reader(text)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            continue
    return None


def parse_plan(raw: str, target: EvidenceTarget, dropped: dict[str, int] | None = None) -> tuple[tuple[str, str], ...] | None:
    """LLM의 자료 계획을 실행할 요청으로 바꾼다. 해석할 수 없으면 None, 검색이 필요 없다는 답이면 빈 값이다. 버린 요청은 사유별로 dropped에 센다."""
    def drop(reason: str) -> None:
        if dropped is not None:
            dropped[reason] = dropped.get(reason, 0) + 1

    plan = _load_plan(raw)
    requests = plan.get("requests") if isinstance(plan, Mapping) else None
    if not isinstance(requests, list):
        return None
    if not requests:
        return ()
    aliases = tuple(package["alias"] for package in target.packages)
    chosen: list[tuple[str, str]] = []
    queries: list[str] = []
    for item in requests:
        if not isinstance(item, Mapping) or not isinstance(item.get("query"), str):
            drop("malformed")
            continue
        kind = item.get("knowledge")
        if kind not in target.kinds:
            drop("unknown_kind")
            continue
        query = item["query"].strip()[:MAX_SEARCH_QUESTION_CHARS]
        package = item.get("package")
        if not query:
            drop("malformed")
            continue
        if package != ALL_PACKAGES and package not in aliases:
            drop("unknown_package")
            continue
        if query not in queries:
            if len(queries) == MAX_PLAN_QUERIES:
                drop("over_limit")
                continue
            queries.append(query)
        chosen += [(alias, query) if kind == "rag" else (alias, query, kind) for alias in (aliases if package == ALL_PACKAGES else (package,))]
    return tuple(dict.fromkeys(chosen))[:MAX_PLAN_CALLS] or None


def _chat_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("messages") if isinstance(payload.get("messages"), list) else payload.get("input")
    return items if isinstance(items, list) else []


def append_system_rule(payload: Mapping[str, Any], rule: str) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    if isinstance(out.get("system"), str):
        out["system"] += "\n\n" + rule
        return out
    for item in _chat_items(out):
        if item.get("role") == "system" and isinstance(item.get("content"), str):
            item["content"] += "\n\n" + rule
            break
    return out


def _plan_system(original: str, system: str = PLAN_SYSTEM) -> str:
    for marker in _SCHEMA_INSTRUCTIONS:
        index = original.find(marker)
        if index >= 0:
            return system + original[index:]
    return system


def build_facts_prompt(question: str, conditions: Sequence[Mapping[str, Any]]) -> str:
    """규칙 조건은 개념 id 대신 이름과 짧은 id(F1..)로만 보낸다."""
    lines = ["[질문]", question, "", "[조건]"]
    for item in conditions:
        lines.append(f"- {item['id']}: {item.get('label') or ''} (형식: {item.get('datatype') or 'text'})")
    return "\n".join(lines)


def parse_facts(raw: str, conditions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """LLM이 준 사실 중 아는 조건이고 값이 있는 것만 남긴다. 읽을 수 없으면 사실 없이 판정한다(결과는 확인 필요)."""
    loaded = _load_plan(raw)
    known = {item["id"] for item in conditions}
    rows = loaded.get("facts") if isinstance(loaded, Mapping) else None
    found: dict[str, Any] = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, Mapping) and row.get("id") in known and "value" in row and isinstance(row["value"], (bool, int, float, str)):
            found.setdefault(row["id"], row["value"])
    return found


def rewrite_plan_payload(payload: Mapping[str, Any], user_text: str, system: str = PLAN_SYSTEM) -> dict[str, Any]:
    """일반 호출 형식을 그대로 쓰고 지시문과 사용자 내용만 바꾼다. 어댑터가 붙인 응답 형식 규칙은 유지한다."""
    out = copy.deepcopy(dict(payload))
    if isinstance(out.get("system"), str):
        out["system"] = _plan_system(out["system"], system)
    for item in _chat_items(out):
        if item.get("role") == "system" and isinstance(item.get("content"), str):
            item["content"] = _plan_system(item["content"], system)
        elif item.get("role") == "user":
            item["content"] = user_text
    if isinstance(out.get("options"), dict) and "num_predict" in out["options"]:
        out["options"]["num_predict"] = PLAN_OUTPUT_TOKENS
    return out


def _unavailable() -> ExternalEvidenceError:
    return ExternalEvidenceError("KNOWLEDGE_EVIDENCE_UNAVAILABLE", 503, True)


@contextmanager
def _knowledge_errors() -> Iterator[None]:
    try:
        yield
    except KnowledgeScopeError as error:
        if error.code == "KNOWLEDGE_CONNECTOR_NOT_CONFIGURED":
            raise ExternalEvidenceError(error.code, error.status) from None
        raise _unavailable() from None
    except (McpError, ConnectorError):
        raise _unavailable() from None


def _parsed(row: Any) -> tuple[Mapping[str, Any], float]:
    if not isinstance(row, Mapping) or any(not isinstance(row.get(name), str) or not row[name] for name in _TEXT_FIELDS):
        raise _unavailable()
    page, similarity = row.get("page_no"), row.get("similarity")
    if type(page) is not int or page < 1 or isinstance(similarity, bool) or not isinstance(similarity, (int, float)):
        raise _unavailable()
    return row, float(similarity)


def run_planned(finder: Any, target: EvidenceTarget, requests: Sequence[tuple[str, ...]], fallback: Sequence[tuple[str, ...]], **options: Any) -> tuple[ExternalEvidence, ...]:
    """계획대로 찾는다. 온톨로지·규칙에서 못 찾으면 문서에서 찾고, 질문당 호출 상한은 합쳐서 지킨다."""
    found = tuple(finder.run(target, requests, **options))
    if found or not requests or any(len(item) == 2 for item in requests):
        return found
    return tuple(finder.run(target, fallback[:max(0, MAX_PLAN_CALLS - len(requests))], **options))


def _evidence_rank(item: ExternalEvidence) -> tuple[float, str]:
    return -item.chunk.score, item.block_id


def _select_evidence(groups: Iterable[Sequence[ExternalEvidence]], limit: int = EXTERNAL_LIMIT) -> tuple[ExternalEvidence, ...]:
    """검색어마다 가까운 근거부터 번갈아 고른다. 점수 높은 검색어 하나가 다른 검색어의 근거를 밀어내지 않게 한다."""
    queues = [sorted(group, key=_evidence_rank) for group in groups]
    chosen: dict[str, ExternalEvidence] = {}
    while any(queues) and len(chosen) < limit:
        for queue in queues:
            while queue and len(chosen) < limit:
                item = queue.pop(0)
                if item.block_id not in chosen:
                    chosen[item.block_id] = item
                    break
    return tuple(sorted(chosen.values(), key=_evidence_rank))


class NotebookKnowledgeEvidence:
    def __init__(self, scopes: Any, connectors: Any) -> None:
        self._scopes = scopes
        self._connectors = connectors

    def prepare(self, context: Any) -> EvidenceTarget | None:
        """지금 쓸 수 있는 업무 패키지를 확정한다. 승인 조건에서 벗어난 것은 LLM에게도 보이지 않는다."""
        if context.notebook_id is None:
            return None
        scope_context = KnowledgeScopeContext(context.tenant_id, context.workspace_id, context.actor_id, context.trace_id, context.policy_version)
        with _knowledge_errors():
            selected = self._scopes.selection(scope_context, context.notebook_id)["items"]
            if not selected:
                return None
            connector_context, connector_id, approved = self._scopes.evidence_target(scope_context)
        usable = [item for item in selected if (item["project_id"], item["work_package_id"]) in approved]
        if not usable:
            return None
        daon2 = getattr(self._scopes, "daon2_target", lambda _context: None)(scope_context)
        packages = tuple({**item, "alias": f"P{index + 1}", **self._source_tenant(approved[(item["project_id"], item["work_package_id"])])} for index, item in enumerate(usable))
        return EvidenceTarget(connector_context, connector_id, packages, *(daon2 or (None, None)))

    @staticmethod
    def _source_tenant(row: Mapping[str, Any]) -> Mapping[str, str]:
        return {"tenant_id": row["tenant_id"]} if isinstance(row.get("tenant_id"), str) else {}

    def run(self, target: EvidenceTarget, requests: Sequence[tuple[str, ...]], limit: int = EXTERNAL_LIMIT, extract_facts: Any = None) -> tuple[ExternalEvidence, ...]:
        """extract_facts(검색어, 조건 목록) -> {조건 id: 값}: 규칙 판정에 쓸 사실을 LLM으로 뽑는 함수. 없으면 판정 대신 규칙 본문을 근거로 준다."""
        packages = {package["alias"]: package for package in target.packages}
        by_query: dict[tuple[str, str], list[ExternalEvidence]] = {}
        budget = MAX_PLAN_CALLS
        with _knowledge_errors():
            for request in requests[:MAX_PLAN_CALLS]:
                if budget < 1:
                    break
                alias, query = request[:2]
                kind = request[2] if len(request) > 2 else "rag"
                package = packages[alias]
                if kind != "rag":
                    found, used = self._daon2_evidence(target, package, query, kind, budget, extract_facts)
                    budget -= used
                    by_query.setdefault((kind, query), []).extend(found)
                    continue
                budget -= 1
                result = self._connectors.call(target.connector_context, target.connector_id, "search_document_evidence", {
                    "project_id": package["project_id"], "work_package_id": package["work_package_id"], "question": query, "limit": PER_PACKAGE_LIMIT})
                rows = result.structured.get("result") if isinstance(result.structured, Mapping) and not result.is_error else None
                if not isinstance(rows, list):
                    raise _unavailable()
                by_query.setdefault((kind, query), []).extend(self._evidence(target.connector_id, package, row, similarity) for row, similarity in map(_parsed, rows))
        return _select_evidence(by_query.values(), limit)

    def concepts(self, target: EvidenceTarget, queries: Sequence[str]) -> list[dict[str, Any]]:
        """용어 점검용 승인 개념을 찾는다. 작성은 끝난 뒤이므로 지식이 준비되지 않았거나 호출에 실패하면 빈 목록을 돌려준다."""
        found: dict[str, dict[str, Any]] = {}
        budget = MAX_CONCEPT_CALLS
        for package in target.packages:
            if not package.get("tenant_id") or target.daon2_connector_id is None:
                continue
            scope = {"tenant_id": package.get("tenant_id"), "project_id": package["project_id"], "work_package_id": package["work_package_id"]}
            for query in list(queries)[:MAX_CONCEPT_QUERIES]:
                if budget < 1:
                    return list(found.values())
                try:
                    budget -= 1
                    rows = self._connectors.call(target.daon2_context, target.daon2_connector_id, "ontology_search_concepts", {"scope": scope, "query": query[:200], "limit": DAON2_ITEM_LIMIT}).structured.get("concepts")
                    for row in self._readable(rows, "concept_id", "snapshot_id", budget + 1):
                        if row["concept_id"] in found or budget < 1:
                            continue
                        budget -= 1
                        concept = self._connectors.call(target.daon2_context, target.daon2_connector_id, "ontology_get_concept", {"scope": scope, "concept_id": row["concept_id"], "snapshot_id": row["snapshot_id"]}).structured
                        if concept.get("provenance") == DAON2_APPROVED and isinstance(concept.get("label"), str):
                            synonyms = concept.get("synonyms")
                            found[row["concept_id"]] = {"concept_id": row["concept_id"], "label": concept["label"], "synonyms": [s for s in synonyms if isinstance(s, str)] if isinstance(synonyms, list) else []}
                except (McpError, ConnectorError, AttributeError):
                    break
        return list(found.values())

    def _daon2_evidence(self, target: EvidenceTarget, package: Mapping[str, str], query: str, kind: str, budget: int, extract_facts: Any = None) -> tuple[list[ExternalEvidence], int]:
        """온톨로지와 규칙을 근거 형태로 가져온다. 전문가 승인·게시된 것만 쓰고, 지식이 준비되지 않은 패키지는 건너뛴다."""
        if not package.get("tenant_id") or target.daon2_connector_id is None:
            return [], 0
        scope = {"tenant_id": package["tenant_id"], "project_id": package["project_id"], "work_package_id": package["work_package_id"]}
        used = [0]

        def call(tool: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
            used[0] += 1
            result = self._connectors.call(target.daon2_context, target.daon2_connector_id, tool, {"scope": scope, **arguments})
            if result.is_error or not isinstance(result.structured, Mapping):
                raise _unavailable()
            return result.structured

        def remaining() -> int:
            return budget - used[0]

        readers = {"ontology": self._ontology, "ruleset": self._rulesets, "graphrag": self._graphrag, "approved": self._approved}
        try:
            if kind == "judgment":
                return self._judgment(call, target.daon2_connector_id, package, query, remaining, extract_facts), used[0]
            return readers[kind](call, target.daon2_connector_id, package, query, budget, remaining), used[0]
        except McpError as error:
            if kind not in SKIP_ANY_FAILURE and error.code not in DAON2_SKIP:
                raise
            return [], used[0]
        except ExternalEvidenceError:
            if kind not in SKIP_ANY_FAILURE:
                raise
            return [], used[0]

    @classmethod
    def _ontology(cls, call: Any, connector_id: str, package: Mapping[str, str], query: str, budget: int, remaining: Any = lambda: 0) -> list[ExternalEvidence]:
        rows = call("ontology_search_concepts", {"query": query[:200], "limit": DAON2_ITEM_LIMIT}).get("concepts")
        found: list[ExternalEvidence] = []
        readable = cls._readable(rows, "concept_id", "snapshot_id", budget)
        for index, row in enumerate(readable):
            concept = call("ontology_get_concept", {"concept_id": row["concept_id"], "snapshot_id": row["snapshot_id"]})
            label, definition = concept.get("label"), concept.get("definition")
            if concept.get("provenance") != DAON2_APPROVED or not isinstance(label, str) or not label or not isinstance(definition, str):
                continue
            lines = [f"개념: {label}", f"정의: {definition}"]
            lines += [f"{title}: {names}" for title, names in (("상위 개념", cls._labels(concept.get("parents"))), ("하위 개념", cls._labels(concept.get("children")))) if names]
            # 남은 개념 조회 몫을 먼저 남기고, 여유가 있을 때만 연결 개념을 따라간다.
            related = cls._related(call, row["concept_id"]) if remaining() > len(readable) - index - 1 else ""
            if related:
                lines.append(f"관련 개념: {related}")
            score = row.get("score")
            found.append(cls._named_evidence(connector_id, package, f"온톨로지 · {label}", row["concept_id"], row["snapshot_id"], "\n".join(lines), float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else 0.5))
        return found

    @classmethod
    def _related(cls, call: Any, concept_id: str) -> str:
        """개념에서 한 단계 연결된 승인 개념. 따라가기를 쓸 수 없으면 빈 값으로 두고 개념 근거는 그대로 쓴다."""
        try:
            graph = call("ontology_traverse", {"concept_id": concept_id, "depth": 1, "max_nodes": TRAVERSE_NODE_LIMIT})
        except (McpError, ExternalEvidenceError):
            return ""
        if graph.get("provenance") != DAON2_APPROVED:
            return ""
        labels = {node.get("concept_id"): node.get("label") for node in graph.get("nodes") or [] if isinstance(node, Mapping) and isinstance(node.get("label"), str)}
        parts = []
        for edge in graph.get("edges") or []:
            if not isinstance(edge, Mapping):
                continue
            other = edge.get("target") if edge.get("source") == concept_id else edge.get("source") if edge.get("target") == concept_id else None
            relation = edge.get("relation_type") or edge.get("type") or ""
            if other in labels and other != concept_id:
                parts.append(f"{labels[other]}({relation})" if relation else str(labels[other]))
        return ", ".join(dict.fromkeys(parts))

    @classmethod
    def _graphrag(cls, call: Any, connector_id: str, package: Mapping[str, str], query: str, budget: int, remaining: Any = lambda: 0) -> list[ExternalEvidence]:
        result = call("graphrag_query", {"mode": "local", "query": query[:2000], "limit": GRAPHRAG_EVIDENCE_LIMIT})
        answer = result.get("answer")
        if result.get("provenance") != DAON2_APPROVED or not isinstance(answer, str) or not answer.strip():
            return []
        lines = [f"GraphRAG 답: {answer.strip()}"]
        evidence = result.get("evidence")
        for item in (evidence if isinstance(evidence, list) else [])[:GRAPHRAG_EVIDENCE_LIMIT]:
            if isinstance(item, Mapping):
                text = " · ".join(str(item[key]) for key in ("label", "name", "title", "text", "content", "summary") if isinstance(item.get(key), str) and item[key].strip())
                lines.append(f"- {text or json.dumps(item, ensure_ascii=False)[:300]}")
        snapshot = str(result.get("snapshot_id") or "graphrag")
        return [cls._named_evidence(connector_id, package, f"GraphRAG · {query}", hashlib.sha256(query.encode("utf-8")).hexdigest()[:32], snapshot, "\n".join(lines), 0.6)]

    @classmethod
    def _approved(cls, call: Any, connector_id: str, package: Mapping[str, str], query: str, budget: int, remaining: Any = lambda: 0) -> list[ExternalEvidence]:
        listed = call("approved_knowledge_search", {"query": query[:200], "limit": DAON2_ITEM_LIMIT})
        rows = [{"provenance": listed.get("provenance"), **row} for row in listed.get("assets") or [] if isinstance(row, Mapping) and cls._asset_usable(row)]
        found: list[ExternalEvidence] = []
        for row in cls._readable(rows, "asset_id", "version_id", budget):
            asset = call("approved_knowledge_read", {"asset_id": row["asset_id"], "version_id": row["version_id"]})
            content = asset.get("content")
            if asset.get("provenance") != DAON2_APPROVED or not cls._asset_usable(asset) or not isinstance(content, Mapping):
                continue
            title = next((str(v) for k in ("asset_name", "title", "name") for v in (row.get(k), content.get(k)) if isinstance(v, str) and v), "승인 지식")
            body = "\n".join(str(value) for value in content.values() if isinstance(value, str) and value.strip()) or json.dumps(content, ensure_ascii=False)
            found.append(cls._named_evidence(connector_id, package, f"승인 자산 · {title}", row["asset_id"], row["version_id"], body, 0.55))
        return found

    @staticmethod
    def _asset_usable(item: Mapping[str, Any]) -> bool:
        """철회됐거나 유효기간이 지났거나 승인이 아닌 상태의 자산은 쓰지 않는다."""
        if item.get("revoked_at") or str(item.get("approval_status") or "").upper() in UNAPPROVED_ASSET_STATES:
            return False
        expires = item.get("expires_at")
        if expires:
            try:
                moment = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
            except ValueError:
                return False
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return moment > datetime.now(timezone.utc)
        return True

    @staticmethod
    def _rule_conditions(rule: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        formal = rule.get("formal")
        conditions = formal.get("if") if isinstance(formal, Mapping) else None
        return [c for c in conditions if isinstance(c, Mapping)] if isinstance(conditions, list) else []

    @classmethod
    def _judgment(cls, call: Any, connector_id: str, package: Mapping[str, str], query: str, remaining: Any, extract_facts: Any) -> list[ExternalEvidence]:
        """규칙 판정: 게시 규칙의 조건 대상(개념)을 이름으로 바꿔 LLM이 사실값을 뽑고, Daon2 판정기로 판정한다. 판정은 저장되지 않는 참고 결과다."""
        if extract_facts is None:
            return cls._rulesets(call, connector_id, package, query, remaining())
        listed = call("ruleset_list", {"limit": 10})
        rows = [{"provenance": listed.get("provenance"), **row} for row in listed.get("rulesets") or [] if isinstance(row, Mapping) and row.get("published") is True]
        rules = []
        for row in [r for r in rows if r.get("provenance") == DAON2_APPROVED and isinstance(r.get("ruleset_id"), str)][:JUDGMENT_RULE_LIMIT]:
            if remaining() < 2:
                break
            rule = call("ruleset_get", {"ruleset_id": row["ruleset_id"]})
            if rule.get("provenance") == DAON2_APPROVED and rule.get("published") is True and isinstance(rule.get("name"), str):
                rules.append({**rule, "ruleset_id": row["ruleset_id"]})  # 목록의 id를 쓴다(본문에 빠져도 판정 가능)
        if not rules:
            return []
        subjects: dict[str, str] = {}
        for rule in rules:
            for condition in cls._rule_conditions(rule):
                subject = condition.get("subject")
                if isinstance(subject, str) and subject not in subjects and len(subjects) < JUDGMENT_FACT_LIMIT:
                    subjects[subject] = cls._concept_label(call, subject) if remaining() > 1 else ""
        conditions, by_id = [], {}
        for index, (subject, label) in enumerate(subjects.items(), start=1):
            sample = next((c for rule in rules for c in cls._rule_conditions(rule) if c.get("subject") == subject), {})
            by_id[f"F{index}"] = subject
            conditions.append({"id": f"F{index}", "label": label or f"조건 {index}", "datatype": sample.get("datatype"), "operator": sample.get("operator"), "value": sample.get("value")})
        values = extract_facts(query, conditions) or {}
        facts = [{"key": by_id[key], "value": value} for key, value in values.items() if key in by_id]
        result = call("ruleset_evaluate", {"ruleset_ids": [rule["ruleset_id"] for rule in rules], "facts": facts})
        if result.get("provenance") != DAON2_APPROVED:
            return []
        label_of = {by_id[c["id"]]: c["label"] for c in conditions}
        given = ", ".join(f"{label_of[f['key']]} = {cls._fact_text(f['value'])}" for f in facts) or "없음"
        found = []
        for outcome in result.get("results") or []:
            rule = next((r for r in rules if isinstance(outcome, Mapping) and r["ruleset_id"] == outcome.get("ruleset_id")), None)
            if rule is None:
                continue
            missing = [label_of.get(step.split(":", 1)[1], "") for step in outcome.get("resolution_trace") or [] if isinstance(step, str) and step.startswith("missing_fact:")]
            lines = [f"규칙 판정(참고 판정, 저장되지 않는 시뮬레이션): {rule['name']}", f"결과: {JUDGMENT_RESULT.get(str(outcome.get('result')), '확인 필요')}",
                     f"사용한 사실: {given}", f"규칙 목적: {rule.get('purpose') or ''}"]
            if any(missing):
                lines.insert(3, f"부족한 사실: {', '.join(m for m in dict.fromkeys(missing) if m)}")
            found.append(cls._named_evidence(connector_id, package, f"규칙 판정 · {rule['name']}", rule["ruleset_id"], f"judgment-rev-{rule.get('revision')}", "\n".join(lines), 0.65))
        return found

    @staticmethod
    def _fact_text(value: Any) -> str:
        return "예" if value is True else "아니오" if value is False else str(value)

    @staticmethod
    def _concept_label(call: Any, concept_id: str) -> str:
        try:
            graph = call("ontology_traverse", {"concept_id": concept_id, "depth": 1, "max_nodes": 1})
        except (McpError, ExternalEvidenceError):
            return ""
        return next((str(node["label"]) for node in graph.get("nodes") or [] if isinstance(node, Mapping) and node.get("concept_id") == concept_id and isinstance(node.get("label"), str)), "")

    @classmethod
    def _rulesets(cls, call: Any, connector_id: str, package: Mapping[str, str], query: str, budget: int, remaining: Any = lambda: 0) -> list[ExternalEvidence]:
        listed = call("ruleset_list", {"limit": 5})
        rows = listed.get("rulesets")
        # 목록의 승인 표시는 응답 전체에 한 번만 온다. 각 규칙은 상세 조회에서 다시 확인한다.
        published = [{"provenance": listed.get("provenance"), **row} for row in rows if isinstance(row, Mapping) and row.get("published") is True] if isinstance(rows, list) else []
        found: list[ExternalEvidence] = []
        for row in cls._readable(published, "ruleset_id", "ruleset_id", budget):
            rule = call("ruleset_get", {"ruleset_id": row["ruleset_id"]})
            name = rule.get("name")
            if rule.get("provenance") != DAON2_APPROVED or rule.get("published") is not True or not isinstance(name, str) or not name:
                continue
            body = "\n".join((f"규칙: {name}", f"목적: {rule.get('purpose') or ''}", f"조건과 결과: {json.dumps(rule.get('formal'), ensure_ascii=False)}"))
            found.append(cls._named_evidence(connector_id, package, f"규칙 · {name}", row["ruleset_id"], f"rev-{rule.get('revision')}", body, 0.5))
        return found

    @staticmethod
    def _readable(rows: Any, first: str, second: str, budget: int) -> list[Mapping[str, Any]]:
        """승인된 항목을 남은 호출 수만큼만 고른다. 목록 조회 1회는 이미 썼다."""
        approved = [row for row in rows if isinstance(row, Mapping) and row.get("provenance") == DAON2_APPROVED and isinstance(row.get(first), str) and isinstance(row.get(second), str)] if isinstance(rows, list) else []
        return approved[:max(0, min(DAON2_ITEM_LIMIT, budget - 1))]

    @staticmethod
    def _labels(rows: Any) -> str:
        return ", ".join(str(row["label"]) for row in rows if isinstance(row, Mapping) and row.get("label")) if isinstance(rows, list) else ""

    @staticmethod
    def _named_evidence(connector_id: str, package: Mapping[str, str], name: str, document_id: str, version_id: str, body: str, score: float) -> ExternalEvidence:
        text = body[:DAON2_TEXT_LIMIT]
        chunk_id = "ext-" + hashlib.sha256("|".join((connector_id, version_id, document_id)).encode("utf-8")).hexdigest()[:32]
        chunk = IndexedEvidenceChunk(chunk_id, document_id, version_id, 1, text, document_id, score)
        return ExternalEvidence(chunk, connector_id, package["project_id"], package["project_name"], package["work_package_id"], package["work_package_name"],
                                document_id, version_id, version_id, document_id, 1, name[:1024], text)

    def search(self, context: Any, question: str) -> tuple[ExternalEvidence, ...]:
        target = self.prepare(context)
        return () if target is None else self.run(target, default_requests(target, question))

    @staticmethod
    def _evidence(connector_id: str, item: Mapping[str, str], row: Mapping[str, Any], similarity: float) -> ExternalEvidence:
        name = row.get("document_name")
        chunk_id = "ext-" + hashlib.sha256("|".join((connector_id, row["version_id"], row["block_id"])).encode("utf-8")).hexdigest()[:32]
        chunk = IndexedEvidenceChunk(chunk_id, row["document_id"], row["version_id"], row["page_no"], row["text"], row["block_id"], similarity)
        return ExternalEvidence(chunk, connector_id, item["project_id"], item["project_name"], item["work_package_id"], item["work_package_name"],
                                row["document_id"], row["version_id"], row["run_id"], row["block_id"], row["page_no"], name if isinstance(name, str) and name else None, row["text"])
