# WO-N8 웹 페이지 만들기 구현 계획

> **에이전트 작업자용:** 필수 하위 스킬: superpowers:subagent-driven-development(권장) 또는 superpowers:executing-plans로 작업 단위별로 실행한다. 단계는 체크박스(`- [ ]`)로 추적한다.

**목표:** 스튜디오에 새 유형 `web_page`를 더한다. 사용자가 적은 요청 글과 고른 소스로 근거 확인된 한 장짜리 HTML 페이지를 만든다. 앱 안에서 격리해 보여 주고, 대화로 고치고, 단독 HTML로 내려받을 수 있다.

**구조:**
- 생성은 두 단계다.
  - 1단계: 보고서 모양의 근거 붙은 내용 JSON을 만들고 검사한다. 근거 부족 블록은 표시만 하고 남긴다.
  - 2단계: 근거 확인된 블록만 모델에 주어 자유 HTML을 만든다.
- 서버의 새 모듈 `studio_web_page.py`가 HTML을 처리한다: 정리, CSP 삽입, 숫자·절 제목 대조, 연결 스크립트 삽입·제거.
- 화면은 `sandbox="allow-scripts"` iframe과 근거 칸으로 나눈 두 칸이다.

**기술:** Python 3(FastAPI, 표준 `html.parser`. 새 의존성 없음), PostgreSQL 마이그레이션(alembic + SQL), React(JSX, `packages/ui`), Node 내장 시험(`node --test`), pytest.

**설계서(정본):** `docs/work_orders/WO-N8-web-page.md`(2026-11-25 신산님 승인). 계획과 설계서가 다르면 설계서를 따른다.

## 전역 제약

- 근거 원칙: 숫자·날짜·식별자 대조는 기존 `_evidence_anchors`(`document_understanding_adapter.py:58`)를 쓴다.
- 모델 호출은 모두 기존 `StudioTextGenerator`(외부 전송 판정 `StudioEgressGate` 경유)로만 한다. 새 우회 경로는 만들지 않는다.
- iframe: `sandbox="allow-scripts"`만 쓴다. `allow-same-origin`·`allow-forms`·`allow-popups`·`allow-top-navigation`은 넣지 않는다.
- CSP 메타 값(그대로 쓴다): `default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'`
- 제거할 것:
  - 요소 `script[src]`, `link`, `iframe`, `object`, `embed`, `base`, `form`, `meta[http-equiv=refresh]`
  - 속성과 CSS 안의 `http(s)://`, `//` 주소. CSS `url(` 중 `data:`가 아닌 것.
- 한도:
  - 요청 글 최대 2,000자, 필수
  - HTML 최대 400,000바이트(UTF-8)
  - 판 하나 2 MiB(`MAX_REVISION_BYTES`)
- 2단계 대조 예외: 요청 글에 있는 숫자, 1~20의 단독 정수, 근거 번호 `S\d+`
- 재시도: 2단계 검사(숫자·절 제목) 실패 시 한 번만 다시 시도한다. 두 번째도 실패하면 `STUDIO_VALIDATION_FAILED`(502).
- 진행 문구: "내용 만드는 중" → "페이지 만드는 중"
- 문구는 `packages/ui/src/studio-messages.ko.js`에 모은다. 영문 머리말은 쓰지 않는다.
- 창 배치: 페이지 칸·근거 칸은 각 칸 안에서 스크롤한다. 앱 페이지 전체 스크롤은 없다.
- 작업 위치: main에서 개발하지 않는다. `D:\tmp\daon2-user-n8` 작업 폴더(+ `node_modules` junction)에서 한다. 병합은 PR Broker(`n1-merge.sh`)로, push 후 병합한다.
- Daon2·Daon2-RAG 코드는 고치지 않는다. 비밀값은 출력하지 않는다.

## 검토 초점

시험으로 막지 못했을 가능성이 큰 입력. 각 줄의 시험은 담당 작업에 들어 있다.

