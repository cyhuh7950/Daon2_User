from __future__ import annotations

import csv
import io
import json
import re
import unittest
import zipfile
from xml.etree import ElementTree

from daon2_user_api.studio_v2_export import export_v2, layout_tree, render_markdown
from daon2_user_api.studio_workspace import StudioError
from daon2_user_api.studio_v2_service import StudioV2Service

EVIDENCE = [{"ref_id": "S1", "source_version_id": "sv-1", "locator_kind": "page", "locator_value": "3", "origin": "notebook_source",
             "source_name": "약관.pdf", "has_snapshot": False}]


def output(type_id, body, title="테스트 산출물"):
    return {"output_id": "sv2-x", "type_id": type_id, "title": title, "status": "completed", "evidence": EVIDENCE,
            "revision": {"revision_no": 1, "content": {"schema": f"studio.{type_id}.v1", "language": "ko", "body": body, "warnings": []}}}


REPORT = output("report", {"title": "약관 요약", "summary": "핵심 요약", "sections": [
    {"heading": "지급", "blocks": [{"type": "paragraph", "text": "보험금은 3일 이내에 지급한다.", "refs": ["S1"]},
                                 {"type": "bullets", "items": ["한도 1,000,000원", "면책 90일"], "refs": ["S1"]},
                                 {"type": "table", "rows": [["항목", "값"], ["한도", "100"]], "refs": []}]}]})
TABLE = output("data_table", {"title": "비교", "columns": [{"key": "a", "label": "항목", "type": "text"}, {"key": "b", "label": "한도", "type": "number"}],
                              "rows": [{"cells": {"a": {"value": "보험금", "refs": ["S1"]}, "b": {"value": "1,000,000", "refs": ["S1"]}}}], "notes": ["주의"]})
MAP = output("mind_map", {"root": "r", "nodes": [{"id": "r", "label": "약관", "parent": None, "refs": []},
                                                  {"id": "a", "label": "지급", "parent": "r", "refs": ["S1"]},
                                                  {"id": "b", "label": "면책", "parent": "r", "refs": ["S1"]}]})
CARDS = output("flashcards", {"cards": [{"front": "지급 기한", "back": "3일", "refs": ["S1"], "hint": "접수일"}]})
QUIZ = output("quiz", {"questions": [{"q": "기한은?", "options": ["3일", "5일", "7일", "10일"], "answer_index": 0, "explanation": "3일", "refs": ["S1"]}]})
SLIDES = output("slides", {"title": "발표", "slides": [
    {"layout": "title", "title": "표지", "bullets": ["부제"], "notes": "", "refs": []},
    {"layout": "bullets", "title": "지급", "bullets": ["3일 이내", "한도 100만원"], "notes": "발표 노트", "refs": ["S1"]},
    {"layout": "two_column", "title": "비교", "bullets": ["가", "나", "다"], "notes": "", "refs": ["S1"]},
    {"layout": "table", "title": "표", "bullets": [], "table": {"columns": ["a", "b"], "rows": [["1", "2"]]}, "notes": "", "refs": ["S1"]}]})
MEMO = output("memo", {"markdown": "# 메모\n본문"})


def parse_all_xml(data: bytes) -> dict[str, bytes]:
    archive = zipfile.ZipFile(io.BytesIO(data))
    assert archive.testzip() is None
    parts = {}
    for name in archive.namelist():
        content = archive.read(name)
        if name.endswith((".xml", ".rels")):
            ElementTree.fromstring(content)  # 잘 구성된 XML이어야 한다
        parts[name] = content
    return parts


