"""Studio 생성용 Source 본문 리더. WO-F2 T2-01.

본문 1차 소스는 understanding_results.canonical_json.parser_validation(text/markdown/page_texts)이다(결정 G1).
문서 구조(개요)는 저장하지 않고 읽을 때 추출한다(G2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from .cloud_storage import CloudAccessContext
from .studio_workspace import StudioContext, StudioError

MAX_SECTION_CHARS = 3000
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)


@dataclass(frozen=True, slots=True)
class SourceSection:
    source_version_id: str
    evidence_span_id: str | None
    locator_kind: str      # 'page' | 'section'
    locator_value: str
    heading: str | None
    text: str


@dataclass(frozen=True, slots=True)
class SourceText:
    source_id: str
    source_version_id: str
    filename: str
    sections: tuple[SourceSection, ...]
    truncated: bool


def _chunks(text: str, limit: int = MAX_SECTION_CHARS) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    parts, current = [], ""
    for paragraph in re.split(r"\n{2,}", text):
        if len(current) + len(paragraph) + 2 > limit and current:
            parts.append(current.strip())
            current = ""
        while len(paragraph) > limit:
            parts.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current += paragraph + "\n\n"
    if current.strip():
        parts.append(current.strip())
    return parts


def split_sections(source_version_id: str, parser: Mapping[str, object], *, max_chars: int,
                   spans_by_page: Mapping[int, str] | None = None) -> tuple[list[SourceSection], bool]:
    """parser_validation → 섹션 목록. PDF 등 쪽 단위 본문은 page 로케이터, 그 밖은 section 순번."""
    sections: list[SourceSection] = []
    total = 0
    truncated = False

    def add(kind: str, value: str, heading: str | None, text: str) -> bool:
        nonlocal total, truncated
        if total + len(text) > max_chars:
            truncated = True
            return False
        total += len(text)
        span = spans_by_page.get(int(value)) if (spans_by_page and kind == "page" and value.isdigit()) else None
        sections.append(SourceSection(source_version_id, span, kind, value, heading, text))
        return True

    pages = parser.get("page_texts")
    if isinstance(pages, (list, tuple)) and any(isinstance(p, str) and p.strip() for p in pages):
        for number, page in enumerate(pages, 1):
            if not isinstance(page, str):
                continue
            for piece in _chunks(page):
                if not add("page", str(number), None, piece):
                    return sections, truncated
        return sections, truncated
    body = parser.get("markdown") if isinstance(parser.get("markdown"), str) and parser.get("markdown") else parser.get("text")
    if not isinstance(body, str):
        return sections, truncated
    matches = list(_HEADING.finditer(body))
    blocks: list[tuple[str | None, str]] = []
    if matches:
        if body[:matches[0].start()].strip():
            blocks.append((None, body[:matches[0].start()]))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            blocks.append((match.group(2), body[match.end():end]))
    else:
        blocks.append((None, body))
    ordinal = 0
    for heading, content in blocks:
        for piece in _chunks(content):
            ordinal += 1
            if not add("section", f"s{ordinal}", heading, (f"{heading}\n{piece}" if heading else piece)):
                return sections, truncated
    return sections, truncated


class StudioSourceReader:
    def __init__(self, cloud_store) -> None:  # type: ignore[no-untyped-def]
        self._store = cloud_store

    def read(self, context: StudioContext, source_version_ids: Sequence[str], *, max_chars_per_source: int = 120_000) -> tuple[SourceText, ...]:
        result: list[SourceText] = []
        scope = CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, "studio.v2.read")
        with self._store._transaction(scope) as connection:
            for version_id in source_version_ids:
                row = connection.execute(
                    "SELECT sv.source_id,COALESCE(sv.canonical_json->>'filename',s.canonical_json->>'filename',sv.record_id),"
                    "(SELECT ur.canonical_json->'parser_validation' FROM understanding_results ur WHERE ur.tenant_id=sv.tenant_id "
                    " AND ur.workspace_id=sv.workspace_id AND ur.source_version_id=sv.record_id ORDER BY ur.version DESC LIMIT 1) "
                    "FROM source_versions sv JOIN sources s ON s.tenant_id=sv.tenant_id AND s.workspace_id=sv.workspace_id AND s.record_id=sv.source_id "
                    "WHERE sv.tenant_id=%s AND sv.workspace_id=%s AND sv.record_id=%s "
                    "AND NOT EXISTS(SELECT 1 FROM deletion_requests d WHERE d.tenant_id=sv.tenant_id AND d.workspace_id=sv.workspace_id "
                    "AND d.source_id=sv.source_id AND d.source_active=false)",
                    (context.tenant_id, context.workspace_id, version_id)).fetchone()
                if row is None:
                    continue
                spans = {}
                for span_id, canonical in connection.execute(
                        "SELECT record_id,canonical_json FROM evidence_spans WHERE tenant_id=%s AND workspace_id=%s AND source_version_id=%s ORDER BY record_id",
                        (context.tenant_id, context.workspace_id, version_id)).fetchall():
                    page = canonical.get("page") if isinstance(canonical, dict) else None
                    if isinstance(page, int) and page not in spans:
                        spans[page] = str(span_id)
                parser = row[2] if isinstance(row[2], dict) else {}
                sections, truncated = split_sections(version_id, parser, max_chars=max_chars_per_source, spans_by_page=spans)
                if not sections:
                    # 본문이 없으면 근거 구간 텍스트라도 쓴다(색인 핵심 사실).
                    for span_id, canonical in connection.execute(
                            "SELECT record_id,canonical_json FROM evidence_spans WHERE tenant_id=%s AND workspace_id=%s AND source_version_id=%s ORDER BY record_id",
                            (context.tenant_id, context.workspace_id, version_id)).fetchall():
                        if isinstance(canonical, dict) and isinstance(canonical.get("text"), str):
                            loc = canonical.get("locator") if isinstance(canonical.get("locator"), dict) else {}
                            sections.append(SourceSection(version_id, str(span_id), str(loc.get("kind") or "section"),
                                                          str(loc.get("value") or canonical.get("page") or "s1"), None, canonical["text"]))
                result.append(SourceText(str(row[0]), version_id, str(row[1]), tuple(sections), truncated))
        if not any(item.sections for item in result):
            raise StudioError("STUDIO_NO_READY_SOURCE", 409)
        return tuple(result)

    def read_section(self, context: StudioContext, source_version_id: str, locator_kind: str, locator_value: str) -> tuple[str, str] | None:
        """(파일명, 본문) — 근거 보기에서 span이 없는 로케이터를 다시 찾는다."""
        for source in self.read(context, [source_version_id]):
            matches = [s.text for s in source.sections if s.locator_kind == locator_kind and s.locator_value == locator_value]
            if matches:
                return source.filename, "\n\n".join(matches)
        return None
