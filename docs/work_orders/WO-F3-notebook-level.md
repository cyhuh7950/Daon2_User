# WO-F3. Notebook 수준 기능 (노트북 복사 · 채팅 기록 삭제)

| 항목 | 내용 |
| --- | --- |
| 대상 계획 항목 | F3-02, F3-03, S3-04, S3-05 (시나리오 ST-T19, ST-T20) |
| 상태 | **승인(2026-10-26) → 구현됨. 단 D2(Source 연결 복사)는 사실 확인 결과 불가로 판명되어 보류**(§6) |
| 선행 | 없음(맞춤설정 F3-01, 상단 바·⋮ 메뉴 S3-01~03은 완료. ⋮ 메뉴의 "노트북 복사"·"채팅 기록 삭제"는 지금 "준비 중"으로 비활성) |
| 기준 설계서 | §6.8.1, §10, 부록 D(질문 10·11 해소 기록) |
| 조사 근거 | 2026-10-26 코드 조사(`notebook_postgres.py`, `0074_studio_v2.sql`, `0056/0063` 마이그레이션) |

## 0. 현재 구조 요약 (설계의 근거)

| 사실 | 위치 | 영향 |
| --- | --- | --- |
| Source는 Workspace 수준 기록이고, Notebook과는 `notebook_bindings`(`binding_kind='source'`, `record_id`, `version_id`)로 연결된다. 해제는 `notebook_source_unbindings`로 기록한다 | `notebook_postgres.py` l.219~253, 0063 | **복사는 바이트 복사가 아니라 새 Notebook에 같은 Source 버전을 새로 연결(binding)** 하면 된다. 단 "Source 삭제 정리"(0063)가 Notebook 연결 수를 어떻게 세는지 확인이 필요하다 |
| Studio v2 산출물은 `studio_v2_outputs`(`notebook_id`, `owner_actor_id`) + `revisions` + `sources` + `evidence`로 저장된다. 메모도 `type_id='memo'` 산출물이다 | `0074_studio_v2.sql` | 산출물·메모 복사는 **행 복제**(새 `output_id`)다 |
| `studio_v2_assets`는 정의만 있고 생성 경로가 쓰지 않는다(내보내기는 요청 때 즉시 렌더링) | `studio_v2_postgres.py` l.268 | 설계서의 "Asset 새 저장 키"는 **현재 복사할 Asset이 없다**. Asset 저장이 생기면 그때 객체 복사를 추가한다 |
| 채팅은 `runs`/`run_results`/`citations`에 저장되고 Notebook과는 `conversation_thread` 연결로 이어진다. 조회는 `runs.created_by = 요청자`로 걸러진다 | `notebook_postgres.py` l.309~345 | 채팅은 **이미 작성자 개인 범위**로 조회된다(다른 사용자는 못 본다) |
| `runs`·`run_results`는 비용·감사 원장(0073 `operations_run_cost_events`, 감사)과 연결된다 | 0073, `audit` | 채팅 기록을 **물리 삭제**하면 비용·감사 근거가 끊긴다 |
| 메모는 채팅 답변 본문과 인용 근거를 자기 안에 복사해 저장한다 | `studio_v2_service.create_memo_from_run_result` | 채팅 기록을 지워도 메모는 그대로 유지된다(ST-T19 요구와 맞다) |

## 1. 결정 사항 (승인 요청)

| ID | 질문 | 권고안 | 대안 |
| --- | --- | --- | --- |
| D1 | 복사를 동기 처리할 것인가 | **동기 1회 트랜잭션.** Source 연결 100건·산출물 200건 이하만 허용하고 넘으면 `409 NOTEBOOK_COPY_TOO_LARGE`. 바이트 복사가 없어 수 초 안에 끝난다 | 큰 노트북은 `durable_jobs`로 비동기 처리(구현이 커진다) |
| D2 | Source를 복제할지 연결만 할지 | **연결만(같은 Source 버전을 새 Notebook에 binding).** 저장공간이 늘지 않는다. 원본 Notebook에서 Source를 삭제해도 새 Notebook의 연결이 남아 있으면 Source 기록은 유지되어야 하므로, 0063 정리가 "다른 Notebook 연결이 있으면 보존"하는지 시험으로 확인한다 | Source 기록을 복제(원본과 독립, 저장·처리 비용 증가) |
| D3 | 산출물은 어떤 리비전까지 복사하나 | **완료(`completed`)된 산출물의 최신 리비전만.** 증거(evidence)·Source 연결을 함께 복사하고, 이전 리비전·작업(job)·학습 시도(learning attempts)는 복사하지 않는다 | 모든 리비전 복사 |
| D4 | 맞춤설정은 복사하나 | **복사한다**(새 Notebook 버전 1). 설계서에 명시는 없지만 복사 후 같은 결과를 기대하는 것이 자연스럽다 | 복사하지 않음 |
| D5 | 채팅 기록은 복사하나 | **복사하지 않는다**(개인 범위 원칙) | — |
| D6 | 복사한 사용자가 볼 수 없는 항목은 | **복사하지 않고 건너뛴 건수를 응답에 알린다**(권한 상승 방지) | 전체 실패 |
| D7 | 채팅 기록 삭제의 의미 | **논리 삭제(비움 표시).** `notebook_chat_clears(tenant, workspace, notebook, actor, cleared_at)`를 기록하고, 대화 조회는 `created_at <= cleared_at`인 본인의 실행을 숨긴다. 원본 행은 비용·감사 원장 때문에 보존하고, 보존 기간 뒤 정리는 별도 보존 정책에 맡긴다 | 물리 삭제(비용·감사 근거 손상, 삭제 불가 트리거 가능성) |
| D8 | 노트북 개수 한도 | 새 Notebook 생성은 기존 라이선스 한도(`enforce_license_creation`)를 그대로 적용한다 | — |

