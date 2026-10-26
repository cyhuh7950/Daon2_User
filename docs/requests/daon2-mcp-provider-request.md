# Daon2-RAG·Daon2 MCP 제공 요청 설계서

| 항목 | 내용 |
| --- | --- |
| 문서 구분 | 제품 간 기능 요청 설계 (Daon2-User → Daon2-RAG, Daon2) |
| 문서 버전 | 0.1 초안 (2026-10-20) |
| 요청자 | Daon2-User (신산님 지시: "MCP 표준 준수 연결, 추가 기능은 Daon2-RAG·Daon2에 요청") |
| 수신 | Daon2-RAG 담당, Daon2 담당 |
| 상태 | 초안. 아직 전달·승인되지 않음. 수용 여부는 §9 상태 표에서 관리 |
| 기준 설계서 | `docs/daon2-user-studio-design.md` §7A (지식 연결과 생성형 작성), §7A.10 (가상 MCP) |
| 확인한 수신측 자료 | `~/deploy/daon2-rag/docs/design/Daon2_Rag_Design.md` §5.10, `engines/daon_runtime/app/mcp_*.py`, `~/deploy/daon2/docs/05_decisions/DECISIONS.md`, `docs/WORK_PLAN_GRAPHRAG_20261012.md`, `docs/WORK_PLAN_RAG_CONNECTION_20261014.md` |

> 이 문서는 **요청**이다. 수신 제품의 구현 범위·일정·승인 절차는 각 제품의 정본과 승인 체계를 따르며, Daon2-User는 수신측 코드를 수정하지 않는다. 요청이 수용되지 않거나 지연되어도 Daon2-User는 가상 MCP 서버(§7A.10)로 개발을 계속한다.

---

## 1. 배경: Daon2-User가 하려는 일

Daon2-User는 Daon2·Daon2-RAG가 만든 지식 자산(RAG, GraphRAG, 온톨로지)을 근거로 **사용자 요구에 맞는 새 업무 문서를 작성**한다. 이를 위해 지식을 **MCP 표준**으로 제공받아야 한다.

| ID | 시나리오 | 필요한 지식 |
| --- | --- | --- |
| AU-S2 (첫 템플릿) | 기존 제안서와 새 RFP를 기반으로 제안서 초안 | 기존 제안서의 **구조(목차·절)와 본문**, 유사 사례 검색, 용어·개념 온톨로지, 점검 규칙 |
| AU-S1 | 기존 보험 약관을 기반으로 새 약관 초안 | 약관 **조항 단위** 본문·구조, 조항 유형 온톨로지, 필수 조항 RuleSet |
| AU-S3 | 기존 계약서와 법령 MCP 기반 새 계약서 | 계약서 조항 구조, 조항 유형, 계약서 RuleSet (법령은 별도 법령 MCP) |

Daon2-User의 작성 흐름은 (1) 사용자에게 부족 정보를 질문하고 (2) 필요한 지식을 MCP로 수집하며 (3) 초안을 쓰고 근거를 연결하고 (4) 규칙으로 점검한다(설계서 §7A.5). 이 흐름은 지식을 **검색**하는 것뿐 아니라 **문서 구조 단위로 읽고**, **개념·규칙을 조회**하는 기능을 요구한다.

---

## 2. 현재 사실 (수신측 확인 결과)

### 2.1 Daon2-RAG

