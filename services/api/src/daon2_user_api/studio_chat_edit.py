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

CHAT_EDIT_TYPES = frozenset({"report"})
MAX_PIECE_CHARS = 60_000

_OPS = {"text": {"replace"}, "block": {"replace", "insert_after", "delete"}, "section": {"replace", "insert_after", "delete"}}


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


_FLATTEN = {"report": _flatten_report}


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
        lines.append(f'<piece id="{piece.id}">{json.dumps(shown, ensure_ascii=False)}</piece>')
    return "\n".join(lines)


def piece_text(content: Mapping[str, Any]) -> str:
    """전·후 비교에 보여 줄 평문."""
    if not isinstance(content, Mapping):
        return ""
    if "blocks" in content:
        return "\n".join([str(content.get("heading", "")), *(piece_text(block) for block in content["blocks"])])
    if "items" in content:
        return "\n".join(str(item) for item in content["items"])
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


_MERGE = {"report": _merge_report}
_SIZE = {"report": _report_size}


def apply_changes(type_id: str, content: Mapping[str, Any], changes: Sequence[Mapping[str, Any]], known_refs: set[str]) -> dict[str, Any]:
    """수정안을 끼워 새 내용을 돌려준다. 원본은 바꾸지 않는다. 저장 규칙을 어기면 ChatEditInvalid."""
    by_id = _index(type_id, content, changes)
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
