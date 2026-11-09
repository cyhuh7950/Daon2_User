# WO-K3 노트북 채팅에서 Daon 승인 지식 사용 (WO-K2 T6)

| 항목 | 내용 |
| --- | --- |
| 상태 | **권장안 승인(2026-11-09 신산님).** 1단계 구현. ysna 사용은 E1 확인 후 `DAON_NOTEBOOK_EXTERNAL_EVIDENCE_ENABLED=true`로 켠다 |
| 작성 | 2026-11-09 |
| 기준 | 설계서 §7A.4(지식 소비 모델), §7A.8(보안), WO-K2 R4·R5 |
| 전제 | ysna `6f9bb0ee`, Connector 2개 연결됨, 노트북별 업무 패키지 선택 저장 동작 확인 |

## 1. 목표

노트북에서 선택한 업무 패키지의 승인 지식으로 질문에 답하고, 답변에 인용을 표시한다. 미승인 지식과 선택하지 않은 업무 패키지의 지식은 쓰지 않는다.

## 2. 확인한 사실

| 항목 | 내용 | 근거 |
| --- | --- | --- |
| 현재 검색 | 질문은 Daon2-User 안의 색인만 검색한다. 선택한 업무 패키지는 읽지 않는다 | `question_answering_service.py` `_search_context` |
| 질문 입력 | 자료 종류는 `source`, `knowledge_package`뿐이고 그 외는 거부한다. 최대 8개 | `runtime.py` `_question_inputs`, `QuestionKnowledgeContextBody` |
| 인용 종류 | `raw_source`, `daon_knowledge` 두 가지만 저장·표시한다 | `question_answering_postgres.py`, `product-workspace-shell.jsx`, `question-answering-api.js` |
| 질문 흐름 | 인증 확인 단계와 실제 질문 단계에서 근거를 각각 검색하고, 전송 내용 지문을 대조한다 | `question_answering_service.py`, `runtime.py` |
| 외부 호출 선례 | 문서 작성 기능이 Connector로 외부 근거를 모은다 | `authoring/pipeline.py` `KnowledgeCollector` |
| Connector 기본 한도 | 분당 30회, 동시 4건, 25초 | `knowledge_connector_service.py` |
| RAG 검색 응답(실제 호출) | `result[]`: `document_id`, `version_id`, `run_id`, `block_id`, `page_no`, `text`, `text_truncated`, `similarity`, `resource_uri`. 두 업무 패키지 모두 3건 반환. **문서 이름 없음** | ysna 실제 호출 2026-11-09 |
| RAG 검색 조건 | 활성 문서, 현재 판본, 최신 완료 run, `verified` 블록. **승인 판정 조건은 코드에서 찾지 못함** | Daon2-RAG `postgres_mcp_evidence_scope.py` |
| RAG 승인 문서 수 | 승인 화면과 같은 기준. `제안서 작업` 7, `Insurance Policy Support` 2 | Daon2-RAG 회신, ysna 실제 호출 |
| Daon2 승인 지식 검색 | `scope`, `limit` 필수. `query`는 자산 이름·키 문자열 일치만 비교. 두 업무 패키지 모두 0건 | `daon2_mcp_ruleset_tools.py`, ysna 실제 호출 |
| Daon2 승인 지식 읽기 | `asset_id`, `version_id` 필수. `content`와 `evidence` 반환 | `daon2_mcp_ruleset_tools.py` |

**저장 구조 확인(구현 중):** 기존 `citations`는 로컬 `evidence_spans`와 Studio·보고서 조회에 묶여 있어 외부 인용은 새 표에 분리한다.

## 3. 선행 요청 (Daon2-RAG)

| # | 요청 | 이유 |
| --- | --- | --- |
| E1 | `search_document_evidence`, `get_document_evidence`를 승인 문서 수와 같은 승인 기준으로 제한. 또는 이미 제한된다면 그 위치를 회신 | R5. 검색 결과만으로는 Daon2-User가 승인 여부를 판단할 수 없다 |
| E2 | 검색 결과에 문서 이름 추가 | 인용에 사람이 읽을 수 있는 출처를 표시하기 위해. 실제 서버에는 `list_documents`가 없다 |

E1이 해결되기 전에는 ysna에서 켜지 않는다. E2의 필드 이름은 미확정이며 코드는 `document_name`이 있으면 쓰고 없으면 문서 ID를 표시한다.