| 항목 | 내용 | 출처 |
| --- | --- | --- |
| 역할 | 문서 근거 RAG. MCP는 **문서 RAG의 읽기 전용 제공 채널**. 전문가 RuleSet·온톨로지는 Daon2, 최종 답변·자료 작성은 Daon-user | 설계 §5.10 |
| 설계된 MCP | 엔드포인트 `POST /mcp`(기존 `daon2-rag-api` 라우트), 도구 `search_document_evidence`(필수 `project_id`·`work_package_id`·`question`, 선택 `document_id`·`limit` 1~20), `get_document_evidence`, 리소스 `daon2-rag://documents/{document_id}/versions/{version_id}/runs/{run_id}/blocks/{block_id}` | 설계 §5.10 |
| 기준 프로토콜 | MCP 2026-07-28 (`server/discover`, 세션 없음, Streamable HTTP 요청별 JSON-RPC) | 설계 §5.10 |
| 보안 | 서비스 신원, 전용 MCP audience, 최소 읽기 scope, 프로젝트·업무 패키지 허용 쌍, 요청별 검증, 기본 OFF(`DAON_DOCUMENT_MCP_ENABLED=false`) | 설계 §5.10 |
| 상태 | 소스 개발 상태로 보존, 실제 서비스 토큰·HTTPS·8660 표준 클라이언트·999쪽 원문 대조는 **사용자 인수테스트에서 수행(미수행)** | 설계 §5.10 (2026-10-04 수행 시점 변경) |
| 별도 구현 | `engines/daon_runtime/app/mcp_jsonrpc.py` — 프로토콜 `2025-06-18`, 도구 `rag.search`·`rag.get_evidence`·`rag.get_context`·`rag.explain_lineage`(snapshot 기반) | 소스 |
| 비용 통제 | S10 계량 읽기 v2 제안(OFF 한정 로컬 코드 착수 승인, 실제 활성화 미승인) | `RAG_CONSUMER_COST_CONTROL_PROPOSAL_20261017.md` |

### 2.2 Daon2

| 항목 | 내용 | 출처 |
| --- | --- | --- |
| MCP 위치 | Daon2가 **외부 도구를 호출**하는 실행 수단(`analysis_tool_gateway`). 범용 MCP/tool gateway는 Daon3 범위 | 결정 2026-06-28, 계획 |
| 온톨로지 | PostgreSQL 그래프 저장·조회·outbox worker, 관리자 그래프 탐색 화면 | GraphRAG 계획 2026-10-12 |
| GraphRAG | Daon2의 기능. BYOG/빌드/질의 adapter와 독립 시험은 있으나 제품 요청 경로 호출·지속 projection·실제 엔진 Gate는 **미확인**. 구현 미착수 계획 | GraphRAG 계획 |
| RAG 연결 | 기존 `OntologyRagClient`·consumer 계약 V1(REST 계열) 재사용, 원천 scope와 소비 scope의 불변 매핑 | RAG_CONNECTION 계획 |
| 상태 | **Daon2는 현재 MCP 서버가 아니다.** | |

---

## 3. 요청 원칙

1. **MCP 표준 준수**: 공식 MCP 사양의 전송·수명주기·`tools`·`resources`·`prompts`를 따른다. 별도 프로토콜을 만들지 않는다.
2. **읽기 전용**: 이번 요청의 모든 기능은 읽기·평가이며 지식 쓰기·등록을 요구하지 않는다.
3. **기존 계약 우선**: Daon2-RAG 설계 §5.10에 이미 있는 도구·리소스·보안 규칙을 그대로 쓴다. 없는 것만 추가 요청한다.
4. **근거 보존**: 모든 결과는 출처 ID·버전·계보를 포함하며 Daon2-User는 이를 근거 참조로 저장한다.
5. **각자의 정본 존중**: 수신 제품은 자신의 정본 문서·승인 절차에 따라 수용 여부와 형태를 결정한다. Daon2-User의 가상 계약(Contract v0)은 제안이며 수신측이 수정하면 Daon2-User가 맞춘다.
6. **점진 전환**: 수용되는 항목부터 순차 전환한다(§8).

---

## 4. Daon2-RAG 요청 항목

우선순위: **P0** 필수(첫 템플릿 AU-S2 동작), **P1** 필요(품질·운영), **P2** 개선.

