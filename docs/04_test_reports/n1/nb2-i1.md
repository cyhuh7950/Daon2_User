# NB2-I1 질문 도구 통합 검수 (ysna, 2026-11-24)

- 환경: https://daon2-user.sinsan.kr, 배포 2f0f864(0086). 시험 노트북 `QA-N1-I2a`(notebook-0f18ea607d5ab4bc534759c484279f0a)
- 준비: 승인 지식 범위 "제안서 작업"(Daon2 Demo Project) 연결, 복사한 텍스트 소스 1개 등록
- 같은 질문을 도구 조합만 바꿔 세 번 보냄: "제안서 초안은 언제까지 작성해야 하고, 제안서 작업에서 지켜야 할 주요 기준은 무엇인가요?"

| # | 점검 | 결과 |
| --- | --- | --- |
| 1 | 노트북·승인 지식 범위·소스 1개 준비 | 통과. 단, 범위를 고른 직후 도구 목록을 열면 "승인 지식 범위가 선택되지 않았습니다"(꺼짐·배지 2)로 보이고 새로고침해야 배지 3이 됨 → **N1-B07**(목록이 처음 한 번만 서버 값을 읽음). 증거 `nb2-i1/b07-stale-menu.jpg` |
| 2 | 도구 모두 켬 → 질문 → 답변 과정 ①에 도구 표시, 승인 지식·문서 근거 Citation | 통과. 답변 과정 ① "도구: 승인 지식, Daon2-RAG, Daon2", 지식 패키지 "제안서 작업". Citation 4개 = 소스(raw_source) 2 + 문서 근거(mcp_daon_rag, 제안요청서 PDF 84·107쪽) 2. 증거 `nb2-i1/tools-all-on.jpg`, `nb2-i1/process-tools.jpg` |
| 3 | 지식 연결(Daon2-RAG·Daon2) 끔 → 같은 질문 → mcp_daon_rag Citation 없음, 연결 호출 없음 | 통과. Citation 3개 모두 raw_source, 답변 과정 도구 "승인 지식"만. DB `question_external_citations`에 이 실행의 행 0(첫 질문은 kc-6e48…(Daon2-RAG) 2행). 서버에 연결 호출 별도 로그는 없으므로 "호출 0"은 이 DB 기록과 NB2-F1 단위 시험(test_question_tools_*)으로 갈음 |
| 4 | 승인 지식 끔(연결 켬) → 승인 지식 근거 없음 | 통과. Citation·근거 모두 raw_source, 지식 패키지 빈 목록, 도구 "Daon2-RAG, Daon2" |
| 5 | 새로고침 후 선택 유지 | 통과. 새로고침 뒤 배지 "2개 켜짐", 조회 API 승인 지식 false·Daon2-RAG true·Daon2 true |
| 6 | 정리 | 통과. 화면에서 영구 삭제 → DB notebooks·notebook_overviews·notebook_question_tools·question_external_citations 모두 0행(0084~0086 테이블은 노트북 삭제 시 CASCADE) |

## 확인한 동작 해석

- 이 작업공간의 승인 지식 근거는 지식 연결(Daon2-RAG)을 거쳐 들어온다(`_external_evidence`). 그래서 승인 지식을 켜 두어도 지식 연결 두 개를 모두 끄면 승인 지식 근거가 없다(3번의 지식 패키지 빈 목록). 설계대로이며, 답변 과정이 이를 그대로 보여 준다. → Ruling R-N1-07로 기록.
- 스위치를 빠르게 연달아 누르면 저장 중인 동안 두 번째 누름은 무시된다(설계: 저장이 끝날 때까지 다른 스위치 잠금).

## 결함

- **N1-B07** 질문 도구 목록이 마운트 때 한 번만 서버 값을 읽어, 승인 지식 범위를 바꾼 뒤 새로고침 전까지 옛 상태를 보임. 수정: 목록을 열 때마다 조용히 다시 읽음(`question-tools-menu.jsx`), 시험 `목록을 열 때마다 서버의 최신 도구 상태를 다시 읽는다` RED→GREEN.
