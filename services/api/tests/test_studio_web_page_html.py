"""WO-N8 웹 페이지 2단계 HTML 처리(정리·CSP·대조·연결 스크립트)."""

from __future__ import annotations

import re

import pytest

from daon2_user_api.studio_web_page import (
    BRIDGE_SCRIPT,
    CSP,
    MAX_HTML_BYTES,
    WebPageCheckFailed,
    attach_bridge,
    extract_html,
    finalize_html,
    missing_headings,
    sanitize_html,
    stray_anchors,
    strip_bridge,
)


def _page(body: str, head: str = "") -> str:
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>"


def _has_external(html: str) -> bool:
    lowered = html.lower()
    # 우리 CSP 메타 값은 주소가 아니므로 빼고 본다.
    lowered = lowered.replace(CSP.lower(), "")
    return any(token in lowered for token in ("http:", "https:", "//", "javascript:"))


# --- 브리프 시험 11개 ---


def test_extract_html_strips_fence_and_chatter() -> None:
    raw = "다음은 페이지입니다\n```html\n<!doctype html><html><body><p>안</p></body></html>\n```\n마칩니다."
    out = extract_html(raw)
    assert out.startswith("<!doctype")
    assert out.endswith("</html>")
    assert "다음은" not in out and "마칩니다" not in out


def test_sanitize_removes_dangerous_elements() -> None:
    raw = _page(
        '<script src="x.js"></script>'
        "<iframe src=\"a.html\"><p>속</p></iframe>"
        '<object data="o.swf"><p>대체</p></object>'
        '<embed src="e.swf">'
        '<form action="/send"><input name="q"><p>양식 안 글</p></form>',
        head='<base href="https://x/"><link rel="stylesheet" href="s.css">'
        '<meta http-equiv="refresh" content="0;url=/x">',
    )
    out = sanitize_html(raw).lower()
    for token in ("<script src", "src=\"x.js", "<iframe", "<object", "<embed", "<base", "<form", "action=", "<link", "refresh"):
        assert token not in out, token
    # form 태그만 지우고 안의 내용은 남긴다.
    assert "양식 안 글" in out and "<input" in out
    # 통째로 지운 요소의 안쪽 내용은 남지 않는다.
    assert "대체" not in out and "속" not in out


def test_sanitize_removes_external_urls() -> None:
    data_url = "data:image/png;base64,AAAA"
    raw = _page(
        '<img src="https://a/b.png" alt="그림">'
        '<div style="background:url(//x)">배경</div>'
        '<a href="http://x">밖</a>'
        f'<div style="background:url({data_url})">데이터</div>'
    )
    out = sanitize_html(raw)
    assert "https://a/b.png" not in out
    assert "url(//x)" not in out
    assert 'href="http://x"' not in out
    assert f"url({data_url})" in out
    assert '<img alt="그림">' in out
    assert not _has_external(out)


def test_csp_meta_inserted_once() -> None:
    raw = _page(
        "<p>본문</p>",
        head="<meta charset=\"utf-8\"><meta http-equiv=\"Content-Security-Policy\" content=\"default-src *\">",
    )
    out = sanitize_html(raw)
    assert out.lower().count("content-security-policy") == 1
    assert "default-src *" not in out
    meta = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
    assert re.search(r"<head>" + re.escape(meta), out)


def test_numbers_outside_verified_text_are_stray() -> None:
    html = sanitize_html(_page("<p>보상 한도는 500만 원입니다.</p>"))
    assert stray_anchors(html, "보상 한도는 100만 원이다.", "요청") != set()


def test_script_constant_is_checked() -> None:
    html = sanitize_html(_page("<p>안내</p><script>const rate=0.37</script>"))
    assert "number:0.37" in stray_anchors(html, "안내", "요청")


def test_numbers_match_with_commas_and_units() -> None:
    # 세 자리 쉼표는 양쪽 모두 지운 뒤 _evidence_anchors로 비교한다. "원"은 단위로 묶이지 않는다.
    html = sanitize_html(_page("<p>지원금 1000000원</p>"))
    assert stray_anchors(html, "지원금은 1,000,000원이다.", "요청") == set()
    # 반대 방향(허용 글에 쉼표 없음, HTML에 쉼표)도 같다.
    html2 = sanitize_html(_page("<p>지원금 1,000,000 원, 기간 12개월</p>"))
    assert stray_anchors(html2, "지원금 1000000원, 기간 12 개월", "요청") == set()


def test_exceptions_request_ordinals_refs() -> None:
    html = sanitize_html(_page(
        '<h2>2026년 계획</h2><ol><li>단계 3</li></ol><p data-ref="S12">근거 S12, S1-S3</p><p>21개 항목</p>'
    ))
    stray = stray_anchors(html, "계획", "2026년 계획을 정리해 줘")
    assert "number:21" in stray or any(a.startswith("quantity:21") for a in stray)
    assert stray == {a for a in stray if "21" in a}
    assert not any("12" in a for a in stray)