| ID | 우선 | 요청 | 상세 | 수용 기준 |
| --- | --- | --- | --- | --- |
| R-RAG-01 | P0 | **문서 RAG MCP 가동** | 설계 §5.10의 `search_document_evidence`, `get_document_evidence`, resource 템플릿을 WSL-server 환경에서 가동하고(기본 OFF 해제 절차 포함) Daon2-User 서비스 신원을 허용 | 표준 MCP 클라이언트로 발견→목록→검색→재조회→scope 거부 시험 통과, 결과 ID·버전·쪽이 기존 뷰어와 일치 |
| R-RAG-02 | P0 | `list_knowledge_scopes` | 호출자(서비스 + 위임 사용자 컨텍스트)가 읽을 수 있는 `project_id`·`work_package_id`와 이름·설명·문서 수·마지막 갱신 시각 목록 | 허용 밖 scope 비노출, 페이지네이션, 빈 목록과 오류 구분 |
| R-RAG-03 | P0 | `list_documents` | scope 안 문서 목록: `document_id`, 제목, **문서 유형**(제안서·약관·계약서·RFP 등), 현재 버전 ID, 완료 run, 쪽수, 갱신 시각, 메타데이터. 유형·날짜·키워드 필터와 cursor 페이지네이션 | 삭제·휴지통·미완료 문서 제외, 필터 시험, 상한 준수 |
| R-RAG-04 | P0 | `get_document_outline` | 문서의 **구조**(장·절·조항·표 목록)를 계층으로 반환하고 각 노드에 `block_id`·쪽 범위를 연결. 구조 신뢰도(자동 추출 여부) 표시 | 같은 문서의 outline 노드가 `get_document_evidence`로 재조회되는 블록과 일치, 구조 미추출 문서는 명시적 `OUTLINE_UNAVAILABLE` |
| R-RAG-05 | P0 | `read_document_section` | outline 노드 단위로 본문과 포함 블록 목록을 반환(상한 있음, 길면 cursor). 원문 훼손 없이 순서 유지 | 블록 순서·쪽·텍스트가 resource 읽기와 일치, 크기 상한 초과 시 분할 응답 |
| R-RAG-06 | P1 | 검색 확장 | `search_document_evidence`에 `document_type`, `document_ids[]`, 날짜, 메타데이터 필터와 `cursor` 추가. 점수 의미(`score_kind`)와 모델 불일치 사유를 구조화 필드로 반환 | 기존 필수 입력·상한(1~20) 호환 유지, 필터 조합 시험 |
| R-RAG-07 | P1 | **지식 변경 감지** | `resources/subscribe`와 `notifications/resources/updated`, 또는 `get_document_version_status`(문서 ID 목록 → 현재 버전·삭제 여부). Daon2-User는 산출물의 stale 판정에 사용 | 문서 교체·삭제 후 구독/조회로 변경이 확인됨 |
| R-RAG-08 | P0 | **서비스 신원 발급·등록** | Daon2-User 서비스 주체 발급, 전용 audience, 읽기 scope, 허용 project·work package 쌍 등록 절차와 개발·QA용 설정 값 전달(비밀은 별도 안전 경로) | 허용 쌍 안 호출 성공, 쌍 밖 403, 토큰·질문·본문 로그 미기록 |
| R-RAG-09 | P1 | **호출 계량·비용 정보** | 응답 메타(`_meta`)에 처리 시간·사용 임베딩 토큰·결과 수 등 계량 정보를 선택 제공(S10 계량 읽기 v2와 정렬) | 한도 초과 시 구조화 오류, 계량 필드 스키마 문서화 |
| R-RAG-10 | P1 | **프로토콜 판본 정합** | 설계 §5.10(2026-07-28)과 런타임 어댑터(2025-06-18)가 다르다. Daon2-User가 소비할 대상 엔드포인트와 판본을 확정해 알려 줄 것 | 판본·엔드포인트·전송 방식을 요청 회신서에 명시 |
| R-RAG-11 | P2 | `get_related_evidence` | 근거 블록 기준 유사·인접 블록(같은 절 이전·다음, 참조 관계) 조회 | 인접 블록이 outline 순서와 일치 |
| R-RAG-12 | P2 | 표·이미지 블록 | 표는 구조화(행·열)로, 이미지는 설명·위치로 제공 | 표 셀 좌표와 텍스트 검증 |

