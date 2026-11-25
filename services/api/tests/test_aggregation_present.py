"""WO-N9 차트·요약 문장·크기 검사 시험 (aggregation_present)."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from daon2_user_api.aggregation_engine import run
from daon2_user_api.aggregation_present import build_chart, content_size_ok, summary_sentences
from daon2_user_api.aggregation_spec import normalize
from daon2_user_api.table_reader import Column, NotNumber, Table

D = Decimal

COLUMNS = (
    Column('청구일', 'A', 0, 'date'),
    Column('상품', 'B', 1, 'text'),
    Column('지급액', 'C', 2, 'number'),
)
ROWS = [
    (date(2026, 1, 5), '암보험', D('1000000')),
    (date(2026, 1, 20), '실손', D('500.5')),
    (date(2026, 2, 3), '암보험', D('12345000')),
    (date(2026, 2, 10), '실손', D('49.5')),
    (date(2026, 3, 1), '암보험', D('300.25')),
]


def table(rows=ROWS):
    return Table(file_name='t.xlsx', source_format='xlsx', sheet='S', header_row=1, columns=COLUMNS,
                 rows=tuple(tuple(r) for r in rows), row_numbers=tuple(range(2, 2 + len(rows))))


def build(raw, rows=ROWS):
    t = table(rows)
    spec, _ = normalize(raw, t)
    return run(t, spec), spec


def raw_spec(group_by, measures=None):
    return {'filters': [], 'group_by': group_by,
            'measures': measures or [{'id': 's', 'func': 'sum', 'column': '지급액'}], 'growth': []}


MONTH = {'column': '청구일', 'month': True}
PRODUCT = {'column': '상품', 'month': False}


def test_chart_values_equal_table_values():
    result, spec = build(raw_spec([MONTH, PRODUCT]))
    chart = build_chart(result, spec)
    keys = [c['key'] for c in result['columns']]
    cells = {(row[keys.index('청구일(월)')]['value'], row[keys.index('상품')]['value']): row[keys.index('s')]['value']
             for row in result['rows']}
    points = {(p['x'], s['label']): p['value'] for s in chart['series'] for p in s['points'] if p['value'] is not None}
    assert points == cells
    assert len(points) == len(result['rows'])


def test_not_computable_is_null_point():
    rows = ROWS + [(date(2026, 4, 1), '암보험', NotNumber('abc'))]
    result, spec = build(raw_spec([MONTH]), rows)
    cells = [row[1] for row in result['rows']]
    assert any(c['value'] is None for c in cells)
    chart = build_chart(result, spec)
    values = [p['value'] for p in chart['series'][0]['points']]
    assert values == [c['value'] for c in cells]
    assert None in values


def test_summary_numbers_subset_of_table_display():
    result, spec = build(raw_spec([PRODUCT, MONTH]))
    sentences = summary_sentences(result, spec)
    assert len(sentences) == 2
    displays = {cell['display'] for row in result['rows'] for cell in row}
    for sentence in sentences:
        shown = re.findall(r'\(([^()]*)\)\s*$', sentence)
        assert shown and shown[-1] in displays
        assert set(re.findall(r'\d[\d,.]*', sentence)) <= {n for d in displays for n in re.findall(r'\d[\d,.]*', d)}
    assert '합계(지급액) 가장 큰 묶음: 암보험 · 2026-02 (12,345,000)' in sentences


def test_line_for_month_bar_otherwise():
    result, spec = build(raw_spec([MONTH]))
    assert build_chart(result, spec)['kind'] == 'line'
    result, spec = build(raw_spec([PRODUCT]))
    assert build_chart(result, spec)['kind'] == 'bar'


def test_content_size_limit():
    assert content_size_ok({'a': '가' * 1000})
    limit = 2 * 1024 * 1024
    # 한글 1자 = UTF-8 3바이트: 바이트 기준으로 경계를 검사한다.
    overhead = len('{"a": ""}'.encode())
    assert content_size_ok({'a': 'x' * (limit - overhead)})
    assert not content_size_ok({'a': 'x' * (limit - overhead + 1)})
    assert not content_size_ok({'a': '가' * (limit // 3)})


def test_two_groups_with_month_make_series_per_other_group():
    result, spec = build(raw_spec([PRODUCT, MONTH]))
    chart = build_chart(result, spec)
    assert chart['x_key'] == '청구일(월)' and chart['kind'] == 'line'
    by_label = {s['label']: [(p['x'], p['value']) for p in s['points']] for s in chart['series']}
    assert set(by_label) == {'암보험', '실손'}
    assert by_label['암보험'] == [('2026-01', '1000000'), ('2026-02', '12345000'), ('2026-03', '300.25')]
    assert by_label['실손'] == [('2026-01', '500.5'), ('2026-02', '49.5'), ('2026-03', None)]


def test_no_group_column_returns_none_and_no_sentences():
    result, spec = build(raw_spec([]))
    assert build_chart(result, spec) is None
    assert summary_sentences(result, spec) == []


def test_single_computable_cell_gives_no_sentences():
    result, spec = build(raw_spec([MONTH]), ROWS[:1])
    assert summary_sentences(result, spec) == []


def test_line_x_is_ascending_month_even_when_sorted_by_value():
    raw = raw_spec([PRODUCT, MONTH])
    raw['sort'] = {'by': 's', 'desc': True}
    result, spec = build(raw)
    months_in_rows = [row[1]['display'] for row in result['rows']]
    assert months_in_rows != sorted(months_in_rows)  # the fixture really is shuffled
    chart = build_chart(result, spec)
    xs = [[p['x'] for p in s['points']] for s in chart['series']]
    assert all(x == ['2026-01', '2026-02', '2026-03'] for x in xs)
    by_label = {s['label']: [p['value'] for p in s['points']] for s in chart['series']}
    assert by_label['실손'] == ['500.5', '49.5', None]  # missing month -> null point
    assert [s['label'] for s in chart['series']] == ['실손', '암보험']  # series: key ascending


def test_series_keyed_by_value_not_display():
    rows = [(date(2026, 1, 5), 'A', D('1')), (date(2026, 1, 6), 'a', D('2'))]
    result, spec = build(raw_spec([PRODUCT, MONTH]), rows)
    for r in result['rows']:  # force identical display for distinct values
        r[0]['display'] = '같음'
    chart = build_chart(result, spec)
    assert len(chart['series']) == 2
    assert len({s['key'] for s in chart['series']}) == 2
    assert [s['label'] for s in chart['series']] == ['같음', '같음']


def test_multi_group_without_month_has_x_label_and_first_group_x_key():
    result, spec = build(raw_spec([PRODUCT, {'column': '청구일', 'month': False}]))
    chart = build_chart(result, spec)
    assert chart['kind'] == 'bar'
    assert chart['x_key'] == '상품'
    assert chart['x_label'] == '상품 · 청구일'
    assert all(' · ' in p['x'] and p['x'].split(' · ')[0] in ('암보험', '실손') for p in chart['series'][0]['points'])
    single, spec1 = build(raw_spec([PRODUCT]))
    assert build_chart(single, spec1)['x_label'] == '상품'
