"""웹 페이지 만들기(WO-N8): 1단계 내용 JSON 검사.

1단계는 근거 라벨이 붙은 보고서형 내용 JSON을 만든다. 근거가 없거나 숫자·날짜·식별자가
인용 구간에 없는 블록은 지우지 않고 insufficient=True로 표시한다. 2단계(HTML)에는
verified_body()로 근거가 확인된 블록만 넘긴다.

아래쪽 "2단계 HTML 처리" 부분은 모델이 쓴 HTML을 정리하고(외부 주소·위험 요소 제거, CSP 삽입)
숫자·절 제목을 대조한 뒤 고정 연결 스크립트를 붙인다.
"""

from __future__ import annotations

import html as _html
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any, Mapping, Sequence

from .document_understanding_adapter import _evidence_anchors
from .studio_context_builder import ContextPack
from .studio_validation import Warnings, as_list, clean_refs, ensure_size, text_field
from .studio_workspace import StudioError

MAX_SECTIONS = 8
MAX_BLOCKS_PER_SECTION = 30
TITLE_LIMIT = 160
HEADING_LIMIT = 120
REQUEST_LIMIT = 2000
_KINDS = {"paragraph", "bullets", "table", "metric"}


def _block_text(block: Mapping[str, Any]) -> str:
    kind = block["type"]
    if kind == "bullets":
        return "\n".join(block["items"])
    if kind == "table":
        return "\n".join(" ".join(row) for row in block["rows"])
    if kind == "metric":
        return f"{block['label']} {block['value']}"
    return str(block["text"])


def _build_block(kind: str, raw: Mapping[str, object]) -> dict[str, Any] | None:
    """종류별 내용을 다듬는다. 비어 있으면 None."""
    if kind == "bullets":
        items = [text_field(i, 400) for i in as_list(raw.get("items"), 20) if isinstance(i, str) and i.strip()]
        return {"type": "bullets", "items": items} if items else None
    if kind == "table":
        rows = [[text_field(c, 200) for c in r] for r in as_list(raw.get("rows"), 30) if isinstance(r, list)]
        rows = [r for r in rows if any(r)]
        return {"type": "table", "rows": rows} if rows else None
    if kind == "metric":
        label, value = text_field(raw.get("label"), 120), text_field(raw.get("value"), 120)
        return {"type": "metric", "label": label, "value": value} if label and value else None
    text = text_field(raw.get("text"), 3000)
    return {"type": "paragraph", "text": text} if text else None


def validate_web_page(data: Mapping[str, object], pack: ContextPack, request: str) -> tuple[dict[str, object], list[dict[str, object]], list[str]]:
    w = Warnings()
    used: list[str] = []
    by_ref = pack.by_ref()
    pack_anchors: set = set()
    for passage in pack.passages:
        pack_anchors |= _evidence_anchors(passage.text)
    sections: list[dict[str, object]] = []
    verified_count = 0
    for si, section in enumerate(as_list(data.get("sections"), MAX_SECTIONS)):
        if not isinstance(section, Mapping):
            continue
        heading = text_field(section.get("heading"), HEADING_LIMIT)
        heading_ok = _evidence_anchors(heading).issubset(pack_anchors)
        if not heading_ok:
            w.add("ANCHOR_MISMATCH", f"sections[{si}].heading")
        blocks: list[dict[str, object]] = []
        sec_verified = 0
        sec_used: list[str] = []
        for bi, raw in enumerate(as_list(section.get("blocks"), MAX_BLOCKS_PER_SECTION)):
            if not isinstance(raw, Mapping):
                continue
            raw_kind = raw.get("type")
            kind = raw_kind if isinstance(raw_kind, str) and raw_kind in _KINDS else "paragraph"
            block = _build_block(kind, raw)
            if block is None:
                continue
            path = f"sections[{si}].blocks[{bi}]"
            refs = clean_refs(raw.get("refs"), pack, w, path)
            insufficient = not refs or not heading_ok
            if refs:
                source = "\n".join(by_ref[r].text for r in refs)
                if not _evidence_anchors(_block_text(block)).issubset(_evidence_anchors(source)):
                    w.add("ANCHOR_MISMATCH", path)
                    insufficient = True
            block["refs"] = refs
            block["insufficient"] = insufficient
            if not insufficient:
                sec_verified += 1
                sec_used += refs
            blocks.append(block)
        if heading and blocks:
            sections.append({"heading": heading, "blocks": blocks})
            verified_count += sec_verified
            used += sec_used
    if not sections or verified_count == 0:
        raise StudioError("STUDIO_VALIDATION_FAILED", 502)
    title = text_field(data.get("title"), TITLE_LIMIT)
    title_ok = _evidence_anchors(title).issubset(pack_anchors)
    if not title_ok:
        w.add("ANCHOR_MISMATCH", "title")
    body: dict[str, object] = {
        "title": title,
        "title_insufficient": not title_ok,
        "request": text_field(request, REQUEST_LIMIT),
        "sections": sections,
        "html": "",
    }
    ensure_size(body)
    return body, w.items, list(dict.fromkeys(used))


