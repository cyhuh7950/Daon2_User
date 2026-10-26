"""Studio 컨텍스트 구성기: Source 섹션을 라벨([S1]...)이 붙은 근거 구간 묶음으로 만든다. WO-F2 T2-02."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from .studio_source_reader import SourceText

DEFAULT_CONTEXT_CHARS = 24_000
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")


@dataclass(frozen=True, slots=True)
class Passage:
    ref: str
    source_version_id: str
    source_id: str
    filename: str
    evidence_span_id: str | None
    locator_kind: str
    locator_value: str
    heading: str | None
    text: str


@dataclass(frozen=True, slots=True)
class ContextPack:
    passages: tuple[Passage, ...]
    truncated: bool
    total_sections: int

    def by_ref(self) -> Mapping[str, Passage]:
        return {p.ref: p for p in self.passages}

    def subset(self, refs: Sequence[str]) -> "ContextPack":
        wanted = set(refs)
        chosen = tuple(p for p in self.passages if p.ref in wanted)
        return ContextPack(chosen or self.passages, self.truncated, self.total_sections)

    def render(self) -> str:
        """프롬프트용 본문. 구간 안의 지시문은 데이터일 뿐이다(프롬프트 인젝션 방지)."""
        lines = []
        for p in self.passages:
            where = f"{p.locator_kind} {p.locator_value}"
            lines.append(f'<source id="{p.ref}" file="{p.filename}" locator="{where}">\n{p.text}\n</source>')
        return "\n".join(lines)

    def evidence_rows(self, refs: Sequence[str]) -> list[dict[str, object]]:
        index = self.by_ref()
        rows: list[dict[str, object]] = []
        for ref in dict.fromkeys(refs):
            p = index.get(ref)
            if p is None:
                continue
            rows.append({"ref_id": p.ref, "source_version_id": p.source_version_id, "evidence_span_id": p.evidence_span_id,
                         "locator_kind": p.locator_kind, "locator_value": p.locator_value,
                         "quote_sha256": hashlib.sha256(p.text.encode("utf-8")).hexdigest(), "origin": "notebook_source"})
        return rows


def _score(text: str, tokens: set[str]) -> int:
    if not tokens:
        return 0
    found = set(_TOKEN.findall(text.lower()))
    return len(found & tokens)


def build_pack(sources: Sequence[SourceText], *, budget_chars: int = DEFAULT_CONTEXT_CHARS, focus: str | None = None) -> ContextPack:
    """예산 이내면 전체, 초과하면 포커스 점수 + 문서 전반을 고르게 표본으로 고른다(문서 순서 유지)."""
    flat = [(s, section) for s in sources for section in s.sections]
    total = sum(len(section.text) for _, section in flat)
    chosen = list(range(len(flat)))
    truncated = any(s.truncated for s in sources)
    if total > budget_chars:
        truncated = True
        tokens = {t.lower() for t in _TOKEN.findall(focus or "")}
        scored = sorted(range(len(flat)), key=lambda i: (-_score(flat[i][1].text, tokens), i)) if tokens else []
        picked: list[int] = []
        used = 0
        for i in scored:
            if _score(flat[i][1].text, tokens) == 0:
                break
            if used + len(flat[i][1].text) > budget_chars // 2:
                break
            picked.append(i)
            used += len(flat[i][1].text)
        remaining = [i for i in range(len(flat)) if i not in set(picked)]
        step = max(1, len(remaining) // max(1, (budget_chars - used) // max(1, total // max(1, len(flat)))))
        for i in remaining[::step]:
            size = len(flat[i][1].text)
            if used + size > budget_chars:
                continue
            picked.append(i)
            used += size
        chosen = sorted(set(picked)) or [0]
    passages = []
    for number, i in enumerate(chosen, 1):
        source, section = flat[i]
        text = section.text if len(section.text) <= budget_chars else section.text[:budget_chars]
        passages.append(Passage(f"S{number}", source.source_version_id, source.source_id, source.filename,
                                section.evidence_span_id, section.locator_kind, section.locator_value, section.heading, text))
    return ContextPack(tuple(passages), truncated, len(flat))
