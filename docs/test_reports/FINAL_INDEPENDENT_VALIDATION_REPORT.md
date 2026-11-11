# Daon2-User 독립 최종 검증 보고서

| 항목 | 내용 |
| --- | --- |
| 검증 기준 시각 | 2026-11-11 (로컬 Windows) |
| 검증 대상 | `D:\Project\Daon2_User` main, HEAD `50533e4fa354c507114d3c1aba24dc1299d55063` (2026-11-10 01:37 UTC, PR #26) |
| 검증자 | 독립 품질검증(개발 담당과 분리). 개발 완료 보고는 참고만 했고 판정 근거로 쓰지 않음 |
| 작업 범위 | 분석과 테스트만 수행. 제품 코드·설계서·매뉴얼 수정, commit·push·배포, 운영 데이터 변경 없음 |
| 작업트리 | 시작·종료 시 `git status`는 미추적 `.serena/`만 있음(기존 상태 그대로). 이 보고서와 `FINAL_INDEPENDENT_VALIDATION_EVIDENCE/`만 새로 추가 |
| **독립 최종 판정** | **CONDITIONAL ACCEPTANCE (조건부 인수)** — 12절 |

---

## 1. 검증 목적과 범위

**목적**: (1) 설계서·매뉴얼 대비 구현 충실도, (2) 테스트 시나리오 실제 수행 결과를 독립적으로 판정한다.

**범위에 포함**
- Studio v2(산출물 9종+메모), 작성(Authoring), MCP 클라이언트·가상 MCP, 노트북 수준 기능, 권한, 오류 처리, 접근성·L10N, 계약(OpenAPI), 빌드·정적 검사.
- 로컬에서 실행 가능한 단위·통합·계약 시험 전체, 로컬 브라우저 화면(시험 페이지), ysna 배포본의 비인증 읽기 확인.

**범위에서 제외(설계·계획이 후속으로 둔 것)**: Phase 5(Mobile·Desktop 화면, 애널리틱스, 산출물별 추가 공유, 검토·승인·전달 재연결), M1 실서버 전환(F5). 이 항목은 "미구현"이 아니라 "계획상 범위 밖"으로 분류한다.

**수행하지 못한 범위(10절에 상세)**: 로그인이 필요한 실제 화면·실제 LLM·실제 Postgres·WSL 정식 스택 E2E. 근거: 전역 지침상 비밀번호 입력 금지, WSL-server는 손대지 않는다는 신산님 지시(WORK_STATUS 승인 사항), 로컬에 Postgres·LLM 없음.

## 2. 기준 자료와 정본 판정

| 자료 | 경로 | 판정 |
| --- | --- | --- |
| 프로젝트 지침 | `AGENTS.md` | 정본 라우터. 단 `PRODUCT.md`를 정본으로 지정하나 **파일이 없음**(결함 F-12) |
| 공통 규칙 | `D:\Project\PMO\AGENTS.md` | 정본(§5.1 1·2단계, §7 환경 역할) |
| **요구·설계 정본** | `docs/daon2-user-studio-design.md` v0.2 초안 | **기준 설계서.** 머리말에 "검토 대기, 구현 승인 아님"이 남아 있고 `sinsan-develop` 저장소를 가리켜 현실과 어긋남 |
| 작업계획서 | `docs/daon2_user_development_plan.md` v1.0 | 진행 상태·완료 기준 정본 |
| 작업현황 | `WORK_STATUS.md`(마지막 행 #111) | 현재 사실 정본(자체 보고). 실제 Git·실행 결과와 대조함 |
| 환경 | `docs/DEVELOPMENT_ENVIRONMENT.md` | 옛 저장소·WSL 기준 기술이 남음(WORK_STATUS 90행이 자체 보고) |
| 남은 작업 | `docs/daon2_user_remaining_work.md`(기준일 10-26) | 참고 |
| 개발 측 시나리오 추적표 | `docs/04_test_reports/studio_eval/st-t-coverage.md` | 참고(주장). 아래에서 독립 재실행 가능한 범위만 재확인 |
| 사용자 매뉴얼 | `docs/manual/daon-user-manual`, `daon-getting-started`, `daon-knowledge-llm-guide` (+`dist/*.docx|pdf`, `apps/web/public/manual`) | 매뉴얼 정본은 `docs/manual/*/index.md`. 공개 사본·dist와 불일치(결함 F-02) |
| 설계서(구) | `D:\Project\Daon_User\docs\Daon 사용자용 프로그램 기본 설계서.docx` | **참고만**. 대화 기록 형태의 3.7천 자 문서(한글 인코딩 깨짐 포함)로, NotebookLM형 Studio 방향성만 담고 있어 요구사항 단위 대조는 불가. 정본은 위 v0.2 설계서 |
| 시험 시나리오 | 설계서 §14.1 ST-T01~T27, 계획서 §완료 기준, `scripts/tests`(146 파일), `services/api/tests`(319 파일), `services/mcp-virtual/contract_tests.py` | 수집 완료 |

정본 충돌·한계: 설계서는 초안 상태로 남아 있고, 이후 결정(Notebook 복사 시 Source 제외, SSE 대신 폴링 등)은 WORK_STATUS·작업지시서에만 있다. 이 보고서는 **설계서 본문을 기준**으로 판정하고, 결정이 문서화된 경우 그 사실을 병기했다.

## 3. 실행 환경

| 항목 | 값 |
| --- | --- |
| OS / 셸 | Windows 11 Home 10.0.26200, Git Bash·PowerShell |
| Node / npm | 24.22.1 / 11.19.1 (`toolchain-versions.json` 일치, `verify-toolchain-baseline` 통과) |
| Python | 3.14.3, `services/api/.venv`(uv). **`lameenc` 미설치**(pyproject 고정 항목과 불일치 → 6건 실패) |
| DB / 큐 / LLM | 로컬에 없음. `DAON_*_TEST_DSN` 미설정 → 실DB 시험 건너뜀 |
| 브라우저 | 앱 내장 브라우저 1개, `tools/visual-harness`(가짜 데이터) 로컬 5199 포트(종료 확인) |
| 가상 MCP | 로컬 127.0.0.1:18641(rag)·18642(ops), 시험용 키는 임시 폴더에만 생성(종료 확인) |
| 원격 | ysna 배포본(`daon2-user.sinsan.kr`)에 **비인증 GET만** 수행 |
| 실행 방식 | API: `PYTHONPATH=src pytest tests`(격리 7파일은 개별 실행, 임시 루트 `D:\tmp\daon2-user-s44-d1-main-20261019` 생성 후 삭제, 잔류 0 확인) / Node: `node --test "scripts/tests/*.test.mjs"` |

## 4. 설계 요구사항 대비 구현 충실도 매트릭스

판정: 충족 / 부분 충족 / 미구현 / 설계 불일치 / 검증 불가. "근거"의 시험은 모두 이번 독립 실행에서 통과한 것이다. 실제 LLM·DB·브라우저 E2E는 NOT RUN이므로 해당 열에 명시한다.

| 요구 ID | 설계서 위치 | 요구사항 | 대응 구현 | 판정 | 근거·한계·위험 |
| --- | --- | --- | --- | --- | --- |
| D-01 | §1.2, P1~P2 | 타일 한 번 클릭 즉시 생성, 설정은 선택형, 기본값 우선 | `studio-panel.jsx`, `studio-panel-model.js`, `POST /outputs`(`studio_v2_routes.py:161`), `studio-dialogs.jsx` | 충족 | `studio-panel-react` 시험 통과, 시험 페이지에서 9개 타일·연필 편집 렌더 확인. 실서비스 클릭→생성은 NOT RUN |
| D-02 | §5 | 산출물 9종+메모, 유형별 내보내기 형식 | `studio_v2_types.py:36-56`(report docx/pdf/md, data_table xlsx/csv/pdf, mind_map svg/png/json, flashcards·quiz csv/json/pdf, slides pptx/pdf, infographic png/svg/pdf, memo md/txt), `studio_generators.py`, `studio_v2_export.py` | 충족 | `test_studio_v2_types`·`test_studio_v2_export`·`test_studio_infographic` 통과. 오디오·동영상은 `test_studio_video` 통과이나 `test_tts_audio` 6건은 `lameenc` 미설치로 실패 → 오디오 MP3 인코딩 경로 **로컬 검증 불가**(운영 이미지 의존) |
| D-03 | §5.2 ST-A1 | 마인드맵 노드 "이 개념으로 질문", 자동 전송 없음 | `studio-viewers.jsx`, `product-workspace-shell.jsx` | 충족 | UI 시험 통과(입력창 채움·1회 범위). 실제 앱 클릭 NOT RUN |
| D-04 | §5.2 ST-A2 | 학습 히스토리(본인 범위), 모르는 카드만/틀린 문항만 | `learning-attempts` 라우트(`:345,:355`), 뷰어 | 충족 | UI·API 시험 통과, 실DB 격리 시험 NOT RUN |
| D-05 | §5.2 ST-A3 | 보고서 형식 5종·부제에 형식명 | `presets=(summary,briefing,blog,study_guide,custom)` | 충족 | `test_studio_v2_types` 통과 |
| D-06 | §6.1 | 패널 상태(소스 없음/선택 0/준비/처리 중) 안내 | `studio.tile.disabled.*` | 충족 | 모델·UI 시험 통과 |
| D-07 | §6.2 | 즉시 "생성 중" 카드, 취소 가능, 연속 생성 별도 카드 | 큐·워커 `studio_v2_queue.py`, 카드 | 충족 | 시험 페이지에서 생성 중·취소 렌더 확인. 1초 이내 응답 실측은 NOT RUN |
| D-08 | §6.3 | 설정 대화상자(언어·형식·길이·소스·지시문·난이도·개수·독자·스타일) | `studio-dialogs.jsx`, 유형별 schema | 충족 | `test_studio_v2_settings`·UI 시험 통과 |
| D-09 | §6.4 | 카드 상태(생성 중/완료/실패+다시 시도/stale) | `studio.card.*` | 충족 | 시험 페이지: "생성 중… 취소", "생성하지 못했습니다 / 다시 시도", "소스가 변경됨" 배지 확인 |
| D-10 | §6.5 | ⋮ 메뉴: 기본 5항목(공유·이름 바꾸기·다운로드·프롬프트 및 소스 보기·삭제)을 고정 순서, 구분선 뒤 추가 항목(다시 생성·설정 변경 후 다시 생성·**메모로 저장**) | `studio-panel-model.js:130 menuItems` | **설계 불일치** | 실제 순서: 공유·이름 바꾸기·다운로드·프롬프트 및 소스 보기·다시 생성·설정 변경 후 다시 생성·삭제(삭제만 구분선 아래). `메모로 저장` 메뉴 **없음**. 시험(`studio-panel-react` 124행)이 실제 순서를 정답으로 고정해 통과함. F-04 결함 |
| D-11 | §6.5.1 | 공유=조회 전용, 공개 링크 없음, Notebook 권한 기준 | `/sharing`(`:336`) | 충족 | API·UI 시험 통과(공개 링크 없음 문구) |
| D-12 | §6.5.2 | 프롬프트 및 소스 보기, 시스템 프롬프트 미노출 | `/provenance`(`:285`) | 충족 | `test_sharing_is_notebook_scoped_and_provenance_hides_prompt_text` 통과 |
| D-13 | §6.6 | 유형별 상세 뷰어(10종), 인용 번호 클릭→근거 | `studio-viewers.jsx`, `/evidence/{ref}/content` | 충족(자동 수준) | UI 시험 통과. 실제 PDF 쪽 이동 등 소스 뷰어는 NOT RUN |
| D-14 | §6.7 | 보고서·메모·슬라이드·카드·퀴즈 사용자 편집=새 Revision | `/revisions`, `studio_user_edit.py`, `studio-editor.jsx` | 충족 | `test_studio_user_edit` 통과. 추가로 "대화로 수정"(`edit-turns`)이 설계 밖 기능으로 구현됨(WO-K5) |
| D-15 | §6.8 | 메모 추가, 채팅 답변→메모(인용 보존), **메모→소스 변환(사용자 명시)** | `/memos`(`:387`), `product-workspace-shell.jsx:850` | **부분 충족** | 메모 추가·답변 저장은 있음. **"소스로 변환"은 `packages`·`apps/web`·`services/api/src` 전체에서 검색해도 없음 → 미구현** |
| D-16 | §6.8.1 | 맞춤설정, 노트북 복사(기본 Source+메모+산출물), 채팅 기록 삭제(본인) | `/customization`, `notebook_copy.py`, `runtime.py:6075 chat-history`, `notebook-menu.jsx` | **부분 충족/설계 불일치** | 맞춤설정·채팅 기록 삭제 충족. **복사는 Source를 복사하지 않음**(`notebook_copy.py:187` 요청 시 409 `NOTEBOOK_COPY_SOURCES_UNSUPPORTED`, 기본값 `k!="sources"`). 결정(WO-F3 안 C)은 있으나 설계서 미반영 |
| D-17 | §6.9 | Web 넓은 화면 오른쪽 패널, 좁은 화면 하단 탭·2열 | `workspace-polish.css`, `product-workspace-shell.jsx` | 충족(자동 수준) | a11y·대비·UI 시험 통과. 375px 실화면은 개발 측 기록만 있고 이번엔 NOT RUN |
| D-18 | §7.1~7.2, §12 | 비동기 큐·리스·재시도 최대 2회(max_attempts 3)·동시 사용자 2/서비스 4 | `studio_v2_queue.py`(`:61`), 마이그레이션 0074(`max_attempts DEFAULT 3`), `studio_v2_worker.py:45-46` | 충족(코드·단위) | 단위 시험 통과. 실DB 통합 시험은 DSN 없어 skip → NOT RUN |
| D-19 | §7.5, ST-T06 | 인용 계약: 존재하지 않는 근거는 제거/실패, "근거 미확인" 표시 | `studio_validation.py`, `studio.evidence.unverified` | 충족 | `test_studio_v2_generation` 통과 |
| D-20 | §7A.1~7A.4 | Daon2·Daon2-RAG를 MCP 표준으로 연결, 승인 지식 소비 | `mcp_client/*`, `knowledge_connector_*.py`, `knowledge_scope_service.py`, `question_external_evidence.py` | 부분 충족 | 클라이언트·연결 단위 시험(108) 통과. **실서버(F5)는 계획상 미착수**, 가상·ysna 연결만 있음 |
| D-21 | §7A.5 | 작성 흐름(템플릿·요구 확인·계획·초안·점검) | `authoring/*`, `template_data/{rfp_response_proposal,insurance_terms_draft,contract_draft,general_document}.py`, `authoring-wizard.jsx` | 충족(자동 수준) | `test_authoring*` 92건 통과. 실제 LLM 작성은 NOT RUN |
| D-22 | §7A.3.3, §7A.8 | Connector 관리, 호출 직전 외부 전송 재확인 | `knowledge_connector_routes.py`, `knowledge_connector_egress.py`, `knowledge-connectors-pane.jsx` | 충족(자동 수준) | `test_knowledge_connector_egress` 등 통과 |
| D-23 | §7A.10 | 가상 MCP 서버와 계약 시험 | `services/mcp-virtual`, `contract_tests.py` | 충족 | 로컬 기동 후 **rag 9/9, ops 9/9 통과**(독립 실행). 실서버 대상은 NOT RUN |
| D-24 | §9 API | 엔드포인트 목록 | `studio_v2_routes.py` 등 | **부분 충족** | 있음: types·outputs CRUD·revisions·regenerate·cancel·exports·provenance·sharing·learning-attempts·customization·memos. 경로 변형: `/assets/{id}`→`/audio`·`/video`, `/copy`→`/copies`, chat-history는 `/workspaces/{id}/notebooks/{nb}/…`. **`/studio/events`(SSE) 없음**(폴링 대체, 결정은 WORK_STATUS에만), `/analytics/studio`는 설계상 1차 제외 |
| D-25 | §9.2 | 오류 코드 7종 | `build-studio-v2-contract.mjs ERROR_CODES` | 부분 충족 | `STUDIO_QUOTA_EXCEEDED`·`STUDIO_EGRESS_BLOCKED` 코드는 코드베이스에 **없음**(외부 전송 거부는 다른 코드). 계약 31종 오류 코드는 검증 통과 |
| D-26 | §9 assets | 오디오·영상 Range 지원 | API는 `Accept-Ranges`·206(`:316-326`) | 부분 충족 | **BFF가 Range를 전달하지 않음**(remaining_work §5에 자체 보고) → 브라우저 경유 시 전체 다운로드 |
| D-27 | §10 | 권한: 생성=편집 이상, 비권한 403, 채팅 개인 범위, 감사 기록 | `studio_v2_routes.py:139 _audit`, 권한 시험 | 충족(자동 수준) | 권한 없는 사용자 전 경로 403 시험 통과. 실계정 다중 사용자 시험 NOT RUN |
| D-28 | §10 | 외부 전송: egress_policy 통과 모델만 | `studio_egress.py`, `egress_policy*.py`, `question_egress.py` | 충족(자동 수준) | 관련 시험 통과 |
| D-29 | §11 | 마이그레이션·기존 Studio 호환 | `migrations/versions` 0074~0083, 기존 `product-studio-*` 유지 | 부분 충족 | 마이그레이션 구문·집합 시험 통과, **실DB 적용·역호환 데이터 시험 NOT RUN**. 레거시 Studio 화면 시험(`product-studio-click` 7건 등) 실패 중(결함 F-07) |
| D-30 | §12 | 시간 목표(참고치)·진행률 중심 | `generation-time-baseline.md`(개발 측 실측 6~14초, 표본 1~2) | 검증 불가 | 실측 NOT RUN. 설계서도 "수치 목표 없이 WSL 실측 후 확정"으로 둠 |
| D-31 | §12 | 접근성(키보드·라벨·대비 4.5:1)·L10N 키 | `studio-a11y`, `studio-contrast`, `studio-l10n` 시험 | 충족(자동 수준) | 모두 통과. 스크린리더·실제 키보드 조작 NOT RUN |
| D-32 | §13 | Phase 0~4 구현, Phase 5 후속 | 해당 코드·WO | 충족 | Phase 0~4 코드 존재 확인. Phase 5는 계획상 범위 밖 |
| D-33 | §14.2 | 합성 코퍼스+수동 평가, 기준선 | `authoring-rfp-eval.md`(사람 채점 칸 비어 있음) | 검증 불가 | 사람 평가 미수행(F8-06 `[ ]`) |
| D-34 | §14.3 | 자동 검증(스키마·참조 무결성·상태 전이·OpenAPI·접근성) | 시험 다수, `verify-openapi-contract` | 충족 | Studio v2 계약(paths 26/ops 32/schemas 61), 전체 OpenAPI(paths 75/ops 94/schemas 120) 통과 |
| D-35 | 계획 F0 | 배포·환경(ysna) | `deploy/daon2-user`, 실서버 | 검증 불가 | 배포본 비인증 확인만: `/` 200, `/api/v1/session` 401. 로그인 후 기능·컨테이너·DB 상태 NOT RUN |

요약: 35개 요구 묶음 중 **충족 24, 부분 충족 6, 부분 충족+설계 불일치 혼합 1(D-16), 설계 불일치 1(D-10), 검증 불가 3, 미구현 단독 0**(미구현은 D-15 안의 "소스로 변환" 1건). "충족 (자동 수준)"은 단위·UI 시험까지 확인한 것이며 실서비스 E2E를 증명하지 않는다.

## 5. 사용자 매뉴얼 대비 실제 동작 충실도 매트릭스

대상: `docs/manual/daon-user-manual/index.md`(문서 업데이트 2026-10-27, Release 1.0.0, 52,155 바이트), `daon-getting-started`, `daon-knowledge-llm-guide`. 판정: 정확 / 부분 정확 / 누락 / 실제 동작과 불일치 / 검증 불가.

| ID | 매뉴얼 위치 | 설명 내용 | 실제 구현(근거) | 판정 |
| --- | --- | --- | --- | --- |
| M-01 | §7.3, §12 전체 | Studio = 유형 선택 → **필수 8개 설정 확정** → `설정 확인` → `생성` → Library → Version 수정 → `검토 요청`·`승인`·`전달` | v2 Studio는 타일 한 번 클릭 즉시 생성, 설정은 선택, 카드 목록, 검토·승인·전달은 **1차 미표시**(설계 §6.5). 레거시 문구가 UI에 남은 곳: `product-studio-pane.jsx`(Library·설정 확인·검토 요청) | **실제 동작과 불일치** |
| M-02 | §12.1 | AI 오디오·동영상은 "JSON 계약만 존재, 사용 불가" | 오디오·동영상 생성기·뷰어·TTS 엔진 관리 구현(WO-F7·F7V·F7T) | **실제 동작과 불일치** |
| M-03 | §12.1 | 유형별 형식(보고서 DOCX/PDF, 슬라이드 PDF/JSON 등) | v2: 보고서 docx/pdf/md, 슬라이드 pptx/pdf, 마인드맵 svg/png/json 등(`studio_v2_types.py`) | 실제 동작과 불일치(형식 목록이 레거시 기준) |
| M-04 | §12.1 구조 표 | 데이터 표·슬라이드·카드·퀴즈 구조 규칙 | v2 검증기 규칙과 대체로 맞는 서술이나 v2 대조는 미수행 | 검증 불가 |
| M-05 | §10.5 | `대화 새로고침`(내 채팅 기록 비우기) | UI에 이 문구 **없음**. 실제는 ⋮ 메뉴의 `채팅 기록 삭제`(`notebook-messages.ko.js:12`) | **실제 동작과 불일치**(버튼명) |
| M-06 | §10.5 | 질문·답변 시간순 누적, 새로고침 후 복원, 사용자별 보기 | `chat-history` API, 복원 시험 통과 | 정확(자동 수준) |
| M-07 | §10.2 | 소스 없으면 지식 질문은 모델 미호출·안내, 일반 대화는 짧게 답함 | `question_answering_service.is_chat_question`, 시험 통과 | 정확(자동 수준) |
| M-08 | §10.6 | 모델·추론 수준 선택, 라우터는 3종 고정, 자동 전환 안 함 | `model_selection.py`, `model-selection-bar.jsx`, 시험 통과 | 정확(자동 수준) |
| M-09 | §8.1~8.5 | Source 추가 메뉴(파일 업로드·웹사이트·Drive·복사한 텍스트·MCP 연결) | `product-workspace-shell.jsx`에 `Source 추가`·`복사한 텍스트`·`텍스트 등록`·`MCP 연결` 문구 존재 | 정확(문구 수준) |
| M-10 | §8.2 | "현재 운영 사용은 PDF 우선, 다른 형식은 조직 검증 후" | PDF 글자 추출 처리 추가(WORK_STATUS #109), 한글 파일명 수정 | 부분 정확(PDF 글자 추출·여러 파일 RFP 등 변경 미반영) |
| M-11 | §7.1, §9 | `Daon 승인 지식`·`연결형 Source`·`Raw Source` 그룹, 승인 지식 선택 질문 | 지식 패키지 가져오기(K1)·노트북 지식 선택(K2/K3)·지식 에이전트(K4) 구현 | 부분 정확(K1~K5 내용 누락, "자동 적용 보장 불가" 서술은 K4 이후 낡음) |
| M-12 | 전체(3문서) | **문서 작성(Authoring) 마법사·템플릿 관리·RFP 여러 파일** | 구현됨(`authoring-wizard.jsx`, `/settings/authoring-templates`) — 매뉴얼 3종에서 `문서 작성`·`RFP`·`템플릿`·`마법사` 검색 결과 **0건** | **누락** |
| M-13 | 전체 | 메모, 노트북 맞춤설정·복사, 대화로 수정, 마인드맵 질문, 학습 모드, 프롬프트 및 소스 보기 | 모두 구현됨. `메모` 1회 언급, `맞춤설정`·`노트북 복사`·`마인드맵` 0건 | **누락** |
| M-14 | 전체 | 관리자: TTS 음성 엔진, 내려받기(내보내기) 정책, 지식 연결 화면 | `/settings/tts-engines`, `/settings/export-policy`, `/settings/knowledge-connectors` 구현. `TTS`·`음성 엔진`·`내려받기` 매뉴얼 0건 | **누락** |
| M-15 | §16 | 조직 정책 초기값(허용 목적지 호스트 목록 등) | 시드 코드와 일치하도록 최근 수정(분류 internal) | 정확하나 **공개 사본은 수정 전 내용**(M-17) |
| M-16 | §1 | "내부 주소를 기록하거나 공유하도록 안내하지 않는다" | §16 표에 허용 목적지 호스트명(`*.sinsan.kr`)이 그대로 기재 | 부분 정확(원칙과 본문 불일치, 공개 저장소 여부는 이번에 재확인하지 않음) |
| M-17 | 배포물 | 정본·dist·Web 공개 사본 동일 | `docs/manual/daon-user-manual/index.md` 52,155B ≠ `apps/web/public/manual/daon-user-manual.md` 52,051B. **ysna 배포본이 서빙하는 파일 해시 = 공개 사본(구판)**. 원인 커밋 `711ab8d9`가 정본 md만 고침(docx·pdf·사본 미재생성) | **실제 동작과 불일치**(배포 매뉴얼이 정본보다 오래됨) |
| M-18 | §3 | 역할(관리자·편집자·검토자·승인자·열람자)별 권한 | v2 Studio 생성=편집 이상(설계 §10), 승인자 권한은 레거시 Studio 전용 | 부분 정확 |
| M-19 | §4 | 가입·로그인·Step-up·비밀번호 재설정 | 로그인 필요 → NOT RUN. 공개 `/` 200 | 검증 불가 |
| M-20 | 재현성 | 선행조건(Workspace 기본 모델·외부 전송 정책 두 탭 모두 저장) | §16에 명시되어 있음. 신규 Workspace에서 재현 NOT RUN | 검증 불가 |

요약: 20개 점검 중 **정확 4, 부분 정확 5, 실제 동작과 불일치 5, 누락 3(핵심 기능 군), 검증 불가 3**. 매뉴얼의 업무 Studio 장(§7.3·§12)과 대화 장 일부가 현행 제품과 어긋나, **매뉴얼만 보고 현재 Studio를 재현할 수 없다.**

## 6. 테스트 시나리오별 실행 결과

### 6.1 수집한 시나리오와 연결

| 출처 | 규모 | 비고 |
| --- | --- | --- |
| 설계서 §14.1 | ST-T01~T27 | 아래 6.3 |
| 계획서 완료 기준 | S0~S7·F0~F9, 192항목 | 진행 요약 블록은 10-20 기준이라 현재 WORK_STATUS와 다름(결함 F-13) |
| 코드 시험 | API 319 파일, 스크립트 146 파일, 가상 MCP 계약 9×2 | 6.2 |

### 6.2 독립 실행 결과 (실제 실행 명령·결과)

| 테스트 ID | 목적·연결 요구 | 실행 명령 | 기대 | 실제 결과 | 판정 |
| --- | --- | --- | --- | --- | --- |
| T-API-01 | API 전체 단위·통합(D-01~D-31) | `cd services/api && PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests -p no:cacheprovider -q --maxfail=1000 --ignore=<격리 7파일>` | 전부 통과 | **7 failed, 3,077 passed, 522 skipped, 2,143 subtests passed**(371.5초). 실패: `test_tts_audio` 6건(`ModuleNotFoundError: lameenc`), `test_notification_dispatch_runtime::…requires_current_ready_0072_before_discovery`(`ValueError: too many values to unpack`) | **FAIL(7)** / PASS 3,077 / **NOT RUN 522(DSN 없는 실DB 시험)** |
| T-API-02 | 복구·스냅샷 격리 시험(7파일) | 파일별 `TMP=D:/tmp/daon2-user-s44-d1-main-20261019 pytest tests/<file>.py` | 통과 | 25+26+17+13+25+48+58 = **212 passed, 11 skipped, 0 failed** | PASS / NOT RUN 11 |
| T-API-03 | 영역별 재확인 | studio_v2 `118 passed, 12 skipped` / studio 기타 `126 passed` / authoring `92 passed` / mcp·knowledge `108 passed, 7 skipped` | 통과 | 전부 통과 | PASS |
| T-JS-01 | 프런트·스크립트 전체(UI·BFF·계약·경계) | `node --test "scripts/tests/*.test.mjs"` | 전부 통과 | **1,758건 중 1,660 pass, 96 fail, 2 skip**(100.8초) | **FAIL(96)** |
| T-CON-01 | Studio v2 OpenAPI 계약 | `node scripts/build-studio-v2-contract.mjs` | 저장본과 일치 | paths=26 operations=32 schemas=61 | PASS |
| T-CON-02 | 전체 OpenAPI | `node scripts/verify-openapi-contract.mjs --no-write` | 통과 | paths=75 ops=94 schemas=120 errors=31 | PASS |
| T-CON-03 | 모바일 Studio 계약 | `node scripts/verify-mobile-studio-contract.mjs` | 통과 | 15/15 actions | PASS |
| T-STA-01 | 정적 검사 | `node scripts/lint-workspace.mjs` | 통과 | 16 files passed | PASS |
| T-STA-02 | 저장소 독립성 | `node scripts/verify-repository-independence.mjs` | 위반 0 | violations=0 | PASS |
| T-STA-03 | 툴체인 기준선 | `node scripts/verify-toolchain-baseline.mjs` | 통과 | 7 manifests, exact pins | PASS |
| T-BLD-01 | 웹 프로덕션 빌드 + 제품 UI 경계 | `npm run build --workspace @daon2-user/web` | 성공 | Compiled successfully, 라우트 목록 생성, 경계 검사 731 files, violations [] | PASS |
| T-MCP-01 | 가상 RAG MCP 계약 | `contract_tests.py --kind rag`(로컬 18641) | required 9/9 | **9/9 PASS** | PASS(가상 서버 한정) |
| T-MCP-02 | 가상 Ops(Daon2) MCP 계약 | `--kind ops`(로컬 18642) | 9/9 | **9/9 PASS** | PASS(가상 서버 한정) |
| T-BRW-01 | 브라우저 실제 렌더: Studio 패널(시험 페이지, 가짜 데이터) | 로컬 vite 5199, 내장 브라우저 | 타일 9, 카드 상태, ⋮ 메뉴 설계 일치 | 타일 9개·13 카드·생성 중/실패/stale/정책 거부 문구 표시. **⋮ 메뉴가 설계 순서와 다름**(D-10) | **FAIL(메뉴) / PASS(렌더)** |
| T-STG-01 | 배포본 비인증 확인 | `curl https://daon2-user.sinsan.kr/`, `/api/v1/session`, `/manual/daon-user-manual.md` | 200 / 401 / 정본과 동일 | 200 / 401 / **구판 매뉴얼(52,051B)** | PASS(가용성) / FAIL(매뉴얼 동일성) |
| T-STG-02 | 로그인 후 실제 사용 흐름 | — | — | 비밀번호 입력 금지·로그인 계정 없음 | **BLOCKED** |
| T-E2E-01 | 실제 LLM·Postgres·워커 E2E(`qa/e2e_studio_v2.py`) | WSL 스택 필요 | — | WSL-server 사용 금지(신산님 지시), 로컬 DB·LLM 없음 | **BLOCKED** |
| T-IT-01 | 실DB 통합(`DAON_*_TEST_DSN`) | 임시 Postgres 필요 | — | 522건 skip | **NOT RUN** |
| T-OFF-01 | PPTX·DOCX·XLSX를 실제 Office로 열기 | — | — | Office 자동화 NOT RUN | **NOT RUN** |

**Node 96건 실패 분류**(파일별, 실제 오류 문구 확인):

| 파일 | 건수 | 확인한 원인 |
| --- | --- | --- |
| `organization-admin-console-react` | 28 | `승인된 L3 TEMP만 사용한다`(환경 고정 가드) |
| `organization-journey-react` / `organization-join-react` | 16 / 14 | 값 불일치(`strictEqual`), 조직 가입 흐름(Studio 밖) — 원인 세부 미분석 |
| `ios-native-shell` | 8 | `.github/workflows/release-1-ios-phase-a.yml` 파일 없음(ENOENT) |
| `product-studio-click` / `product-studio` | 7 / 1 | **레거시 Studio** 화면 시험(`Version 2 · 근거 5 …` 불일치, `STUDIO_RESPONSE_INVALID`) |
| `admin-user-management-react`, `s16-source-actions`, `provider-model-picker-layout` | 3, 2, 2 | 화면 문구·레이아웃 단언 불일치(1920×1080 페이지 높이 1094px 등) |
| `manual-content` | 2 | 정본 ↔ 공개 사본 바이트 불일치(결함 F-02) |
| `daon2-user-compose` | 1 | `provider_credential_key`가 provider 호출부 compose에 남음(보안 단언) |
| `product-ui-boundary` | 1 | 금지 토큰 검사 실패(빌드 산출물 상태 의존, 재현 시 확인 필요) |
| `web-runtime-shell` | 1 | `packages/design-tokens/tokens.css` 해시가 고정값과 다름(WO-D 토큰 개정 후 고정 해시 미갱신) |
| `account-security`(C01 증거), `windows-*`, `platform-prototype-evidence`, `evidence-hub-boundary`, `egress-policy-evidence-hash`, `operations-recovery`, `organization-admin-role-label` 등 | 각 1 | 증거 manifest 파일 부재(ENOENT)·JSON 비어 있음 등 |

개발 측은 "기준선 실패 약 100건, 신규 0건"이라 보고한다. 이번 실행은 96건이며 **과거 커밋과의 실패 목록 대조는 하지 않았다(작업트리 변경 금지)** → "신규 실패 없음" 주장은 **독립 확인 불가**.

### 6.3 설계 시나리오 ST-T01~T27

"자동 근거"는 개발 측 추적표(`st-t-coverage.md`)가 인용한 시험 중, 이번 독립 실행에서 통과한 것을 뜻한다(해당 파일에 실패 없음). 실서비스 E2E(개발 측 주장)는 재실행하지 않았다.

| ID | 시나리오 | 연결 요구 | 독립 확인 근거 | 판정 |
| --- | --- | --- | --- | --- |
| ST-T01 | 소스 선택 후 보고서 타일, 생성 중 카드 | D-01, D-07 | `studio-panel-react` 통과, 시험 페이지 렌더 | PASS(UI 수준). 1초 실측 NOT RUN |
| ST-T02 | 생성 중 채팅 비차단 | D-07 | 실서비스 필요 | **NOT RUN** |
| ST-T03 | 연필 설정 변경 반영 | D-08 | `test_studio_v2_settings`, UI 시험 | PASS(자동) |
| ST-T04 | 소스 0개 타일 비활성 | D-06 | 모델·UI 시험 | PASS |
| ST-T05 | 인용 번호 → 소스 위치 | D-13 | UI 시험(발췌 표시). 실제 뷰어 NOT RUN | PASS(자동) |
| ST-T06 | 존재하지 않는 근거 처리 | D-19 | `test_studio_v2_generation` | PASS |
| ST-T07 | 생성 중 취소 | D-07 | 큐·생성 단위 시험. 실행 중 취소 E2E NOT RUN | PASS(단위) |
| ST-T08 | 워커 강제 종료 후 재시도 | D-18 | 프로세스 종료 시험 없음 | **NOT RUN** |
| ST-T09 | 소스 새 버전 → stale | D-09 | `test_studio_v2_knowledge_stale`, UI 배지. 실DB IT skip | PASS(단위) / IT NOT RUN |
| ST-T10 | 채팅 답변 "메모에 저장" | D-15 | `product-workspace` 시험 | PASS(자동) |
| ST-T11 | 퀴즈 풀이·제출 | D-13 | UI 시험 | PASS(자동) |
| ST-T12 | 형식별 다운로드·파일 열림 | D-02 | `test_studio_v2_export`·`test_studio_export` 통과. Office·PDF 뷰어로 열기 NOT RUN | PASS(자동) / 열기 NOT RUN |
| ST-T13 | 권한 없는 사용자 403 | D-27 | 전 경로 403 시험 통과 | PASS |
| ST-T14 | 외부 전송 차단 | D-28 | `test_studio_v2_generation`·`test_question_egress` 통과, 시험 페이지에 거부 사유 문구 표시 | PASS |
| ST-T15 | 새로고침 시 카드 유지 | D-01 | 서버 저장 필요 | **NOT RUN** |
| ST-T16 | ⋮ 메뉴 순서 | D-10 | 실제 브라우저 렌더에서 **설계 순서와 다름**, `메모로 저장` 없음 | **FAIL** |
| ST-T17 | 프롬프트 및 소스 보기 | D-12 | API·UI 시험 | PASS |
| ST-T18 | 맞춤설정 입력 후 생성 | D-16 | `test_chat_customization`, UI 시험. 실제 생성 반영 NOT RUN | PASS(단위) |
| ST-T19 | 채팅 기록 삭제 | D-16 | UI·API 시험. 실DB 시험 skip | PASS(단위) |
| ST-T20 | 노트북 복사 | D-16 | 복사 코드가 Source를 복사하지 않음(요청 시 409) → 설계 기대("Source·메모·산출물") 불충족 | **FAIL(설계 불일치, 결정 문서화됨)** |
| ST-T21 | 공유 대화상자 | D-11 | UI·API 시험 | PASS |
| ST-T22 | 슬라이드·PPTX | D-02 | export 시험 통과. PowerPoint 열기 NOT RUN | PASS(자동) / 열기 NOT RUN |
| ST-T23 | 마인드맵 노드 질문 | D-03 | UI 시험 | PASS(자동) |
| ST-T24 | 카드·퀴즈 학습 모드 | D-04 | UI 시험 | PASS(자동) |
| ST-T25 | 보고서 형식 선택 | D-05 | `test_studio_v2_types` | PASS |
| ST-T26 | 동시 생성 한도·대기 표시 | D-18 | UI·모델 시험, 설정값 2/4 코드 확인. 실DB IT skip | PASS(단위) |
| ST-T27 | 내보내기 Step-up(정책 ON일 때만) | D-02 | 단위 시험(정책 ON 시 403, 승인 토큰 시 200). 실제 토큰 NOT RUN | PASS(단위) |

집계: **PASS 22(대부분 자동·단위 수준), FAIL 2(T16, T20), NOT RUN 3(T02, T08, T15)**. T12·T22·T09·T26 등은 PASS이나 "실제 파일 열기·실DB"는 별도 NOT RUN이다.

## 7. 발견 결함과 심각도

심각도: **High**=핵심 기능의 오인·오동작 가능, **Medium**=설계·문서 불일치로 업무 영향, **Low**=관리·정리 문제.

| 결함 ID | 심각도 | 내용 | 재현·증거 | 영향 |
| --- | --- | --- | --- | --- |
| F-01 | **High** | 사용자 매뉴얼 §7.3·§12가 **폐기된 레거시 Studio**(필수 8설정·Library·검토·승인·전달, 오디오·동영상 사용 불가)를 설명 | 매뉴얼 §12.1~12.6 대 `studio-messages.ko.js`·`studio_v2_types.py`. 5절 M-01~M-03 | 사용자가 현재 Studio를 매뉴얼로 학습 불가 |
| F-02 | **Medium** | 매뉴얼 정본과 **배포 공개 사본 불일치**. ysna 배포본이 구판 서빙 | `sha256` 정본 `05e1496…` ≠ 공개 사본·배포본 `6b8cb2e…`(52,155B vs 52,051B). `manual-content` 시험 2건 실패. 원인 커밋 `711ab8d9`가 md만 수정 | 최신 안내(분류 internal 값)가 사용자에게 안 보임, docx·pdf도 구판 |
| F-03 | **Medium** | 매뉴얼이 신규 핵심 기능(문서 작성, 메모, 맞춤설정·복사, 대화로 수정, TTS 엔진·내려받기 정책 관리 등)을 전혀 다루지 않음 | 3문서 키워드 검색 0건 | 기능 발견·사용 불가 |
| F-04 | **Medium** | ⋮ 메뉴가 설계 §6.5(기본 5항목 고정 순서+구분선 뒤 추가 항목)와 다르고 `메모로 저장` 항목이 없음. 시험이 비설계 순서를 정답으로 고정 | `studio-panel-model.js:130`, `studio-panel-react.test.mjs:131`, 브라우저 렌더 | ST-T16 불합격, 시험이 회귀를 막지 못함 |
| F-05 | **Medium** | 노트북 복사가 Source를 복사하지 않음(설계 기본 범위 불충족). 결정은 WORK_STATUS·WO-F3에만 있고 설계서 미갱신 | `notebook_copy.py:139,187` | 설계·구현 정본 불일치. 사용자는 소스 없는 빈 복사본을 받음 |
| F-06 | **Medium** | 메모 → 소스 변환("소스로 변환") 미구현 | 전체 검색 0건. 계획 S1-13 `[1]`에도 반영 안 됨 | 설계 §6.8 일부 누락 |
| F-07 | **Medium** | 전체 시험이 녹색이 아님: Node 96건, API 7건 실패. 레거시 Studio·조직·iOS·증거 파일 시험 포함 | 6.2 | 회귀 탐지력 저하. 개발 측 "신규 0건" 주장은 이번에 확인 못 함 |
| F-08 | Medium | 로컬 venv에 `lameenc` 누락 → 오디오 시험 6건 실패, `pyproject.toml` 고정과 환경 불일치 | `ModuleNotFoundError` | 오디오 MP3 경로를 로컬에서 검증 못 함 |
| F-09 | Low | `test_notification_dispatch_runtime` 1건: `too many values to unpack (expected 2, got 3)` | 로그 | 알림 경로 회귀 가능(개발 측 기준선 보고와 일치) |
| F-10 | Low | 설계 §9 대비 API 변형(SSE 없음, `/assets`→`/audio`·`/video`, `/copy`→`/copies`)·오류 코드 2종 부재를 설계서가 반영하지 않음 | 4절 D-24, D-25(요구 ID) | 계약 문서 신뢰도 |
| F-11 | Low | BFF가 Range 미전달 | remaining_work §5 | 긴 오디오·동영상 UX |
| F-12 | Low | `AGENTS.md`가 `PRODUCT.md`를 정본으로 지정하나 파일 없음. 설계서·환경 문서의 저장소·검증 방식 기술이 낡음 | 파일 시스템, WORK_STATUS #90 | 인수 시 혼선 |
| F-13 | Low | 계획서 진행 요약 블록이 현재와 어긋남(10-20 기준), 남은 작업 문서는 "`[x]` 표시 없음"이라 하나 계획서는 `[0]` 52건 | 계획서 §진행 요약 | 진척 판단 혼선 |
| F-14 | Low | 매뉴얼 §1 원칙("내부 주소 기록 금지")과 §16 허용 목적지 호스트 목록이 충돌 | 매뉴얼 §16 | 문서 정책 일관성 |

치명(Critical) 결함은 이번 범위에서 확인되지 않았다. 단, 로그인 후 실제 흐름·실 LLM·실 DB는 검증하지 못했으므로 "없음"이 아니라 "발견되지 않음"이다.

## 8. 회귀 위험

| 위험 | 근거 | 수준 |
| --- | --- | --- |
| 레거시 Studio(`product-studio-*`)와 v2 Studio 공존: 레거시 시험 8건 실패, v2 미지원 시 폴백 | WORK_STATUS S0-11 결정, `product-studio-click` 실패 | 중 |
| 토큰(디자인) 해시 고정 시험 실패: `web-runtime-shell` | 단언 해시 불일치 | 중(시험 갱신 미반영) |
| 시험이 설계를 어기는 현재 동작을 고정(ST-T16) | `studio-panel-react.test.mjs:131` | 중 |
| 실DB·실서버 시험 522건 skip → 마이그레이션 0074~0083, 큐·리스·권한 격리 회귀는 로컬에서 미탐지 | skip 사유 `DAON_*_TEST_DSN` 미제공 | **높음(미검증)** |
| 오디오 인코딩 의존(`lameenc`)·ffmpeg 의존이 운영 이미지에서만 검증됨 | 환경 | 중 |
| 환경 고정 가드 시험 다수(승인 TEMP·고정 경로) → 환경이 바뀌면 의미 없는 실패와 진짜 실패 구분 곤란 | 28건 L3 TEMP | 중 |
| 매뉴얼·공개 사본 드리프트 반복 가능(재생성 절차가 커밋에 묶이지 않음) | F-02 | 중 |

## 9. PASS / FAIL / BLOCKED / NOT RUN 집계

개별 시험 항목(테스트 케이스) 기준, 서브테스트 제외.

| 구분 | PASS | FAIL | BLOCKED | NOT RUN(skip 포함) |
| --- | --- | --- | --- | --- |
| API pytest(주 3,606건) | 3,077 | 7 | — | 522 |
| API 격리 7파일(223건) | 212 | 0 | — | 11 |
| Node(1,758건) | 1,660 | 96 | — | 2 |
| **자동 시험 소계(5,587건)** | **4,949** | **103** | — | **535** |
| 계약·정적·빌드·MCP(T-CON·STA·BLD·MCP, 11건) | 11 | 0 | — | — |
| 브라우저·배포 확인(T-BRW-01, T-STG-01) | 렌더·가용성 | 메뉴 순서, 매뉴얼 동일성 | — | — |
| 설계 시나리오 ST-T01~T27(27건) | 22 | 2 | — | 3 |
| 로그인 후 실사용, 실 LLM·DB·WSL E2E, Office 열기, 스크린리더 | — | — | 2(T-STG-02, T-E2E-01) | 2(T-IT-01, T-OFF-01) 외 다수 |

PASS 비율은 "실행된 시험 중 97.9%(4,949/5,052)"이나 **전체 5,587건 중 535건(9.6%)은 아예 실행되지 않았고, 실서비스 E2E는 전부 미실행**이므로 통과율을 완료도로 읽어서는 안 된다.

## 10. 미검증 범위와 차단 사유

| 미검증 범위 | 상태 | 사유 | 재개 조건 |
| --- | --- | --- | --- |
| 로그인 후 실제 화면·사용자 흐름(가입·로그인·Studio 생성·내보내기·권한별 화면) | BLOCKED | 전역 지침상 비밀번호 입력 금지, 시험 계정 없음 | 신산님이 시험 계정을 로그인된 브라우저로 제공하거나 개발용 인증 우회 허용 |
| 실제 LLM·워커·Postgres E2E(`e2e_studio_v2.py`, 실DB IT 12건, 격리 DB 522건) | BLOCKED/NOT RUN | WSL-server 사용 금지 지시, 로컬 DB·LLM 없음 | 일회성 로컬/임시 Postgres 승인 + `DAON_*_TEST_DSN`, 승인된 LLM 설정 |
| ST-T02, T08, T15 | NOT RUN | 실서비스·프로세스 강제 종료 필요(임대 만료 기본 900초) | 위 조건 + 워커 설정 변경 승인 |
| PPTX·DOCX·XLSX 실제 Office 열기, PDF 글자 확인 | NOT RUN | Office 자동화 미수행 | Office 설치 PC에서 수동 또는 자동화 |
| 오디오·동영상 생성·청취/시청 품질, MP3 인코딩 로컬 시험 | NOT RUN | TTS 서버·`lameenc` 없음 | venv 동기화(`uv sync`)·TTS 엔드포인트 |
| 실서버 MCP(Daon2-RAG·Daon2) 계약 100%(F5) | NOT RUN | 수신측 서버·신원·권한 미정(계획상 외부 의존) | 수신측 가동·서비스 신원 발급 |
| 스크린리더·색약·실제 키보드 조작·좁은 화면 실측 | NOT RUN | 보조기기·로그인 화면 필요 | 수동 확인 |
| 합성 코퍼스 사람 평가(F8-06, 근거 충실도·환각 비율) | NOT RUN | 사람 채점 필요 | 평가자 지정 |
| 개발 측 "신규 실패 0건" 주장(과거 커밋 대조) | 검증 불가 | 작업트리 변경 금지로 과거 커밋 체크아웃 미수행 | 별도 worktree 승인 후 동일 명령 실행 |
| 5분 이상 오디오·동영상·대용량 소스 성능, 부하·장애 복구 | NOT RUN | 2단계(Oracle) 검증 범위 | 2단계 승인 |
| Phase 5·M1 항목 | 범위 밖 | 계획상 후속 | — |

## 11. 수정·재검증 권고사항

우선순위 순. 이 보고서는 수정하지 않았으며, 아래는 담당자에게 넘기는 권고다.

1. **(High) 매뉴얼 §7.3·§12·§10.5 개정** — v2 Studio 기준(한 번 클릭 생성, 선택 설정, 카드 상태, 메뉴, 편집·대화로 수정, 메모, 내보내기 형식, 오디오·동영상 가용 조건)과 `채팅 기록 삭제` 명칭. 문서 작성·맞춤설정·노트북 복사·관리 화면(TTS·내려받기 정책·지식 연결) 장을 신설. 재검증: `manual-content` 시험, 신규 Workspace에서 매뉴얼 절차 그대로 재현.
2. **(Medium) 매뉴얼 산출물 재생성·재배포 절차 고정** — 정본 md 변경 시 dist·`apps/web/public/manual`·manifest를 함께 갱신하고 `manual-content` 시험을 병합 조건에 포함. 재검증: 정본·공개 사본·ysna 서빙 해시 동일.
3. **(Medium) ⋮ 메뉴를 설계대로 정렬하거나 설계서를 개정** — 어느 쪽이든 결정을 문서화하고 시험을 설계 기준으로 교체. `메모로 저장`, "메모 → 소스 변환" 구현 또는 범위 제외를 설계서에 명시. 재검증: ST-T16, ST-T10.
4. **(Medium) 설계서 v0.2 갱신** — 노트북 복사의 Source 제외(안 C), SSE→폴링, API 경로 변형, 오류 코드, 상태 "검토 대기" 해소. 재검증: 설계서와 `studio-v2.openapi.json` 대조.
5. **(Medium) 시험 기준선 정리** — 로컬 venv 동기화(`lameenc`), 환경 고정 가드 시험의 갱신/격리, 레거시 Studio 시험·고정 해시 시험 재정비. "기준선 vs 신규" 구분을 위해 실패 목록을 기준 커밋과 함께 파일로 저장. 재검증: T-API-01, T-JS-01 재실행.
6. **(High, 미검증 해소) 실DB·실 LLM E2E를 독립 환경에서 재실행** — `deploy/daon2-user/wsl-run-studio-v2-it.sh`, `e2e_studio_v2.py --st-t` 및 로그인된 브라우저 상태에서 ST-T02/08/15/12/22 확인. 재검증 결과를 이 보고서의 NOT RUN 항목과 교체.
7. **(Low) 문서 정합** — `PRODUCT.md` 작성 또는 `AGENTS.md` 수정, 환경 문서의 저장소·검증 방식 정정, 계획서 진행 요약 재생성(`node scripts/plan-progress.mjs --write`), 매뉴얼 §1 원칙과 §16 호스트 목록 정리.
8. **(Low) BFF Range 전달** 검토.

## 12. 독립 최종 판정

# **CONDITIONAL ACCEPTANCE (조건부 인수)**

**판정 근거**
- 설계 핵심 기능(Studio v2 9종+메모, 큐·취소·재시도·한도, 인용·검증, 내보내기, 권한 403, 외부 전송 정책, 작성 엔진, MCP 클라이언트와 가상 MCP, 계약·빌드·정적 검사)은 **독립 실행에서 통과**했다(API 3,289 통과, Node 1,660 통과, 계약·MCP 9/9×2, 웹 빌드 성공).
- 그러나 (a) 사용자 매뉴얼이 현행 Studio와 크게 어긋나고(High), (b) 설계 불일치 3건(⋮ 메뉴, 노트북 복사 Source, 메모→소스)과 설계서 미갱신이 있으며, (c) 자동 시험 103건이 실패 중이고, (d) 실DB·실 LLM·로그인 후 화면·Office 열기 등 **실서비스 증거를 이번 독립 검증에서 확보하지 못했다.**
- REJECTED가 아닌 이유: 필수 요구 중 단독 미구현은 "메모→소스 변환"뿐이고 치명 결함은 발견되지 않았다. BLOCKED가 아닌 이유: 구현·자동 시험·계약·정적 검사는 판정 가능한 범위에서 확인했다.

**ACCEPTED로 전환하기 위한 조건**
1. 권고 1~4 완료(매뉴얼·설계서·메뉴·공개 사본 정합) 후 `manual-content` 포함 시험 통과.
2. 권고 6의 실DB·실 LLM E2E와 로그인 후 브라우저 확인을 독립 재실행해 NOT RUN 항목(ST-T02/T08/T15, Office 열기, 522건 skip)을 PASS/FAIL로 교체.
3. 기준선 실패 103건에 대해 "환경 가드/레거시/실결함"을 분류한 목록과 기준 커밋 대조 증거 제출.

## 13. 검증 증거와 관련 파일 목록

**이 검증이 남긴 증거(저장소 내, 신규)**
- `docs/test_reports/FINAL_INDEPENDENT_VALIDATION_REPORT.md` (이 파일)
- `docs/test_reports/FINAL_INDEPENDENT_VALIDATION_EVIDENCE/api-pytest-main.log` — T-API-01 전체 출력
- `docs/test_reports/FINAL_INDEPENDENT_VALIDATION_EVIDENCE/node-tests.log` — T-JS-01 전체 출력(실패 목록 포함)
- `docs/test_reports/FINAL_INDEPENDENT_VALIDATION_EVIDENCE/mcp-virtual-rag-contract.json`, `mcp-virtual-ops-contract.json` — T-MCP-01/02
- `docs/test_reports/FINAL_INDEPENDENT_VALIDATION_EVIDENCE/web-build.log` — T-BLD-01

**주요 대조 파일**
- 설계·계획·현황: `docs/daon2-user-studio-design.md`, `docs/daon2_user_development_plan.md`, `WORK_STATUS.md`, `docs/daon2_user_remaining_work.md`, `docs/work_orders/WO-*.md`
- 개발 측 보고(참고): `docs/04_test_reports/studio_eval/st-t-coverage.md`, `docs/04_test_reports/acceptance-readiness-2026-10-26.md`
- 매뉴얼: `docs/manual/*/index.md`, `docs/manual/dist/*`, `apps/web/public/manual/*`
- 구현: `services/api/src/daon2_user_api/{studio_v2_*.py,notebook_copy.py,authoring/,mcp_client/,knowledge_*.py,runtime.py}`, `services/mcp-virtual/`, `packages/ui/src/{studio-panel*.js*,studio-messages.ko.js,notebook-menu.jsx,notebook-messages.ko.js,product-workspace-shell.jsx}`, `apps/web/lib/bff-api-proxy.js`
- 시험: `services/api/tests/`, `scripts/tests/`, `services/mcp-virtual/contract_tests.py`, `tools/visual-harness/`

**실행 중 생성·정리한 임시 자원**: 로컬 vite(5199)·가상 MCP 서버 2개(18641·18642) 종료 확인, 임시 시험 루트 `D:\tmp\daon2-user-s44-d1-main-20261019` 삭제 확인, 시험용 MCP 키·토큰은 세션 임시 폴더에만 존재(저장소 밖). `apps/web/.next`는 빌드 산출물(.gitignore 대상).

**한계 명시**: 본 판정의 "충족(자동 수준)"은 단위·UI·계약 시험 통과를 뜻하며 실서비스 동작을 증명하지 않는다. Node 실패 중 조직·iOS·증거 파일 관련 일부는 원인 문구만 확인했고 세부 원인은 분석하지 않았다.
