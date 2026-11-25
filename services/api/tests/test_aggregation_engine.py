"""WO-N9 집계 계산·칸별 근거 시험 (aggregation_engine)."""
from __future__ import annotations

import re
import time
from datetime import date
from decimal import Context, Decimal

import pytest

from daon2_user_api.aggregation_engine import AggregationTimeout, compress_ranges, run
from daon2_user_api.table_reader import Column, NotDate, NotNumber, Table

D = Decimal


def make_table(rows, row_numbers=None, *, csv=False, columns=None):
    """청구일(date)·상품(text)·지급액(number). Column.index/letter는 일부러
    위치와 다르게(E, F, G) 두어 위치 대신 index를 쓰는 실수를 잡는다."""
    if columns is None:
        columns = (
            Column('청구일', None if csv else 'E', 4, 'date'),
            Column('상품', None if csv else 'F', 5, 'text'),
            Column('지급액', None if csv else 'G', 6, 'number'),
        )
    if row_numbers is None:
        row_numbers = tuple(range(2, 2 + len(rows)))
    return Table(file_name='t.csv' if csv else 't.xlsx', source_format='csv' if csv else 'xlsx',
                 sheet=None if csv else '청구내역', header_row=1, columns=columns,
                 rows=tuple(tuple(r) for r in rows), row_numbers=tuple(row_numbers))


def spec(**kw):
    base = {'filters': [], 'group_by': [], 'measures': [], 'growth': [], 'sort': None, 'limit': None}
    base.update(kw)
    return base


def by_key(result):
    """[{column key: cell}] per output row."""
    keys = [c['key'] for c in result['columns']]
    return [dict(zip(keys, row)) for row in result['rows']]


def expand(ranges):
    """근거 범위 문자열을 행 번호 집합으로 펼친다 (XLSX·CSV 모두)."""
    numbers = set()
    for text in ranges:
        if text.startswith('행 '):
            body = text[2:].split(' · ')[0]
            for part in body.split(', '):
                lo, _, hi = part.partition('–')
                numbers.update(range(int(lo), int(hi or lo) + 1))
        else:
            ref = text.split('!')[-1]
            lo, _, hi = ref.partition(':')
            lo_n = int(re.sub(r'[A-Z]', '', lo)); hi_n = int(re.sub(r'[A-Z]', '', hi or lo))
            numbers.update(range(lo_n, hi_n + 1))
    return numbers


SAMPLE = [
    (date(2026, 1, 5), 'A', D('100')),
    (date(2026, 1, 20), 'B', D('50.5')),
    (date(2026, 2, 3), 'A', D('200')),
    (date(2026, 2, 10), 'B', D('49.5')),
    (date(2026, 3, 1), 'A', D('300.25')),
]
MEASURES3 = [
    {'id': 'n', 'func': 'count', 'column': None},
    {'id': 's', 'func': 'sum', 'column': '지급액'},
    {'id': 'a', 'func': 'avg', 'column': '지급액'},
]


# ------------------------------------------------------------------ named

def test_sum_count_avg_by_product():
    result = run(make_table(SAMPLE), spec(group_by=[{'column': '상품', 'month': False}], measures=MEASURES3))
    assert [c['key'] for c in result['columns']] == ['상품', 'n', 's', 'a']
    assert [c['role'] for c in result['columns']] == ['group', 'measure', 'measure', 'measure']
    rows = by_key(result)
    assert [r['상품']['value'] for r in rows] == ['A', 'B']
    a, b = rows
    assert (a['n']['value'], a['s']['value']) == ('3', '600.25')
    exact_avg = Context(prec=28).divide(D('600.25'), D(3))
    assert a['a']['value'] == str(exact_avg)
    assert a['a']['display'] == '200.1'
    assert (b['n']['value'], b['s']['value'], b['a']['value']) == ('2', '100.0', '50')
    assert b['s']['display'] == '100.0'
    # 묶음 칸은 원래 값: 계산 아님, 근거 없음
    assert a['상품'] == {'value': 'A', 'display': 'A', 'computed': False, 'status': 'ok', 'reason': None, 'evidence_id': None}
    assert a['s']['computed'] is True and a['s']['status'] == 'ok'


