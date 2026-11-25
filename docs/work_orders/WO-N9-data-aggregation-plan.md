# WO-N9 데이터 집계 구현 계획

> **에이전트 작업자용:** 필수 하위 스킬: superpowers:subagent-driven-development(권장) 또는 superpowers:executing-plans로 작업 단위별로 실행한다. 단계는 체크박스(`- [ ]`)로 추적한다.

**목표:** 스튜디오 새 유형 `data_aggregation`을 만든다. 요청 글과 표 소스 한 개(XLSX·CSV)로 집계표·차트·칸별 계산 근거를 만든다. 모델은 집계 조건만 제안하고, 서버가 허용된 연산만 계산한다.

**구조:** 네 개의 순수 모듈을 만든다.
- `table_reader.py`: 표 읽기
- `aggregation_spec.py`: 조건 정규화·검사
- `aggregation_engine.py`: 계산·근거
- `aggregation_present.py`: 차트·요약

생성기가 이들을 묶고, 스튜디오 작업자가 원본 저장소에서 해시를 확인한 원본을 읽는다. 큰 XLSX는 소스 처리에서 "집계 전용"으로 완료시키고 질문 근거에서 뺀다.

**기술:** Python 3(표준 `decimal`·`zipfile`·`xml.etree.ElementTree.iterparse`·`csv`, 새 의존성 없음), PostgreSQL 마이그레이션, React(JSX), `node --test`, pytest.

**설계서(정본):** `docs/work_orders/WO-N9-data-aggregation.md`(2026-11-25 승인). 계획과 다르면 설계서를 따른다.

## 전역 제약

**근거 원칙**
- 원본값과 계산값을 화면·내려받기 모두에서 구분한다.
- 계산값 칸에는 계산 근거를 단다: 파일, 시트, 원본 범위(CSV는 행·열), 필터 문장, 계산식, 대상 행 수, 제외 칸 수와 이유.
- 증감률 = (이번 − 전기) ÷ 전기 × 100.
  - 전기 값이 0이면 `계산 불가`, 이유 `전월 값 0`.
  - 전기 자료가 없으면 `계산 불가`, 이유 `전월 자료 없음`.
  - 비교 기준은 달력상 바로 앞 달이다.
- 평균의 대상 행이 0개면 `계산 불가`.
- 숫자 아님·빈칸은 합계·평균에서 빼고 개수를 근거에 적는다. 건수는 행 수를 센다.
- 표시는 소수 첫째 자리까지 사사오입(ROUND_HALF_UP), 저장은 정확한 `Decimal` 문자열이다. 금액 합계는 원본 자릿수를 유지한다.
- 숫자가 든 요약 문장은 서버가 정해진 틀로만 만든다. 모델 문장은 넣지 않는다.
- 차트 값은 집계표 저장값과 같은 값에서 만든다.

**외부 전송**
- 모델에는 열 이름, 열 종류(`date`·`number`·`text`), 행 수, 요청 글만 보낸다.
- 셀 값과 값 목록은 보내지 않는다.
- 모델 호출은 기존 `StudioTextGenerator`(`StudioEgressGate`)로만 한다.
- 필터 값이 열에 없으면 실패 메시지 `그런 값이 없습니다: {값}({열})`.

**격리와 한도**
- 입력은 그 노트북·그 판의 원본만 쓴다. 저장소의 원본은 크기와 sha256이 맞을 때만 읽는다.
- 한도(측정 후 작업 9에서 조정):
  - 파일 20 MB
  - 행 100,000
  - 열 100
  - 결과 묶음 2,000
  - 실행 60초
- 판 크기는 2 MiB(`MAX_REVISION_BYTES`)다. 넘으면 실패 메시지 `결과가 너무 큽니다. 조건을 좁혀 다시 생성해 주세요`.

**범위 밖 요청**
- 일부만 범위 밖이면 계산 가능한 부분만 완료하고, 경고 `하지 않은 요청: …`를 단다.
- 전부 범위 밖이면 실패 메시지 `이 요청은 데이터 집계 1차 범위에서 할 수 없습니다`.

**큰 XLSX**
- 2,048셀 초과 XLSX는 "집계 전용" 소스로 받는다.
- 질문 근거(색인·검색)에서는 빠진다.
- 이 소스만 골라 질문하면 안내 `이 표는 데이터 집계에만 쓸 수 있습니다`.

