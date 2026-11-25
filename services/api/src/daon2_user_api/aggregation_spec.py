"""Aggregation condition schema, normalization and validation for WO-N9.

The model only proposes conditions; this module rejects everything that the
aggregation engine does not support. Pure functions, no model calls.

``normalize`` returns exactly the spec dict that ``aggregation_engine.run``
consumes. Column names must match exactly (no nearest-name substitution).
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from .table_reader import Table, parse_number

MAX_GROUPS = 2
MAX_LIMIT = 50
MAX_IN_VALUES = 100
MAX_ITEMS = 20
MAX_UNSUPPORTED_TEXT = 200
_TOP_KEYS = frozenset(('filters', 'group_by', 'measures', 'growth', 'sort', 'limit', 'unsupported'))
_ITEM_KEYS = {
    'filters': frozenset(('column', 'op', 'value')), 'group_by': frozenset(('column', 'month')),
    'measures': frozenset(('id', 'func', 'column')), 'growth': frozenset(('measure_id',)),
    'sort': frozenset(('by', 'desc')),
}

_OPS = ('eq', 'ne', 'in', 'gt', 'gte', 'lt', 'lte', 'between', 'date_between')
_FUNCS = ('count', 'sum', 'avg')
_FUNC_LABEL = {'count': '건수', 'sum': '합계', 'avg': '평균'}
_OP_SYMBOL = {'eq': '=', 'ne': '≠', 'gt': '>', 'gte': '≥', 'lt': '<', 'lte': '≤'}
_NOT_FOUND = 'AGGREGATION_FILTER_VALUE_NOT_FOUND'

_SCALAR = {'anyOf': [{'type': 'string'}, {'type': 'integer'}]}
SPEC_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'filters': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'column': {'type': 'string'},
                'op': {'type': 'string', 'enum': list(_OPS)},
                'value': {'anyOf': [{'type': 'string'}, {'type': 'integer'},
                                    {'type': 'array', 'items': _SCALAR}]},
            },
            'required': ['column', 'op', 'value']}},
        'group_by': {'type': 'array', 'maxItems': MAX_GROUPS, 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'column': {'type': 'string'}, 'month': {'type': 'boolean'}},
            'required': ['column', 'month']}},
        'measures': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {
                'id': {'type': 'string'},
                'func': {'type': 'string', 'enum': list(_FUNCS)},
                'column': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
            },
            'required': ['id', 'func', 'column']}},
        'growth': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'properties': {'measure_id': {'type': 'string'}},
            'required': ['measure_id']}},
        'sort': {'anyOf': [{'type': 'null'}, {
            'type': 'object', 'additionalProperties': False,
            'properties': {'by': {'type': 'string'}, 'desc': {'type': 'boolean'}},
            'required': ['by', 'desc']}]},
        'limit': {'anyOf': [{'type': 'integer', 'minimum': 1, 'maximum': MAX_LIMIT}, {'type': 'null'}]},
        'unsupported': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['filters', 'group_by', 'measures', 'growth', 'sort', 'limit', 'unsupported'],
}


class SpecInvalid(Exception):
    """The proposed conditions break a rule; ``reasons`` are Korean retry hints."""

    def __init__(self, reasons: list[str]):
        super().__init__('AGGREGATION_SPEC_INVALID')
        self.reasons = list(reasons)


class SpecUnsupported(Exception):
    """Every request was out of scope (no measures, only ``unsupported``)."""

    def __init__(self, items: list[str] | None = None):
        super().__init__('AGGREGATION_UNSUPPORTED')
        self.items = list(items or [])


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_scalar(value) -> bool:
    return isinstance(value, str) or _is_int(value)


def _iso(value) -> date | None:
    if isinstance(value, str) and len(value) == 10:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _column_values(table: Table, position: int) -> set[str]:
    return {row[position] for row in table.rows if isinstance(row[position], str)}


def _list(raw, key) -> list:
    value = raw.get(key)
    return list(value) if isinstance(value, (list, tuple)) else []


def _items(raw, key: str, reasons: list[str]) -> list:
    """A list field of the proposal: None -> [], non-list or too long -> reason."""
    value = raw.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        reasons.append(f'{key} 형식 오류')
        return []
    if len(value) > MAX_ITEMS:
        reasons.append(f'{key}는 최대 {MAX_ITEMS}개')
        return []
    for item in value:
        _check_keys(item, key, reasons)
    return list(value)


def _check_keys(item, key: str, reasons: list[str]) -> None:
    if isinstance(item, Mapping):
        for extra in item:
            if extra not in _ITEM_KEYS[key]:
                reasons.append(f'알 수 없는 항목: {extra}')


def _filter(table: Table, item, reasons: list[str], cache: dict[int, set[str]]):
    if not isinstance(item, Mapping):
        reasons.append('필터 형식 오류')
        return None
    name = item.get('column'); op = item.get('op'); value = item.get('value')
    found = next(((p, c) for p, c in enumerate(table.columns) if isinstance(name, str) and c.name == name), None)
    if found is None:
        reasons.append(f'없는 열: {name}')
        return None
    position, column = found
    bad = f'필터 값 형식 오류: {name}'
    if op not in _OPS:
        reasons.append(f'지원하지 않는 필터 연산: {op}')
        return None

    if op in ('eq', 'ne', 'in'):
        values = value if op == 'in' else [value]
        if op == 'in' and (not isinstance(value, list) or not value or len(value) > MAX_IN_VALUES):
            reasons.append(bad); return None
        if not all(_is_scalar(v) for v in values):
            reasons.append(bad); return None
        if column.kind == 'text':
            values = [str(v) for v in values]
            known = cache.setdefault(position, _column_values(table, position))
            for v in values:
                if v not in known:
                    raise ValueError(f'{_NOT_FOUND}:{v}({name})')
        elif column.kind == 'number':
            if not all(_is_int(v) or parse_number(v) is not None for v in values):
                reasons.append(bad); return None
        else:
            if not all(_iso(v) for v in values):
                reasons.append(bad); return None
        return {'column': name, 'op': op, 'value': values if op == 'in' else values[0]}

    if op in ('gt', 'gte', 'lt', 'lte', 'between'):
        if column.kind != 'number':
            reasons.append(f'숫자 열이 아님: {name}'); return None
        values = value if op == 'between' else [value]
        if op == 'between' and (not isinstance(value, list) or len(value) != 2):
            reasons.append(bad); return None
        if not all(_is_scalar(v) and (_is_int(v) or parse_number(v) is not None) for v in values):
            reasons.append(bad); return None
        if op == 'between':
            low, high = (parse_number(v) if isinstance(v, str) else v for v in values)
            if low > high:
                reasons.append(bad); return None
        return {'column': name, 'op': op, 'value': list(value) if op == 'between' else value}

    # date_between
    if column.kind != 'date':
        reasons.append(f'날짜 열이 아님: {name}'); return None
    if not isinstance(value, list) or len(value) != 2 or not all(_iso(v) for v in value) or _iso(value[0]) > _iso(value[1]):
        reasons.append(bad); return None
    return {'column': name, 'op': op, 'value': list(value)}


def normalize(raw: Mapping, table: Table) -> tuple[dict, list[str]]:
    """Validate the model's proposal and return ``(spec, warnings)``.

    Raises ``SpecInvalid`` (retry with reasons), ``SpecUnsupported`` (nothing
    supported was requested) or ``ValueError('AGGREGATION_FILTER_VALUE_NOT_FOUND:값(열)')``
    (fails immediately; the value list is never sent back to the model).
    """
    if not isinstance(raw, Mapping):
        raise SpecInvalid(['조건 형식 오류'])
    reasons: list[str] = []
    for extra in raw:
        if extra not in _TOP_KEYS:
            reasons.append(f'알 수 없는 항목: {extra}')
    raw_unsupported = raw.get('unsupported')
    if raw_unsupported is None:
        raw_unsupported = []
    if not isinstance(raw_unsupported, list) or not all(isinstance(u, str) for u in raw_unsupported):
        reasons.append('unsupported 형식 오류')
        raw_unsupported = []
    unsupported = [u.strip()[:MAX_UNSUPPORTED_TEXT] for u in raw_unsupported if u.strip()]
    warnings = [f'하지 않은 요청: {u}' for u in unsupported]
    if not _list(raw, 'measures') and unsupported and not reasons:
        raise SpecUnsupported(unsupported)

    by_name = {c.name: c for c in table.columns}
    cache: dict[int, set[str]] = {}

    filters = [f for f in (_filter(table, item, reasons, cache) for item in _items(raw, 'filters', reasons)) if f]

    groups = []
    raw_groups = _items(raw, 'group_by', reasons)
    for item in raw_groups:
        name = item.get('column') if isinstance(item, Mapping) else None
        month = item.get('month', False) if isinstance(item, Mapping) else None
        if not (isinstance(name, str) and name in by_name):
            reasons.append(f'없는 열: {name}'); continue
        if not isinstance(month, bool):
            reasons.append(f'월 묶기 값 형식 오류: {name}'); continue
        if month and by_name[name].kind != 'date':
            reasons.append(f'월 묶기는 날짜 열만 가능: {name}'); continue
        groups.append({'column': name, 'month': month})
    if len(raw_groups) > MAX_GROUPS:
        reasons.append(f'묶음 열은 최대 {MAX_GROUPS}개')
    group_keys = [f'{g["column"]}(월)' if g['month'] else g['column'] for g in groups]

    measures = []
    raw_measures = _items(raw, 'measures', reasons)
    if not raw_measures:
        reasons.append('집계 항목 없음')
    used_ids = {m.get('id') for m in raw_measures if isinstance(m, Mapping) and isinstance(m.get('id'), str) and m.get('id')}
    seen_ids: set[str] = set()
    counter = 0
    for item in raw_measures:
        if not isinstance(item, Mapping):
            reasons.append('집계 항목 형식 오류'); continue
        func = item.get('func'); name = item.get('column'); ident = item.get('id')
        if func not in _FUNCS:
            reasons.append(f'지원하지 않는 집계: {func}'); continue
        if name is None:
            if func != 'count':
                reasons.append(f'{_FUNC_LABEL[func]}에는 열이 필요함'); continue
        elif not (isinstance(name, str) and name in by_name):
            reasons.append(f'없는 열: {name}'); continue
        elif func in ('sum', 'avg') and by_name[name].kind != 'number':
            reasons.append(f'숫자 열이 아님: {name} ({_FUNC_LABEL[func]}은 숫자 열만 가능)'); continue
        if ident is not None and not isinstance(ident, str):
            reasons.append('집계 id 형식 오류'); continue
        if not ident or ident in seen_ids:
            while True:  # deterministic: m1, m2, ... skipping ids already used
                counter += 1
                ident = f'm{counter}'
                if ident not in used_ids and ident not in seen_ids:
                    break
        seen_ids.add(ident)
        measures.append({'id': ident, 'func': func, 'column': name})

    growth = []
    month_groups = [g for g in groups if g['month']]
    for item in _items(raw, 'growth', reasons):
        if len(month_groups) != 1:
            reasons.append('증감률 비교는 월 묶기가 있을 때만 가능'); break
        ident = item.get('measure_id') if isinstance(item, Mapping) else None
        if not any(m['id'] == ident for m in measures):
            reasons.append(f'없는 집계 id: {ident}'); continue
        if any(g['measure_id'] == ident for g in growth):
            reasons.append(f'증감률 중복: {ident}'); continue
        growth.append({'measure_id': ident})

    keys = group_keys + [m['id'] for m in measures] + [f'growth_{g["measure_id"]}' for g in growth]
    duplicated = sorted({k for k in keys if keys.count(k) > 1})
    for k in duplicated:
        reasons.append(f'결과 이름 중복: {k}')

    sort = None
    raw_sort = raw.get('sort')
    if raw_sort is not None:
        by = raw_sort.get('by') if isinstance(raw_sort, Mapping) else None
        desc = raw_sort.get('desc', False) if isinstance(raw_sort, Mapping) else None
        if not isinstance(desc, bool) or not isinstance(by, str):
            reasons.append('정렬 형식 오류')
        elif by in keys:
            sort = {'by': by, 'desc': desc}
        else:  # a month group may be named by its plain column name
            alias = [f'{g["column"]}(월)' for g in month_groups if g['column'] == by]
            if len(alias) == 1:
                sort = {'by': alias[0], 'desc': desc}
            else:
                reasons.append(f'정렬 기준 없음: {by}')

    limit = raw.get('limit')
    if limit is not None and (not _is_int(limit) or limit < 1 or limit > MAX_LIMIT):
        reasons.append(f'limit은 1~{MAX_LIMIT}')

    if reasons:
        raise SpecInvalid(reasons)
    return ({'filters': filters, 'group_by': groups, 'measures': measures, 'growth': growth,
             'sort': sort, 'limit': limit}, warnings)


def _filter_text(item: Mapping) -> str:
    name, op, value = item['column'], item['op'], item['value']
    if op in _OP_SYMBOL:
        return f'{name}{_OP_SYMBOL[op]}{value}'
    if op == 'in':
        return f'{name}: {", ".join(str(v) for v in value)} 중 하나'
    return f'{name} {value[0]}~{value[1]}'


def describe(spec: Mapping) -> str:
    """One-sentence summary of normalized conditions (shown to the user)."""
    parts = []
    if spec.get('filters'):
        parts.append('필터: ' + ', '.join(_filter_text(f) for f in spec['filters']))
    if spec.get('group_by'):
        parts.append('묶기: ' + ', '.join(f'{g["column"]}(월)' if g.get('month') else g['column'] for g in spec['group_by']))
    measures = spec.get('measures') or []
    if measures:
        parts.append('집계: ' + ', '.join(
            _FUNC_LABEL[m['func']] if m.get('column') is None else f'{_FUNC_LABEL[m["func"]]}({m["column"]})'
            for m in measures))
    if spec.get('growth'):
        parts.append('비교: 전월 대비 증감률')
    sort = spec.get('sort')
    if sort:
        parts.append(f'정렬: {sort["by"]} {"내림차순" if sort.get("desc") else "오름차순"}')
    if spec.get('limit'):
        parts.append(f'상위 {spec["limit"]}개')
    return ' · '.join(parts)
