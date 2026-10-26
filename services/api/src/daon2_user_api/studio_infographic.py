"""인포그래픽(F7-01): 본문 JSON → 레이아웃 계산 → SVG·PNG·PDF 렌더링, 텍스트 넘침 검사.

본문 형식: {title, subtitle?, sections[{headline, value?, detail?, icon?, refs}]}
SVG와 PNG는 같은 레이아웃(`layout`)을 그린다. 글자 폭은 번들된 한글 폰트(나눔고딕)로 재서 줄을 나누고, 줄 수 상한을 넘으면
"…"로 줄이고 넘침으로 표시한다(`overflow`). 생성기는 넘침이 있으면 경고(INFOGRAPHIC_TEXT_TRUNCATED)를 남긴다.
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.sax.saxutils import escape

FONT_PATH = Path(__file__).parent / "assets" / "NanumGothic-Regular.ttf"
WIDTH = 800
MARGIN = 40
CARD_GAP = 16
CARD_PAD = 20
ICON_BOX = 56
TEXT_X = MARGIN + CARD_PAD + ICON_BOX + 16  # 카드 안 글자 시작
TEXT_W = WIDTH - MARGIN - CARD_PAD - TEXT_X
FONT_TITLE, FONT_SUBTITLE, FONT_HEAD, FONT_VALUE, FONT_DETAIL = 34, 18, 22, 36, 16
MAX_LINES = {"title": 2, "subtitle": 2, "headline": 2, "detail": 3}
LINE_GAP = 1.35
PALETTE = ("#2f55d4", "#c2185b", "#2e7d32", "#ef6c00", "#6a1b9a", "#00838f")
ICON_NAMES = ("chart", "check", "alert", "target", "people", "document", "clock", "star")

# 24x24 좌표계의 단순 도형. ("rect", x, y, w, h) ("line", x1, y1, x2, y2) ("circle", cx, cy, r) ("poly", [(x, y), ...])
ICONS: Mapping[str, Sequence[tuple]] = {
    "chart": (("rect", 4, 13, 4, 7), ("rect", 10, 8, 4, 12), ("rect", 16, 4, 4, 16)),
    "check": (("line", 5, 13, 10, 18), ("line", 10, 18, 19, 6)),
    "alert": (("poly", [(12, 3), (22, 20), (2, 20)]), ("line", 12, 9, 12, 14), ("circle", 12, 17, 0.8)),
    "target": (("circle", 12, 12, 9), ("circle", 12, 12, 5), ("circle", 12, 12, 1.2)),
    "people": (("circle", 12, 8, 4), ("poly", [(4, 21), (6, 15), (18, 15), (20, 21)])),
    "document": (("rect", 5, 3, 14, 18), ("line", 8, 8, 16, 8), ("line", 8, 12, 16, 12), ("line", 8, 16, 13, 16)),
    "clock": (("circle", 12, 12, 9), ("line", 12, 7, 12, 12), ("line", 12, 12, 16, 14)),
    "star": (("poly", [(12, 3), (14.6, 9.2), (21, 9.8), (16, 14), (17.6, 20.5), (12, 17), (6.4, 20.5), (8, 14), (3, 9.8), (9.4, 9.2)]),),
}


@lru_cache(maxsize=8)
def _font(size: int):  # type: ignore[no-untyped-def]
    from PIL import ImageFont
    return ImageFont.truetype(str(FONT_PATH), size)


def _width(text: str, size: int) -> float:
    return _font(size).getlength(text)


def wrap(text: str, size: int, max_width: float, max_lines: int) -> tuple[list[str], bool]:
    """글자 단위로 줄을 나눈다(한글은 띄어쓰기와 무관하게 폭 기준). 줄 수를 넘으면 마지막 줄을 "…"로 줄이고 True를 돌려준다."""
    lines: list[str] = []
    current = ""
    for char in " ".join(str(text).split()):
        if char == " " and not current:
            continue
        if _width(current + char, size) <= max_width:
            current += char
            continue
        lines.append(current.rstrip())
        current = "" if char == " " else char
    if current.strip():
        lines.append(current.rstrip())
    if len(lines) <= max_lines:
        return lines, False
    kept = lines[:max_lines]
    last = kept[-1]
    while last and _width(last + "…", size) > max_width:
        last = last[:-1]
    kept[-1] = last.rstrip() + "…"
    return kept, True


def _line_height(size: int) -> int:
    return round(size * LINE_GAP)


def layout(body: Mapping[str, Any]) -> dict[str, Any]:
    """그릴 위치와 줄 나눔을 계산한다. 값은 모두 정수 좌표다."""
    overflow: list[str] = []
    title, over = wrap(str(body.get("title", "")), FONT_TITLE, WIDTH - 2 * MARGIN, MAX_LINES["title"])
    if over:
        overflow.append("title")
    y = MARGIN + FONT_TITLE
    title_y = y
    y += _line_height(FONT_TITLE) * len(title)
    subtitle: list[str] = []
    subtitle_y = y
    if body.get("subtitle"):
        subtitle, over = wrap(str(body["subtitle"]), FONT_SUBTITLE, WIDTH - 2 * MARGIN, MAX_LINES["subtitle"])
        if over:
            overflow.append("subtitle")
        y += _line_height(FONT_SUBTITLE) * len(subtitle) + 4
    y += 16
    cards = []
    for index, section in enumerate(body.get("sections") or []):
        head, head_over = wrap(str(section.get("headline", "")), FONT_HEAD, TEXT_W, MAX_LINES["headline"])
        value = str(section.get("value") or "")
        value_lines, value_over = wrap(value, FONT_VALUE, TEXT_W, 1) if value else ([], False)
        detail, detail_over = wrap(str(section.get("detail") or ""), FONT_DETAIL, TEXT_W, MAX_LINES["detail"]) if section.get("detail") else ([], False)
        if head_over or value_over or detail_over:
            overflow.append(f"sections[{index}]")
        inner = _line_height(FONT_HEAD) * len(head)
        if value_lines:
            inner += _line_height(FONT_VALUE)
        inner += _line_height(FONT_DETAIL) * len(detail)
        height = max(ICON_BOX, inner) + 2 * CARD_PAD
        cards.append({"index": index, "y": y, "height": height, "headline": head, "value": value_lines[0] if value_lines else "", "detail": detail,
                      "icon": section.get("icon") if section.get("icon") in ICONS else None, "color": PALETTE[index % len(PALETTE)]})
        y += height + CARD_GAP
    height = y - CARD_GAP + MARGIN
    return {"width": WIDTH, "height": height, "title": title, "title_y": title_y, "subtitle": subtitle, "subtitle_y": subtitle_y, "cards": cards, "overflow": overflow}


def _icon_svg(name: str | None, x: float, y: float, size: float, color: str, number: int) -> str:
    scale = size / 24
    if name is None:
        return (f'<text x="{x + size / 2:.1f}" y="{y + size * 0.68:.1f}" font-size="{size * 0.5:.1f}" text-anchor="middle" fill="#ffffff">{number}</text>')
    parts = []
    for prim in ICONS[name]:
        kind = prim[0]
        if kind == "rect":
            parts.append(f'<rect x="{x + prim[1] * scale:.1f}" y="{y + prim[2] * scale:.1f}" width="{prim[3] * scale:.1f}" height="{prim[4] * scale:.1f}" fill="none" stroke="#ffffff" stroke-width="2"/>')
        elif kind == "line":
            parts.append(f'<line x1="{x + prim[1] * scale:.1f}" y1="{y + prim[2] * scale:.1f}" x2="{x + prim[3] * scale:.1f}" y2="{y + prim[4] * scale:.1f}" stroke="#ffffff" stroke-width="2" stroke-linecap="round"/>')
        elif kind == "circle":
            parts.append(f'<circle cx="{x + prim[1] * scale:.1f}" cy="{y + prim[2] * scale:.1f}" r="{prim[3] * scale:.1f}" fill="none" stroke="#ffffff" stroke-width="2"/>')
        elif kind == "poly":
            points = " ".join(f"{x + px * scale:.1f},{y + py * scale:.1f}" for px, py in prim[1])
            parts.append(f'<polygon points="{points}" fill="none" stroke="#ffffff" stroke-width="2" stroke-linejoin="round"/>')
    return "".join(parts)


def render_svg(body: Mapping[str, Any]) -> bytes:
    lay = layout(body)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{lay["width"]}" height="{lay["height"]}" viewBox="0 0 {lay["width"]} {lay["height"]}" font-family="NanumGothic, \'Nanum Gothic\', sans-serif">',
           f'<rect width="100%" height="100%" fill="#ffffff"/>']
    y = lay["title_y"]
    for line in lay["title"]:
        out.append(f'<text x="{MARGIN}" y="{y}" font-size="{FONT_TITLE}" fill="#1b2230">{escape(line)}</text>')
        y += _line_height(FONT_TITLE)
    y = lay["subtitle_y"] + FONT_SUBTITLE
    for line in lay["subtitle"]:
        out.append(f'<text x="{MARGIN}" y="{y}" font-size="{FONT_SUBTITLE}" fill="#5b6577">{escape(line)}</text>')
        y += _line_height(FONT_SUBTITLE)
    for card in lay["cards"]:
        top = card["y"]
        out.append(f'<rect x="{MARGIN}" y="{top}" width="{WIDTH - 2 * MARGIN}" height="{card["height"]}" rx="14" fill="#f1f3f8"/>')
        icon_x, icon_y = MARGIN + CARD_PAD, top + CARD_PAD
        out.append(f'<rect x="{icon_x}" y="{icon_y}" width="{ICON_BOX}" height="{ICON_BOX}" rx="12" fill="{card["color"]}"/>')
        out.append(_icon_svg(card["icon"], icon_x + 12, icon_y + 12, ICON_BOX - 24, card["color"], card["index"] + 1))
        ty = top + CARD_PAD + FONT_HEAD
        for line in card["headline"]:
            out.append(f'<text x="{TEXT_X}" y="{ty}" font-size="{FONT_HEAD}" fill="#1b2230">{escape(line)}</text>')
            ty += _line_height(FONT_HEAD)
        if card["value"]:
            out.append(f'<text x="{TEXT_X}" y="{ty + FONT_VALUE - 8}" font-size="{FONT_VALUE}" fill="{card["color"]}">{escape(card["value"])}</text>')
            ty += _line_height(FONT_VALUE)
        for line in card["detail"]:
            out.append(f'<text x="{TEXT_X}" y="{ty + FONT_DETAIL - 4}" font-size="{FONT_DETAIL}" fill="#5b6577">{escape(line)}</text>')
            ty += _line_height(FONT_DETAIL)
    out.append("</svg>")
    return "".join(out).encode("utf-8")


def render_png(body: Mapping[str, Any], *, scale: int = 1) -> bytes:
    from PIL import Image, ImageDraw
    lay = layout(body)
    image = Image.new("RGB", (lay["width"] * scale, lay["height"] * scale), "white")
    draw = ImageDraw.Draw(image)
    s = scale

    def text(x: float, y: float, value: str, size: int, fill: str) -> None:
        draw.text((x * s, y * s), value, font=_font(size * s), fill=fill, anchor="ls")

    y = lay["title_y"]
    for line in lay["title"]:
        text(MARGIN, y, line, FONT_TITLE, "#1b2230")
        y += _line_height(FONT_TITLE)
    y = lay["subtitle_y"] + FONT_SUBTITLE
    for line in lay["subtitle"]:
        text(MARGIN, y, line, FONT_SUBTITLE, "#5b6577")
        y += _line_height(FONT_SUBTITLE)
    for card in lay["cards"]:
        top = card["y"]
        draw.rounded_rectangle([MARGIN * s, top * s, (WIDTH - MARGIN) * s, (top + card["height"]) * s], radius=14 * s, fill="#f1f3f8")
        ix, iy = MARGIN + CARD_PAD, top + CARD_PAD
        draw.rounded_rectangle([ix * s, iy * s, (ix + ICON_BOX) * s, (iy + ICON_BOX) * s], radius=12 * s, fill=card["color"])
        if card["icon"] is None:
            draw.text(((ix + ICON_BOX / 2) * s, (iy + ICON_BOX / 2) * s), str(card["index"] + 1), font=_font(round(ICON_BOX * 0.5) * s), fill="white", anchor="mm")
        else:
            _icon_png(draw, card["icon"], ix + 12, iy + 12, ICON_BOX - 24, s)
        ty = top + CARD_PAD + FONT_HEAD
        for line in card["headline"]:
            text(TEXT_X, ty, line, FONT_HEAD, "#1b2230")
            ty += _line_height(FONT_HEAD)
        if card["value"]:
            text(TEXT_X, ty + FONT_VALUE - 8, card["value"], FONT_VALUE, card["color"])
            ty += _line_height(FONT_VALUE)
        for line in card["detail"]:
            text(TEXT_X, ty + FONT_DETAIL - 4, line, FONT_DETAIL, "#5b6577")
            ty += _line_height(FONT_DETAIL)
    out = BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def _icon_png(draw: Any, name: str, x: float, y: float, size: float, s: int) -> None:
    k = size / 24
    for prim in ICONS[name]:
        kind = prim[0]
        if kind == "rect":
            draw.rectangle([(x + prim[1] * k) * s, (y + prim[2] * k) * s, (x + (prim[1] + prim[3]) * k) * s, (y + (prim[2] + prim[4]) * k) * s], outline="white", width=2 * s)
        elif kind == "line":
            draw.line([(x + prim[1] * k) * s, (y + prim[2] * k) * s, (x + prim[3] * k) * s, (y + prim[4] * k) * s], fill="white", width=2 * s)
        elif kind == "circle":
            cx, cy, r = (x + prim[1] * k) * s, (y + prim[2] * k) * s, prim[3] * k * s
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline="white", width=2 * s)
        elif kind == "poly":
            pts = [((x + px * k) * s, (y + py * k) * s) for px, py in prim[1]]
            draw.line(pts + [pts[0]], fill="white", width=2 * s, joint="curve")


def render_pdf(body: Mapping[str, Any]) -> bytes:
    """PNG(2배 해상도)를 한 쪽 PDF에 맞춰 넣고, 그 위에 **보이지 않는 글자 층**을 얹는다(복사·검색·스크린리더용).
    쪽 크기는 이미지 비율을 따른다. 글자 층의 위치·줄 나눔은 그림과 같은 layout() 결과를 쓴다."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    lay = layout(body)
    png = render_png(body, scale=2)
    if "NanumGothic" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("NanumGothic", str(FONT_PATH)))
    buffer = BytesIO()
    height = lay["height"]
    pdf = canvas.Canvas(buffer, pagesize=(lay["width"], height), invariant=1)
    pdf.drawImage(ImageReader(BytesIO(png)), 0, 0, width=lay["width"], height=height)

    def invisible(x: float, baseline: float, lines: Sequence[str], size: int) -> float:
        for line in lines:
            text = pdf.beginText(x, height - baseline)
            text.setTextRenderMode(3)           # 3 = 보이지 않음(선택·검색·접근성 도구는 읽는다)
            text.setFont("NanumGothic", size)
            text.textLine(line)
            pdf.drawText(text)
            baseline += _line_height(size)
        return baseline

    invisible(MARGIN, lay["title_y"], lay["title"], FONT_TITLE)
    invisible(MARGIN, lay["subtitle_y"] + FONT_SUBTITLE, lay["subtitle"], FONT_SUBTITLE)
    for card in lay["cards"]:
        ty = card["y"] + CARD_PAD + FONT_HEAD
        ty = invisible(TEXT_X, ty, card["headline"], FONT_HEAD)
        if card["value"]:
            ty = invisible(TEXT_X, ty + FONT_VALUE - 8, [card["value"]], FONT_VALUE)
        invisible(TEXT_X, ty + FONT_DETAIL - 4, card["detail"], FONT_DETAIL)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