**화면·작업 방식**
- 화면 원칙: 칸 안에서만 스크롤하고, 페이지 전체 스크롤은 없다. 문구는 `studio-messages.ko.js`에 둔다.
- 작업: main에서 개발하지 않는다. `D:\tmp\daon2-user-n9` 작업 폴더(+ node_modules junction)에서 하고, PR Broker로 병합한다.
- 새 의존성·새 컨테이너·외부 서비스는 없다. ysna는 ARM64다.

## 검토 초점

시험으로 다 막지 못했을 입력입니다. 각 시험은 담당 작업에 들어 있습니다.

1. **혼합 숫자 표기:** `1,234,000`, `₩1,234`, `(12,000)`, ` 3000 `, `3.0E+3`, 빈칸, `-`가 한 열에 섞인 지급액 열. 숫자는 정확히 읽고, 나머지는 "숫자 아님"으로 센다. 조용한 0은 없다. → 작업 2 `test_number_parsing_mixed_column`
2. **XLSX 날짜 일련번호와 1904 기준, 글 날짜:** `2026-03-05`, `2026.03.05`, `2026/3/5`가 섞인 청구일 열. 같은 달로 묶여야 한다. → 작업 2 `test_date_parsing_serial_and_text`
3. **빈 달:** 1월·3월만 있고 2월이 없는 상품. 3월 증감률은 `계산 불가(전월 자료 없음)`이어야 한다. 1월과 비교하면 안 된다. → 작업 3 `test_growth_gap_month_is_not_computable`
4. **CP949 CSV:** 머리글이 한글이고 BOM이 없다. 열 이름이 깨지지 않아야 한다. → 작업 2 `test_csv_cp949_headers`
5. **모델이 없는 열이나 비슷한 이름을 쓰는 경우:** 예를 들어 "지급금액" 열에 "지급액"을 쓴다. 근접 이름으로 몰래 바꾸지 않고, 이유를 붙여 한 번 다시 묻는다. → 작업 4 `test_unknown_column_retries_with_reason`

---

## 파일 구조

| 파일 | 책임 |
| --- | --- |
| `services/api/migrations/versions/0089_data_aggregation.py`·`.sql` (새) | `studio_v2_outputs.type_id` 허용값에 `data_aggregation` 추가 |
| `services/api/src/daon2_user_api/table_reader.py` (새) | XLSX·CSV 표 읽기(한도·열 종류·행 위치) |
| `services/api/src/daon2_user_api/aggregation_spec.py` (새) | 집계 조건 JSON 스키마·정규화·검사·범위 밖 요청 |
| `services/api/src/daon2_user_api/aggregation_engine.py` (새) | 필터·묶기·집계·증감률·정렬, 칸별 근거·범위 압축 |
| `services/api/src/daon2_user_api/aggregation_present.py` (새) | 차트 정의, 요약 문장, 조건 요약 문장 |
| `studio_v2_types.py`, `studio_v2_postgres.py`(TYPE_LABELS), 준비 상태 허용 목록(`cloud_storage.py`, `runtime.py`, `question_answering_postgres.py`) | 유형 등록, 0089 허용 |
| `studio_original_reader.py` (새), `studio_generators.py`, `studio_v2_worker.py`, `deploy/daon2-user/compose.yaml`·`compose.ysna.yaml` | 원본 읽기, 생성기, 작업자 연결·배포 설정 |
| `document_processing_postgres.py`, `xlsx_source.py`(예외 구분), 질문 경로 | 집계 전용 소스 |
| `studio_v2_export.py`, `studio_v2_routes.py`, `studio_v2_service.py` | XLSX 3시트·CSV 내려받기, 표 정보 조회 API |
| `packages/ui/src/…`(타일·설정·보기·소스 표시), `apps/web/lib/studio-v2-api.js`, `bff-api-proxy.js`, OpenAPI 계약 | 화면 |
| 설명서 2-22, `WORK_STATUS.md` | 문서 |

---

### Task 1 (작업 1): 유형 등록과 DB 허용값

**파일:**
- 새로 만들기: `services/api/migrations/versions/0089_data_aggregation.py`·`.sql`
- 수정:
  - `studio_v2_types.py`(`STUDIO_V2_TYPES`, `_TILE_TYPES`, `validate_settings`)
  - `studio_v2_postgres.py:26`(`TYPE_LABELS`)
  - 준비 상태 허용 목록 전부. `'0088'`이 있는 곳마다 `'0089'`를 더하고, 시험의 미지원 탐침은 `'0090'`으로 옮긴다.
- 시험: `services/api/tests/test_data_aggregation_type.py`(새). 기존 마이그레이션·준비 상태·유형 개수 시험도 갱신한다.

