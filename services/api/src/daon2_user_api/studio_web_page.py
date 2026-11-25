"""웹 페이지 만들기(WO-N8): 1단계 내용 JSON 검사.

1단계는 근거 라벨이 붙은 보고서형 내용 JSON을 만든다. 근거가 없거나 숫자·날짜·식별자가
인용 구간에 없는 블록은 지우지 않고 insufficient=True로 표시한다. 2단계(HTML)에는
verified_body()로 근거가 확인된 블록만 넘긴다.
"""

from __future__ import annotations

from typing import Any, Mapping

from .document_understanding_adapter import _evidence_anchors
from .studio_context_builder import ContextPack
from .studio_validation import Warnings, as_list, clean_refs, ensure_size, text_field
from .studio_workspace import StudioError

MAX_SECTIONS = 8
MAX_BLOCKS_PER_SECTION = 30
TITLE_LIMIT = 160
HEADING_LIMIT = 120
REQUEST_LIMIT = 2000
_KINDS = {"paragraph", "bullets", "table", "metric"}


def _block_text(block: Mapping[str, Any]) -> str:
    kind = block["type"]
    if kind == "bullets":
        return "\n".join(block["items"])
    if kind == "table":
        return "\n".join(" ".join(row) for row in block["rows"])
    if kind == "metric":
        return f"{block['label']} {block['value']}"
    return str(block["text"])


def _build_block(kind: str, raw: Mapping[str, object]) -> dict[str, Any] | None:
    """종류별 내용을 다듬는다. 비어 있으면 None."""
    if kind == "bullets":
        items = [text_field(i, 400) for i in as_list(raw.get("items"), 20) if isinstance(i, str) and i.strip()]
        return {"type": "bullets", "items": items} if items else None
    if kind == "table":
        rows = [[text_field(c, 200) for c in r] for r in as_list(raw.get("rows"), 30) if isinstance(r, list)]
        rows = [r for r in rows if any(r)]
        return {"type": "table", "rows": rows} if rows else None
    if kind == "metric":
        label, value = text_field(raw.get("label"), 120), text_field(raw.get("value"), 120)
        return {"type": "metric", "label": label, "value": value} if label and value else None
    text = text_field(raw.get("text"), 3000)
    return {"type": "paragraph", "text": text} if text else None


def validate_web_page(data: Mapping[str, object], pack: ContextPack, request: str) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    w = Warnings()
    used: list[str] = []
    by_ref = pack.by_ref()
    sections: list[dict[str, object]] = []
    verified_count = 0
    for si, section in enumerate(as_list(data.get("sections"), MAX_SECTIONS)):
        if not isinstance(section, Mapping):
            continue
        blocks: list[dict[str, object]] = []
        for bi, raw in enumerate(as_list(section.get("blocks"), MAX_BLOCKS_PER_SECTION)):
            if not isinstance(raw, Mapping):
                continue
            kind = raw.get("type") if raw.get("type") in _KINDS else "paragraph"
            block = _build_block(str(kind), raw)
            if block is None:
                continue
            path = f"sections[{si}].blocks[{bi}]"
            refs = clean_refs(raw.get("refs"), pack, w, path)
            insufficient = not refs
            if refs:
                source = "\n".join(by_ref[r].text for r in refs)
                if not _evidence_anchors(_block_text(block)).issubset(_evidence_anchors(source)):
                    w.add("ANCHOR_MISMATCH", path)
                    insufficient = True
            block["refs"] = refs
            block["insufficient"] = insufficient
            if not insufficient:
                verified_count += 1
                used += refs
            blocks.append(block)
        heading = text_field(section.get("heading"), HEADING_LIMIT)
        if heading and blocks:
            sections.append({"heading": heading, "blocks": blocks})
    if not sections or verified_count == 0:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    body: dict[str, object] = {
        "title": text_field(data.get("title"), TITLE_LIMIT),
        "request": text_field(request, REQUEST_LIMIT),
        "sections": sections,
        "html": "",
    }
    ensure_size(body)
    return body, w.items, list(dict.fromkeys(used))


def verified_body(body: Mapping[str, Any]) -> dict[str, Any]:
    """근거 부족 블록을 뺀 사본. 블록이 다 빠진 절도 뺀다."""
    sections = []
    for section in body.get("sections", []):
        blocks = [dict(b) for b in section.get("blocks", []) if not b.get("insufficient")]
        if blocks:
            sections.append({"heading": section.get("heading", ""), "blocks": blocks})
    return {**body, "sections": sections}


def verified_text(body: Mapping[str, Any]) -> str:
    """verified_body의 모든 글(제목·절 제목·블록 글)을 이어 붙인 것."""
    clean = verified_body(body)
    parts = [str(clean.get("title") or "")]
    for section in clean["sections"]:
        parts.append(str(section["heading"]))
        parts.extend(_block_text(b) for b in section["blocks"])
    return "\n".join(p for p in parts if p)