1. 모델이 HTML을 ```` ```html ```` 코드 울타리로 감싸거나 앞뒤에 설명을 붙인다. 울타리를 벗기고 `<html`/`<!doctype` 앞의 글을 버려 정상 처리해야 한다. → 작업 3 `test_extract_html_strips_fence_and_chatter`
2. 숫자가 전각·쉼표·단위 붙은 형태(`1,000,000원`, `100만 원`)로 나온다. `_evidence_anchors` 정규화로 1단계 글과 같게 대조돼야 하고, 거짓 실패가 나면 안 된다. → 작업 3 `test_numbers_match_with_commas_and_units`
3. `data-ref`가 없는 근거 번호(`S99`처럼 존재하지 않는 번호)를 쓴다. 연결 스크립트는 형식만 보내고, 앱은 근거 목록에 없는 번호를 무시해야 한다. → 작업 8 `ignores unknown ref`
4. 근거 확인된 블록이 0개다(모두 근거 부족). 2단계 모델을 부르지 않고 바로 실패해야 한다. → 작업 4 `test_all_insufficient_fails_without_stage2_call`
5. 대화로 고치기에서 고친 문장의 새 숫자가 근거 없이 들어온다. 그 블록은 근거 부족이 되어 새 HTML에서 빠져야 한다. → 작업 6 `test_edited_block_with_new_number_becomes_insufficient`

---

## 파일 구조

| 파일 | 책임 |
| --- | --- |
| `services/api/migrations/versions/0088_web_page.py`·`.sql` (새) | `studio_v2_outputs.type_id` 허용값에 `web_page` 추가, `studio_v2_edit_turns.preview_json jsonb` 추가 |
| `services/api/src/daon2_user_api/studio_web_page.py` (새) | 1단계 검사(`validate_web_page`), HTML 처리(정리·CSP·대조·연결 스크립트), 2단계 입력 만들기 |
| `studio_v2_types.py` | `web_page` 유형 등록 |
| `studio_generators.py` | `WebPageGenerator`, 레지스트리 등록 |
| `studio_v2_export.py`, `studio_v2_service.py`, `studio_v2_routes.py` | `html` 내려받기와 `include_sources` 선택 |
| `studio_chat_edit.py`, `studio_chat_edit_runner.py`, `studio_v2_edit_turns.py` | 대화로 고치기에서 HTML 재생성·저장·적용 |
| `packages/ui/src/studio-panel-model.js`, `studio-icon-data.js`, `product-studio-model.js`, `studio-dialogs.jsx`, `studio-messages.ko.js`, `apps/web/lib/product-workspace-api.js` | 타일·설정(요청 글)·문구 |
| `packages/ui/src/studio-web-page-viewer.jsx` (새), `studio-viewers.jsx`, `studio-chat-edit.jsx`, 관련 CSS | 보기·근거 연결·고친 안 미리보기·내려받기 선택 |
| `docs/manual/…` 2-21 절, `WORK_STATUS.md` | 설명서·기록 |

---

### 작업 1: DB 허용값과 유형 등록

**파일:**
- 새로 만들기: `services/api/migrations/versions/0088_web_page.py`, `0088_web_page.sql`
- 수정: `services/api/src/daon2_user_api/studio_v2_types.py:44-60`
- 시험: `services/api/tests/test_studio_web_page_type.py`(새)

**연결:**
- 사용: 없음
- 제공:
  - `STUDIO_V2_TYPES["web_page"]`: `export_formats=("html",)`, 설정 스키마에 `page_request: {"type":"string","maxLength":2000}`
  - DB 칸 `studio_v2_edit_turns.preview_json jsonb NOT NULL DEFAULT '{}'::jsonb`

- [ ] **1단계: 실패하는 시험 쓰기**

```python
def test_web_page_type_registered():
    t = STUDIO_V2_TYPES["web_page"]
    assert t.export_formats == ("html",)
    assert t.settings_schema["properties"]["page_request"]["maxLength"] == 2000

def test_migration_0088_allows_web_page_and_preview_column():
    sql = Path(MIGRATIONS, "0088_web_page.sql").read_text(encoding="utf-8")
    assert "'web_page'" in sql and "studio_v2_outputs_type_id_check" in sql
    assert "preview_json" in sql
