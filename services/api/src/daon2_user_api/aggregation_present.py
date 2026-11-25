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


def build_chart(result: dict, spec: dict) -> dict | None:
    layout = _layout(result, spec)
    if layout is None:
        return None
    group_idx, month_idx, measure_idx = layout
    columns = result['columns']
    measure = columns[measure_idx]
    if month_idx is not None:
        x_idx = [month_idx]
        series_idx = [i for i in group_idx if i != month_idx]
    else:
        x_idx = group_idx
        series_idx = []
    series: dict[str, dict] = {}
    for row in result['rows']:
        label = _join(row, series_idx) if series_idx else measure['label']
        entry = series.get(label)
        if entry is None:
            key = _join(row, series_idx) if series_idx else measure['key']
            entry = series[label] = {'key': key, 'label': label, 'points': []}
        entry['points'].append({'x': _join(row, x_idx), 'value': row[measure_idx]['value']})
    x_key = columns[x_idx[0]]['key'] if len(x_idx) == 1 else _SEPARATOR.join(columns[i]['key'] for i in x_idx)
    return {'kind': 'line' if month_idx is not None else 'bar', 'x_key': x_key, 'series': list(series.values())}


def _particle(label: str) -> str:
    """이/가 by the last hangul syllable of the label (a trailing ')' is skipped)."""
    text = label.rstrip(')').rstrip()
    last = text[-1] if text else ''
    if '가' <= last <= '힣':
        return '이' if (ord(last) - 0xAC00) % 28 else '가'
    return '이'


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
    particle = _particle(label)
    return [f'{label}{particle} {word}: {_join(row, group_idx)} ({display})'
            for word, (_, row, display) in (('가장 큰 묶음', largest), ('가장 작은 묶음', smallest))]