**연결:**
- 제공:
  - 유형 `data_aggregation`, 화면 이름 `데이터 집계`, `export_formats=("xlsx","csv")`
  - 설정 스키마:
    - `aggregation_request` 문자열, 최대 2000
    - `table_source_version_id` 문자열, 최대 120
    - `sheet` 문자열, 최대 120
    - `header_row` 정수, 1~50
  - `validate_settings`: `aggregation_request`(공백 아님)와 `table_source_version_id`가 없으면 `ValueError("STUDIO_INPUT_INVALID")`

- [ ] **1단계: 실패하는 시험**
  - `test_type_registered_with_formats_and_schema`
  - `test_validate_requires_request_and_table_source`: 빈 요청, 공백 요청, 소스 없음 → ValueError
  - `test_migration_0089_adds_type_keeps_12_existing`: 기존 12개 값과 `data_aggregation`, 제약 이름 `studio_v2_outputs_type_id_check`, downgrade 가드 `DATA_AGGREGATION_FORWARD_RECOVERY_REQUIRED`
  - `test_readiness_accepts_0089`
  - `test_available_types_lists_data_aggregation_last`
- [ ] **2단계: 실행해 실패 확인**: `cd services/api && PYTHONPATH="src;tests" <venv python> -m pytest -q -p no:cacheprovider tests/test_data_aggregation_type.py`
- [ ] **3단계: 구현.** 마이그레이션 형식은 `0088_web_page.py`를 따른다(`revision='0089'`, `down_revision='0088'`). `TYPE_LABELS["data_aggregation"]="데이터 집계"`.
- [ ] **4단계: 통과 확인.** 전체 API 시험에서 새 실패 0(알려진 9건 제외).
- [ ] **5단계: 커밋** `WO-N9 data_aggregation 유형·DB 허용값`

---

### Task 2 (작업 2): 표 읽기

**파일:**
- 새로 만들기: `services/api/src/daon2_user_api/table_reader.py`
- 시험: `services/api/tests/test_table_reader.py`(새, 시험 안에서 작은 XLSX를 zipfile로 만들어 쓴다)

**연결:**
- 제공:
  - `class TableLimits(max_bytes=20*1024*1024, max_rows=100_000, max_columns=100)`
  - `class TableReadError(Exception)`: `.code`는 다음 중 하나
    - `TABLE_TOO_LARGE`
    - `TABLE_FORMAT_UNSUPPORTED`
    - `TABLE_SHEET_NOT_FOUND`
    - `TABLE_HEADER_INVALID`
    - `TABLE_ENCODING_UNSUPPORTED`
    - `TABLE_TIMEOUT`
  - `@dataclass(frozen=True) Column(name: str, letter: str|None, index: int, kind: Literal["date","number","text"])`
    - XLSX면 `letter`가 열 문자, CSV면 None
  - `@dataclass(frozen=True) Table(file_name, source_format: Literal["xlsx","csv"], sheet: str|None, header_row: int, columns: tuple[Column,...], rows: tuple[tuple[object,...],...], row_numbers: tuple[int,...])`
    - `rows`의 값은 열 종류에 따라 `Decimal`, `date`, `str`, 또는 문자열 표지 `NotNumber(raw)`, `NotDate(raw)`, `None`(빈칸)
    - `row_numbers`는 원본 행 번호(XLSX 행 번호, CSV는 1부터 센 줄 번호로 머리글 포함)
  - `list_sheets(content: bytes) -> list[str]`
  - `read_table(content: bytes, *, file_name: str, source_format: str, sheet: str|None, header_row: int, limits: TableLimits = TableLimits(), deadline: float|None = None) -> Table`
  - `profile(table: Table) -> dict`: `{"columns":[{"name","kind"}], "row_count": n}`. 값은 넣지 않는다.

- [ ] **1단계: 실패하는 시험**(각 하나씩)
  - `test_xlsx_over_2048_cells_reads`(1,000행 × 8열)
  - `test_xlsx_header_row_and_skip_title_rows`(header_row=3)
  - `test_duplicate_and_blank_headers_named`: `지급액`, `지급액_2`, 빈 머리글은 `열 C`
  - `test_number_parsing_mixed_column`: `1,234,000`, `₩1,234`, `(12,000)`, ` 3000 `는 숫자(-12000 포함)이고, `-`, `abc`는 NotNumber, 빈칸은 None
  - `test_date_parsing_serial_and_text`: 일련번호 46086, 1904 기준 일련번호, `2026-03-05`·`2026.03.05`·`2026/3/5`
  - `test_column_kind_inference`: 비어 있지 않은 칸의 90% 이상이 숫자면 number, 날짜면 date, 아니면 text
  - `test_csv_utf8_bom_and_tab`
  - `test_csv_cp949_headers`
  - `test_limits_rows_columns_bytes`: 각각 `TABLE_TOO_LARGE`
  - `test_deadline_raises_timeout`
  - `test_profile_has_no_cell_values`: 프로필 JSON에 시험 값 문자열이 없다
  - `test_sheet_not_found`
