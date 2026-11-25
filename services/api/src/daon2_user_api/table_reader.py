"""Bounded table reader for uploaded XLSX and CSV files (WO-N9 데이터 집계).

Untrusted input. XLSX parts are streamed with a pull parser and completed rows
are discarded immediately; only the header span of each data row is kept.
Limits: input bytes, decompressed bytes (max_bytes x 4), rows, columns,
XML nesting depth and an optional monotonic deadline. No formula evaluation,
no external resolution, no float arithmetic (Decimal only).

The question-indexing reader ``xlsx_source.read_xlsx`` keeps its own small
limits; this module only borrows its built-in number format table.
"""
from __future__ import annotations

import csv
import io
import posixpath
import re
import time
import zipfile
import zlib
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from xml.etree import ElementTree as ET

from .xlsx_source import _BUILTIN_FORMATS

_DOC_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_MAX_ZIP_MEMBERS = 4096
_MAX_XML_DEPTH = 64
_MAX_EXCEL_COLUMN = 16384
_MAX_EXCEL_ROW = 1048576
_DEADLINE_EVERY = 1000
_MAX_KEPT_ELEMENTS = 100_000  # elements retained inside one open <row> or <si>
_MAX_STRUCTURE_RECORDS = 200_000  # sheets / relationships / styles records
_MAX_CENTRAL_DIRECTORY = 4 * 1024 * 1024
_MAX_HEADER_NAME = 200
_ALLOWED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
_CHUNK = 65536
_SAFE_XML_ENCODINGS = {'utf-8', 'utf8', 'utf-16', 'utf-16le', 'utf-16be', 'us-ascii', 'ascii', 'iso-8859-1', 'latin-1', 'latin1'}
# ko-KR/ja-JP/zh locales render these built-in ids as dates; they are absent
# from the locale-neutral table, so classify them explicitly.
_LOCALE_DATE_FORMAT_IDS = (set(range(27, 37)) | set(range(50, 59))) - {32, 33, 55, 56}  # ko-KR 32/33/55/56 are times


@dataclass(frozen=True)
class TableLimits:
    max_bytes: int = 20 * 1024 * 1024
    max_rows: int = 100_000
    max_columns: int = 100
    max_cells: int = 2_000_000  # stored cells = kept rows x kept columns


