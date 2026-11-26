"""WO-N9 집계 조건 스키마·정규화·검사 시험 (aggregation_spec)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from daon2_user_api import aggregation_engine
from daon2_user_api.aggregation_spec import SPEC_SCHEMA, SpecInvalid, SpecUnsupported, describe, normalize
from daon2_user_api.table_reader import Column, Table

D = Decimal


def make_table():
    columns = (Column('청구일', 'E', 4, 'date'), Column('상품', 'F', 5, 'text'), Column('지급금액', 'G', 6, 'number'))
    rows = ((date(2025, 1, 5), '암보험', D(100)), (date(2025, 2, 5), '암보험', D(150)),
            (date(2025, 2, 9), '실손', D(40)))
    return Table(file_name='t.xlsx', source_format='xlsx', sheet='S', header_row=1, columns=columns,
                 rows=rows, row_numbers=(2, 3, 4))


def raw(**kw):
    base = {'filters': [], 'group_by': [], 'measures': [{'id': 'm1', 'func': 'count', 'column': None}],
            'growth': [], 'sort': None, 'limit': None, 'unsupported': []}
    base.update(kw)
    return base


def reasons_of(table, data):
    with pytest.raises(SpecInvalid) as info:
        normalize(data, table)
    return info.value.reasons


def test_valid_spec_normalized():
    spec, warnings = normalize(raw(
        filters=[{'column': '상품', 'op': 'eq', 'value': '암보험'}],
        group_by=[{'column': '청구일', 'month': True}],
        measures=[{'id': 'cnt', 'func': 'count', 'column': None}, {'id': 'tot', 'func': 'sum', 'column': '지급금액'}],
        growth=[{'measure_id': 'tot'}], sort={'by': '청구일', 'desc': True}, limit=10), make_table())
    assert warnings == []
    assert spec == {
        'filters': [{'column': '상품', 'op': 'eq', 'value': '암보험'}],
        'group_by': [{'column': '청구일', 'month': True}],
        'measures': [{'id': 'cnt', 'func': 'count', 'column': None}, {'id': 'tot', 'func': 'sum', 'column': '지급금액'}],
        'growth': [{'measure_id': 'tot'}], 'sort': {'by': '청구일(월)', 'desc': True}, 'limit': 10}


def test_unknown_column_retries_with_reason():
    reasons = reasons_of(make_table(), raw(measures=[{'id': 'm1', 'func': 'sum', 'column': '지급액'}]))
    assert '없는 열: 지급액' in reasons


def test_sum_on_text_column_invalid():
    reasons = reasons_of(make_table(), raw(measures=[{'id': 'm1', 'func': 'sum', 'column': '상품'}]))
    assert any('상품' in r and '숫자' in r for r in reasons)


def test_growth_without_month_invalid():
    reasons = reasons_of(make_table(), raw(growth=[{'measure_id': 'm1'}]))
    assert any('월 묶기' in r for r in reasons)


def test_filter_value_missing_fails_fast():
    with pytest.raises(ValueError) as info:
        normalize(raw(filters=[{'column': '상품', 'op': 'in', 'value': ['암보험', '치아보험']}]), make_table())
    assert str(info.value) == 'AGGREGATION_FILTER_VALUE_NOT_FOUND:치아보험(상품)'


def test_partial_unsupported_warns():
    spec, warnings = normalize(raw(unsupported=['고객 나이별 분석']), make_table())
    assert warnings == ['하지 않은 요청: 고객 나이별 분석']
    assert spec['measures']


def test_all_unsupported_raises():
    with pytest.raises(SpecUnsupported):
        normalize(raw(measures=[], unsupported=['예측']), make_table())


def test_describe_sentence():
    spec = {'filters': [{'column': '상품', 'op': 'eq', 'value': '암보험'}],
            'group_by': [{'column': '상품', 'month': False}, {'column': '청구일', 'month': True}],
            'measures': [{'id': 'm1', 'func': 'count', 'column': None}, {'id': 'm2', 'func': 'sum', 'column': '지급액'}],
            'growth': [{'measure_id': 'm2'}], 'sort': None, 'limit': None}
    assert describe(spec) == '필터: 상품=암보험 · 묶기: 상품, 청구일(월) · 집계: 건수, 합계(지급액) · 비교: 전월 대비 증감률'


def test_normalize_then_run_end_to_end():
    table = make_table()
    spec, _ = normalize(raw(
        filters=[{'column': '지급금액', 'op': 'between', 'value': [10, '200']},
                 {'column': '청구일', 'op': 'date_between', 'value': ['2025-01-01', '2025-12-31']},
                 {'column': '상품', 'op': 'ne', 'value': '실손'}],
        group_by=[{'column': '청구일', 'month': True}],
        measures=[{'id': 'a', 'func': 'avg', 'column': '지급금액'}], growth=[{'measure_id': 'a'}],
        sort={'by': 'growth_a', 'desc': True}, limit=5), table)
    result = aggregation_engine.run(table, spec)
    assert [c['key'] for c in result['columns']] == ['청구일(월)', 'a', 'growth_a']
    assert len(result['rows']) == 2


@pytest.mark.parametrize('value', [1.5, True, None, {'a': 1}])
def test_filter_value_bad_type_invalid(value):
    reasons = reasons_of(make_table(), raw(filters=[{'column': '지급금액', 'op': 'eq', 'value': value}]))
    assert reasons


def test_filter_list_item_float_invalid():
    assert reasons_of(make_table(), raw(filters=[{'column': '지급금액', 'op': 'between', 'value': [1, 2.5]}]))


def test_missing_and_duplicate_measure_ids_assigned():
    spec, _ = normalize(raw(measures=[{'func': 'count', 'column': None}, {'id': 'x', 'func': 'count', 'column': None},
                                      {'id': 'x', 'func': 'sum', 'column': '지급금액'}]), make_table())
    ids = [m['id'] for m in spec['measures']]
    assert len(set(ids)) == 3 and ids[1] == 'x'


def test_limit_and_group_limits():
    table = make_table()
    assert reasons_of(table, raw(limit=51))
    assert reasons_of(table, raw(group_by=[{'column': '상품', 'month': False}, {'column': '청구일', 'month': True},
                                           {'column': '지급금액', 'month': False}]))
    assert reasons_of(table, raw(group_by=[{'column': '상품', 'month': True}]))
    assert reasons_of(table, raw(sort={'by': '없는키', 'desc': False}))


def test_schema_has_unsupported():
    assert SPEC_SCHEMA['properties']['unsupported']['type'] == 'array'


# ---- 검토 보강 1차 -------------------------------------------------------

@pytest.mark.parametrize('data', [
    raw(group_by=[{'column': ['a'], 'month': False}]),
    raw(group_by=[{'column': {'a': 1}, 'month': False}]),
    raw(measures=[{'id': 'm1', 'func': 'sum', 'column': ['x']}]),
    raw(measures=[{'id': ['a'], 'func': 'count', 'column': None}]),
    raw(filters=[{'column': ['상품'], 'op': 'eq', 'value': 'x'}]),
])
def test_unhashable_names_give_reasons_not_typeerror(data):
    assert reasons_of(make_table(), data)


@pytest.mark.parametrize('data', [
    raw(filters='상품=암보험'),
    raw(filters={'column': '상품', 'op': 'eq', 'value': 'x'}),
    raw(group_by={'column': '상품', 'month': False}),
    raw(growth={'measure_id': 'm1'}),
    raw(unsupported=[1]),
    raw(unsupported='예측'),
    raw(measures={'id': 'm1'}),
])
def test_non_list_containers_rejected(data):
    assert any('형식 오류' in r for r in reasons_of(make_table(), data))


def test_unknown_keys_rejected():
    table = make_table()
    assert '알 수 없는 항목: having' in reasons_of(table, raw(having='x'))
    assert '알 수 없는 항목: x' in reasons_of(table, raw(filters=[{'column': '상품', 'op': 'eq', 'value': '암보험', 'x': 1}]))
    assert '알 수 없는 항목: y' in reasons_of(table, raw(measures=[{'id': 'm1', 'func': 'count', 'column': None, 'y': 1}]))


def test_item_count_cap():
    table = make_table()
    many = [{'column': '상품', 'op': 'eq', 'value': '암보험'}] * 21
    assert reasons_of(table, raw(filters=many))
    assert reasons_of(table, raw(measures=[{'id': f'a{i}', 'func': 'count', 'column': None} for i in range(21)]))


def test_between_list_copied_and_unsupported_truncated():
    table = make_table()
    source = [10, 20]
    spec, warnings = normalize(raw(filters=[{'column': '지급금액', 'op': 'between', 'value': source}],
                                   unsupported=['가' * 300]), table)
    assert spec['filters'][0]['value'] == [10, 20] and spec['filters'][0]['value'] is not source
    assert warnings == ['하지 않은 요청: ' + '가' * 200]


# ------------------------------------------------------------------ final review fixes

def test_group_by_only_on_text_columns():
    t = make_table()
    reasons = reasons_of(t, raw(group_by=[{'column': '지급금액', 'month': False}]))
    assert any('글자 열' in r and '지급금액' in r for r in reasons), reasons
    reasons = reasons_of(t, raw(group_by=[{'column': '청구일', 'month': False}]))
    assert any('글자 열' in r and '청구일' in r for r in reasons), reasons
    spec, _ = normalize(raw(group_by=[{'column': '상품', 'month': False}, {'column': '청구일', 'month': True}]), t)
    assert spec['group_by'] == [{'column': '상품', 'month': False}, {'column': '청구일', 'month': True}]
    # 계산기도 같은 규칙을 지킨다.
    with pytest.raises(ValueError, match='AGGREGATION_SPEC_INVALID'):
        aggregation_engine.run(t, {'filters': [], 'group_by': [{'column': '지급금액', 'month': False}],
                                   'measures': [{'id': 'n', 'func': 'count', 'column': None}], 'growth': [], 'sort': None, 'limit': None})


def test_leading_zero_codes_stay_distinct_groups_and_filter_exactly():
    from daon2_user_api.table_reader import read_table
    csv = '상품코드,월,지급액\n0101,2026-01-05,100\n101,2026-01-06,200\n0101,2026-02-01,300\n102,2026-03-01,1\n'.encode()
    t = read_table(csv, file_name='a.csv', source_format='csv', sheet=None, header_row=1)
    assert [(c.name, c.kind) for c in t.columns] == [('상품코드', 'text'), ('월', 'date'), ('지급액', 'number')]
    spec, _ = normalize(raw(group_by=[{'column': '상품코드', 'month': False}],
                            measures=[{'id': 's', 'func': 'sum', 'column': '지급액'}]), t)
    result = aggregation_engine.run(t, spec)
    assert [[c['display'] for c in row] for row in result['rows']] == [['0101', '400'], ['101', '200'], ['102', '1']]
    spec, _ = normalize(raw(filters=[{'column': '상품코드', 'op': 'eq', 'value': '0101'}]), t)
    (row,) = aggregation_engine.run(t, spec)['rows']
    assert row[0]['value'] == '2'
    spec, _ = normalize(raw(filters=[{'column': '상품코드', 'op': 'eq', 'value': 101}]), t)
    (row,) = aggregation_engine.run(t, spec)['rows']
    assert row[0]['value'] == '1'


def test_unsupported_warning_hides_numbers_not_in_request():
    t = make_table()
    request = '2026년 상품별 건수를 보여주고 2027년 지급액 999억 예측도 해줘'
    _, warnings = normalize(raw(unsupported=['2027년 지급액 999억 예측', '다른 파일 3개와 비교', '12.5% 성장 가정']), t, request=request)
    assert warnings == ['하지 않은 요청: 2027년 지급액 999억 예측', '하지 않은 요청: 다른 파일 …개와 비교',
                        '하지 않은 요청: ….…% 성장 가정']
    # 요청 글을 주지 않으면 모든 숫자를 가린다.
    _, warnings = normalize(raw(unsupported=['2027년 예측']), t)
    assert warnings == ['하지 않은 요청: …년 예측']
    # 요청 글의 숫자 일부만 맞는 더 긴 숫자도 가린다(숫자 묶음 단위로 비교).
    _, warnings = normalize(raw(unsupported=['20270 예측']), t, request='2027 예측')
    assert warnings == ['하지 않은 요청: … 예측']
    with pytest.raises(SpecUnsupported) as caught:
        normalize(raw(measures=[], unsupported=['2027년 999억 예측']), t, request='2027년 예측')
    assert caught.value.items == ['2027년 …억 예측']