```

- [ ] **2단계: 실행해 실패 확인**

실행: `cd services/api && PYTHONPATH="src;tests" .venv/Scripts/python -m pytest -q -p no:cacheprovider tests/test_studio_web_page_type.py`
기대: FAIL(KeyError 'web_page', 파일 없음)

- [ ] **3단계: 구현**
- SQL 동작:
  - `ALTER TABLE public.studio_v2_outputs DROP CONSTRAINT studio_v2_outputs_type_id_check`
  - 같은 이름으로 기존 11개 값 + `'web_page'`로 다시 `ADD CONSTRAINT`
  - `ALTER TABLE public.studio_v2_edit_turns ADD COLUMN preview_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(preview_json)='object')`
- 제약 이름은 먼저 확인한다. ysna DB에서 `SELECT conname FROM pg_constraint WHERE conrelid='public.studio_v2_outputs'::regclass AND contype='c'`로 실제 이름을 보고, 다르면 그 이름을 쓴다.
- `.py`는 `0087_source_groups.py` 형식을 따른다(`revision='0088'`, `down_revision='0087'`).
- downgrade는 두 가지를 거부한다: `web_page` 행이 있을 때, `preview_json`이 빈 객체가 아닌 행이 있을 때(`WEB_PAGE_FORWARD_RECOVERY_REQUIRED`). 거부하지 않을 때만 되돌린다.
- 마이그레이션 목록 시험(기존 `test_migration*`)이 새 번호를 요구하면 같이 갱신한다.
- 유형 등록: `_t("web_page", ("html",), schema={"page_request": {"type": "string", "maxLength": 2000}})`

- [ ] **4단계: 통과 확인**(2단계 명령) 기대: PASS. 기존 유형 목록 시험(`STUDIO_V2_TYPES` 개수·순서)이 깨지면 기대값에 `web_page`를 더한다.

- [ ] **5단계: 커밋** `WO-N8 web_page 유형·DB 허용값`

---

### 작업 2: 1단계 내용 검사

**파일:**
- 새로 만들기: `services/api/src/daon2_user_api/studio_web_page.py`
- 시험: `services/api/tests/test_studio_web_page_content.py`(새)

**연결:**
- 사용: `studio_validation.clean_refs`, `text_field`, `as_list`, `ensure_size`, `Warnings`. `ContextPack.by_ref()`. `_evidence_anchors`
- 제공:
  - `validate_web_page(data: Mapping, pack: ContextPack, request: str) -> tuple[dict, list[dict], list[str]]`
    - 반환: `(body, warnings, used_refs)`
    - `body = {"title", "request", "sections":[{"heading","blocks":[...]}], "html": ""}`
  - 블록 종류:
    - `paragraph{text}`, `bullets{items}`, `table{rows}`, `metric{label,value}`
    - 모든 블록에 `refs: list[str]`, `insufficient: bool`
  - `verified_body(body) -> dict`: `insufficient`인 블록을 뺀 사본. 블록이 다 빠진 절도 뺀다.
  - `verified_text(body) -> str`: `verified_body`의 모든 글(제목·절 제목·블록 글)을 이어 붙인 것

- [ ] **1단계: 실패하는 시험 쓰기**
- `test_block_without_valid_refs_is_insufficient`: refs가 `["S99"]`(pack에 없음)이면 `insufficient is True`. 블록은 body에 남는다.
- `test_number_not_in_cited_passage_is_insufficient`: 문장 "보상 한도는 300만 원", 인용 구간에는 "100만 원"만 있음 → `insufficient is True`
- `test_supported_block_is_kept_verified`: 인용 구간에 숫자가 있으면 `insufficient is False`
- `test_all_insufficient_raises_validation_failed`: 모든 블록이 근거 부족이면 `StudioError("STUDIO_VALIDATION_FAILED")`
- `test_verified_body_drops_insufficient_and_empty_sections`
- `test_request_stored_trimmed_to_2000`

- [ ] **2단계: 실행해 실패 확인** 기대: FAIL(모듈 없음)

- [ ] **3단계: 구현**
- `validate_report`(`studio_validation.py:71`)의 블록 순회를 따른다. 차이는 세 가지:
  - 블록마다 `insufficient` 판정: 유효 refs가 없거나, 블록 글의 anchor가 인용 구간 anchor의 부분집합이 아니면 근거 부족
  - 경고 대신 블록 표시를 쓴다(경고 `UNVERIFIED_CLAIM`·`ANCHOR_MISMATCH`도 그대로 남긴다)
  - `metric` 블록 지원
- 근거 확인된 블록이 0이면 실패한다.
- 한도: 절 최대 8개, 절당 블록 최대 30개, `title` 160자, `heading` 120자

- [ ] **4단계: 통과 확인** 기대: PASS 6/6
- [ ] **5단계: 커밋** `WO-N8 1단계 내용 검사`

---

### 작업 3: HTML 처리(정리·CSP·대조·연결 스크립트)

**파일:**
- 수정: `services/api/src/daon2_user_api/studio_web_page.py`
- 시험: `services/api/tests/test_studio_web_page_html.py`(새)

**연결:**
- 사용: `_evidence_anchors`
- 제공(같은 모듈):
  - `MAX_HTML_BYTES = 400_000`
  - `CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'"`
  - `extract_html(raw: str) -> str`: 코드 울타리와 앞뒤 설명글 제거
  - `sanitize_html(html: str) -> str`: 위험 요소·외부 주소 제거, 기존 CSP 메타를 지우고 `<head>` 맨 앞에 우리 CSP 메타를 넣는다(`<head>`가 없으면 만든다)
  - `stray_anchors(html: str, allowed_text: str, request: str) -> set[str]`: 보이는 글과 `<script>` 글(스타일·주석·속성 제외)에서 뽑은 anchor 가운데 `allowed_text`에 없는 것. 예외 3가지(요청 글 anchor, 1~20 단독 정수, `S\d+`)는 뺀다.
  - `missing_headings(html: str, headings: Sequence[str]) -> list[str]`: 보이는 글에 없는 절 제목. 공백을 정규화해 비교한다.
  - `BRIDGE_SCRIPT`: 고정 문자열. `[data-ref]` 클릭 → `/^S\d+$/` 확인 → `parent.postMessage({type:"daon-ref",ref:r},"*")`. `<script data-daon-bridge>`로 감싼다.
  - `attach_bridge(html) -> str`: `</body>` 앞에 넣는다(없으면 끝에)
  - `strip_bridge(html) -> str`: `data-daon-bridge` 스크립트 제거
  - `finalize_html(raw, allowed_text, request, headings) -> str`
    - 순서: `extract` → `sanitize` → 크기 검사 → `stray_anchors` → `missing_headings` → `attach_bridge`
    - 실패 시 `WebPageCheckFailed(reason)`. reason은 `"numbers"`, `"headings"`, `"size"`, `"empty"` 중 하나.

