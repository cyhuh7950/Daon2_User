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
# 대화로 고치기(WO-K5 연결): 고친 본문 정리와 바뀐 블록 다시 판정
# ---------------------------------------------------------------------------


def clean_edited_body(body: Mapping[str, Any], known_refs: set[str]) -> dict[str, Any]:
    """대화로 고친 본문을 정리한다. 근거 라벨은 known_refs에 있는 것만 남기고 insufficient·title_insufficient·
    request·html 같은 다른 칸은 그대로 둔다. 판정은 mark_edited_blocks가 따로 한다. 규칙 위반은 STUDIO_INPUT_INVALID."""
    sections: list[dict[str, Any]] = []
    for section in as_list(body.get("sections"), MAX_SECTIONS):
        if not isinstance(section, Mapping):
            continue
        blocks: list[dict[str, Any]] = []
        for raw in as_list(section.get("blocks"), MAX_BLOCKS_PER_SECTION):
            if not isinstance(raw, Mapping):
                continue
            kind = raw.get("type")
            if not isinstance(kind, str) or kind not in _KINDS:
                raise StudioError("STUDIO_INPUT_INVALID", 400)
            block = _build_block(kind, raw)
            if block is None:
                continue
            refs = raw.get("refs") if isinstance(raw.get("refs"), list) else []
            block["refs"] = [r for r in dict.fromkeys(refs) if isinstance(r, str) and r in known_refs]
            block["insufficient"] = raw.get("insufficient") is True
            blocks.append(block)
        heading = text_field(section.get("heading"), HEADING_LIMIT)
        if heading and blocks:
            sections.append({"heading": heading, "blocks": blocks})
    if not sections:
        raise StudioError("STUDIO_INPUT_INVALID", 400)
    cleaned = {**body, "title": text_field(body.get("title"), TITLE_LIMIT), "sections": sections}
    ensure_size(cleaned)
    return cleaned


