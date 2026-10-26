"""Studio 생성 결과 검증: 라벨 환원, 숫자·날짜·식별자 앵커 검사, 구조 검증. WO-F2 T2-04."""

from __future__ import annotations

import logging

from typing import Any, Mapping, Sequence

from .document_understanding_adapter import _evidence_anchors
from .studio_context_builder import ContextPack
from .studio_workspace import StudioError

MAX_BODY_BYTES = 2 * 1024 * 1024


class Warnings:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def add(self, code: str, path: str, **extra: object) -> None:
        self.items.append({"code": code, "path": path, **extra})


_LOG = logging.getLogger(__name__)


def clean_refs(value: object, pack: ContextPack, warnings: Warnings, path: str, *, required: bool = True) -> list[str]:
    """모델이 돌려준 라벨을 pack에 있는 것만 남긴다. 없으면 UNVERIFIED_CLAIM 경고."""
    known = pack.by_ref()
    refs = [r for r in (value if isinstance(value, list) else []) if isinstance(r, str)]
    valid = list(dict.fromkeys(r for r in refs if r in known))
    if len(valid) != len(set(refs)):
        warnings.add("INVALID_REF_REMOVED", path)
    if required and not valid:
        warnings.add("UNVERIFIED_CLAIM", path)
    return valid


def check_anchors(text: str, refs: Sequence[str], pack: ContextPack, warnings: Warnings, path: str) -> None:
    """문장 속 숫자·날짜·식별자가 참조한 구간에 있어야 한다."""
    if not refs or not text:
        return
    known = pack.by_ref()
    source_text = "\n".join(known[r].text for r in refs if r in known)
    if not _evidence_anchors(text).issubset(_evidence_anchors(source_text)):
        warnings.add("ANCHOR_MISMATCH", path)


def text_field(value: object, limit: int, default: str = "") -> str:
    return value.strip()[:limit] if isinstance(value, str) else default


def as_list(value: object, limit: int) -> list[Any]:
    return value[:limit] if isinstance(value, list) else []


def ensure_size(content: Mapping[str, object]) -> None:
    import json
    if len(json.dumps(content, ensure_ascii=False).encode("utf-8")) > MAX_BODY_BYTES:
        raise StudioError("STUDIO_REVISION_TOO_LARGE", 413)


def fail_if_all_unreferenced(any_valid_ref: bool) -> None:
    """모든 참조가 무효이면 생성 실패로 본다(환각 방지)."""
    if not any_valid_ref:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)


# 유형별 검증기 -------------------------------------------------------------

def validate_report(data: Mapping[str, object], pack: ContextPack) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    w = Warnings()
    used: list[str] = []
    sections = []
    for si, section in enumerate(as_list(data.get("sections"), 10)):
        if not isinstance(section, Mapping):
            continue
        blocks = []
        for bi, block in enumerate(as_list(section.get("blocks"), 40)):
            if not isinstance(block, Mapping):
                continue
            kind = block.get("type") if block.get("type") in {"paragraph", "bullets", "table"} else "paragraph"
            path = f"sections[{si}].blocks[{bi}]"
            refs = clean_refs(block.get("refs"), pack, w, path)
            used += refs
            if kind == "bullets":
                items = [text_field(i, 400) for i in as_list(block.get("items"), 20) if isinstance(i, str) and i.strip()]
                if not items:
                    continue
                check_anchors("\n".join(items), refs, pack, w, path)
                blocks.append({"type": "bullets", "items": items, "refs": refs})
            elif kind == "table":
                rows = [[text_field(c, 200) for c in r] for r in as_list(block.get("rows"), 30) if isinstance(r, list)]
                if rows:
                    blocks.append({"type": "table", "rows": rows, "refs": refs})
            else:
                text = text_field(block.get("text"), 3000)
                if not text:
                    continue
                check_anchors(text, refs, pack, w, path)
                blocks.append({"type": "paragraph", "text": text, "refs": refs})
        heading = text_field(section.get("heading"), 120)
        if heading and blocks:
            sections.append({"heading": heading, "blocks": blocks})
    if not sections:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    fail_if_all_unreferenced(bool(used))
    body = {"title": text_field(data.get("title"), 160), "summary": text_field(data.get("summary"), 1500), "sections": sections}
    ensure_size(body)
    return body, w.items, used


