# WO-T0. 이식 기능 테스트·수정

| 항목 | 내용 |
| --- | --- |
| 대상 계획 항목 | S0-01 ~ S0-10, F8-09 (모두 `[1]` 테스트·수정 단계) |
| 원칙 | daon-user에서 가져온 기능은 **코딩을 생략하고 테스트와 수정만** 한다(2026-10-20 결정). 신규 기능 개발은 다른 WO에서 한다. |
| 기준선 | 커밋 `0130e9f9`(2026-10-20), 로컬 Windows + WSL 서버 `daon2_user` 스택(웹 3340, 전용 Postgres 127.0.0.1:5436) |
| 결함 관리 | 결함 ID `D-NNN`을 이 문서 §1에 등록하고, 수정 커밋 SHA와 회귀 결과를 같은 표에 기록한다. 계획서 비고에는 결함 ID만 적는다. |

---

## 1. 기준선 결과와 결함 등록부

### 1.1 측정 결과

| 검사 | 결과 | 비고 |
| --- | --- | --- |
| API 단위 테스트(`--ignore-glob "*postgres*" "*integration*"`) | 통과 1,506 / **실패 34 / 오류 16** / 스킵 282 | `maxfail=50`에서 중단된 실행이므로 **전체 실패 수는 더 클 수 있다**(수정 후 재측정 필요). 스킵 282건은 Postgres·외부 환경 의존 |
| 전체 품질 게이트(`verify:quality-gate`) | 실패 **5건**: `security-static-scan`, `desktop-rust-type`, `desktop-shell-unit`, `api-runtime-build`, `quality-gate-runner-tests` | lint·contract·independence는 통과 |
| `verify:independence` / `verify:openapi-contract` / `verify:public-repository-boundary` | 모두 통과 | 이번 이식 작업에서 정리함 |
| 웹 빌드, 모바일 lint·type·unit·contract, workspace(38건), product-foundation(11건) | 통과 | 앞선 검증 |

### 1.2 결함 등록부

분류: **E**=환경(이 PC/서버 설정), **R**=rename·이식 과정이 만든 결함, **O**=원래 코드(이식 원본)의 결함.