- [ ] **2단계: 실행해 실패 확인**
- [ ] **3단계: 구현**
  - XLSX는 `zipfile`과 `ElementTree.iterparse`로 시트 XML을 행 단위로 읽고, 필요한 열만 저장한다.
  - 공유 문자열·날짜 서식·1904 판단은 `xlsx_source.py`의 내부 함수(`_parts`, `_number`, `_display_date`, 서식 판단)를 가져다 써도 된다. 단 `read_xlsx`의 한도와 동작은 바꾸지 않는다.
  - 압축 폭탄 방어: 압축을 푼 총량을 `max_bytes × 4`로 제한한다.
  - CSV는 `utf-8-sig`로 먼저 해독하고, 실패하면 `cp949`로 해독한다. 구분자는 첫 줄에서 쉼표와 탭 중 많은 쪽이다.
- [ ] **4단계: 통과 확인** 12/12
- [ ] **5단계: 커밋** `WO-N9 표 읽기`

---

### Task 3 (작업 3): 계산과 칸별 근거

**파일:**
- 새로 만들기: `services/api/src/daon2_user_api/aggregation_engine.py`
- 시험: `services/api/tests/test_aggregation_engine.py`(새)

**연결:**
- 사용: 작업 2의 `Table`, `Column`
- 사용: 작업 4의 `Spec`. 이 작업에서는 아래 정규 모양의 dict를 직접 만들어 시험한다.
  - `{"filters":[{"column","op","value"}], "group_by":[{"column","month":bool}], "measures":[{"id","func":"count|sum|avg","column":str|None}], "growth":[{"measure_id"}], "sort":{"by","desc":bool}|None, "limit":int|None}`
  - 필터 `op`: `eq`, `ne`, `in`, `gt`, `gte`, `lt`, `lte`, `between`, `date_between`
- 제공:
  - `AggregationTimeout(Exception)`
  - `run(table: Table, spec: Mapping, *, deadline: float|None = None, max_groups: int = 2000) -> dict`. 반환 모양:
    - `columns`: 묶음 열과 집계 열. 각각 `{key, label, role: "group"|"measure"|"growth"}`
    - `rows`: 칸마다 `{value: str|None, display: str, computed: bool, status: "ok"|"not_computable", reason: str|None, evidence_id: str|None}`
    - `evidence`: `{evidence_id: {"ranges": [...], "filter_text": str, "formula": str, "row_count": int, "excluded": {"not_number": n, "blank": n}}}`
    - `warnings`: 경고 목록
  - `compress_ranges(column_letter: str|None, column_name: str, sheet: str|None, row_numbers: Sequence[int]) -> list[str]`
    - XLSX: `청구내역!F2:F31`
    - CSV: `행 2–31 · 지급액`
  - 결과 묶음이 `max_groups`를 넘으면 `ValueError("AGGREGATION_TOO_MANY_GROUPS")`

- [ ] **1단계: 실패하는 시험**
  - `test_sum_count_avg_by_product`: 손계산 값과 같다. `Decimal` 문자열 비교
  - `test_month_grouping`
  - `test_growth_previous_month`: 100 → 150은 `50.0` 표시
  - `test_growth_previous_zero_not_computable`: 이유 `전월 값 0`
  - `test_growth_gap_month_is_not_computable`: 1월과 3월만 있으면 3월은 `전월 자료 없음`
  - `test_avg_no_rows_not_computable`
  - `test_not_number_and_blank_excluded_and_counted`
  - `test_filters_each_op`
  - `test_evidence_ranges_match_rows`: 근거 범위를 펼친 행 번호 집합이 그 칸을 만든 행 집합과 같다
  - `test_compress_ranges_xlsx_and_csv`: `F2:F31, F45:F60`, `행 2–31, 45–60 · 지급액`
  - `test_rounding_half_up_display`: `2.25`는 `2.3`, 저장은 정확한 값
  - `test_money_sum_exact`: `0.1+0.2`는 `0.3`
  - `test_sort_and_limit`
  - `test_too_many_groups`
  - `test_deadline_timeout`
