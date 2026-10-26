# WO-M0. MCP 클라이언트와 가상 MCP 서버 (Phase M0)

| 항목 | 내용 |
| --- | --- |
| 대상 계획 항목 | F4-01 ~ F4-13, S5-01 ~ S5-04, F0-17(요청 전달) |
| 기준 | 설계서 §7A.3, §7A.10 / 요청 설계서 `docs/requests/daon2-mcp-provider-request.md` |
| 조사 근거 | **일반 MCP 클라이언트는 없다.** 있는 것은 국가법령 MCP 하나(`open_law_mcp_server.py` stdio 서버 + `open_law_mcp_client.py`, 프로토콜 `2025-11-25`, 호출마다 자식 프로세스, 최대 8프레임, 동시 2개 제한). `mcp_connector.py`의 `ConnectorRegistry`(kinds `mcp`, `daon_approved_knowledge`)와 `connector_postgres.py`는 실제로 존재하고, `approved_knowledge_connector.py`·`ruleset_connector.py`는 메모리 스텁이다. |
| 환경 | 서버 Python 3.14.3 고정, 새 서비스는 `repo-boundaries.json` 등록 필요, `independence-policy.json`은 승인 Connector 경로 기준 |

경로 약어: `API` = `services/api/src/daon2_user_api`, `MCP` = `services/mcp-virtual`.

---

## 0. 설계 결정

| # | 결정 | 이유 |
| --- | --- | --- |
| M1 | **MCP 클라이언트는 `services/api` 안에 둔다**(`API/mcp_client/…`). 별도 서비스로 분리하지 않는다. | 권한·egress·감사 문맥(`CloudAccessContext`)이 API 안에 있다. 독립성 게이트는 승인 Connector 경로(`services/api/src/connectors/…`)를 요구하므로 **Connector 어댑터는 `API/connectors/` 하위에 둔다**(T-M0-12에서 `independence-policy.json`의 `approved_connector_prefix` 값 수정). |
| M2 | **전송은 Streamable HTTP(단순 JSON-RPC POST) 우선.** 원격 서버(Daon2-RAG, 가상 서버)는 HTTP, 법령은 기존 stdio 유지. | Daon2-RAG의 현재 구현이 `POST /mcp` JSON-RPC이다(조사 요청서 §2.1). |
| M3 | **판본 어댑터 계층**을 둔다: `server/discover`(2026-07-28, 세션 없음) / `initialize`(2025-06-18, 2025-11-25). 서버가 알리는 판본으로 협상, 범위 밖이면 `MCP_VERSION_UNSUPPORTED`. | 설계서 §7A.3.1. |
| M4 | **가상 서버는 별도 컨테이너(`mcp-virtual`)**, 표준 MCP Python SDK(`mcp`)를 사용한다. 클라이언트(API 이미지)는 SDK를 쓰지 않고 직접 구현(의존성 최소화, 판본 어댑터 제어). | API 이미지에 의존성을 늘리지 않는다. 서버 쪽은 SDK로 표준 준수를 보장. SDK 버전은 Python 3.14에서 설치 확인 후 고정(스파이크 T-M0-01). |
| M5 | **응답은 신뢰할 수 없는 데이터**다. 도구 결과 안의 지시문은 실행하지 않고, 호출은 템플릿/계획에 선언된 도구만 허용. | 설계서 §7A.3.3, §7A.8. |
| M6 | **가상 서버 인증은 실제와 같은 형태**(Bearer + audience + 허용 쌍)로 흉내 낸다. 시험 키는 환경 변수 파일 시크릿으로만 주입. | 클라이언트 인증 경로를 미리 시험. |

---

## 1. 작업 목록

### T-M0-01. 스파이크: MCP SDK 가용성과 판본 확인

- **내용**: (1) WSL 서버에서 `uv run --isolated --with mcp python -c "import mcp"`로 Python 3.14.3 설치 가능 여부와 최신 안정 버전 확인, (2) 공식 MCP 사양 최신 판본 확인(기준 2026-07-28, Daon2-RAG 설계서 §5.10) 후 `docs/design/mcp-spec-notes.md`에 `initialize` 대 `server/discover` 차이·`tools/list`·`tools/call`·`resources/read`·`prompts/get` 메시지 형식 요약, (3) 가상 서버가 SDK로 두 판본을 모두 제공할 수 있는지 확인.
- **산출**: 결정 기록(SDK 사용 가부, 사용 불가 시 `fastapi`로 JSON-RPC를 직접 구현하는 대안).
- **완료 기준**: 위 문서와 SDK 버전 핀 결정.