## 2. 작업 목록

### T-F3-01. 노트북 복사 API (F3-02)

- `POST /api/v1/workspaces/{id}/notebooks/{notebook_id}/copies` — 헤더 `Idempotency-Key` 필수. 본문 `{title?: string(≤160, 기본 "<원본 제목> 사본"), include: {sources: bool, memos: bool, outputs: bool, customization: bool}}`(기본 모두 true).
- 응답 `201 {data: {notebook_id, title, copied: {sources, memos, outputs, customization}, skipped: {sources, memos, outputs}}, meta}` + `ETag`.
- 권한: 원본 Notebook `VIEW` 이상, 새 Notebook 생성 권한은 요청자. 새 Notebook의 소유자는 요청자. 원본에서 요청자가 볼 수 없는 항목은 건너뛴다(D6).
- 서비스: `notebook_copy.py`(`NotebookCopyService.copy(context, notebook_id, options, idempotency_key)`) — 한 트랜잭션에서 ① 새 Notebook 생성(`create`와 같은 경로·라이선스 검사) ② Source binding 복사(`bind_verified` 재사용) ③ 산출물·메모 행 복제(새 `output_id`, 최신 리비전 1개를 `revision_no=1`로, evidence·sources 포함, `owner_actor_id`=요청자) ④ 맞춤설정 복사.
- 멱등: `(tenant, workspace, actor, idempotency_key_sha256)`로 `notebook_copy_requests` 한 행(결과 notebook_id 저장). 같은 키·같은 본문이면 같은 결과, 본문이 다르면 `409 IDEMPOTENCY_CONFLICT`.
- 감사: `notebook.copy`(원본·새 ID, 건수만. 제목·본문 미기록).
- DB: 마이그레이션 **0076**(`notebook_copy_requests`, `notebook_chat_clears`). 새 head를 인정하도록 준비 상태 판정 9곳(`cloud_storage.py` 381·451·527·745, `question_answering_postgres.py` 1207·1212, `runtime.py` 545·555·895·1702·2422)과 관련 시험 5건의 허용 개정 목록에 `0076`을 추가한다. RLS는 0075와 같은 방식(`tenant_id` 기준 강제).

### T-F3-02. 채팅 기록 삭제 API (F3-03)

- `DELETE /api/v1/workspaces/{id}/notebooks/{notebook_id}/chat-history` — `Idempotency-Key` 필수, `204`. 요청자 본인의 비움 시각만 갱신한다(`notebook_chat_clears` UPSERT).
- 대화 조회 경로(`notebook_postgres.py`의 context·conversation 조회, 질문 이력 조회)에서 `runs.created_at > cleared_at`인 본인 실행만 보이게 한다. 다른 사용자의 조회는 영향이 없다.
- 메모·산출물·맞춤설정은 건드리지 않는다.
- 감사: `notebook.chat_history.clear`(건수 미기록, Notebook ID만).

### T-F3-03. 화면 (S3-04, S3-05)

- ⋮ 메뉴의 "노트북 복사"와 "채팅 기록 삭제"를 활성화한다(`notebook-menu.jsx`, 지금은 "준비 중" 비활성).
- **복사 대화상자**: 원본 제목, 항목별 체크박스(Source N개 · 메모 N개 · 산출물 N개 · 맞춤설정), 새 이름 입력, "복사" 버튼. 건수는 Notebook context에서 얻는다. 성공하면 `/notebooks/{새 ID}`로 이동. 건너뛴 항목이 있으면 이동 전에 "N개는 권한이 없어 복사하지 않았습니다"를 보인다.
- **삭제 확인**: "채팅 기록은 나만 볼 수 있습니다. 삭제해도 메모와 산출물은 유지됩니다." + "삭제"/"취소". 성공 시 대화창을 비운다.
- 문구는 `notebook-messages.ko.js` 키로 추가하고(L10N 규칙), 접근성 검사(`studio-a11y.test.mjs`)에 두 대화상자를 포함한다.
- 어댑터: `studio-v2-adapter.js`가 아닌 Notebook 어댑터에 `copyNotebook`, `clearChatHistory`를 추가하고 BFF 허용 경로 표(`bff-api-proxy.js`)에 두 경로를 정확히 등록한다.