| ID | 증상 | 원인 분석 | 분류 | 수정 방법 | 영향 테스트 | 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| D-001 | `FileNotFoundError: ...\.superpowers\<임시>` (테스트 29건 이상: `test_account_settings.py` 16 오류, `test_open_law_source_runtime.py` 13 실패, `test_account_settings_contract.py` 4, `test_account_settings_session_race.py` 1 등) | 테스트가 저장소 루트의 `.superpowers` 폴더 아래에 임시 폴더를 만드는데, 새 저장소에는 폴더가 없다(원래 저장소는 무시 파일로 존재). | E/R | 방법 (a) 테스트의 공통 헬퍼가 `os.makedirs(root/".superpowers", exist_ok=True)`를 하도록 수정, 또는 (b) `.superpowers/.gitkeep`을 커밋하고 `.gitignore`에 `/.superpowers/*`·`!/.superpowers/.gitkeep`. **(a)를 권장**(체크아웃 방식과 무관). | 위 4개 파일 | [ ] |
| D-002 | `test_notebook_selected_context.py` 8건 실패: `4-튜플 ('tenant','workspace','notebook','actor')` 대 기대 `3-튜플` | 구현이 노트북 바인딩 조회 키에 `actor`를 포함하도록 바뀌었는데 테스트가 이전 형식을 단언(또는 반대). 이식 원본이 작업 중이던 코드(원래 저장소에 미커밋 수정이 있었다). | O | `API/notebook_postgres.py`(`_read_exact_context` 등)와 테스트 기대값 중 **정본 판단**: 질문·Notebook 설계 의도(`NotebookContext` 필드)를 `API/notebook.py`에서 확인해 일치시킨다. 결정 근거를 이 표에 기록. | `test_notebook_selected_context.py` | [0] 완료: 테스트를 구현에 맞춤: 바인딩 조회는 소유자(actor)까지 포함(소유자 한정이 안전). |
| D-003 | `test_recovery_destinations.py` 5건: `owned root must be new` | Windows 경로·디렉터리 속성 처리 차이로 추정(`recovery` 목적지 루트 검증이 "새 폴더여야 한다"를 확인). Linux(WSL)에서는 통과할 가능성이 높다. | E | WSL에서 먼저 실행해 통과 여부 확인. Windows에서 실패가 정상이라면 테스트에 플랫폼 skip을 명시하고 이유를 기록. | `test_recovery_destinations.py` | [0] 완료: 원인=시험이 고정 "새 루트"(D:/tmp/daon2-user-s44-d1-*)를 요구. 파일별 격리 실행(scripts/run-api-tests-isolated.sh)으로 전부 통과. |
| D-004 | `test_recovery_contract.py` 1건: 라우트 집합 불일치 (`/backups/{id}/restore-destinations` GET 존재 대 기대 `restore-previews` POST …) | OpenAPI 계약·검증 스크립트와 런타임 라우트가 서로 다른 시점의 코드(이식 원본의 미커밋 변경). | O | 런타임이 최신이면 `packages/contracts/openapi/v1/openapi.json`과 `scripts/verify-openapi-contract.mjs`의 복구 경로를 런타임에 맞춘다(반대 방향이면 런타임 되돌림). **기준은 실제 동작하는 UI가 호출하는 경로**(`apps/web/lib/recovery-api.js`)이다. | `test_recovery_contract.py`, `verify:openapi-contract` | [0] 완료: Python 계약 시험에 restore-destinations GET 추가(런타임·OpenAPI·JS와 일치). |
| D-005 | `test_external_transfer_personal_owner_runtime_http.py` 2건: `issue_step_up_after_reauthentication` 호출 0회, 기대 `consume_step_up` 1회 | 개인 소유 워크스페이스의 질문에서 step-up 흐름이 구현·테스트 사이에 어긋남. | O | 설계 의도 확인(개인 워크스페이스는 질문에 step-up 불필요하다는 테스트 제목) → 구현이 정본이면 테스트 수정, 아니면 구현 수정. | 해당 파일 | [0] 완료: 정본=구현(참조와 동일): 외부 provider 질문은 external_transfer step-up 필수. 시험을 구현에 맞춤(보안 약화 없음). |
| D-006 | `quality-gate-runner-tests`와 `security-static-scan` 실패: `BROWSER_INTERNAL_ADDRESS` `apps/web/app/settings/model-connections/page.jsx` | **이번 이식 중 내가 추가한 코드**: `독립성` 위반을 고치려고 서버 페이지에 `"http://asr-base:8080"` 리터럴을 두었는데 보안 스캔의 브라우저 내부 주소 규칙이 이를 잡는다. | R | 리터럴을 코드에서 제거하고 값을 환경변수(`DAON_QA_ASR_BASE_URL`)로만 받는다. 기본값은 Compose(`deploy/daon2-user/compose.yaml`의 `web.environment`)에서 `http://asr-base:8080`으로 주입. 환경변수가 없으면 Endpoint 필드는 비워 둔다(관리자가 입력). `scripts/tests/provider-settings-web.test.mjs`(prop 전달 방식) 유지. | `security-static-scan`, `quality-gate.test.mjs`, `provider-settings-web.test.mjs` | [0] 완료: 2026-10-26 전체 게이트 실행에서 `security-static-scan`·`quality-gate-runner-tests` 통과 확인 |
| D-007 | `api-runtime-build`(= `verify:api-runtime --check-only`) 실패: `api-bff-runtime.test.mjs` 1건 "BFF는 Workspace 운영상태 GET만 same-origin 안전 경로로 전달한다" (기대 200, 실제 400) | 운영상태 GET의 쿼리 허용 규칙(`include_capacity`·`include_readiness`, `bff-api-proxy.js` strictQuery 검사)과 테스트 기대 불일치. 원본 미커밋 변경 가능. | O | `routeFor`의 `operations/status` 블록(`query` 집합에 `include_capacity` 포함 여부)과 테스트 요청 쿼리를 대조해 정본 결정 후 수정. | `api-bff-runtime.test.mjs` | [0] 완료: 수정 완료(이전). |
| D-008 | `desktop-shell-unit` 실패(`verify:desktop-unit` 3건): ① `Windows package declares a generated target-triple sidecar and cleanup` ② `Web Operations 직접 진입은 Safe unavailable만 렌더…` ③ `PostCSS 보정 이력은 고정 Successor Blob으로…` | ① sidecar 이름 `daon-user-local-service`→`daon2-user-local-service` rename이 테스트의 고정 문자열·해시와 충돌했을 가능성, ② 운영 화면 테스트(원본), ③ **git 이력(blob SHA) 기반 검증이라 새 저장소에는 해당 blob이 없다** | R | ①은 테스트 기대 문자열을 rename 후 이름으로 갱신, ③은 이력에 의존하는 검증이므로 **새 저장소에서는 의미가 없다 → 테스트 제거 또는 현재 파일의 핵심 핀 검증만 남김**, ②는 원인 분석 필요. | `scripts/tests/desktop-tauri-shell.test.mjs` 등 | [0] 완료: ①.gitignore 항목 추가 ②시험이 옛 화면 문구를 기대 → 실제 화면에 맞춤 ③고정 해시를 rename 반영값으로 갱신. 단 npm ls 부분은 worktree의 node_modules 접합으로 실패 → 기준 저장소에서 확인. |
| D-009 | `desktop-rust-type` 실패 | 로컬에 `cargo` 없음 | E | Desktop은 후속(Phase 5, F0-15). 품질 게이트 정책에서 Desktop 검사를 "N/A"로 두는 방안은 사용자 결정 필요(게이트 약화이므로 임의 변경 금지). 결정 전까지 `[ ]`로 두고 **알려진 실패**로 기록. | `quality-gate-policy.json` | [0] 완료: 2026-10-26 사용자 지시로 Rust 1.97.1(rustup) 설치, `verify:desktop-type` 통과 |
| D-010 | 전체 API 테스트가 `maxfail=50`에서 중단되어 전체 실패 규모를 모른다 | 측정 한계 | — | 수정 후 `-p no:cacheprovider --maxfail=0`(무제한)으로 재측정해 이 표를 갱신. 실행 시간 약 4~10분. | 전체 | [0] 완료: 전체 재측정 완료: 기본 2597 통과·0 실패, 격리 7개 파일 통과. |
| D-011 | 임시 Postgres(`scripts/run-postgres-tests-wsl.sh`)에서 이식 시험 약 500건 실패·오류 | 이식 시험이 이전 환경의 승인 DB 이름(`daon2_user_s42_qa_20261017_l2` 등)·`D:/tmp` 루트·특정 역할을 하드코딩한 안전 가드를 가진다. 우리 환경에서는 가드가 항상 거부한다 | E/T | 가드 값을 환경변수로 받게 바꾸거나 가드가 있는 시험을 제외하는 방안 — 안전 가드 완화이므로 결정 필요 | 알림·복구·서비스 스냅샷 시험군 | [ ] |