- [ ] **2단계: 실행해 실패 확인**
- [ ] **3단계: 구현**
  - 한 번 훑으며 묶음 키별로 행 번호 목록과 누적값(`Decimal`)을 모은다.
  - 1,000행마다 `deadline`을 확인한다.
  - 증감률은 같은 다른 묶음 값 안에서 `(year, month)` 바로 앞 달 키를 찾는다.
  - 표시 문자열은 숫자에 천 단위 쉼표를 넣고, 증감률은 `%`를 붙여 소수 첫째 자리까지 쓴다.
- [ ] **4단계: 통과 확인** 15/15
- [ ] **5단계: 커밋** `WO-N9 집계 계산·근거`

---

### Task 4 (작업 4): 조건 스키마·정규화·검사

**파일:**
- 새로 만들기: `services/api/src/daon2_user_api/aggregation_spec.py`
- 시험: `services/api/tests/test_aggregation_spec.py`(새)

**연결:**
- 사용: 작업 2의 `Table`
- 제공:
  - `SPEC_SCHEMA`: 모델 출력용 JSON 스키마. 작업 3의 정규 모양에 `unsupported: list[str]`(모델이 판단한 범위 밖 요청)을 더한다.
  - `class SpecInvalid(Exception)`: `.reasons: list[str]`, 다시 물을 때 쓰는 한국어 이유
  - `class SpecUnsupported(Exception)`: 전부 범위 밖
  - `normalize(raw: Mapping, table: Table) -> tuple[dict, list[str]]`
    - 정규 spec과 경고 목록(`하지 않은 요청: …`)을 돌려준다.
    - 검사: 열 존재(정확한 이름만), 합계·평균은 number 열, 월 묶기는 date 열, 묶음 열 최대 2개, `limit` 최대 50, `growth`는 월 묶기가 있을 때만, 필터 값이 그 열에 실제로 있는지(eq·ne·in, 글 열)
    - 필터 값이 열에 없으면 `SpecInvalid`가 아니라 `ValueError("AGGREGATION_FILTER_VALUE_NOT_FOUND:{값}({열})")`로 즉시 실패한다. 값 목록을 모델에 다시 보내지 않으려는 것이다.
    - measures가 비었고 unsupported만 있으면 `SpecUnsupported`
  - `describe(spec: dict) -> str`: 조건 요약 문장. 예: `필터: 상품=암보험 · 묶기: 상품, 청구일(월) · 집계: 건수, 합계(지급액) · 비교: 전월 대비 증감률`

- [ ] **1단계: 실패하는 시험**
  - `test_valid_spec_normalized`
  - `test_unknown_column_retries_with_reason`: "지급금액" 열에 "지급액"을 쓰면 `SpecInvalid`이고, reasons에 `없는 열: 지급액`이 들어간다(근접 이름으로 바꾸지 않음)
  - `test_sum_on_text_column_invalid`
  - `test_growth_without_month_invalid`
  - `test_filter_value_missing_fails_fast`
  - `test_partial_unsupported_warns`
  - `test_all_unsupported_raises`
  - `test_describe_sentence`
- [ ] **2단계: 실행해 실패 확인**
- [ ] **3단계: 구현.** 순수 함수로만 만든다(모델 호출 없음).
- [ ] **4단계: 통과 확인** 8/8
- [ ] **5단계: 커밋** `WO-N9 집계 조건 검사`

---

### Task 5 (작업 5): 차트·요약 문장·크기 검사

**파일:**
- 새로 만들기: `services/api/src/daon2_user_api/aggregation_present.py`
- 시험: `services/api/tests/test_aggregation_present.py`(새)

**연결:**
- 사용: 작업 3의 `run()` 반환값, 작업 4의 정규 spec
- 제공:
  - `build_chart(result: dict, spec: dict) -> dict | None`
    - 반환 모양: `{"kind": "bar"|"line", "x_key", "series": [{"key", "label", "points": [{"x": str, "value": str|None}]}]}`
    - `kind`: 월 묶기가 있으면 line, 아니면 bar
    - 값은 첫 measure의 칸 저장값을 그대로 쓴다. 계산 불가 칸은 None
  - `summary_sentences(result: dict, spec: dict) -> list[str]`
    - 틀: 첫 measure 기준 최댓값 묶음과 최솟값 묶음. 예: `합계(지급액)이 가장 큰 묶음: 암보험 · 2026-03 (12,345,000)`
    - 숫자는 칸의 `display` 문자열만 쓴다.
  - `content_size_ok(body: dict) -> bool`: JSON 직렬화 크기가 2 MiB 이하인지

