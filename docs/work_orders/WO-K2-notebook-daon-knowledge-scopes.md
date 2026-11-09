# WO-K2 노트북의 Daon 승인 지식 선택 (업무 패키지 단위)

| 항목 | 내용 |
| --- | --- |
| 상태 | **승인(2026-11-09 신산님).** T2~T5 구현. 마이그레이션 0081 승인(D3). T6은 조사 후 별도 진행 |
| 작성 | 2026-11-09 (Daon2-RAG 회신과 신산님 결정 반영) |
| 기준 | 설계서 §7A.3, §7A.4, §7A.8, 요청서 R-RAG-02, R-D2-06, R-D2-09 |
| 계획서 | 해당 항목 없음. 승인 시 계획서에 항목 추가 |
| 환경 | 소스는 Git 기준, PR로 이력 관리, ysna-server는 `main`에서 배포. 비밀값은 로컬 보관. WSL-server 사용 안 함 |

## 1. 합의한 요구 (신산님 지시)

| # | 요구 |
| --- | --- |
| R1 | `Daon 승인 지식`을 누르면 **팝업**으로 전체 목록을 조회한다 |
| R2 | 목록은 Daon2-RAG에서 **자동으로 가져온다.** 새 업무 패키지도 사람이 등록하지 않아도 나타나야 한다 |
| R3 | 구조는 프로젝트 → 업무 패키지. 선택 단위는 **업무 패키지 전체**이고 **다중 선택**한다 |
| R4 | 선택한 업무 패키지만 왼쪽 패널에 **소스로 표시**한다 |
| R5 | **승인·게시된 지식만** 보여주고 사용한다. Daon2-RAG 문서 지식과 Daon2 승인 지식 각각 승인된 것만 해당한다 |
| R6 | 사용자·조직별 제한은 두지 않는다 |

## 2. 확인한 사실

| 항목 | 내용 | 근거 |
| --- | --- | --- |
| Daon2-RAG 목록 도구 | `list_knowledge_scopes` ysna 반영, **Daon2-RAG `main` 병합 전**. 입력 `limit`(1~200)·`cursor`, 출력 `scopes[tenant_id, project_id, project_name, work_package_id, work_package_name, updated_at]`·`next_cursor` | Daon2-RAG 회신 |
| Daon2-RAG MCP | `https://daon2-admin.sinsan.kr/mcp`, 프로토콜 `2026-07-28` | Daon2-RAG 회신 |
| 서비스 자격 | `spn:daon-user` 활성, scope `rag.mcp.evidence.read`, audience는 위 주소. 토큰은 `https://daon2.sinsan.kr/oauth/token`, 수명 300초 이하 | Daon2-RAG 회신, 관리 화면 |
| 접근 등록 | 전체 허용 미지원. 주체별 프로젝트·업무 패키지 쌍 등록. `spn:daon-user`에 2건 등록 | Daon2-RAG 회신 |
| 현재 목록 | Daon2 Demo Project의 `제안서 작업`, `Insurance Policy Support` | Daon2-RAG 회신 |
| `제안서 작업` 승인 상태 | RAG 문서 7건 승인됨. 최종 승인·게시 package 0건(GraphRAG 미승인) | 관리 화면, 신산님 확인 |
| ID 일치 | Daon2-RAG는 같은 값이라고 회신. Daon2에서 이 값으로 호출한 시험은 없음 | Daon2-RAG 회신 |
| 실제 토큰 호출 | 2026-11-09 로컬에서 확인. Daon2-RAG: 토큰 발급, `2026-07-28` 연결, 도구 3개(`search_document_evidence`, `get_document_evidence`, `list_knowledge_scopes`), 목록 2건. Daon2: 토큰 발급, `2025-06-18` 연결, 도구 9개 | 실제 호출 |
| Daon2 MCP 주체 | ysna는 시험용 주체(`spn:daon2-mcp-ysna-test`)만 허용. `spn:daon-user`는 호출 불가 | Daon2-RAG 회신 |
| Daon2 호출 범위 | 인자 `scope = {tenant_id, project_id, work_package_id}` 필수 | `Daon2/apps/api/src/app/daon2_mcp_server.py:63` |
| Daon2 승인 지식 검색 | 필수 `limit`, 선택 `query`. `query`는 자산 이름과 `canonical_key` 문자열 일치만 비교 | `daon2_mcp_ruleset_tools.py:376` |
| Daon2-RAG 근거 검색 | `search_document_evidence`, `get_document_evidence`. `project_id`, `work_package_id`, `question` 필수 | `Daon2-RAG/apps/api/src/app/document_mcp.py` |
| Daon2-User MCP 프로토콜 | `2026-07-28` 지원 | `mcp_client/lifecycle.py:11` |
| Daon2-User 인증 | 고정 Bearer 토큰 저장만 가능. 토큰 발급·갱신 기능 없음 | `knowledge_connector_service.py:131`, `mcp_client/transport.py:55` |
| Daon2-User 도구 허용 | `daon2_rag` 허용 목록에 `list_knowledge_scopes` 없음 | `knowledge_connector_service.py:26` |
| 외부 전송 허용 | 공용 주소는 허용 목록에 있어야 호출됨. 현재 4개 호스트이고 Daon2-RAG MCP 주소 없음 | `knowledge_connector_egress.py`, ysna 배포 로그 |
| Connector 범위 검사 | 최상위 `project_id`·`work_package_id`만 검사. Daon2의 중첩 `scope`는 검사되지 않음 | `knowledge_connector_service.py:252` |
| Daon2-User 등록 상태 | ysna `knowledge_connectors`에 실제 서버 미등록 | ysna DB |
| 노트북 채팅 | 승인 지식은 Daon2-User DB의 패키지만 읽음 | `question_answering_service.py`, `runtime.py:4774` |
| 토큰 요청 값 | 호출 대상별로 따로 요청. Daon2-RAG: resource `https://daon2-admin.sinsan.kr/mcp`, scope `rag.mcp.evidence.read`. Daon2: resource `https://daon2.sinsan.kr/mcp`, scope `ontology.read graphrag.query ruleset.read ruleset.evaluate knowledge.read` | Daon2 회신 |
| 승인 정보 | Daon2-RAG 응답의 `approved_document_count`가 1 이상인 업무 패키지만 표시. 이 값이 없으면 표시하지 않음. 필드 이름은 Daon2-RAG 확정 필요 | `knowledge_scope_service.py` |
| 자격값 입력 | `설정 > 지식 연결`에서 Connector마다 입력하고 DB에 암호화 저장. Secret 로컬 원본은 `D:\Project\Daon2_User\.env`의 `DAON_RAG_SECRET` | 신산님 지시 |