def verified_body(body: Mapping[str, Any]) -> dict[str, Any]:
    """근거 부족 블록을 뺀 사본. 블록이 다 빠진 절도 뺀다."""
    sections = []
    for section in body.get("sections", []):
        blocks = [dict(b) for b in section.get("blocks", []) if not b.get("insufficient")]
        if blocks:
            sections.append({"heading": section.get("heading", ""), "blocks": blocks})
    return {**body, "title": "" if body.get("title_insufficient") else body.get("title", ""), "sections": sections}


def verified_text(body: Mapping[str, Any]) -> str:
    """verified_body의 모든 글(제목·절 제목·블록 글)을 이어 붙인 것."""
    clean = verified_body(body)
    parts = [str(clean.get("title") or "")]
    for section in clean["sections"]:
        parts.append(str(section["heading"]))
        parts.extend(_block_text(b) for b in section["blocks"])
    return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# 2단계 HTML 처리: 추출·정리(sanitize)·CSP·숫자/절 제목 대조·연결 스크립트
#
# 정리기는 표준 HTMLParser 토큰을 다시 써서 출력한다(정규식으로 태그를 지우지 않는다).
# 속성 값과 일반 글은 모두 다시 escape하고, <script>/<style> 원문만 그대로(정리 후) 내보낸다.
# 1차 방어는 격리 iframe + CSP이고, 정리기는 내려받은 파일까지 포함한 2차 방어다.
# ---------------------------------------------------------------------------

MAX_HTML_BYTES = 400_000
CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'"
_CSP_META = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
_CHARSET_META = '<meta charset="utf-8">'

BRIDGE_SCRIPT = (
    "<script data-daon-bridge>"
    'document.addEventListener("click",function(e){'
    "var t=e.target;"
    'var el=t&&t.closest?t.closest("[data-ref]"):null;'
    "if(!el)return;"
    'var r=el.getAttribute("data-ref");'
    "if(/^S\\d+$/.test(r)){"
    "e.preventDefault();"
    'parent.postMessage({type:"daon-ref",ref:r},"*");'
    "}"
    "});"
    "</script>"
)


