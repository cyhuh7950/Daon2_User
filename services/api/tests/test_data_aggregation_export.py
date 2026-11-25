"""데이터 집계(WO-N9) 내려받기: XLSX 3시트·CSV 계산값 표시 열·수식 주입 막기."""
from __future__ import annotations

import csv
import io
import re
import unittest
import zipfile
from xml.etree import ElementTree

from daon2_user_api.studio_v2_export import export_v2

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def cell(value, display, *, computed=False, status="ok", reason=None, evidence_id=None):
    return {"value": value, "display": display, "computed": computed, "status": status, "reason": reason, "evidence_id": evidence_id}


def body(**over):
    data = {
        "request": "=HYPERLINK(\"http://x\") 상품별 지급액 합계",
        "source": {"source_version_id": "sv-1", "sha256": "a" * 64, "file_name": "@청구.xlsx", "sheet": "청구내역", "header_row": 1},
        "spec": {}, "spec_raw": {},
        "conditions_text": "+묶기: 상품 · 집계: 합계(지급액)",
        "columns": [{"key": "상품", "label": "-상품", "role": "group"},
                    {"key": "m1", "label": "지급액 합계", "role": "measure"},
                    {"key": "growth_m1", "label": "전월 대비 증감률 · 지급액 합계", "role": "growth"}],
        "rows": [
            [cell("=1+1", "=1+1"), cell("1234.50", "1,234.50", computed=True, evidence_id="e1"),
             cell("-12.5", "-12.5%", computed=True, evidence_id="e2")],
            [cell("암\x00보험", "암\x00보험"), cell(None, "계산 불가", computed=True, status="not_computable", reason="숫자 값 없음", evidence_id="e3"),
             cell(None, "계산 불가", computed=True, status="not_computable", reason="전월 자료 없음", evidence_id="e4")],
        ],
        "evidence": {
            "e1": {"range": "청구내역!F: 2–31, 45–60", "filter_text": "@상품 = =1+1", "formula": "지급액 합계 = 숫자 46개의 합",
                   "row_count": 46, "excluded": {"not_number": 2, "blank": 1}},
            # 증감률 근거는 범위를 다시 쓰지 않고 이번 달·전월 근거 번호만 가진다(e5는 표에 없는 전월 칸의 근거).
            "e2": {"current_evidence_id": "e1", "previous_evidence_id": "e5", "filter_text": "상품 = =1+1", "formula": "(a − b) ÷ b × 100",
                   "row_count": 76, "excluded": {"not_number": 2, "blank": 1}},
            "e3": {"range": None, "filter_text": "상품 = 암보험", "formula": "지급액 합계 = 숫자 0개의 합", "row_count": 0,
                   "excluded": {"not_number": 3, "blank": 0}},
            "e4": {"current_evidence_id": "e3", "previous_evidence_id": None, "filter_text": "상품 = 암보험", "formula": "(a − b) ÷ b × 100",
                   "row_count": 0, "excluded": {"not_number": 3, "blank": 0}},
            "e5": {"range": "청구내역!F: 70–99", "filter_text": "상품 = =1+1 · 월 = 2026-01", "formula": "지급액 합계 = 숫자 30개의 합",
                   "row_count": 30, "excluded": {"not_number": 0, "blank": 0}},
        },
        "chart": None,
        "summary": ["지급액 합계 가장 큰 묶음: =1+1 (1,234.50)"],
        "warnings": ["하지 않은 요청: \t다른 파일과 비교"],
        "stats": {"rows_read": 120, "elapsed_ms": 30},
    }
    data.update(over)
    return data


def output(data=None, title="데이터 집계"):
    return {"output_id": "sv2-x", "type_id": "data_aggregation", "title": title, "status": "completed", "evidence": [],
            "revision": {"revision_no": 1, "content": {"schema": "studio.data_aggregation.v1", "language": "ko", "body": data or body(), "warnings": []}}}


def workbook(content: bytes):
    archive = zipfile.ZipFile(io.BytesIO(content))
    names = archive.namelist()
    wb = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    sheet_names = [s.get("name") for s in wb.iter(f"{NS}sheet")]
    sheets = []
    for index in range(1, len(sheet_names) + 1):
        root = ElementTree.fromstring(archive.read(f"xl/worksheets/sheet{index}.xml"))
        rows = []
        for row in root.iter(f"{NS}row"):
            cells = []
            for c in row.iter(f"{NS}c"):
                kind = c.get("t")
                if kind == "inlineStr":
                    cells.append(("s", "".join(t.text or "" for t in c.iter(f"{NS}t"))))
                else:
                    cells.append(("n", c.find(f"{NS}v").text))
            rows.append(cells)
        sheets.append(rows)
    raw = b"".join(archive.read(n) for n in names if n.startswith("xl/worksheets/"))
    return sheet_names, sheets, raw


