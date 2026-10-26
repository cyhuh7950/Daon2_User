"""기준 조문과 초안의 문장 단위 비교(변경 표시). WO-A1 T-A2: unchanged / modified / new, 기준에만 남은 문장은 delete_suggested.

공백·구두점을 정규화한 글자 2-gram Dice 유사도로 비교한다(결정적, LLM 미사용).
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

UNCHANGED_AT = 0.92
MODIFIED_AT = 0.5
_SENT = re.compile(r"(?<=[.。!?])\s+|\n+")
_NOISE = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize(text: str) -> str:
    return _NOISE.sub("", text).lower()


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if s and s.strip()]


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)} or ({text} if text else set())


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ga, gb = _bigrams(na), _bigrams(nb)
    return 2 * len(ga & gb) / (len(ga) + len(gb))


def tag_sentence(sentence: str, base: Sequence[str]) -> tuple[str, str | None, float]:
    best, best_text = 0.0, None
    for candidate in base:
        score = similarity(sentence, candidate)
        if score > best:
            best, best_text = score, candidate
    if best >= UNCHANGED_AT:
        return "unchanged", best_text, best
    if best >= MODIFIED_AT:
        return "modified", best_text, best
    return "new", None, best


def tag_section(paragraph_texts: Sequence[str], base_sentences: Sequence[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """문단별 변경 태그와, 새 초안 어디에도 이어지지 않은 기준 문장(삭제 제안)을 돌려준다."""
    paragraphs: list[dict[str, Any]] = []
    new_sentences: list[str] = []
    for text in paragraph_texts:
        rows = []
        for sentence in split_sentences(text) or [text]:
            tag, matched, score = tag_sentence(sentence, base_sentences)
            rows.append({"text": sentence, "tag": tag, "base": matched, "score": round(score, 3)})
            new_sentences.append(sentence)
        tags = {r["tag"] for r in rows}
        paragraph_tag = "unchanged" if tags == {"unchanged"} else "new" if tags == {"new"} else "modified"
        paragraphs.append({"tag": paragraph_tag, "sentences": rows})
    removed = [b for b in base_sentences if all(similarity(b, s) < MODIFIED_AT for s in new_sentences)]
    return paragraphs, removed


def summarize(sections: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"unchanged": 0, "modified": 0, "new": 0, "delete_suggested": 0}
    for section in sections:
        for paragraph in section.get("paragraphs", []):
            for sentence in (paragraph.get("diff") or {}).get("sentences", []):
                counts[sentence["tag"]] += 1
        counts["delete_suggested"] += len(section.get("delete_suggested", []))
    return counts
