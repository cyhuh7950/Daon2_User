"""WO-N9 집계 계산·칸별 근거 시험 (aggregation_engine)."""
from __future__ import annotations

import re
import time
from datetime import date
from decimal import Context, Decimal

import pytest

from daon2_user_api.aggregation_engine import AggregationTimeout, compact_range, run
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


def expand(text):
    """근거 범위 한 줄(``시트!F: 2–31, 45–60`` 또는 ``행 2–31 · 열``)을 행 번호 집합으로 펼친다."""
    if text is None:
        return set()
    if text.startswith('행 '):
        body = text[2:].split(' · ')[0]
    else:
        ref = text.rpartition('!')[2]
        assert re.fullmatch(r'[A-Z]+: .+', ref), text
        body = ref.split(': ', 1)[1]
    numbers = set()
    for part in body.split(', '):
        lo, _, hi = part.partition('–')
        numbers.update(range(int(lo), int(hi or lo) + 1))
    return numbers


def growth_rows(result, entry):
    """증감률 근거: 이번 달·전월 근거 번호를 따라가 두 범위의 행을 합친다."""
    assert 'range' not in entry
    ev = result['evidence']
    rows = expand(ev[entry['current_evidence_id']]['range'])
    if entry['previous_evidence_id'] is not None:
        rows |= expand(ev[entry['previous_evidence_id']]['range'])
    return rows


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
    assert growth_rows(result, ev) == {2, 3}
    assert ev['current_evidence_id'] == feb['s']['evidence_id'] and ev['previous_evidence_id'] == jan['s']['evidence_id']
    assert result['evidence'][jan['growth_s']['evidence_id']]['previous_evidence_id'] is None
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
    ev = result['evidence'][cell['evidence_id']]
    assert ev['formula'] == '평균(지급액): 대상 행 없음'  # '합계 0 ÷ 0개' 같은 식을 쓰지 않는다
    assert ev['range'] is None and ev['row_count'] == 0
    # 아무 행도 맞지 않는 묶음 없는 집계: 한 줄, 건수 0, 합계·평균 계산 불가
    result = run(make_table(SAMPLE), spec(filters=[{'column': '상품', 'op': 'eq', 'value': 'Z'}], measures=MEASURES3))
    (row,) = by_key(result)
    assert row['n']['value'] == '0'
    assert (row['s']['status'], row['s']['reason']) == ('not_computable', '숫자 값 없음')
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
    assert expand(ev['range']) == {2, 5}
    assert any('숫자 아님 1행' in w for w in result['warnings'])


def _count_rows(table, flt):
    result = run(table, spec(filters=[flt], measures=[{'id': 'n', 'func': 'count', 'column': None}]))
    (row,) = by_key(result)
    return expand(result['evidence'][row['n']['evidence_id']]['range'])


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
        assert expand(ev[a['n']['evidence_id']]['range']) == {2, 3, 7, 8, 11}
        assert expand(ev[a['s']['evidence_id']]['range']) == {2, 3, 7, 11}
        assert expand(ev[a['a']['evidence_id']]['range']) == {2, 3, 7, 11}
        assert expand(ev[b['s']['evidence_id']]['range']) == {4, 10}
        assert ev[a['s']['evidence_id']]['row_count'] == 4
        assert a['s']['value'] == '14' and b['s']['value'] == '9'
        if not csv:
            assert ev[a['s']['evidence_id']]['range'] == '청구내역!G: 2–3, 7, 11'
            assert ev[a['n']['evidence_id']]['range'].startswith('청구내역!F: ')
        else:
            assert ev[a['s']['evidence_id']]['range'] == '행 2–3, 7, 11 · 지급액'
        # 근거 번호는 행 우선 순서로 e1, e2, ...
        ids = [cell['evidence_id'] for row in result['rows'] for cell in row if cell['evidence_id']]
        assert ids == [f'e{i}' for i in range(1, len(ids) + 1)]
        assert set(ev) == set(ids)


def test_compact_range_xlsx_and_csv():
    numbers = list(range(45, 61)) + list(range(2, 32))
    # 시트·열은 한 번만 쓰고 행 묶음을 잇는다(근거 한 칸에 문자열 하나).
    assert compact_range('F', '지급액', '청구내역', numbers) == '청구내역!F: 2–31, 45–60'
    assert compact_range(None, '지급액', None, numbers) == '행 2–31, 45–60 · 지급액'
    assert compact_range('F', '지급액', '청구내역', []) is None
    assert compact_range('F', '지급액', '청구 내역', [5]) == "'청구 내역'!F: 5"
    assert compact_range('F', '지급액', None, [5, 6]) == 'F: 5–6'


