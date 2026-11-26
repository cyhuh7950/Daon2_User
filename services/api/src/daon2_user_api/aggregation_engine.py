"""Aggregation engine for WO-N9 데이터 집계.

Filter -> group (incl. calendar month) -> count/sum/avg -> previous-month
growth -> sort/limit, with per-cell evidence (exact original row ranges).

Numbers are Decimal only. Sums are exact (an inexact sum is reported as not
computable rather than silently rounded); averages and growth rates are
divided with 28 significant digits. Display strings round half up to one
decimal place; stored ``value`` strings keep the exact/divided Decimal.

Row tuples are indexed by POSITION in ``Table.columns``; ``Column.index`` is
the original sheet position and is used only through ``Column.letter``.
"""
from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from datetime import date
from fractions import Fraction
from decimal import (ROUND_HALF_EVEN, ROUND_HALF_UP, Context, Decimal, DivisionByZero, Inexact,
                     InvalidOperation, Overflow)

from .table_reader import Column, NotDate, NotNumber, Table, parse_number, throttled_cancel_check

_SPEC_INVALID = 'AGGREGATION_SPEC_INVALID'
_TOO_MANY_GROUPS = 'AGGREGATION_TOO_MANY_GROUPS'
_DEADLINE_EVERY = 1000
_EXACT = Context(prec=1000, rounding=ROUND_HALF_EVEN, traps=[Inexact, InvalidOperation, Overflow])
_WIDE = Context(prec=5000, rounding=ROUND_HALF_UP, traps=[InvalidOperation, Overflow])
_DIV = Context(prec=28, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow])
_PLAIN_SHEET = re.compile(r'[^\W\d]\w*')
# Names Excel would read as a cell reference (A1, XFD100, R1C1, R, C) must be quoted.
_REF_LIKE_SHEET = re.compile(r'[A-Za-z]{1,3}[0-9]+|[Rr][0-9]*[Cc][0-9]*|[RrCc]')

_REASON_NO_NUMBER = '숫자 값 없음'
_REASON_PRECISION = '정밀도 초과'
_REASON_NO_PREVIOUS = '전월 자료 없음'
_REASON_PREVIOUS_FAILED = '전월 값 계산 불가'
_REASON_PREVIOUS_ZERO = '전월 값 0'

_FUNC_LABEL = {'count': '건수', 'sum': '합계', 'avg': '평균'}
_OP_SYMBOL = {'eq': '=', 'ne': '≠', 'gt': '>', 'gte': '≥', 'lt': '<', 'lte': '≤'}


class AggregationTimeout(Exception):
    """The monotonic deadline passed during aggregation."""


def _invalid():
    raise ValueError(_SPEC_INVALID)


def _check_deadline(deadline, cancel_check=None):
    if deadline is not None and time.monotonic() > deadline:
        raise AggregationTimeout('AGGREGATION_TIMEOUT')
    if cancel_check is not None:
        cancel_check()  # the job's cancellation propagates unchanged


# ---------------------------------------------------------------- display

def _plain(value: Decimal) -> str:
    return format(value, 'f')


def _ratio_text(value: Decimal) -> str:
    """Divided results (avg, growth): trailing zeros removed, never exponent form."""
    return format(value.normalize(_WIDE), 'f')


def _grouped(value: Decimal) -> str:
    return format(value, ',f')


def _round1_exact(numerator: Decimal, denominator: Decimal) -> Decimal:
    """numerator / denominator rounded half up (away from zero) to one
    decimal place, computed from the exact fraction (no prior rounding)."""
    tenths = Fraction(numerator) * 10 / Fraction(denominator)
    magnitude = abs(tenths)
    rounded = (2 * magnitude.numerator + magnitude.denominator) // (2 * magnitude.denominator)  # floor(x + 1/2)
    sign = '-' if tenths < 0 and rounded else ''  # no '-0.0'
    return Decimal(f'{sign}{rounded // 10}.{rounded % 10}')


def _month_text(ym) -> str:
    return f'{ym[0]:04d}-{ym[1]:02d}'


def _value_text(value) -> tuple[str | None, str]:
    """Original cell value -> (stored value, display)."""
    if value is None:
        return None, '(빈칸)'
    if isinstance(value, Decimal):
        return _plain(value), _grouped(value)
    if isinstance(value, date):
        return value.isoformat(), value.isoformat()
    if isinstance(value, (NotNumber, NotDate)):
        return value.raw, value.raw
    return str(value), str(value)


# ---------------------------------------------------------------- ranges

