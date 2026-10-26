"""인포그래픽(F7-01): 검증기·레이아웃(텍스트 넘침)·SVG/PNG/PDF 렌더링·생성기."""
from __future__ import annotations

import unittest
from xml.etree import ElementTree

from daon2_user_api import studio_infographic as infographic
from daon2_user_api.studio_generators import InfographicGenerator
from daon2_user_api.studio_v2_export import export_v2
from daon2_user_api.studio_v2_types import is_available
from daon2_user_api.studio_workspace import StudioError
from test_studio_v2_generation import FakeReader, ScriptedLLM, gen_ctx

BODY = {"title": "보험금 지급 안내", "subtitle": "청구부터 지급까지", "sections": [
    {"headline": "지급 기한", "value": "3일", "detail": "청구서류 접수일부터 3일 이내에 지급한다.", "icon": "clock", "refs": ["S1"]},
    {"headline": "지급 한도", "value": "1,000,000원", "detail": "사고당 지급 한도", "icon": "chart", "refs": ["S1"]},
    {"headline": "면책 기간", "value": "90일", "icon": "alert", "refs": ["S2"]}]}


class LayoutTests(unittest.TestCase):
    def test_wraps_to_line_limits_and_flags_overflow(self):
        lines, over = infographic.wrap("가" * 200, 16, 300, 3)
        self.assertEqual(len(lines), 3)
        self.assertTrue(over)
        self.assertTrue(lines[-1].endswith("…"))
        self.assertTrue(all(infographic._width(line, 16) <= 300 for line in lines))
        lines, over = infographic.wrap("짧은 문장", 16, 300, 3)
        self.assertEqual((lines, over), (["짧은 문장"], False))

    def test_layout_places_cards_without_overlap_and_reports_overflow(self):
        lay = infographic.layout(BODY)
        self.assertEqual(lay["overflow"], [])
        ends = [c["y"] + c["height"] for c in lay["cards"]]
        starts = [c["y"] for c in lay["cards"]]
        self.assertTrue(all(starts[i + 1] >= ends[i] for i in range(len(ends) - 1)))
        self.assertGreater(lay["height"], ends[-1])
        long = {**BODY, "sections": [{"headline": "가" * 40, "detail": "나" * 200, "refs": ["S1"]}, BODY["sections"][1]]}
        self.assertEqual(infographic.layout(long)["overflow"], ["sections[0]"])


class RenderTests(unittest.TestCase):
    def test_svg_is_wellformed_and_contains_text(self):
        svg = infographic.render_svg(BODY)
        root = ElementTree.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))
        text = "".join(root.itertext())
        for expected in ("보험금 지급 안내", "지급 기한", "1,000,000원"):
            self.assertIn(expected, text)

    def test_png_and_pdf_headers_and_size(self):
        png = infographic.render_png(BODY)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        lay = infographic.layout(BODY)
        from PIL import Image
        from io import BytesIO
        self.assertEqual(Image.open(BytesIO(png)).size, (lay["width"], lay["height"]))
        self.assertEqual(infographic.render_pdf(BODY)[:5], b"%PDF-")

    def test_pdf_has_an_invisible_text_layer_for_copy_search_and_screen_readers(self):
        from io import BytesIO
        from pypdf import PdfReader
        text = PdfReader(BytesIO(infographic.render_pdf(BODY))).pages[0].extract_text()
        for expected in ("보험금 지급 안내", "청구부터 지급까지", "지급 기한", "3일", "1,000,000원", "사고당 지급 한도", "면책 기간", "90일"):
            self.assertIn(expected, text)

    def test_export_registry_uses_infographic_renderers(self):
        output = {"title": "인포그래픽", "type_id": "infographic", "revision": {"content": {"body": BODY}}, "evidence": []}
        self.assertEqual(export_v2("png", output).media_type, "image/png")
        self.assertTrue(export_v2("svg", output).media_type.startswith("image/svg"))
        self.assertEqual(export_v2("pdf", output).content[:5], b"%PDF-")
        with self.assertRaises(StudioError):
            export_v2("pptx", output)


class GeneratorTests(unittest.TestCase):
    def run_generator(self, data):
        return InfographicGenerator(FakeReader(), ScriptedLLM(data)).generate(gen_ctx("infographic")[0])

    def test_valid_sections_are_kept_and_refs_cleaned(self):
        data = {"title": "t", "sections": [{"headline": "지급 기한", "value": "3일", "detail": "접수일부터 3일", "icon": "clock", "refs": ["S1", "S9"]},
                                           {"headline": "면책", "value": "90일", "icon": "nope", "refs": ["S2"]}, {"headline": "", "refs": ["S1"]}]}
        result = self.run_generator(data)
        sections = result.content["body"]["sections"]
        self.assertEqual([s["headline"] for s in sections], ["지급 기한", "면책"])
        self.assertEqual(sections[0]["refs"], ["S1"])
        self.assertNotIn("icon", sections[1])
        self.assertEqual(result.content["schema"], "studio.infographic.v1")
        self.assertEqual({e["ref_id"] for e in result.evidence}, {"S1", "S2"})

    def test_made_up_number_warns_and_long_text_is_flagged(self):
        data = {"title": "t", "sections": [{"headline": "지급 기한", "value": "99일", "detail": "W" * 120, "refs": ["S1"]},
                                           {"headline": "면책", "value": "90일", "refs": ["S2"]}]}
        codes = {w["code"] for w in self.run_generator(data).warnings}
        self.assertIn("ANCHOR_MISMATCH", codes)
        self.assertIn("INFOGRAPHIC_TEXT_TRUNCATED", codes)

    def test_too_few_sections_or_no_valid_refs_fail(self):
        with self.assertRaises(StudioError):
            self.run_generator({"sections": [{"headline": "하나", "refs": ["S1"]}]})
        with self.assertRaises(StudioError):
            self.run_generator({"sections": [{"headline": "가", "refs": ["S9"]}, {"headline": "나", "refs": []}]})


class AvailabilityTests(unittest.TestCase):
    def test_infographic_is_available_but_audio_video_are_not(self):
        self.assertTrue(is_available("infographic"))
        self.assertFalse(is_available("video_overview"))
        self.assertFalse(is_available("audio_overview"))


if __name__ == "__main__":
    unittest.main()