- [ ] **1단계: 실패하는 시험 쓰기**(각 하나씩)
- `test_extract_html_strips_fence_and_chatter`: "다음은 페이지입니다\n```html\n<!doctype html><html>…</html>\n```" → `<!doctype`로 시작
- `test_sanitize_removes_dangerous_elements`: `<script src=x>`, `<iframe>`, `<object>`, `<embed>`, `<base href>`, `<form action=…>`, `<link rel=stylesheet href=…>`, `<meta http-equiv="refresh">` 모두 결과에 없음
- `test_sanitize_removes_external_urls`: `<img src="https://a/b.png">`의 src, `style="background:url(//x)"`의 url, `<a href="http://x">`의 href가 사라짐. `url(data:…)`는 남음
- `test_csp_meta_inserted_once`: 모델이 넣은 CSP 메타는 지우고, 우리 값 하나만 `<head>` 첫 자식으로 들어감
- `test_numbers_outside_verified_text_are_stray`: 보이는 글의 "500만 원"(허용 글에 없음) → `stray` 비어 있지 않음
- `test_script_constant_is_checked`: `<script>const rate=0.37</script>` → `0.37`이 stray
- `test_numbers_match_with_commas_and_units`: 허용 글 "1,000,000원", HTML "1000000원" → stray 없음(`_evidence_anchors` 정규화 기준)
- `test_exceptions_request_ordinals_refs`: 요청 글의 "2026년", 단독 "3", "S12" → stray 없음. "21"은 stray
- `test_missing_headings_detected`
- `test_bridge_attached_and_stripped`: `attach` 뒤 `data-daon-bridge` 1개, `strip` 뒤 0개, 나머지 HTML은 같음
- `test_oversize_fails`: 400,001바이트 → `WebPageCheckFailed("size")`

- [ ] **2단계: 실행해 실패 확인** 기대: FAIL(이름 없음)

- [ ] **3단계: 구현**
- 모두 표준 `html.parser.HTMLParser` 기반으로 한다. 토큰을 다시 써서 출력하는 정리기와, 글만 모으는 수집기 두 개를 만든다.
- 정규식으로 태그를 지우는 방식은 쓰지 않는다. 우회되기 쉽기 때문이다.
- 속성 이름이 `on*`인 인라인 처리기는 허용한다. 격리 iframe과 CSP 안에서 동작한다.

- [ ] **4단계: 통과 확인** 기대: PASS 11/11
- [ ] **5단계: 커밋** `WO-N8 HTML 정리·대조·연결 스크립트`

---

### 작업 4: WebPageGenerator(두 단계·재시도·진행 문구)

**파일:**
- 수정: `services/api/src/daon2_user_api/studio_generators.py`(새 클래스, `build_registry:341`)
- 시험: `services/api/tests/test_studio_web_page_generator.py`(새)