## 3. 시험

| 시험 | 내용 |
| --- | --- |
| 단위 | 복사 옵션 검증, 한도 초과, 멱등 재생·충돌, 건너뛰기 계산 |
| 통합(WSL, 실DB) | ① 복사 후 새 Notebook 소유자·권한이 요청자 ② Source 연결·산출물·메모·맞춤설정 복제, 채팅·학습 시도 미복제 ③ 원본에서 Source를 삭제해도 새 Notebook의 연결·산출물 근거 유지 ④ 타인 비공개 항목 건너뜀 ⑤ 채팅 비움이 본인에게만 적용, 다른 사용자 조회 불변, 메모·산출물 불변(ST-T19) ⑥ 비움 뒤 새 질문은 정상 표시 |
| UI | 대화상자 렌더·체크박스·성공 이동·오류 문구, 접근성 규칙, L10N 키 |
| E2E(WSL) | `e2e_studio_v2.py`에 `--notebook-copy` 단계 추가(복사→건수 확인→원본 삭제 후 사본 근거 열람) |

## 4. 완료 기준

- ST-T19, ST-T20이 자동 시험과 WSL E2E로 확인되고 `st-t-coverage.md`가 갱신된다.
- 복사·삭제가 감사에 남고 본문이 기록되지 않는다.
- 새 마이그레이션 0076이 빈 DB와 기존 DB에서 head까지 적용되고, 준비 상태 판정·시험 5건이 통과한다.

## 5. 위험

- 0063 "Source 삭제 정리"가 Notebook 간 공유 Source를 잘못 정리할 수 있다 → 구현 첫 단계에서 **읽기 시험으로 먼저 확인**하고, 문제가 있으면 D2를 "Source 기록 복제"로 바꾸는 안을 다시 제안한다.
- 비움 표시는 "내 화면에서 사라진다"는 뜻이며 물리 삭제가 아니다. 사용자 문구에 "삭제"를 쓰되 약관·개인정보 정책상 물리 삭제 요구가 있으면 D7을 바꿔야 한다(결정 필요).

## 6. 구현 결과와 편차 (2026-10-26)

- 구현: 마이그레이션 0076(`notebook_copy_requests`, `notebook_chat_clears`), `notebook_copy.py`, 복사·채팅 비움 API, BFF 경로, 복사·삭제 대화상자, 시험(단위·WSL IT 4·E2E).
- **D2 편차(Source 복사 보류)**: `delete_notebook_scope`(노트북 삭제 DB 함수)는 같은 Source 레코드나 같은 객체(`object_id`)가 다른 Notebook에도 연결되어 있으면 `DELETE_SHARED_DATA_BLOCKED`로 삭제를 막는다. 연결만 복사하면 **원본도 사본도 삭제할 수 없게 된다**(WSL 시험으로 확인). 그래서 Source가 있는 노트북에서 `include.sources=true`는 `409 NOTEBOOK_COPY_SOURCES_UNSUPPORTED`로 거절하고, 기본값을 `false`로 두었다. Source에 기대는 산출물(근거가 원본 Source 버전을 가리키는 것)도 새 노트북에서 근거를 볼 수 없으므로 건너뛴다(건수는 응답 `skipped`). Source 없이 만들어진 메모와 맞춤설정만 복사된다.
- **선택지(결정 필요)**: (A) Source를 새 객체로 복제하고 재처리(비동기·LLM 비용·시간) (B) 노트북 삭제 함수를 "공유 Source는 연결만 해제"로 바꿈(DB 함수 변경, 데이터 보호 규칙 완화) (C) 현재처럼 Source 없이 복사.
- D7 확인: 채팅 기록은 논리 삭제이며 실행 기록(runs)은 남는다. 대화 조회 두 경로(context 직접 조회, run_id 조회)가 본인의 비움 시각 이후 실행만 보인다. 실제 채팅이 있는 노트북에서의 숨김 동작은 질문을 보내는 E2E로 **미검증**(SQL 유효성과 비움 기록만 확인).

- **결정(2026-10-26, 사용자)**: Source 복사는 (C) 안으로 확정한다. 메모·맞춤설정만 복사하고 Source는 복사하지 않는다. 이 상태로 F3-02·S3-04를 닫는다. Source 복사가 다시 필요해지면 (A)·(B) 안을 새 WO로 다룬다.