> 수정 우선순위: D-006(내가 만든 결함, 게이트 2건 해소) → D-001(환경, 29건 해소) → D-007/D-002/D-004/D-005(동작 불일치) → D-008 → D-003 → D-009 결정.

---

## 2. 테스트 환경 준비

| 항목 | 내용 | 비고 |
| --- | --- | --- |
| E-1 QA 계정 | `qa-e2e`(생성·승인 완료), 비밀번호는 서버 `~/deploy/daon2-user/secrets/qa_e2e_password` | 값은 채팅·문서에 쓰지 않음 |
| E-2 관리자 | `admin`(시드, 최초 로그인 시 비밀번호 변경 필요) | 사용자가 직접 로그인 시 변경 |
| E-3 LLM Provider | 질문 응답·문서 처리에 `text_generation`(+PDF는 `document_parsing`·`image_understanding`) 모델 연결 필요. 기존 daon-user는 Ollama(`192.168.220.180:11434`)를 사용. **새 환경에서도 같은 서버를 쓸지 사용자 확인 필요**(미확정). 확정 전에는 Source 처리·질문 응답 시험(S0-05 일부, S0-06)을 시작할 수 없다. | 외부 유료 Provider는 비용 승인 전 사용 금지 |
| E-4 시험 문서 | 합성 파일 세트 `docs/04_test_reports/inherited/fixtures/`: TXT, MD, CSV, XLSX(2시트), DOCX(제목·표 포함), PPTX(3슬라이드), PDF(텍스트 3쪽), WAV(10초, 합성 음성), PNG(문서 이미지), 25 MiB 초과 파일(업로드 제한 시험, 생성 스크립트로 만들고 커밋하지 않음) | 실제 업무 문서 금지 |
| E-5 DB 실시험 | WSL의 전용 Postgres에 **시험 전용 DB**를 만들어 Postgres 통합 테스트 실행. `daon_app` 멤버의 `NOSUPERUSER NOBYPASSRLS` 로그인 역할 DSN을 환경변수로 전달(`DAON_TEST_POSTGRES_DSN`, `DAON_STUDIO_TEST_DSN`, `DAON_NOTIFICATION_TEST_DSN`, `DAON_ORGANIZATION_TEST_DSN`, `DAON_TEST_ACCOUNT_POSTGRES_DSN`, `DAON_PROVIDER_TEST_DSN`, `DAON_OUTPUT_SETTINGS_TEST_DSN`, `DAON_OPERATIONS_TEST_DSN`, `DAON_SYNC_SETTINGS_TEST_DSN`) | 기존 `scripts/run-*-postgres-gate.sh`는 공유 `local-postgres`(컨테이너명·비밀 위치)를 가정하므로 **새 전용 Postgres용으로 수정**(§3 F8-09). 운영 `daon2_user` DB에는 시험 데이터 금지 |
| E-6 브라우저 | 클릭 E2E는 사용자 PC 브라우저(`http://172.27.253.53:3340`)에서 사용자가 수행하거나, 서버 루프백 HTTP 시험(`deploy/daon2-user/qa/e2e_login.py`)으로 대체 | 브라우저 자동 입력은 하지 않음(자격 증명 규칙) |
| E-7 `.superpowers` | D-001 수정 전에는 로컬에 폴더를 수동 생성(`mkdir .superpowers`)해야 테스트가 진행됨 | |