def validate_table(data: Mapping[str, object], pack: ContextPack) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    w = Warnings()
    columns = []
    seen: set[str] = set()
    for column in as_list(data.get("columns"), 12):
        if not isinstance(column, Mapping):
            continue
        key = text_field(column.get("key"), 40)
        if not key or key in seen:
            continue
        seen.add(key)
        ctype = column.get("type") if column.get("type") in {"text", "number", "date"} else "text"
        columns.append({"key": key, "label": text_field(column.get("label"), 60) or key, "type": ctype})
    # 비교표 구조: 첫 열 = 비교 대상, 나머지 열 = 비교 기준(최소 2개). 대상 2개 이상이 있어야 비교가 된다.
    if len(columns) < 3:
        _LOG.warning("table validation failed: columns=%d (need target + 2 criteria)", len(columns))
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    used: list[str] = []
    rows = []
    for ri, row in enumerate(as_list(data.get("rows"), 60)):
        cells_in = row.get("cells") if isinstance(row, Mapping) else None
        if not isinstance(cells_in, Mapping):
            continue
        cells: dict[str, object] = {}
        for column in columns:
            cell = cells_in.get(column["key"])
            value = cell.get("value") if isinstance(cell, Mapping) else cell
            refs = clean_refs(cell.get("refs") if isinstance(cell, Mapping) else [], pack, w, f"rows[{ri}].{column['key']}", required=False)
            used += refs
            text = "" if value is None else str(value).strip()[:300]
            if not text and column is not columns[0]:
                text, refs = "소스에 없음", []  # 소스가 말하지 않는 칸을 지어내지 않는다
            check_anchors(text, refs, pack, w, f"rows[{ri}].{column['key']}")
            cells[str(column["key"])] = {"value": text, "refs": refs}
        if not cells[str(columns[0]["key"])]["value"]:
            continue  # 비교 대상 이름이 없는 행은 버린다
        rows.append({"cells": cells})
    if len(rows) < 2:
        _LOG.warning("table validation failed: usable rows=%d of %d (need 2 targets)", len(rows), len(as_list(data.get("rows"), 60)))
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    fail_if_all_unreferenced(bool(used))
    body = {"title": text_field(data.get("title"), 160), "columns": columns, "rows": rows,
            "notes": [text_field(n, 300) for n in as_list(data.get("notes"), 10) if isinstance(n, str)]}
    ensure_size(body)
    return body, w.items, used


def validate_mind_map(data: Mapping[str, object], pack: ContextPack) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    w = Warnings()
    nodes_in = [n for n in as_list(data.get("nodes"), 60) if isinstance(n, Mapping)]
    nodes: dict[str, dict[str, object]] = {}
    for node in nodes_in:
        nid = text_field(node.get("id"), 40)
        if nid and nid not in nodes:
            nodes[nid] = {"id": nid, "label": text_field(node.get("label"), 40) or nid,
                          "parent": node.get("parent") if isinstance(node.get("parent"), str) else None,
                          "summary": text_field(node.get("summary"), 300), "_refs": node.get("refs")}
    roots = [n for n in nodes.values() if n["parent"] is None or n["parent"] not in nodes]
    if not roots:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    root = roots[0]
    for extra in roots[1:]:  # 루트는 하나만 — 나머지는 루트의 자식으로 붙인다.
        extra["parent"] = root["id"]
    root["parent"] = None
    depth_cache: dict[str, int] = {}

    def depth(nid: str, trail: tuple[str, ...] = ()) -> int:
        if nid in depth_cache:
            return depth_cache[nid]
        parent = nodes[nid]["parent"]
        if parent is None or nid in trail:
            value = 0
        else:
            value = depth(str(parent), trail + (nid,)) + 1
        depth_cache[nid] = value
        return value

    used: list[str] = []
    result = []
    for nid, node in nodes.items():
        if depth(nid) > 5:
            continue
        if node["parent"] is not None and (node["parent"] not in nodes or depth(str(node["parent"])) >= depth(nid)):
            continue
        refs = clean_refs(node.pop("_refs"), pack, w, f"nodes.{nid}", required=nid != root["id"])
        used += refs
        node["refs"] = refs
        result.append(node)
    ids = {n["id"] for n in result}
    result = [n for n in result if n["parent"] is None or n["parent"] in ids]
    if len(result) < 2:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    fail_if_all_unreferenced(bool(used))
    body = {"root": root["id"], "nodes": result}
    ensure_size(body)
    return body, w.items, used