class TableReadError(Exception):
    """``code`` is one of TABLE_TOO_LARGE, TABLE_FORMAT_UNSUPPORTED,
    TABLE_SHEET_NOT_FOUND, TABLE_HEADER_INVALID, TABLE_ENCODING_UNSUPPORTED,
    TABLE_TIMEOUT. The message never contains cell values."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Column:
    name: str
    letter: str | None  # XLSX column letter; None for CSV
    index: int  # 0-based source column position (A=0, first CSV field=0)
    kind: Literal['date', 'number', 'text']


@dataclass(frozen=True)
class NotNumber:
    raw: str


@dataclass(frozen=True)
class NotDate:
    raw: str


@dataclass(frozen=True)
class Table:
    file_name: str
    source_format: Literal['xlsx', 'csv']
    sheet: str | None
    header_row: int
    columns: tuple[Column, ...]
    rows: tuple[tuple[object, ...], ...]
    row_numbers: tuple[int, ...]


def _fail(code: str):
    raise TableReadError(code)


def _check_deadline(deadline):
    if deadline is not None and time.monotonic() > deadline:
        _fail('TABLE_TIMEOUT')


def _letter(index0: int) -> str:
    col = index0 + 1; letters = ''
    while col:
        col, digit = divmod(col - 1, 26); letters = chr(65 + digit) + letters
    return letters


# ---------------------------------------------------------------- values

_NUMBER = re.compile(r'(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]*)?(?:[eE][+-]?[0-9]{1,3})?|\.[0-9]+(?:[eE][+-]?[0-9]{1,3})?')
_DATE_TEXT = re.compile(r'([0-9]{4})([-./])([0-9]{1,2})\2([0-9]{1,2})\.?')
_KOREAN_DATE = re.compile(r'([0-9]{4})\s*년\s*([0-9]{1,2})\s*월\s*([0-9]{1,2})\s*일')
_MAX_NUMBER_TEXT = 64


def parse_number(text: str) -> Decimal | None:
    """Return a Decimal for accounting-style numeric text, else None."""
    if len(text) > _MAX_NUMBER_TEXT:
        return None
    value = text.strip()
    negative = False
    if len(value) >= 2 and value[0] == '(' and value[-1] == ')':
        negative = True; value = value[1:-1].strip()
    sign = ''
    if value[:1] in {'+', '-'}:
        sign = value[0]; value = value[1:].strip()
    if value[:1] in {'₩', '￦'}:
        value = value[1:].strip()
    elif value.endswith('원'):
        value = value[:-1].strip()
    if not sign and value[:1] in {'+', '-'}:  # ₩-1,234
        sign = value[0]; value = value[1:].strip()
    if not _NUMBER.fullmatch(value) or (negative and sign):
        return None
    try:
        result = Decimal(value.replace(',', ''))
    except InvalidOperation:
        return None
    if not result.is_finite():
        return None
    if sign == '-' or negative:
        result = -result
    return result


def _valid_date(year, month, day):
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def parse_date_text(text: str) -> date | None:
    value = text.strip()
    if len(value) > 32:
        return None
    match = _DATE_TEXT.fullmatch(value)
    if match:
        return _valid_date(match[1], match[3], match[4])
    match = _KOREAN_DATE.fullmatch(value)
    if match:
        return _valid_date(match[1], match[2], match[3])
    return None


def _serial_date(serial: Decimal, date1904: bool) -> date | None:
    if serial < 0 or serial >= (2957004 if date1904 else 2958466):
        return None  # compared as Decimal before any int conversion
    days = int(serial)
    if date1904:
        return date(1904, 1, 1) + timedelta(days=days)
    if days < 1 or days == 60:  # 1900-01-00 and the fictitious 1900-02-29
        return None
    return date(1899, 12, 31) + timedelta(days=days if days < 60 else days - 1)


def _infer_and_convert(raw_rows, width, deadline):
    """raw values: None, str, Decimal (typed numeric cell) or date."""
    kinds = []
    for j in range(width):
        nonempty = numbers = dates = 0
        _check_deadline(deadline)
        for i, row in enumerate(raw_rows):
            if i % _DEADLINE_EVERY == 0:
                _check_deadline(deadline)
            value = row[j]
            if value is None:
                continue
            nonempty += 1
            if isinstance(value, Decimal):
                numbers += 1
            elif isinstance(value, date):
                dates += 1
            elif parse_number(value) is not None:
                numbers += 1
            elif parse_date_text(value) is not None:
                dates += 1
        if nonempty and numbers * 10 >= nonempty * 9:
            kinds.append('number')
        elif nonempty and dates * 10 >= nonempty * 9:
            kinds.append('date')
        else:
            kinds.append('text')
    for i, row in enumerate(raw_rows):
        if i % _DEADLINE_EVERY == 0:
            _check_deadline(deadline)
        out = []
        for value, kind in zip(row, kinds):
            if value is None:
                out.append(None)
            elif kind == 'number':
                if isinstance(value, Decimal):
                    out.append(value)
                elif isinstance(value, date):
                    out.append(NotNumber(value.isoformat()))
                else:
                    parsed = parse_number(value)
                    out.append(parsed if parsed is not None else NotNumber(value))
            elif kind == 'date':
                if isinstance(value, date):
                    out.append(value)
                elif isinstance(value, Decimal):
                    out.append(NotDate(str(value)))
                else:
                    parsed = parse_date_text(value)
                    out.append(parsed if parsed is not None else NotDate(value))
            else:
                out.append(value.isoformat() if isinstance(value, date) else str(value))
        raw_rows[i] = tuple(out)  # in place: never two full copies
    return kinds, raw_rows


def _header_names(raw_header, first, width):
    names = []; used = set()
    bases = []
    for j in range(width):
        value = raw_header[j]
        text = value.isoformat() if isinstance(value, date) else ('' if value is None else str(value))
        text = ' '.join(text.split())[:_MAX_HEADER_NAME]
        bases.append(text or f'열 {_letter(first + j)}')
    for base in bases:
        name = base; n = 1
        while name in used:
            n += 1; name = f'{base}_{n}'
        used.add(name); names.append(name)
    return names


def _build_table(*, deadline, file_name, source_format, sheet, header_row, raw_header, first, raw_rows, row_numbers, letters):
    width = len(raw_header)
    names = _header_names(raw_header, first, width)
    kinds, rows = _infer_and_convert(raw_rows, width, deadline)
    columns = tuple(
        Column(name=names[j], letter=_letter(first + j) if letters else None, index=first + j, kind=kinds[j])
        for j in range(width)
    )
    return Table(file_name=file_name, source_format=source_format, sheet=sheet, header_row=header_row,
                 columns=columns, rows=tuple(rows), row_numbers=tuple(row_numbers))


def _admit_row(kept, width, limits):
    """Checked while streaming, before the row is stored."""
    if kept >= limits.max_rows or (kept + 1) * width > limits.max_cells:
        _fail('TABLE_TOO_LARGE')


def _header_span(raw_header_cells, limits):
    """raw_header_cells: iterable of (index0, value). Returns (first, width)."""
    first = last = None
    for j, value in raw_header_cells:
        if value is not None:
            first = j if first is None else min(first, j)
            last = j if last is None else max(last, j)
    if first is None:
        _fail('TABLE_HEADER_INVALID')
    width = last - first + 1
    if width > limits.max_columns:
        _fail('TABLE_TOO_LARGE')
    return first, width


def _clean(value):
    if isinstance(value, str) and not value.strip():
        return None
    return value


# ---------------------------------------------------------------- XLSX

class _Budget:
    def __init__(self, limit):
        self.limit = limit; self.used = 0

    def consume(self, amount):
        self.used += amount
        if self.used > self.limit:
            _fail('TABLE_TOO_LARGE')


def _local(tag):
    return tag.rsplit('}', 1)[-1]


_XML_DECL_ENCODING = re.compile(rb'^\s*<\?xml[^>]*encoding\s*=\s*["\']([A-Za-z0-9._-]+)["\']')


def _xml_events(stream, budget, deadline):
    """Yield (event, element, depth) with DOCTYPE/ENTITY rejected.

    NUL bytes are removed only for the scan so UTF-16 markup is visible; the
    parser receives the original bytes. Declared encodings outside an
    ASCII-compatible/UTF-16 allowlist are rejected so the scan cannot be
    bypassed with an EBCDIC-like 8-bit codec.
    """
    parser = ET.XMLPullParser(events=('start', 'end'))
    tail = b''; first = True; depth = 0
    while True:
        chunk = stream.read(_CHUNK)
        if not chunk:
            break
        budget.consume(len(chunk))
        _check_deadline(deadline)
        scan = tail + chunk.replace(b'\x00', b'')
        if first:
            first = False
            head = scan.lstrip(b'\xef\xbb\xbf\xff\xfe')
            match = _XML_DECL_ENCODING.match(head)
            if match and match[1].decode('ascii').lower() not in _SAFE_XML_ENCODINGS:
                _fail('TABLE_FORMAT_UNSUPPORTED')
        lowered = scan.lower()
        if b'<!doctype' in lowered or b'<!entity' in lowered:
            _fail('TABLE_FORMAT_UNSUPPORTED')
        tail = lowered[-16:]
        parser.feed(chunk)
        for event, elem in parser.read_events():
            if event == 'start':
                depth += 1
                if depth > _MAX_XML_DEPTH:
                    _fail('TABLE_FORMAT_UNSUPPORTED')
                yield event, elem, depth
            else:
                yield event, elem, depth
                depth -= 1
    parser.close()
    for event, elem in parser.read_events():  # pragma: no cover - close() flushes nothing new for well-formed input
        yield event, elem, depth


def _precheck_central_directory(content):
    """Bound zipfile's central-directory parse before it allocates ZipInfos.

    Uses the same end-record search as zipfile (last signature within the
    trailing comment window). ZIP64 is refused: a sub-limit workbook never
    needs it, and its records would override the sizes checked here.
    """
    eocd = content.rfind(b'PK\x05\x06', max(0, len(content) - 65557))
    if eocd < 0 or len(content) - eocd < 22:
        _fail('TABLE_FORMAT_UNSUPPORTED')
    entries = int.from_bytes(content[eocd + 10:eocd + 12], 'little')
    size = int.from_bytes(content[eocd + 12:eocd + 16], 'little')
    if eocd >= 20 and content[eocd - 20:eocd - 16] == b'PK\x06\x07':
        _fail('TABLE_FORMAT_UNSUPPORTED')
    if entries == 0xFFFF or size == 0xFFFFFFFF or entries > _MAX_ZIP_MEMBERS or size > _MAX_CENTRAL_DIRECTORY:
        _fail('TABLE_FORMAT_UNSUPPORTED')


class _Package:
    def __init__(self, content, limits, deadline):
        if len(content) > limits.max_bytes:
            _fail('TABLE_TOO_LARGE')
        if not content.startswith(b'PK\x03\x04'):
            _fail('TABLE_FORMAT_UNSUPPORTED')
        _precheck_central_directory(content)
        self.deadline = deadline
        self.budget = _Budget(limits.max_bytes * 4)
        self.archive = zipfile.ZipFile(io.BytesIO(content))
        infos = self.archive.infolist()
        if len(infos) > _MAX_ZIP_MEMBERS:
            _fail('TABLE_FORMAT_UNSUPPORTED')
        self.members = {}
        for info in infos:
            # Encrypted members and non-deflate codecs (bzip2/lzma decompress
            # without an output bound inside zipfile) are refused.
            if info.filename in self.members or info.flag_bits & 0x1 or info.compress_type not in _ALLOWED_COMPRESSION:
                _fail('TABLE_FORMAT_UNSUPPORTED')
            self.members[info.filename] = info

    def events(self, name):
        info = self.members.get(name)
        if info is None or info.is_dir():
            _fail('TABLE_FORMAT_UNSUPPORTED')
        # Declared size first (cheap reject), actual streamed bytes always.
        if info.file_size > self.budget.limit - self.budget.used:
            _fail('TABLE_TOO_LARGE')
        with self.archive.open(info) as stream:
            yield from _xml_events(stream, self.budget, self.deadline)

    def close(self):
        self.archive.close()


def _simple_records(package, name, wanted):
    """Small structural parts: collect (local tag, attrs, parent local tag).

    Every finished element is detached from its parent, so a part padded with
    millions of empty elements cannot accumulate a tree in memory.
    """
    records = []; stack = []
    for event, elem, _ in package.events(name):
        if event == 'start':
            stack.append(elem)
            continue
        stack.pop()
        tag = _local(elem.tag)
        if tag in wanted:
            records.append((tag, dict(elem.attrib), _local(stack[-1].tag) if stack else None))
            if len(records) > _MAX_STRUCTURE_RECORDS:
                _fail('TABLE_FORMAT_UNSUPPORTED')
        if stack:
            stack[-1].remove(elem)
        elem.clear()
    return records


def _workbook(package):
    records = _simple_records(package, 'xl/workbook.xml', {'sheet', 'workbookPr'})
    date1904 = any(tag == 'workbookPr' and attrs.get('date1904', '0').lower() in {'1', 'true'} for tag, attrs, _ in records)
    sheets = [(attrs.get('name'), attrs.get(f'{{{_DOC_REL}}}id')) for tag, attrs, parent in records if tag == 'sheet' and parent == 'sheets']
    if not sheets or any(not isinstance(name, str) or not name for name, _ in sheets):
        _fail('TABLE_FORMAT_UNSUPPORTED')
    return date1904, sheets


def _sheet_target(package, rid):
    rels = _simple_records(package, 'xl/_rels/workbook.xml.rels', {'Relationship'})
    for _, attrs, _ in rels:
        if attrs.get('Id') != rid or not rid:
            continue
        target = attrs.get('Target', '')
        if attrs.get('TargetMode', 'Internal') != 'Internal' or not target or attrs.get('Type') != f'{_DOC_REL}/worksheet':
            _fail('TABLE_FORMAT_UNSUPPORTED')
        resolved = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('xl', target))
        if resolved.startswith('../') or resolved == '..' or resolved not in package.members:
            _fail('TABLE_FORMAT_UNSUPPORTED')
        return resolved
    _fail('TABLE_FORMAT_UNSUPPORTED')


def _is_date_format(ident, code):
    """True only when the format shows a calendar date (y, d or month m).

    Time/duration-only formats (h:mm, mm:ss, [h]:mm:ss, AM/PM) keep the value
    a number. Excel reads m as minutes right after an h token or right before
    an s token; any other m is a month.
    """
    if ident in _LOCALE_DATE_FORMAT_IDS:
        return True
    if not code or code == 'General':
        return False
    tokens = re.sub(r'"[^"]*"|\\.|\[[^]]*\]|am/pm|a/p', '', code.lower())
    runs = [match[0] for match in re.finditer(r'([a-z])\1*', tokens)]  # 'mmss' -> mm, ss
    for index, run in enumerate(runs):
        if run[0] in {'y', 'd'}:
            return True
        if run[0] == 'm':
            after_hour = index > 0 and runs[index - 1][0] == 'h'
            before_second = index + 1 < len(runs) and runs[index + 1][0] == 's'
            if not (after_hour or before_second):
                return True
    return False


def _date_styles(package):
    """Return a list: cellXfs index -> True when its number format is a date."""
    if 'xl/styles.xml' not in package.members:
        return []
    records = _simple_records(package, 'xl/styles.xml', {'numFmt', 'xf'})
    formats = dict(_BUILTIN_FORMATS)
    for tag, attrs, parent in records:
        if tag == 'numFmt' and parent == 'numFmts':
            ident = attrs.get('numFmtId', '')
            if ident.isdigit() and len(ident) <= 6:
                formats[int(ident)] = attrs.get('formatCode', '')
    result = []
    for tag, attrs, parent in records:
        if tag == 'xf' and parent == 'cellXfs':
            ident = attrs.get('numFmtId', '0')
            ident = int(ident) if ident.isdigit() and len(ident) <= 6 else 0
            result.append(_is_date_format(ident, formats.get(ident)))
    return result


def _rich_text(elem):
    """Concatenate <t> of a <si>/<is>, skipping phonetic runs (rPh)."""
    parts = []
    for child in elem:
        tag = _local(child.tag)
        if tag == 't':
            parts.append(child.text or '')
        elif tag == 'r':
            for node in child:
                if _local(node.tag) == 't':
                    parts.append(node.text or '')
    return ''.join(parts)


def _shared_strings(package, max_count):
    if 'xl/sharedStrings.xml' not in package.members:
        return []
    strings = []; stack = []; in_si = False; kept = 0
    for event, elem, depth in package.events('xl/sharedStrings.xml'):
        if event == 'start':
            stack.append(elem)
            if in_si:
                kept += 1
                if kept > _MAX_KEPT_ELEMENTS:
                    _fail('TABLE_TOO_LARGE')
            elif depth == 2 and _local(elem.tag) == 'si':
                in_si = True; kept = 0
            continue
        stack.pop()
        if in_si and depth > 2:
            continue  # part of the open <si>; released with it
        if in_si:
            in_si = False
            strings.append(_rich_text(elem))
            if len(strings) > max_count:
                _fail('TABLE_TOO_LARGE')
        if stack:
            stack[-1].remove(elem)
        elem.clear()
    return strings


_CELL_REF = re.compile(r'([A-Z]{1,3})([0-9]{1,7})')
_DECIMAL_TEXT = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]{1,3})?')


def _xlsx_value(cell, strings, date_styles, date1904):
    kind = cell.get('t', 'n'); raw = None; inline = None
    for child in cell:
        tag = _local(child.tag)
        if tag == 'v':
            raw = child.text
        elif tag == 'is':
            inline = _rich_text(child)
    if kind == 's':
        if raw is None or not raw.strip().isdigit() or len(raw) > 12:
            _fail('TABLE_FORMAT_UNSUPPORTED')
        index = int(raw)
        if index >= len(strings):
            _fail('TABLE_FORMAT_UNSUPPORTED')
        return _clean(strings[index])
    if kind == 'inlineStr':
        return _clean(inline)
    if kind == 'b':
        return {'1': 'TRUE', '0': 'FALSE'}.get(raw, _clean(raw))
    if kind in {'str', 'e'}:
        return _clean(raw)
    if kind == 'd':
        if raw is None:
            return None
        parsed = None
        try:
            parsed = date.fromisoformat(raw.strip()[:10])
        except ValueError:
            pass
        return parsed if parsed is not None else _clean(raw)
    if kind != 'n':
        return _clean(raw)
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    if len(text) > 128 or not _DECIMAL_TEXT.fullmatch(text):
        return text  # odd numeric text is kept as text -> NotNumber later
    value = Decimal(text)
    style = cell.get('s', '0')
    style = int(style) if style.isdigit() and len(style) <= 6 else 0
    if style < len(date_styles) and date_styles[style]:
        parsed = _serial_date(value, date1904)
        return parsed if parsed is not None else text
    return value


def _column_index(ref, previous, row_number):
    if ref is None:
        return previous + 1
    match = _CELL_REF.fullmatch(ref)
    if not match or int(match[2]) != row_number:
        _fail('TABLE_FORMAT_UNSUPPORTED')
    col = 0
    for letter in match[1]:
        col = col * 26 + ord(letter) - 64
    return col - 1


def _read_xlsx(content, *, file_name, sheet, header_row, limits, deadline):
    package = _Package(content, limits, deadline)
    try:
        date1904, sheets = _workbook(package)
        if sheet is None:
            name, rid = sheets[0]
        else:
            match = next((item for item in sheets if item[0] == sheet), None)
            if match is None:
                _fail('TABLE_SHEET_NOT_FOUND')
            name, rid = match
        target = _sheet_target(package, rid)
        date_styles = _date_styles(package)
        strings = _shared_strings(package, limits.max_rows * limits.max_columns + 1024)

        header = None; first = width = 0
        raw_rows = []; row_numbers = []
        last_row = 0; seen = 0
        stack = []; in_row = False; kept = 0
        for event, elem, depth in package.events(target):
            if event == 'start':
                stack.append(elem)
                if in_row:
                    kept += 1
                    if kept > _MAX_KEPT_ELEMENTS:
                        _fail('TABLE_TOO_LARGE')
                elif depth == 3 and _local(elem.tag) == 'row' and _local(stack[1].tag) == 'sheetData':
                    in_row = True; kept = 0
                continue
            stack.pop()
            if in_row and depth > 3:
                continue  # inside the open data row; released with the row
            parent = stack[-1] if stack else None
            if in_row:
                in_row = False
                seen += 1
                if seen % _DEADLINE_EVERY == 0:
                    _check_deadline(deadline)
                ref = elem.get('r')
                if ref is None:
                    row_number = last_row + 1
                else:
                    if not ref.isdigit() or len(ref) > 7:
                        _fail('TABLE_FORMAT_UNSUPPORTED')
                    row_number = int(ref)
                if not last_row < row_number <= _MAX_EXCEL_ROW:
                    _fail('TABLE_FORMAT_UNSUPPORTED')
                last_row = row_number
                if row_number >= header_row:
                    if header is None and row_number > header_row:
                        _fail('TABLE_HEADER_INVALID')
                    cells = {}; previous = -1
                    for cell in elem:
                        if _local(cell.tag) != 'c':
                            continue
                        col = _column_index(cell.get('r'), previous, row_number)
                        if col <= previous or col >= _MAX_EXCEL_COLUMN:
                            _fail('TABLE_FORMAT_UNSUPPORTED')
                        previous = col
                        if header is not None and not first <= col < first + width:
                            continue  # outside the header span: never stored
                        cells[col] = _xlsx_value(cell, strings, date_styles, date1904)
                    if header is None:
                        first, width = _header_span(cells.items(), limits)
                        header = [cells.get(first + j) for j in range(width)]
                    else:
                        values = tuple(cells.get(first + j) for j in range(width))
                        if any(value is not None for value in values):
                            _admit_row(len(raw_rows), width, limits)
                            raw_rows.append(values); row_numbers.append(row_number)
                parent.remove(elem); elem.clear()
            elif parent is not None:
                # Anything finished outside a data row (cols, mergeCells, junk) is dropped.
                parent.remove(elem); elem.clear()
        if header is None:
            _fail('TABLE_HEADER_INVALID')
        _check_deadline(deadline)
        return _build_table(deadline=deadline, file_name=file_name, source_format='xlsx', sheet=name, header_row=header_row,
                            raw_header=header, first=first, raw_rows=raw_rows, row_numbers=row_numbers, letters=True)
    finally:
        package.close()


# ---------------------------------------------------------------- CSV

def _decode_csv(content):
    try:
        return content.decode('utf-8-sig')
    except UnicodeDecodeError:
        pass
    try:
        return content.decode('cp949')
    except UnicodeDecodeError:
        _fail('TABLE_ENCODING_UNSUPPORTED')


def _physical_line(text, number, deadline):
    """The number-th physical line, split exactly as csv.reader counts lines."""
    stream = io.StringIO(text, newline='')
    for index in range(1, number + 1):
        line = stream.readline()
        if not line:
            return None
        if index % _DEADLINE_EVERY == 0:
            _check_deadline(deadline)
    return line


def _read_csv(content, *, file_name, header_row, limits, deadline):
    if len(content) > limits.max_bytes:
        _fail('TABLE_TOO_LARGE')
    text = _decode_csv(content)
    header_line = _physical_line(text, header_row, deadline)
    if header_line is None:
        _fail('TABLE_HEADER_INVALID')
    delimiter = '	' if header_line.count('	') > header_line.count(',') else ','
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter)
    header = None; first = width = 0
    raw_rows = []; row_numbers = []
    record = 0; line_after = 0
    try:
        for fields in reader:
            record += 1
            # header_row and row_numbers are both physical line numbers: a
            # record spanning several lines is numbered by its first line.
            start_line = line_after + 1
            line_after = reader.line_num
            if record % _DEADLINE_EVERY == 0:
                _check_deadline(deadline)
            if header is None:
                if line_after < header_row:
                    continue
                if start_line != header_row:
                    _fail('TABLE_HEADER_INVALID')  # header line is inside a multi-line record
                first, width = _header_span(((j, _clean(value)) for j, value in enumerate(fields)), limits)
                header = [_clean(fields[first + j]) for j in range(width)]
                continue
            values = tuple(_clean(fields[first + j]) if first + j < len(fields) else None for j in range(width))
            if any(value is not None for value in values):
                _admit_row(len(raw_rows), width, limits)
                raw_rows.append(values); row_numbers.append(start_line)
    except csv.Error as error:
        if 'field larger than field limit' in str(error):
            _fail('TABLE_TOO_LARGE')
        raise
    if header is None:
        _fail('TABLE_HEADER_INVALID')
    _check_deadline(deadline)
    return _build_table(deadline=deadline, file_name=file_name, source_format='csv', sheet=None, header_row=header_row,
                        raw_header=header, first=first, raw_rows=raw_rows, row_numbers=row_numbers, letters=False)


# ---------------------------------------------------------------- public

_PARSE_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, ET.ParseError, OSError, EOFError, ValueError,
                 KeyError, IndexError, RuntimeError, NotImplementedError, UnicodeError, zlib.error, csv.Error)


def list_sheets(content: bytes) -> list[str]:
    """Sheet names of an XLSX workbook, in workbook order."""
    if not isinstance(content, (bytes, bytearray)):
        _fail('TABLE_FORMAT_UNSUPPORTED')
    try:
        package = _Package(bytes(content), TableLimits(), None)
        try:
            _, sheets = _workbook(package)
            return [name for name, _ in sheets]
        finally:
            package.close()
    except TableReadError:
        raise
    except _PARSE_ERRORS:
        _fail('TABLE_FORMAT_UNSUPPORTED')


def read_table(content: bytes, *, file_name: str, source_format: str, sheet: str | None, header_row: int,
               limits: TableLimits = TableLimits(), deadline: float | None = None) -> Table:
    if not isinstance(content, (bytes, bytearray)) or source_format not in {'xlsx', 'csv'}:
        _fail('TABLE_FORMAT_UNSUPPORTED')
    if isinstance(header_row, bool) or not isinstance(header_row, int) or not 1 <= header_row <= _MAX_EXCEL_ROW:
        _fail('TABLE_HEADER_INVALID')
    _check_deadline(deadline)
    content = bytes(content)
    try:
        if source_format == 'xlsx':
            return _read_xlsx(content, file_name=file_name, sheet=sheet, header_row=header_row, limits=limits, deadline=deadline)
        return _read_csv(content, file_name=file_name, header_row=header_row, limits=limits, deadline=deadline)
    except TableReadError:
        raise
    except _PARSE_ERRORS:
        _fail('TABLE_FORMAT_UNSUPPORTED')


def profile(table: Table) -> dict:
    """Column names/kinds and row count only; never cell values."""
    return {
        'columns': [{'name': column.name, 'kind': column.kind} for column in table.columns],
        'row_count': len(table.rows),
    }