## 3. 작업 범위

### T1. 외부 선행 (Daon2-RAG·Daon2 담당)
- Daon2-RAG: `list_knowledge_scopes`를 `main`에 병합.
- Daon2-RAG: 새 업무 패키지를 `spn:daon-user`에 자동 등록.
- Daon2-RAG: 승인된 것만 고를 수 있도록 목록에 승인 정보 제공(응답 형식은 Daon2-RAG 회신 후 확정).
- Daon2: ysna MCP가 `spn:daon-user`를 받도록 설정, Daon2용 자격 정보 회신, Daon2-RAG 목록 값으로 호출 가능한지 확인.
- Daon2-User에서는 수정하지 않는다. 요청서 §3 원칙.

### T2. 실제 서버 연결
- `client_id`·`secret`으로 토큰을 받아 쓰는 기능 추가(수명 300초 이하, 값 노출 금지).
- `list_knowledge_scopes`를 허용 도구에 추가, Daon2-RAG·Daon2 MCP 주소를 외부 전송 허용 목록에 추가.
- ysna에 실제 Connector 등록, 연결 확인. 자격값은 등록 화면에서 입력한다.
- Daon2 호출의 중첩 `scope` 검사와 필수 인자를 실제 계약에 맞게 수정.

### T3. 목록 API
- Daon2-RAG 목록을 페이지 끝까지 읽어 프로젝트 → 업무 패키지로 돌려주는 조회 API와 BFF. 승인된 것만 반환.

### T4. 노트북별 선택 저장
- 업무 패키지 선택을 노트북에 저장하고 조회·변경하는 API.

### T5. 화면
- 팝업: 전체 목록 조회, 다중 선택, 적용.
- 왼쪽 `Daon 승인 지식` 영역: 선택한 업무 패키지만 표시.

### T6. 채팅 질문 연결
- 선택한 업무 패키지에서 승인된 지식만 조회해 답변 근거로 사용하고 인용 표시.
- `제안서 작업`은 현재 Daon2-RAG 승인 문서만 사용 대상이다. Daon2 승인 지식은 게시되면 사용한다.
- **구현 전 조사 필요:** 현재 질문 파이프라인에 외부 근거를 넣는 위치, 승인 지식 원문을 읽는 방법(`approved_knowledge_read`는 자산 ID와 판본 ID 필요).

## 4. 검증 (ysna)
- 팝업에 승인된 프로젝트·업무 패키지만 표시, 다중 선택 후 패널 반영, 새로고침 후 유지.
- 새 업무 패키지가 사람의 등록 없이 팝업에 나타남.
- 선택한 업무 패키지로 질문했을 때 승인된 근거로만 답변하고 인용 표시.
- 미승인 지식과 선택하지 않은 업무 패키지의 지식이 답변에 쓰이지 않음.
- 서버 연결 실패, 토큰 발급 실패 시 오류 표시.

## 5. 결정

| # | 질문 | 상태 |
| --- | --- | --- |
| D1 | 목록 기능 요청 전달 | **완료.** Daon2-RAG 회신 수신, Daon2 회신 대기 |
| D2 | 서비스 계정 하나로 호출해도 되는가 | **결정.** `spn:daon-user` 사용(R6) |
| D3 | 선택 저장에 DB 추가(마이그레이션 0081)가 필요한지 | **승인(2026-11-09).** `auth_kind` 토큰 발급 방식, `notebook_knowledge_scopes` |
| D4 | WO-K1 경로(`knowledge-packages` 가져오기)를 유지할지 | 미결정 |
| D5 | ysna 배포는 매번 후보 commit·영향·검증·rollback을 제시하고 승인 | 유지 |
| D6 | 새 업무 패키지 접근 등록 | **결정.** 자동으로 가져오기 |
| D7 | 팝업 표시 범위 | **결정.** 승인·게시된 것만 |