class WebPageCheckFailed(Exception):
    """2단계 HTML 검사 실패. reason: numbers | headings | size | empty.

    items: numbers면 허용 글에 없는 anchor 목록(정렬), headings면 빠진 절 제목 목록.
    재시도 안내문에 그대로 쓸 수 있다.
    """

    def __init__(self, reason: str, items: Sequence[str] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.items = list(items)


_TAG_START = re.compile(r"<(?:!doctype|[a-z])", re.I)
_FENCE_OPEN = re.compile(r"```[ \t]*[A-Za-z0-9_-]*[ \t]*\r?\n")
_DOC_START = re.compile(r"<!doctype|<html[\s>]", re.I)


def extract_html(raw: str) -> str:
    """코드 울타리(```html)와 앞뒤 설명글을 떼고 HTML만 돌려준다. HTML이 없으면 ""."""
    text = raw or ""
    first_tag = _TAG_START.search(text)
    fence = _FENCE_OPEN.search(text)
    fenced = bool(fence) and (first_tag is None or fence.start() < first_tag.start())
    if fenced:
        body = text[fence.end():]
        end = body.rfind("```")
        text = body[:end] if end >= 0 else body
    doc = _DOC_START.search(text)
    if doc:
        text = text[doc.start():]
        end = text.lower().rfind("</html>")
        if end >= 0:
            text = text[: end + len("</html>")]
    elif not fenced:
        start = _TAG_START.search(text)
        if start is None:
            return ""
        text = text[start.start(): text.rfind(">") + 1]
    text = text.strip()
    return text if _TAG_START.search(text) else ""


# --- 정리기 규칙 ---

_TAG_NAME = re.compile(r"[a-z][a-z0-9-]*")
_ATTR_NAME = re.compile(r"[a-z_:][a-z0-9_:.-]*")
# 요소와 안쪽 내용을 통째로 지운다.
_DROP_WITH_CONTENT = {"iframe", "object", "applet", "noembed", "noframes", "portal", "fencedframe"}
# 태그만 지운다(안쪽 내용은 남김). form은 내용을 살린다.
_DROP_TAG = {"link", "base", "embed", "frame", "frameset", "form", "param", "plaintext", "keygen"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_RAW_KEEP = {"script", "style"}
_RCDATA_LIKE = {"textarea", "title", "xmp"}
_ANIMATION = {"set", "animate", "animatemotion", "animatetransform", "animatecolor"}
# 값과 상관없이 늘 지우는 속성(주소를 담거나 요청을 일으킨다).
_ALWAYS_DROP_ATTRS = {
    "srcset", "imagesrcset", "ping", "action", "formaction", "manifest", "codebase", "archive",
    "classid", "longdesc", "profile", "lowsrc", "dynsrc", "srcdoc", "cite", "icon", "http-equiv",
    "data-daon-bridge",
}
_HREF_ATTRS = {"href", "xlink:href"}
_SRC_ATTRS = {"src", "poster", "background", "data"}
_CTRL_WS = re.compile(r"[\x00-\x20\x7f]+")
_CSS_COMMENT = re.compile(r"/\*.*?(?:\*/|\Z)", re.S)
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\r\n\f]?|(\r\n|[\n\r\f])|(.))", re.S)
_CSS_URL = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)\s\"']*))\s*\)", re.I)
_ATTR_URL = re.compile(r"url\(\s*['\"]?([^'\")\s]*)", re.I)


def _css_unescape(value: str) -> str:
    """CSS escape를 풀고, 풀린 결과에 역슬래시가 남지 않게 한다(다시 escape로 숨지 못하게)."""

    def rep(match: re.Match[str]) -> str:
        if match.group(1):
            code = int(match.group(1), 16)
            if code == 0 or code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                return "�"
            char = chr(code)
        elif match.group(2) is not None:
            return ""
        else:
            char = match.group(3)
        return "" if char == "\\" else char

    return _CSS_ESCAPE.sub(rep, value).replace("\\", "")


def _clean_css(css: str) -> tuple[str, bool]:
    """CSS에서 외부 참조를 지운다. (정리된 CSS, 외부 참조가 있었는지).

    주석 제거 → escape 풀기 → data: url만 보존 → 나머지 url()/@import/image-set/주소 제거 →
    '<'를 CSS escape로 바꿔 어떤 파싱 문맥에서도 태그가 되지 못하게 한다.
    """
    text = css.replace("\x00", "�")
    text = _CSS_COMMENT.sub(" ", text)
    text = _CSS_COMMENT.sub(" ", _css_unescape(text))
    saved: list[str] = []
    offending = False

    def url_rep(match: re.Match[str]) -> str:
        nonlocal offending
        target = next(g for g in match.groups() if g is not None)
        if target.strip().lower().startswith("data:"):
            saved.append(match.group(0).replace("<", "%3C").replace(">", "%3E"))
            return f"\x00{len(saved) - 1}\x00"
        offending = True
        return "none"

    text = _CSS_URL.sub(url_rep, text)
    for pattern, replacement in (
        (r"url\s*\(", "none("),
        (r"@import[^;{}]*;?", ""),
        (r"(?:-webkit-)?image-set\s*\(", "none("),
        (r"https?:", ""),
    ):
        text, count = re.subn(pattern, replacement, text, flags=re.I)
        offending = offending or count > 0
    text, count = re.subn(r"/{2,}", "/", text)
    offending = offending or count > 0
    text = text.replace("<", "\\3c ")
    text = re.sub(r"\x00(\d+)\x00", lambda m: saved[int(m.group(1))], text)
    return text, offending


def _has_address(probe: str) -> bool:
    return "http:" in probe or "https:" in probe or "//" in probe or "javascript:" in probe or "vbscript:" in probe


def _attr_value_ok(probe: str) -> bool:
    for candidate in (probe, _css_unescape(probe)):
        if _has_address(candidate):
            return False
        for target in _ATTR_URL.findall(candidate):
            if not (target.startswith("#") or target.startswith("data:")):
                return False
    return True


