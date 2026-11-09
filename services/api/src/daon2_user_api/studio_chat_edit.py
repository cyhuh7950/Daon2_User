"""완료 자료를 번호 붙은 조각으로 펼치고, LLM이 돌려준 조각만 끼워 넣는다(WO-K5 §5.1).

내용은 판단하지 않는다. 번호와 형식만 확인하고, 저장 규칙은 사용자 편집과 같은 검증기를 쓴다.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .studio_user_edit import validate_user_edit
from .studio_workspace import StudioError

CHAT_EDIT_TYPES = frozenset({"report", "slides", "flashcards", "quiz", "authored_document"})
AUTHORED_TYPE = "authored_document"
MAX_PARAGRAPHS = 40
MAX_PARAGRAPH_CHARS = 4000
MAX_UNIT_TITLE_CHARS = 120
MAX_PIECE_CHARS = 60_000

_LIST_OPS = {"replace", "insert_after", "delete"}
_OPS = {"text": {"replace"}, "block": _LIST_OPS, "section": _LIST_OPS, "item": _LIST_OPS, "paragraph": _LIST_OPS}


class ChatEditInvalid(ValueError):
    """수정안을 자료에 끼워 넣을 수 없다. 사유는 LLM 재요청에 쓴다."""


@dataclass(frozen=True, slots=True)
class Piece:
    id: str
    kind: str
    content: Mapping[str, Any]


def _body(content: Mapping[str, Any]) -> Mapping[str, Any]:
    body = content.get("body") if isinstance(content, Mapping) else None
    if not isinstance(body, Mapping):
        raise ChatEditInvalid("자료 본문을 읽을 수 없습니다.")
    return body


def _flatten_report(content: Mapping[str, Any]) -> list[Piece]:
    body = _body(content)
    pieces = [Piece("title", "text", {"text": body.get("title", "")}), Piece("summary", "text", {"text": body.get("summary", "")})]
    for n, section in enumerate(body.get("sections", []), 1):
        pieces.append(Piece(f"s{n}", "section", section))
        pieces.append(Piece(f"s{n}.heading", "text", {"text": section.get("heading", "")}))
        pieces.extend(Piece(f"s{n}.b{m}", "block", block) for m, block in enumerate(section.get("blocks", []), 1))
    return pieces


def _flatten_slides(content: Mapping[str, Any]) -> list[Piece]:
    body = _body(content)
    return [Piece("title", "text", {"text": body.get("title", "")}), *(Piece(f"s{n}", "item", slide) for n, slide in enumerate(body.get("slides", []), 1))]


def _flatten_cards(content: Mapping[str, Any]) -> list[Piece]:
    return [Piece(f"c{n}", "item", card) for n, card in enumerate(_body(content).get("cards", []), 1)]


def _flatten_quiz(content: Mapping[str, Any]) -> list[Piece]:
    return [Piece(f"q{n}", "item", question) for n, question in enumerate(_body(content).get("questions", []), 1)]


def _flatten_authored(content: Mapping[str, Any]) -> list[Piece]:
    if not isinstance(content, Mapping) or content.get("mode") != "agent" or content.get("state") != "completed":
        raise ChatEditInvalid("완성된 문서만 대화로 수정할 수 있습니다.")
    pieces: list[Piece] = []
    for unit in content.get("units", []):
        pieces.append(Piece(f"{unit['key']}.title", "text", {"text": unit.get("title", "")}))
        pieces.extend(Piece(f"{unit['key']}.p{n}", "paragraph", paragraph) for n, paragraph in enumerate(unit.get("paragraphs", []), 1))
    return pieces


_FLATTEN = {"report": _flatten_report, "slides": _flatten_slides, "flashcards": _flatten_cards, "quiz": _flatten_quiz, AUTHORED_TYPE: _flatten_authored}


def flatten(type_id: str, content: Mapping[str, Any]) -> list[Piece]:
    handler = _FLATTEN.get(type_id)
    if handler is None:
        raise ChatEditInvalid("대화 수정을 지원하지 않는 자료입니다.")
    return handler(content)


def render_pieces(pieces: Sequence[Piece]) -> str:
    """LLM에 줄 자료. 절 전체 조각은 번호만 알리고 내용은 하위 조각으로 준다."""
    lines = []
    for piece in pieces:
        shown = {"kind": "section"} if piece.kind == "section" else piece.content
        data = json.dumps(shown, ensure_ascii=False).replace("</", "<\/")  # 본문이 태그 경계를 닫지 못하게 한다
        lines.append(f'<piece id="{piece.id}">{data}</piece>')
    return "\n".join(lines)


def piece_text(content: Mapping[str, Any]) -> str:
    """전·후 비교에 보여 줄 평문."""
    if not isinstance(content, Mapping):
        return ""
    if "blocks" in content:
        return "\n".join([str(content.get("heading", "")), *(piece_text(block) for block in content["blocks"])])
    if "items" in content:
        return "\n".join(str(item) for item in content["items"])
    if "front" in content:
        return "\n".join(str(content[key]) for key in ("front", "back", "hint") if content.get(key))
    if "q" in content:
        options = (("✓ " if index == content.get("answer_index") else "") + str(option) for index, option in enumerate(content.get("options", [])))
        return "\n".join(line for line in (str(content.get("q", "")), *options, str(content.get("explanation", ""))) if line)
    if "bullets" in content or "layout" in content:
        table = content.get("table") if content.get("layout") == "table" else None
        rows = [" | ".join(str(cell) for cell in row) for row in (table or {}).get("rows", [])]
        return "\n".join(line for line in (str(content.get("title", "")), *(str(item) for item in content.get("bullets", [])), *rows, str(content.get("notes", ""))) if line)
    if "rows" in content:
        return "\n".join(" | ".join(str(cell) for cell in row) for row in content["rows"])
    return str(content.get("text", ""))


def pieces_size(pieces: Sequence[Piece]) -> int:
    return sum(len(piece_text(piece.content)) for piece in pieces if piece.kind != "section")


def _index(type_id: str, content: Mapping[str, Any], changes: object) -> dict[str, Mapping[str, Any]]:
    """번호·종류를 확인해 조각 번호별 변경표를 만든다. 번호는 모두 원본 기준이다."""
    if not isinstance(changes, Sequence) or isinstance(changes, (str, bytes)):
        raise ChatEditInvalid("changes는 배열이어야 합니다.")
    pieces = {piece.id: piece for piece in flatten(type_id, content)}
    by_id: dict[str, Mapping[str, Any]] = {}
    for change in changes:
        if not isinstance(change, Mapping):
            raise ChatEditInvalid("changes 항목의 형식이 틀렸습니다.")
        piece_id, op = change.get("id"), change.get("op")
        piece = pieces.get(piece_id) if isinstance(piece_id, str) else None
        if piece is None:
            raise ChatEditInvalid(f"없는 조각 번호입니다: {piece_id}")
        if piece_id in by_id:
            raise ChatEditInvalid(f"같은 조각을 두 번 고쳤습니다: {piece_id}")
        if op not in _OPS[piece.kind]:
            raise ChatEditInvalid(f"{piece_id} 조각에는 {op} 수정을 할 수 없습니다.")
        if op != "delete" and not isinstance(change.get("content"), Mapping):
            raise ChatEditInvalid(f"{piece_id} 조각의 content가 없습니다.")
        by_id[piece_id] = change
    for piece_id in by_id:
        parent = piece_id.split(".", 1)[0]
        if parent != piece_id and parent in by_id:
            raise ChatEditInvalid(f"{parent} 조각과 그 안의 조각을 함께 고칠 수 없습니다.")
    return by_id


def _text(original: object, change: Mapping[str, Any] | None) -> object:
    if change is None:
        return original
    value = change["content"].get("text")
    if not isinstance(value, str):
        raise ChatEditInvalid(f"{change['id']} 조각의 text가 없습니다.")
    return value


def _merge_list(items: Sequence[Mapping[str, Any]], prefix: str, by_id: Mapping[str, Mapping[str, Any]], rebuild=None) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    merged: list[dict[str, Any]] = []
    for number, item in enumerate(items, 1):
        piece_id = f"{prefix}{number}"
        change = by_id.get(piece_id)
        if change is not None and change["op"] == "delete":
            continue
        if change is not None and change["op"] == "replace":
            merged.append(dict(change["content"]))
        else:
            merged.append(rebuild(piece_id, item) if rebuild is not None else dict(item))
        if change is not None and change["op"] == "insert_after":
            merged.append(dict(change["content"]))
    return merged


def _merge_report(content: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    body = _body(content)

    def section(piece_id: str, item: Mapping[str, Any]) -> dict[str, Any]:
        return {**item, "heading": _text(item.get("heading"), by_id.get(f"{piece_id}.heading")),
                "blocks": _merge_list(item.get("blocks", []), f"{piece_id}.b", by_id)}

    return {**body, "title": _text(body.get("title"), by_id.get("title")), "summary": _text(body.get("summary"), by_id.get("summary")),
            "sections": _merge_list(body.get("sections", []), "s", by_id, section)}


def _report_size(body: Mapping[str, Any]) -> tuple[int, int]:
    sections = body.get("sections", [])
    return len(sections), sum(len(section.get("blocks", [])) for section in sections)


def _merge_slides(content: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    body = _body(content)
    return {**body, "title": _text(body.get("title"), by_id.get("title")), "slides": _merge_list(body.get("slides", []), "s", by_id)}


def _merge_cards(content: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    body = _body(content)
    return {**body, "cards": _merge_list(body.get("cards", []), "c", by_id)}


def _merge_quiz(content: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    body = _body(content)
    return {**body, "questions": _merge_list(body.get("questions", []), "q", by_id)}


_MERGE = {"report": _merge_report, "slides": _merge_slides, "flashcards": _merge_cards, "quiz": _merge_quiz}
_SIZE = {"report": _report_size, "slides": lambda body: len(body.get("slides", [])), "flashcards": lambda body: len(body.get("cards", [])), "quiz": lambda body: len(body.get("questions", []))}


def authored_known_refs(content: Mapping[str, Any]) -> set[str]:
    """문서에서 쓸 수 있는 근거 번호: 모은 자료와 이미 문단에 붙은 번호."""
    known = {str(row["ref"]) for row in content.get("knowledge") or [] if isinstance(row, Mapping) and row.get("ref")}
    return known | {str(ref) for unit in content.get("units", []) for paragraph in unit.get("paragraphs", []) for ref in paragraph.get("refs", [])}


def _paragraph(change: Mapping[str, Any], known_refs: set[str]) -> dict[str, Any]:
    item = change["content"]
    text = item.get("text")
    if item.get("type", "paragraph") != "paragraph" or not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_PARAGRAPH_CHARS:
        raise ChatEditInvalid(f"{change['id']} 조각은 {MAX_PARAGRAPH_CHARS}자 이하의 문단이어야 합니다.")
    refs = item.get("refs") if isinstance(item.get("refs"), list) else []
    return {"text": text.strip(), "refs": [ref for ref in dict.fromkeys(refs) if isinstance(ref, str) and ref in known_refs], "origin": "chat"}


def _apply_authored(content: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]], known_refs: set[str]) -> dict[str, Any]:
    updated = copy.deepcopy(dict(content))
    for unit in updated["units"]:
        prefix = f"{unit['key']}."
        if not any(piece_id.startswith(prefix) for piece_id in by_id):
            continue
        title = by_id.get(f"{prefix}title")
        if title is not None:
            value = title["content"].get("text")
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > MAX_UNIT_TITLE_CHARS:
                raise ChatEditInvalid(f"{title['id']} 조각의 제목이 올바르지 않습니다.")
            unit["title"] = value.strip()
        paragraphs: list[dict[str, Any]] = []
        for number, paragraph in enumerate(unit["paragraphs"], 1):
            change = by_id.get(f"{prefix}p{number}")
            if change is None or change["op"] == "insert_after":
                paragraphs.append(paragraph)
            elif change["op"] == "replace":
                paragraphs.append(_paragraph(change, known_refs))
            if change is not None and change["op"] == "insert_after":
                paragraphs.append(_paragraph(change, known_refs))
        if not paragraphs or len(paragraphs) > MAX_PARAGRAPHS:
            raise ChatEditInvalid(f"{unit['key']} 소목차에는 문단이 1개 이상 {MAX_PARAGRAPHS}개 이하여야 합니다.")
        unit.update({"paragraphs": paragraphs, "status": "done", "locked": True, "error_code": None, "summary": " ".join(p["text"] for p in paragraphs)[:300]})
    return updated


def apply_changes(type_id: str, content: Mapping[str, Any], changes: Sequence[Mapping[str, Any]], known_refs: set[str]) -> dict[str, Any]:
    """수정안을 끼워 새 내용을 돌려준다. 원본은 바꾸지 않는다. 저장 규칙을 어기면 ChatEditInvalid."""
    by_id = _index(type_id, content, changes)
    if type_id == AUTHORED_TYPE:
        return _apply_authored(content, by_id, known_refs)
    merged = copy.deepcopy(_MERGE[type_id](content, by_id))
    try:
        cleaned = validate_user_edit(type_id, merged, known_refs, _body(content))
    except StudioError as error:
        raise ChatEditInvalid("자료 저장 규칙에 맞지 않습니다.") from error
    if _SIZE[type_id](cleaned) != _SIZE[type_id](merged):
        raise ChatEditInvalid("내용이 비어 있는 조각이 있습니다.")
    return {**copy.deepcopy(dict(content)), "body": cleaned}


def describe_changes(type_id: str, content: Mapping[str, Any], changes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    pieces = {piece.id: piece for piece in flatten(type_id, content)}
    rows = []
    for change in changes:
        op = change["op"]
        rows.append({"op": op, "id": change["id"], "content": change.get("content"), "reason": str(change.get("reason") or ""),
                     "before_text": "" if op == "insert_after" else piece_text(pieces[change["id"]].content),
                     "after_text": "" if op == "delete" else piece_text(change["content"])})
    return rows
