# WO-F1B. 내보내기 정책 추가 인증 · Connector 한도 · 상태 스트림

| 항목 | 내용 |
| --- | --- |
| 대상 계획 항목 | F1-08(조직 정책 시 추가 인증), F4-02(Connector별 한도), F1-07(SSE) |
| 상태 | **승인(2026-10-26) → 구현됨**(편차 1건: §1 D1) |
| 선행 | F1-08의 렌더러 등록 구조는 완료. F4-02의 등록·해제·확인·허용 도구는 완료 |
| 기준 설계서 | §9, §12, §7A.7, §10 |

## 1. 내보내기 추가 인증 (F1-08, ST-T27)

### 현재 상태

- 내보내기(`GET /studio/outputs/{id}/exports/{format}`)는 `VIEW` 권한만 확인하고 추가 인증을 요구하지 않는다("D2: 승인·step-up 불필요", `studio_v2_routes.py`). 기본 설정에서 추가 인증 없이 내려받는 부분(ST-T27 앞 절반)은 E2E로 확인됐다.
- 질문 경로에는 이미 외부 전송 정책의 `required_approver`(`none`/`step_up` 등)에 따른 추가 인증이 있다. 내보내기에는 해당 정책 항목이 없다.

### 결정 사항

| ID | 질문 | 권고안 | 대안 |
| --- | --- | --- | --- |
| D1 | 정책 항목을 어디에 둘까 | **조직 외부 전송 정책(Egress policy)과 별도의 "내보내기 정책"**: `export_requires_step_up: bool`(기본 false). 외부 전송이 아니라 "파일을 사용자 기기로 내려받는 행위"라서 외부 전송 모드와 섞지 않는다 | Egress 정책에 필드 추가 |
| D2 | 인증 방식 | 질문 경로와 같은 **비밀번호 재확인(step-up) 헤더 `x-daon-step-up-authorization`**(BFF에 구버전 Studio 내보내기용 허용이 이미 있다) | 별도 방식 |
| D3 | 적용 범위 | 정책이 켜진 조직에서 **모든 형식**의 내보내기에 적용(미리보기·상세 화면 조회는 제외) | 형식별 선택 |

### 작업

- 정책 저장: 기존 조직 정책 저장소에 `export_requires_step_up` 필드를 추가한다(새 테이블이 아니라 기존 행의 JSON 필드라면 마이그레이션 없이 가능한지 먼저 확인하고, 불가능하면 0076/0077에 포함).
- `studio_v2_routes.py` 내보내기 경로: 정책이 켜져 있으면 step-up 토큰을 검증하고 없거나 틀리면 `401 STEP_UP_REQUIRED`. 감사에 `studio_v2.output.export`와 함께 `step_up=true/false`를 남긴다.
- UI: 다운로드 메뉴에서 `STEP_UP_REQUIRED`를 받으면 비밀번호 확인 대화상자를 띄우고 성공 시 다시 시도한다(질문의 추가 인증 대화상자 재사용).
- 시험: 정책 꺼짐→추가 인증 없이 200, 켜짐→헤더 없이 401, 올바른 헤더로 200, 타 조직 정책 영향 없음, UI 대화상자 흐름.

## 2. Connector별 한도 (F4-02)

### 현재 상태

호출 시간 제한(`DAON_MCP_CALL_TIMEOUT_SECONDS`, 기본 25초), 동시 호출 4건(`McpClient(max_concurrent=4)`), 응답 최대 1 MiB(`MAX_RESPONSE_BYTES`)가 **서버 전체 상수**로 있고, Connector별로 바꿀 수 없다.

### 결정 사항

| ID | 질문 | 권고안 |
| --- | --- | --- |
| D4 | 한도 항목 | `max_concurrent`(1~8), `timeout_seconds`(1~60), `max_response_bytes`(4 KiB~4 MiB), `calls_per_minute`(1~600, 비우면 무제한) |
| D5 | 저장 | `knowledge_connectors.call_limits jsonb NOT NULL DEFAULT '{}'`(크기 상한 1 KiB, 객체만) — 마이그레이션 필요. 비어 있으면 서버 기본값 |
| D6 | 분당 호출 제한 방식 | 프로세스 메모리의 슬라이딩 윈도우(API·워커 프로세스별). 정확한 전역 제한은 아니며 폭주 방지 용도 |

### 작업