### T-M0-02. Contract v0 정의 (`MCP/contracts/`)

- **파일**
  - `MCP/contracts/daon2_rag.v0.json` — 도구 `search_document_evidence`, `get_document_evidence`, `list_knowledge_scopes`, `list_documents`, `get_document_outline`, `read_document_section`; 리소스 템플릿 `daon2-rag://documents/{document_id}/versions/{version_id}/runs/{run_id}/blocks/{block_id}`.
  - `MCP/contracts/daon2.v0.json` — 도구 `ontology_search_concepts`, `ontology_get_concept`, `ontology_traverse`, `graphrag_query`, `ruleset_list`, `ruleset_get`, `ruleset_evaluate`, `approved_knowledge_search`, `approved_knowledge_read`; 프롬프트 `authoring_template`.
  - `MCP/contracts/errors.json` — 코드 8종(요청 설계서 §6.4).
  - `MCP/contracts/examples/*.json` — 각 도구의 요청/응답 예.
- 각 도구는 `inputSchema`, `outputSchema`(JSON Schema 2020-12). **기존 도구(`search_document_evidence`, `get_document_evidence`)의 입력은 Daon2-RAG 설계서 §5.10 그대로**(필수 `project_id`, `work_package_id`, `question`; 선택 `document_id`, `limit` 1~20).
- **입출력 핵심 형식**
  - `search_document_evidence` 결과: `{results:[{document_id, version_id, run_id, block_id, page, excerpt, score, score_kind, resource_uri}], model_mismatch?: bool}`.
  - `get_document_outline`: 요청 설계서 §4.1의 `nodes` 트리(노드 `node_id, kind, title, level, page_from, page_to, block_ids, children`).
  - `read_document_section`: `{node_id, blocks:[{block_id, page, text, resource_uri}], next_cursor}`.
  - `ruleset_evaluate`: 입력 `{ruleset_id, draft:{sections:[{id,title,text}]}}`, 출력 `{results:[{rule_id, status:'pass'|'fail'|'needs_review', section_id?, evidence_refs[], message}]}`.
- **검증 스크립트** `MCP/contracts/validate.py`: 모든 예제를 스키마로 검증(`jsonschema`는 개발 의존성만).
- **완료 기준**: 검증 스크립트 통과, `docs/requests/daon2-mcp-provider-request.md`의 §4.1·§5.1 예시와 동일 형식임을 리뷰.

### T-M0-03. 합성 코퍼스 `MCP/fixtures/` (F4-07)

- **내용(실제 문서 금지, 전부 합성)**
  - `insurance_terms/`: 약관 3종(실손, 종신, 자동차) — 장·조·항 구조(Markdown), 조항 유형 태그.
  - `proposals/`: 기존 제안서 3건(목차·섹션·표 포함), 서로 다른 발주처·주제.
  - `rfps/`: RFP 2건(요구사항 번호 REQ-001… 포함, 평가기준표).
  - `contracts/`: 계약서 3종(용역·공급·라이선스).
  - `law/`: 합성 법령 조문 20개(실제 법령 인용 금지, "가상 보험업법 제N조" 형태).
  - `ontology.json`: 개념 60개(클래스·속성·관계·동의어), `rulesets/*.json`: 제안서 필수 섹션·약관 필수 조항·계약서 필수 조항 규칙(각 10~15개).
  - `collections.json`: `project_id`·`work_package_id` 쌍 3개(허용/비허용 테스트용).
- **형식**: 문서는 `{document_id, title, document_type, versions:[{version_id, run_id, blocks:[{block_id, page, text}], outline:[…]}]}` JSON. 생성 스크립트 `MCP/fixtures/build.py`가 Markdown 원본에서 블록·개요를 만든다(결정성: 시드 고정).
- **완료 기준**: 빌드 결과가 스키마 검증 통과, 문서 수·조항 수가 위 목록과 일치.

### T-M0-04. 가상 서버 `MCP/daon2_rag_virtual/`, `MCP/daon2_virtual/`

