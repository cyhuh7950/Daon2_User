"""제목 자동 생성(F2-02): 완료된 콘텐츠의 핵심 주제로 40자 이내 제목을 만든다. 사용자가 이름을 바꾼 산출물은 건드리지 않는다."""

from __future__ import annotations

import re
from typing import Any, Mapping

TITLE_MAX = 40
_SENTENCE_END = re.compile(r"(?<=[.!?。])\s|\n")


def _clip(text: object) -> str:
    value = " ".join(str(text or "").split())
    return value[:TITLE_MAX].rstrip(" ,.:;·-") if value else ""


def _first_sentence(text: object) -> str:
    value = str(text or "").strip()
    return _SENTENCE_END.split(value, maxsplit=1)[0] if value else ""


def derive_title(content: Mapping[str, Any]) -> str:
    """본문에서 제목 후보를 고른다. 없으면 빈 문자열(= 기본 제목 유지)."""
    body = content.get("body") if isinstance(content, Mapping) else None
    if not isinstance(body, Mapping):
        return ""
    candidates: list[object] = [body.get("title"), _first_sentence(body.get("summary"))]
    nodes = body.get("nodes")
    if isinstance(nodes, list):
        root = next((n for n in nodes if isinstance(n, Mapping) and n.get("id") == body.get("root")), None)
        candidates.append(root.get("label") if root else None)
    sections = body.get("sections")
    if isinstance(sections, list) and sections and isinstance(sections[0], Mapping):
        candidates.append(sections[0].get("heading"))
    cards = body.get("cards")
    if isinstance(cards, list) and cards and isinstance(cards[0], Mapping):
        candidates.append(cards[0].get("front"))
    questions = body.get("questions")
    if isinstance(questions, list) and questions and isinstance(questions[0], Mapping):
        candidates.append(questions[0].get("q"))
    slides = body.get("slides")
    if isinstance(slides, list) and slides and isinstance(slides[0], Mapping):
        candidates.append(slides[0].get("title"))
    for candidate in candidates:
        title = _clip(candidate)
        if title:
            return title
    return ""
