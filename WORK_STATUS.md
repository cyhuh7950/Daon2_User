# WORK_STATUS

비상 시 이어받기 위한 단계별 작업 기록. 상태 정본은 `docs/daon2_user_development_plan.md`, 작업 내용은 `docs/work_orders/WO-*.md`.
규칙: 작업 위치 `D:\Project\Daon2_User`(main), 단계마다 커밋 후 `git push origin main`. 진행 순서 WO-F1 → F2 → D → S1 → M0 → A1 → T0.

## 승인 사항 (2026-10-20, 사용자)
- 7개 WO 전체 승인, 계획서 범위 내 추가 질문·승인 없이 완료까지 진행.
- WSL daon2_user 스택·전용 Postgres(5436) 대상 0074 적용·재빌드·`DAON_STUDIO_V2_ENABLED=true`·시험 전용 DB 생성/삭제 사전 승인(다른 스택·DB·역할 금지).
- Ollama `192.168.220.180:11434` 사용 허용(외부 유료 Provider 금지). D-009는 알려진 실패로 기록, MCP SDK는 가상 서버 이미지에만 설치.
- LLM(사용자 정정): Ollama는 `https://ollama-api.sinsan.kr`. 사용 순서 1 Media Bridge Server(`https://media-bridge-gateway.sinsan.kr/v1`, OpenAI 호환, auto·uss/solar-pro4) → 2 Upstage → 3 OmniRoute → 4 Ollama. 설정은 daon-user의 소스와 설정을 모두 가져온다. API Key는 .env가 아니라 DB에 등록(암호 저장). 비밀값은 채팅·문서·커밋에 쓰지 않는다.
- 작업 위치: 이 worktree(origin/main과 동일, 후크가 기준 저장소 직접 편집을 막음). 푸시는 `git push origin HEAD:main`, 이후 기준 저장소 `git pull --ff-only`.
- 유지 규칙: 비밀값 채팅 출력 금지, Backup 읽기 전용, 게이트 약화 금지.

