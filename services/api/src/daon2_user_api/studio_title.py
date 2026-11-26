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
    if content.get("schema") == "studio.web_page.v1" or "title_insufficient" in body:
        # 웹 페이지(WO-N8): 근거 부족 제목·근거 부족 블록만 있는 절 제목은 쓰지 않는다.
        from .studio_web_page import verified_body

        body = verified_body(body)
    if content.get("schema") == "studio.data_aggregation.v1":
        # 데이터 집계(WO-N9): 사용자가 적은 요청 글의 첫 문장을 제목으로 쓴다. 요약은 숫자가 든 문장 목록이라 쓰지 않는다.
        return _clip(_first_sentence(body.get("request")).rstrip(".!?。"))
    summary = body.get("summary")
    candidates: list[object] = [body.get("title"), _first_sentence(summary) if isinstance(summary, str) else None]
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