### 4.1 입출력 초안 (Daon2-RAG)

```json
// get_document_outline
{ "name": "get_document_outline",
  "arguments": { "project_id": "…", "work_package_id": "…", "document_id": "…", "version_id": "…(선택)", "max_depth": 4 } }
// → 결과
{ "document_id": "…", "version_id": "…", "run_id": "…", "structure_source": "extracted|manual|none",
  "nodes": [ { "node_id": "n1", "kind": "chapter|section|clause|table", "title": "제3장 보장내용",
               "level": 1, "page_from": 12, "page_to": 30, "block_ids": ["b101","b102"], "children": [ … ] } ] }

// read_document_section
{ "name": "read_document_section",
  "arguments": { "project_id": "…", "work_package_id": "…", "document_id": "…", "node_id": "n1", "cursor": null } }
// → 결과
{ "node_id": "n1", "blocks": [ { "block_id": "b101", "page": 12, "text": "…", "resource_uri": "daon2-rag://documents/…/blocks/b101" } ],
  "next_cursor": null }
```

---

## 5. Daon2 요청 항목

Daon2는 현재 MCP 서버가 아니며, 범용 MCP gateway는 Daon3 범위로 명시되어 있다. 따라서 이 절은 **Daon2의 로드맵·범위 결정이 필요한 신규 요청**이다.

| ID | 우선 | 요청 | 상세 | 수용 기준 |
| --- | --- | --- | --- | --- |
| R-D2-01 | P0 | **Daon2 지식 MCP 서버 제공 여부 결정** | 온톨로지·RuleSet·승인 지식을 읽기 전용 MCP로 제공하는 서버를 만들지(또는 Daon3로 이관) 결정하고 일정·형태를 회신 | 결정 회신서 |
| R-D2-02 | P0 | `ontology_search_concepts` / `ontology_get_concept` | 질의어로 개념(클래스·조항 유형·업무 용어)을 검색하고 개념 상세(정의·상위/하위·동의어·관계·근거 문서)를 반환 | 결과에 개념 ID·버전·근거 참조 포함, 권한 scope 적용 |
| R-D2-03 | P0 | `ontology_traverse` | 시작 개념에서 관계 유형·깊이(상한 N)로 탐색해 노드·엣지 반환 | 깊이·결과 수 상한, 순환 처리 |
| R-D2-04 | P0 | `ruleset_list` / `ruleset_get` / `ruleset_evaluate` | 업무 유형별 RuleSet 조회와, Daon2-User가 만든 초안 구조(섹션·조항 목록)를 입력으로 한 **평가 결과**(충족/미충족/확인 필요, 규칙 ID, 근거) | 평가 결과가 Daon2 관리자 화면의 규칙 정의와 일치, 입력 크기 상한 |
| R-D2-05 | P1 | `graphrag_query` | `mode`: `local`(엔티티 중심) / `global`(커뮤니티 요약)로 질의. 결과는 엔티티·관계·요약·근거(문서·블록 ID, Daon2-RAG 참조 가능) | GraphRAG 제품 경로 동작이 전제(GraphRAG 계획의 Gate 통과 후), 근거 ID로 R-RAG `get_document_evidence` 재조회 가능 |
| R-D2-06 | P1 | `approved_knowledge_search` / `approved_knowledge_read` | 전문가 승인 지식 검색·본문(기존 daon-user 설계 §19.2 계약) | 승인 상태·버전·만료 포함 |
| R-D2-07 | P1 | `prompts`: `authoring_template` | 작성 템플릿(문서 유형별 필수 입력 질문, 섹션 구성, 지식 수집 계획, 점검 규칙)을 `prompts/list`·`prompts/get`으로 제공. 전문가가 템플릿을 관리 | 템플릿 스키마(§5.1) 준수, 버전 관리 |
| R-D2-08 | P1 | **서비스 신원·권한** | Daon2-User 호출자 인증, 사용자·조직 범위 전달 방식(위임 토큰 또는 서비스 계정 + 범위 필터) | R-RAG-08과 같은 기준 |
| R-D2-09 | P2 | RAG 소비 scope 해석 | Daon2의 소비 scope ↔ Daon2-RAG 원천 scope 매핑을 `list_knowledge_scopes` 응답에서 일관되게 노출 | 매핑 ID가 양쪽에서 대응 |
| R-D2-10 | P2 | 장기 실행 평가 | `ruleset_evaluate`가 길어질 때 비동기 작업(task) 지원 | 진행·취소·결과 조회 |

