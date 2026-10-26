"""사용자 편집(S2-11): 편집된 본문(body)을 유형별 규칙으로 정리한다. 생성 검증기와 같은 구조 규칙을 쓰되
근거 라벨은 해당 산출물에 실제로 연결된 것만 남기고(그 밖은 제거), 문장 근거 일치 검사는 하지 않는다(사용자가 의도해서 바꾼 글이다)."""

from __future__ import annotations

from typing import Any, Mapping

from .studio_validation import as_list, ensure_size, text_field
from .studio_workspace import StudioError

EDITABLE_TYPES = frozenset({"report", "flashcards", "quiz", "slides", "memo"})


def _refs(value: object, known: set[str]) -> list[str]:
    return [r for r in dict.fromkeys(as_list(value, 12)) if isinstance(r, str) and r in known]


def _invalid() -> StudioError:
    return StudioError("STUDIO_INPUT_INVALID", 400)


def _report(body: Mapping[str, Any], known: set[str]) -> dict[str, Any]:
    sections = []
    for section in as_list(body.get("sections"), 30):
        if not isinstance(section, Mapping):
            continue
        blocks = []
        for block in as_list(section.get("blocks"), 60):
            if not isinstance(block, Mapping):
                continue
            kind = block.get("type")
            refs = _refs(block.get("refs"), known)
            if kind == "bullets":
                items = [text_field(i, 600) for i in as_list(block.get("items"), 30) if isinstance(i, str) and i.strip()]
                if items:
                    blocks.append({"type": "bullets", "items": items, "refs": refs})
            elif kind == "table":
                rows = [[text_field(c, 300) for c in r] for r in as_list(block.get("rows"), 60) if isinstance(r, list)]
                if rows:
                    blocks.append({"type": "table", "rows": rows, "refs": refs})
            elif kind == "paragraph":
                text = text_field(block.get("text"), 5000)
                if text:
                    blocks.append({"type": "paragraph", "text": text, "refs": refs})
            else:
                raise _invalid()
        heading = text_field(section.get("heading"), 160)
        if heading and blocks:
            sections.append({"heading": heading, "blocks": blocks})
    if not sections:
        raise _invalid()
    return {"title": text_field(body.get("title"), 200), "summary": text_field(body.get("summary"), 2000), "sections": sections}


def _flashcards(body: Mapping[str, Any], known: set[str]) -> dict[str, Any]:
    cards = []
    for card in as_list(body.get("cards"), 80):
        if not isinstance(card, Mapping):
            continue
        front, back = text_field(card.get("front"), 300), text_field(card.get("back"), 800)
        if not front or not back:
            continue
        item: dict[str, Any] = {"front": front, "back": back, "refs": _refs(card.get("refs"), known)}
        hint = text_field(card.get("hint"), 300)
        if hint:
            item["hint"] = hint
        cards.append(item)
    if not cards:
        raise _invalid()
    return {"cards": cards}


def _quiz(body: Mapping[str, Any], known: set[str]) -> dict[str, Any]:
    questions = []
    for q in as_list(body.get("questions"), 60):
        if not isinstance(q, Mapping):
            continue
        options = [text_field(o, 300) for o in as_list(q.get("options"), 8) if isinstance(o, str) and o.strip()]
        answer = q.get("answer_index")
        text = text_field(q.get("q"), 500)
        if not text or len(options) != 4 or len(set(options)) != 4 or type(answer) is not int or not 0 <= answer < 4:
            raise _invalid()
        questions.append({"q": text, "options": options, "answer_index": answer,
                          "explanation": text_field(q.get("explanation"), 1000), "refs": _refs(q.get("refs"), known)})
    if not questions:
        raise _invalid()
    return {"questions": questions}


def _slides(body: Mapping[str, Any], known: set[str]) -> dict[str, Any]:
    slides = []
    for slide in as_list(body.get("slides"), 40):
        if not isinstance(slide, Mapping):
            continue
        title = text_field(slide.get("title"), 160)
        if not title:
            raise _invalid()
        layout = slide.get("layout") if slide.get("layout") in {"title", "bullets", "two_column", "table"} else "bullets"
        item: dict[str, Any] = {"layout": layout, "title": title,
                                "bullets": [text_field(b, 300) for b in as_list(slide.get("bullets"), 12) if isinstance(b, str) and b.strip()],
                                "notes": text_field(slide.get("notes"), 1500), "refs": _refs(slide.get("refs"), known)}
        table = slide.get("table")
        if layout == "table" and isinstance(table, Mapping):
            cols = [text_field(c, 80) for c in as_list(table.get("columns"), 8)]
            rows = [[text_field(c, 120) for c in r] for r in as_list(table.get("rows"), 20) if isinstance(r, list)]
            if cols and rows:
                item["table"] = {"columns": cols, "rows": rows}
        slides.append(item)
    if len(slides) < 1:
        raise _invalid()
    return {"title": text_field(body.get("title"), 200), "slides": slides}


_VALIDATORS = {"report": _report, "flashcards": _flashcards, "quiz": _quiz, "slides": _slides}


def validate_user_edit(type_id: str, body: object, known_refs: set[str], previous_body: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """편집된 body를 정리해 돌려준다. 지원하지 않는 유형이면 STUDIO_INPUT_INVALID."""
    if not isinstance(body, Mapping):
        raise _invalid()
    if type_id == "memo":
        markdown = body.get("markdown")
        if not isinstance(markdown, str) or len(markdown) > 200_000:
            raise _invalid()
        return {**dict(previous_body or {}), "markdown": markdown}
    validator = _VALIDATORS.get(type_id)
    if validator is None:
        raise _invalid()
    cleaned = validator(body, known_refs)
    ensure_size(cleaned)
    return cleaned
