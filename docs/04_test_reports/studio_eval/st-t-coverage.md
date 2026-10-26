# Studio 시나리오 ST-T01~T27 추적표

설계서 §14.1의 시나리오가 어떤 시험으로 확인되는지, 확인되지 않은 것은 무엇인지 적는다. 갱신: 2026-10-26(F8-04/05 재점검).
**자동**은 단위·통합 시험, **IT**는 WSL의 실DB 시험(`wsl-run-studio-v2-it.sh`), **E2E**는 WSL 스택의 `deploy/daon2-user/qa/e2e_studio_v2.py`(실제 LLM·실제 DB·실제 워커), **브라우저**는 사람이 실제 앱 화면에서 확인하는 항목이다.
"미검증"은 시험이 없거나 실행하지 못한 것이며, 통과로 보지 않는다. LLM이 지시를 따랐는지에 달린 E2E 항목은 따르지 않으면 **INCONCLUSIVE**로 출력해 통과로 세지 않는다(이번 실행은 0건).

| ID | 시나리오 | 확인 근거 | 상태 |
| --- | --- | --- | --- |
| ST-T01 | 소스 선택 후 보고서 생성, 생성 중 카드 | 자동: `studio-panel-react` "타일 클릭은 선택한 소스로 createOutput을 호출하고 생성 중 카드를 보여준다". E2E `--st-t`: 생성 요청 뒤 **0.2초 안에** 목록에 `queued` 카드가 보임, `--with-source`: 7종 생성 | 확인(실제 브라우저에서의 렌더 시간은 **미검증**) |
| ST-T02 | 생성 중 채팅 질문이 막히지 않음 | E2E `--st-t`: 보고서가 `generating`인 동안 같은 노트북에 채팅 질문 → 200, 1.2초 만에 답변, 답변 후에도 생성은 계속 진행 | **확인**(2026-10-26) |
| ST-T03 | 연필 아이콘으로 설정 변경 후 생성 | 자동: `test_studio_v2_settings`, `studio-panel-react` 다이얼로그 연결(엔진·보이스 선택 포함). E2E `--st-t`: 포커스 설정이 산출물 `settings`·provenance `instruction.focus`에 기록되고 본문에 반영됨 | **확인** |
| ST-T04 | 소스 0개일 때 타일 비활성·안내 | 자동: `studio-panel-model` "타일 활성 규칙", `studio-panel-react` "소스가 없으면 타일이 비활성…". E2E: 소스 없는 생성 409 | 확인 |
| ST-T05 | 인용 번호 클릭 시 소스 위치 열림 | 자동: `studio-panel-react` "인용 번호를 누르면 그 근거의 소스 위치(발췌)가 열린다"(클릭 → `getEvidenceContent` 호출 → 발췌 표시), v2 근거 콘텐츠 엔드포인트(`test_studio_v2_runtime_http`). E2E: evidence content 200 | **확인**(PDF 쪽 이동 등 실제 브라우저 뷰어는 **미검증**) |
| ST-T06 | 존재하지 않는 근거 참조 처리 | 자동: `test_studio_v2_generation`(알 수 없는 근거 제거·근거 없음 실패), 작성 점검 `evidence_integrity`(`test_authoring_checks`) | 확인 |
| ST-T07 | 생성 중 취소 | 자동: IT "cancel queued job", `test_studio_v2_generation` "cancel check stops generation". E2E `--st-t`: **실행 중(generating)인 보고서에 취소 → 실제 워커가 멈추고 카드가 `cancelled`** | **확인** |
| ST-T08 | 워커 강제 종료 후 재시도·실패 사유 | 자동: IT "sweeper dead letters exhausted lease" | 부분 확인(실제 프로세스 강제 종료는 임대 만료까지 기본 900초라 **미검증**) |
| ST-T09 | 소스·지식 새 버전 시 stale 배지 | 자동: `test_studio_v2_knowledge_stale`(MCP 지식 변경), `studio-panel-model`/`studio-panel-react` "소스가 변경됨" 배지. **IT(실DB, 2026-10-26)**: 옛 `source_versions` v1로 만든 산출물은 stale, 최신 v2로 만든 산출물은 stale 아님(목록·상세 모두) | **확인**(실제 새 버전 업로드 흐름 → 화면은 **미검증**) |
| ST-T10 | 채팅 답변 "메모에 저장" | 자동: `product-workspace` 메모 저장 시험, IT "memo is completed and idempotent". E2E: 메모 생성·내보내기 | 확인 |
| ST-T11 | 퀴즈 풀이·제출 | 자동: `studio-panel-react` "퀴즈를 풀고 제출하면 정오 표시·결과 점수·시도 기록이 남고…"(선택 → 제출 → 정답/오답 → 결과 1/2 → `recordLearningAttempt`), IT "learning attempts are private" | **확인**(실제 브라우저 조작은 **미검증**) |
| ST-T12 | 형식별 다운로드 | E2E: report docx/pdf/md, mind_map svg/png/json, slides pptx/pdf, 작성 문서 docx/pptx/pdf, 오디오 mp3, 동영상 mp4·vtt. 자동: `test_studio_v2_export`. **2026-10-26 실제 파일을 Word·PowerPoint·Excel에서 열어 확인**(DOCX 2쪽·표·제목, PPTX 10장 모두 글자, XLSX 시트 2개), PDF 7개 글자 추출, PNG·SVG·CSV(BOM)·JSON 검증. 실제 앱에서 DOCX·PDF·MD 내려받기(MIME·파일 이름) 확인 | **확인** |
| ST-T13 | 권한 없는 사용자 접근 | 자동: `test_user_without_workspace_access_is_forbidden_on_every_studio_route`(권한 없는 사용자는 types·목록·상세·내보내기·오디오·생성·삭제 모두 **403**, 서비스 호출 0), 타인 산출물은 404(`test_hidden_output_is_not_found_for_other_owners`), IT 타 사용자 격리 | **확인** |
| ST-T14 | 외부 전송 차단 정책 | 자동: `test_studio_v2_generation` "gate checks policy/destination/kind/size", "external provider needs gate and policy". 오디오·동영상: `test_tts_audio`·`test_studio_video`(정책 차단·마스킹), E2E(WSL 정책으로 허용된 음성 서버만 호출) | 확인 |
| ST-T15 | 새로고침 시 카드 유지 | E2E `--st-t`: **재로그인(새 세션)한 뒤에도** 카드가 같은 제목·상태(`completed`)로 목록에 남음. 목록은 서버 저장 | **확인**(브라우저 새로고침 자체는 **미검증**) |
| ST-T16 | 카드 ⋮ 메뉴 순서·생성 중 다운로드 비활성 | 자동: `studio-panel-react` "메뉴는 항목 순서를 지키고…", `studio-panel-model` "카드 상태와 메뉴 항목 규칙" | 확인 |
| ST-T17 | 프롬프트 및 소스 보기 | 자동: `studio-panel-react` "프롬프트 및 소스 보기…"(UI). E2E: provenance 200, `--st-t`에서 focus 기록. API: `test_sharing_is_notebook_scoped_and_provenance_hides_prompt_text`(시스템 프롬프트 없음) | 확인 |
| ST-T18 | 맞춤설정 적용 | 자동: `studio-panel`/`notebook-menu` 시험, `test_chat_customization`, IT "customization is versioned". E2E `--st-t`: **새 보고서 제목이 지시("[맞춤]으로 시작")를 따름**, **채팅 답변이 지시("영어로만")를 따름**(ASCII 100%), **기존 산출물은 리비전·본문이 그대로**, 원래 지시 복원 | **확인**(서식 지시처럼 모델이 무시하는 경우가 있어, 판정이 확실한 지시로 검증했다) |
| ST-T19 | 채팅 기록 삭제 | 자동: `notebook-menu` 시험, `test_notebook_copy_integration`(본인 행만). E2E `--st-t`: **채팅이 있는 노트북에서** 삭제 전 `conversation` 있음 → 삭제 204 → 이후 `conversation`이 비어 숨겨지고 산출물은 유지. 실제 앱 화면에서도 삭제 호출·서버 기록 확인(2026-10-26) | **확인** |
| ST-T20 | 노트북 복사 | 자동: `notebook-menu` 대화상자, IT(메모·맞춤설정 복제, 새 소유자, 채팅 미복제, 멱등), E2E: 복사 201·재생 200·키 재사용 409. 실제 앱 화면: 복사 후 새 노트북으로 이동, 제목·맞춤설정 복제 | 확인(Source는 복사하지 않기로 결정, 안 C) |
| ST-T21 | 산출물 공유 대화상자 | 자동: `studio-panel-react` 공유 대화상자("공개 링크 없음"). API: `test_sharing_is_notebook_scoped_and_provenance_hides_prompt_text` | 확인(조회 전용) |
| ST-T22 | 슬라이드 생성·PPTX 다운로드 | E2E: slides export pptx 200. 자동: `test_studio_v2_export`. **PowerPoint에서 실제로 열어** 10장·장마다 제목·본문·근거 표기를 확인하고 슬라이드를 PNG로 렌더해 눈으로 확인 | **확인** |
| ST-T23 | 마인드맵 노드 "이 개념으로 질문" | 자동: `product-workspace` "마인드맵 노드 질문…"(입력창 채움·자동 전송 없음·1회 범위) | 확인(브라우저 실화면 **미검증**) |
| ST-T24 | 플래시카드·퀴즈 학습 모드 | 자동: `studio-panel-react` "플래시카드는 알아요/모르겠어요를 기록하고 '모르는 카드만' 모드는 모르는 카드만 보인다", 퀴즈 "틀린 문항만 다시"(1/1, 틀린 문항만 표시), IT "learning attempts" | **확인**(실제 브라우저 조작은 **미검증**) |
| ST-T25 | 보고서 형식 선택 | 자동: `test_studio_v2_types`(presets), `PRESET_GUIDES`, 다이얼로그 시험. E2E `--st-t`: 같은 소스·포커스로 `summary`와 `briefing`을 만들면 **섹션 구조가 다름**(실행한 세 번 모두 다름: 3 vs 4, 4 vs 2 등), `format_id` 기록 | **확인**(결과 품질은 사람 평가) |
| ST-T26 | 동시 생성 한도·대기 표시 | 자동: IT "per user concurrency limit and other user", `studio-panel-react`/`studio-panel-model` "대기 중" 시험 | 확인 |
| ST-T27 | 내보내기 인증 | 기본 설정에서 추가 인증 없이 다운로드는 E2E로 확인. 정책 ON: 자동 `test_export_requires_step_up_only_when_the_organization_enabled_it`(승인 토큰 없으면 403, 있으면 200), UI 시험(비밀번호 대화상자→토큰→재시도). 관리자 정책 API 시험 | 확인(실제 토큰 발급·소비 E2E는 관리자 계정이 필요해 **미검증**) |