class DataAggregationExportTest(unittest.TestCase):
    def test_xlsx_three_sheets_no_formulas(self):
        exported = export_v2("xlsx", output())
        self.assertTrue(exported.ascii_filename.endswith(".xlsx"))
        names, sheets, raw = workbook(exported.content)
        self.assertEqual(names, ["집계표", "계산 근거", "적용한 조건"])
        self.assertNotIn(b"<f>", raw)
        self.assertNotIn(b"<f ", raw)
        table = sheets[0]
        header = [text for _, text in table[0]]
        self.assertEqual(header, ["-상품", "지급액 합계", "지급액 합계 계산값 표시", "전월 대비 증감률 · 지급액 합계",
                                  "전월 대비 증감률 · 지급액 합계 계산값 표시"])
        first = table[1]
        # 묶음 열(원본값)은 글자, 계산값은 저장값 그대로의 숫자, 옆 열에 "계산값" 표시.
        self.assertEqual(first[0], ("s", "=1+1"))
        self.assertEqual(first[1], ("n", "1234.50"))
        self.assertEqual(first[2], ("s", "계산값"))
        self.assertEqual(first[3], ("n", "-12.5"))
        self.assertEqual(first[4], ("s", "계산값"))
        second = table[2]
        self.assertEqual(second[0], ("s", "암보험"))  # NUL 제거
        self.assertEqual(second[1], ("s", "계산 불가"))
        self.assertEqual(second[2], ("s", "계산 불가: 숫자 값 없음"))
        evidence = sheets[1]
        self.assertEqual([text for _, text in evidence[0]],
                         ["행", "열", "값", "파일", "시트", "범위", "필터", "계산식", "대상 행 수", "제외(숫자 아님)", "제외(빈칸)", "계산 불가 이유", "근거 번호"])
        e1 = evidence[1]
        self.assertEqual(e1[1], ("s", "지급액 합계"))
        self.assertEqual(e1[3], ("s", "@청구.xlsx"))
        self.assertEqual(e1[5], ("s", "청구내역!F: 2–31, 45–60"))
        self.assertEqual(e1[12], ("s", "e1"))
        # 증감률: 이번 달·전월 근거를 번호와 범위로 함께 적는다(표에 없는 전월 칸의 범위도 보인다).
        e2 = evidence[2]
        self.assertEqual(e2[5], ("s", "이번 달(e1): 청구내역!F: 2–31, 45–60 / 전월(e5): 청구내역!F: 70–99"))
        self.assertEqual(e2[12], ("s", "e2"))
        self.assertEqual(evidence[3][5], ("s", ""))
        self.assertEqual(evidence[4][5], ("s", "이번 달(e3): 없음 / 전월: 자료 없음"))
        self.assertEqual(e1[6], ("s", "@상품 = =1+1"))
        self.assertEqual(e1[7], ("s", "지급액 합계 = 숫자 46개의 합"))
        self.assertEqual(e1[8:11], [("n", "46"), ("n", "2"), ("n", "1")])
        self.assertEqual(len(evidence), 5)
        conditions = {row[0][1]: row[1][1] for row in sheets[2][1:] if len(row) > 1}
        self.assertEqual(conditions["적용한 조건"], "+묶기: 상품 · 집계: 합계(지급액)")
        self.assertTrue(conditions["요청 글"].startswith("=HYPERLINK"))
        texts = [row[1][1] for row in sheets[2][1:] if len(row) > 1]
        self.assertIn("하지 않은 요청: \t다른 파일과 비교", texts)
        self.assertIn("지급액 합계 가장 큰 묶음: =1+1 (1,234.50)", texts)
        # 모든 글자 칸은 inlineStr(수식이 아님), 숫자 칸은 숫자 형식만.
        for sheet in sheets:
            for row in sheet:
                for kind, value in row:
                    if kind == "n":
                        self.assertRegex(value, r"^-?\d+(\.\d+)?$")

    def test_xlsx_number_cells_only_from_numeric_strings(self):
        data = body()
        data["rows"][0][1] = cell("=SUM(A1)", "=SUM(A1)", computed=True, evidence_id="e1")
        _, sheets, raw = workbook(export_v2("xlsx", output(data)).content)
        self.assertEqual(sheets[0][1][1], ("s", "=SUM(A1)"))
        self.assertNotIn(b"<f>", raw)

    def test_csv_has_computed_flag_column(self):
        exported = export_v2("csv", output())
        self.assertTrue(exported.content.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(exported.content[3:].decode("utf-8"))))
        self.assertEqual(rows[0], ["'-상품", "지급액 합계", "지급액 합계 계산값 표시", "전월 대비 증감률 · 지급액 합계",
                                   "전월 대비 증감률 · 지급액 합계 계산값 표시"])
        # 글자 칸의 수식 시작 문자는 작은따옴표로 막고, 계산값 숫자는 그대로 쓴다(음수 포함).
        self.assertEqual(rows[1], ["'=1+1", "1234.50", "계산값", "-12.5", "계산값"])
        self.assertEqual(rows[2], ["암보험", "계산 불가", "계산 불가: 숫자 값 없음", "계산 불가", "계산 불가: 전월 자료 없음"])
        flat = [value for row in rows for value in row]
        self.assertIn("'@청구.xlsx", flat)
        self.assertIn("'@상품 = =1+1", flat)
        self.assertIn("'+묶기: 상품 · 집계: 합계(지급액)", flat)
        self.assertIn("'=HYPERLINK(\"http://x\") 상품별 지급액 합계", flat)
        self.assertIn("하지 않은 요청: \t다른 파일과 비교", flat)
        self.assertIn("계산 근거", flat)
        self.assertIn("적용한 조건", flat)
        for value in flat:
            self.assertFalse(value[:1] in ("=", "+", "@", "\t", "\r") or (value.startswith("-") and not re.fullmatch(r"-\d+(\.\d+)?", value)), value)
            self.assertIsNone(re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value), value)

    def test_noncharacters_stripped_and_xlsx_well_formed(self):
        data = body()
        data["columns"][1]["label"] = "지급￿액￾ 합계"
        data["warnings"].append("￿ 이상한 글자")
        content = export_v2("xlsx", output(data)).content
        names, sheets, raw = workbook(content)  # ElementTree가 읽으면 XML이 올바르다
        self.assertEqual(sheets[0][0][1], ("s", "지급액 합계"))
        self.assertNotIn("￿".encode("utf-8"), raw)
        self.assertNotIn("￾".encode("utf-8"), raw)
        text = export_v2("csv", output(data)).content.decode("utf-8-sig")
        self.assertNotIn("￿", text)
        self.assertNotIn("￾", text)
        # 데이터 표 XLSX(_sheet)도 같은 규칙.
        table = {**output(), "type_id": "data_table", "revision": {"revision_no": 1, "content": {"body": {
            "columns": [{"key": "a", "label": "항￿목"}], "rows": [{"cells": {"a": {"value": "x￾", "refs": []}}}]}}}}
        archive = zipfile.ZipFile(io.BytesIO(export_v2("xlsx", table).content))
        sheet = archive.read("xl/worksheets/sheet1.xml")
        ElementTree.fromstring(sheet)
        self.assertNotIn("￿".encode("utf-8"), sheet)
        self.assertNotIn("￾".encode("utf-8"), sheet)

    def test_csv_numeric_looking_group_values_not_prefixed(self):
        data = body()
        data["rows"][0][0] = cell("-5", "-5")
        data["rows"][1][0] = cell("-1.25", "-1.25")
        rows = list(csv.reader(io.StringIO(export_v2("csv", output(data)).content[3:].decode("utf-8"))))
        self.assertEqual(rows[1][0], "-5")
        self.assertEqual(rows[2][0], "-1.25")
        for text, expected in (("-abc", "'-abc"), ("+5", "'+5"), ("-5-1", "'-5-1"), ("-1.", "'-1."), ("@1", "'@1"), ("=1", "'=1")):
            data["rows"][0][0] = cell(text, text)
            rows = list(csv.reader(io.StringIO(export_v2("csv", output(data)).content[3:].decode("utf-8"))))
            self.assertEqual(rows[1][0], expected)

    def test_csv_tab_and_cr_prefixed(self):
        data = body()
        data["rows"][0][0] = cell("\tx", "\tx")
        data["rows"][1][0] = cell("\ry", "\ry")
        rows = list(csv.reader(io.StringIO(export_v2("csv", output(data)).content[3:].decode("utf-8"))))
        self.assertEqual(rows[1][0], "'\tx")
        self.assertEqual(rows[2][0], "'\ry")


if __name__ == "__main__":
    unittest.main()