def test_missing_headings_detected() -> None:
    html = sanitize_html(_page("<h2>사업  개요</h2><p>글</p><h2>신청<br>방법</h2>"))
    assert missing_headings(html, ["사업 개요", "신청 방법", "문의처"]) == ["문의처"]


def test_bridge_attached_and_stripped() -> None:
    html = sanitize_html(_page('<p data-ref="S1">글</p>'))
    attached = attach_bridge(html)
    assert attached.count("data-daon-bridge") == 1
    assert attached.index("data-daon-bridge") < attached.lower().rindex("</body>")
    stripped = strip_bridge(attached)
    assert stripped.count("data-daon-bridge") == 0
    assert stripped == html


def test_oversize_fails() -> None:
    prefix, suffix = "<!doctype html><html><body><p>", "</p></body></html>"
    filler = "a" * (MAX_HTML_BYTES + 1 - len(prefix) - len(suffix))
    raw = prefix + filler + suffix
    assert len(raw.encode("utf-8")) == MAX_HTML_BYTES + 1
    with pytest.raises(WebPageCheckFailed) as info:
        finalize_html(raw, "a", "요청", [])
    assert info.value.reason == "size"


# --- 추가 시험(우회·경계) ---


def test_extract_html_without_fence_and_json_string() -> None:
    assert extract_html("설명\n<html><body>x</body></html>\n끝").startswith("<html>")
    assert extract_html("```\n<p>x</p>\n```") == "<p>x</p>"
    assert extract_html("   ") == ""


def test_uppercase_tags_and_attrs_are_handled() -> None:
    raw = _page(
        '<SCRIPT SRC="x.js"></SCRIPT><IFRAME SRC=a></IFRAME><IMG SRC="HTTPS://A/B.PNG" ALT=x>'
        '<A HREF="JavaScript:alert(1)">링크</A><A HREF=" &#106;avascript:alert(1)">링크2</A>'
    )
    out = sanitize_html(raw)
    assert "<script" not in out.lower() and "<iframe" not in out.lower()
    assert not _has_external(out)
    assert "href" not in out.lower()
    assert "링크" in out and "링크2" in out


def test_inline_handlers_and_inline_script_are_kept() -> None:
    raw = _page('<button onclick="toggle()">열기</button><script>function toggle(){return 1<2}</script>')
    out = sanitize_html(raw)
    assert 'onclick="toggle()"' in out
    assert "<script>function toggle(){return 1<2}</script>" in out


def test_url_attributes_allow_only_fragments_and_data_images() -> None:
    raw = _page(
        '<a href="#s1">안</a><a href="page.html">상대</a><a href="mailto:a@b">메일</a>'
        '<img src="data:image/png;base64,AAAA"><img src="x.png">'
        '<img srcset="a.png 1x"><a ping="/p" href="#a">핑</a>'
        '<video poster="p.png"></video><button formaction="/x">b</button>'
    )
    out = sanitize_html(raw)
    assert 'href="#s1"' in out and 'href="#a"' in out
    assert "page.html" not in out and "mailto" not in out
    assert 'src="data:image/png;base64,AAAA"' in out
    assert "x.png" not in out and "srcset" not in out and "ping" not in out
    assert "poster" not in out and "formaction" not in out


def test_style_block_external_references_removed() -> None:
    raw = _page(
        "<p>본문</p>",
        head="<style>@import 'https://x/a.css';"
        "body{background:url(https://x/b.png)}"
        "h1{background:url( 'img.png' )}"
        ".a{background:\\75rl(\\2f\\2f x/c.png)}"
        ".b{background-image:image-set('d.png' 1x)}"
        ".ok{background:url(\"data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg'></svg>\")}"
        "/* http://comment */</style>",
    )
    out = sanitize_html(raw)
    style = out[out.index("<style>"):out.index("</style>")]
    assert "@import" not in style
    assert "url(https" not in style and "img.png" not in style and "c.png" not in style
    assert "image-set" not in style
    assert "data:image/svg+xml" in style
    assert "\\75" not in style
    outside_data = re.sub(r"url\(\"data:[^\"]*\"\)", "", style)
    assert "http" not in outside_data and "//" not in outside_data
    assert "<" not in style[len("<style>"):]


def test_style_attribute_with_escape_is_dropped() -> None:
    raw = _page('<div style="background:\\75rl(\\2f\\2fx.y/z)">a</div><div style="color:red">b</div>')
    out = sanitize_html(raw)
    assert "x.y" not in out
    assert 'style="color:red"' in out