- **서버 두 개**(포트 8641/8642, 컨테이너 내부)를 하나의 이미지에서 모듈별로 실행. SDK의 `FastMCP`(또는 T-M0-01 결정)로 도구 등록, `POST /mcp` 라우트 제공.
- **동작 규칙**
  - 결과는 **결정적**(점수·정렬 고정: 점수 내림차순, 동률은 `block_id` 오름차순).
  - 검색은 간단한 토큰 겹침 점수(한글 2-gram), `limit` 상한 20.
  - `project_id`·`work_package_id`가 허용 쌍에 없으면 HTTP 403. 타 scope 블록 조회는 존재 비노출 `NOT_FOUND`.
  - 인증: `Authorization: Bearer <token>`의 `aud`가 서버별 기대값이 아니면 401, scope 부족 403. 토큰은 HS256 JWT(시험용 키, 파일 시크릿 `MCP_VIRTUAL_JWT_KEY_FILE`).
  - 판본: `MCP_VIRTUAL_PROTOCOL=2026-07-28|2025-06-18`로 선택.
  - 크기 상한: 응답 1 MiB, 블록 텍스트 8,000자.
- **결함 주입**: 요청 헤더 `X-Virtual-Fault: delay=3000 | timeout | empty | forbidden | model_mismatch | not_ready | invalid_schema | version_changed`(시험 모드에서만, 환경변수 `MCP_VIRTUAL_FAULTS=true`).
- **관리 엔드포인트**: `POST /_admin/bump-version`(문서 버전 갱신 → stale 시험), `POST /_admin/reset`. `MCP_VIRTUAL_ADMIN_TOKEN` 필요.
- **운영 차단**: `ENV=production`이면 서버가 기동 거부(`VIRTUAL_MCP_FORBIDDEN_IN_PRODUCTION`).
- **테스트** `MCP/tests/`(pytest): 각 도구 스키마 준수, 권한, 결함 주입, 결정성.

### T-M0-05. 컨테이너·배포

- `MCP/Dockerfile`(python:3.14-slim, `mcp`·`uvicorn` 핀, 비루트 사용자, 읽기 전용 파일시스템, `cap_drop ALL`), `deploy/daon2-user/compose.mcp-virtual.yaml`(별도 프로젝트 파일, `daon2_user_network` 외부 참조, 포트 미공개, `mem_limit 256m`, `cpus 0.5`). `asr-base`의 compose.asr-base.yaml 패턴을 따른다.
- `repo-boundaries.json`에 `services/mcp-virtual` 등록(kind service, allowed_dependencies [], forbidden = 모든 다른 컴포넌트). `services/asr-base`는 uv 워크스페이스 밖의 독립 프로젝트이므로 같은 방식으로 `MCP/pyproject.toml`을 둔다(`package=false`, 의존성 핀).
- **완료 기준**: WSL에서 `docker compose -p daon2_user_mcp …` 기동, API 컨테이너에서 `http://mcp-daon2-rag:8641/mcp` 호출 성공(문서에 주소·포트 기록). `verify:independence` 통과.

### T-M0-06. MCP 클라이언트 `API/mcp_client/`

```text
API/mcp_client/
  __init__.py
  transport.py      # HttpJsonRpcTransport(post), StdioTransport(기존 open_law 방식 재사용)
  lifecycle.py      # VersionAdapter: DiscoverAdapter(2026-07-28), InitializeAdapter(2025-06-18/2025-11-25)
  client.py         # McpClient: connect(), list_tools(), call_tool(), read_resource(), get_prompt(), list_resources()
  errors.py         # McpError(code, retryable)
  schemas.py        # 응답 스키마 검증(jsonschema 없이 수작업 검증 또는 소형 검증기)
```
- **불변식**: 응답 크기 상한(기본 1 MiB, 도구별 설정), 프레임 상한, 타임아웃(연결 2초·호출 25초 기본, 도구별 재정의), 리다이렉트 금지, 사설 주소 정책은 Connector 설정에 따름(내부 서비스는 허용 목록으로).
- **인증**: `Authorization: Bearer` 토큰은 `provider_credentials`와 같은 방식으로 **암호화 저장**(`ProviderCredentialCipher`, `API/provider_credentials.py`)하고 호출 직전에만 복호화. 로그·감사에 토큰·질문·본문을 남기지 않는다.
- **호출 한도**: Connector별 동시 호출 상한(기본 4), 사용자별 분당 상한(기본 30). 초과 시 `LIMIT_EXCEEDED`.
- **재사용**: `open_law_mcp_client.py`의 프레임 읽기·종료 정리 코드는 `StdioTransport`로 일반화(기존 법령 클라이언트는 호환 래퍼로 유지, 동작 변경 금지).
- **테스트** `TESTS/test_mcp_client.py`: 가짜 전송으로 두 판본 협상, 크기 상한, 타임아웃, 오류 매핑, 토큰 비노출; 실제 가상 서버 통합 테스트는 WSL 전용(`DAON_MCP_VIRTUAL_URL` 환경변수 있을 때만).

