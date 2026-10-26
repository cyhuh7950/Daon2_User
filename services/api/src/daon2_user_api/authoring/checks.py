"""작성 점검(F6-13): 근거 무결성과 용어 일관성. RuleSet 평가·법령 대조는 파이프라인이 Connector로 수행한다.
두 점검 모두 결정론적이며 LLM·네트워크를 쓰지 않는다. 결과는 점검 탭의 "확인 필요" 목록이고 작성을 막지 않는다."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

MAX_ITEMS = 30
MIN_SYNONYM_CHARS = 3
PLACEHOLDER = "[작성 필요]"


def _preview(text: str, limit: int = 60) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "…"


def evidence_integrity(sections: Sequence[Mapping[str, Any]], known_refs: set[str]) -> dict[str, Any]:
    """문단마다 근거 번호가 있고 모두 알려진 근거인지 확인한다. 근거가 없거나 모르는 번호면 "근거 미확인"이다."""
    verified, items = 0, []
    for section in sections:
        for index, paragraph in enumerate(section.get("paragraphs") or []):
            text = str(paragraph.get("text", ""))
            if not text.strip() or PLACEHOLDER in text:
                continue  # 비어 있거나 작성 필요 표시는 미결 항목으로 따로 안내한다
            refs = [r for r in paragraph.get("refs") or [] if isinstance(r, str)]
            unknown = [r for r in refs if r not in known_refs]
            if refs and not unknown:
                verified += 1
            else:
                items.append({"section_key": section.get("key"), "section_title": section.get("title"), "paragraph_index": index,
                              "reason": "unknown_ref" if unknown else "no_ref", "text": _preview(text)})
    return {"id": "evidence_integrity", "title": "근거 무결성", "status": "done",
            "summary": {"verified": verified, "unverified": len(items)}, "items": items[:MAX_ITEMS]}


def _count(text: str, needle: str) -> int:
    return text.count(needle) if needle else 0


def term_consistency(sections: Sequence[Mapping[str, Any]], concepts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """온톨로지 기준 용어(label)와 동의어(synonyms) 사용을 점검한다.
    mixed: 같은 문서에서 기준 용어와 동의어를 함께 쓴다. synonym_only: 동의어만 쓰고 기준 용어는 쓰지 않는다."""
    text = "\n".join(" ".join(str(p.get("text", "")) for p in section.get("paragraphs") or []) for section in sections)
    items: list[dict[str, Any]] = []
    for concept in concepts:
        label = str(concept.get("label", "")).strip()
        if not label:
            continue
        synonyms = [s.strip() for s in concept.get("synonyms") or [] if isinstance(s, str) and len(s.strip()) >= MIN_SYNONYM_CHARS and s.strip() != label]
        # 동의어 안에 기준 용어가 들어 있는 경우(예: 보험계약자 ⊃ 계약자)는 기준 용어 사용으로 세지 않는다.
        label_total = _count(text, label) - sum(_count(text, s) * _count(s, label) for s in synonyms)
        for synonym in synonyms:
            used = _count(text, synonym)
            if used <= 0:
                continue
            kind = "mixed" if label_total > 0 else "synonym_only"
            items.append({"concept_id": concept.get("concept_id"), "preferred": label, "found": synonym, "count": used, "kind": kind})
    items.sort(key=lambda i: (0 if i["kind"] == "mixed" else 1, -i["count"], str(i["preferred"])))
    return {"id": "term_consistency", "title": "용어·일관성", "status": "done",
            "summary": {"mixed": sum(1 for i in items if i["kind"] == "mixed"), "synonym_only": sum(1 for i in items if i["kind"] == "synonym_only")},
            "items": items[:MAX_ITEMS]}
