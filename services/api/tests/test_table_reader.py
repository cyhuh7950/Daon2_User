from __future__ import annotations

import io
import json
import time
import unittest
import zipfile
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape, quoteattr

from daon2_user_api.table_reader import (
    Column, NotDate, NotNumber, Table, TableLimits, TableReadError,
    list_sheets, profile, read_table,
)

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _letter(col):
    letters = ""
    while col:
        col, digit = divmod(col - 1, 26)
        letters = chr(65 + digit) + letters
    return letters


def _cell(ref, value, style=None):
    s = f' s="{style}"' if style is not None else ""
    if value is None:
        return ""
    if isinstance(value, (int, float, Decimal)):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'


def sheet_xml(rows, *, start_row=1, date_cols=()):
    """rows: list of lists; ints/Decimals are numeric cells, str inline strings."""
    out = []
    for offset, row in enumerate(rows):
        r = start_row + offset
        cells = "".join(
            _cell(f"{_letter(c)}{r}", v, 1 if c in date_cols else None)
            for c, v in enumerate(row, 1)
        )
        out.append(f'<row r="{r}">{cells}</row>')
    return "<sheetData>" + "".join(out) + "</sheetData>"


def workbook(sheets, *, date1904=False, shared=(), compression=zipfile.ZIP_DEFLATED, extra=None, skip=()):
    """sheets: list of (name, sheetData xml)."""
    book_sheets = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1)
    )
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="{DOC_REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    entries = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "_rels/.rels": f'<Relationships xmlns="{REL}"><Relationship Id="r1" Type="{DOC_REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<workbook xmlns="{NS}" xmlns:r="{DOC_REL}"><workbookPr date1904="{int(date1904)}"/><sheets>{book_sheets}</sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{REL}">{rels}</Relationships>',
        "xl/styles.xml": f'<styleSheet xmlns="{NS}"><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd"/></numFmts><cellXfs count="3"><xf numFmtId="0"/><xf numFmtId="164"/><xf numFmtId="14"/></cellXfs></styleSheet>',
    }
    if shared:
        sis = "".join(f"<si><t>{escape(s)}</t></si>" for s in shared)
        entries["xl/sharedStrings.xml"] = f'<sst xmlns="{NS}">{sis}</sst>'
    for i, (_, xml) in enumerate(sheets, 1):
        entries[f"xl/worksheets/sheet{i}.xml"] = f'<worksheet xmlns="{NS}">{xml}</worksheet>'
    if extra:
        entries.update(extra)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, value in entries.items():
            if name in skip:
                continue
            archive.writestr(name, value.encode("utf-8") if isinstance(value, str) else value)
    return output.getvalue()


def read_xlsx(content, *, sheet=None, header_row=1, **kwargs):
    return read_table(content, file_name="t.xlsx", source_format="xlsx", sheet=sheet, header_row=header_row, **kwargs)


def read_csv(content, *, header_row=1, **kwargs):
    return read_table(content, file_name="t.csv", source_format="csv", sheet=None, header_row=header_row, **kwargs)