def validate_flashcards(data: Mapping[str, object], pack: ContextPack) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    w = Warnings()
    used: list[str] = []
    cards, seen = [], set()
    for ci, card in enumerate(as_list(data.get("cards"), 60)):
        if not isinstance(card, Mapping):
            continue
        front, back = text_field(card.get("front"), 120), text_field(card.get("back"), 400)
        key = "".join(front.split()).lower()
        if not front or not back or key in seen:
            continue
        seen.add(key)
        refs = clean_refs(card.get("refs"), pack, w, f"cards[{ci}]")
        used += refs
        check_anchors(back, refs, pack, w, f"cards[{ci}]")
        item: dict[str, object] = {"front": front, "back": back, "refs": refs}
        hint = text_field(card.get("hint"), 200)
        if hint:
            item["hint"] = hint
        cards.append(item)
    if not cards:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    fail_if_all_unreferenced(bool(used))
    body = {"cards": cards}
    ensure_size(body)
    return body, w.items, used


def validate_quiz(data: Mapping[str, object], pack: ContextPack) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    w = Warnings()
    used: list[str] = []
    questions = []
    for qi, q in enumerate(as_list(data.get("questions"), 40)):
        if not isinstance(q, Mapping):
            continue
        options = [text_field(o, 200) for o in as_list(q.get("options"), 8) if isinstance(o, str) and o.strip()]
        answer = q.get("answer_index")
        if len(options) != 4 or len(set(options)) != 4 or type(answer) is not int or not 0 <= answer < 4:
            continue
        text = text_field(q.get("q"), 300)
        explanation = text_field(q.get("explanation"), 600)
        if not text or not explanation:
            continue  # 퀴즈 한 문항 = 문제 + 정답 + 해설
        refs = clean_refs(q.get("refs"), pack, w, f"questions[{qi}]")
        used += refs
        check_anchors(options[answer], refs, pack, w, f"questions[{qi}].answer")
        questions.append({"q": text, "options": options, "answer_index": answer,
                          "explanation": explanation, "refs": refs})
    if not questions:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    fail_if_all_unreferenced(bool(used))
    body = {"questions": questions}
    ensure_size(body)
    return body, w.items, used


def validate_slides(data: Mapping[str, object], pack: ContextPack) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    w = Warnings()
    used: list[str] = []
    slides = []
    for si, slide in enumerate(as_list(data.get("slides"), 20)):
        if not isinstance(slide, Mapping):
            continue
        title = text_field(slide.get("title"), 100)
        bullets = [text_field(b, 120) for b in as_list(slide.get("bullets"), 6) if isinstance(b, str) and b.strip()][:5]
        if not title or (si > 0 and not bullets and not isinstance(slide.get("table"), Mapping)):
            continue  # 표지 뒤의 슬라이드는 챕터 제목과 핵심 내용을 함께 가진다
        layout = slide.get("layout") if slide.get("layout") in {"title", "bullets", "two_column", "table"} else "bullets"
        if si == 0:
            layout = "title"
        refs = clean_refs(slide.get("refs"), pack, w, f"slides[{si}]", required=si != 0)
        used += refs
        check_anchors("\n".join(bullets), refs, pack, w, f"slides[{si}]")
        item: dict[str, object] = {"layout": layout, "title": title, "bullets": bullets,
                                   "notes": text_field(slide.get("notes"), 800), "refs": refs}
        table = slide.get("table")
        if layout == "table" and isinstance(table, Mapping):
            cols = [text_field(c, 40) for c in as_list(table.get("columns"), 6)]
            rows = [[text_field(c, 60) for c in r] for r in as_list(table.get("rows"), 10) if isinstance(r, list)]
            if cols and rows:
                item["table"] = {"columns": cols, "rows": rows}
        slides.append(item)
    if len(slides) < 2:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    fail_if_all_unreferenced(bool(used))
    body = {"title": text_field(data.get("title"), 160), "slides": slides}
    ensure_size(body)
    return body, w.items, used