def _quote_sheet(sheet: str) -> str:
    if _PLAIN_SHEET.fullmatch(sheet) and not _REF_LIKE_SHEET.fullmatch(sheet):
        return sheet
    return "'" + sheet.replace("'", "''") + "'"


def _runs(row_numbers):
    runs = []
    for number in sorted(set(row_numbers)):
        if runs and number == runs[-1][1] + 1:
            runs[-1][1] = number
        else:
            runs.append([number, number])
    return runs


def compact_range(column_letter: str | None, column_name: str, sheet: str | None,
                  row_numbers: Sequence[int]) -> str | None:
    """Consecutive row numbers -> ONE compact range string (None for no rows).

    The sheet and column are written once, then the row runs:
    XLSX (letter given): ``청구내역!F: 2–31, 45–60``; CSV: ``행 2–31, 45–60 · 지급액``.
    """
    runs = _runs(row_numbers)
    if not runs:
        return None
    rows = ', '.join(f'{lo}' if lo == hi else f'{lo}–{hi}' for lo, hi in runs)
    if column_letter is None:
        return f'행 {rows} · {column_name}'
    prefix = f'{_quote_sheet(sheet)}!' if sheet else ''
    return f'{prefix}{column_letter}: {rows}'


# ---------------------------------------------------------------- spec

def _resolve(table: Table, name) -> tuple[int, Column]:
    if isinstance(name, str):
        for position, column in enumerate(table.columns):
            if column.name == name:
                return position, column
    _invalid()


def _to_decimal(value) -> Decimal:
    if isinstance(value, bool):
        _invalid()
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        result = Decimal(repr(value))
    elif isinstance(value, str):
        result = parse_number(value)
    else:
        result = None
    if result is None or not result.is_finite():
        _invalid()
    return result


def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) == 10:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    _invalid()


def _pair(value, convert):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        _invalid()
    low, high = convert(value[0]), convert(value[1])
    if low > high:
        _invalid()
    return low, high


def _compile_filter(table: Table, item):
    """Return (position, predicate, text). Blank and NotNumber/NotDate cells
    never match any filter (including ``ne``)."""
    if not isinstance(item, Mapping):
        _invalid()
    position, column = _resolve(table, item.get('column'))
    op = item.get('op'); value = item.get('value')
    name = column.name
    if op in {'eq', 'ne', 'in'}:
        if op == 'in':
            if not isinstance(value, (list, tuple)) or not value:
                _invalid()
            values = list(value)
        else:
            values = [value]
        if column.kind == 'number':
            kind = Decimal; targets = [_to_decimal(v) for v in values]; shown = [_grouped(t) for t in targets]
        elif column.kind == 'date':
            kind = date; targets = [_to_date(v) for v in values]; shown = [t.isoformat() for t in targets]
        else:
            if not all(isinstance(v, str) for v in values):
                _invalid()
            kind = str; targets = values; shown = values
        target_set = set(targets)
        if op == 'ne':
            predicate = lambda cell: isinstance(cell, kind) and cell not in target_set  # noqa: E731
        else:
            predicate = lambda cell: isinstance(cell, kind) and cell in target_set  # noqa: E731
        if op == 'in':
            text = f'{name}: {", ".join(shown)} 중 하나'
        else:
            text = f'{name} {_OP_SYMBOL[op]} {shown[0]}'
        return position, predicate, text
    if op in {'gt', 'gte', 'lt', 'lte'}:
        if column.kind != 'number':
            _invalid()
        target = _to_decimal(value)
        compare = {'gt': lambda c: c > target, 'gte': lambda c: c >= target,
                   'lt': lambda c: c < target, 'lte': lambda c: c <= target}[op]
        return position, (lambda cell: isinstance(cell, Decimal) and compare(cell)), f'{name} {_OP_SYMBOL[op]} {_grouped(target)}'
    if op == 'between':
        if column.kind != 'number':
            _invalid()
        low, high = _pair(value, _to_decimal)
        return (position, lambda cell: isinstance(cell, Decimal) and low <= cell <= high,
                f'{name} {_grouped(low)} 이상 {_grouped(high)} 이하')
    if op == 'date_between':
        if column.kind != 'date':
            _invalid()
        low, high = _pair(value, _to_date)
        return (position, lambda cell: isinstance(cell, date) and low <= cell <= high,
                f'{name} {low.isoformat()} ~ {high.isoformat()}')
    _invalid()