def test_compact_range_quotes_cell_reference_like_sheet_names():
    for name in ('A1', 'xfd100', 'R1C1', 'R', 'C', 'rc'):
        assert compact_range('F', '지급액', name, [2]) == f"'{name}'!F: 2"
    for name in ('청구내역', 'Sheet1', 'ABCD1', 'Data'):
        assert compact_range('F', '지급액', name, [2]) == f'{name}!F: 2'


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
    assert growth_rows(result, ev) == {4, 5}


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
    assert expand(ev['range']) == {2, 4, 6}
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


# ------------------------------------------------------------------ fix round 1

def test_count_with_column_counts_all_rows():
    rows = [(date(2026, 1, 1), 'A', D('1')), (date(2026, 1, 2), 'A', None),
            (date(2026, 1, 3), 'A', NotNumber('x')), (date(2026, 1, 4), 'A', None)]
    result = run(make_table(rows), spec(measures=[{'id': 'n', 'func': 'count', 'column': '지급액'}]))
    (row,) = by_key(result)
    assert row['n']['value'] == '4'
    ev = result['evidence'][row['n']['evidence_id']]
    assert expand(ev['range']) == {2, 3, 4, 5}
    assert ev['range'] == '청구내역!G: 2–5'
    assert ev['row_count'] == 4
    assert '건수' in ev['formula']


def test_sum_without_numbers_not_computable_and_next_growth():
    rows = [(date(2026, 1, 1), 'A', NotNumber('q')), (date(2026, 1, 2), 'A', None), (date(2026, 2, 1), 'A', D('5'))]
    result = run(make_table(rows), spec(group_by=[{'column': '청구일', 'month': True}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                         growth=[{'measure_id': 's'}]))
    jan, feb = by_key(result)
    assert (jan['s']['status'], jan['s']['reason'], jan['s']['value']) == ('not_computable', '숫자 값 없음', None)
    assert feb['s']['value'] == '5'
    assert (feb['growth_s']['status'], feb['growth_s']['reason']) == ('not_computable', '전월 값 계산 불가')


def test_sum_of_real_zeros_stays_zero():
    rows = [(date(2026, 1, 1), 'A', D('5')), (date(2026, 1, 2), 'A', D('-5')), (date(2026, 1, 3), 'A', NotNumber('q'))]
    result = run(make_table(rows), spec(measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}]))
    (row,) = by_key(result)
    assert (row['s']['status'], row['s']['value'], row['s']['display']) == ('ok', '0', '0')