### 5.1 작성 템플릿 스키마 초안 (Daon2 `authoring_template`)

```yaml
template_id: rfp_response_proposal
title: RFP 대응 제안서 초안
version: 1
inputs:
  - { key: rfp_document,        question: "대상 RFP 문서를 선택해 주세요.",            kind: source_ref,    required: true }
  - { key: reference_proposals, question: "참고할 기존 제안서를 선택해 주세요.",        kind: knowledge_ref, required: true }
  - { key: proposer_profile,    question: "제안 주체의 강점·실적·인력을 알려 주세요.",   kind: text,          required: false }
  - { key: price_schedule,      question: "가격(예산)과 일정, 투입 인력을 알려 주세요.", kind: structured,    required: false }
knowledge:
  - { tool: list_documents, args: { document_type: proposal } }
  - { tool: get_document_outline }
  - { tool: search_document_evidence }
  - { tool: ontology_search_concepts }
sections: [사업 이해, 요구사항 대응, 수행 방안, 일정·조직, 가격, 부록(요구사항 대응표)]
checks:
  - { derived: rfp_requirement_coverage }
  - { ruleset: proposal_required_sections }
output: { type: document_draft, formats: [docx, pptx] }   # 사용자가 생성 시 선택
```

(템플릿의 최종 형식은 Daon2가 정한다. Daon2-User는 이 스키마를 가정하고 가상 서버에서 시험한다.)

---

## 6. 공통 요구 (양 제품)

### 6.1 표준과 판본

| 항목 | 요구 |
| --- | --- |
| 프로토콜 | 공식 MCP 사양. Daon2-RAG 설계의 2026-07-28 기준과 일치시키거나 지원 판본을 명시 |
| 전송 | HTTPS(운영), 개발·테스트는 사내 네트워크 내 평문 허용 여부 명시. Streamable HTTP 요청별 JSON-RPC |
| 발견 | 서버 정보·판본·capability·도구/리소스/프롬프트 목록 조회 가능 |
| 스키마 | 모든 도구에 `inputSchema`·`outputSchema`(JSON Schema) 제공, 변경 시 버전 표기 |

### 6.2 인증·권한

- 서비스 신원(Bearer)과 **전용 audience** 검증, 최소 읽기 scope, 허용 scope 쌍 검증(요청별).
- 사용자 단위 권한이 필요한 경우의 전달 방식(위임 토큰 vs 서비스 계정 + 범위 필터)을 수신측이 정해 회신한다.
- 허용 밖 요청은 403, 타 scope 자원은 **존재 비노출**(미존재 오류).
- 토큰·질문 원문·문서 본문은 URL·운영 로그·감사 이벤트에 남기지 않는다.

### 6.3 결과 계약

| 항목 | 요구 |
| --- | --- |
| 근거 식별 | 문서 ID·버전 ID·run ID·블록 ID·쪽, 개념 ID·버전 |
| 계보 | 원천(문서/온톨로지)→표현(블록/노드) 연결 |
| 현재성 | 삭제·교체·미완료 자원은 기본 제외, 호출 시점에 재검사 |
| 상한 | 응답 크기·결과 수·깊이·페이지 상한, 초과 시 cursor |
| 결정성 | 같은 입력·같은 지식 버전에서 같은 결과(점수 동률 시 정렬 규칙 명시) |

