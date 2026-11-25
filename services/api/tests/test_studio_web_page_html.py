"""WO-N8 웹 페이지 2단계 HTML 처리(정리·CSP·대조·연결 스크립트)."""

from __future__ import annotations

import re

import pytest

from daon2_user_api.studio_web_page import (
    BEHAVIOR_SCRIPT,
    BRIDGE_SCRIPT,
    CSP,
    MAX_HTML_BYTES,
    WebPageCheckFailed,
    attach_behavior,
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
    assert re.search(r"<head>" + re.escape('<meta charset="utf-8">' + meta), out)


def test_numbers_outside_verified_text_are_stray() -> None:
    html = sanitize_html(_page("<p>보상 한도는 500만 원입니다.</p>"))
    assert stray_anchors(html, "보상 한도는 100만 원이다.", "요청") != set()


def test_model_script_is_removed_entirely() -> None:
    # 모델 스크립트는 남지 않으므로 숫자 대조 대상도 아니다(판정 A).
    html = sanitize_html(_page("<p>안내</p><script>const rate=0.37</script>"))
    assert "<script" not in html.lower()
    assert "0.37" not in html
    assert stray_anchors(html, "안내", "요청") == set()


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
    assert attached.index("data-daon-bridge") < attached.index("<p data-ref")
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


def test_inline_handlers_and_inline_script_are_removed() -> None:
    raw = _page(
        '<button onclick="toggle()" ONMOUSEOVER="x()" data-toggle="a">열기</button>'
        "<script>function toggle(){return 1<2}</script>"
        "<svg><script>alert(1)</script></svg><math><script>alert(2)</script></math>"
    )
    out = sanitize_html(raw)
    assert "onclick" not in out.lower() and "onmouseover" not in out.lower()
    assert "<script" not in out.lower() and "alert" not in out and "toggle()" not in out
    assert '<button data-toggle="a">열기</button>' in out


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
    assert "<script" not in out.lower() and "</script" not in out.lower()
    assert "<p>x</p>" in out


_EVIL = (
    '<meta http-equiv="refresh" content="1;url=https://evil.example/?x">'
    '<a href="https://evil.example/a">x</a><form action="https://evil.example/f"></form>'
)


def _assert_no_evil(out: str) -> None:
    lowered = out.lower()
    assert "http-equiv" not in lowered.replace('http-equiv="content-security-policy"', "")
    assert "evil.example" not in lowered
    assert "<form" not in lowered
    assert '<a href="http' not in lowered


@pytest.mark.parametrize("payload", [
    "<h2>개요</h2><p>본문</p><svg></math><script>" + _EVIL + "</script></svg>",
    "<h2>개요</h2><p>본문</p><svg><foreignObject><p></svg></p></foreignObject><script>" + _EVIL + "</script></svg>",
])
def test_reviewer_foreign_content_script_payloads(payload: str) -> None:
    out = sanitize_html(payload)
    _assert_no_evil(out)
    assert out.lower().count("http-equiv") == 1
    final = finalize_html(payload, "개요 본문", "", ["개요"])
    _assert_no_evil(final)


@pytest.mark.parametrize("wrapper", ["{}", "<svg>{}</svg>", "<svg></math>{}</svg>", "<math><mtext>{}</mtext></math>"])
def test_style_raw_text_never_contains_lt(wrapper: str) -> None:
    out = sanitize_html(wrapper.format("<style>p{color:red}" + _EVIL + "</style>"))
    chunks = re.findall(r"<style>(.*?)</style>", out, re.S)
    assert chunks
    for chunk in chunks:
        # 태그를 열 수 없고(<가 없음) 주소 형태도 남지 않는다. 남은 "evil.example" 글자 자체는 CSS 안의 무해한 글이다.
        assert "<" not in chunk
        assert "http:" not in chunk.lower() and "https:" not in chunk.lower() and "//" not in chunk
    assert "<a " not in out and "<form" not in out and "<meta http-equiv=\"refresh" not in out


def test_template_and_noscript_dropped_with_content() -> None:
    out = sanitize_html(_page("<template><p>틀 안</p></template><noscript><p>대체 글</p></noscript><p>남음</p>"))
    assert "template" not in out and "noscript" not in out
    assert "틀 안" not in out and "대체 글" not in out
    assert "<p>남음</p>" in out


def test_charset_and_doctype_always_ours() -> None:
    meta = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
    for raw in (
        '<html><head><meta charset="euc-kr"><meta http-equiv="Content-Type" content="text/html; charset=euc-kr"></head><body>a</body></html>',
        "<p>a</p>",
        "<!DOCTYPE html PUBLIC \"-//W3C//DTD HTML 4.01//EN\"><p>a</p>",
    ):
        out = sanitize_html(raw)
        assert out.startswith("<!DOCTYPE html><html><head>" + '<meta charset="utf-8">' + meta)
        assert out.lower().count("charset") == 1
        assert "euc-kr" not in out and "W3C" not in out


def test_control_characters_stripped() -> None:
    out = sanitize_html(_page('<p title="a\x01b\x00c">x\x02y\x1fz\tw\nv</p>'))
    assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", out)
    assert 'title="abc"' in out
    assert "xyz\tw\nv" in out


@pytest.mark.parametrize(("body", "anchor"), [
    ('<p title="연 37%">a</p>', "quantity:37:percent"),
    ('<img alt="500만 원" src="data:image/png;base64,AA">', "number:500"),
    ('<input value="777">', "number:777"),
    ('<ol start="450"><li>a</li></ol>', "number:450"),
    ('<ul><li value="321">a</li></ul>', "number:321"),
    ('<p aria-label="연 88명">a</p>', "number:88"),
    ('<input placeholder="예: 6543">', "number:6543"),
    ('<option label="4321">a</option>', "number:4321"),
    ('<p data-rate="0.37">a</p>', "number:0.37"),
])
def test_numbers_in_attributes_are_checked(body: str, anchor: str) -> None:
    html = sanitize_html(_page(body))
    assert anchor in stray_anchors(html, "a", "")


def test_numbers_in_css_content_are_checked() -> None:
    html = sanitize_html(_page('<p class="p">a</p><span style="--x:1">b</span>', head='<style>.p::before{content:"9,999원"}</style>'))
    assert "number:9999" in stray_anchors(html, "a b", "")
    inline = sanitize_html(_page('<p style="content:\'4,444\'">a</p>'))
    assert "number:4444" in stray_anchors(inline, "a", "")
    # CSS 정리로 생긴 \3c 는 숫자로 잡히지 않는다.
    lt = sanitize_html(_page("<p>a</p>", head='<style>.p::before{content:"<"}</style>'))
    assert stray_anchors(lt, "a", "") == set()


def test_structural_data_attributes_not_checked() -> None:
    html = sanitize_html(_page(
        '<div data-tabs="1"><button data-tab="t2026">a</button><div data-panel="t2026">a</div></div>'
        '<button data-toggle="x99">a</button><div data-toggle-target="x99">a</div>'
        '<table data-sortable="555"><tr><th>a</th></tr></table><p data-ref="S12">a</p>'
    ))
    assert stray_anchors(html, "a", "") == set()


def test_behavior_script_shape_and_attach() -> None:
    assert BEHAVIOR_SCRIPT.startswith("<script data-daon-behavior>") and BEHAVIOR_SCRIPT.endswith("</script>")
    for token in ("[data-tabs]", "[data-tab]", "[data-panel]", "aria-selected", "hidden",
                  "[data-toggle]", "[data-toggle-target]", "table[data-sortable]", "localeCompare", "numeric:true"):
        assert token in BEHAVIOR_SCRIPT, token
    body = BEHAVIOR_SCRIPT[len("<script data-daon-behavior>"):-len("</script>")]
    for banned in ("fetch", "XMLHttpRequest", "location", "window.open", "WebSocket", "sendBeacon", "import(", "eval", "innerHTML", "src", "href"):
        assert banned not in body, banned
    assert not re.search(r"(?<![\w.])(?:[2-9]|\d{2,})", body)
    html = sanitize_html(_page("<p>a</p>"))
    assert attach_behavior(html).count("data-daon-behavior") == 1


def test_finalize_inserts_behavior_then_bridge_and_strip_keeps_behavior() -> None:
    final = finalize_html(_page("<h2>개요</h2><p>a</p>"), "개요 a", "", ["개요"])
    b, r, end = final.index(BEHAVIOR_SCRIPT), final.index(BRIDGE_SCRIPT), final.index("<h2>")
    assert b < r < end
    stripped = strip_bridge(final)
    assert BEHAVIOR_SCRIPT in stripped and BRIDGE_SCRIPT not in stripped


def test_model_behavior_marker_attribute_removed() -> None:
    out = sanitize_html(_page('<p data-daon-behavior="1">x</p>'))
    assert "data-daon-behavior" not in out


def test_attach_goes_right_after_head_metas() -> None:
    # 최종 검토 M1: 고정 스크립트는 <head>의 charset·CSP 메타 바로 뒤에 들어간다(본문보다 앞).
    html = sanitize_html("<body><p>" + "İ" * 30 + '</p></body><p title="abcdefghijklmnopqrstuvwxyz">t</p>')
    metas = f'<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{CSP}">'
    after = html.index(metas) + len(metas)
    attached = attach_bridge(html)
    assert attached.index(BRIDGE_SCRIPT) == after
    assert strip_bridge(attached) == html
    behaved = attach_behavior(html)
    assert behaved.index(BEHAVIOR_SCRIPT) == after
    both = attach_bridge(behaved)
    assert both.index(BEHAVIOR_SCRIPT) == after and both.index(BRIDGE_SCRIPT) == after + len(BEHAVIOR_SCRIPT)


def test_unclosed_math_does_not_swallow_fixed_scripts() -> None:
    raw = '<!DOCTYPE html><html lang="ko"><body><h2>보장 안내</h2><p data-ref="S1">월 보험료는 15만 원입니다.</p><math><mi>x</body></html>'
    out = finalize_html(raw, "보장 안내\n월 보험료는 15만 원입니다.", "고객 안내", ["보장 안내"])
    body_start = out.index("<h2>")
    assert out.index(BEHAVIOR_SCRIPT) < body_start and out.index(BRIDGE_SCRIPT) < body_start
    assert out.index(BEHAVIOR_SCRIPT) < out.index(BRIDGE_SCRIPT)
    assert out.index(BRIDGE_SCRIPT) < out.index("<math>")


def test_charset_first_and_within_1024_bytes_even_with_huge_html_attrs() -> None:
    huge = "x" * 5000
    raw = f'<html data-x="{huge}" class="{huge}" lang="ko" dir="ltr" style="color:red"><body><p>a</p></body></html>'
    out = sanitize_html(raw)
    assert out.encode("utf-8").index(b'<meta charset="utf-8">') < 1024
    assert out.startswith('<!DOCTYPE html><html lang="ko" dir="ltr"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy"')
    assert huge not in out
    long_lang = sanitize_html(f'<html lang="{huge}" dir="{huge}"><body>a</body></html>')
    assert long_lang.startswith("<!DOCTYPE html><html><head><meta charset=")


def test_attribute_values_are_reescaped() -> None:
    raw = _page('<p title="&quot;&gt;&lt;img src=x onerror=1&gt;">t</p><p>a &lt;b&gt; &amp; c</p>')
    out = sanitize_html(raw)
    assert "<img" not in out
    assert "a &lt;b&gt; &amp; c" in out


def test_head_and_html_created_when_missing() -> None:
    out = sanitize_html("<p>조각</p>")
    meta = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
    assert out.startswith("<!DOCTYPE html><html><head>" + '<meta charset="utf-8">' + meta)
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


# --- 최종 검토 C1: 1~20 예외는 단독 순번만 ---


@pytest.mark.parametrize("phrase", [
    "5만 원", "3억 원", "3천만 원", "월 12만 원", "제3조", "제15조 제2항", "10세", "2배", "3회", "5명",
    "5 명", "7일", "20%", "3 kg", "1.5", "10:30",
])
def test_small_numbers_with_units_are_stray(phrase: str) -> None:
    html = sanitize_html(_page(f"<h2>안내</h2><p>보험료 {phrase} 안내</p>"))
    assert stray_anchors(html, "안내 보험료", "요청") != set(), phrase


@pytest.mark.parametrize("phrase", ["1. 신청", "(2) 서류", "2) 접수", "탭 3", "3단계", "3번", "3번째", "단계 20"])
def test_standalone_ordinals_pass(phrase: str) -> None:
    html = sanitize_html(_page(f"<h2>안내</h2><p>{phrase}</p>"))
    assert stray_anchors(html, "안내 신청 서류 접수", "요청") == set(), phrase


def test_small_numbers_in_request_text_still_pass() -> None:
    html = sanitize_html(_page("<p>보험료 5만 원, 제3조</p>"))
    assert stray_anchors(html, "보험료", "보험료 5만 원과 제3조 안내") == set()


def test_reviewer_probe_numbers_are_stray() -> None:
    allowed = "월 보험료는 15만 원이며 보장 기간은 20년입니다."
    html = sanitize_html("<!DOCTYPE html><html><body><h2>보장</h2><p>월 보험료는 5만 원이며, 약관 제7조에 따라 3배 보상, 10세 이상 가입.</p></body></html>")
    stray = stray_anchors(html, allowed, "고객 안내 페이지")
    assert {"number:5", "number:7", "number:3", "number:10"} <= stray


# --- 재검토: 서식 문자·속성 글의 순번 ---


@pytest.mark.parametrize("hidden", ["​", "­", "⁠", "﻿"])
def test_format_characters_do_not_hide_units(hidden: str) -> None:
    html = sanitize_html(_page(f"<h2>안내</h2><p>보험료 5{hidden}만 원</p>"))
    assert "number:5" in stray_anchors(html, "안내 보험료", "요청"), repr(hidden)


@pytest.mark.parametrize("body", ['<ol start="3"><li>신청</li></ol>', '<h2 aria-level="2">신청</h2>', '<button aria-label="탭 2">신청</button>'])
def test_standalone_ordinals_in_attributes_pass(body: str) -> None:
    html = sanitize_html(_page(body))
    assert stray_anchors(html, "신청", "요청") == set(), body


@pytest.mark.parametrize(("body", "anchor"), [('<p title="5만 원">신청</p>', "number:5"), ('<p aria-label="제3조">신청</p>', "number:3")])
def test_small_numbers_with_units_in_attributes_are_stray(body: str, anchor: str) -> None:
    html = sanitize_html(_page(body))
    assert anchor in stray_anchors(html, "신청", "요청"), body