def test_month_grouping():
    rows = SAMPLE + [(NotDate('미정'), 'A', D('7')), (None, 'B', D('8'))]
    result = run(make_table(rows), spec(group_by=[{'column': '청구일', 'month': True}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}]))
    out = by_key(result)
    key = result['columns'][0]['key']
    assert [r[key]['value'] for r in out] == ['2026-01', '2026-02', '2026-03']
    assert [r['s']['value'] for r in out] == ['150.5', '249.5', '300.25']
    assert any('날짜 아님 2행 제외' in w for w in result['warnings'])


def test_growth_previous_month():
    rows = [(date(2026, 1, 9), 'A', D('100')), (date(2026, 2, 9), 'A', D('150')), (date(2026, 3, 9), 'A', D('131.25'))]
    result = run(make_table(rows), spec(group_by=[{'column': '청구일', 'month': True}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                         growth=[{'measure_id': 's'}]))
    col = result['columns'][-1]
    assert (col['key'], col['role']) == ('growth_s', 'growth')
    jan, feb, mar = by_key(result)
    assert jan['growth_s']['status'] == 'not_computable' and jan['growth_s']['reason'] == '전월 자료 없음'
    assert feb['growth_s']['value'] == '50' and feb['growth_s']['display'] == '50.0%'
    assert mar['growth_s']['value'] == '-12.5' and mar['growth_s']['display'] == '-12.5%'
    ev = result['evidence'][feb['growth_s']['evidence_id']]
    assert expand(ev['ranges']) == {2, 3}
    assert ev['formula'] == '(합계(지급액)[2026-02] − 합계(지급액)[2026-01]) ÷ 합계(지급액)[2026-01] × 100'


def test_growth_previous_zero_not_computable():
    rows = [(date(2026, 1, 9), 'A', D('0')), (date(2026, 2, 9), 'A', D('10'))]
    result = run(make_table(rows), spec(group_by=[{'column': '청구일', 'month': True}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                         growth=[{'measure_id': 's'}]))
    feb = by_key(result)[1]['growth_s']
    assert (feb['status'], feb['reason'], feb['value']) == ('not_computable', '전월 값 0', None)


def test_growth_gap_month_is_not_computable():
    rows = [(date(2026, 1, 9), 'A', D('10')), (date(2026, 3, 9), 'A', D('20'))]
    result = run(make_table(rows), spec(group_by=[{'column': '청구일', 'month': True}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                         growth=[{'measure_id': 's'}]))
    jan, mar = by_key(result)
    assert mar['growth_s']['status'] == 'not_computable'
    assert mar['growth_s']['reason'] == '전월 자료 없음'


def test_avg_no_rows_not_computable():
    rows = [(date(2026, 1, 9), 'A', NotNumber('x')), (date(2026, 1, 9), 'A', None)]
    result = run(make_table(rows), spec(group_by=[{'column': '상품', 'month': False}],
                                         measures=[{'id': 'a', 'func': 'avg', 'column': '지급액'}]))
    cell = by_key(result)[0]['a']
    assert cell['status'] == 'not_computable' and cell['value'] is None and cell['reason']
    # 아무 행도 맞지 않는 묶음 없는 집계: 한 줄, 개수 0, 평균 계산 불가
    result = run(make_table(SAMPLE), spec(filters=[{'column': '상품', 'op': 'eq', 'value': 'Z'}], measures=MEASURES3))
    (row,) = by_key(result)
    assert row['n']['value'] == '0' and row['s']['value'] == '0'
    assert row['a']['status'] == 'not_computable'


def test_not_number_and_blank_excluded_and_counted():
    rows = [(date(2026, 1, 1), 'A', D('100')), (date(2026, 1, 2), 'A', NotNumber('abc')),
            (date(2026, 1, 3), 'A', None), (date(2026, 1, 4), 'A', D('50'))]
    result = run(make_table(rows), spec(measures=[{'id': 's', 'func': 'sum', 'column': '지급액'},
                                                   {'id': 'n', 'func': 'count', 'column': None}]))
    (row,) = by_key(result)
    assert row['s']['value'] == '150'
    assert row['n']['value'] == '4'
    ev = result['evidence'][row['s']['evidence_id']]
    assert ev['excluded'] == {'not_number': 1, 'blank': 1}
    assert ev['row_count'] == 2
    assert expand(ev['ranges']) == {2, 5}
    assert any('숫자 아님 1행' in w for w in result['warnings'])


def _count_rows(table, flt):
    result = run(table, spec(filters=[flt], measures=[{'id': 'n', 'func': 'count', 'column': None}]))
    (row,) = by_key(result)
    return expand(result['evidence'][row['n']['evidence_id']]['ranges'])


def test_filters_each_op():
    rows = [
        (date(2026, 1, 1), 'A', D('10')),       # 2
        (date(2026, 1, 31), 'B', D('20')),      # 3
        (date(2026, 2, 1), 'C', D('30')),       # 4
        (NotDate('?'), 'A', NotNumber('n/a')),  # 5
        (None, None, None),                     # 6
    ]
    t = make_table(rows)
    assert _count_rows(t, {'column': '상품', 'op': 'eq', 'value': 'A'}) == {2, 5}
    assert _count_rows(t, {'column': '상품', 'op': 'ne', 'value': 'A'}) == {3, 4}
    assert _count_rows(t, {'column': '상품', 'op': 'in', 'value': ['B', 'C']}) == {3, 4}
    assert _count_rows(t, {'column': '지급액', 'op': 'gt', 'value': '20'}) == {4}
    assert _count_rows(t, {'column': '지급액', 'op': 'gte', 'value': 20}) == {3, 4}
    assert _count_rows(t, {'column': '지급액', 'op': 'lt', 'value': '20'}) == {2}
    assert _count_rows(t, {'column': '지급액', 'op': 'lte', 'value': '20'}) == {2, 3}
    assert _count_rows(t, {'column': '지급액', 'op': 'between', 'value': ['10', '20']}) == {2, 3}
    assert _count_rows(t, {'column': '지급액', 'op': 'eq', 'value': '20.0'}) == {3}
    assert _count_rows(t, {'column': '청구일', 'op': 'date_between', 'value': ['2026-01-01', '2026-01-31']}) == {2, 3}
    with pytest.raises(ValueError, match='AGGREGATION_SPEC_INVALID'):
        run(t, spec(filters=[{'column': '상품', 'op': 'gt', 'value': '1'}], measures=[{'id': 'n', 'func': 'count', 'column': None}]))
    with pytest.raises(ValueError, match='AGGREGATION_SPEC_INVALID'):
        run(t, spec(filters=[{'column': '없는열', 'op': 'eq', 'value': '1'}], measures=[{'id': 'n', 'func': 'count', 'column': None}]))


def test_evidence_ranges_match_rows():
    rows = [
        (date(2026, 1, 1), 'A', D('1')), (date(2026, 1, 1), 'A', D('2')), (date(2026, 1, 1), 'B', D('3')),
        (date(2026, 1, 1), 'A', D('4')), (date(2026, 1, 1), 'A', NotNumber('x')), (date(2026, 1, 1), 'B', D('6')),
        (date(2026, 1, 1), 'A', D('7')),
    ]
    numbers = (2, 3, 4, 7, 8, 10, 11)
    for csv in (False, True):
        table = make_table(rows, numbers, csv=csv)
        result = run(table, spec(group_by=[{'column': '상품', 'month': False}], measures=MEASURES3))
        a, b = by_key(result)
        ev = result['evidence']
        assert expand(ev[a['n']['evidence_id']]['ranges']) == {2, 3, 7, 8, 11}
        assert expand(ev[a['s']['evidence_id']]['ranges']) == {2, 3, 7, 11}
        assert expand(ev[a['a']['evidence_id']]['ranges']) == {2, 3, 7, 11}
        assert expand(ev[b['s']['evidence_id']]['ranges']) == {4, 10}
        assert ev[a['s']['evidence_id']]['row_count'] == 4
        assert a['s']['value'] == '14' and b['s']['value'] == '9'
        if not csv:
            assert ev[a['s']['evidence_id']]['ranges'] == ['청구내역!G2:G3', '청구내역!G7', '청구내역!G11']
            assert ev[a['n']['evidence_id']]['ranges'][0].startswith('청구내역!F')
        else:
            assert ev[a['s']['evidence_id']]['ranges'] == ['행 2–3, 7, 11 · 지급액']
        # 근거 번호는 행 우선 순서로 e1, e2, ...
        ids = [cell['evidence_id'] for row in result['rows'] for cell in row if cell['evidence_id']]
        assert ids == [f'e{i}' for i in range(1, len(ids) + 1)]
        assert set(ev) == set(ids)


def test_compress_ranges_xlsx_and_csv():
    numbers = list(range(45, 61)) + list(range(2, 32))
    xlsx = compress_ranges('F', '지급액', '청구내역', numbers)
    assert xlsx == ['청구내역!F2:F31', '청구내역!F45:F60']
    assert ', '.join(r.split('!')[1] for r in xlsx) == 'F2:F31, F45:F60'
    assert compress_ranges(None, '지급액', None, numbers) == ['행 2–31, 45–60 · 지급액']
    assert compress_ranges('F', '지급액', '청구내역', []) == []
    assert compress_ranges('F', '지급액', '청구 내역', [5]) == ["'청구 내역'!F5"]


def test_rounding_half_up_display():
    rows = [(date(2026, 1, 1), 'A', D('2.0')), (date(2026, 1, 2), 'A', D('2.5'))]
    result = run(make_table(rows), spec(measures=[{'id': 'a', 'func': 'avg', 'column': '지급액'}]))
    (row,) = by_key(result)
    assert row['a']['value'] == '2.25'
    assert row['a']['display'] == '2.3'


def test_money_sum_exact():
    rows = [(date(2026, 1, 1), 'A', D('0.1')), (date(2026, 1, 2), 'A', D('0.2')),
            (date(2026, 1, 3), 'B', D('1234567.50')), (date(2026, 1, 4), 'B', D('1000000'))]
    result = run(make_table(rows), spec(group_by=[{'column': '상품', 'month': False}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}]))
    a, b = by_key(result)
    assert a['s']['value'] == '0.3' and a['s']['display'] == '0.3'
    assert b['s']['value'] == '2234567.50' and b['s']['display'] == '2,234,567.50'


def test_sort_and_limit():
    rows = [(date(2026, 1, 1), p, D(v)) for p, v in [('A', '5'), ('B', '30'), ('C', '10'), ('D', '20'), ('B', '1')]]
    result = run(make_table(rows), spec(group_by=[{'column': '상품', 'month': False}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                         sort={'by': 's', 'desc': True}, limit=2))
    out = by_key(result)
    assert [(r['상품']['value'], r['s']['value']) for r in out] == [('B', '31'), ('D', '20')]
    asc = run(make_table(rows), spec(group_by=[{'column': '상품', 'month': False}],
                                      measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                      sort={'by': 's', 'desc': False}))
    assert [r['상품']['value'] for r in by_key(asc)] == ['A', 'C', 'D', 'B']
    by_group = run(make_table(rows), spec(group_by=[{'column': '상품', 'month': False}],
                                           measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                           sort={'by': '상품', 'desc': True}))
    assert [r['상품']['value'] for r in by_key(by_group)] == ['D', 'C', 'B', 'A']


def test_too_many_groups():
    rows = [(date(2026, 1, 1), p, D('1')) for p in 'ABC']
    with pytest.raises(ValueError, match='AGGREGATION_TOO_MANY_GROUPS'):
        run(make_table(rows), spec(group_by=[{'column': '상품', 'month': False}],
                                   measures=[{'id': 'n', 'func': 'count', 'column': None}]), max_groups=2)
    ok = run(make_table(rows), spec(group_by=[{'column': '상품', 'month': False}],
                                    measures=[{'id': 'n', 'func': 'count', 'column': None}]), max_groups=3)
    assert len(ok['rows']) == 3


def test_deadline_timeout():
    rows = [(date(2026, 1, 1), 'A', D('1'))] * 2500
    with pytest.raises(AggregationTimeout):
        run(make_table(rows), spec(measures=[{'id': 'n', 'func': 'count', 'column': None}]),
            deadline=time.monotonic() - 1)
    done = run(make_table(rows), spec(measures=[{'id': 'n', 'func': 'count', 'column': None}]),
               deadline=time.monotonic() + 60)
    assert done['rows'][0][0]['value'] == '2500'


# ------------------------------------------------------------------ edges

def test_growth_within_same_other_group():
    rows = [
        (date(2026, 1, 3), 'A', D('100')), (date(2026, 2, 3), 'A', D('200')),
        (date(2026, 1, 3), 'B', D('40')), (date(2026, 2, 3), 'B', D('10')),
        (date(2025, 12, 3), 'B', D('20')),
    ]
    result = run(make_table(rows), spec(group_by=[{'column': '상품', 'month': False}, {'column': '청구일', 'month': True}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                         growth=[{'measure_id': 's'}]))
    month_key = result['columns'][1]['key']
    got = {(r['상품']['value'], r[month_key]['value']): r['growth_s'] for r in by_key(result)}
    assert got[('A', '2026-02')]['display'] == '100.0%'
    assert got[('B', '2026-01')]['display'] == '100.0%'  # 2025-12 → 2026-01: 연도 넘김
    assert got[('B', '2026-02')]['display'] == '-75.0%'
    assert got[('A', '2026-01')]['reason'] == '전월 자료 없음'
    ev = result['evidence'][got[('B', '2026-02')]['evidence_id']]
    assert expand(ev['ranges']) == {4, 5}


def test_growth_when_previous_or_current_not_computable():
    rows = [(date(2026, 1, 3), 'A', NotNumber('x')), (date(2026, 2, 3), 'A', D('5')), (date(2026, 3, 3), 'A', None)]
    result = run(make_table(rows), spec(group_by=[{'column': '청구일', 'month': True}],
                                         measures=[{'id': 'a', 'func': 'avg', 'column': '지급액'}],
                                         growth=[{'measure_id': 'a'}]))
    jan, feb, mar = by_key(result)
    assert feb['growth_a']['reason'] == '전월 값 계산 불가'
    assert mar['growth_a']['reason'] == mar['a']['reason']
    assert mar['growth_a']['status'] == 'not_computable'


def test_filtered_rows_are_not_evidence_and_filter_text():
    result = run(make_table(SAMPLE), spec(filters=[{'column': '지급액', 'op': 'gte', 'value': '100'}],
                                           group_by=[{'column': '상품', 'month': False}],
                                           measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}]))
    (a,) = by_key(result)  # B 행은 모두 100 미만
    ev = result['evidence'][a['s']['evidence_id']]
    assert expand(ev['ranges']) == {2, 4, 6}
    assert '지급액 ≥ 100' in ev['filter_text'] and '상품 = A' in ev['filter_text']
    assert a['s']['value'] == '600.25'


def test_negative_and_thousands_display_and_count_display():
    rows = [(date(2026, 1, 1), 'A', D('-1234.5'))] + [(date(2026, 1, 1), 'A', D('0'))] * 1200
    result = run(make_table(rows), spec(measures=[{'id': 's', 'func': 'sum', 'column': '지급액'},
                                                   {'id': 'n', 'func': 'count', 'column': None},
                                                   {'id': 'a', 'func': 'avg', 'column': '지급액'}]))
    (row,) = by_key(result)
    assert row['s']['display'] == '-1,234.5'
    assert row['n']['display'] == '1,201'
    assert row['a']['display'] == '-1.0'  # -1234.5/1201 = -1.0279...


def test_spec_validation():
    t = make_table(SAMPLE)
    bad = [
        spec(measures=[]),
        spec(measures=[{'id': 's', 'func': 'sum', 'column': '상품'}]),  # 문자 열 합계
        spec(measures=[{'id': 's', 'func': 'median', 'column': '지급액'}]),
        spec(measures=[{'id': 's', 'func': 'count', 'column': None}], growth=[{'measure_id': 's'}]),  # 월 묶음 없음
        spec(group_by=[{'column': '상품', 'month': True}], measures=[{'id': 'n', 'func': 'count', 'column': None}]),
        spec(measures=[{'id': 'n', 'func': 'count', 'column': None}], sort={'by': 'zz', 'desc': True}),
        spec(measures=[{'id': 'n', 'func': 'count', 'column': None}], limit=0),
        spec(measures=[{'id': 'n', 'func': 'count', 'column': None}, {'id': 'n', 'func': 'sum', 'column': '지급액'}]),
    ]
    for item in bad:
        with pytest.raises(ValueError, match='AGGREGATION_SPEC_INVALID'):
            run(t, item)