**연결:**
- 사용:
  - 작업 2: `validate_web_page`, `verified_body`, `verified_text`
  - 작업 3: `finalize_html`, `WebPageCheckFailed`
  - `_Base._pack`, `_ask`, `_finish`, `ctx.progress`, `self._llm`
- 제공:
  - `WebPageGenerator.type_id = "web_page"`
  - `render_web_page_html(llm, ctx_like, body: dict, request: str) -> str`: 2단계와 한 번 재시도. 작업 6이 같은 함수를 쓴다.
    - `ctx_like`는 모델 호출에 필요한 최소 정보(취소 확인·언어)
    - 시그니처는 실제 `_ask` 형태에 맞춰 정하되, 이 이름을 작업 6에서 그대로 쓴다

- [ ] **1단계: 실패하는 시험 쓰기**(가짜 LLM: 단계별로 정해 둔 응답을 차례로 돌려주고, 받은 프롬프트를 기록)
- `test_two_stage_success_stores_sections_and_html`: content `body.html`에 CSP 메타·bridge가 있고, `body.sections`가 있다
- `test_stage2_prompt_excludes_insufficient_blocks`: 근거 부족 블록 글이 2단계 프롬프트에 없다. 소스 원문도 없다(pack 구간 글이 없다)
- `test_stage2_retry_once_then_success`: 첫 HTML에 stray 숫자, 두 번째 정상 → 성공, 2단계 호출 2회
- `test_stage2_fails_after_second_failure`: 두 번 다 stray → `STUDIO_VALIDATION_FAILED`
- `test_all_insufficient_fails_without_stage2_call`: 2단계 호출 0회
- `test_empty_request_rejected`: `page_request`가 빈칸 → `StudioError("STUDIO_INPUT_INVALID")`
- `test_progress_notes`: 진행 문구에 "내용 만드는 중", "페이지 만드는 중"이 차례로 나온다
- `test_llm_call_count_equals_egress_decisions`: 기존 외부 전송 시험 도구로 판정 수 = 모델 호출 수

- [ ] **2단계: 실행해 실패 확인** 기대: FAIL

- [ ] **3단계: 구현**
- 1단계 `_ask`: 지시는 "요청: …. 소스로 페이지 내용 JSON. 절 3~8개, 블록마다 refs". 스키마는 작업 2의 블록 종류를 쓴다. `tokens=4000`.
- 2단계: 일반 텍스트 응답(JSON 아님)으로 `verified_body` JSON과 요청 글만 준다.
  - 지시: 이 내용만 쓸 것, 새 숫자·사실 금지, 계산식·숫자 상수를 스크립트에 넣지 말 것, 외부 자원 금지, 한 파일, 근거 자리에 `data-ref="S…"`
  - `max_output_tokens=16000`(모델 연결 한도 안. 실제 한도가 더 작으면 그 값으로 하고 원장에 Ruling을 남긴다)
- 재시도 프롬프트에는 실패 이유(넘친 숫자 목록 또는 빠진 절 제목)를 덧붙인다.
- 저장: `_finish(ctx, pack, {**body, "html": html}, warnings, used)`

- [ ] **4단계: 통과 확인** 기대: PASS 8/8
- [ ] **5단계: 커밋** `WO-N8 웹 페이지 생성기`

---

### 작업 5: HTML 내려받기와 출처 목록 선택

**파일:**
- 수정:
  - `studio_v2_export.py`(렌더러 등록, `export_v2`에 선택 인자)
  - `studio_v2_service.py:71`(`export`)
  - `studio_v2_routes.py:312`(쿼리 `include_sources`)
  - `runtime.py:5662`(같은 내려받기 경로가 있으면 같이)
- 시험: `services/api/tests/test_studio_web_page_export.py`(새)

**연결:**
- 사용: 작업 3의 `strip_bridge`, `sanitize_html`
- 제공:
  - `export_v2(format_name, output, *, include_sources: bool = True)`
  - 렌더러 시그니처 `renderer(stem, output, **options)`. 기존 렌더러는 옵션을 무시한다.
  - 라우트 쿼리 `?include_sources=0|1`(기본 1)

- [ ] **1단계: 실패하는 시험 쓰기**
- `test_html_export_strips_bridge_keeps_csp`
- `test_html_export_appends_sources_by_default`: 맨 아래 "출처" 목록에 근거 번호·자료 이름·쪽/구간
- `test_html_export_without_sources`
- `test_html_export_has_no_external_reference`: 결과에 `http://`, `https://`, `src="//` 없음
- `test_other_types_reject_html`: `report`에 `html` → `EXPORT_FORMAT_UNSUPPORTED`
- `test_route_passes_include_sources_and_audits`: 감사 metadata에 `include_sources`

