from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from daon2_user_api.studio_v2_export import export_v2
from daon2_user_api.studio_web_page import BEHAVIOR_SCRIPT, BRIDGE_SCRIPT, CSP, attach_bridge, finalize_html
from daon2_user_api.studio_workspace import StudioError

RAW = "<!DOCTYPE html><html><body><h1>요약</h1><p>본문 글</p></body></html>"
EVIDENCE = [
    {"ref_id": "S1", "source_name": "연간 <보고서>.pdf", "locator_kind": "page", "locator_value": "3"},
    {"ref_id": "S2", "origin": "회의록", "locator_kind": "section", "locator_value": "2장"},
]


def _output(type_id: str = "web_page", html: str | None = None, evidence=EVIDENCE) -> dict:
    stored = finalize_html(RAW, "요약 본문 글", "", ["요약"]) if html is None else html
    return {"type_id": type_id, "title": "페이지", "revision": {"content": {"body": {"html": stored}}}, "evidence": evidence}


def _text(output: dict, **kw) -> str:
    return export_v2("html", output, **kw).content.decode("utf-8")


class WebPageHtmlExportTests(unittest.TestCase):
    def test_html_export_strips_bridge_keeps_csp(self):
        output = _output()
        self.assertIn(BRIDGE_SCRIPT, output["revision"]["content"]["body"]["html"])
        text = _text(output)
        self.assertNotIn("data-daon-bridge", text)
        self.assertNotIn("postMessage", text)
        self.assertEqual(text.count("Content-Security-Policy"), 1)
        self.assertIn(CSP, text)
        self.assertEqual(text.count(BEHAVIOR_SCRIPT), 1)  # 고정 동작 스크립트는 남는다
        self.assertEqual(text.count("<script"), 1)
        self.assertEqual(export_v2("html", output).media_type, "text/html; charset=utf-8")

    def test_html_export_appends_sources_by_default(self):
        text = _text(_output())
        self.assertIn("출처", text)
        self.assertIn("S1", text)
        self.assertIn("연간 &lt;보고서&gt;.pdf", text)
        self.assertNotIn("<보고서>", text)
        self.assertIn("3쪽", text)
        self.assertIn("회의록", text)
        self.assertIn("section 2장", text)
        self.assertLess(text.index("본문 글"), text.index("출처"))
        self.assertLess(text.index("출처"), text.lower().rindex("</body>"))

    def test_html_export_without_sources(self):
        text = _text(_output(), include_sources=False)
        self.assertNotIn("출처", text)
        self.assertNotIn("연간", text)
        self.assertIn("본문 글", text)
        self.assertEqual(text.count(BEHAVIOR_SCRIPT), 1)

    def test_html_export_has_no_external_reference(self):
        hostile = attach_bridge(finalize_html(RAW, "요약 본문 글", "", ["요약"]))
        for text in (_text(_output(html=hostile)), _text(_output(), include_sources=False)):
            for needle in ("http://", "https://", 'src="//'):
                self.assertNotIn(needle, text)

    def test_other_types_reject_html(self):
        with self.assertRaises(StudioError) as caught:
            export_v2("html", _output(type_id="report"))
        self.assertEqual(caught.exception.code, "EXPORT_FORMAT_UNSUPPORTED")

    def test_sources_skipped_when_no_evidence(self):
        self.assertNotIn("출처", _text(_output(evidence=[])))


if __name__ == "__main__":
    unittest.main()