### 6.4 오류 코드 (요청)

수신측이 다른 코드를 쓰면 매핑표를 제공한다.

| 코드 | 의미 |
| --- | --- |
| `SCOPE_FORBIDDEN` | 허용 scope 밖 |
| `NOT_FOUND` | 존재하지 않거나 현재 아님(타 scope 포함, 존재 비노출) |
| `NOT_READY` | 처리 미완료 |
| `EMPTY_RESULT` | 정상이나 결과 없음 |
| `MODEL_MISMATCH` | 임베딩 모델 불일치 |
| `OUTLINE_UNAVAILABLE` | 구조 미추출 |
| `LIMIT_EXCEEDED` | 호출·크기 한도 초과 |
| `UPSTREAM_UNAVAILABLE` | 하위 시스템 오류, 재시도 가능 여부 포함 |

### 6.5 성능·가용성 (제안, 수신측 협의)

| 항목 | 제안 |
| --- | --- |
| `search_document_evidence` | p95 5초 이내 (수신측 설계의 시간 제한과 정렬) |
| `get_document_outline` / `read_document_section` | p95 3초 이내 |
| `ruleset_evaluate` | 동기 30초 이내, 초과 시 비동기(R-D2-10) |
| 동시 호출 | Daon2-User 측 사용자당 3건 이내, 서비스 합계 한도 협의 |
| 가용성 | 테스트 환경: 업무시간 중 가동, 비가동 시 `UPSTREAM_UNAVAILABLE`로 안전 실패 |

---

## 7. Daon2-User가 제공하는 것

| 제공물 | 설명 |
| --- | --- |
| **Contract v0** | 도구·리소스·프롬프트의 JSON Schema와 예제 (`services/mcp-virtual/contracts/`) |
| **가상 MCP 서버** | Contract v0를 구현한 합성 데이터 서버. 수신측이 클라이언트 동작을 미리 볼 수 있음 |
| **계약 시험 모음** | `packages/mcp-contract-tests` — 실제/가상 서버 공통 시험. 수신측이 자체 서버 검증에 사용 가능 |
| **소비 패턴 설명** | 작성 흐름에서 각 도구를 호출하는 순서와 빈도(§7A.5), 부하 예측 |
| **합성 샘플** | 약관·제안서·RFP·계약서 합성 문서 (실제 문서 아님) |

---

## 8. 전환 일정 제안

| 단계 | 내용 | Daon2-User | 수신측 |
| --- | --- | --- | --- |
| T0 | 요청서 전달·검토 | 가상 서버로 개발 | 요청 검토, 판본·방식 회신(R-RAG-10, R-D2-01) |
| T1 | Daon2-RAG 문서 RAG MCP 가동 | 해당 Connector 실제 엔드포인트 전환, 계약 시험 | R-RAG-01, 08 |
| T2 | 구조 읽기 | `get_document_outline`·`read_document_section` 전환 → AU-S2 핵심 | R-RAG-02~05 |
| T3 | Daon2 온톨로지·RuleSet | 점검·용어 기능 전환 | R-D2-01~04, 08 |
| T4 | GraphRAG·템플릿 관리 | GraphRAG 질의, 템플릿 서버 관리 | R-D2-05, 07 |
| T5 | 개선 항목 | | P2 항목 |

수신측 일정이 정해지기 전에도 Daon2-User는 T0 상태(가상 서버)에서 Phase 1·M0·A1을 진행할 수 있다.

---

## 9. 상태 표 (수신측 회신 시 갱신)