- [ ] **2단계: 실행해 실패 확인** 기대: FAIL

- [ ] **3단계: 구현**
- `register_renderer("html", _web_page_html_renderer, type_id="web_page")`
- 출처 목록 글은 `output["evidence"]`의 표시 이름·위치로 만든다. 글은 HTML 이스케이프한다.
- 결과는 `sanitize_html`로 한 번 더 정리한다.
- 조직 내려받기 정책은 기존 라우트 경로를 그대로 탄다(새 분기 없음).

- [ ] **4단계: 통과 확인** 기대: PASS 6/6
- [ ] **5단계: 커밋** `WO-N8 HTML 내려받기`

---

### 작업 6: 대화로 고치기(고친 안에 HTML 함께 만들기)

**파일:**
- 수정:
  - `studio_chat_edit.py:17`(`CHAT_EDIT_TYPES`), `_FLATTEN:79`, `_MERGE:222`, `_SIZE:223`
  - `studio_chat_edit_runner.py:80-101`
  - `studio_v2_edit_turns.py:107`(`save_edit_turn_result`), `apply_edit_turn`, 고친 안 목록 직렬화
- 시험: `services/api/tests/test_studio_web_page_chat_edit.py`(새)

**연결:**
- 사용:
  - 작업 2: `verified_body`, `verified_text`
  - 작업 4: `render_web_page_html`
  - 기존 `apply_changes`, `describe_changes`
- 제공:
  - `save_edit_turn_result(..., preview: Mapping[str, Any] | None = None)`: `preview_json`에 저장한다(`{"html": str, "body": dict}`)
  - `mark_edited_blocks(new_body, old_body, extra_text: str) -> dict`
    - 바뀐 블록을 다시 판정한다: 유효 refs가 없거나, 새 anchor가 이전 근거 확인 글 + 새 자료 글(`material.text`) 안에 없으면 `insufficient=True`
  - 고친 안 응답 칸 `preview_html`(`web_page`만, 다른 유형은 `null`)

- [ ] **1단계: 실패하는 시험 쓰기**
- `test_web_page_in_chat_edit_types`
- `test_runner_saves_preview_html_with_turn`: 가짜 LLM(고치기 응답 1 + HTML 1) → `preview_json.html`에 bridge·CSP가 있다
- `test_html_failure_fails_turn`: HTML 두 번 실패 → turn이 `failed`, `error_code="STUDIO_VALIDATION_FAILED"`, `changes` 저장 없음
- `test_edited_block_with_new_number_becomes_insufficient`: 고친 문장에 근거 없는 "900만 원" → `preview_json.body`의 그 블록이 `insufficient`, 새 HTML에 "900만"이 없다(2단계 입력에서 빠짐)
- `test_apply_uses_stored_preview`: `apply_edit_turn` 뒤 새 판 `body.html == preview_json.html`, `body.sections == preview_json.body.sections`. 모델 호출 0회
- `test_other_types_unchanged`: `report` 고친 안의 `preview_json`은 `{}`이고 적용 결과는 기존과 같다

- [ ] **2단계: 실행해 실패 확인** 기대: FAIL

- [ ] **3단계: 구현**
- `_FLATTEN["web_page"]`는 `_flatten_report`와 같은 조각 구조를 쓴다: 제목, 절 제목, 블록. `table`·`metric` 블록은 조각으로 내지 않아 고치기 대상에서 뺀다. 그 이유를 주석 한 줄로 남긴다.
- `_MERGE["web_page"]`·`_SIZE["web_page"]`는 보고서 것을 재사용하고, 블록의 `insufficient` 칸을 보존한다.
- runner 흐름(`type_id == "web_page"`일 때만):
  1. `apply_changes`로 미리 합친다
  2. `mark_edited_blocks`로 다시 판정한다
  3. `render_web_page_html`로 HTML을 만든다
  4. `save_edit_turn_result(..., preview={"html", "body"})`
  - HTML 실패(`StudioError`)는 그대로 올려 기존 실패 처리 경로(`fail_edit_turn`)로 간다
- `apply_edit_turn`(`web_page`):
  - 지금처럼 `apply_changes`를 하고, 그 결과 body를 `preview_json.body`로 덮고 `html`을 넣어 판을 만든다
  - `preview_json`이 비어 있으면 `CHAT_EDIT_INVALID`(422)