class ExportTests(unittest.TestCase):
    def test_docx_structure_and_korean_text(self):
        result = export_v2("docx", REPORT)
        parts = parse_all_xml(result.content)
        for required in ("[Content_Types].xml", "word/document.xml", "word/styles.xml", "word/numbering.xml", "_rels/.rels"):
            self.assertIn(required, parts)
        document = parts["word/document.xml"].decode()
        for text in ("약관 요약", "보험금은 3일 이내에 지급한다.", "근거 목록", "약관.pdf", "[S1]"):
            self.assertIn(text, document)
        self.assertIn('w:pStyle w:val="Heading1"', document)
        self.assertIn("<w:tbl>", document)
        self.assertEqual(result.media_type, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertTrue(result.ascii_filename.endswith(".docx"))

    def test_pdf_has_text_and_korean(self):
        from pypdf import PdfReader
        result = export_v2("pdf", REPORT)
        self.assertTrue(result.content.startswith(b"%PDF-"))
        text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(result.content)).pages)
        self.assertIn("약관 요약", text)
        self.assertIn("근거 목록", text)
        # 같은 입력은 같은 바이트(invariant)
        self.assertEqual(result.content, export_v2("pdf", REPORT).content)

    def test_markdown_footnotes_and_memo_passthrough(self):
        md = render_markdown(REPORT)
        self.assertIn("# 약관 요약", md)
        self.assertIn("[^S1]", md)
        self.assertIn("[^S1]: 약관.pdf 3쪽", md)
        self.assertEqual(render_markdown(MEMO), "# 메모\n본문")
        self.assertEqual(export_v2("txt", MEMO).content, "# 메모\n본문".encode())

    def test_xlsx_has_two_sheets_with_bold_header_and_evidence(self):
        parts = parse_all_xml(export_v2("xlsx", TABLE).content)
        sheet1, sheet2 = parts["xl/worksheets/sheet1.xml"].decode(), parts["xl/worksheets/sheet2.xml"].decode()
        self.assertIn("보험금", sheet1)
        self.assertIn('s="1"', sheet1)
        self.assertIn("[S1]", sheet2)
        self.assertIn("데이터", parts["xl/workbook.xml"].decode())
        with self.assertRaises(StudioError):
            export_v2("xlsx", REPORT)

    def test_csv_bom_header_and_evidence_section(self):
        data = export_v2("csv", TABLE).content
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual(rows[0], ["항목", "한도"])
        self.assertEqual(rows[1], ["보험금", "1,000,000"])
        self.assertIn(["S1", "약관.pdf", "3쪽"], [[r[0], r[1], r[2]] for r in rows if len(r) >= 3])
        quiz = list(csv.reader(io.StringIO(export_v2("csv", QUIZ).content.decode("utf-8-sig"))))
        self.assertEqual(quiz[1][5], "1")
        cards = list(csv.reader(io.StringIO(export_v2("csv", CARDS).content.decode("utf-8-sig"))))
        self.assertEqual(cards[1][:2], ["지급 기한", "3일"])

    def test_json_contains_content_and_evidence(self):
        data = json.loads(export_v2("json", QUIZ).content)
        self.assertEqual(data["schema"], "studio.quiz.v1")
        self.assertEqual(data["evidence"][0]["ref_id"], "S1")

    def test_mind_map_svg_png_and_layout(self):
        positions = layout_tree(MAP["revision"]["content"]["body"]["nodes"])
        self.assertEqual(positions["r"][0], 0)
        self.assertEqual(positions["a"][0], positions["b"][0])
        self.assertLess(positions["a"][1], positions["b"][1])
        svg = export_v2("svg", MAP).content.decode()
        ElementTree.fromstring(svg)
        self.assertIn("약관", svg)
        self.assertEqual(svg.count("<rect"), 4)  # 배경 + 노드 3
        from PIL import Image
        png = export_v2("png", MAP).content
        image = Image.open(io.BytesIO(png))
        self.assertEqual(image.format, "PNG")
        self.assertGreater(image.size[0], 200)

    def test_pptx_parts_relationships_and_text(self):
        result = export_v2("pptx", SLIDES)
        parts = parse_all_xml(result.content)
        names = set(parts)
        for n in range(1, 5):
            self.assertIn(f"ppt/slides/slide{n}.xml", names)
            self.assertIn(f"ppt/notesSlides/notesSlide{n}.xml", names)
        for required in ("ppt/presentation.xml", "ppt/slideMasters/slideMaster1.xml", "ppt/slideLayouts/slideLayout1.xml",
                         "ppt/notesMasters/notesMaster1.xml", "ppt/theme/theme1.xml", "docProps/app.xml"):
            self.assertIn(required, names)
        # 모든 관계 대상이 실제로 존재해야 한다
        for name, content in parts.items():
            if not name.endswith(".rels"):
                continue
            base = name.replace("_rels/", "").rsplit("/", 1)[0] if "/" in name.replace("_rels/", "") else ""
            for rel in ElementTree.fromstring(content):
                target = rel.attrib["Target"]
                path = target.lstrip("/") if target.startswith("/") else "/".join(filter(None, [base, target]))
                parts_path = []
                for piece in path.split("/"):
                    if piece == "..":
                        parts_path.pop()
                    elif piece:
                        parts_path.append(piece)
                self.assertIn("/".join(parts_path), names, f"{name} -> {target}")
        presentation = parts["ppt/presentation.xml"].decode()
        self.assertEqual(len(re.findall(r"<p:sldId ", presentation)), 4)
        self.assertIn('cx="12192000" cy="6858000"', presentation)
        slide2 = parts["ppt/slides/slide2.xml"].decode()
        self.assertIn("3일 이내", slide2)
        self.assertIn("근거: S1", slide2)
        self.assertIn("발표 노트", parts["ppt/notesSlides/notesSlide2.xml"].decode())
        self.assertIn("<a:tbl>", parts["ppt/slides/slide4.xml"].decode())
        content_types = parts["[Content_Types].xml"].decode()
        self.assertIn("/ppt/slides/slide4.xml", content_types)
        self.assertIn("/ppt/notesMasters/notesMaster1.xml", content_types)

    def test_pdf_for_each_type_and_unsupported_formats(self):
        for item in (TABLE, CARDS, QUIZ, SLIDES, MEMO):
            self.assertTrue(export_v2("pdf", item).content.startswith(b"%PDF-"))
        for fmt, item in (("svg", REPORT), ("png", REPORT), ("pptx", REPORT), ("mp3", REPORT), ("csv", REPORT)):
            with self.subTest(fmt=fmt):
                with self.assertRaises(StudioError):
                    export_v2(fmt, item)

    def test_control_characters_do_not_break_xml(self):
        dirty = output("report", {"title": "제목\x00\x0b", "summary": "요약\x01", "sections": [
            {"heading": "h<&>", "blocks": [{"type": "paragraph", "text": "a & b < c \x08", "refs": ["S1"]}]}]})
        parse_all_xml(export_v2("docx", dirty).content)

    def test_service_rejects_formats_not_declared_for_type(self):
        service = StudioV2Service.__new__(StudioV2Service)
        service.get_output = lambda ctx, oid, rev: QUIZ  # type: ignore[method-assign]
        with self.assertRaisesRegex(StudioError, "EXPORT_FORMAT_UNSUPPORTED"):
            service.export(None, "sv2-x", "docx", None)
        self.assertEqual(service.export(None, "sv2-x", "csv", None).media_type, "text/csv; charset=utf-8")


if __name__ == "__main__":
    unittest.main()