### T-M0-07. Connector 관리 (백엔드)

- **저장**: 기존 `connector_postgres.py`(`PostgresConnectorRepository`)를 확장하거나, 마이그레이션이 필요하면 `WO-F1`의 `0074`에 `knowledge_connectors` 테이블 추가(`connector_id, kind, name, endpoint_url, protocol_version, auth_kind, credential_ciphertext, allowed_tools text[], allowed_scopes jsonb, is_virtual bool, status, last_checked_at, error_code, tenant_id` + RLS). **결정**: 기존 레지스트리 스키마가 MCP 도구 허용 목록·판본·가상 표시를 담지 못하면 신규 테이블을 `0074`에 포함(WO-F1 T1-03 갱신 필요 — 이 항목은 WO-F1 완료 전에 결정).
- **서비스** `API/knowledge_connector_service.py`: `register(admin, spec)`, `verify(connector_id)`(`initialize/discover` + `tools/list` + 스키마 대조 + 샘플 호출), `list()`, `set_allowed_tools()`, `disconnect()`, `call(context, connector_id, tool, args)`(권한·egress·한도 확인 → 클라이언트 호출 → 결과 검증 → 감사).
- **라우트**(`runtime.py`): `GET /api/v1/knowledge-connectors`(VIEW), `POST /admin/knowledge-connectors`, `POST /admin/knowledge-connectors/{id}/verify`, `PATCH /admin/knowledge-connectors/{id}`, `DELETE …` — 관리자(`Action.POLICY_MANAGE` 또는 시스템 관리자)만. BFF 경로 추가(WO-F1 T1-10 방식).
- **가상 표시**: `is_virtual=true`이면 API 응답과 UI에 `virtual: true`(배지), `ENV=production`에서는 등록 거부.
- **감사**: 등록·해제·검증·호출(도구 이름·결과 건수만).
- **테스트** `TESTS/test_knowledge_connector_service.py`, `TESTS/test_knowledge_connector_runtime_http.py`.

### T-M0-08. 근거 스냅샷 저장(F4-13)

- MCP 도구 결과를 산출물 근거로 쓸 때 `studio_v2_evidence.external_ref`에 `{connector_id, tool, args_sha256, result: {…}, fetched_at, knowledge_version}`을 **불변 스냅샷**으로 저장하고 `quote_sha256`을 기록한다(`origin='mcp_daon_rag'|'mcp_daon'|'mcp_law'`). 지식 서버의 버전 필드(`version_id`/개념 `version`)를 저장해 stale 판정(WO-F1 T1-13)에서 `get_document_version_status`(요청 R-RAG-07) 또는 재조회로 비교한다.
- **완료 기준**: 가상 서버의 문서 버전을 `bump-version`으로 올린 뒤 해당 산출물이 stale 표시.

### T-M0-09. 관리자 화면 (S5)

- 설정 화면에 "지식 연결" 탭 추가(`apps/web/app/settings/knowledge-connectors/page.jsx` + 컴포넌트 `UI/knowledge-connectors-pane.jsx`): 목록(이름·상태 배지·마지막 확인·가상 배지), 등록 대화상자(이름·URL·인증 토큰·판본·허용 도구 체크·허용 컬렉션), 연결 확인 버튼(진행·결과 표시), 해제 확인. 기존 `settings/model-connections`의 `provider-settings-workspace.jsx` 패턴(관리자 폼·검증)을 따른다.
- **주의**: 이 화면의 URL 입력은 `apps/web` 코드에서 `http://` 리터럴을 쓰지 않는다(보안 스캔 `BROWSER_INTERNAL_ADDRESS` 규칙). 기본값·예시는 서버가 내려주거나 placeholder 없이 둔다.
- **테스트** `T/knowledge-connectors-ui.test.mjs`.

### T-M0-10. 계약 시험 모음 `packages/mcp-contract-tests/` (F4-09)