## 진행 로그
| 일시 | WO·항목 | 상태 | 커밋 | 비고 |
| --- | --- | --- | --- | --- |
| 2026-10-20 | 착수 | 시작 | 3010434d | WO-F1 부터 |
| 2026-10-20 | WO-F1 T1-01 스파이크 | 완료 | 이 커밋 | 삭제 방식 결정 D11(CASCADE, 소유자 daon_notebook_delete) |
| 2026-10-20 | WO-F1 T1-02 플래그 | 완료 | 이 커밋 | DAON_STUDIO_V2_ENABLED, test_studio_v2_settings 4건 |
| 2026-10-20 | WO-F1 T1-03·04 마이그레이션·준비 검사 | 코드 완료, WSL 적용 대기 | 이 커밋 | 0074, cloud_storage/runtime/qa 리비전 집합 갱신, 관련 테스트 150건 통과 |
| 2026-10-20 | WO-F1 T1-05~08 유형·저장소·큐·워커 | 완료 | 6a0c.. | WSL 실DB 통합 시험 통과(test_studio_v2_postgres_integration) |
| 2026-10-20 | WO-F1 T1-09~11,16 라우트·BFF·OpenAPI·근거 콘텐츠 | 완료 | 84da0581 | studio-v2.openapi.json 별도 계약(v1 동결), 루프백 E2E 통과 |
| 2026-10-20 | WO-F1 잔여 | T1-12 자산 캐시·F1-07 SSE(폴링으로 대체, D6)·F1-08 형식 렌더러·F1-10 스냅샷·F1-14·F1-15는 WO-F2에서 | - | 소스 포함 E2E는 LLM 설정 이전 후 |
| 2026-10-20 | LLM 설정 가져오기 | 완료 | 이 커밋 | daon-user의 Provider 연결 12·모델 735·허용 35 + 암호 키 이전(복호화 검증 OK, 값 비출력), 새 Workspace 3곳 text_generation 기본=Media Bridge(uss/solar-pro4). Upstage는 개인 키 방식이라 사용자 키 등록 필요. 새 스택 .env에 남은 *_API_KEY 평문은 사용 안 함(후속 정리) |
| 2026-10-20 | WO-F2 생성 스택 | 완료(실 LLM E2E) | 다수 | 소스 리더·컨텍스트·검증·생성기 6종·내보내기 9형식. WSL에서 합성 약관 업로드→생성→내보내기→근거 보기 전 유형 통과. Provider 우선순위 폴백·외부 전송 정책 게이트(F1-14) 구현 |
| 2026-10-20 | WO-S1/D 화면 | 구현·단위 시험 통과, 브라우저 확인 대기 | 다수 | 패널·뷰어·대화상자·API 클라이언트·셸 통합(소스 체크박스, 404면 기존 Studio로 폴백). 마운트 시험 11건 |
| 2026-10-20 | WO-T0 일부 | D-001 완료, D-006 코드 수정 | 다수 | D-001 .superpowers 헬퍼(37건). D-011 신규: product-workspace.test.mjs 6건 실패(기준선 동일). D-012 신규: test_open_law_source_runtime 2건 실패 |
| 2026-10-20 | WO-D 토큰·레이아웃 | 적용, 브라우저 확인 대기 | 이 커밋 | 토큰 개정+workspace-polish.css. D-013 신규: web-final-ui.test.mjs 9건 기준선 동일 실패 |
| 2026-10-20 | WO-M0 MCP 클라이언트·가상 서버 | 완료(Connector 관리 API 제외) | 이 커밋 | 클라이언트 13건, 가상 서버 2종 WSL 기동, 계약 시험 9/9×2. 결정: MCP SDK 미사용(표준 라이브러리), 위치는 services/mcp-virtual. 남음: T-M0-07 Connector 저장·API, T-M0-08 스냅샷 연동, T-M0-09 관리자 화면 |
| 2026-10-20 | WO-A1 저작 | 완료(WSL 실 E2E 통과) | 이 커밋 | RFP 업로드→가상 MCP 목록→세션→질문→분석(요구 6·섹션 6·지식 30)→확정→생성(대응 6/6)→DOCX/PPTX/PDF 내보내기 전부 통과. 마법사 UI 마운트 시험 4건(브라우저 확인 대기). 결정: 가상 MCP는 운영 프로필에서 차단 유지, WSL 시험 override에만 DAON_MCP_ALLOW_VIRTUAL_QA=true(사용자 승인). 남음: A2/A3 템플릿, 평가 보고서 |
| 2026-10-20 | WO-T0 결함 정리 | 완료(D-009 제외, D-008 일부 기준 저장소 확인 대기) | 이 커밋 | API 전체 2597 통과·0 실패(+격리 7개 파일 통과), web-final-ui 44, product-workspace 91, independence 0건. 시험 갱신 근거는 WO-T0 표. 외부 provider 질문 step-up은 구현을 정본으로 유지 |
| 2026-10-20 | WO-T0 전체 품질 게이트 | 거의 통과 | 이 커밋 | 기준 저장소에서 실행: lint·contract·build·security·independence PASS, 의존성 고위험 20→0. 실패는 cargo 없는 desktop-rust-type·desktop-shell-unit의 Rust 단위(D-009, 알려진 실패)와 mobile-shell-unit(WO-D 토큰 개정 반영해 시험 갱신 → 해소). worktree의 node_modules 접합 때문에 web 빌드·npm 트리 검사는 기준 저장소에서만 가능 |
| 2026-10-20 | WO-M0·S1 잔여 | 완료(브라우저 확인 대기) | 이 커밋 | T-M0-08 stale: MCP 근거의 문서 버전을 get_document_version_status로 확인, WSL E2E에서 bump-version 후 상세·카드 stale 확인. T-M0-09 관리자 지식 연결 화면(settings/knowledge-connectors, 시험 5건). S1-15 채팅 "메모에 저장"·복사. S0-13 질문 범위(체크한 소스 최대 8개, 인용 검증). 남음: T-M0-12 독립성 정책 갱신, T-M0-13 요청 전달(채널 필요), S2-05 노드 질문, S3, S0-11 레거시 제거 |
| 2026-10-20 | 브라우저 실화면 확인(WSL 3340) | 완료, 수정 4건 | 이 커밋 | 확인: Notebook 생성→텍스트 Source 등록·재처리→Studio 보고서 생성→질문·답변→메모 저장(메모 카드·내용)→문서 작성 마법사(소스·제안서 선택→분석→요구사항 확인→초안·탭)→지식 연결 화면(목록·연결 확인·등록 대화상자). 수정: Studio 타일이 옛 CSS(.studio-tiles 5열·가로 스크롤)와 충돌→v2 전용 클래스, 연결 상태 라벨(verified), 지식 연결 화면 스타일 추가, 답변 버튼 색(흰 배경에 흰 글자). 참고: 창 blur/focus 때 Notebook이 다시 불러와지는 것은 기존 보안 설계. 운영 메모: 시험 계정(admin)의 Workspace에서 소스 처리가 되도록 DAON_QA_STRUCTURED_OLLAMA_WORKSPACE_ID를 admin Workspace로 바꿈(.env.bak-qa-ws에 원본). 확인 뒤 QA 계정 Workspace(workspace-011a…)로 되돌림 |
| 2026-10-20 | Source 처리를 설정된 LLM으로 | 완료(WSL 확인) | 이 커밋 | 원인: 가져오기 스크립트가 Workspace 기본 모델을 임의로 Ollama qwen3.5로 덮어씀 → 원본 설정(admin Workspace=Media Bridge uss/solar-pro4)을 복원하고 스크립트는 원본 기본값만 가져오고 임의 기본값은 채우지 않음(기본 모델은 설정 화면에서 지정; 임의로 넣었던 Ollama qwen3.5 행은 삭제). 코드: OriginalDocumentEgressGuard가 Egress 정책(allow_approved_external·목적지·종류·최대 바이트)을 만족하면 외부 LLM 허용(사용자 승인), 기본 모델이 OLLAMA가 아니면 OpenAI 호환 어댑터 사용(개인정보 패턴 마스킹, 핵심 사실 원문 일치 검증). admin Workspace에 daon-user 정책(v34: media-bridge-gateway.sinsan.kr, 64KiB, 마스킹·삭제) 적용. 확인: 새 소스가 uss/solar-pro4(Media Bridge)로 이해됨. 이미지·OOXML·오디오는 크기를 모르는 경로라 외부 전송 계속 거부 |
| 2026-10-20 | 외부 전송 정책 3모드 | 완료(WSL 확인) | 이 커밋 | 외부 전송 차단 / 추가 인증 후 허용 / 추가 인증 없이 허용(= allow_approved_external + 필수 승인자 none, DB 변경 없음). 질문의 추가 인증은 승인 모드에서만, Studio·문서 처리는 "없이 허용"에서만 외부 전송. 개발 단계 기본(DAON_DEVELOPMENT_STAGE=true + DAON_DEV_EGRESS_DESTINATIONS): 처음 만들어진 차단 정책을 "추가 인증 없이 허용"으로 올림(저장된 정책은 유지). 설정 화면 3모드. API 전체 2605 통과·0 실패 |
| 2026-10-25 | WO-A1 A2 약관·계약서 템플릿 | 완료(WSL 실 E2E 통과) | 이 커밋 | 파이프라인을 기준 문서 기반(요구사항 추출 없음)으로 일반화. insurance_terms_draft: 기준 약관+변경점 → 문장 단위 변경 표시(유지/수정/신규)·삭제 제안·필수 조항 점검, DOCX. contract_draft: 기준 계약서 → 법령 도구(search_law, law 종류 Connector)로 법령 대조표(관련/충돌 가능, 법률 자문 아님 문구), DOCX. 템플릿이 제공하지 않는 형식(PPTX)은 내보내기 400. 마법사 화면: 변경 표시·법령 대조 탭, 기준 문서 종류별 조회. 가상 서버에 법령 도구 추가. 남음: A3(템플릿 관리 UI·실제 Daon2 ruleset 연동), 평가 보고서 |
| 2026-10-25 | WO-A1 평가 보고서 | 완료(자동 측정, 사람 채점 대기) | 이 커밋 | 합성 RFP 2건×제안서 3건: 요구사항 재현율 100%·100%, 정밀도 80%·80%, 대응표 10/0/0·8/2/0, DOCX/PPTX 열림 확인, 분석 9~18초·작성 37~59초. 설정된 기본 모델(Media Bridge)로 소스 처리. docs/04_test_reports/studio_eval/authoring-rfp-eval.md (사람 채점 칸 비어 있음). Phase A1 종료 기준 충족 |