- [ ] **1단계: 실패하는 시험**
  - `test_chart_values_equal_table_values`: 차트 points의 value가 집계표 칸 value와 모두 같다
  - `test_not_computable_is_null_point`
  - `test_summary_numbers_subset_of_table_display`
  - `test_line_for_month_bar_otherwise`
  - `test_content_size_limit`
- [ ] **2단계~4단계**(실패 확인, 구현, 통과 5/5)
- [ ] **5단계: 커밋** `WO-N9 차트·요약`

---

### Task 6 (작업 6): 원본 읽기·생성기·작업자 연결·표 정보 API

**파일:**
- 새로 만들기: `services/api/src/daon2_user_api/studio_original_reader.py`
- 수정:
  - `studio_generators.py`(`DataAggregationGenerator`, `build_registry`)
  - `studio_v2_worker.py:215-250`: 원본 읽기 생성. 저장소 어댑터는 `document_processing_worker.py:131,173`과 같은 환경변수로 만든다.
  - `deploy/daon2-user/compose.yaml:140`의 studio-v2-worker에 아래를 더한다. `compose.ysna.yaml`도 필요하면 같이 고친다.
    - `DAON_OBJECT_STORAGE_ENDPOINT`·`_BUCKET`·`_SECURE`
    - `DAON_OBJECT_ACCESS_KEY_FILE`·`DAON_OBJECT_SECRET_KEY_FILE`
    - secrets `object_access_key`·`object_secret_key`
  - `studio_v2_service.py`·`studio_v2_routes.py`: `GET {base}/table-profile?source_version_id=&sheet=&header_row=`
    - 반환: `{"sheets": [...], "columns": [{"name","kind"}], "row_count": n}`
    - 값은 넣지 않는다.
- 시험: `services/api/tests/test_data_aggregation_generator.py`(새), 라우트 시험

**연결:**
- 사용: 작업 2·3·4·5의 공개 이름
- 제공:
  - `StudioOriginalReader.read(context, source_version_id) -> tuple[bytes, str, str, str]`
    - 반환: `(content, file_name, source_format, sha256)`
    - 그 노트북·워크스페이스의 활성 소스 판만 읽는다.
    - 크기·sha256 불일치는 `StudioError("STUDIO_SOURCE_UNAVAILABLE", 409)`
    - XLSX·CSV가 아니면 `StudioError("STUDIO_INPUT_INVALID", 400)`
  - 판 내용 `body`의 모양:
    - `request`, `source`: `{source_version_id, sha256, file_name, sheet, header_row}`
    - `spec`(정규화본), `spec_raw`(모델 원문), `conditions_text`
    - `columns`, `rows`, `evidence`, `chart`, `summary`, `warnings`
    - `stats`: `{rows_read, elapsed_ms}`
  - 진행 문구: `표 읽는 중` → `집계 조건 만드는 중` → `계산 중`

- [ ] **1단계: 실패하는 시험**(가짜 LLM, 가짜 저장소)
  - `test_end_to_end_body_shape`
  - `test_prompt_has_no_cell_values`: 시험 값 문자열이 프롬프트에 없다
  - `test_spec_invalid_retries_once_then_fails`: 두 번째도 틀리면 `STUDIO_VALIDATION_FAILED`
  - `test_filter_value_missing_message`
  - `test_partial_unsupported_completes_with_warning`
  - `test_all_unsupported_fails`
  - `test_checksum_mismatch_rejected`
  - `test_other_notebook_source_rejected`
  - `test_progress_notes_order`
  - `test_egress_decisions_equal_model_calls`
  - `test_audit_records_run`: 감사 기록 `studio_v2.aggregation.run`, metadata는 `{rows_read, elapsed_ms, source_sha256}`
  - `test_result_too_large_message`
  - `test_table_profile_route_no_values`
- [ ] **2단계: 실행해 실패 확인**
- [ ] **3단계: 구현**
  - 오류 코드와 사용자 문구 연결은 `studio-messages.ko.js`의 오류표에 맞춘다(작업 8에서 문구를 추가한다).
  - 서버 오류 코드:
    - `AGGREGATION_FILTER_VALUE_NOT_FOUND`
    - `AGGREGATION_UNSUPPORTED`
    - `AGGREGATION_TOO_LARGE`
    - `AGGREGATION_TOO_MANY_GROUPS`
    - `TABLE_TOO_LARGE`
    - `TABLE_TIMEOUT`
    - `TABLE_SHEET_NOT_FOUND`
    - `TABLE_HEADER_INVALID`
  - 필터 값 없음은 오류 세부(`detail`)에 값과 열 이름을 담는다. 실패 카드에 표시할 방법을 기존 실패 코드 저장 방식에서 찾고, 없으면 일반 문구 `필터 값이 표에 없습니다`로 한다(원장에 Ruling).