def _parse_spec(table: Table, spec):
    if not isinstance(spec, Mapping):
        _invalid()
    filters = [_compile_filter(table, item) for item in (spec.get('filters') or [])]

    groups = []  # (position, column, month, key, label)
    for item in spec.get('group_by') or []:
        if not isinstance(item, Mapping):
            _invalid()
        position, column = _resolve(table, item.get('column'))
        month = item.get('month', False)
        if not isinstance(month, bool) or column.kind != ('date' if month else 'text'):
            _invalid()
        key = f'{column.name}(월)' if month else column.name
        groups.append((position, column, month, key, key))

    measures = []  # dicts
    raw_measures = spec.get('measures') or []
    if not raw_measures:
        _invalid()
    for item in raw_measures:
        if not isinstance(item, Mapping):
            _invalid()
        ident = item.get('id'); func = item.get('func'); name = item.get('column')
        if not isinstance(ident, str) or not ident or func not in _FUNC_LABEL:
            _invalid()
        if name is None:
            if func != 'count':
                _invalid()
            position = column = None
            label = '건수'
        else:
            position, column = _resolve(table, name)
            if func in {'sum', 'avg'} and column.kind != 'number':
                _invalid()
            label = f'{_FUNC_LABEL[func]}({column.name})'
        measures.append({'id': ident, 'func': func, 'position': position, 'column': column, 'label': label})

    month_indexes = [i for i, group in enumerate(groups) if group[2]]
    growth = []  # measure indexes
    for item in spec.get('growth') or []:
        if not isinstance(item, Mapping) or len(month_indexes) != 1:
            _invalid()
        index = next((i for i, m in enumerate(measures) if m['id'] == item.get('measure_id')), None)
        if index is None or index in growth:
            _invalid()
        growth.append(index)

    keys = [g[3] for g in groups] + [m['id'] for m in measures] + [f'growth_{measures[i]["id"]}' for i in growth]
    if len(set(keys)) != len(keys):
        _invalid()

    sort = spec.get('sort')
    sort_index = None; sort_desc = False
    if sort is not None:
        if not isinstance(sort, Mapping) or not isinstance(sort.get('desc', False), bool):
            _invalid()
        by = sort.get('by')
        if by in keys:
            sort_index = keys.index(by)
        else:  # a month group may also be named by its plain column name
            aliases = [i for i, g in enumerate(groups) if g[2] and g[1].name == by]
            if len(aliases) != 1:
                _invalid()
            sort_index = aliases[0]
        sort_desc = sort.get('desc', False)

    limit = spec.get('limit')
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
        _invalid()
    return filters, groups, measures, growth, (month_indexes[0] if month_indexes else None), keys, sort_index, sort_desc, limit


# ---------------------------------------------------------------- accumulate

class _Acc:
    __slots__ = ('rows', 'total', 'not_number', 'blank', 'overflow')

    def __init__(self):
        self.rows = []; self.total = Decimal(0); self.not_number = 0; self.blank = 0; self.overflow = False

    def add(self, func, cell, row_number, has_column):
        if func == 'count':  # always the group's row count; the column only locates evidence
            self.rows.append(row_number)
            return
        if isinstance(cell, Decimal):
            self.rows.append(row_number)
            if not self.overflow:
                try:
                    self.total = _EXACT.add(self.total, cell)
                except (Inexact, Overflow, InvalidOperation):
                    self.overflow = True
        elif cell is None:
            self.blank += 1
        else:
            self.not_number += 1


def _measure_result(measure, acc):
    """-> dict(value Decimal|None, display, status, reason)."""
    func = measure['func']
    if func == 'count':
        count = len(acc.rows)
        return {'value': Decimal(count), 'text': str(count), 'display': f'{count:,}', 'status': 'ok', 'reason': None}
    if acc.overflow:
        return {'value': None, 'text': None, 'display': '계산 불가', 'status': 'not_computable', 'reason': _REASON_PRECISION}
    if not acc.rows:
        return {'value': None, 'text': None, 'display': '계산 불가', 'status': 'not_computable', 'reason': _REASON_NO_NUMBER}
    if func == 'sum':
        return {'value': acc.total, 'text': _plain(acc.total), 'display': _grouped(acc.total), 'status': 'ok', 'reason': None}
    try:
        average = _DIV.divide(acc.total, Decimal(len(acc.rows)))
    except (InvalidOperation, Overflow):
        return {'value': None, 'text': None, 'display': '계산 불가', 'status': 'not_computable', 'reason': _REASON_PRECISION}
    return {'value': average, 'text': _ratio_text(average), 'display': _grouped(_round1_exact(acc.total, Decimal(len(acc.rows)))), 'status': 'ok', 'reason': None}