def test_display_rounds_from_exact_fraction():
    def avg(values):
        rows = [(date(2026, 1, 1), 'A', D(v)) for v in values]
        (row,) = by_key(run(make_table(rows), spec(measures=[{'id': 'a', 'func': 'avg', 'column': '지급액'}])))
        return row['a']
    assert avg(['0.0499999999999999999999999999999'])['display'] == '0.0'
    big = avg(['12345678901234567890123456789.04', '12345678901234567890123456789.06'])
    assert big['display'] == '12,345,678,901,234,567,890,123,456,789.1'
    assert avg(['-0.05'])['display'] == '-0.1'
    assert avg(['1', '2', '2'])['display'] == '1.7'
    # 증감률: (x − 3) / 3 × 100 이 정확히 −33.35 → −33.4
    rows = [(date(2026, 1, 1), 'A', D('3')), (date(2026, 2, 1), 'A', D('1.9995'))]
    result = run(make_table(rows), spec(group_by=[{'column': '청구일', 'month': True}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                         growth=[{'measure_id': 's'}]))
    assert by_key(result)[1]['growth_s']['display'] == '-33.4%'
    # 전월 3 → 1: −66.666…% (반올림 경계 아님) → −66.7%
    rows = [(date(2026, 1, 1), 'A', D('3')), (date(2026, 2, 1), 'A', D('1'))]
    result = run(make_table(rows), spec(group_by=[{'column': '청구일', 'month': True}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                         growth=[{'measure_id': 's'}]))
    assert by_key(result)[1]['growth_s']['display'] == '-66.7%'


def test_blank_group_sorts_last_both_directions():
    rows = [(date(2026, 1, 1), p, D('1')) for p in ['B', None, 'A', 'C']]
    for desc, expected in ((False, ['A', 'B', 'C', None]), (True, ['C', 'B', 'A', None])):
        result = run(make_table(rows), spec(group_by=[{'column': '상품', 'month': False}],
                                             measures=[{'id': 'n', 'func': 'count', 'column': None}],
                                             sort={'by': '상품', 'desc': desc}))
        assert [r['상품']['value'] for r in by_key(result)] == expected
        assert by_key(result)[-1]['상품']['display'] == '(빈칸)'


# ------------------------------------------------------------------ final review fixes

def test_growth_previous_evidence_exists_when_cut_by_limit():
    rows = [(date(2026, 1, 9), 'A', D('100')), (date(2026, 2, 9), 'A', D('300')), (date(2026, 3, 9), 'A', D('150'))]
    result = run(make_table(rows), spec(group_by=[{'column': '청구일', 'month': True}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                         growth=[{'measure_id': 's'}], sort={'by': 's', 'desc': False}, limit=1))
    (jan,) = by_key(result)  # 가장 작은 1월만 남는다
    assert jan['청구일(월)']['value'] == '2026-01'
    result = run(make_table(rows), spec(group_by=[{'column': '청구일', 'month': True}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                         growth=[{'measure_id': 's'}], sort={'by': 's', 'desc': True}, limit=1))
    (feb,) = by_key(result)  # 2월만 보이고 1월 행은 잘렸다
    ev = result['evidence'][feb['growth_s']['evidence_id']]
    previous = result['evidence'][ev['previous_evidence_id']]
    assert expand(previous['range']) == {2} and previous['row_count'] == 1
    assert '2026-01' in previous['filter_text']
    assert growth_rows(result, ev) == {2, 3}


def test_growth_evidence_reuses_measure_entries_without_copying_ranges():
    rows = [(date(2026, 1, 9), 'A', D('1')), (date(2026, 2, 9), 'A', D('2')), (date(2026, 3, 9), 'A', D('3'))]
    result = run(make_table(rows), spec(group_by=[{'column': '청구일', 'month': True}],
                                         measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}],
                                         growth=[{'measure_id': 's'}]))
    ranges = [e['range'] for e in result['evidence'].values() if 'range' in e]
    assert len(ranges) == 3  # 달마다 한 번만
    for entry in result['evidence'].values():
        if 'range' not in entry:
            assert set(entry) == {'current_evidence_id', 'previous_evidence_id', 'filter_text', 'formula', 'row_count', 'excluded'}


def test_cancel_check_is_called_and_propagates():
    rows = [(date(2026, 1, 1), 'A', D('1'))] * 2500
    calls = []

    class Cancelled(RuntimeError):
        pass

    def cancel():
        calls.append(1)
        if len(calls) >= 2:
            raise Cancelled('cancelled')

    with pytest.raises(Cancelled):
        run(make_table(rows), spec(measures=[{'id': 'n', 'func': 'count', 'column': None}]), cancel_check=cancel)
    seen = []
    run(make_table(rows), spec(measures=[{'id': 'n', 'func': 'count', 'column': None}]), cancel_check=lambda: seen.append(1))
    assert len(seen) >= 3  # 시작·반복 중간·끝


def _representative(table):
    from daon2_user_api.aggregation_present import build_chart, content_size_ok, summary_sentences
    from daon2_user_api.aggregation_spec import describe, normalize
    raw = {'filters': [], 'group_by': [{'column': '청구일', 'month': True}, {'column': '상품', 'month': False}],
           'measures': [{'id': 'cnt', 'func': 'count', 'column': None}, {'id': 'amt', 'func': 'sum', 'column': '지급액'}],
           'growth': [{'measure_id': 'cnt'}, {'measure_id': 'amt'}], 'sort': None, 'limit': None, 'unsupported': []}
    normalized, warnings = normalize(raw, table)
    result = run(table, normalized)
    body = {'request': '월별·상품별 청구 건수와 지급액 합계, 전월 대비 증감률', 'source': {'source_version_id': 'v', 'sha256': '0' * 64,
            'file_name': table.file_name, 'sheet': table.sheet, 'header_row': 1}, 'spec': normalized, 'spec_raw': raw,
            'conditions_text': describe(normalized), 'columns': result['columns'], 'rows': result['rows'], 'evidence': result['evidence'],
            'chart': build_chart(result, normalized), 'summary': summary_sentences(result, normalized),
            'warnings': [*warnings, *result['warnings']], 'stats': {'rows_read': len(table.rows), 'elapsed_ms': 0}}
    return body, content_size_ok(body)


def test_representative_request_on_100k_rows_fits_storage_limit():
    """대표 요청(월별·상품별 건수·지급액 합계·전월 대비 증감률)이 10만 행(CSV·XLSX 모양)에서 2 MiB 안에 든다."""
    import json
    import random
    from dataclasses import replace

    from daon2_user_api.table_reader import read_table
    rng = random.Random(20261126)
    products = ['암보험', '실손보험', '상해보험', '여행자보험', '치아보험']
    lines = ['청구번호,청구일,상품,지급액']
    for i in range(100_000):
        lines.append(f'C{i + 1:07d},2026-{rng.randint(1, 6):02d}-{rng.randint(1, 28):02d},{rng.choice(products)},{rng.randint(1, 999) * 1000}')
    table = read_table('\n'.join(lines).encode(), file_name='claims.csv', source_format='csv', sheet=None, header_row=1)
    body, ok = _representative(table)
    assert ok, len(json.dumps(body, ensure_ascii=False).encode())
    xlsx = replace(table, source_format='xlsx', sheet='청구내역', file_name='claims.xlsx',
                   columns=tuple(Column(c.name, 'ABCD'[i], i, c.kind) for i, c in enumerate(table.columns)))
    body, ok = _representative(xlsx)
    assert ok, len(json.dumps(body, ensure_ascii=False).encode())