def validate_infographic(data: Mapping[str, object], pack: ContextPack) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    """인포그래픽 본문 검증(F7-01): 섹션 2~8개, 글자 수 상한, 근거 라벨 환원, 숫자 앵커 검사, 텍스트 넘침 경고."""
    from .studio_infographic import ICON_NAMES, layout
    w = Warnings()
    used: list[str] = []
    sections = []
    for si, section in enumerate(as_list(data.get("sections"), 8)):
        if not isinstance(section, Mapping):
            continue
        headline = text_field(section.get("headline"), 40)
        if not headline:
            continue
        refs = clean_refs(section.get("refs"), pack, w, f"sections[{si}]")
        used += refs
        value, detail = text_field(section.get("value"), 20), text_field(section.get("detail"), 120)
        check_anchors(f"{value} {detail}", refs, pack, w, f"sections[{si}]")
        item: dict[str, object] = {"headline": headline, "refs": refs}
        if value:
            item["value"] = value
        if detail:
            item["detail"] = detail
        if section.get("icon") in ICON_NAMES:
            item["icon"] = section["icon"]
        sections.append(item)
    if len(sections) < 2:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    fail_if_all_unreferenced(bool(used))
    body: dict[str, object] = {"title": text_field(data.get("title"), 60) or sections[0]["headline"], "sections": sections}
    subtitle = text_field(data.get("subtitle"), 120)
    if subtitle:
        body["subtitle"] = subtitle
    for path in layout(body)["overflow"]:
        w.add("INFOGRAPHIC_TEXT_TRUNCATED", path)
    ensure_size(body)
    return body, w.items, used


def validate_audio_script(data: Mapping[str, object], pack: ContextPack, *, min_lines: int = 6, max_lines: int = 120) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    """오디오 개요 스크립트 검증(F7-03): 화자 A/B 줄 6~120개, 줄당 400자 이하, 근거 라벨 환원, 숫자 앵커 검사.

    text는 화면·자막용 원문이고 speech는 소리 내어 읽을 형태(없으면 text)다. 앵커 검사는 text에 한다.
    """
    from .tts_engines import MAX_LINE_CHARS
    w = Warnings()
    used: list[str] = []
    lines: list[dict[str, object]] = []
    for index, row in enumerate(as_list(data.get("script"), max_lines)):
        if not isinstance(row, Mapping) or row.get("speaker") not in ("A", "B"):
            continue
        text = text_field(row.get("text"), MAX_LINE_CHARS)
        if not text:
            continue
        refs = clean_refs(row.get("refs"), pack, w, f"script[{index}]")
        used += refs
        check_anchors(text, refs, pack, w, f"script[{index}]")
        item: dict[str, object] = {"speaker": row["speaker"], "text": text, "refs": refs}
        speech = text_field(row.get("speech"), MAX_LINE_CHARS)
        if speech and speech != text:
            item["speech"] = speech
        lines.append(item)
    if len(lines) < min_lines or len({line["speaker"] for line in lines}) < 2:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    fail_if_all_unreferenced(bool(used))
    body: dict[str, object] = {"title": text_field(data.get("title"), 60) or "오디오 개요", "script": lines}
    summary = text_field(data.get("summary"), 300)
    if summary:
        body["summary"] = summary
    ensure_size(body)
    return body, w.items, used


def validate_video_scenes(data: Mapping[str, object], pack: ContextPack, *, max_scenes: int = 20) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    """동영상 개요 장면 검증(F7-05): 슬라이드 규칙(validate_slides)에 장면별 내레이션을 더한다.

    scenes[]는 슬라이드 필드(layout,title,bullets,table,refs)와 narration(자막·원문, 600자 이하)·speech(읽는 형태, 선택)를 갖는다.
    장면은 3~20개이고, 내레이션이 없으면 제목+글머리로 대신하며 NARRATION_FALLBACK 경고를 남긴다.
    """
    raw = [dict(row, notes=row.get("narration") or row.get("notes") or "") for row in as_list(data.get("scenes"), max_scenes) if isinstance(row, Mapping)]
    body, warnings, used = validate_slides({"title": data.get("title"), "slides": raw}, pack)
    w = Warnings()
    w.items.extend(warnings)
    scenes: list[dict[str, object]] = []
    for index, slide in enumerate(body["slides"]):  # type: ignore[arg-type]
        source_row = next((r for i, r in enumerate(raw) if text_field(r.get("title"), 100) == slide["title"]), {})
        narration = text_field(slide.get("notes"), 600)
        if not narration:
            narration = text_field(" ".join([str(slide["title"]), *[str(b) for b in slide["bullets"]]]), 600)  # type: ignore[union-attr]
            w.add("NARRATION_FALLBACK", f"scenes[{index}]")
        check_anchors(narration, slide["refs"], pack, w, f"scenes[{index}].narration")  # type: ignore[arg-type]
        scene = {k: v for k, v in slide.items() if k != "notes"}
        scene["narration"] = narration
        speech = text_field(source_row.get("speech"), 600)
        if speech and speech != narration:
            scene["speech"] = speech
        scenes.append(scene)
    if len(scenes) < 3:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    result: dict[str, object] = {"title": body["title"] or str(scenes[0]["title"]), "scenes": scenes}
    ensure_size(result)
    return result, w.items, used