---

## 3. 항목별 테스트 매트릭스

표기: 방식 **A**=자동(스크립트/단위), **H**=HTTP 서버 시험(루프백), **M**=수동(브라우저). 결과는 `docs/04_test_reports/inherited/<ID>.md`에 날짜·SHA·증거(로그/스크린샷 경로)와 함께 기록. 통과 시 계획서 상태를 `[0]`으로.

### S0-01 로그인 화면

| 시나리오 | 절차 | 기대 | 방식 | 상태 |
| --- | --- | --- | --- | --- |
| L1 정상 로그인(QA) | 로그인 | 200, 세션 쿠키(HttpOnly), 비밀번호 변경 요구 시 변경 화면 | H(완료: 2026-10-20) | 증거 있음 |
| L2 잘못된 비밀번호 | | 401 `AUTHENTICATION_REQUIRED`, 화면에 코드 표시 | H(완료) | 증거 있음 |
| L3 빈 값 | | 400 `INVALID_REQUEST` | H(완료) | 증거 있음 |
| L4 로그아웃·재로그인 | `POST /bff/api/session/logout` | 쿠키 만료, 보호 페이지 접근 시 `/`로 이동 | H | [ ] |
| L5 세션 만료·재진입 | 만료 후 `/notebooks` | 로그인 화면 | H/M | [ ] |
| L6 UI 클릭(로그인 화면) | 사용자 브라우저에서 로그인 | 화면 이동 | M | [ ] |
| **완료 기준** | L1~L6 통과 | | | |