- [ ] **4단계: 통과 확인** 기대: PASS 6/6. 기존 대화로 고치기 시험 전부 통과.
- [ ] **5단계: 커밋** `WO-N8 대화로 고치기 연결`

---

### 작업 7: 타일·설정·문구

**파일:**
- 수정:
  - `packages/ui/src/studio-panel-model.js:3`(`TILE_ORDER` 끝에 `web_page`)
  - `studio-icon-data.js:196`(아이콘·accent·`labelKey: "studio.tile.web_page"`)
  - `product-studio-model.js:8`(`{id:"web_page", label:"웹 페이지", formats:["html"]}`)
  - `studio-dialogs.jsx`(요청 글 입력)
  - `studio-messages.ko.js`
  - `studio-chat-edit.jsx`(유형 목록)
  - `apps/web/lib/product-workspace-api.js:716`(허용 유형)
- 시험: `scripts/tests/studio-web-page-ui-contract.test.mjs`(새)

**연결:**
- 제공:
  - 설정 칸 이름 `page_request`(작업 1과 같음)
  - 문구 키: `studio.tile.web_page`="웹 페이지", `studio.web_page.request`="요청 글", `studio.web_page.request.hint`, `studio.web_page.excluded`="근거 부족으로 뺀 내용 {n}건", `studio.web_page.include_sources`="출처 목록 넣기", `studio.progress.web_page.content`="내용 만드는 중", `studio.progress.web_page.html`="페이지 만드는 중"

- [ ] **1단계: 실패하는 시험 쓰기**(소스 문자열 계약 시험, 기존 `*-contract.test.mjs` 방식)
- 타일 순서에 `web_page`가 있다
- 설정 창에 `page_request` textarea가 `maxLength={2000}`, `required`로 있다. 빈칸이면 만들기 버튼이 꺼진다
- 위 문구 키가 모두 있다
- 대화로 고치기 유형 목록에 `web_page`가 있다
- API 허용 유형에 `web_page`가 있다

- [ ] **2단계: 실행해 실패 확인** 실행: `node --test scripts/tests/studio-web-page-ui-contract.test.mjs` 기대: FAIL
- [ ] **3단계: 구현.** 아이콘은 기존 아이콘 데이터에 있는 것을 쓴다(새 SVG가 필요하면 `studio-icon-data.js`의 형식대로 하나 더한다).
- [ ] **4단계: 통과 확인** 기대: PASS
- [ ] **5단계: 커밋** `WO-N8 타일·설정·문구`

---

### 작업 8: 웹 페이지 보기(격리 iframe·근거 칸·미리보기·내려받기)

**파일:**
- 새로 만들기: `packages/ui/src/studio-web-page-viewer.jsx`, `packages/ui/src/studio-web-page-bridge.js`(메시지 판정 순수 함수)
- 수정:
  - `studio-viewers.jsx:488`(`case "web_page"`)
  - `studio-chat-edit.jsx`(고친 안 미리보기: `preview_html`이 있으면 같은 뷰어로 보인다)
  - 내려받기 메뉴(`html` 선택 시 "출처 목록 넣기" 체크, 기본 켬, 쿼리 `include_sources`)
  - CSS(`workspace-polish.css` 또는 스튜디오 CSS)
- 시험: `scripts/tests/studio-web-page-viewer.test.mjs`(새)

**연결:**
- 사용: 작업 7 문구 키. 기존 근거 창 `onOpenEvidence(ref)`
- 제공: `acceptRefMessage(event, frameWindow, knownRefs:Set<string>) -> string|null`

- [ ] **1단계: 실패하는 시험 쓰기**
- `acceptRefMessage` 단위 시험:
  - `accepts own frame daon-ref`: `event.source === frameWindow`이고 `data={type:"daon-ref",ref:"S2"}`이며 S2가 알려진 번호 → `"S2"`
  - `rejects other source`
  - `rejects wrong shape`: `type` 다름, `ref:"S2;x"`, `ref` 숫자
  - `ignores unknown ref`: `S99` → `null`
- 소스 계약 시험:
  - iframe `sandbox="allow-scripts"`가 정확히 이 값이다(`allow-same-origin` 없음). `srcDoc` 사용
  - 뷰어 루트는 두 칸 grid이고 각 칸이 `overflow:auto` + `min-height:0`. 좁은 화면(≤820px)에서는 위아래로 쌓는다
  - `insufficient` 블록 수 > 0이면 `studio.web_page.excluded` 줄과 목록을 보인다
  - 내려받기에 `include_sources` 쿼리를 붙인다