- [ ] **4단계: 통과 확인**
- [ ] **5단계: 커밋** `WO-N9 생성기·원본 읽기·작업자 연결`

---

### Task 7 (작업 7): 큰 XLSX를 "집계 전용" 소스로

**파일:**
- 수정:
  - `xlsx_source.py`: 한도 초과(셀 2,048·구조 32 KB)만 별도 예외 `XlsxIndexLimitExceeded(SourceRejected)`로 구분한다. 손상 파일은 기존대로 둔다.
  - `document_processing_postgres.py:362-368`과 xlsx 이해 단계(`xlsx_document_understanding.py:114-118`)
  - 질문 경로(선택 소스가 모두 집계 전용인 경우)
  - 소스 목록 API 응답(`aggregation_only: true`)
- 시험: `services/api/tests/test_xlsx_aggregation_only_source.py`(새), 기존 소스 처리 시험 갱신

**연결:**
- 제공:
  - 집계 전용 소스는 처리 상태가 완료다. 근거 구간(`evidence_spans`)은 0개이고, 판의 정규 정보에 `aggregation_only: true`가 표시된다.
  - 소스 목록 항목에 `aggregation_only: bool`
  - 질문 범위 소스가 전부 집계 전용이면 질문 오류 `SOURCE_AGGREGATION_ONLY`. 문구는 `이 표는 데이터 집계에만 쓸 수 있습니다`.
- 맡기는 것: 처리 실행·판 상태 갱신의 정확한 자리. 기존 `complete()`(`document_processing_postgres.py:751`) 흐름을 읽고 맞춘다. 상태 값을 새로 만들지 말고 완료 + 표시 칸으로 해결한다. 불가능하면 BLOCKED로 보고한다.

- [ ] **1단계: 실패하는 시험**
  - `test_large_xlsx_completes_as_aggregation_only`: 처리 완료, 근거 구간 0, 표시 true
  - `test_corrupted_xlsx_still_fails`
  - `test_small_xlsx_unchanged`
  - `test_question_with_only_aggregation_sources_returns_code`
  - `test_source_list_exposes_flag`
  - `test_studio_text_reader_skips_aggregation_only`: 보고서 등 다른 산출물의 소스 글에 들어가지 않는다
- [ ] **2단계~4단계**(실패 확인, 구현, 통과). 전체 API 새 실패 0.
- [ ] **5단계: 커밋** `WO-N9 집계 전용 소스`

---

### Task 8 (작업 8): 내려받기와 화면

**파일:**
- 수정:
  - `studio_v2_export.py`(`register_renderer("xlsx", …, type_id="data_aggregation")`, `("csv", …)`)
  - `packages/ui/src`: 타일 순서·아이콘·문구, 설정 창(요청 글·표 소스·시트·머리글 행), 보기 `studio-data-aggregation-viewer.jsx`(새), 소스 목록의 `집계 전용` 표시
  - `apps/web/lib/studio-v2-api.js`(표 정보 조회), `bff-api-proxy.js`(`table-profile` GET 허용, 쿼리 3개만), OpenAPI 계약
- 시험:
  - `services/api/tests/test_data_aggregation_export.py`(새)
  - `scripts/tests/studio-data-aggregation-ui.test.mjs`(새)
  - BFF·계약 시험 갱신

**연결:**
- 사용: 작업 6의 `body` 모양과 `table-profile` API, 작업 7의 `aggregation_only`
- 제공(문구 키):
  - `studio.tile.data_aggregation`="데이터 집계"
  - `studio.aggregation.request`="요청 글"
  - `studio.aggregation.source`="표 소스"
  - `studio.aggregation.sheet`="시트"
  - `studio.aggregation.header_row`="머리글 행"
  - `studio.aggregation.computed`="계산값"
  - `studio.aggregation.not_computable`="계산 불가"
  - `studio.aggregation.conditions`="적용한 조건"
  - `studio.aggregation.evidence`="계산 근거"
  - `studio.aggregation.skipped`="하지 않은 요청"
  - `studio.progress.aggregation.read`="표 읽는 중"
  - `studio.progress.aggregation.spec`="집계 조건 만드는 중"
  - `studio.progress.aggregation.compute`="계산 중"
  - `source.aggregation_only`="집계 전용"
  - 작업 6 오류 코드마다 문구

