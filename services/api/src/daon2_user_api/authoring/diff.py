"""기준 조문과 초안의 문장 단위 비교(변경 표시). WO-A1 T-A2: unchanged / modified / new, 기준에만 남은 문장은 delete_suggested.

공백·구두점을 정규화한 글자 2-gram Dice 유사도로 비교한다(결정적, LLM 미사용).
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from ..studio_context_builder import Passage

UNCHANGED_AT = 0.92
MODIFIED_AT = 0.5
_SENT = re.compile(r"(?<=[.。!?])\s+|\n+")
_NOISE = re.compile(r"[\s\W_]+", re.UNICODE)
_CHAPTER = re.compile(r"^제\s*\d+\s*장")
_HIGHER_BOUNDARY = re.compile(r"^(?:제\s*\d+\s*[편부]|(?:부칙|부록|별표|별지|특약)(?=$|[\s\d:：.\-]))")
_ARTICLE = re.compile(r"^제\s*\d+\s*조")


def normalize(text: str) -> str:
    return _NOISE.sub("", text).lower()


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if s and s.strip()]


def scoped_deletion_candidates(passages: Sequence[Passage], chapter_refs: Mapping[str, set[str]]) -> list[str]:
    """확정된 장과 해당 장을 작성할 때 참조한 구간의 교집합만 삭제 후보로 쓴다."""
    candidates: dict[str, None] = {}
    active_refs: set[str] = set()
    source_version_id: str | None = None
    for passage in passages:
        if passage.source_version_id != source_version_id:
            active_refs = set()
            source_version_id = passage.source_version_id
        if passage.heading and not _ARTICLE.match(passage.heading):
            active_refs = chapter_refs.get(normalize(passage.heading), set())
        body = passage.text.removeprefix(f"{passage.heading}\n") if passage.heading else passage.text
        for raw_line in body.splitlines():
            line = raw_line.strip()
            heading = line.lstrip("#").strip()
            if _CHAPTER.match(heading):
                active_refs = chapter_refs.get(normalize(heading), set())
            elif _HIGHER_BOUNDARY.match(heading) or (line.startswith("#") and not _ARTICLE.match(heading)):
                active_refs = set()
            elif not line.startswith("#") and passage.ref in active_refs:
                candidates.update(dict.fromkeys(split_sentences(line)))
    return list(candidates)


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)} or ({text} if text else set())


def _exact_text(text: str) -> str:
    # 수치의 소수점이나 부호가 바뀌면 유지로 분류하지 않는다.
    return re.sub(r"\s+", "", text).rstrip(".。!?").casefold()


def similarity(a: str, b: str) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ga, gb = _bigrams(na), _bigrams(nb)
    return 2 * len(ga & gb) / (len(ga) + len(gb))


def tag_sentence(sentence: str, base: Sequence[str], *, exact_unchanged: bool = False) -> tuple[str, str | None, float]:
    best, best_text = 0.0, None
    for candidate in base:
        score = similarity(sentence, candidate)
        if score > best or (score == best and exact_unchanged and _exact_text(sentence) == _exact_text(candidate)):
            best, best_text = score, candidate
    if best >= UNCHANGED_AT and (not exact_unchanged or _exact_text(sentence) == _exact_text(best_text or "")):
        return "unchanged", best_text, best
    if best >= MODIFIED_AT:
        return "modified", best_text, best
    return "new", None, best


def tag_section(paragraph_texts: Sequence[str], base_sentences: Sequence[str], *, exact_unchanged: bool = False,
                deletion_candidates: Sequence[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """문단별 변경 태그와, 새 초안 어디에도 이어지지 않은 기준 문장(삭제 제안)을 돌려준다."""
    paragraphs: list[dict[str, Any]] = []
    new_sentences: list[str] = []
    for text in paragraph_texts:
        rows = []
        for sentence in split_sentences(text) or [text]:
            tag, matched, score = tag_sentence(sentence, base_sentences, exact_unchanged=exact_unchanged)
            rows.append({"text": sentence, "tag": tag, "base": matched, "score": round(score, 3)})
            new_sentences.append(sentence)
        tags = {r["tag"] for r in rows}
        paragraph_tag = "unchanged" if tags == {"unchanged"} else "new" if tags == {"new"} else "modified"
        paragraphs.append({"tag": paragraph_tag, "sentences": rows})
    candidates = base_sentences if deletion_candidates is None else deletion_candidates
    removed = [b for b in candidates if all(similarity(b, s) < MODIFIED_AT for s in new_sentences)]
    return paragraphs, removed


def summarize(sections: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"unchanged": 0, "modified": 0, "new": 0, "delete_suggested": 0}
    for section in sections:
        for paragraph in section.get("paragraphs", []):
            for sentence in (paragraph.get("diff") or {}).get("sentences", []):
                counts[sentence["tag"]] += 1
        counts["delete_suggested"] += len(section.get("delete_suggested", []))
    return counts