def _clean_attrs(tag: str, attrs: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    kept: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for name, value in attrs:
        if not _ATTR_NAME.fullmatch(name) or name in seen:
            continue
        seen.add(name)  # 브라우저는 같은 이름의 첫 속성만 쓴다.
        if name in _ALWAYS_DROP_ATTRS:
            continue
        if value is None:
            kept.append((name, None))
            continue
        probe = _CTRL_WS.sub("", value).lower()
        if name in _HREF_ATTRS:
            if probe.startswith("#") or (tag in ("image", "feimage") and probe.startswith("data:image/")):
                kept.append((name, value))
            continue
        if name in _SRC_ATTRS:
            if probe.startswith("data:image/"):
                kept.append((name, value))
            continue
        if name == "style":
            css, offending = _clean_css(value)
            if not offending:
                kept.append((name, css))
            continue
        if _attr_value_ok(probe):
            kept.append((name, value))
    return kept


def _render_attrs(attrs: list[tuple[str, str | None]]) -> str:
    return "".join(f" {n}" if v is None else f' {n}="{_html.escape(v, quote=True)}"' for n, v in attrs)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.doctype = False
        self.html_attrs: list[tuple[str, str | None]] | None = None
        self.charset = False
        self.skip: str | None = None
        self.skip_depth = 0
        self.raw: str | None = None
        self.foreign = 0
        self.dropped_animation = 0

    # 시작 태그(자기 닫힘 포함)
    def _open(self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool) -> None:
        if self.skip is not None:
            if tag == self.skip and not self_closing:
                self.skip_depth += 1
            return
        if not _TAG_NAME.fullmatch(tag):
            return
        if tag == "html":
            if self.html_attrs is None:
                self.html_attrs = _clean_attrs(tag, attrs)
            return
        if tag == "head" or tag in _DROP_TAG:
            return
        names = {n for n, _ in attrs}
        if tag in _DROP_WITH_CONTENT or (tag == "script" and names & {"src", "href", "xlink:href"}):
            if not self_closing:
                self.skip, self.skip_depth = tag, 1
            return
        if tag == "meta":
            if "http-equiv" in names:
                return
            if "charset" in names:
                self.charset = True
        if tag in _ANIMATION:
            target = next((str(v or "").strip().lower() for n, v in attrs if n == "attributename"), "")
            if target.endswith("href") or target in ("src", "action", "formaction"):
                if not self_closing:
                    self.dropped_animation += 1
                return
        rendered = f"<{tag}{_render_attrs(_clean_attrs(tag, attrs))}"
        if self_closing and (tag in _VOID or self.foreign or tag in ("svg", "math")):
            self.out.append(rendered + "/>")
            return
        self.out.append(rendered + ">")
        if self_closing and tag in _RAW_KEEP | _RCDATA_LIKE:
            self.out.append(f"</{tag}>")
            return
        if tag in ("svg", "math"):
            self.foreign += 1
        if tag in _RAW_KEEP | _RCDATA_LIKE and not self_closing:
            self.raw = tag

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs, False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open(tag, attrs, True)

    def handle_endtag(self, tag: str) -> None:
        if self.skip is not None:
            if tag == self.skip:
                self.skip_depth -= 1
                if self.skip_depth == 0:
                    self.skip = None
            return
        if not _TAG_NAME.fullmatch(tag) or tag in _DROP_TAG or tag in _DROP_WITH_CONTENT:
            return
        if tag in _ANIMATION and self.dropped_animation:
            self.dropped_animation -= 1
            return
        if tag == self.raw:
            self.raw = None
        if tag in ("svg", "math"):
            self.foreign = max(0, self.foreign - 1)
        self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self.skip is not None:
            return
        if self.raw == "script" and not self.foreign:
            # 원문 유지. 단 "</"와 "<!--"는 스크립트 끝/escape 상태를 만들지 못하게 바꾼다.
            self.out.append(data.replace("</", "<\\/").replace("<!--", "<\\!--"))
        elif self.raw == "style":
            css, _ = _clean_css(data)
            self.out.append(_html.escape(css, quote=False) if self.foreign else css)
        else:
            # 일반 글, RCDATA(textarea·title), xmp, 그리고 svg/math 안의 script(문자 데이터로 파싱됨)
            self.out.append(_html.escape(data, quote=False))

    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower().startswith("doctype"):
            self.doctype = True

    def handle_comment(self, data: str) -> None:  # 주석은 버린다.
        return

    def handle_pi(self, data: str) -> None:
        return

    def unknown_decl(self, data: str) -> None:
        return

    def result(self) -> str:
        if self.raw is not None:
            self.out.append(f"</{self.raw}>")
        head = _CSP_META + ("" if self.charset else _CHARSET_META)
        prefix = ("<!DOCTYPE html>" if self.doctype else "") + f"<html{_render_attrs(self.html_attrs or [])}><head>"
        return prefix + head + "".join(self.out)


def sanitize_html(html: str) -> str:
    """위험 요소·외부 주소를 지우고 <head> 첫 자식으로 우리 CSP 메타 하나를 넣는다.

    모델이 쓴 <html>/<head> 시작 태그는 우리가 앞에 새로 쓰므로(첫 <html> 속성만 옮김) 버리고,
    모델이 넣은 http-equiv 메타(CSP·refresh 포함)는 모두 지운다.
    """
    parser = _Sanitizer()
    parser.feed(html)
    parser.close()
    return parser.result()


# --- 글 수집·대조 ---

_INLINE = {
    "a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em", "font", "i", "kbd", "label",
    "mark", "q", "s", "samp", "small", "span", "strong", "sub", "sup", "time", "u", "var",
}
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_REF_PART = re.compile(r"s\d+")


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.visible: list[str] = []
        self.script: list[str] = []
        self.raw: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.raw = tag
        if tag not in _INLINE:
            self.visible.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _INLINE:
            self.visible.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == self.raw:
            self.raw = None
        if tag not in _INLINE:
            self.visible.append(" ")

    def handle_data(self, data: str) -> None:
        if self.raw == "style":
            return
        (self.script if self.raw == "script" else self.visible).append(data)


def _collect(html: str) -> tuple[str, str]:
    collector = _TextCollector()
    collector.feed(html)
    collector.close()
    return "".join(collector.visible), "\n".join(collector.script)


def _anchors(text: str) -> frozenset[str]:
    """_evidence_anchors 앞에 세 자리 쉼표만 양쪽 똑같이 지운다(1,000,000 = 1000000)."""
    return _evidence_anchors(_THOUSANDS.sub("", unicodedata.normalize("NFKC", text)))


def _excepted(anchor: str) -> bool:
    kind, _, value = anchor.partition(":")
    if kind == "number":
        return value.isdigit() and 1 <= int(value) <= 20
    if kind == "identifier":
        return all(_REF_PART.fullmatch(part) for part in re.split(r"[-_.:/]", value))
    return False


def stray_anchors(html: str, allowed_text: str, request: str) -> set[str]:
    """보이는 글과 <script> 글의 anchor 가운데 allowed_text·요청 글에 없는 것(예외 제외)."""
    visible, script = _collect(html)
    page = _anchors(visible) | _anchors(script)
    allowed = _anchors(allowed_text) | _anchors(request)
    return {a for a in page - allowed if not _excepted(a)}


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def missing_headings(html: str, headings: Sequence[str]) -> list[str]:
    """보이는 글에 없는 절 제목(공백을 모두 지우고 NFKC·대소문자 무시로 비교)."""
    visible = _squash(_collect(html)[0])
    return [h for h in headings if _squash(h) and _squash(h) not in visible]


def attach_bridge(html: str) -> str:
    end = html.lower().rfind("</body>")
    if end < 0:
        return html + BRIDGE_SCRIPT
    return html[:end] + BRIDGE_SCRIPT + html[end:]


def strip_bridge(html: str) -> str:
    return html.replace(BRIDGE_SCRIPT, "")


def finalize_html(raw: str, allowed_text: str, request: str, headings: Sequence[str]) -> str:
    """extract → sanitize → 크기 → 숫자 대조 → 절 제목 → 연결 스크립트. 실패 시 WebPageCheckFailed."""
    extracted = extract_html(raw)
    if not extracted:
        raise WebPageCheckFailed("empty")
    if len(extracted.encode("utf-8")) > 4 * MAX_HTML_BYTES:  # 지나치게 큰 입력은 파싱 전에 끊는다.
        raise WebPageCheckFailed("size")
    html = sanitize_html(extracted)
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise WebPageCheckFailed("size")
    if not _collect(html)[0].strip():
        raise WebPageCheckFailed("empty")
    stray = stray_anchors(html, allowed_text, request)
    if stray:
        raise WebPageCheckFailed("numbers", sorted(stray))
    missing = missing_headings(html, headings)
    if missing:
        raise WebPageCheckFailed("headings", missing)
    return attach_bridge(html)
