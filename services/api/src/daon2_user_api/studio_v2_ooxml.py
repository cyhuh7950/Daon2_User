"""Studio v2 OOXML 렌더러(DOCX, PPTX). 새 라이브러리 없이 zipfile + 직접 XML(결정 G5). WO-F2 §3."""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Sequence
from xml.sax.saxutils import escape

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_FONT = "맑은 고딕"
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _x(value: object) -> str:
    text = "" if value is None else str(value)
    # XML 1.0에서 허용되지 않는 제어 문자를 제거한다.
    return escape("".join(ch for ch in text if ch in "\t\n\r" or ord(ch) >= 32))


def _zip(entries: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()


def _rels(items: Sequence[tuple[str, str, str]]) -> str:
    body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{g}"/>' for i, t, g in items)
    return f'{_XML}<Relationships xmlns="{_REL_NS}">{body}</Relationships>'


# ---------------------------------------------------------------- DOCX
def _run(text: str, *, bold: bool = False, sup: bool = False, color: str | None = None, size: int | None = None) -> str:
    props = ""
    if bold:
        props += "<w:b/>"
    if color:
        props += f'<w:color w:val="{color}"/>'
    if size:
        props += f'<w:sz w:val="{size}"/>'
    if sup:
        props += '<w:vertAlign w:val="superscript"/>'
    return f'<w:r>{"<w:rPr>" + props + "</w:rPr>" if props else ""}<w:t xml:space="preserve">{_x(text)}</w:t></w:r>'


def _para(text: str, style: str | None = None, refs: Sequence[str] = (), *, numbered: bool = False, bold: bool = False) -> str:
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if numbered:
        ppr += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
    runs = _run(text, bold=bold)
    if refs:
        runs += _run(" " + "".join(f"[{r}]" for r in refs), sup=True, color="666666")
    return f'<w:p>{"<w:pPr>" + ppr + "</w:pPr>" if ppr else ""}{runs}</w:p>'


def _table(rows: Sequence[Sequence[object]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    grid = "".join('<w:gridCol w:w="%d"/>' % (9000 // width) for _ in range(width))
    out = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="5000" w:type="pct"/></w:tblPr>', f"<w:tblGrid>{grid}</w:tblGrid>"]
    for index, row in enumerate(rows):
        cells = list(row) + [""] * (width - len(row))
        out.append("<w:tr>" + "".join(
            f'<w:tc><w:tcPr><w:tcW w:w="{9000 // width}" w:type="dxa"/></w:tcPr><w:p>{_run(str(c), bold=index == 0)}</w:p></w:tc>' for c in cells) + "</w:tr>")
    out.append("</w:tbl><w:p/>")
    return "".join(out)


STYLES = f"""{_XML}<w:styles {_W}><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{_FONT}" w:hAnsi="{_FONT}" w:eastAsia="{_FONT}" w:cs="{_FONT}"/><w:sz w:val="21"/><w:lang w:val="ko-KR" w:eastAsia="ko-KR"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="320" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:before="240" w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="44"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="999999"/><w:left w:val="single" w:sz="4" w:space="0" w:color="999999"/><w:bottom w:val="single" w:sz="4" w:space="0" w:color="999999"/><w:right w:val="single" w:sz="4" w:space="0" w:color="999999"/><w:insideH w:val="single" w:sz="4" w:space="0" w:color="999999"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="999999"/></w:tblBorders></w:tblPr></w:style>
</w:styles>"""

NUMBERING = f"""{_XML}<w:numbering {_W}><w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>"""


def build_docx(elements: Sequence[tuple], title: str, *, language: str = "ko") -> bytes:
    """elements: ('title',text) ('h1',text) ('h2',text) ('p',text,refs) ('bullets',items,refs) ('table',rows) ('pagebreak',)."""
    body: list[str] = []
    for element in elements:
        kind = element[0]
        if kind == "title":
            body.append(_para(element[1], "Title"))
        elif kind in {"h1", "h2"}:
            body.append(_para(element[1], "Heading1" if kind == "h1" else "Heading2"))
        elif kind == "p":
            body.append(_para(element[1], None, element[2] if len(element) > 2 else ()))
        elif kind == "bullets":
            refs = element[2] if len(element) > 2 else ()
            for index, item in enumerate(element[1]):
                body.append(_para(item, "ListBullet", refs if index == len(element[1]) - 1 else (), numbered=True))
        elif kind == "table":
            body.append(_table(element[1]))
        elif kind == "pagebreak":
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
    sect = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1304" w:bottom="1440" w:left="1304" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
    document = f'{_XML}<w:document {_W}><w:body>{"".join(body)}{sect}</w:body></w:document>'
    entries = {
        "[Content_Types].xml": f'{_XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>',
        "_rels/.rels": _rels([("rId1", f"{_R}/officeDocument", "word/document.xml"),
                              ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml")]),
        "word/document.xml": document,
        "word/styles.xml": STYLES,
        "word/numbering.xml": NUMBERING,
        "word/_rels/document.xml.rels": _rels([("rId1", f"{_R}/styles", "styles.xml"), ("rId2", f"{_R}/numbering", "numbering.xml")]),
        "docProps/core.xml": f'{_XML}<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{_x(title)}</dc:title><dc:language>{_x(language)}</dc:language></cp:coreProperties>',
    }
    return _zip(entries)


# ---------------------------------------------------------------- PPTX
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS = f'xmlns:a="{_A}" xmlns:r="{_R}" xmlns:p="{_P}"'
EMU = 914400
SLIDE_W, SLIDE_H = 12192000, 6858000

_THEME = f"""{_XML}<a:theme xmlns:a="{_A}" name="Daon2"><a:themeElements><a:clrScheme name="Daon2"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="1F2A44"/></a:dk2><a:lt2><a:srgbClr val="EEF1F6"/></a:lt2><a:accent1><a:srgbClr val="3B6FD8"/></a:accent1><a:accent2><a:srgbClr val="D9534F"/></a:accent2><a:accent3><a:srgbClr val="3FA37A"/></a:accent3><a:accent4><a:srgbClr val="8E5BD1"/></a:accent4><a:accent5><a:srgbClr val="E0A100"/></a:accent5><a:accent6><a:srgbClr val="2AA3B8"/></a:accent6><a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme><a:fontScheme name="Daon2"><a:majorFont><a:latin typeface="{_FONT}"/><a:ea typeface="{_FONT}"/><a:cs typeface="{_FONT}"/></a:majorFont><a:minorFont><a:latin typeface="{_FONT}"/><a:ea typeface="{_FONT}"/><a:cs typeface="{_FONT}"/></a:minorFont></a:fontScheme><a:fmtScheme name="Daon2"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>"""

_CLRMAP = '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
_GROUP = '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'


def _textbox(shape_id: int, name: str, x: int, y: int, w: int, h: int, paragraphs: Sequence[tuple[str, int, bool, str]], *, anchor: str = "t") -> str:
    """paragraphs: (text, size_pt, bold, color_hex). 글머리표는 text 앞에 '• '를 붙여 표현한다."""
    body = ""
    for text, size, bold, color in paragraphs:
        body += (f'<a:p><a:r><a:rPr lang="ko-KR" sz="{size * 100}" b="{1 if bold else 0}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
                 f'<a:latin typeface="{_FONT}"/><a:ea typeface="{_FONT}"/></a:rPr><a:t>{_x(text)}</a:t></a:r></a:p>')
    if not body:
        body = "<a:p><a:endParaRPr lang=\"ko-KR\"/></a:p>"
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{_x(name)}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" rtlCol="0" anchor="{anchor}"><a:normAutofit/></a:bodyPr><a:lstStyle/>{body}</p:txBody></p:sp>')


def _graphic_table(shape_id: int, x: int, y: int, w: int, h: int, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    cols = max(1, len(columns))
    col_w = w // cols
    row_h = max(300000, min(480000, h // (len(rows) + 1)))

    def cell(text: str, header: bool) -> str:
        fill = '<a:solidFill><a:srgbClr val="%s"/></a:solidFill>' % ("3B6FD8" if header else "FFFFFF")
        color = "FFFFFF" if header else "1F2A44"
        return (f'<a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="ko-KR" sz="1400" b="{1 if header else 0}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
                f'<a:latin typeface="{_FONT}"/><a:ea typeface="{_FONT}"/></a:rPr><a:t>{_x(text)}</a:t></a:r></a:p></a:txBody><a:tcPr>{fill}</a:tcPr></a:tc>')

    grid = "".join(f'<a:gridCol w="{col_w}"/>' for _ in range(cols))
    trs = f'<a:tr h="{row_h}">' + "".join(cell(c, True) for c in columns) + "</a:tr>"
    for row in rows:
        padded = list(row) + [""] * (cols - len(row))
        trs += f'<a:tr h="{row_h}">' + "".join(cell(str(c), False) for c in padded[:cols]) + "</a:tr>"
    return (f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{shape_id}" name="Table {shape_id}"/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/></p:nvGraphicFramePr>'
            f'<p:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{col_w * cols}" cy="{row_h * (len(rows) + 1)}"/></p:xfrm>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr firstRow="1"/><a:tblGrid>{grid}</a:tblGrid>{trs}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>')


def _slide_xml(slide: dict) -> str:
    layout = slide.get("layout", "bullets")
    shapes: list[str] = []
    margin = 640080
    width = SLIDE_W - 2 * margin
    title = str(slide.get("title", ""))
    bullets = [str(b) for b in slide.get("bullets", [])]
    if layout == "title":
        shapes.append(_textbox(2, "Title", margin, 2200000, width, 1200000, [(title, 40, True, "1F2A44")], anchor="b"))
        shapes.append(_textbox(3, "Subtitle", margin, 3500000, width, 1400000, [(b, 20, False, "55607A") for b in bullets[:3]]))
    else:
        shapes.append(_textbox(2, "Title", margin, 380000, width, 900000, [(title, 30, True, "1F2A44")], anchor="ctr"))
        refs = slide.get("refs") or []
        footer = ("근거: " + ", ".join(refs)) if refs else ""
        if layout == "table" and slide.get("table"):
            table = slide["table"]
            shapes.append(_graphic_table(3, margin, 1500000, width, 4200000, [str(c) for c in table.get("columns", [])], table.get("rows", [])))
            if bullets:
                shapes.append(_textbox(4, "Notes", margin, 5800000, width, 600000, [("• " + b, 16, False, "1F2A44") for b in bullets[:2]]))
        elif layout == "two_column" and len(bullets) > 1:
            half = (len(bullets) + 1) // 2
            colw = width // 2 - 150000
            shapes.append(_textbox(3, "Left", margin, 1500000, colw, 4400000, [("• " + b, 20, False, "1F2A44") for b in bullets[:half]]))
            shapes.append(_textbox(4, "Right", margin + colw + 300000, 1500000, colw, 4400000, [("• " + b, 20, False, "1F2A44") for b in bullets[half:]]))
        else:
            shapes.append(_textbox(3, "Body", margin, 1500000, width, 4400000, [("• " + b, 24, False, "1F2A44") for b in bullets]))
        if footer:
            shapes.append(_textbox(9, "Evidence", margin, 6200000, width, 400000, [(footer, 12, False, "8A93A6")]))
    return f'{_XML}<p:sld {_NS}><p:cSld><p:spTree>{_GROUP}{"".join(shapes)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'


def _notes_xml(text: str) -> str:
    return (f'{_XML}<p:notes {_NS}><p:cSld><p:spTree>{_GROUP}'
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/><p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr><p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp>'
            '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="ko-KR"/><a:t>{_x(text)}</a:t></a:r></a:p></p:txBody></p:sp>'
            '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>')


def build_pptx(slides: Sequence[dict], title: str, *, closing_note: str = "") -> bytes:
    """slides: {'layout','title','bullets','table'?,'notes','refs'}. 마지막 슬라이드 노트에 closing_note를 덧붙인다."""
    if not slides:
        raise ValueError("PPTX_EMPTY")
    count = len(slides)
    entries: dict[str, str] = {}
    overrides = [
        ("/ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"),
        ("/ppt/slideMasters/slideMaster1.xml", "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"),
        ("/ppt/slideLayouts/slideLayout1.xml", "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"),
        ("/ppt/notesMasters/notesMaster1.xml", "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"),
        ("/ppt/theme/theme1.xml", "application/vnd.openxmlformats-officedocument.theme+xml"),
        ("/ppt/theme/theme2.xml", "application/vnd.openxmlformats-officedocument.theme+xml"),
        ("/docProps/core.xml", "application/vnd.openxmlformats-package.core-properties+xml"),
        ("/docProps/app.xml", "application/vnd.openxmlformats-officedocument.extended-properties+xml"),
    ]
    for n in range(1, count + 1):
        overrides.append((f"/ppt/slides/slide{n}.xml", "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"))
        overrides.append((f"/ppt/notesSlides/notesSlide{n}.xml", "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"))
    entries["[Content_Types].xml"] = (f'{_XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                                      '<Default Extension="xml" ContentType="application/xml"/>' + "".join(f'<Override PartName="{p}" ContentType="{c}"/>' for p, c in overrides) + "</Types>")
    entries["_rels/.rels"] = _rels([("rId1", f"{_R}/officeDocument", "ppt/presentation.xml"),
                                    ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"),
                                    ("rId3", f"{_R}/extended-properties", "docProps/app.xml")])
    entries["docProps/core.xml"] = (f'{_XML}<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
                                    f'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{_x(title)}</dc:title></cp:coreProperties>')
    entries["docProps/app.xml"] = (f'{_XML}<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Daon2-User</Application><Slides>{count}</Slides></Properties>')
    sld_ids = "".join(f'<p:sldId id="{255 + n}" r:id="rId{3 + n}"/>' for n in range(1, count + 1))
    entries["ppt/presentation.xml"] = (f'{_XML}<p:presentation {_NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                                       f'<p:notesMasterIdLst><p:notesMasterId r:id="rId2"/></p:notesMasterIdLst><p:sldIdLst>{sld_ids}</p:sldIdLst>'
                                       f'<p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    entries["ppt/_rels/presentation.xml.rels"] = _rels([("rId1", f"{_R}/slideMaster", "slideMasters/slideMaster1.xml"),
                                                        ("rId2", f"{_R}/notesMaster", "notesMasters/notesMaster1.xml"),
                                                        ("rId3", f"{_R}/theme", "theme/theme1.xml"),
                                                        *[(f"rId{3 + n}", f"{_R}/slide", f"slides/slide{n}.xml") for n in range(1, count + 1)]])
    entries["ppt/slideMasters/slideMaster1.xml"] = (f'{_XML}<p:sldMaster {_NS}><p:cSld><p:spTree>{_GROUP}</p:spTree></p:cSld>{_CLRMAP}'
                                                    '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst></p:sldMaster>')
    entries["ppt/slideMasters/_rels/slideMaster1.xml.rels"] = _rels([("rId1", f"{_R}/slideLayout", "../slideLayouts/slideLayout1.xml"), ("rId2", f"{_R}/theme", "../theme/theme1.xml")])
    entries["ppt/slideLayouts/slideLayout1.xml"] = (f'{_XML}<p:sldLayout {_NS} type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>{_GROUP}</p:spTree></p:cSld>'
                                                    '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')
    entries["ppt/slideLayouts/_rels/slideLayout1.xml.rels"] = _rels([("rId1", f"{_R}/slideMaster", "../slideMasters/slideMaster1.xml")])
    entries["ppt/theme/theme1.xml"] = _THEME
    entries["ppt/theme/theme2.xml"] = _THEME
    entries["ppt/notesMasters/notesMaster1.xml"] = (f'{_XML}<p:notesMaster {_NS}><p:cSld><p:spTree>{_GROUP}</p:spTree></p:cSld>{_CLRMAP}</p:notesMaster>')
    entries["ppt/notesMasters/_rels/notesMaster1.xml.rels"] = _rels([("rId1", f"{_R}/theme", "../theme/theme2.xml")])
    for n, slide in enumerate(slides, 1):
        entries[f"ppt/slides/slide{n}.xml"] = _slide_xml(dict(slide))
        entries[f"ppt/slides/_rels/slide{n}.xml.rels"] = _rels([("rId1", f"{_R}/slideLayout", "../slideLayouts/slideLayout1.xml"),
                                                                 ("rId2", f"{_R}/notesSlide", f"../notesSlides/notesSlide{n}.xml")])
        note = str(slide.get("notes", ""))
        if n == count and closing_note:
            note = (note + "\n" if note else "") + closing_note
        entries[f"ppt/notesSlides/notesSlide{n}.xml"] = _notes_xml(note)
        entries[f"ppt/notesSlides/_rels/notesSlide{n}.xml.rels"] = _rels([("rId1", f"{_R}/notesMaster", "../notesMasters/notesMaster1.xml"),
                                                                           ("rId2", f"{_R}/slide", f"../slides/slide{n}.xml")])
    return _zip(entries)