def _growth_result(current, previous):
    def failed(reason):
        return {'value': None, 'text': None, 'display': '계산 불가', 'status': 'not_computable', 'reason': reason}
    if current['status'] != 'ok':
        return failed(current['reason'])
    if previous is None:
        return failed(_REASON_NO_PREVIOUS)
    if previous['status'] != 'ok':
        return failed(_REASON_PREVIOUS_FAILED)
    if previous['value'] == 0:
        return failed(_REASON_PREVIOUS_ZERO)
    try:
        scaled = _WIDE.multiply(_WIDE.subtract(current['value'], previous['value']), Decimal(100))
        rate = _DIV.divide(scaled, previous['value'])
    except (InvalidOperation, Overflow, DivisionByZero):
        return failed(_REASON_PRECISION)
    shown = _round1_exact(scaled, previous['value'])
    return {'value': rate, 'text': _ratio_text(rate), 'display': f'{_grouped(shown)}%', 'status': 'ok', 'reason': None}


def _sort_component(value):
    if value is None:
        return (3, 0)
    if isinstance(value, (tuple, Decimal, date)):
        return (0, value)
    if isinstance(value, str):
        return (1, value)
    return (2, value.raw)  # NotNumber / NotDate


def _previous_month(ym):
    year, month = ym
    return (year - 1, 12) if month == 1 else (year, month - 1)


# ---------------------------------------------------------------- run