- [ ] **2단계: 실행해 실패 확인** 기대: FAIL
- [ ] **3단계: 구현.**
- `window.addEventListener("message", …)`를 뷰어가 붙어 있는 동안에만 걸고 떼어 낸다.
- 받은 번호는 근거 칸에서 그 항목으로 스크롤·강조하고, 기존 `onOpenEvidence`를 부른다.
- [ ] **4단계: 통과 확인** 기대: PASS
- [ ] **5단계: 커밋** `WO-N8 웹 페이지 보기`

---

### 작업 9: 설명서·전체 시험·배포·실서버 확인·기록

**파일:**
- 수정: 설명서 원본(2-20 절이 있는 파일)에 새 절 "2-21 웹 페이지", `WORK_STATUS.md`, `docs/work_orders/WO-N8-web-page.md` §9
- 시험: 설명서 목차 계약 시험(기존 manual 시험)이 새 절을 요구하면 갱신

- [ ] **1단계: 설명서 2-21 절 쓰기**: 만들기(요청 글), 보기(근거 누르기, 근거 부족으로 뺀 내용), 대화로 고치기, 내려받기(출처 목록 넣기)
- [ ] **2단계: 전체 시험**
  - API: `cd services/api && PYTHONPATH="src;tests" .venv/Scripts/python -m pytest -q -p no:cacheprovider tests -rf > $WS/api.txt`
    - 기대: 실패 목록이 기준(/tmp/pkt-api-b.txt의 9건)과 이름이 같다. 새 실패 0.
  - Node: `node --test scripts/tests/*.test.mjs > $WS/node.txt`
    - 기대: 기준(/tmp/pkt-node-b.txt) 대비 새 실패 0. 알려진 흔들림 시험은 단독 재실행으로 확인한다.
- [ ] **3단계: 병합**: 커밋 → `git push -q origin claude/n8-web-page` → `n1-merge.sh` → 원격 `pr-request` 태그 잔여 확인
- [ ] **4단계: ysna 배포**: 인자 없이 `ysna-deploy.sh` 전체 배포(마이그레이션·api·작업자·web). 기대: `rc=0`. DB에서 `alembic_version=0088` 확인.
- [ ] **5단계: 실서버 1차 확인**(직접 수행, 설계서 §7)
  - 합성 약관 소스로 임시 노트북을 만들고 "고객 안내 페이지" 요청 → 카드 완료, 페이지 표시
  - 페이지 안 근거 누르기 → 근거 칸 이동
  - 내려받은 HTML을 앱 밖에서 열어 네트워크 기록의 외부 요청 0건
  - 대화로 고치기 한 번: 미리보기 → 적용 → 새 판
  - 페이지 전체 스크롤 없음(넓은 화면, 375px)
  - 임시 노트북 삭제. `notebook_id` 칸이 있는 모든 표에서 0행 확인
- [ ] **6단계: 기록**: `WORK_STATUS.md` 행 추가, 설계서 §9에 구현 결과·Ruling 요약. 커밋·병합.

---

## 자체 검토 결과

- **설계서 대응**
  - §3 제약: 작업 3(격리·CSP·외부 주소·크기), 작업 5(내려받기 정책), 작업 8(창 배치)
  - §5.1: 작업 2·4
  - §5.2: 작업 8
  - §5.3: 작업 6, 요청 바꿔 다시 만들기는 기존 "설정 바꿔 다시 만들기"가 `page_request`를 그대로 다룬다(작업 7 시험에 포함)
  - §5.4: 작업 5·8
  - §6: 맡긴 값은 아래 Ruling으로 정했다
  - §7: 작업 2~9 시험에 모두 대응
- **계획에서 정한 값(설계서 §6 위임분)**
  - HTML 정리는 표준 `html.parser` 자체 구현(새 의존성 없음)
  - HTML 상한 400,000바이트
  - 2단계 출력 16,000토큰(연결 한도가 작으면 낮춤)
  - 좁은 화면 기준 820px(기존 좁은 화면 기준과 같음)
  - 대화로 고치기에서 `table`·`metric` 블록은 고치기 대상에서 뺌
  - 고친 안 HTML은 새 칸 `preview_json`에 저장(마이그레이션 0088에 함께)
- **이름 일관성**: `page_request`(작업 1·4·7), `render_web_page_html`(작업 4·6), `preview_json`/`preview_html`(작업 1·6·8), `include_sources`(작업 5·8)