def test_svg_href_and_animation_are_neutralized() -> None:
    raw = _page(
        '<svg xmlns="http://www.w3.org/2000/svg"><a xlink:href="https://x"><text>t</text></a>'
        '<use href="#icon"/><image href="https://x/i.png"/>'
        '<a href="#"><set attributeName="href" to="data:text/html,x"/></a>'
        '<style><![CDATA[ x ]]><img src=x></style></svg>'
    )
    out = sanitize_html(raw)
    assert not _has_external(out)
    assert 'href="#icon"' in out
    assert "<set" not in out.lower()
    assert "<img" not in out.lower()


def test_css_escaped_presentation_attribute_is_dropped() -> None:
    raw = _page('<svg><rect fill="\\75rl(x.svg#a)" stroke="url(#g)"/></svg>')
    out = sanitize_html(raw)
    assert "x.svg" not in out
    assert 'stroke="url(#g)"' in out


def test_style_content_cannot_open_tags_in_any_context() -> None:
    # 브라우저가 svg/math 문맥으로 보든 HTML 문맥으로 보든 <style> 안에서 태그가 생기지 않아야 한다.
    raw = (
        "<svg><foreignObject><div></svg></div></foreignObject>"
        "<style><a href=data:text/html;base64,AAA>x</a></style>"
        "<math><mtext><table><mglyph><style><img src=x onerror=alert(1)></style>"
    )
    out = sanitize_html(raw)
    for chunk in re.findall(r"<style>(.*?)</style>", out, re.S):
        assert "<" not in chunk


def test_sanitize_is_idempotent() -> None:
    once = sanitize_html('<html lang="ko"><head><meta charset="utf-8"><title>t</title></head><body><p>a</p></body></html>')
    assert sanitize_html(once) == once


def test_script_end_tag_variants_cannot_escape() -> None:
    raw = _page('<script>var a="</scr"+"ipt>";</script><p>x</p>')
    out = sanitize_html(raw)
    assert out.lower().count("<script") == out.lower().count("</script>")


def test_attribute_values_are_reescaped() -> None:
    raw = _page('<p title="&quot;&gt;&lt;img src=x onerror=1&gt;">t</p><p>a &lt;b&gt; &amp; c</p>')
    out = sanitize_html(raw)
    assert "<img" not in out
    assert "a &lt;b&gt; &amp; c" in out


def test_head_and_html_created_when_missing() -> None:
    out = sanitize_html("<p>조각</p>")
    meta = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
    assert out.startswith("<html><head>" + meta)
    assert "<p>조각</p>" in out


def test_doctype_preserved_and_comments_dropped() -> None:
    out = sanitize_html("<!DOCTYPE html><!-- note https://x --><html lang=\"ko\"><head></head><body>a</body></html>")
    assert out.startswith("<!DOCTYPE html><html lang=\"ko\"><head>")
    assert "note" not in out


def test_model_bridge_marker_attribute_removed() -> None:
    out = sanitize_html(_page("<script data-daon-bridge>alert(1)</script><p>x</p>"))
    assert "data-daon-bridge" not in out


def test_bridge_script_shape() -> None:
    assert BRIDGE_SCRIPT.startswith("<script data-daon-bridge>")
    assert BRIDGE_SCRIPT.endswith("</script>")
    assert 'closest("[data-ref]")' in BRIDGE_SCRIPT
    assert "/^S\\d+$/" in BRIDGE_SCRIPT
    assert 'parent.postMessage({type:"daon-ref",ref:r},"*")' in BRIDGE_SCRIPT


def test_attach_bridge_without_body_appends() -> None:
    assert attach_bridge("<p>x</p>") == "<p>x</p>" + BRIDGE_SCRIPT
    assert strip_bridge("<p>x</p>" + BRIDGE_SCRIPT) == "<p>x</p>"


def test_finalize_success_and_failures() -> None:
    raw = "```html\n" + _page("<h2>개요</h2><p>보상 한도는 100만 원입니다.</p>") + "\n```"
    out = finalize_html(raw, "개요\n보상 한도는 100만 원이다.", "요청", ["개요"])
    assert out.count("data-daon-bridge") == 1
    assert "Content-Security-Policy" in out

    with pytest.raises(WebPageCheckFailed) as numbers:
        finalize_html(_page("<h2>개요</h2><p>500만 원</p>"), "개요 100만 원", "요청", ["개요"])
    assert numbers.value.reason == "numbers"
    assert "number:500" in numbers.value.items

    with pytest.raises(WebPageCheckFailed) as headings:
        finalize_html(_page("<h2>개요</h2>"), "개요", "요청", ["개요", "문의처"])
    assert headings.value.reason == "headings"
    assert headings.value.items == ["문의처"]

    with pytest.raises(WebPageCheckFailed) as empty:
        finalize_html("설명만 있고 HTML은 없음", "", "요청", [])
    assert empty.value.reason == "empty"