- 마이그레이션(0076 이후): `call_limits` 열 추가 + 준비 상태 판정에 새 head 추가(WO-F3 T-F3-01과 같은 9곳).
- `KnowledgeConnectorService`: `_view`·`_COLUMNS`·`_client`의 열 번호를 맞추고(열 하나 추가), `McpClient`·`HttpJsonRpcTransport`에 한도를 전달, `call()`에서 분당 한도를 검사해 초과 시 `429 CONNECTOR_RATE_LIMITED`.
- API: `PATCH /api/v1/admin/knowledge-connectors/{id}` 본문을 `{allowed_tools?, limits?}`로 확장(둘 중 하나 이상, 범위 검증, `If-Match`).
- UI: 지식 연결 관리 화면의 각 Connector에 "한도" 입력(숫자 4개)과 저장. 문구는 L10N 키.
- 시험: 범위 밖 값 거부, 한도 반영(동시 호출 초과 대기·시간 초과·응답 초과), 분당 초과 429, 기존 Connector(빈 한도)는 서버 기본값, UI.

## 3. 상태 이벤트 스트림 (F1-07)

### 현재 상태

WO-F1 결정 D6에 따라 **폴링**으로 구현되어 있다(활성 작업이 있을 때만 1.5초, 숨김 탭은 느리게). BFF 프록시는 응답을 `arrayBuffer()`로 버퍼링하고 10초 타임아웃과 정확한 경로 허용표를 쓰므로 스트리밍(SSE)을 그대로 통과시킬 수 없다.

### 결정 사항

| ID | 질문 | 권고안 | 대안 |
| --- | --- | --- | --- |
| D7 | SSE를 도입할 것인가 | **도입하지 않고 폴링을 유지한다.** 사용자 수·산출물 수가 작고(동시 한도 2), 폴링은 이미 동작·시험되어 있다. SSE를 위해 BFF의 응답 버퍼링·타임아웃·허용표 보안 구조를 바꾸는 이득이 작다 | BFF에 "스트리밍 허용 경로"를 추가해 `GET …/studio/events`를 통과시킴(BFF 보안 설계 변경, 연결 수 관리, 프록시 타임아웃 조정 필요) |

권고안을 승인하면 F1-07은 "폴링 구현 완료, SSE는 도입하지 않음(결정 D7)"으로 닫는다. 대안을 선택하면 별도 WO로 BFF 변경 설계를 먼저 작성한다.

## 4. 마이그레이션 번호 정리

WO-F3(`notebook_copy_requests`, `notebook_chat_clears`), WO-A3(`authoring_templates`), 이 WO의 F4-02(`call_limits`)는 모두 새 테이블·열이 필요하다. 세 WO를 모두 승인하면 **0076 하나에 합치고**(순서: 테이블 3개 + 열 1개), 준비 상태 판정 9곳과 시험 5건의 허용 개정 목록을 한 번에 갱신하는 것을 권고한다. 일부만 승인하면 승인된 것만 0076에 넣는다.

## 5. 구현 결과와 편차 (2026-10-26)

- **내보내기 추가 인증(D1 편차)**: 새 정책 필드·테이블 대신 **기존 조직 step-up 행동 목록**(`tenant_step_up_actions`)에 `studio_export_download`를 더하는 방식으로 구현했다. 마이그레이션이 필요 없고 질문·승인 등 다른 추가 인증과 같은 비밀번호 재확인·1회용 토큰을 쓴다. 다만 이 목록은 조직 보안 정책이라 **한 번 켜면 되돌릴 수 없다**(`remove_step_up_action`은 항상 거부). 설정 API는 `GET·PUT /api/v1/admin/export-policy`, 화면은 `/settings/export-policy`. 되돌릴 수 있는 토글이 필요하면 별도 테이블이 필요하다(결정 필요).
- **Connector별 한도**: 0076의 `knowledge_connectors.call_limits`(동시 호출·제한 시간·응답 크기·분당 호출). `PATCH /admin/knowledge-connectors/{id}` 본문에 `limits` 추가, 화면에 "한도" 대화상자.
- **SSE(D7)**: 도입하지 않고 폴링 유지.
- 시험: 단위(내보내기 정책·승인 토큰 연결), HTTP, UI, WSL IT(Connector 한도 분당 초과). 실제 추가 인증 토큰으로 내려받는 흐름은 QA 계정이 관리자가 아니라 E2E로는 **미검증**(토큰 소비는 단위 시험에서 대체 객체로 확인).
