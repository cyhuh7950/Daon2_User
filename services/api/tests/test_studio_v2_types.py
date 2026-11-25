import unittest

from daon2_user_api.studio_v2_types import STUDIO_V2_TYPES, available_types, is_available, validate_settings


class StudioV2TypesTests(unittest.TestCase):
    def test_design_types_exist(self):
        for type_id in ("report", "data_table", "mind_map", "flashcards", "quiz", "slides", "infographic",
                        "audio_overview", "video_overview", "memo", "authored_document"):
            self.assertIn(type_id, STUDIO_V2_TYPES)
        self.assertEqual(STUDIO_V2_TYPES["report"].presets, ("summary", "briefing", "blog", "study_guide", "custom"))
        self.assertEqual(STUDIO_V2_TYPES["slides"].export_formats, ("pptx", "pdf"))

    def test_export_formats_have_no_duplicates(self):
        for spec in STUDIO_V2_TYPES.values():
            self.assertEqual(len(spec.export_formats), len(set(spec.export_formats)))

    def test_later_phase_types_are_unavailable_with_reason(self):
        by_id = {item["type_id"]: item for item in available_types()}
        for type_id in ("audio_overview", "video_overview", "authored_document"):
            self.assertFalse(by_id[type_id]["available"])
            self.assertEqual(by_id[type_id]["reason"], "STUDIO_TYPE_UNAVAILABLE")
        for type_id in ("report", "data_table", "mind_map", "flashcards", "quiz", "slides", "infographic", "memo"):
            self.assertTrue(by_id[type_id]["available"])
            self.assertNotIn("reason", by_id[type_id])
        self.assertTrue(is_available("audio_overview", tts_enabled=True))

    def test_web_page_is_listed_last_among_tiles_with_page_request_schema(self):
        items = available_types()
        by_id = {item["type_id"]: item for item in items}
        self.assertIn("web_page", by_id)
        self.assertTrue(by_id["web_page"]["available"])
        self.assertEqual(by_id["web_page"]["export_formats"], ["html"])
        self.assertEqual(by_id["web_page"]["settings_schema"]["properties"]["page_request"]["maxLength"], 2000)
        ids = [item["type_id"] for item in items]
        self.assertEqual(ids[ids.index("web_page") - 1], "data_table")

    def test_web_page_requires_page_request_at_create(self):
        for settings in ({}, {"page_request": ""}, {"page_request": "   "}):
            with self.assertRaises(ValueError):
                validate_settings("web_page", None, settings)
        self.assertEqual(validate_settings("web_page", None, {"page_request": " 안내 페이지 "}), (None, {"page_request": " 안내 페이지 "}))

    def test_validate_settings_defaults_and_rejections(self):
        self.assertEqual(validate_settings("report", None, {}), ("summary", {}))
        self.assertEqual(validate_settings("quiz", None, {"count": 10, "focus": "핵심"}), (None, {"count": 10, "focus": "핵심"}))
        for bad in (("report", "unknown", {}), ("report", "custom", {}), ("quiz", None, {"count": 99}),
                    ("quiz", None, {"count": True}), ("memo", "summary", {}), ("quiz", None, {"nope": 1}),
                    ("nope", None, {}), ("report", None, {"focus": "x" * 501})):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "STUDIO_INPUT_INVALID"):
                    validate_settings(*bad)
        self.assertEqual(validate_settings("report", "custom", {"custom_instruction": "표로"})[0], "custom")


if __name__ == "__main__":
    unittest.main()