def run(table: Table, spec: Mapping, *, deadline: float | None = None, max_groups: int = 2000,
        cancel_check=None) -> dict:
    """Evidence entries: a measure cell's entry has one compact ``range``
    string; a growth cell's entry references the two measure entries it
    compares (``current_evidence_id``, ``previous_evidence_id`` or None when
    the previous month has no rows) instead of repeating their ranges. A
    referenced previous-month entry exists even when that row is cut by
    ``limit``. ``cancel_check`` runs at most once per second (it is the job
    heartbeat); the deadline is checked at every point."""
    if cancel_check is not None:
        cancel_check = throttled_cancel_check(cancel_check)
    _check_deadline(deadline, cancel_check)
    filters, groups, measures, growth, month_index, keys, sort_index, sort_desc, limit = _parse_spec(table, spec)

    buckets: dict[tuple, list[_Acc]] = {}
    not_date = 0
    for i, (row, row_number) in enumerate(zip(table.rows, table.row_numbers)):
        if i % _DEADLINE_EVERY == 0:
            _check_deadline(deadline, cancel_check)
        if not all(predicate(row[position]) for position, predicate, _ in filters):
            continue
        key = []
        for position, _, month, _, _ in groups:
            cell = row[position]
            if month:
                if not isinstance(cell, date):
                    key = None
                    break
                key.append((cell.year, cell.month))
            else:
                key.append(cell)
        if key is None:
            not_date += 1
            continue
        key = tuple(key)
        accs = buckets.get(key)
        if accs is None:
            if len(buckets) >= max_groups:
                raise ValueError(_TOO_MANY_GROUPS)
            accs = buckets[key] = [_Acc() for _ in measures]
        for acc, measure in zip(accs, measures):
            position = measure['position']
            acc.add(measure['func'], None if position is None else row[position], row_number, position is not None)
    _check_deadline(deadline, cancel_check)
    if not groups and not buckets:
        buckets[()] = [_Acc() for _ in measures]

    results = {key: [_measure_result(m, acc) for m, acc in zip(measures, accs)] for key, accs in buckets.items()}
    ordered = sorted(buckets, key=lambda k: tuple(_sort_component(v) for v in k))

    growth_results = {}
    for key in ordered:
        cells = []
        for index in growth:
            previous_key = None
            if month_index is not None:
                previous_key = key[:month_index] + (_previous_month(key[month_index]),) + key[month_index + 1:]
            previous = results.get(previous_key)
            cells.append((_growth_result(results[key][index], None if previous is None else previous[index]), previous_key))
        growth_results[key] = cells

    def sort_value(key):
        if sort_index < len(groups):
            value = key[sort_index]
            return None if value is None else _sort_component(value)  # blank group goes last
        offset = sort_index - len(groups)
        cell = results[key][offset] if offset < len(measures) else growth_results[key][offset - len(measures)][0]
        return cell['value']

    if sort_index is not None:
        present = [k for k in ordered if sort_value(k) is not None]
        missing = [k for k in ordered if sort_value(k) is None]
        ordered = sorted(present, key=sort_value, reverse=sort_desc) + missing

    warnings = []
    total_groups = len(ordered)
    if limit is not None and total_groups > limit:
        ordered = ordered[:limit]
        warnings.append(f'상위 {limit}개만 표시 (전체 {total_groups}개)')
    if not_date:
        month_name = groups[month_index][1].name if month_index is not None else ''
        warnings.append(f'날짜 아님 {not_date}행 제외 ({month_name})')
    for index, measure in enumerate(measures):
        not_number = sum(buckets[k][index].not_number for k in buckets)
        blank = sum(buckets[k][index].blank for k in buckets)
        if not_number:
            warnings.append(f'{measure["label"]}: 숫자 아님 {not_number}행 제외')
        if blank:
            warnings.append(f'{measure["label"]}: 빈칸 {blank}행 제외')

    columns = [{'key': g[3], 'label': g[4], 'role': 'group'} for g in groups]
    columns += [{'key': m['id'], 'label': m['label'], 'role': 'measure'} for m in measures]
    columns += [{'key': f'growth_{measures[i]["id"]}', 'label': f'전월 대비 증감률 · {measures[i]["label"]}', 'role': 'growth'}
                for i in growth]

    filter_texts = [text for _, _, text in filters]
    sheet = table.sheet if table.source_format == 'xlsx' else None

    def evidence_column(measure):
        if measure['column'] is not None:
            return measure['column']
        return groups[0][1] if groups else table.columns[0]

    def group_texts(key, month_text=None):
        texts = []
        for (_, column, month, label, _), value in zip(groups, key):
            if month:
                texts.append(f'{label} = {month_text or _month_text(value)}')
            else:
                texts.append(f'{column.name} = {_value_text(value)[1]}')
        return texts

    evidence = {}
    measure_evidence = {}  # (group key, measure index) -> evidence id
    rows_out = []

    def add_evidence(entry):
        ident = f'e{len(evidence) + 1}'
        evidence[ident] = entry
        return ident

    def measure_evidence_id(key, index):
        ident = measure_evidence.get((key, index))
        if ident is not None:
            return ident
        measure = measures[index]
        acc = buckets[key][index]
        label = measure['label']
        if measure['func'] == 'count':
            formula = f'{label} = 조건에 맞는 행 {len(acc.rows):,}개'
        elif measure['func'] == 'sum':
            formula = f'{label} = 숫자 {len(acc.rows):,}개의 합'
        elif not acc.rows:
            formula = f'{label}: 대상 행 없음'
        else:
            formula = f'{label} = 합계 {_grouped(acc.total)} ÷ {len(acc.rows):,}개'
        column = evidence_column(measure)
        ident = measure_evidence[(key, index)] = add_evidence({
            'range': compact_range(column.letter, column.name, sheet, acc.rows),
            'filter_text': ' · '.join(filter_texts + group_texts(key)) or '전체 행', 'formula': formula,
            'row_count': len(acc.rows), 'excluded': {'not_number': acc.not_number, 'blank': acc.blank}})
        return ident

    def computed_cell(result, evidence_id):
        return {'value': result['text'], 'display': result['display'], 'computed': True,
                'status': result['status'], 'reason': result['reason'], 'evidence_id': evidence_id}

    for key in ordered:
        row_cells = []
        for (_, _, month, _, _), value in zip(groups, key):
            stored, shown = (_month_text(value), _month_text(value)) if month else _value_text(value)
            row_cells.append({'value': stored, 'display': shown, 'computed': False, 'status': 'ok',
                              'reason': None, 'evidence_id': None})
        for index in range(len(measures)):
            row_cells.append(computed_cell(results[key][index], measure_evidence_id(key, index)))
        for (result, previous_key), index in zip(growth_results[key], growth):
            label = measures[index]['label']
            current_acc = buckets[key][index]
            previous_acc = buckets[previous_key][index] if previous_key in buckets else None
            current_month = _month_text(key[month_index]); previous_month = _month_text(previous_key[month_index])
            current_id = measure_evidence_id(key, index)
            previous_id = measure_evidence_id(previous_key, index) if previous_acc is not None else None
            ident = add_evidence({
                'current_evidence_id': current_id, 'previous_evidence_id': previous_id,
                'filter_text': ' · '.join(filter_texts + group_texts(key, f'{current_month}, {previous_month}')),
                'formula': f'({label}[{current_month}] − {label}[{previous_month}]) ÷ {label}[{previous_month}] × 100',
                'row_count': len(current_acc.rows) + (len(previous_acc.rows) if previous_acc else 0),
                'excluded': {
                    'not_number': current_acc.not_number + (previous_acc.not_number if previous_acc else 0),
                    'blank': current_acc.blank + (previous_acc.blank if previous_acc else 0),
                },
            })
            row_cells.append(computed_cell(result, ident))
        rows_out.append(row_cells)

    return {'columns': columns, 'rows': rows_out, 'evidence': evidence, 'warnings': warnings}