- [ ] **1단계: 실패하는 시험**
  - 내려받기:
    - `test_xlsx_three_sheets_no_formulas`: 시트 이름 `집계표`·`계산 근거`·`적용한 조건`, 계산값 표시 열, 셀 수식 없음
    - `test_csv_has_computed_flag_column`
  - 화면:
    - 타일을 누르면 설정 창(바로 만들지 않음, 웹 페이지와 같은 규칙)
    - 표 소스는 XLSX·CSV 소스만 고를 수 있고, 시트 목록은 `table-profile`에서 불러온다
    - 요청 글은 필수, 2000자
    - 보기에서 계산값 칸에 `계산값` 표지, 계산 불가는 `계산 불가`와 이유
    - 칸을 누르면 근거 칸에 범위·필터·식·행 수
    - 차트 SVG가 `chart.series` 값과 같다
    - 각 칸 `min-height:0; overflow:auto`, 820px 이하에서는 위아래 배치
    - 소스 목록 `집계 전용` 표지
    - BFF는 `table-profile`에 허용한 쿼리 3개 외에는 400
- [ ] **2단계~4단계**(실패 확인, 구현, 통과). Node 기준 새 실패 0(product-studio-click 9건은 main에도 있음).
- [ ] **5단계: 커밋** `WO-N9 내려받기·화면`

---

### Task 9 (작업 9): 설명서·측정·배포·실서버 확인·기록

- [ ] **1단계:** 설명서 2-22 데이터 집계 절. 원본·공개 사본에 쓰고, docx·pdf·manifest를 `python scripts/build-daon-manuals.py all`로 다시 만들고, 설명서 내용 시험에 항목을 추가한다. 통화가 섞인 열은 지원하지 않는다는 안내를 넣는다.
- [ ] **2단계:** 전체 시험. API는 알려진 9건만 실패, Node는 기준과 비교해 새 실패 0.
- [ ] **3단계:** 병합(push → `n1-merge.sh` → 원격 태그 확인) 뒤 ysna 전체 배포(인자 없음). DB `alembic_version=0089`.
- [ ] **4단계: ysna 측정.** 합성 익명 청구 내역 10,000행과 100,000행(XLSX·CSV)으로 실행 시간과 작업자 메모리(`docker stats`)를 잰다. 768 MB와 60초 안에 들지 않으면 한도를 낮추고 다시 배포하며, Ruling을 남긴다.
- [ ] **5단계: 실서버 1차 확인**
  - 임시 노트북에서 예시 요청("월별·상품별 청구 건수와 지급액 합계, 전월 대비 증감률")을 낸다.
  - 표·차트·증감률을 보고, 계산 불가 칸이 생기는 자료를 포함한다.
  - 몇 칸을 손으로 계산해 대조한다.
  - 칸을 눌러 근거를 본다.
  - XLSX를 내려받아 3시트를 확인한다.
  - 집계 전용 소스로 질문해 안내 문구를 본다.
  - 페이지 스크롤이 없는지 본다(넓은 화면, 375px).
  - 임시 노트북을 지우고 0행인지 확인한다.
- [ ] **6단계:** `WORK_STATUS.md` 행 추가, 설계서 구현 기록 절 작성, 병합.

---

## 자체 검토 결과

**설계서 대응**
- §3 제약: 작업 6(격리·외부 전송·기록), 작업 2·3(한도), 작업 8(화면)
- §5.1: 작업 2·7
- §5.2: 작업 6
- §5.3: 작업 3·4
- §5.4: 작업 3·5·6
- §5.5: 작업 8
- §5.6: 기존 다시 생성으로 해결(작업 1의 설정 스키마)
- §5.7: 작업 8
- §7: 작업 9의 측정
- §8: 작업 2~9 시험

**계획에서 정한 값**
- 유형 이름 `data_aggregation`
- 설정 키 4개
- 열 종류 판단 기준 90%
- 범위 표기 형식
- 오류 코드 목록
- 감사 기록 이름 `studio_v2.aggregation.run`
- 표 정보 조회 API 경로

**이름 일관성**
- `table_source_version_id`: 작업 1·6·8
- `Table`·`Column`: 작업 2·3·4
- `run`·`normalize`·`describe`·`build_chart`·`summary_sentences`: 작업 3~6
- `aggregation_only`: 작업 7·8

**실행 위험**
- 작업 6은 배포 설정에 원본 저장소 읽기 권한을 추가한다. 스튜디오 작업자가 원본 저장소를 읽게 되는 권한 확장이다.
- 작업 7은 소스 처리 흐름을 건드린다.
- 두 작업 모두 검토에서 집중해서 본다.