| ID | 요청 | 수신 | 우선 | 상태 | 회신·일정 |
| --- | --- | --- | --- | --- | --- |
| R-RAG-01 | 문서 RAG MCP 가동 | Daon2-RAG | P0 | 미전달 | |
| R-RAG-02 | `list_knowledge_scopes` | Daon2-RAG | P0 | 미전달 | |
| R-RAG-03 | `list_documents` | Daon2-RAG | P0 | 미전달 | |
| R-RAG-04 | `get_document_outline` | Daon2-RAG | P0 | 미전달 | |
| R-RAG-05 | `read_document_section` | Daon2-RAG | P0 | 미전달 | |
| R-RAG-06 | 검색 확장 | Daon2-RAG | P1 | 미전달 | |
| R-RAG-07 | 지식 변경 감지 | Daon2-RAG | P1 | 미전달 | |
| R-RAG-08 | 서비스 신원 발급·등록 | Daon2-RAG | P0 | 미전달 | |
| R-RAG-09 | 호출 계량 정보 | Daon2-RAG | P1 | 미전달 | |
| R-RAG-10 | 프로토콜 판본 정합 | Daon2-RAG | P1 | 미전달 | |
| R-RAG-11 | `get_related_evidence` | Daon2-RAG | P2 | 미전달 | |
| R-RAG-12 | 표·이미지 블록 | Daon2-RAG | P2 | 미전달 | |
| R-D2-01 | MCP 서버 제공 여부 결정 | Daon2 | P0 | 미전달 | |
| R-D2-02 | 온톨로지 개념 검색·상세 | Daon2 | P0 | 미전달 | |
| R-D2-03 | 온톨로지 탐색 | Daon2 | P0 | 미전달 | |
| R-D2-04 | RuleSet 조회·평가 | Daon2 | P0 | 미전달 | |
| R-D2-05 | `graphrag_query` | Daon2 | P1 | 미전달 | |
| R-D2-06 | 승인 지식 검색·읽기 | Daon2 | P1 | 미전달 | |
| R-D2-07 | `authoring_template` 프롬프트 | Daon2 | P1 | 미전달 | |
| R-D2-08 | 서비스 신원·권한 | Daon2 | P1 | 미전달 | |
| R-D2-09 | 소비 scope 매핑 노출 | Daon2 | P2 | 미전달 | |
| R-D2-10 | 장기 실행 평가 | Daon2 | P2 | 미전달 | |

상태 값: 미전달 → 전달 → 검토 중 → 수용(일정) / 부분 수용 / 보류 / 거절(대안) → 완료(계약 시험 통과)

---

## 10. 수신측에 묻고 싶은 것

1. Daon2-RAG의 문서 구조(장·절·조항) 정보가 현재 저장되어 있는가? 없다면 outline(R-RAG-04)은 어떤 방식으로 가능한가?
2. Daon2-RAG 런타임 어댑터(`rag.*`)와 문서 RAG MCP(§5.10)는 최종적으로 어떤 관계인가? 하나로 통합되는가?
3. 사용자 권한 전달: 위임 토큰 방식이 가능한가, 서비스 계정 + project/work package 허용 쌍으로 충분한가?
4. Daon2의 온톨로지·RuleSet을 읽기 전용 MCP로 노출하는 것이 Daon3 이전에 가능한 범위인가? 가능하다면 기존 REST consumer 계약(V1)을 MCP로 감싸는 방식인가?
5. RuleSet 평가의 입력 형식(구조화 초안)과 결과 형식에 이미 정의된 계약이 있는가?
6. 테스트용 합성 지식 컬렉션을 Daon2-RAG·Daon2의 QA 환경에 만드는 것이 가능한가? (가상 서버 대신 실제 서버로 시험하기 위함)

---

## 11. 제약과 비요청

- Daon2-RAG·Daon2의 코드·데이터·설정·배포를 Daon2-User가 변경하지 않는다.
- 쓰기 기능(지식 등록·갱신·삭제)을 요청하지 않는다. 작성 결과의 지식 재등록은 별도 후속 논의다(설계서 §7A.6, Phase 5).
- 최종 답변·문서 작성은 Daon2-User 책임이며 수신측에 요청하지 않는다.
- 외부 인터넷·유료 Provider 호출 요구는 포함하지 않는다.
- 이 요청은 구현·배포·환경 변경에 대한 승인이 아니다. 각 제품의 승인 절차를 따른다.