- **구성**: Node 또는 Python 패키지(결정: **Python pytest 패키지**, 가상·실제 서버를 URL 인자로 대상 지정). 시험 목록은 요청 설계서 §7A.10.4 표(발견·스키마·근거·권한·오류·한도·갱신) 그대로 `required` 와 `pending`(요청 항목 미수용)으로 표시.
- **실행**: `python -m mcp_contract_tests --url … --token-file … --profile virtual|real --json report.json`.
- **완료 기준**: 가상 서버 대상 `required` 100% 통과 보고서를 `docs/04_test_reports/mcp/`에 저장.

### T-M0-11. 운영 차단과 설정

- 환경 변수: `DAON_KNOWLEDGE_CONNECTORS_ENABLED`(strict bool, 기본 false, WO-F1 T1-02와 같은 5곳 수정), `DAON_MCP_ALLOW_PRIVATE_ENDPOINTS`(내부 서비스 허용, 기본 false), `DAON_MCP_CALL_TIMEOUT_SECONDS`.
- `ENV/DAON_RUNTIME_PROFILE == production` 이고 Connector `is_virtual`이면 등록·호출 모두 거부.

### T-M0-12. 독립성 정책 갱신 (F4-12)

- 현재 `independence-policy.json`의 `approved_connector_prefix`는 `services/api/src/connectors/daon`(존재하지 않는 경로). **`services/api/src/daon2_user_api/connectors/` 로 바꾸고**, `scripts/lib/independence-check.mjs`의 `CONNECTOR_PATTERN`(l.16: `daon…-client|sdk|internal|endpoint`)이 Connector 어댑터 코드를 차단하지 않는지 확인한다. 가상 서버 이름(`mcp-daon2-rag`)이 `DAON_PRODUCT_PATTERN`에 걸리면(경로 `…/daon2-rag/…`) 이름을 `knowledge-rag-virtual` 등으로 바꾸거나 정책 예외 대신 패턴을 좁힌다.
- **완료 기준**: `npm run verify:independence` 위반 0건 + `scripts/tests/independence-check.test.mjs` 통과(필요 시 신규 사례 추가).

### T-M0-13. 요청 설계서 전달 (F0-17)

- 전달 전 최종 점검: `docs/requests/daon2-mcp-provider-request.md`의 도구명·스키마가 T-M0-02와 일치하는지, 수신측 담당자가 읽을 수 있는 형식(DOCX/MD)으로 보낼 채널을 사용자에게 확인. 전달 기록과 회신을 같은 문서 §9 상태 표에 갱신한다.
- 이 항목은 **사용자가 전달 수단을 정해야** 진행(Daon2-RAG/Daon2 담당 채널).

---

## 2. 의존 관계·순서

```text
T-M0-01(스파이크) → T-M0-02(계약) → T-M0-03(코퍼스) → T-M0-04(가상 서버) → T-M0-05(배포)
                        ↘ T-M0-06(클라이언트) → T-M0-07(Connector 서비스·라우트) → T-M0-08(스냅샷) → T-M0-09(관리자 화면)
T-M0-10(계약 시험)은 T-M0-04 이후 병행, T-M0-11·12는 T-M0-06 이후
```
- **WO-F1과의 관계**: T-M0-07의 테이블 결정이 `0074` 마이그레이션 범위에 영향을 주므로 WO-F1 T1-03 시작 전에 T-M0-07의 저장 방식 결정만 먼저 한다.

## 3. 종료 기준 (Phase M0)

가상 서버(두 개)가 WSL에서 가동, API가 Connector로 등록·검증·호출, 계약 시험 `required` 100% 통과, 관리자 화면에서 등록·확인·해제, 가상 표시와 운영 차단 동작, 근거 스냅샷 저장과 stale 판정, `verify:independence` 통과.

## 4. 위험과 대응

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| MCP SDK가 Python 3.14에서 설치/동작 불가 | 가상 서버 지연 | T-M0-01 스파이크, 대안(FastAPI 직접 JSON-RPC) |
| 사양 판본 차이(2026-07-28 vs 2025-06-18) | 실서버 전환 시 재작업 | 판본 어댑터와 계약 시험의 판본별 프로파일 |
| 토큰·질문 본문이 로그에 남음 | 정보 유출 | 호출 감사에 인자 해시와 결과 건수만 기록, 로그 필터 테스트 |
| 독립성 게이트가 Connector 코드를 위반으로 판정 | 개발 차단 | T-M0-12를 가상 서버 개발 초기에 처리 |
| 수신측(Daon2-RAG·Daon2) 회신 지연 | M1 지연 | 가상 서버로 개발 계속, 요청 항목별 대체 동작 문서화 |