## 요약 (2026-10-26)

- 확인: T01~T07, T09~T11, T13~T21, T24~T26 (일부는 실제 브라우저 조작이 남음 — 위 표의 괄호)
- 부분 확인: T08(프로세스 강제 종료), T12·T22(Office 앱에서 열기는 수동)
- 미검증 항목은 모두 **사람이 실제 브라우저·Office·관리자 계정으로 해야 하는 것**이거나 실행 시간이 비현실적인 것(T08)이다. 자동화로 줄일 수 있는 항목은 이번에 모두 줄였다.
- 이번에 줄어든 항목: T02(미검증→확인), T03, T05, T07, T09, T11, T13, T15, T18, T19, T24, T25.
- 결정: T20의 Source는 복사하지 않음(안 C)

## 실행 방법

```bash
# 실DB 시험(소스 새 버전 stale 포함)
bash deploy/daon2-user/wsl-run-studio-v2-it.sh
# 실제 LLM이 필요한 E2E(약 5분)
python3 deploy/daon2-user/qa/e2e_studio_v2.py --st-t
```

실제 브라우저에서 사람이 확인하는 항목은 개발용 인증 우회(개발 프로필 한정)로 로그인 없이 열 수 있으나, 개발 테넌트에는 LLM 모델이 없어 생성 화면은 `tools/visual-harness`(가짜 데이터)로 확인한다.