## 다음 할 일
1. WSL에 0074 적용·/health/ready 확인(T1-03/04 마무리)
2. WO-F1 T1-05~16 (유형·저장소·큐·워커·라우트·BFF·OpenAPI)
3. LLM 설정 가져오기: Backup의 Provider 설정 소스 대조 + 설정값(DB 연결 행) 이전 절차, 키는 서버 안에서만 처리(WO-T0 E-3와 병행)
4. WO-F2 → D → S1 → M0 → A1 → T0

## /goal 실행 기록 (미완료 계획 항목을 계획서 순서대로 진행)

기록 열: 항목 | 단계 | 담당 | 상태 | 변경 파일 | 테스트 | 오류 횟수(같은 원인 반복) | 미검증 범위 | 다음 조치.
담당은 모두 Claude(단일 code writer, worktree `current-status-check-fd8692`→`origin/main` 직접 푸시).

| 항목 | 단계 | 담당 | 상태 | 변경 파일 | 테스트 | 오류 | 미검증 범위 | 다음 조치 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S1-18 대기 중 표시(ST-T26) | Phase 1 | Claude | [1] 구현·단위 시험 통과 | studio_v2_routes.py(`/types` limits), studio-v2-api.js, studio-panel(.jsx/-model.js), studio-messages.ko.js, 계약 JSON, 시험 3개 | studio-panel-react 13·model·api 7 통과, 계약 재생성 | 0 | WSL 배포·브라우저에서 한도 초과 시 실화면 확인 | 배포 후 확인 |
| S2-05/F2-16 마인드맵 노드 질문 | Phase 1 | Claude | [1] 구현·WSL 배포 | studio-panel, product-workspace-shell, 시험 | UI 시험 통과 | 0 | 브라우저 실화면 클릭 | 없음 |
| S2-11 사용자 편집 | Phase 1 | Claude | [1] 구현·WSL 검증 | studio_user_edit.py, studio_v2_postgres.py, studio-editor.jsx, 시험 | 단위·WSL IT 10·E2E(메모 편집) 통과 | 0 | 브라우저 편집 화면 | 없음 |
| F3-01 맞춤설정 채팅 적용 | Phase 1 | Claude | [1] 구현·단위 시험 통과 | question_answering_service.py(`set_customization_provider`), runtime.py, test_chat_customization.py | 77 통과(채팅 근거·인가 시험 포함) | 0 | WSL 배포 후 실제 질문에서 지시 반영 확인 | 배포 후 확인, 다음 S3-01~03 |
| S3-01~03 상단 바·⋮ 메뉴·맞춤설정 화면 | Phase 1 | Claude | [1] 구현·WSL 배포 | packages/ui/src/notebook-menu.jsx, product-workspace-shell.jsx, workspace-polish.css, scripts/tests/notebook-menu.test.mjs | notebook-menu 2·product-workspace 97·web-final-ui 44·mobile 10 통과 | 0 | 브라우저 실화면(로그인 필요)·실제 질문에서 지시 반영·공유/복사/채팅 기록 삭제는 서버 기능(F3-02/03) 전까지 "준비 중"(비활성) | WO-F3 필요 항목은 승인 요청에 포함 |
| F2-02 제목 자동 생성 | Phase 1 | Claude | [1] 구현·WSL IT 통과 | studio_title.py, studio_v2_postgres.py(`apply_generated_title`), studio_v2_worker.py, 시험 2개 | 단위 3·WSL IT 11 통과 | 0 | 실제 LLM 생성 결과 제목 확인(배포 후 E2E) | 배포 후 확인 |
| F2-17·F1-10·F1-14·F1-15 코드 확인 | Phase 1 | Claude | [1] 기존 구현 확인 | studio_v2_types.py(presets는 /types), studio_v2_postgres.py(settings_json 스냅샷), studio_egress.py, studio_text_generation.py | 해당 시험 기존 통과 | 0 | 없음 | 없음 |
| F1-08 내보내기 렌더러 등록 | Phase 1 | Claude | [ ] 렌더러 등록 구조로 정리, 조직 정책 기반 추가 인증은 미구현 | studio_v2_export.py(`register_renderer`) | export·runtime·authoring 29 통과 | 0 | 내보내기 시 조직 정책 Step-up(정책 항목 정의 필요 — 승인 요청 대상) | 승인 요청 |
| F6-13 점검 엔진(근거 무결성·용어 일관성) | Phase A | Claude | [1] 구현·WSL 배포·E2E | authoring/checks.py, pipeline.py, export.py, authoring-wizard.jsx, 시험 4+1 | 단위 4·wizard 9 통과, WSL E2E(RFP)에서 evidence_integrity·term_consistency 점검 항목 생성 확인 | 0 | 브라우저 점검 탭 실화면 | 없음 |
| F0-11·F0-12 배포 스크립트·컨테이너 상한 | Phase 0 | Claude | [1] 구현·WSL 적용 | scripts/deploy-wsl.sh, deploy/daon2-user/wsl-deploy.sh, compose.wsl-dedicated-postgres.yaml | 스크립트로 배포·헬스 통과, docker stats에서 상한(api 1g·web 512m·document-worker 1.5g 등) 확인 | 0 | 없음 | 없음 |
| S6-03·S7-06 하단 탭·아이콘 교체 | Phase 1 | Claude | [1] 구현·단위 시험 통과 | product-workspace-shell.jsx, workspace-polish.css, workspace.css, studio-icon.js | product-workspace 97·web-final-ui 44·mobile 10·studio-icon 6 통과 | 0 | 좁은 화면 브라우저 실화면 | 없음 |
| F4-12 independence-policy | Phase M0 | Claude | [1] 확인(등록 불필요) | independence-policy.json(변경 없음) | `verify-repository-independence` 위반 0 | 0 | 없음 | 없음 |
| F8-11 임시 Postgres 시험 러너 | Phase 0 | Claude | [1] 구현·WSL 실행 | scripts/run-postgres-tests-wsl.sh | 전체 3,100건 중 2,735 통과·258 실패·241 오류(실패 대부분이 이식 시험의 환경 고정 가드: 승인 DB 이름·D:/tmp 루트) | 499 | 이식 시험의 환경 고정 가드 해소(WO-T0 D-011) | 결정 요청 |
| S6-01·F8-07 접근성 자동 검사 | Phase 1 | Claude | [1] 구현·시험 통과 | scripts/tests/studio-a11y.test.mjs, studio-contrast.test.mjs, notebook-menu.jsx(포커스 가둠) | a11y 4·대비 2 통과(버튼·입력 이름, 대화상자 aria-modal, 탭 aria-selected, 글자 대비 4.5:1 라이트·다크) | 0 | 스크린리더 읽기 순서·실제 키보드 조작·시각 스냅샷(수동) | 브라우저 수동 확인 대기 |
| S6-02 L10N 키 적용 | Phase 1 | Claude | [1] 구현·시험 통과 | notebook/studio-editor/authoring/studio-view-messages.ko.js, studio-panel·dialogs·viewers·editor·wizard·notebook-menu | studio-l10n 13(한글 직접 문구 0, msg 키 존재) 통과, 기존 UI 시험 전부 통과 | 0 | 설정·로그인 등 Studio 밖 화면은 범위 밖 | 없음 |
| F8-08 생성 시간 실측 | Phase 1 | Claude | [1] 실측 기록(목표치는 제안) | docs/04_test_reports/studio_eval/generation-time-baseline.md | 유형별 6~14초(표본 1~2, 1쪽 소스) | 0 | 큰 소스 실측, 목표치 확정(승인) | 승인 요청 |
| F8-04·05 ST-T 추적표 | Phase 1 | Claude | [ ] 추적표 작성, 일부 미검증·미구현 | docs/04_test_reports/studio_eval/st-t-coverage.md, test_studio_v2_runtime_http.py | HTTP 시험 7 통과 | 0 | T02·T19·T20·T27 일부 및 브라우저 확인 항목 | 결정 요청 |
| S7-07 검증 기록 | Phase 1 | Claude | [ ] 자동·정적 + 시험 페이지 화면 확인(다크·라이트·375px) 기록 | docs/04_test_reports/design/theme-responsive-verification.md | 대비·a11y·구조 시험 통과 | 0 | 실제 앱 셸 화면(로그인 필요)·색약·키보드·스크린리더 | 로그인된 브라우저 대기 |
| F7-01·S2-12 인포그래픽 | Phase 2 | Claude | [1] 구현·WSL 배포·E2E | studio_infographic.py, studio_validation.py, studio_generators.py, studio_v2_export.py, studio-viewers.jsx, 시험 9+1 | 단위 9·UI 17 통과, WSL E2E(생성→PNG/SVG/PDF 내보내기→근거 보기) 통과 | 0 | 브라우저 실화면, 큰 소스 품질 평가 | 없음 |
| F7-02 TTS 환경 점검 | Phase 3 | Claude | [ ] 점검·MeloTTS 측정 완료, 모델 선정 미완(MeloTTS는 부적합: 화자 1명·2.3GiB·문장당 약 9초) | docs/04_test_reports/deploy/tts-environment-check.md | GPU 없음·메모리 여유 약 4GiB·ffmpeg 있음 확인 | 0 | 모델 후보 설치·청취 평가(외부 다운로드 승인 필요) | 승인 요청 |
| F4-03 호출 직전 재확인 | Phase M0 | Claude | [1] 구현·WSL 배포·IT | knowledge_connector_egress.py, knowledge_connector_service.py, pipeline.py, studio_v2_worker.py, runtime.py, test_knowledge_connector_egress.py | 단위 3·WSL IT 8·E2E(작성) 통과. 사설·가상 주소는 통과, 공용 주소는 정책(추가 인증 없이 허용+목적지+크기)을 만족할 때만 | 0 | 실제 공용 MCP 서버 호출(미보유) | 없음 |
| F4-02 Connector 한도 | Phase M0 | Claude | [ ] 등록·해제·확인·허용 도구는 있음, Connector별 한도 설정은 미구현 | — | — | 0 | 스키마 변경(마이그레이션 0076)과 준비 상태 판정 9곳 수정이 필요 — 승인 필요 | 승인 요청 |
| F0-13·F8-10 전체 품질 게이트 | Phase 0 | Claude | [1] 전체 통과 | docs/04_test_reports/deploy/quality-gate-2026-10-26.md, toolchain 기준 갱신, desktop-tauri-shell.test.mjs | 7개 범주 PASS, 실패 0, high/critical 0 | 0 | 없음(이전 5건 모두 해소) | 없음 |
| 의존성 보안 갱신(사용자 승인) | Phase 0 | Claude | [1] 반영·로컬 검증, WSL 배포 확인 대기 | apps/web/package.json, package-lock.json, toolchain-versions.json, services/*/pyproject.toml, uv.lock | `npm audit --omit=dev` 0건, 웹 빌드·경계 검사 통과, 스크립트 시험 1,658건 중 1,559 통과(97 실패는 시작 시점부터 있던 환경 고정 시험: 승인 TEMP·누락된 iOS 워크플로·레거시 Studio S22 등) | 97 | 파이썬 pip-audit 재실행(WSL 배포 뒤) | 배포·재감사 |
| WO 3건(WO-F3, WO-A3, WO-F1B) 구현 | Phase 1~A3 | Claude | [1] 구현·WSL 배포·E2E(Source는 복사하지 않기로 결정, 안 C) | migrations/0076, notebook_copy.py, authoring/org_templates.py, authoring_template_routes.py, export_policy_routes.py, knowledge_connector_*.py, UI(notebook-menu, authoring-templates-pane, export-policy-pane, knowledge-connectors-pane), 시험 다수 | 단위·HTTP·UI 통과, WSL IT(복사·템플릿·Connector 한도)·E2E(--notebook-copy, --authoring-org) 통과 | 0 | **실제 채팅이 있는 노트북에서의 비움 효과·내보내기 추가 인증 실토큰 E2E는 미검증** | 없음 |
| S7-07 실제 앱 셸 화면 확인 | Phase 7 | Claude | [1] 개발용 인증 우회로 WSL 앱에서 확인 후 우회 해제·재배포 | packages/ui/src/workspace-polish.css, docs/04_test_reports/design/theme-responsive-verification.md, st-t-coverage.md | 3면 배치·⋮ 메뉴·맞춤설정 저장·복사·채팅 기록 삭제(DB 기록 확인)·하단 탭(375px) 확인. 375px에서 활성 면이 첫 열에 갇히는 결함을 발견해 단일 열 그리드로 수정, 주입으로 확인 | 0 | 색약 시뮬레이션·스크린리더·820px 경계·라이트 테마 앱 셸·채팅 있는 노트북의 삭제 효과는 미검증. 닫은 뒤 포커스 복귀·헤더 문구 가림은 관찰만 | 없음 |
| WO-F7 오디오 개요(선택 가능한 TTS) | Phase 3 | Claude | [1] 구현·WSL 배포(0077)·실제 LLM+supertonic E2E 통과 | tts_engines.py, studio_audio.py, studio_validation.py, studio_v2_{routes,service,postgres,types,worker}.py, migrations/0077, studio-viewers.jsx(AudioViewer), studio-dialogs.jsx, bff-api-proxy.js, compose, qa/e2e_studio_v2.py --audio | 단위 23·API HTTP(Range)·UI·E2E(10줄 약 88초 분량, 생성 77~84초) 통과 | 0 | **청취 품질(사람)·Open RAIL-M 라이선스 확인·실제 앱 화면에서의 생성 조작(개발 테넌트에 LLM 없음)·5분 이상 분량 시간은 미검증**. 엔진 관리 화면(Provider 등록)은 후속 | 라이선스 확인 |
| WO-F7V 동영상 개요(F7-05, S2-14) | Phase 4 | Claude | [1] 구현·WSL 배포·실제 LLM+supertonic+ffmpeg E2E 통과 | studio_video.py, studio_validation.validate_video_scenes, studio_v2_{routes,service,types,export,worker}.py, studio-viewers.jsx(VideoViewer), bff-api-proxy.js, imageio-ffmpeg, qa/e2e_studio_v2.py --video | 단위 12·타입·HTTP·UI·BFF·E2E(5장면 87초) 통과 | 0 | **시청 품질(사람)·실제 앱 화면 조작·5분 이상 분량 시간·글자 크기 개선은 미검증/남음**. 내부 배포 전제(ffmpeg GPL 빌드) | 외부 배포 시 라이선스 재검토 |
| F8-04/05 ST-T 시나리오 재점검 | Phase 1 | Claude | [1] 추적표 재작성, 자동화 가능한 항목 모두 확인 | docs/04_test_reports/studio_eval/st-t-coverage.md, qa/e2e_studio_v2.py --st-t, studio-panel-react.test.mjs, test_studio_v2_runtime_http.py, test_studio_v2_postgres_integration.py | 실제 LLM E2E 26개 통과·INCONCLUSIVE 0, 실DB IT 12건(소스 새 버전 stale), UI 4건 추가(근거 클릭·퀴즈·플래시카드·stale 배지), 권한 403 HTTP 1건 | 0 | **T08 프로세스 강제 종료, T12·T22 Office 열기, T27 관리자 step-up 실토큰, 실제 브라우저 조작(T01 렌더·T05 PDF 뷰어·T11·T23·T24)은 미검증** | 사람 확인 필요
| WO-F7T TTS 엔진 관리 화면(WO-F7 후속) | Phase 3 | Claude | [1] 설계·구현·WSL 배포(0078)·실서비스 점검·실제 E2E 통과 | migrations/0078, tts_engine_service.py, tts_engine_routes.py, studio_audio/video.py(조직별 해석), studio_v2_{routes,postgres,worker}.py, runtime.py, bff-api-proxy.js, tts-engines-api.js, tts-engines-pane.jsx, /settings/tts-engines | 서비스 18·라우트 5·UI/클라이언트 8·BFF 1·실DB IT 6 통과, 화면 등록 엔진으로 실제 오디오 생성 E2E | 0 | **실제 앱 화면 조작은 미검증**(시험 페이지로 렌더만 확인). 관리자 계정의 BFF 관리 API는 사용자 승인으로 시험 스택에서만 qa-e2e를 잠시 관리자로 지정해 E2E 24개 통과 후 원복. 배포 설정 파일 방식은 하위 호환으로 유지 | 관리자 계정으로 화면 확인
| WO-F7T 관리 API E2E(승인된 임시 권한) | Phase 3 | Claude | [1] qa-e2e를 WSL 시험 스택에서만 시스템 관리자로 잠시 지정 → E2E 24개 통과 → 원복 확인(전 경로 다시 403, .env 항목·백업 없음, tts_engines 0행) | qa/e2e_studio_v2.py --tts-admin | 24개 통과 | 0 | 없음 | 없음
| WO-C1 대화 누적·복원 / 소스 지식만 답변 / Studio 유형별 구조 / 모델·추론 수준 선택 | Phase 1~3 | Claude | [1] 구현·WSL 배포(0079)·실제 스택 E2E(`--chat`) 통과. 시각 확인(브라우저)은 개발용 인증 우회 승인이 거부되어 못 함 | docs/work_orders/WO-C1-conversation-source-only-model-selection.md, notebook_copy.py(list_chat_turns), model_selection.py, question_answering_service.py, studio_validation.py, product-workspace-shell.jsx, model-selection-bar.jsx |
| WO-C1 후속: 일반 대화/지식 질문 분리, OmniRoute 실제 연동, ysna 배포, 새 설치용 초기 데이터 | Phase 1~3 | Claude | [1] 저장소를 cyhuh7950/Daon2_User로 이전, ysna-server 배포(daon2-user.sinsan.kr, 마이그레이션 0080)·WSL 데이터 복제. 인사(소스 없음)와 소스 근거 질문이 OmniRoute로 동작(사용자 화면 확인), 오디오 개요 동작(사용자 확인). 초기 데이터(Provider·조직 정책·화면 설정·음성 엔진·라이선스 안내·설명서) 시드 | question_answering_service.py(is_chat_question, OmniRoute 어댑터), question_egress.py, runtime.py(오류 코드), model_selection.py(자동 추론 확인), deploy/daon2-user/{compose.ysna.yaml,ysna-*.sh,seed/*} | 단위 시험 추가(소스 전용·모델 선택 적용·OmniRoute 응답 모양·정책 시드), 실제 OmniRoute 직접 호출, 시드 스크립트를 ysna DB에서 건너뜀·삽입·재실행 확인 | 0 | 관리자 화면은 브라우저로 직접 보지 못함(React 시험·API로만). OmniRoute가 평문으로 답하면 인용을 못 뽑음(보완 미구현). 설명서 PDF는 LibreOffice 변환(글꼴 대체 가능). `DAON_OPEN_LAW_API_KEY`·QA 환경은 ysna에 없음 | 인수 테스트(ysna)
| 인수 테스트 준비(전 항목 개발 측 검증) | 전체 | Claude | [1] 개발 측 검증 완료·보고서 작성 | docs/04_test_reports/acceptance-readiness-2026-10-26.md, daon2_user_remaining_work.md, st-t-coverage.md, theme-responsive-verification.md | API 2,880 통과, node 신규 실패 0(기준선 실패 102), 실DB 18, 실제 LLM E2E 다수, Office 실제 열기, 음성 인식 왕복, 실제 앱 화면 측정. 결함 7건 발견·수정 | 0 | 주관 음질·스크린리더·실제 소스 뷰어·라이선스·외부 서버·수동 평가는 사람/외부 필요 | 인수 테스트