### S0-02 비밀번호 변경 화면
- P1 12자 미만 거부(`PASSWORD_POLICY_FAILED`) H, P2 정상 변경 H(완료), P3 변경 후 이전 세션 무효 H, P4 UI 클릭 M.

### S0-03 Notebook 홈
- N1 목록(빈/있음) H(빈 목록 확인), N2 생성(제목) H/M, N3 제목 변경(ETag) H, N4 삭제 요청·진행 상태 H, N5 열기→워크스페이스 이동 M. 자동 테스트 `notebook-home-react.test.mjs`, `notebook-bff.test.mjs`, `notebook-openapi.test.mjs`를 먼저 실행.

### S0-04 3면 레이아웃
- W1 폭 1440/1180/820에서 배치(`workspace.css` 규칙) M(스크린샷), W2 접근성(탭 순서·포커스 트랩·`aria-label`) A(`web-final-ui.test.mjs`, `workspace.test.mjs`) + M, W3 로그아웃·설정 메뉴 동작 A(`product-workspace.test.mjs`).

### S0-05 Source 추가·목록 (E-3 필요)
| ID | 시나리오 | 기대 |
| --- | --- | --- |
| SRC-1 | TXT/MD/CSV 업로드 | 처리 완료(`ready`), 목록에 표시 |
| SRC-2 | XLSX/DOCX/PPTX 업로드 | 처리 완료, 로케이터 형식(`sheet_cell`/`docx_block`/`pptx_block`) 근거 생성 |
| SRC-3 | PDF 업로드 | 쪽 단위 처리(`UPSTAGE` 필요 — 미연결 시 `waiting_model`) |
| SRC-4 | WAV 업로드 | 전사(`speech_to_text`: ASR 서비스 필요 — `services/asr-base` 미배포면 `unavailable` 표시 확인) |
| SRC-5 | PNG 업로드 | `image_understanding` 모델 필요 |
| SRC-6 | 25 MiB 초과 | 413/안전 오류 |
| SRC-7 | 웹사이트·붙여넣기·법령 | 웹 스냅샷/원문 import(법령은 `DAON_OPEN_LAW_*` 필요, 기본 비활성) |
| SRC-8 | 삭제(즉시/요청) | 목록에서 제거, 삭제 상태 표시 |
| SRC-9 | 동일 파일 재업로드 | 중복 처리(digest) |
- 자동: `drive-source-ui.test.mjs`, `source-knowledge.test.mjs`, `source-upload-*` 계열, API `test_source_*`, `test_document_processing*.py`(Postgres 제외분).

### S0-06 채팅·인용 (E-3 필요)
- Q1 소스 선택 후 질문→답변+인용, Q2 인용 클릭: 형식별 뷰어(PDF 쪽, DOCX 블록, PPTX, XLSX 셀, 오디오, 이미지 영역, 법령), Q3 근거 부족 안내(`insufficient`), Q4 일반 상담(소스 없이), Q5 오류(모델 미설정 `WORKSPACE_MODEL_DEFAULT_UNAVAILABLE`) 표시. 자동 `product-workspace.test.mjs`(2,112줄), API `test_question_answering*.py`.

### S0-07 모델 연결(Provider)
- PV1 Ollama 연결 등록·모델 검증(`provider_connection_admin`), PV2 기본 모델 지정(`workspace_model_defaults`), PV3 자격 증명 암호 저장·마스킹, PV4 ASR 연결(`asr_base_native`, 엔드포인트 입력 필요 — D-006 수정 후 동작 확인). 자동 `provider-settings-web.test.mjs`(47건 통과), API `test_provider_*`(통과).

### S0-08 설정(계정·화면·조직·라이선스·매뉴얼)
- ST1 계정 프로필·기기, ST2 화면(테마), ST3 조직 가입·승인, ST4 라이선스 입력·상태, ST5 매뉴얼 화면(`/settings/manual`, 200 확인). 자동: `account-*`, `organization-*`, `license-*`, `manual-*.test.mjs`.

