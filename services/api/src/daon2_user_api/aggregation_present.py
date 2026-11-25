"""Chart definition, template summary sentences and size check for WO-N9.

Pure functions over the aggregation engine result. Chart points carry the
cell's stored ``value`` string unchanged (None when not computable); summary
sentences use only cell ``display`` strings and never format numbers.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

MAX_CONTENT_BYTES = 2 * 1024 * 1024
_SEPARATOR = ' · '


def content_size_ok(body: dict) -> bool:
    return len(json.dumps(body, ensure_ascii=False).encode('utf-8')) <= MAX_CONTENT_BYTES


def _layout(result: dict, spec: dict):
    """(group column indexes, month column index or None, first measure index) or None."""
    columns = result.get('columns') or []
    group_idx = [i for i, c in enumerate(columns) if c.get('role') == 'group']
    measure_idx = next((i for i, c in enumerate(columns) if c.get('role') == 'measure'), None)
    if not group_idx or measure_idx is None:
        return None
    month_idx = None
    for position, group in enumerate(spec.get('group_by') or []):
        if group.get('month') and position < len(group_idx):
            month_idx = group_idx[position]
            break
    return group_idx, month_idx, measure_idx


def _join(row, indexes) -> str:
    return _SEPARATOR.join(row[i]['display'] for i in indexes)


def _series_key(row, indexes) -> str:
    """Series key from the underlying group values; a blank group is JSON null,
    so it never collides with a literal '(빈칸)' text value."""
    return json.dumps([row[i]['value'] for i in indexes], ensure_ascii=False, separators=(',', ':'))


def build_chart(result: dict, spec: dict) -> dict | None:
    """Chart of the first measure.

    line (month group present): x categories are the month strings ascending
    and identical for every series (a month missing from a series is a point
    with value None and ``missing: True``; a not-computable cell is a point
    with value None and no ``missing``); series are ordered by their underlying group value
    ascending, regardless of the row sort. Series are keyed by the underlying
    group cell values (JSON array, blank = null), labelled by the display.
    bar: single series in row order; x is the group combination. With several
    group columns x_key is the FIRST group column key and x_label the joined
    column labels (the composite x text lives in the points).
    """
    layout = _layout(result, spec)
    if layout is None:
        return None
    group_idx, month_idx, measure_idx = layout
    columns = result['columns']
    measure = columns[measure_idx]
    if month_idx is None:
        points = [{'x': _join(row, group_idx), 'value': row[measure_idx]['value']} for row in result['rows']]
        return {'kind': 'bar', 'x_key': columns[group_idx[0]]['key'],
                'x_label': _SEPARATOR.join(columns[i]['label'] for i in group_idx),
                'series': [{'key': measure['key'], 'label': measure['label'], 'points': points}]}
    series_idx = [i for i in group_idx if i != month_idx]
    months = sorted({row[month_idx]['value'] for row in result['rows']})
    grouped: dict[tuple, dict] = {}
    for row in result['rows']:
        ident = tuple(row[i]['value'] for i in series_idx)
        entry = grouped.get(ident)
        if entry is None:
            entry = grouped[ident] = {
                'key': _series_key(row, series_idx) if series_idx else measure['key'],
                'label': _join(row, series_idx) if series_idx else measure['label'], 'values': {}}
        entry['values'][row[month_idx]['value']] = row[measure_idx]['value']
    ordered = sorted(grouped.items(), key=lambda kv: tuple('' if v is None else v for v in kv[0]))
    series = [{'key': e['key'], 'label': e['label'],
               'points': [{'x': m, 'value': e['values'][m]} if m in e['values'] else {'x': m, 'value': None, 'missing': True}
                          for m in months]} for _, e in ordered]
    return {'kind': 'line', 'x_key': columns[month_idx]['key'], 'x_label': columns[month_idx]['label'],
            'series': series}


def summary_sentences(result: dict, spec: dict) -> list[str]:
    """Largest/smallest group of the first measure, from display strings only.

    Returns [] when fewer than 2 computable cells exist or all computable
    values are equal (no distinct max/min to report).
    """
    layout = _layout(result, spec)
    if layout is None:
        return []
    group_idx, _, measure_idx = layout
    label = result['columns'][measure_idx]['label']
    candidates = []
    for row in result['rows']:
        cell = row[measure_idx]
        if cell.get('value') is None:
            continue
        try:
            candidates.append((Decimal(cell['value']), row, cell['display']))
        except (InvalidOperation, ValueError):
            continue
    if len(candidates) < 2:
        return []
    largest = max(candidates, key=lambda c: c[0])
    smallest = min(candidates, key=lambda c: c[0])
    if largest[0] == smallest[0]:
        return []
    return [f'{label} {word}: {_join(row, group_idx)} ({display})'
            for word, (_, row, display) in (('가장 큰 묶음', largest), ('가장 작은 묶음', smallest))]
