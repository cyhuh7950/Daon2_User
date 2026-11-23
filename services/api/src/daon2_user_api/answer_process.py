"""답변 과정 기록(WO-N1 N1-1, 블록 형식 answer_process.v1).

시스템이 실제로 한 일(범위·근거 찾기·외부 전송 판정·모델·검증)만 이름·개수·코드로 남긴다.
모델 내부 추론, 프롬프트·질문 원문, 근거 본문, 비밀값, 내부 주소, DB ID(소스 ID 제외)는 넣지 않는다.
웹 클라이언트 `apps/web/lib/answer-process.js`가 같은 허용 목록으로 다시 검사한다.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

VERSION = 1
MAX_SELECTED_EVIDENCE = 20
MAX_KNOWLEDGE_PACKAGES = 20
MAX_TOOLS = 20
MAX_TEXT = 200
EVIDENCE_ORIGINS = frozenset({"raw_source", "daon_knowledge", "mcp_daon_rag", "mcp_law", "notebook_source"})
EGRESS_DECISIONS = frozenset({"allowed", "blocked", "not_needed"})

_TOP_KEYS = frozenset({"version", "scope", "evidence", "egress", "model", "verification"})
_SCOPE_KEYS = frozenset({"source_count", "knowledge_packages", "tools"})
_EVIDENCE_KEYS = frozenset({"searched", "selected"})
_SELECTED_KEYS = frozenset({"title", "page", "origin", "source_id", "source_version_id"})
_EGRESS_KEYS = frozenset({"decision", "masked", "redacted", "policy_ref"})
_MODEL_KEYS = frozenset({"connection", "model", "reasoning"})
_VERIFICATION_KEYS = frozenset({"citations", "valid", "insufficient", "retried"})

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_POLICY_REF = re.compile(r"^[0-9a-f]{12}$")
_REASONING = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_CONTROL = re.compile(r"[\u0000-\u001f\u007f]")
# 주소·연락처·비밀값처럼 보이는 문자열. 화면에 이름으로 보일 값에만 적용한다.
_FORBIDDEN = (
    re.compile(r"://|\bwww\.", re.IGNORECASE),
    re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])"),
    re.compile(r"(?:\b[0-9a-f]{1,4}:){3,}[0-9a-f]{0,4}|[0-9a-f]{0,4}::[0-9a-f]{0,4}", re.IGNORECASE),
    re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+"),
    re.compile(r"\blocalhost\b|\b(?:[a-z0-9-]+\.)+(?:com|net|org|kr|io|ai|dev|app|cloud|local|internal|lan|co|biz|info|me|xyz|site|corp|intra|svc|cluster|home)\b", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])(?:sk|pk|rk)-[A-Za-z0-9]", re.IGNORECASE),
    re.compile(r"\bBearer\s|\bgh[pousr]_[A-Za-z0-9]|\bxox[abpr]-|\bAKIA[0-9A-Z]{8,}|\beyJ[A-Za-z0-9_-]{8,}"),
    re.compile(r"[A-Za-z0-9+/_=-]{40,}"),
)


def _fail() -> None:
    raise ValueError("ANSWER_PROCESS_INVALID")


def is_safe_text(value: object, *, limit: int = MAX_TEXT) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= limit and not _CONTROL.search(value)
            and not any(pattern.search(value) for pattern in _FORBIDDEN))


def _exact(value: object, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _fail()
    return value  # type: ignore[return-value]


def _count(value: object, maximum: int = 100_000) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        _fail()
    return value  # type: ignore[return-value]


def _flag(value: object) -> bool:
    if type(value) is not bool:
        _fail()
    return value  # type: ignore[return-value]


def _optional_text(value: object, *, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    if not is_safe_text(value, limit=limit):
        _fail()
    return value  # type: ignore[return-value]


def _optional_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        _fail()
    return value


def validate_answer_process(value: object) -> dict[str, Any]:
    """허용 목록 밖 키, 주소·IP·호스트·이메일·토큰 모양 문자열이 있으면 ValueError."""
    top = _exact(value, _TOP_KEYS)
    if type(top["version"]) is not int or top["version"] != VERSION:
        _fail()
    scope = _exact(top["scope"], _SCOPE_KEYS)
    packages = scope["knowledge_packages"]
    if not isinstance(packages, list) or len(packages) > MAX_KNOWLEDGE_PACKAGES:
        _fail()
    tools = scope["tools"]
    if tools is not None and (not isinstance(tools, list) or len(tools) > MAX_TOOLS
                              or not all(is_safe_text(item, limit=120) for item in tools)):
        _fail()
    clean_scope = {
        "source_count": _count(scope["source_count"], 1000),
        "knowledge_packages": [{"name": _require_text(_exact(item, frozenset({"name"}))["name"])} for item in packages],
        "tools": None if tools is None else list(tools),
    }
    clean_evidence = None
    if top["evidence"] is not None:
        evidence = _exact(top["evidence"], _EVIDENCE_KEYS)
        selected = evidence["selected"]
        if not isinstance(selected, list) or len(selected) > MAX_SELECTED_EVIDENCE:
            _fail()
        items = []
        for raw in selected:
            item = _exact(raw, _SELECTED_KEYS)
            page = item["page"]
            if page is not None and (type(page) is not int or page < 1):
                _fail()
            if item["origin"] not in EVIDENCE_ORIGINS:
                _fail()
            items.append({"title": _optional_text(item["title"]), "page": page, "origin": item["origin"],
                          "source_id": _optional_id(item["source_id"]),
                          "source_version_id": _optional_id(item["source_version_id"])})
        clean_evidence = {"searched": _count(evidence["searched"]), "selected": items}
    egress = _exact(top["egress"], _EGRESS_KEYS)
    if egress["decision"] not in EGRESS_DECISIONS:
        _fail()
    policy_ref = egress["policy_ref"]
    if policy_ref is not None and (not isinstance(policy_ref, str) or not _POLICY_REF.fullmatch(policy_ref)):
        _fail()
    clean_egress = {"decision": egress["decision"], "masked": _flag(egress["masked"]),
                    "redacted": _flag(egress["redacted"]), "policy_ref": policy_ref}
    clean_model = None
    if top["model"] is not None:
        model = _exact(top["model"], _MODEL_KEYS)
        reasoning = model["reasoning"]
        if reasoning is not None and (not isinstance(reasoning, str) or not _REASONING.fullmatch(reasoning)):
            _fail()
        clean_model = {"connection": _optional_text(model["connection"]), "model": _optional_text(model["model"]),
                       "reasoning": reasoning}
    clean_verification = None
    if top["verification"] is not None:
        verification = _exact(top["verification"], _VERIFICATION_KEYS)
        clean_verification = {"citations": _count(verification["citations"], 1000), "valid": _flag(verification["valid"]),
                              "insufficient": _flag(verification["insufficient"]), "retried": _flag(verification["retried"])}
    return {"version": VERSION, "scope": clean_scope, "evidence": clean_evidence, "egress": clean_egress,
            "model": clean_model, "verification": clean_verification}


def _require_text(value: object) -> str:
    if not is_safe_text(value):
        _fail()
    return value  # type: ignore[return-value]


def _display(value: object, *, limit: int = MAX_TEXT) -> str | None:
    """화면 이름으로 쓸 값. 위험해 보이거나 비어 있으면 값을 버린다(None)."""
    if not isinstance(value, str):
        return None
    text = value.strip()[:limit]
    return text if is_safe_text(text, limit=limit) else None


def policy_ref(fingerprint: object) -> str | None:
    """정책 지문의 앞 12자(16진수). `sha256:` 머리는 떼고, 16진수가 아니면 남기지 않는다."""
    if not isinstance(fingerprint, str):
        return None
    text = fingerprint[len("sha256:"):] if fingerprint.startswith("sha256:") else fingerprint
    ref = text[:12].lower()
    return ref if _POLICY_REF.fullmatch(ref) else None


def build_answer_process(*, scope: Mapping[str, Any], evidence: Mapping[str, Any] | None,
                         egress: Mapping[str, Any], model: Mapping[str, Any] | None,
                         verification: Mapping[str, Any] | None) -> dict[str, Any]:
    """허용 목록 필드만 골라 블록을 만든다. 이름 값이 위험해 보이면 그 값만 버리고, 결과는 다시 검사한다."""
    packages = []
    for item in scope.get("knowledge_packages") or ():
        name = _display(item.get("name") if isinstance(item, Mapping) else item)
        if name is not None and {"name": name} not in packages:
            packages.append({"name": name})
    tools = scope.get("tools")
    clean_tools = None if tools is None else [text for text in (_display(item, limit=120) for item in tools) if text][:MAX_TOOLS]
    built_evidence = None
    if evidence is not None:
        selected = []
        for item in list(evidence.get("selected") or ())[:MAX_SELECTED_EVIDENCE]:
            page = item.get("page")
            source_id, version_id = item.get("source_id"), item.get("source_version_id")
            selected.append({
                "title": _display(item.get("title")),
                "page": page if type(page) is int and page >= 1 else None,
                "origin": item.get("origin"),
                "source_id": source_id if isinstance(source_id, str) and _SAFE_ID.fullmatch(source_id) else None,
                "source_version_id": version_id if isinstance(version_id, str) and _SAFE_ID.fullmatch(version_id) else None,
            })
        built_evidence = {"searched": evidence.get("searched", 0), "selected": selected}
    ref = egress.get("policy_ref")
    built_model = None
    if model is not None:
        reasoning = model.get("reasoning")
        built_model = {"connection": _display(model.get("connection")), "model": _display(model.get("model")),
                       "reasoning": reasoning if isinstance(reasoning, str) and _REASONING.fullmatch(reasoning) else None}
    return validate_answer_process({
        "version": VERSION,
        "scope": {"source_count": scope.get("source_count", 0), "knowledge_packages": packages[:MAX_KNOWLEDGE_PACKAGES],
                  "tools": clean_tools},
        "evidence": built_evidence,
        "egress": {"decision": egress.get("decision"), "masked": bool(egress.get("masked")),
                   "redacted": bool(egress.get("redacted")),
                   "policy_ref": ref if isinstance(ref, str) and _POLICY_REF.fullmatch(ref) else policy_ref(ref)},
        "model": built_model,
        "verification": None if verification is None else dict(verification),
    })


def blocked_answer_process(draft: Mapping[str, Any] | None, *, policy_fingerprint: object = None) -> dict[str, Any] | None:
    """외부 전송이 막힌 질문의 블록. draft는 scope·evidence·model. 만들 수 없으면 None(오류 응답은 그대로)."""
    if not isinstance(draft, Mapping) or not isinstance(draft.get("scope"), Mapping):
        return None
    try:
        return build_answer_process(
            scope=draft["scope"], evidence=draft.get("evidence"), model=draft.get("model"), verification=None,
            egress={"decision": "blocked", "masked": False, "redacted": False, "policy_ref": policy_ref(policy_fingerprint)},
        )
    except (ValueError, TypeError, AttributeError, KeyError):
        return None


def safe_answer_process(value: object) -> dict[str, Any] | None:
    """저장값·오류값을 내보내기 전에 검사한다. 형식이 틀리면 None(과정 기록 없음)."""
    if value is None:
        return None
    try:
        return validate_answer_process(value)
    except (ValueError, TypeError):
        return None
