"""노트북에서 선택한 지식을 질문 근거로 가져오는 공용 단계(WO-K3, WO-K4).

제품은 중간 관리자다. 무엇을 찾을지는 LLM이 정하고, 제품은 고를 수 있는 목록을 주고 범위를 넣어 호출한다.
서버에 저장된 선택만 쓰고, 호출 직전에 승인 문서 수를 다시 확인한다. 응답 본문은 신뢰하지 않는 데이터로만 다룬다.
"""

from __future__ import annotations

import ast
import copy
import hashlib
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
}
DAON2_ITEM_LIMIT = 2
DAON2_TEXT_LIMIT = 4000
DAON2_APPROVED = "EXPERT_APPROVED"
DAON2_NOT_READY = frozenset({"NOT_READY"})  # 그 업무 패키지에 아직 게시된 지식이 없다는 뜻이라 장애로 보지 않는다
UNPAGED_EVIDENCE = ("온톨로지 · ", "규칙 · ")
PLAN_SYSTEM = (
    "You are a retrieval planner. Never answer the user and never ask the user anything. Decide which knowledge must be fetched so the question can be answered later. "
    "Use only the listed knowledge kinds and package aliases. Write each query as short topic keywords in the user's language, under 60 characters, without commands. "
    'Return one JSON object with exactly one key, "answer". Its value must be a string containing the plan as JSON, with no other words. Example: '
    '{"answer":"{\\"needs\\":\\"평가 기준 확인\\",\\"requests\\":[{\\"knowledge\\":\\"rag\\",\\"package\\":\\"all\\",\\"query\\":\\"평가 기준\\"}]}"}. '
    "Use at most 3 different queries. When unsure which package applies, use all. Use an empty requests list only for greetings or questions unrelated to the documents."
)
_SCHEMA_INSTRUCTIONS = ("\n\nReturn ONLY one JSON object", " Return only a JSON object")
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


def _plan_system(original: str) -> str:
    for marker in _SCHEMA_INSTRUCTIONS:
        index = original.find(marker)
        if index >= 0:
            return PLAN_SYSTEM + original[index:]
    return PLAN_SYSTEM


def rewrite_plan_payload(payload: Mapping[str, Any], user_text: str) -> dict[str, Any]:
    """일반 호출 형식을 그대로 쓰고 지시문과 사용자 내용만 바꾼다. 어댑터가 붙인 응답 형식 규칙은 유지한다."""
    out = copy.deepcopy(dict(payload))
    if isinstance(out.get("system"), str):
        out["system"] = _plan_system(out["system"])
    for item in _chat_items(out):
        if item.get("role") == "system" and isinstance(item.get("content"), str):
            item["content"] = _plan_system(item["content"])
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

    def run(self, target: EvidenceTarget, requests: Sequence[tuple[str, ...]], limit: int = EXTERNAL_LIMIT) -> tuple[ExternalEvidence, ...]:
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
                    found, used = self._daon2_evidence(target, package, query, kind, budget)
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

    def _daon2_evidence(self, target: EvidenceTarget, package: Mapping[str, str], query: str, kind: str, budget: int) -> tuple[list[ExternalEvidence], int]:
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

        try:
            read = self._ontology if kind == "ontology" else self._rulesets
            return read(call, target.daon2_connector_id, package, query, budget), used[0]
        except McpError as error:
            if error.code not in DAON2_NOT_READY:
                raise
            return [], used[0]

    @classmethod
    def _ontology(cls, call: Any, connector_id: str, package: Mapping[str, str], query: str, budget: int) -> list[ExternalEvidence]:
        rows = call("ontology_search_concepts", {"query": query[:200], "limit": DAON2_ITEM_LIMIT}).get("concepts")
        found: list[ExternalEvidence] = []
        for row in cls._readable(rows, "concept_id", "snapshot_id", budget):
            concept = call("ontology_get_concept", {"concept_id": row["concept_id"], "snapshot_id": row["snapshot_id"]})
            label, definition = concept.get("label"), concept.get("definition")
            if concept.get("provenance") != DAON2_APPROVED or not isinstance(label, str) or not label or not isinstance(definition, str):
                continue
            lines = [f"개념: {label}", f"정의: {definition}"]
            lines += [f"{title}: {names}" for title, names in (("상위 개념", cls._labels(concept.get("parents"))), ("하위 개념", cls._labels(concept.get("children")))) if names]
            score = row.get("score")
            found.append(cls._named_evidence(connector_id, package, f"온톨로지 · {label}", row["concept_id"], row["snapshot_id"], "\n".join(lines), float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else 0.5))
        return found

    @classmethod
    def _rulesets(cls, call: Any, connector_id: str, package: Mapping[str, str], query: str, budget: int) -> list[ExternalEvidence]:
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