def _block_key(block: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(sorted((k, repr(v)) for k, v in block.items() if k != "insufficient"))


def _ref_scoped_allowed(refs: Sequence[str], old_body: Mapping[str, Any], plain_by_ref: Mapping[str, str]) -> frozenset[str]:
    """바뀐 블록 하나의 허용 anchor: 그 블록 refs에 해당하는 새 자료 본문 + 이전 본문에서 같은 ref를 가진 근거 확인 블록 글."""
    wanted = set(refs)
    parts = [str(plain_by_ref[r]) for r in refs if r in plain_by_ref]
    for section in verified_body(old_body)["sections"]:
        parts.extend(_block_text(b) for b in section["blocks"] if wanted & set(b.get("refs") or []))
    return _evidence_anchors("\n".join(parts))


def mark_edited_blocks(new_body: Mapping[str, Any], old_body: Mapping[str, Any], plain_by_ref: Mapping[str, str]) -> dict[str, Any]:
    """대화로 고친 본문의 바뀐 블록을 1단계와 같은 규칙으로 다시 판정한 사본을 돌려준다.

    plain_by_ref: 이번에 새로 찾은 자료의 근거 번호 → 본문 글(태그·파일 이름·위치 글 제외).
    - 같은 자리의 이전 블록과 내용이 같으면 원래 판정을 그대로 둔다.
    - 바뀌었거나 새 블록이면 유효 refs가 없거나, 숫자·날짜·식별자가 그 블록 refs의 근거 글(새 자료 중 같은 ref 본문 +
      이전 본문에서 같은 ref를 가진 근거 확인 블록 글)에 없을 때 insufficient=True. 다른 ref 블록의 숫자는 근거가 아니다.
    - 자리가 밀린 블록이라도 이전에 근거 부족이던 블록과 내용이 같으면 근거 부족으로 둔다(승격하지 않는다).
    - 절 제목·제목은 이전 본문의 근거 확인 글(verified_text) + 새 자료 본문 전체로 본다. 절 제목의 anchor가 없으면
      그 절의 블록을 모두 근거 부족으로 둔다(1단계 규칙과 같다). 제목이 바뀌었으면 title_insufficient도 다시 정한다.
    """
    plain_by_ref = {str(k): str(v) for k, v in (plain_by_ref or {}).items()}
    allowed = _evidence_anchors(verified_text(old_body) + "\n" + "\n".join(plain_by_ref.values()))
    old_sections = list(old_body.get("sections") or [])
    weak = {_block_key(b) for s in old_sections for b in s.get("blocks", []) if b.get("insufficient")}
    sections: list[dict[str, Any]] = []
    for si, section in enumerate(new_body.get("sections") or []):
        old_section = old_sections[si] if si < len(old_sections) else {}
        old_blocks = list(old_section.get("blocks") or [])
        heading = str(section.get("heading", ""))
        # 바뀌지 않은 절 제목도 같이 본다: 근거 확인 블록이 있던 절의 제목은 verified_text에 들어 있어 통과하고,
        # 1단계에서 제목 근거가 없어 블록이 모두 근거 부족이던 절은 고친 블록도 근거 부족으로 남는다.
        heading_ok = _evidence_anchors(heading).issubset(allowed)
        blocks = []
        for bi, block in enumerate(section.get("blocks") or []):
            item = dict(block)
            old_block = old_blocks[bi] if bi < len(old_blocks) else None
            if old_block is not None and _block_key(old_block) == _block_key(item):
                item["insufficient"] = bool(old_block.get("insufficient"))
            else:
                refs = [str(r) for r in (item.get("refs") or [])]
                item["insufficient"] = (not refs or _block_key(item) in weak
                                        or not _evidence_anchors(_block_text(item)).issubset(_ref_scoped_allowed(refs, old_body, plain_by_ref)))
            if not heading_ok:
                item["insufficient"] = True
            blocks.append(item)
        sections.append({**section, "blocks": blocks})
    result = {**new_body, "sections": sections}
    title = str(new_body.get("title") or "")
    if title != str(old_body.get("title") or ""):
        result["title_insufficient"] = not _evidence_anchors(title).issubset(allowed)
    else:
        result["title_insufficient"] = bool(old_body.get("title_insufficient"))
    return result


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
# <head> 첫머리: charset(첫 1024바이트 안) → CSP. 고정 스크립트는 이 바로 뒤에 넣어 CSP 적용을 받고 본문보다 먼저 온다.
_HEAD_METAS = _CHARSET_META + _CSP_META
_LANG = re.compile(r"[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8}){0,4}")
_DIRS = {"ltr", "rtl", "auto"}


def _html_lang_dir(attrs: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    """모델 <html> 속성 가운데 형식에 맞는 lang·dir만 남긴다."""
    kept: list[tuple[str, str | None]] = []
    for name, value in attrs:
        text = (value or "").strip()
        if name == "lang" and _LANG.fullmatch(text):
            kept.append((name, text))
        elif name == "dir" and text.lower() in _DIRS:
            kept.append((name, text.lower()))
    return kept

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


# 표시 동작(탭·접기·표 정렬)용 고정 스크립트. 모델 스크립트는 모두 지우고 이것만 붙인다.
# 네트워크·이동 API를 쓰지 않고, 0/1 밖의 숫자 상수를 쓰지 않는다.
BEHAVIOR_SCRIPT = (
    "<script data-daon-behavior>"
    "(function(){"
    "function all(root,q){return Array.prototype.slice.call(root.querySelectorAll(q));}"
    'function own(box,el){return el.closest("[data-tabs]")===box;}'
    # 모델 CSS가 hidden 대신 aria-hidden·display·.active로 보이고 숨길 수 있어 모두 함께 맞춘다(ysna 1차 확인).
    'function hide(el,off){if(off){el.setAttribute("hidden","");el.setAttribute("aria-hidden","true");el.style.display="none";}'
    'else{el.removeAttribute("hidden");el.setAttribute("aria-hidden","false");el.style.display="";'
    'if(getComputedStyle(el).display==="none"){el.style.display="block";}}'
    'el.classList.toggle("active",!off);}'
    # 영역이 [data-tabs] 밖(같은 부모의 형제)에 있으면 그 부모 안에서 어느 탭 묶음에도 속하지 않은 영역을 쓴다.
    'function panels(box){var mine=all(box,"[data-panel]").filter(function(p){return own(box,p);});'
    'if(mine.length||!box.parentElement){return mine;}'
    'return all(box.parentElement,"[data-panel]").filter(function(p){return !p.closest("[data-tabs]");});}'
    "function show(box,name){"
    'all(box,"[data-tab]").forEach(function(b){if(own(box,b)){var on=b.getAttribute("data-tab")===name;'
    'b.setAttribute("aria-selected",on?"true":"false");b.classList.toggle("active",on);}});'
    'panels(box).forEach(function(p){hide(p,p.getAttribute("data-panel")!==name);});}'
    "function init(){"
    'all(document,"[data-tabs]").forEach(function(box){'
    'var first=all(box,"[data-tab]").filter(function(b){return own(box,b);})[0];'
    'if(first){show(box,first.getAttribute("data-tab"));}});}'
    'if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",init);}else{init();}'
    "function sortBy(th){"
    'var table=th.closest("table[data-sortable]");if(!table){return;}'
    "var row=th.parentNode;var idx=Array.prototype.indexOf.call(row.children,th);"
    "var body=table.tBodies[0];if(!body){return;}"
    'var dir=th.getAttribute("data-sort-dir")==="asc"?"desc":"asc";'
    'all(row,"th").forEach(function(h){h.removeAttribute("data-sort-dir");h.removeAttribute("aria-sort");});'
    'th.setAttribute("data-sort-dir",dir);'
    'th.setAttribute("aria-sort",dir==="asc"?"ascending":"descending");'
    "var rows=Array.prototype.slice.call(body.rows);"
    "rows.sort(function(a,b){"
    'var x=a.cells[idx]?a.cells[idx].textContent.trim():"";'
    'var y=b.cells[idx]?b.cells[idx].textContent.trim():"";'
    'var r=x.localeCompare(y,undefined,{numeric:true,sensitivity:"base"});'
    'return dir==="asc"?r:-r;});'
    "rows.forEach(function(r){body.appendChild(r);});}"
    'document.addEventListener("click",function(e){'
    "var t=e.target;if(!t||!t.closest){return;}"
    'var tab=t.closest("[data-tab]");'
    'if(tab){var box=tab.closest("[data-tabs]");if(box){show(box,tab.getAttribute("data-tab"));return;}}'
    'var tg=t.closest("[data-toggle]");'
    'if(tg){var name=tg.getAttribute("data-toggle");'
    'all(document,"[data-toggle-target]").forEach(function(el){'
    'if(el.getAttribute("data-toggle-target")===name){'
    'var open=el.hasAttribute("hidden");hide(el,!open);'
    'tg.setAttribute("aria-expanded",open?"true":"false");}});return;}'
    'var th=t.closest("th");if(th){sortBy(th);}'
    "});"
    "})();"
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
# 요소와 안쪽 내용을 통째로 지운다. 모델 script는 어디에 있든(svg/math 안 포함) 모두 지운다.
_DROP_WITH_CONTENT = {
    "script", "iframe", "object", "applet", "noembed", "noframes", "portal", "fencedframe",
    "template", "noscript",
}
# 태그만 지운다(안쪽 내용은 남김). form은 내용을 살린다.
_DROP_TAG = {"link", "base", "embed", "frame", "frameset", "form", "param", "plaintext", "keygen"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_RAW_KEEP = {"style"}
_RCDATA_LIKE = {"textarea", "title", "xmp"}
_ANIMATION = {"set", "animate", "animatemotion", "animatetransform", "animatecolor"}
# 값과 상관없이 늘 지우는 속성(주소를 담거나 요청을 일으킨다).
_ALWAYS_DROP_ATTRS = {
    "srcset", "imagesrcset", "ping", "action", "formaction", "manifest", "codebase", "archive",
    "classid", "longdesc", "profile", "lowsrc", "dynsrc", "srcdoc", "cite", "icon", "http-equiv",
    "data-daon-bridge", "data-daon-behavior",
}
# 글자 데이터·속성 값에서 지우는 C0 제어문자(\t \n \r 제외).
_C0 = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
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
        if name.startswith("on"):  # 모델 처리기는 모두 지운다(판정 A).
            continue
        if value is None:
            kept.append((name, None))
            continue
        value = _C0.sub("", value)
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
        self.html_attrs: list[tuple[str, str | None]] | None = None
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
        if tag in _DROP_WITH_CONTENT:
            if not self_closing:
                self.skip, self.skip_depth = tag, 1
            return
        if tag == "meta" and {n for n, _ in attrs} & {"http-equiv", "charset"}:
            return  # CSP·refresh·content-type·charset는 우리 것만 쓴다.
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
        data = _C0.sub("", data)
        if self.raw == "style":
            # _clean_css가 '<'를 CSS escape로 바꾸므로 어떤 파싱 문맥에서도 태그가 생기지 않는다.
            css, _ = _clean_css(data)
            self.out.append(_html.escape(css, quote=False) if self.foreign else css)
        else:
            # 일반 글, RCDATA(textarea·title), xmp
            self.out.append(_html.escape(data, quote=False))

    def handle_decl(self, decl: str) -> None:  # doctype은 늘 우리 것(<!DOCTYPE html>)을 쓴다.
        return

    def handle_comment(self, data: str) -> None:  # 주석은 버린다.
        return

    def handle_pi(self, data: str) -> None:
        return

    def unknown_decl(self, data: str) -> None:
        return

    def result(self) -> str:
        if self.raw is not None:
            self.out.append(f"</{self.raw}>")
        # charset을 맨 앞(첫 1024바이트 안)에 두려고 <html>에는 짧은 lang·dir만 옮긴다.
        prefix = f"<!DOCTYPE html><html{_render_attrs(_html_lang_dir(self.html_attrs or []))}><head>"
        return prefix + _HEAD_METAS + "".join(self.out)


def sanitize_html(html: str) -> str:
    """위험 요소·외부 주소를 지우고 <head> 첫머리에 우리 charset 메타와 CSP 메타를 이 순서로 넣는다.

    모델이 쓴 <html>/<head> 시작 태그는 우리가 앞에 새로 쓰므로(첫 <html>의 lang·dir만 옮김) 버리고,
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


# 숫자 대조에 넣는 속성 글. 구조용 data-*는 뺀다.
_CHECKED_ATTRS = {"alt", "title", "placeholder", "value", "label"}
_STRUCTURAL_DATA = {
    "data-ref", "data-tab", "data-panel", "data-toggle", "data-toggle-target", "data-tabs", "data-sortable",
}
_CSS_CONTENT = re.compile(r"content\s*:\s*((?:\"[^\"]*\"|'[^']*'|[^;}\"'])*)", re.I)
_CSS_STRING = re.compile(r"\"([^\"]*)\"|'([^']*)'")


def _css_content_strings(css: str) -> list[str]:
    found: list[str] = []
    for value in _CSS_CONTENT.findall(css):
        for double, single in _CSS_STRING.findall(value):
            found.append(_css_unescape(double or single))
    return found


def _attr_checked(tag: str, name: str) -> bool:
    if name in _CHECKED_ATTRS or name.startswith("aria-"):
        return True
    if name.startswith("data-"):
        return name not in _STRUCTURAL_DATA
    return tag == "ol" and name == "start"


class _TextCollector(HTMLParser):
    """보이는 글(절 제목·숫자)과 숫자 대조용 속성·CSS content 글을 모은다. script 글은 보지 않는다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.visible: list[str] = []
        self.extra: list[str] = []
        self.raw: str | None = None

    def _attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if not value:
                continue
            if name == "style":
                self.extra.extend(_css_content_strings(value))
            elif _attr_checked(tag, name):
                self.extra.append(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.raw = tag
        self._attrs(tag, attrs)
        if tag not in _INLINE:
            self.visible.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._attrs(tag, attrs)
        if tag not in _INLINE:
            self.visible.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == self.raw:
            self.raw = None
        if tag not in _INLINE:
            self.visible.append(" ")

    def handle_data(self, data: str) -> None:
        if self.raw == "style":
            self.extra.extend(_css_content_strings(data))
        elif self.raw is None:
            self.visible.append(data)


def _collect(html: str) -> tuple[str, str]:
    """(보이는 글, 속성·CSS content 글)."""
    collector = _TextCollector()
    collector.feed(html)
    collector.close()
    return "".join(collector.visible), "\n".join(collector.extra)


def _drop_format(text: str) -> str:
    """보이지 않는 서식 문자(Cf: U+200B·U+00AD·U+2060·U+FEFF 등)를 지운다. 5​만 원이 순번처럼 보이지 않게 한다."""
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _anchors(text: str) -> frozenset[str]:
    """서식 문자를 지우고, _evidence_anchors 앞에 세 자리 쉼표만 양쪽 똑같이 지운다(1,000,000 = 1000000)."""
    return _evidence_anchors(_THOUSANDS.sub("", _drop_format(unicodedata.normalize("NFKC", text))))


_DIGITS = re.compile(r"\d+")
# 단독 순번 뒤에 붙어도 되는 말(단계·번째·번). 그 밖의 한글이 바로 붙으면 단위·셈말로 본다.
_ORDINAL_SUFFIX = re.compile(r"(?:단계|번째|번)(?![가-힣])")
# 띄어 쓴 뒤 오는 단위·셈말(5 명, 3 kg, 20 %): 이것들이 오면 순번이 아니다.
_SPACED_UNIT = re.compile(
    r"\s+(?:%|[만억천백조원세배회명개년월일시분초항호차건쪽장권점층평]"
    r"|(?:kg|g|mg|km|m|cm|mm|l|ml|day|days|month|months|year|years|hour|hours|minute|minutes"
    r"|second|seconds|item|items|percent|won|krw|usd)(?![a-z]))",
    re.I,
)
_BEFORE_BLOCK = set(".,:/-+$₩€¥£")


def _strip_ordinals(text: str) -> str:
    """보이는 글에서 1~20의 단독 순번(목록 번호 1. (2) 2), 탭 3, 3단계, 3번째 등)만 지운다.

    앞에 '제'·글자·숫자·. , : / - + 통화 기호가 붙었거나, 뒤에 숫자(소수점·시각 포함)·%·글자·한글 단위/셈말이
    붙으면 단독이 아니다(5만 원, 제3조, 10세, 2배, 3회, 5명은 남아서 대조된다)."""
    text = _drop_format(unicodedata.normalize("NFKC", text))

    def rep(match: re.Match[str]) -> str:
        digits = match.group(0)
        start, end = match.span()
        if digits.startswith("0") or not 1 <= int(digits) <= 20:
            return digits
        before = text[start - 1] if start else ""
        if before and (before.isalnum() or before in _BEFORE_BLOCK):
            return digits
        after = text[end:]
        if re.match(r"[.,:/]\d", after):
            return digits
        if _ORDINAL_SUFFIX.match(after):
            return " " * len(digits)
        if after and (after[0].isalnum() or after[0] == "%"):
            return digits
        if _SPACED_UNIT.match(after):
            return digits
        return " " * len(digits)

    return _DIGITS.sub(rep, text)


def _excepted(anchor: str) -> bool:
    kind, _, value = anchor.partition(":")
    if kind == "identifier":
        return all(_REF_PART.fullmatch(part) for part in re.split(r"[-_.:/]", value))
    return False


def stray_anchors(html: str, allowed_text: str, request: str) -> set[str]:
    """보이는 글·속성 글(alt·title·aria-*·placeholder·value·label·비구조 data-*·ol[start])·
    CSS content 글의 anchor 가운데 allowed_text·요청 글에 없는 것(예외 제외).
    속성 글은 따로 뽑아 보이는 글과 붙지 않게 한다. 보이는 글·속성 글의 1~20 단독 순번만 대조 전에 지운다
    (ol start="3", aria-level="2", aria-label="탭 2"는 통과, title="5만 원"·aria-label="제3조"는 대조)."""
    visible, extra = _collect(html)
    page = _anchors(_strip_ordinals(visible)) | _anchors(_strip_ordinals(extra))
    allowed = _anchors(allowed_text) | _anchors(request)
    return {a for a in page - allowed if not _excepted(a)}


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def missing_headings(html: str, headings: Sequence[str]) -> list[str]:
    """보이는 글에 없는 절 제목(공백을 모두 지우고 NFKC·대소문자 무시로 비교)."""
    visible = _squash(_collect(html)[0])
    return [h for h in headings if _squash(h) and _squash(h) not in visible]


_BODY_END = re.compile(r"</body\s*>", re.I)


def _insert_before_body_end(html: str, script: str) -> str:
    """원래 문자열에서 대소문자 무시로 찾은 마지막 </body> 앞에 넣는다(없으면 끝에)."""
    last = None
    for last in _BODY_END.finditer(html):
        pass
    if last is None:
        return html + script
    return html[: last.start()] + script + html[last.start():]


def _insert_in_head(html: str, script: str) -> str:
    """<head>의 charset·CSP 메타(정리기가 넣은 것) 바로 뒤, 이미 붙은 고정 스크립트들 뒤에 넣는다.

    본문 앞에 두므로 닫히지 않은 <math>·<svg> 같은 모델 요소가 스크립트를 삼키지 못한다.
    정리기는 모델의 http-equiv 메타를 모두 지우므로 첫 메타 묶음은 늘 우리 것이다. 없으면 예전처럼 </body> 앞(없으면 끝)."""
    at = html.find(_HEAD_METAS)
    if at < 0:
        return _insert_before_body_end(html, script)
    at += len(_HEAD_METAS)
    moved = True
    while moved:
        moved = False
        for fixed in (BEHAVIOR_SCRIPT, BRIDGE_SCRIPT):
            if html.startswith(fixed, at):
                at += len(fixed)
                moved = True
    return html[:at] + script + html[at:]


def attach_bridge(html: str) -> str:
    return _insert_in_head(html, BRIDGE_SCRIPT)


def attach_behavior(html: str) -> str:
    return _insert_in_head(html, BEHAVIOR_SCRIPT)


def strip_bridge(html: str) -> str:
    return html.replace(BRIDGE_SCRIPT, "")


def finalize_html(raw: str, allowed_text: str, request: str, headings: Sequence[str]) -> str:
    """extract → sanitize → 크기 → 숫자 대조 → 절 제목 → 동작 스크립트·연결 스크립트(<head> 메타 뒤, 이 순서).
    실패 시 WebPageCheckFailed."""
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
    return attach_bridge(attach_behavior(html))
