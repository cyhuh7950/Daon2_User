"""Studio v2 내보내기 렌더러. 기존 studio_export.py(승인 흐름용)는 수정하지 않는다. WO-F2 §3."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote
from xml.sax.saxutils import escape

from .studio_v2_ooxml import build_docx, build_pptx
from .studio_workspace import StudioError

_FONT_PATH = Path(__file__).parent / "assets" / "NanumGothic-Regular.ttf"
CLOSING_NOTE = "AI 작성 초안, 전문가 검토 필요"


@dataclass(frozen=True, slots=True)
class StudioV2Export:
    content: bytes
    media_type: str
    ascii_filename: str
    quoted_filename: str
    sha256: str


MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf", "mp3": "audio/mpeg", "mp4": "video/mp4", "vtt": "text/vtt; charset=utf-8", "png": "image/png", "svg": "image/svg+xml", "json": "application/json",
    "csv": "text/csv; charset=utf-8", "md": "text/markdown; charset=utf-8", "txt": "text/plain; charset=utf-8",
}


def safe_stem(title: str) -> str:
    stem = re.sub(r"[^\w가-힣.-]", "_", title or "output", flags=re.UNICODE).strip("._") or "output"
    return stem[:60]


def _bundle(stem: str, extension: str, body: bytes) -> StudioV2Export:
    filename = f"{stem}.{extension}"
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or f"output.{extension}"
    return StudioV2Export(body, MEDIA[extension], ascii_name, quote(filename, safe=""), hashlib.sha256(body).hexdigest())


# ------------------------------------------------------------------ 공통 요소 모델
def _refs(value: object) -> list[str]:
    return [str(r) for r in value] if isinstance(value, list) else []


def _where(item: Mapping[str, Any]) -> str:
    kind, value = item.get("locator_kind"), item.get("locator_value")
    if kind == "page":
        return f"{value}쪽"
    return f"{kind or ''} {value or ''}".strip()


def _appendix(output: Mapping[str, Any]) -> list[tuple]:
    evidence = output.get("evidence") or []
    if not evidence:
        return []
    rows: list[list[str]] = [["번호", "출처", "위치"]]
    for item in evidence:
        rows.append([f"[{item.get('ref_id')}]", str(item.get("source_name") or item.get("origin") or ""), _where(item)])
    return [("pagebreak",), ("h1", "근거 목록"), ("table", rows)]


def _content(output: Mapping[str, Any]) -> Mapping[str, Any]:
    revision = output.get("revision")
    if not revision:
        raise StudioError("RESOURCE_UNAVAILABLE", 404)
    return revision["content"]


def to_elements(output: Mapping[str, Any]) -> list[tuple]:
    type_id, content = str(output["type_id"]), _content(output)
    if type_id == "authored_document":
        from .authoring.export import authored_elements
        return authored_elements(output)
    body = content.get("body") or {}
    title = str(body.get("title") or output.get("title") or "")
    els: list[tuple] = [("title", title)]
    if type_id == "report":
        if body.get("summary"):
            els.append(("p", str(body["summary"]), []))
        for section in body.get("sections", []):
            els.append(("h1", str(section.get("heading", ""))))
            for block in section.get("blocks", []):
                if block.get("type") == "bullets":
                    els.append(("bullets", [str(i) for i in block.get("items", [])], _refs(block.get("refs"))))
                elif block.get("type") == "table":
                    els.append(("table", block.get("rows", [])))
                else:
                    els.append(("p", str(block.get("text", "")), _refs(block.get("refs"))))
    elif type_id == "data_table":
        columns = body.get("columns", [])
        rows = [[c.get("label", c.get("key")) for c in columns]]
        for row in body.get("rows", []):
            rows.append([(row.get("cells", {}).get(c["key"]) or {}).get("value", "") for c in columns])
        els.append(("table", rows))
        for note in body.get("notes", []):
            els.append(("p", str(note), []))
    elif type_id == "flashcards":
        rows = [["앞면", "뒷면", "근거"]] + [[c.get("front", ""), c.get("back", ""), " ".join(f"[{r}]" for r in _refs(c.get("refs")))] for c in body.get("cards", [])]
        els.append(("table", rows))
    elif type_id == "quiz":
        for n, q in enumerate(body.get("questions", []), 1):
            els.append(("h2", f"{n}. {q.get('q', '')}"))
            els.append(("bullets", [str(o) for o in q.get("options", [])], []))
            answer = q.get("answer_index")
            letter = "①②③④"[answer] if isinstance(answer, int) and 0 <= answer < 4 else "?"
            els.append(("p", f"정답: {letter} — {q.get('explanation', '')}", _refs(q.get("refs"))))
    elif type_id == "slides":
        for slide in body.get("slides", []):
            els.append(("h1", str(slide.get("title", ""))))
            if slide.get("bullets"):
                els.append(("bullets", [str(b) for b in slide["bullets"]], _refs(slide.get("refs"))))
            if slide.get("table"):
                els.append(("table", [slide["table"].get("columns", []), *slide["table"].get("rows", [])]))
            if slide.get("notes"):
                els.append(("p", "발표자 노트: " + str(slide["notes"]), []))
    elif type_id == "memo":
        els.append(("p", str(body.get("markdown", "")), []))
    else:
        raise StudioError("EXPORT_FORMAT_UNSUPPORTED", 400)
    return els + _appendix(output)


# ------------------------------------------------------------------ md / csv / json / xlsx
def render_markdown(output: Mapping[str, Any]) -> str:
    if output.get("type_id") == "memo":
        return str((_content(output).get("body") or {}).get("markdown", ""))
    lines: list[str] = []
    for el in to_elements(output):
        kind = el[0]
        if kind == "title":
            lines.append(f"# {el[1]}\n")
        elif kind == "h1":
            lines.append(f"\n## {el[1]}\n")
        elif kind == "h2":
            lines.append(f"\n### {el[1]}\n")
        elif kind == "p":
            refs = "".join(f"[^{r}]" for r in el[2]) if len(el) > 2 else ""
            lines.append(f"{el[1]}{refs}\n")
        elif kind == "bullets":
            refs = "".join(f"[^{r}]" for r in el[2]) if len(el) > 2 else ""
            lines += [f"- {item}" for item in el[1]]
            if refs:
                lines[-1] += refs
            lines.append("")
        elif kind == "table":
            rows = el[1]
            if rows:
                width = len(rows[0])
                lines.append("| " + " | ".join(str(c).replace("|", "\\|") for c in rows[0]) + " |")
                lines.append("|" + "---|" * width)
                lines += ["| " + " | ".join(str(c).replace("|", "\\|") for c in (list(r) + [""] * width)[:width]) + " |" for r in rows[1:]]
                lines.append("")
    for item in output.get("evidence") or []:
        lines.append(f"[^{item.get('ref_id')}]: {item.get('source_name') or item.get('origin')} {_where(item)}")
    return "\n".join(lines).rstrip() + "\n"


def _csv_rows(output: Mapping[str, Any]) -> list[list[str]]:
    type_id, body = str(output["type_id"]), (_content(output).get("body") or {})
    rows: list[list[str]]
    if type_id == "data_table":
        columns = body.get("columns", [])
        rows = [[str(c.get("label", c.get("key"))) for c in columns]]
        for row in body.get("rows", []):
            rows.append([str((row.get("cells", {}).get(c["key"]) or {}).get("value", "")) for c in columns])
    elif type_id == "flashcards":
        rows = [["앞면", "뒷면", "힌트", "근거"]] + [[c.get("front", ""), c.get("back", ""), c.get("hint", ""), " ".join(_refs(c.get("refs")))] for c in body.get("cards", [])]
    elif type_id == "quiz":
        rows = [["문항", "보기1", "보기2", "보기3", "보기4", "정답", "해설", "근거"]]
        for q in body.get("questions", []):
            opts = (list(q.get("options", [])) + [""] * 4)[:4]
            rows.append([q.get("q", ""), *opts, str(int(q.get("answer_index", 0)) + 1), q.get("explanation", ""), " ".join(_refs(q.get("refs")))])
    else:
        raise StudioError("EXPORT_FORMAT_UNSUPPORTED", 400)
    evidence = output.get("evidence") or []
    if evidence:
        rows += [[], ["근거 번호", "출처", "위치"]] + [[str(e.get("ref_id")), str(e.get("source_name") or e.get("origin") or ""), _where(e)] for e in evidence]
    return rows


def render_csv(output: Mapping[str, Any]) -> bytes:
    buffer = StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerows(_csv_rows(output))
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _sheet(rows: Sequence[Sequence[object]], *, header_style: int = 1) -> str:
    out = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, value in enumerate(row):
            text = escape("".join(ch for ch in str(value) if ch in "\t\n\r" or ord(ch) >= 32))
            style = f' s="{header_style}"' if r == 1 else ""
            cells.append(f'<c r="{_col(c)}{r}" t="inlineStr"{style}><is><t xml:space="preserve">{text}</t></is></c>')
        out.append(f'<row r="{r}">{"".join(cells)}</row>')
    width = max((len(r) for r in rows), default=1)
    cols = "".join(f'<col min="{i}" max="{i}" width="24" customWidth="1"/>' for i in range(1, width + 1))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<cols>{cols}</cols><sheetData>{"".join(out)}</sheetData></worksheet>')


def render_xlsx(output: Mapping[str, Any]) -> bytes:
    if str(output["type_id"]) != "data_table":
        raise StudioError("EXPORT_FORMAT_UNSUPPORTED", 400)
    body = _content(output).get("body") or {}
    columns = body.get("columns", [])
    data = [[c.get("label", c.get("key")) for c in columns]]
    refs = [["행", "열", "근거"]]
    for r, row in enumerate(body.get("rows", []), 2):
        cells = row.get("cells", {})
        data.append([(cells.get(c["key"]) or {}).get("value", "") for c in columns])
        for c_index, c in enumerate(columns):
            refs_for = _refs((cells.get(c["key"]) or {}).get("refs"))
            if refs_for:
                refs.append([r, columns[c_index].get("label", c["key"]), " ".join(f"[{x}]" for x in refs_for)])
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    entries = {
        "[Content_Types].xml": f'{xml}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": f'{xml}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'{xml}<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets><sheet name="데이터" sheetId="1" r:id="rId1"/><sheet name="근거" sheetId="2" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'{xml}<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{rel}/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="{rel}/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": f'{xml}<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="맑은 고딕"/></font><font><b/><sz val="11"/><name val="맑은 고딕"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": _sheet(data),
        "xl/worksheets/sheet2.xml": _sheet(refs),
    }
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()


# ------------------------------------------------------------------ 마인드맵(svg/png)
LEVEL_GAP, SIBLING_GAP, NODE_H = 260, 64, 40


def layout_tree(nodes: Sequence[Mapping[str, Any]]) -> dict[str, tuple[int, int]]:
    """가로 트리: x = 깊이 × 간격, y = 잎 순서 × 간격(부모는 자식 평균)."""
    children: dict[str | None, list[str]] = {}
    ids = {str(n["id"]) for n in nodes}
    for n in nodes:
        parent = n.get("parent")
        children.setdefault(str(parent) if parent in ids else None, []).append(str(n["id"]))
    positions: dict[str, tuple[int, int]] = {}
    cursor = [0]

    def place(node_id: str, depth: int) -> float:
        kids = children.get(node_id, [])
        if not kids:
            y = cursor[0] * SIBLING_GAP
            cursor[0] += 1
        else:
            ys = [place(k, depth + 1) for k in kids]
            y = sum(ys) / len(ys)
        positions[node_id] = (depth * LEVEL_GAP, int(y))
        return y

    for root in children.get(None, []):
        place(root, 0)
    return positions


def _mind_map(output: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], dict[str, tuple[int, int]]]:
    nodes = (_content(output).get("body") or {}).get("nodes", [])
    return nodes, layout_tree(nodes)


_LEVEL_COLORS = ("#3b6fd8", "#3fa37a", "#8e5bd1", "#e0a100", "#2aa3b8", "#d9534f")


def render_svg(output: Mapping[str, Any]) -> bytes:
    nodes, pos = _mind_map(output)
    width = max((x for x, _ in pos.values()), default=0) + 240 + 40
    height = max((y for _, y in pos.values()), default=0) + NODE_H + 40
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="NanumGothic, \'Malgun Gothic\', sans-serif">',
             f'<rect width="{width}" height="{height}" fill="#ffffff"/>']
    for n in nodes:
        parent = n.get("parent")
        if parent in pos and str(n["id"]) in pos:
            (px, py), (cx, cy) = pos[str(parent)], pos[str(n["id"])]
            parts.append(f'<path d="M{px + 200 + 20},{py + 20 + NODE_H // 2} C{px + 200 + 60},{py + 20 + NODE_H // 2} {cx + 20 - 40},{cy + 20 + NODE_H // 2} {cx + 20},{cy + 20 + NODE_H // 2}" fill="none" stroke="#9aa3b5" stroke-width="2"/>')
    depth_of = {k: v[0] // LEVEL_GAP for k, v in pos.items()}
    for n in nodes:
        key = str(n["id"])
        if key not in pos:
            continue
        x, y = pos[key]
        color = _LEVEL_COLORS[depth_of[key] % len(_LEVEL_COLORS)]
        parts.append(f'<rect x="{x + 20}" y="{y + 20}" width="200" height="{NODE_H}" rx="12" fill="{color}"/>')
        parts.append(f'<text x="{x + 120}" y="{y + 20 + NODE_H // 2 + 5}" font-size="14" text-anchor="middle" fill="#ffffff">{escape(str(n.get("label", ""))[:16])}</text>')
    parts.append("</svg>")
    return "".join(parts).encode("utf-8")


def render_png(output: Mapping[str, Any]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    nodes, pos = _mind_map(output)
    width = max((x for x, _ in pos.values()), default=0) + 240 + 40
    height = max((y for _, y in pos.values()), default=0) + NODE_H + 40
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(_FONT_PATH), 14)
    for n in nodes:
        parent = n.get("parent")
        if parent in pos and str(n["id"]) in pos:
            (px, py), (cx, cy) = pos[str(parent)], pos[str(n["id"])]
            draw.line([(px + 220, py + 20 + NODE_H // 2), (cx + 20, cy + 20 + NODE_H // 2)], fill="#9aa3b5", width=2)
    for n in nodes:
        key = str(n["id"])
        if key not in pos:
            continue
        x, y = pos[key]
        color = _LEVEL_COLORS[(x // LEVEL_GAP) % len(_LEVEL_COLORS)]
        draw.rounded_rectangle([x + 20, y + 20, x + 220, y + 20 + NODE_H], radius=12, fill=color)
        label = str(n.get("label", ""))[:16]
        box = draw.textbbox((0, 0), label, font=font)
        draw.text((x + 120 - (box[2] - box[0]) / 2, y + 20 + (NODE_H - (box[3] - box[1])) / 2 - box[1]), label, font=font, fill="white")
    out = BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


# ------------------------------------------------------------------ pdf
def render_pdf(output: Mapping[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    name = "DaonNanumGothic"
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(_FONT_PATH)))
    base = ParagraphStyle("base", fontName=name, fontSize=10, leading=15, wordWrap="CJK")
    styles = {"title": ParagraphStyle("t", parent=base, fontSize=20, leading=26, spaceAfter=10),
              "h1": ParagraphStyle("h1", parent=base, fontSize=14, leading=20, spaceBefore=12, spaceAfter=6),
              "h2": ParagraphStyle("h2", parent=base, fontSize=12, leading=17, spaceBefore=8, spaceAfter=4)}

    def esc(text: object) -> str:
        return escape("".join(ch for ch in str(text) if ch in "\t\n\r" or ord(ch) >= 32)).replace("\n", "<br/>")

    flow: list[Any] = []
    for el in to_elements(output):
        kind = el[0]
        if kind in styles:
            flow.append(Paragraph(esc(el[1]), styles[kind]))
        elif kind == "p":
            refs = (" <font size=7 color='#666666'>" + esc("".join(f"[{r}]" for r in el[2])) + "</font>") if len(el) > 2 and el[2] else ""
            flow.append(Paragraph(esc(el[1]) + refs, base))
            flow.append(Spacer(1, 3))
        elif kind == "bullets":
            refs = (" <font size=7 color='#666666'>" + esc("".join(f"[{r}]" for r in el[2])) + "</font>") if len(el) > 2 and el[2] else ""
            items = [ListItem(Paragraph(esc(t) + (refs if i == len(el[1]) - 1 else ""), base)) for i, t in enumerate(el[1])]
            flow.append(ListFlowable(items, bulletType="bullet", leftIndent=14, bulletFontName=name))
        elif kind == "table":
            rows = [[Paragraph(esc(c), base) for c in row] for row in el[1]]
            if rows:
                table = Table(rows, repeatRows=1)
                table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
                                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf7")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                flow += [table, Spacer(1, 6)]
        elif kind == "pagebreak":
            flow.append(PageBreak())

    def footer(canvas, doc):  # type: ignore[no-untyped-def]
        canvas.setFont(name, 8)
        canvas.drawCentredString(A4[0] / 2, 10 * mm, str(doc.page))

    buffer = BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                      title=str(output.get("title", "")), invariant=1).build(flow, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


# ------------------------------------------------------------------ 진입점
# 형식별 렌더러 등록(F1-08): (형식, 허용 유형 또는 None) -> 렌더러. 새 형식은 register_renderer로 추가한다.
_RENDERERS: dict[tuple[str, str | None], Any] = {}


def register_renderer(format_name: str, renderer, *, type_id: str | None = None) -> None:
    """renderer(stem, output) -> StudioV2Export. type_id가 있으면 그 유형에만 적용된다."""
    _RENDERERS[(format_name, type_id)] = renderer


def _json_renderer(stem, output):  # type: ignore[no-untyped-def]
    return _bundle(stem, "json", json.dumps({**_content(output), "evidence": output.get("evidence", [])}, ensure_ascii=False, indent=2).encode("utf-8"))


def _docx_renderer(stem, output):  # type: ignore[no-untyped-def]
    title = str(output.get("title", ""))
    return _bundle(stem, "docx", build_docx(to_elements(output), title, language=str(_content(output).get("language", "ko"))))


def _authored_pptx_renderer(stem, output):  # type: ignore[no-untyped-def]
    from .authoring.export import authored_slides
    slides = authored_slides(output)
    return _bundle(stem, "pptx", build_pptx(slides, str(slides[0]["title"]) if slides else stem, closing_note=CLOSING_NOTE))


def _slides_pptx_renderer(stem, output):  # type: ignore[no-untyped-def]
    body = _content(output).get("body") or {}
    return _bundle(stem, "pptx", build_pptx(body.get("slides", []), str(body.get("title") or output.get("title", ""))))


register_renderer("json", _json_renderer)
register_renderer("md", lambda stem, output: _bundle(stem, "md", render_markdown(output).encode("utf-8")))
register_renderer("txt", lambda stem, output: _bundle(stem, "txt", render_markdown(output).encode("utf-8")))
register_renderer("csv", lambda stem, output: _bundle(stem, "csv", render_csv(output)))
register_renderer("xlsx", lambda stem, output: _bundle(stem, "xlsx", render_xlsx(output)))
register_renderer("svg", lambda stem, output: _bundle(stem, "svg", render_svg(output)), type_id="mind_map")
register_renderer("png", lambda stem, output: _bundle(stem, "png", render_png(output)), type_id="mind_map")
register_renderer("pdf", lambda stem, output: _bundle(stem, "pdf", render_pdf(output)))
def _infographic_renderer(extension: str):  # type: ignore[no-untyped-def]
    def render(stem, output):  # type: ignore[no-untyped-def]
        from . import studio_infographic as infographic
        body = _content(output).get("body") or {}
        data = {"svg": infographic.render_svg, "png": infographic.render_png, "pdf": infographic.render_pdf}[extension](body)
        return _bundle(stem, extension, data)
    return render


for _extension in ("svg", "png", "pdf"):
    register_renderer(_extension, _infographic_renderer(_extension), type_id="infographic")
register_renderer("docx", _docx_renderer)
register_renderer("pptx", _authored_pptx_renderer, type_id="authored_document")
register_renderer("pptx", _slides_pptx_renderer, type_id="slides")


def export_asset(stem: str, extension: str, body: bytes) -> StudioV2Export:
    """저장된 자산(mp3 등)을 내려받기 형식으로 감싼다."""
    return _bundle(stem, extension, body)


def export_v2(format_name: str, output: Mapping[str, Any]) -> StudioV2Export:
    """output은 PostgresStudioV2Repository.get_output() 결과(최신 또는 지정 리비전)."""
    if not output.get("revision"):
        raise StudioError("RESOURCE_UNAVAILABLE", 404)
    stem = safe_stem(str(output.get("title", "")))
    type_id = str(output["type_id"])
    renderer = _RENDERERS.get((format_name, type_id)) or _RENDERERS.get((format_name, None))
    if renderer is None:
        raise StudioError("EXPORT_FORMAT_UNSUPPORTED", 400)
    return renderer(stem, output)