## 4. 제안 설계

### 4.1 단계

| 단계 | 범위 | 조건 |
| --- | --- | --- |
| 1단계 | Daon2-RAG 문서 근거 | E1, E2 |
| 2단계 | Daon2 승인 지식 | 게시된 자산이 생긴 뒤. `query`가 이름 일치뿐이라 질문 문장으로 찾는 방법을 Daon2와 먼저 정한다 |

### 4.2 1단계 흐름

1. 질문이 오면 서버가 노트북의 `notebook_knowledge_scopes`를 읽는다. 브라우저가 보낸 값은 쓰지 않는다.
2. 호출 직전에 승인 문서 수와 허용 범위를 다시 확인하고, 조건에서 벗어난 업무 패키지는 제외한다.
3. 업무 패키지마다 `search_document_evidence`를 호출한다.
4. Daon2-User 소스 근거와 합친다. 점수 척도가 달라 점수로 섞지 않고, 소스 최대 5건과 승인 지식 최대 5건으로 나눈다. 전체 상한은 지금과 같은 10건이다.
5. 외부 근거 본문은 데이터로만 취급한다. 본문 속 지시문은 따르지 않는다.
6. LLM 전송은 기존 외부 전송 판정을 그대로 거친다.
7. 답변에 실제로 인용된 외부 근거만 스냅샷으로 저장한다(§7A.4).
8. 인용을 누르면 저장된 스냅샷 본문을 보여 준다. 원본 파일은 열지 않는다.

인증 확인 단계와 실제 질문 단계의 검색 결과가 달라지면 지문 대조가 실패한다. 같은 실행에서는 첫 검색 결과를 재사용한다.

### 4.3 변경 범위

| 영역 | 내용 |
| --- | --- |
| DB `0082` | `question_external_citations` 신설: 실행, 인용 키, Connector, 프로젝트, 업무 패키지, 문서, 판본, run, 블록, 페이지, 문서 이름, 본문, 해시, 조회 시각. 노트북 삭제 시 함께 삭제. 기존 데이터 변경 없음 |
| API | 외부 근거 조회 모듈 신설, `_search_context` 연결, 인용 종류 `mcp_daon_rag` 추가, 스냅샷 저장·조회 |
| 화면 | 인용 검증에 새 종류 추가, 출처 표시(업무 패키지, 문서 이름, 페이지), 스냅샷 보기 |
| 설정 | RAG Connector 호출 한도 상향(기본 분당 30회는 업무 패키지 수만큼 질문마다 소모). 노트북당 선택은 최대 8개 |
| 정본 | 설계서 §7A.4에 질문 경로 반영 |

### 4.4 오류 처리

| 상황 | 동작 |
| --- | --- |
| 선택한 패키지 검색 실패 | D2 결정에 따름. 조용히 일반 답변으로 넘어가지 않는다 |
| 근거 0건 | 모델을 호출하지 않고 근거 없음 안내 |
| 선택 패키지가 승인 조건에서 벗어남 | 제외하고 답변에 사용 안 함 |
| Connector 미등록 | 연결 준비 안 됨 안내 |

## 5. 검증

- 선택한 업무 패키지의 승인 문서로만 답하고 인용이 표시된다.
- 미승인 문서, 선택하지 않은 업무 패키지의 내용이 근거로 쓰이지 않는다.
- 소스와 승인 지식을 함께 쓸 때 양쪽 인용이 구분된다.
- 새로고침 뒤에도 답변과 인용이 그대로 열린다.
- RAG 장애, 토큰 실패, 외부 전송 거부가 안내된다.
- 근거 본문 속 지시문이 동작을 바꾸지 않는다.
- 기존 소스 질문의 시험 결과가 기준선에서 나빠지지 않는다.

## 6. 결정 요청

| # | 질문 | 권장 |
| --- | --- | --- |
| D1 | 선택한 업무 패키지를 질문마다 자동으로 포함할까, 질문할 때 따로 고를까 | **승인.** 자동 포함 |
| D2 | RAG 장애 때 질문을 오류로 끝낼까, 소스만으로 답하고 경고할까 | **승인.** 오류로 끝냄 |
| D3 | 마이그레이션 `0082` 추가 승인 | **승인** |
| D4 | 1단계를 Daon2-RAG만으로 진행할까 | **승인.** Daon2는 2단계 |
