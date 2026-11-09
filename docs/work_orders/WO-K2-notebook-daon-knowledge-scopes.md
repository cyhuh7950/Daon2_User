# WO-K2 노트북의 Daon 승인 지식 선택 (업무 패키지 단위)

| 항목 | 내용 |
| --- | --- |
| 상태 | **초안, 신산님 검토 대기.** 구현 승인 아님 |
| 작성 | 2026-11-09 |
| 기준 | 설계서 §7A.3, §7A.4, §7A.8, 요청서 R-RAG-02, R-D2-06, R-D2-09 |
| 계획서 | 해당 항목 없음. 승인 시 계획서에 항목 추가 |
| 환경 | 로컬 수정, Git을 거쳐 ysna 배포. WSL-server 사용 안 함(2026-11-09 신산님 지시) |

## 1. 합의한 요구 (신산님 지시)

| # | 요구 |
| --- | --- |
| R1 | `Daon 승인 지식`을 누르면 **팝업**으로 전체 목록을 조회한다 |
| R2 | 목록은 Daon2·Daon2-RAG에서 **자동으로 가져온다** |
| R3 | 구조는 프로젝트 → 업무 패키지. 선택 단위는 **업무 패키지 전체**이고 **다중 선택**한다 |
| R4 | 선택한 업무 패키지만 왼쪽 패널에 **소스로 표시**한다 |
| R5 | 업무 패키지에는 **Daon2 승인 지식과 Daon2-RAG 문서 지식을 함께** 포함한다 |
| R6 | 사용자·조직별 제한은 두지 않는다 |

## 2. 확인한 사실

| 항목 | 내용 | 근거 |
| --- | --- | --- |
| Daon2 MCP 도구 | `approved_knowledge_search`, `approved_knowledge_read`, 온톨로지, RuleSet, GraphRAG | `Daon2/apps/api/src/infra/daon2_mcp_ruleset_tools.py` |
| Daon2 호출 범위 | 인자 `scope = {tenant_id, project_id, work_package_id}` 필수 | `Daon2/apps/api/src/app/daon2_mcp_server.py:63` |
| Daon2 ysna 시험 기록 | 17개 중 16개 통과(`graphrag_local` 503). 직접 호출은 안 해 봄 | `Daon2/output/ysna-stage1-20261109/mcp_acceptance_result.json` |
| Daon2 승인 지식 검색 | 필수 `limit`, 선택 `query`. `query`는 자산 이름과 `canonical_key` 문자열 일치만 비교 | `daon2_mcp_ruleset_tools.py:376` |
| Daon2-RAG MCP 도구 | `search_document_evidence`, `get_document_evidence` 2개뿐. `project_id`, `work_package_id`, `question` 필수 | `Daon2-RAG/apps/api/src/app/document_mcp.py` |
| 목록 도구 | Daon2-RAG에는 없음. Daon2는 확인한 파일 범위에서 없음 | 위 두 파일 |
| Daon2-User 등록 상태 | ysna에는 가상 Connector만 있고 실제 서버는 미등록 | ysna `knowledge_connectors` |
| 가상 계약과 실제의 차이 | 가상 `approved_knowledge_search`는 `query` 필수·`scope` 없음. 실제와 다름 | `services/mcp-virtual/mcp_virtual/contracts.py:59` |
| Connector 범위 검사 | 최상위 `project_id`·`work_package_id`만 검사. Daon2의 중첩 `scope`는 검사되지 않음 | `knowledge_connector_service.py:252` |
| 노트북 채팅 | 승인 지식은 Daon2-User DB의 패키지만 읽음 | `question_answering_service.py`, `runtime.py:4774` |

## 3. 작업 범위

### T1. 외부 선행 (Daon2·Daon2-RAG 담당)
- 두 서버에 프로젝트·업무 패키지 목록 도구 추가: 이름 포함, 호출자에게 허용된 범위만 반환 (요청서 R-RAG-02).
- Daon2와 Daon2-RAG의 `project_id`·`work_package_id`가 같은 값인지 확인 (요청서 R-D2-09).
- Daon2-User에서는 수정하지 않는다. 요청서 §3 원칙.

### T2. 실제 서버 연결
- ysna에 실제 Daon2·Daon2-RAG Connector 등록, 연결 확인.
- 실제 계약에 맞게 호출부와 범위 검사 수정(중첩 `scope`, 필수 인자).

### T3. 목록 API
- 두 서버의 목록을 합쳐 프로젝트 → 업무 패키지로 돌려주는 조회 API와 BFF.

### T4. 노트북별 선택 저장
- 업무 패키지 선택을 노트북에 저장하고 조회·변경하는 API.

### T5. 화면
- 팝업: 전체 목록 조회, 다중 선택, 적용.
- 왼쪽 `Daon 승인 지식` 영역: 선택한 업무 패키지만 표시.

### T6. 채팅 질문 연결
- 선택한 업무 패키지 각각에 두 서버를 조회해 답변 근거로 사용하고 인용 표시.
- **구현 전 조사 필요:** 현재 질문 파이프라인에 외부 근거를 넣는 위치, 승인 지식 원문을 읽는 방법(`approved_knowledge_read`는 자산 ID와 판본 ID 필요).

## 4. 검증 (ysna)
- 팝업에 실제 프로젝트·업무 패키지 표시, 다중 선택 후 패널 반영, 새로고침 후 유지.
- 선택한 업무 패키지로 질문했을 때 Daon2·Daon2-RAG 양쪽 근거로 답변하고 인용 표시.
- 선택하지 않은 업무 패키지의 지식이 답변에 쓰이지 않음.
- 서버 연결 실패 시 오류 표시.

## 5. 결정 필요

| # | 질문 | 영향 |
| --- | --- | --- |
| D1 | **결정(2026-11-09):** 요청 문서 `docs/requests/knowledge-scope-list-request-2026-11-09.md`를 신산님이 Daon2, Daon2-RAG 담당 세션에 전달 | T3 이후 전부 선행 |
| D2 | 사용자 권한 전달 방식 (설계서 §16-17). R6로 서비스 계정 하나로 호출해도 되는가 | T2 |
| D3 | 선택 저장에 DB 추가(마이그레이션 0081)가 필요한지 구현 전 확인. 필요하면 승인 | T4 |
| D4 | WO-K1 경로(`knowledge-packages` 가져오기)를 유지할지 | T5 |
| D5 | ysna 배포는 매번 후보 commit·영향·검증·rollback을 제시하고 승인 | T2~T6 |