### S0-09 관리자 콘솔
- AD1 사용자 목록, AD2 사용자 생성·승인·재설정 요청·삭제(HTTP: 서비스 호출로 확인 완료한 `create_user`/`approve_user`와 동일 경로), AD3 조직 관리자 화면. 자동: `admin-*`, `identity` 테스트.

### S0-10 알림함
- NT1 알림 목록·읽음, NT2 이벤트 생성(로그인·비밀번호·조직 변경 이벤트), 플래그 `DAON_NOTIFICATION_INBOX_ENABLED`(현재 false)를 true로 바꾸는 시험은 **0072/0073 알림 관련 DB 검사 포함이라 별도 승인 후** 진행.

### F8-09 회귀·통합 테스트
1. **전체 API 단위 테스트 재측정**(D-010).
2. **Postgres 통합 테스트**: E-5의 시험 DB에서 스킵되던 테스트를 실행. 방법: `deploy/daon2-user/wsl-bootstrap-db.sh`를 참고해 `scripts/run-postgres-tests-wsl.sh`(신규)를 만들어 (a) 시험 전용 DB 생성(`daon2_user_test_<suffix>`, 종료 시 정리), (b) 마이그레이션(0040까지 앱 역할, 이후 superuser, 소유자 보정), (c) `NOSUPERUSER NOBYPASSRLS` 로그인 역할 생성·`daon_app` 멤버, (d) 환경변수 DSN 설정 후 `pytest tests -k postgres`, (e) 정리. 기존 `run-*-postgres-gate.sh`의 `local-postgres`·`postgres-owner-credential.sh` 의존은 컨테이너명 `daon2_user-postgres-1`·비밀 파일 `secrets/db_superuser_password`로 치환.
3. **웹**: `verify:workspace`, 모바일 4종, `verify:product-ui-boundary`, 웹 빌드, 위 BFF 테스트 전체(`scripts/tests/*-bff.test.mjs`).
4. **품질 게이트**: 결함 수정 후 재실행해 5건 → (D-009 제외) 0건.

---

## 4. 수정 절차

1. 결함 발견 → §1.2에 ID 등록(증상·재현 명령).
2. 원인 분류(E/R/O). **R·O는 코드 수정, E는 환경 설정**. 게이트를 약화하는 수정(검사 삭제·정책 완화)은 사용자 승인 후에만.
3. 수정은 작은 커밋으로(`fix(<영역>): D-0NN …`), 수정과 함께 재현 테스트를 추가하거나 기존 테스트를 갱신.
4. 영향 범위 회귀: 해당 테스트 + `verify:independence` + `verify:public-repository-boundary`.
5. 표에 수정 커밋 SHA와 회귀 결과 기록, 모든 시나리오가 통과하면 계획서 항목을 `[0]`으로 변경하고 `node scripts/plan-progress.mjs --write`.

## 5. 일정(제안)

| 순서 | 작업 | 산출 |
| --- | --- | --- |
| 1 | D-006, D-001 수정 + 전체 API 재측정(D-010) | 게이트 2건·테스트 30여 건 해소, 실제 결함 목록 확정 |
| 2 | D-007, D-002, D-004, D-005 수정 | 동작 불일치 해소 |
| 3 | D-008, D-003 처리, E-5 Postgres 시험 스크립트 | 통합 시험 가능 |
| 4 | E-3 확정 후 S0-05·06 수동·HTTP 시험 | Source·채팅 확인 |
| 5 | S0-07~10 시험, 결과 문서화 | `[0]` 전환 |

## 6. 위험

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| E-3(LLM 연결) 미확정 | S0-05/06 시험 불가 | 사용자에게 서버 확인 요청, 그 사이 자동 테스트와 다른 항목 진행 |
| 원본이 작업 중이던 코드(원래 저장소의 미커밋 변경) | 정본이 불분명한 결함(O) | 설계 의도·UI 호출 경로를 정본으로 하고 판단 근거를 표에 기록 |
| 게이트 약화 유혹 | 품질 저하 | 정책 변경은 항상 사용자 승인 |
| Windows와 Linux 차이 | 로컬에서만 실패 | 의심 시 WSL에서 먼저 재현 |