class TableReaderTests(unittest.TestCase):
    def assertCode(self, code, fn, *args, **kwargs):
        with self.assertRaises(TableReadError) as caught:
            fn(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_xlsx_over_2048_cells_reads(self):
        header = [f"열{i}" for i in range(1, 9)]
        rows = [header] + [[r * 10 + c for c in range(1, 9)] for r in range(1, 1001)]
        table = read_xlsx(workbook([("데이터", sheet_xml(rows))]))
        self.assertIsInstance(table, Table)
        self.assertEqual(table.source_format, "xlsx")
        self.assertEqual(table.sheet, "데이터")
        self.assertEqual(len(table.columns), 8)
        self.assertEqual(len(table.rows), 1000)
        self.assertEqual(table.rows[0][0], Decimal(11))
        self.assertEqual(table.rows[-1][-1], Decimal(10008))
        self.assertEqual(table.row_numbers[0], 2)
        self.assertEqual(table.row_numbers[-1], 1001)
        self.assertEqual(table.columns[0], Column(name="열1", letter="A", index=0, kind="number"))

    def test_xlsx_header_row_and_skip_title_rows(self):
        xml = sheet_xml([["2026년 지급 내역"], [], ["이름", "지급액"], ["가", 100], ["나", 200]])
        table = read_xlsx(workbook([("S", xml)]), header_row=3)
        self.assertEqual(table.header_row, 3)
        self.assertEqual([c.name for c in table.columns], ["이름", "지급액"])
        self.assertEqual(table.rows, (("가", Decimal(100)), ("나", Decimal(200))))
        self.assertEqual(table.row_numbers, (4, 5))

    def test_duplicate_and_blank_headers_named(self):
        xml = sheet_xml([["지급액", "지급액", None, "비고"], [1, 2, 3, "x"]])
        table = read_xlsx(workbook([("S", xml)]))
        self.assertEqual([c.name for c in table.columns], ["지급액", "지급액_2", "열 C", "비고"])
        self.assertEqual([c.letter for c in table.columns], ["A", "B", "C", "D"])
        self.assertEqual(table.rows[0][2], Decimal(3))

    def test_number_parsing_mixed_column(self):
        values = ["1,234,000", "₩1,234", "(12,000)", " 3000 ", "3.0E+3", "-", "abc", "1234원"]
        data = [str(i) for i in range(30)]  # pad so >=90% are numbers
        xml = sheet_xml([["값"]] + [[v] for v in values + data])
        table = read_xlsx(workbook([("S", xml)]))
        self.assertEqual(table.columns[0].kind, "number")
        got = [row[0] for row in table.rows[: len(values)]]
        self.assertEqual(got[0], Decimal("1234000"))
        self.assertEqual(got[1], Decimal("1234"))
        self.assertEqual(got[2], Decimal("-12000"))
        self.assertEqual(got[3], Decimal("3000"))
        self.assertEqual(got[4], Decimal("3000"))
        self.assertEqual(got[5], NotNumber("-"))
        self.assertEqual(got[6], NotNumber("abc"))
        self.assertEqual(got[7], Decimal("1234"))
        for value in got:
            self.assertNotIsInstance(value, float)
        # empty cell row is a fully blank row -> skipped; check with CSV where a sibling column keeps it
        csv_table = read_csv("k,값\na,1\nb,\nc,2\n".encode())
        self.assertEqual(csv_table.rows[1][1], None)
        self.assertEqual(csv_table.columns[1].kind, "number")

    def test_date_parsing_serial_and_text(self):
        xml = sheet_xml([["날짜"], [46086], ["2026-03-05"], ["2026.03.05"], ["2026/3/5"]], date_cols=(1,))
        table = read_xlsx(workbook([("S", xml)]))
        self.assertEqual(table.columns[0].kind, "date")
        self.assertEqual([r[0] for r in table.rows], [date(2026, 3, 5)] * 4)
        xml1904 = sheet_xml([["날짜"], [46086 - 1462]], date_cols=(1,))
        table1904 = read_xlsx(workbook([("S", xml1904)], date1904=True))
        self.assertEqual(table1904.rows[0][0], date(2026, 3, 5))
        # built-in date format id 14 (style index 2)
        builtin = '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>d</t></is></c></row><row r="2"><c r="A2" s="2"><v>46086</v></c></row></sheetData>'
        self.assertEqual(read_xlsx(workbook([("S", builtin)])).rows[0][0], date(2026, 3, 5))

    def test_column_kind_inference(self):
        nums = [[str(i)] for i in range(9)] + [["x"]]  # 90% numbers
        self.assertEqual(read_csv(("a\n" + "\n".join(r[0] for r in nums)).encode()).columns[0].kind, "number")
        mostly = [str(i) for i in range(8)] + ["x", "y"]  # 80%
        t = read_csv(("a\n" + "\n".join(mostly)).encode())
        self.assertEqual(t.columns[0].kind, "text")
        self.assertEqual(t.rows[0][0], "0")
        dates = [f"2026-01-{d:02d}" for d in range(1, 10)] + ["모름"]
        d = read_csv(("a\n" + "\n".join(dates)).encode())
        self.assertEqual(d.columns[0].kind, "date")
        self.assertEqual(d.rows[-1][0], NotDate("모름"))
        self.assertEqual(d.rows[0][0], date(2026, 1, 1))

    def test_leading_zero_codes_make_column_text(self):
        # 앞자리 0이 있는 코드가 하나라도 있으면 글자 열(숫자로 읽어 0101과 101이 합쳐지지 않게).
        values = ["101", "102", "0101", "103", "104", "105", "106", "107", "108", "109"]
        t = read_csv(("코드\n" + "\n".join(values)).encode())
        self.assertEqual(t.columns[0].kind, "text")
        self.assertEqual([r[0] for r in t.rows][:3], ["101", "102", "0101"])
        # 0, 0.5 같은 값은 코드로 보지 않는다.
        self.assertEqual(read_csv("a\n0\n0.5\n1\n2\n".encode()).columns[0].kind, "number")
        xml = sheet_xml([["코드"], [101], ["0102"], [103]])
        self.assertEqual(read_xlsx(workbook([("S", xml)])).columns[0].kind, "text")

    def test_cancel_check_called_and_not_masked(self):
        class Cancelled(RuntimeError):
            pass
        calls = []

        def cancel():
            calls.append(1)
            if len(calls) >= 1:  # 첫 확인(시작)에서 바로 취소
                raise Cancelled("x")
        content = ("a,b\n" + "\n".join(f"{i},{i}" for i in range(3000))).encode()
        with self.assertRaises(Cancelled):  # RuntimeError가 TABLE_FORMAT_UNSUPPORTED로 바뀌지 않는다
            read_table(content, file_name="a.csv", source_format="csv", sheet=None, header_row=1, cancel_check=cancel)
        xml = sheet_xml([["a"]] + [[i] for i in range(3000)])
        calls.clear()
        with self.assertRaises(Cancelled):
            read_table(workbook([("S", xml)]), file_name="a.xlsx", source_format="xlsx", sheet=None, header_row=1, cancel_check=cancel)
        # 취소 확인(작업 heartbeat = DB 쓰기)은 1초에 한 번까지만: 10만 행 읽기에서도 몇 번뿐이다.
        big = ("a,b,c\n" + "\n".join(f"{i},x{i},2026-01-01" for i in range(100_000))).encode()
        seen = []
        started = time.monotonic()
        read_table(big, file_name="a.csv", source_format="csv", sheet=None, header_row=1, cancel_check=lambda: seen.append(1))
        elapsed = time.monotonic() - started
        self.assertTrue(1 <= len(seen) <= elapsed + 2, (len(seen), elapsed))
        # 간격이 지나면 취소가 곧 전파된다(가짜 시계: 확인 자리 1번 = 0.1초).
        from unittest.mock import patch
        import daon2_user_api.table_reader as reader_module
        clock = {"now": 0.0}

        def tick():
            clock["now"] += 0.1
            return clock["now"]
        stamps = []

        def cancel_later():
            stamps.append(clock["now"])
            if clock["now"] >= 2.0:
                raise Cancelled("x")
        with patch.object(reader_module, "_cancel_clock", tick):
            with self.assertRaises(Cancelled):
                read_table(big, file_name="a.csv", source_format="csv", sheet=None, header_row=1, cancel_check=cancel_later)
        self.assertLessEqual(len(stamps), 4, stamps)
        self.assertLess(stamps[-1], 3.2)

    def test_csv_utf8_bom_and_tab(self):
        content = "﻿이름\t금액\t메모\n가\t1,000\t\"a,b\"\n나\t2000\tc\n".encode("utf-8")
        table = read_csv(content)
        self.assertEqual(table.source_format, "csv")
        self.assertIsNone(table.sheet)
        self.assertEqual([c.name for c in table.columns], ["이름", "금액", "메모"])
        self.assertEqual([c.letter for c in table.columns], [None, None, None])
        self.assertEqual(table.rows[0], ("가", Decimal(1000), "a,b"))
        self.assertEqual(table.row_numbers, (2, 3))

    def test_csv_cp949_headers(self):
        content = "이름,지급액\n홍길동,5000\n".encode("cp949")
        table = read_csv(content)
        self.assertEqual([c.name for c in table.columns], ["이름", "지급액"])
        self.assertEqual(table.rows[0], ("홍길동", Decimal(5000)))
        self.assertCode("TABLE_ENCODING_UNSUPPORTED", read_csv, b"a,b\n\xff\xff\xff,1\n")

    def test_limits_rows_columns_bytes(self):
        csv_rows = "a\n" + "\n".join(str(i) for i in range(11))
        self.assertCode("TABLE_TOO_LARGE", read_csv, csv_rows.encode(), limits=TableLimits(max_rows=10))
        self.assertEqual(len(read_csv(csv_rows.encode(), limits=TableLimits(max_rows=11)).rows), 11)
        self.assertCode("TABLE_TOO_LARGE", read_csv, ",".join("abcdef").encode(), limits=TableLimits(max_columns=5))
        self.assertCode("TABLE_TOO_LARGE", read_csv, b"a\n" + b"1\n" * 100, limits=TableLimits(max_bytes=50))
        xml = sheet_xml([["h"]] + [[i] for i in range(11)])
        self.assertCode("TABLE_TOO_LARGE", read_xlsx, workbook([("S", xml)]), limits=TableLimits(max_rows=10))
        wide = sheet_xml([[f"h{i}" for i in range(6)]])
        self.assertCode("TABLE_TOO_LARGE", read_xlsx, workbook([("S", wide)]), limits=TableLimits(max_columns=5))
        small = workbook([("S", sheet_xml([["h"], [1]]))])
        self.assertCode("TABLE_TOO_LARGE", read_xlsx, small, limits=TableLimits(max_bytes=len(small) - 1))

    def test_deadline_raises_timeout(self):
        xml = sheet_xml([["h"]] + [[i] for i in range(10)])
        self.assertCode("TABLE_TIMEOUT", read_xlsx, workbook([("S", xml)]), deadline=time.monotonic() - 1)
        self.assertCode("TABLE_TIMEOUT", read_csv, b"a\n1\n", deadline=time.monotonic() - 1)
        self.assertEqual(len(read_csv(b"a\n1\n", deadline=time.monotonic() + 60).rows), 1)

    def test_profile_has_no_cell_values(self):
        xml = sheet_xml([["이름", "지급액", "지급일"], ["비밀값ORANGE", 987654, 46086]], date_cols=(3,))
        table = read_xlsx(workbook([("S", xml)]))
        result = profile(table)
        self.assertEqual(result, {
            "columns": [{"name": "이름", "kind": "text"}, {"name": "지급액", "kind": "number"}, {"name": "지급일", "kind": "date"}],
            "row_count": 1,
        })
        dumped = json.dumps(result, ensure_ascii=False)
        for secret in ("비밀값ORANGE", "987654", "46086", "2026"):
            self.assertNotIn(secret, dumped)

    def test_sheet_not_found(self):
        content = workbook([("첫째", sheet_xml([["a"], [1]])), ("둘째", sheet_xml([["b"], [2]]))])
        self.assertEqual(list_sheets(content), ["첫째", "둘째"])
        self.assertEqual(read_xlsx(content).sheet, "첫째")
        self.assertEqual(read_xlsx(content, sheet="둘째").columns[0].name, "b")
        self.assertCode("TABLE_SHEET_NOT_FOUND", read_xlsx, content, sheet="셋째")

    # --- edge / hostile input ---

    def test_zip_bomb_decompressed_total_limited(self):
        padding = "<!-- " + "A" * 500_000 + " -->"
        xml = sheet_xml([["h"], [1]]) + padding
        content = workbook([("S", xml)])
        limits = TableLimits(max_bytes=100_000)
        self.assertLess(len(content), limits.max_bytes)
        self.assertCode("TABLE_TOO_LARGE", read_xlsx, content, limits=limits)

    def test_missing_sheet_part_and_bad_zip(self):
        content = workbook([("S", sheet_xml([["h"], [1]]))], skip=("xl/worksheets/sheet1.xml",))
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, content)
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, b"PK\x03\x04garbage")
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, b"not a zip")
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", list_sheets, b"a,b\n1,2\n")
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_table, b"a\n1\n", file_name="x", source_format="pdf", sheet=None, header_row=1)

    def test_doctype_and_entities_rejected(self):
        evil = '<!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;">]>'
        content = workbook([("S", "")], extra={
            "xl/worksheets/sheet1.xml": f'<?xml version="1.0"?>{evil}<worksheet xmlns="{NS}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&b;</t></is></c></row></sheetData></worksheet>'
        })
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, content)
        utf16 = f'<?xml version="1.0" encoding="UTF-16"?>{evil}<worksheet xmlns="{NS}"/>'.encode("utf-16")
        content16 = workbook([("S", "")], extra={"xl/worksheets/sheet1.xml": utf16})
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, content16)
        other = f'<?xml version="1.0" encoding="cp500"?><worksheet xmlns="{NS}"/>'.encode("ascii")
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, workbook([("S", "")], extra={"xl/worksheets/sheet1.xml": other}))

    def test_header_invalid(self):
        content = workbook([("S", sheet_xml([["a"], [1]]))])
        self.assertCode("TABLE_HEADER_INVALID", read_xlsx, content, header_row=5)
        self.assertCode("TABLE_HEADER_INVALID", read_xlsx, content, header_row=0)
        self.assertCode("TABLE_HEADER_INVALID", read_csv, b"\n\n", header_row=1)
        self.assertCode("TABLE_HEADER_INVALID", read_csv, b"a\n1\n", header_row=3)

    def test_shared_strings_and_sparse_rows(self):
        xml = ('<sheetData><row r="2"><c r="B2" t="s"><v>0</v></c><c r="D2" t="s"><v>1</v></c></row>'
               '<row r="4"><c r="B4" t="s"><v>2</v></c><c r="D4"><v>7</v></c><c r="Z4"><v>9</v></c></row>'
               '<row r="5"/><row r="9"><c r="D9" t="e"><v>#DIV/0!</v></c></row>'
               + "".join(f'<row r="{r}"><c r="D{r}"><v>{r}</v></c></row>' for r in range(10, 20)) + '</sheetData>')
        table = read_xlsx(workbook([("S", xml)], shared=["이름", "금액", "가"]), header_row=2)
        self.assertEqual([(c.name, c.letter, c.index) for c in table.columns], [("이름", "B", 1), ("열 C", "C", 2), ("금액", "D", 3)])
        self.assertEqual(table.row_numbers, (4, 9) + tuple(range(10, 20)))
        self.assertEqual(table.rows[0], ("가", None, Decimal(7)))
        self.assertEqual(table.rows[1][2], NotNumber("#DIV/0!"))
        bad_index = '<sheetData><row r="1"><c r="A1" t="s"><v>5</v></c></row></sheetData>'
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, workbook([("S", bad_index)], shared=["a"]))

    def test_rows_out_of_order_rejected(self):
        xml = '<sheetData><row r="1"><c r="A1"><v>1</v></c></row><row r="3"><c r="A3"><v>1</v></c></row><row r="2"><c r="A2"><v>1</v></c></row></sheetData>'
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, workbook([("S", xml)]))

    def test_number_text_bounds(self):
        rows = "a\n" + "\n".join(["1"] * 40 + ["1E+999999999", "9" * 200, "\"1,2,3\"", "--1"])
        table = read_csv(rows.encode())
        self.assertEqual(table.columns[0].kind, "number")
        self.assertEqual([r[0] for r in table.rows[-4:]], [NotNumber("1E+999999999"), NotNumber("9" * 200), NotNumber("1,2,3"), NotNumber("--1")])


    def test_row_element_flood_and_junk_outside_rows(self):
        flood = '<sheetData><row r="1"><c r="A1"><v>1</v></c>' + "<x/>" * 100_001 + "</row></sheetData>"
        self.assertCode("TABLE_TOO_LARGE", read_xlsx, workbook([("S", flood)]))
        junk = "<cols>" + "<col/>" * 5000 + '</cols><foo><row r="1"><c r="A1"><v>9</v></c></row></foo>' + sheet_xml([["h"], [1]])
        table = read_xlsx(workbook([("S", junk)]))
        self.assertEqual(table.rows, ((Decimal(1),),))

    def test_non_deflate_compression_rejected(self):
        content = workbook([("S", sheet_xml([["h"], [1]]))], compression=zipfile.ZIP_BZIP2)
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, content)

    def test_central_directory_bounds(self):
        content = bytearray(workbook([("S", sheet_xml([["h"], [1]]))]))
        eocd = bytes(content).rfind(b"PK\x05\x06")
        forged = bytes(content[:eocd + 12]) + (0xFFFFFFFF).to_bytes(4, "little") + bytes(content[eocd + 16:])
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, forged)
        zip64 = bytes(content[:eocd]) + b"PK\x06\x07" + b"\x00" * 16 + bytes(content[eocd:])
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, zip64)

    def test_header_name_length_capped(self):
        table = read_csv(("가" * 500 + ",b\n1,2\n").encode())
        self.assertEqual(table.columns[0].name, "가" * 200)


    # --- review fix round 1 ---

    def test_csv_header_row_is_physical_line(self):
        content = '"제목\n둘째줄"\n이름,금액\n홍,100\n'.encode()
        table = read_csv(content, header_row=3)
        self.assertEqual([c.name for c in table.columns], ["이름", "금액"])
        self.assertEqual(table.row_numbers, (4,))
        self.assertCode("TABLE_HEADER_INVALID", read_csv, content, header_row=2)
        cr_only = read_csv(b"t\ra,b\r1,2\r", header_row=2)
        self.assertEqual([c.name for c in cr_only.columns], ["a", "b"])
        self.assertEqual(cr_only.row_numbers, (3,))

    def test_csv_delimiter_detected_on_header_line(self):
        table = read_csv("월간 보고서\n이름\t금액\n홍\t100\n".encode(), header_row=2)
        self.assertEqual([c.name for c in table.columns], ["이름", "금액"])
        self.assertEqual(table.rows, (("홍", Decimal(100)),))

    def test_max_cells_limit(self):
        self.assertEqual(TableLimits().max_cells, 2_000_000)
        rows = [[f"h{c}" for c in range(5)]] + [[1] * 5 for _ in range(1000)]
        content = workbook([("S", sheet_xml(rows))])
        self.assertLess(len(content), 20_000)
        self.assertCode("TABLE_TOO_LARGE", read_xlsx, content, limits=TableLimits(max_cells=4999))
        self.assertEqual(len(read_xlsx(content, limits=TableLimits(max_cells=5000)).rows), 1000)
        csv_content = ("a,b\n" + "1,2\n" * 10).encode()
        self.assertCode("TABLE_TOO_LARGE", read_csv, csv_content, limits=TableLimits(max_cells=19))

    def test_time_and_duration_formats_stay_numbers(self):
        styles = ('<styleSheet xmlns="%s"><numFmts count="3"><numFmt numFmtId="164" formatCode="[h]:mm:ss"/>'
                  '<numFmt numFmtId="165" formatCode="mm:ss.0"/><numFmt numFmtId="166" formatCode="yyyy\\-mm"/></numFmts>'
                  '<cellXfs count="7"><xf numFmtId="0"/><xf numFmtId="164"/><xf numFmtId="165"/><xf numFmtId="18"/>'
                  '<xf numFmtId="46"/><xf numFmtId="166"/><xf numFmtId="22"/></cellXfs></styleSheet>') % NS
        header = "".join(f'<c r="{_letter(i)}1" t="inlineStr"><is><t>h{i}</t></is></c>' for i in range(1, 7))
        data = "".join(f'<c r="{_letter(i)}2" s="{i}"><v>46086.5</v></c>' for i in range(1, 7))
        xml = f'<sheetData><row r="1">{header}</row><row r="2">{data}</row></sheetData>'
        table = read_xlsx(workbook([("S", xml)], extra={"xl/styles.xml": styles}))
        self.assertEqual([c.kind for c in table.columns], ["number", "number", "number", "number", "date", "date"])
        self.assertEqual(table.rows[0][:4], (Decimal("46086.5"),) * 4)
        self.assertEqual(table.rows[0][4:], (date(2026, 3, 5), date(2026, 3, 5)))

    def test_cell_reference_row_mismatch_rejected(self):
        xml = '<sheetData><row r="1"><c r="A1"><v>1</v></c></row><row r="2"><c r="A3"><v>1</v></c></row></sheetData>'
        self.assertCode("TABLE_FORMAT_UNSUPPORTED", read_xlsx, workbook([("S", xml)]))

    def test_csv_field_over_size_limit_is_too_large(self):
        self.assertCode("TABLE_TOO_LARGE", read_csv, b"a,b\n" + b"x" * 200_000 + b",1\n")


if __name__ == "__main__":
    unittest.main()
