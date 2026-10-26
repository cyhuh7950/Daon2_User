# WO-A1. 작성(Authoring) 엔진 (Phase A1~A3)

| 항목 | 내용 |
| --- | --- |
| 대상 계획 항목 | F6-01 ~ F6-14, S4-01 ~ S4-13, S5-05 |
| 선행 | WO-F1(큐·저장소), WO-F2(생성 어댑터·본문 리더·내보내기), WO-M0(MCP 클라이언트·가상 서버) |
| 기준 | 설계서 §7A.1, §7A.5~§7A.9, 부록 D(RFP 첫 템플릿, DOCX/PPTX) |
| 조사 근거 | 기존에 `document_draft.py`(27줄: 섹션·근거·검토 상태 자료구조만), `knowledge_graph.py`(29줄), `conversation-intent.js`(의도 분류 정규식 42줄)가 있으나 **작성 로직·질문 흐름은 없다.** 질문 응답 서비스는 단일 질문→답변이며 다중 턴 세션 개념이 없다. |

경로 약어: `API` = `services/api/src/daon2_user_api`.

---

## 0. 설계 결정

| # | 결정 | 이유 |
| --- | --- | --- |
| A1 | **작성 세션은 새 테이블(`authoring_sessions`, `authoring_session_events`)로 영속화**한다(WO-F1의 `0074`에 포함하거나 `0075`). 세션은 작성 결과 산출물(`studio_v2_outputs`, `type_id='authored_document'`)과 1:1로 연결된다. | 질문 대기·재개가 필요하다. 기존 질문 run은 단발이라 재사용 불가. |
| A2 | **`studio_v2_outputs.type_id`에 `authored_document`를 추가**하고 `settings_json.template_id`로 템플릿을 구분한다(WO-F1 T1-03 CHECK에 추가). | 설계서 §7A.6. 카드·뷰어·내보내기를 요약형과 공유. |
| A3 | **세션 진행은 "상태 기계 + LLM 호출"**이다. LLM은 (a) 부족한 입력 판단, (b) 질문 문장 다듬기, (c) 초안 생성에만 쓰고, **단계 전환은 코드가 결정**한다. | 흐름 예측성·테스트 가능성(FakeTransport로 전 과정 검증). |
| A4 | **템플릿은 YAML이 아니라 JSON 파일**(`API/authoring_templates/*.json`) + 스키마 검증으로 저장한다. 서버가 로드(`TemplateRegistry`)하고, 이후 Daon2의 `authoring_template` 프롬프트(요청 R-D2-07)로 대체 가능하도록 같은 스키마를 쓴다. | 서버 의존성 최소(PyYAML 미도입). |
| A5 | **1차 템플릿은 `rfp_response_proposal`**(필수 입력 2개 + 선택 2개, 요구사항 확인 필수, 출력 DOCX/PPTX 선택). 이후 `insurance_terms_draft`(A2), `contract_draft`(A2). | 설계서 부록 D. |
| A5b | **지식 호출은 가상 MCP 기준**으로 구현하고, 도구 호출은 템플릿 `knowledge` 목록에 선언된 것만 허용한다. | 설계서 §7A.8. |
| A6 | **생성은 섹션 단위 반복**이며 섹션마다 `heartbeat`·취소 확인·근거 라벨 검증을 수행한다(WO-F2 T2-04). 전체 초안 한 번 호출은 금지(출력 토큰·시간 한계). | |

---

## 1. 작업 목록

### T-A1-01. 템플릿 스키마와 로더 `API/authoring_templates.py`

```python
@dataclass(frozen=True, slots=True)
class TemplateInput:
    key: str; question: str
    kind: Literal["text","structured","source_ref","knowledge_ref","choice"]
    required: bool; choices: tuple[str,...] = (); validator: str | None = None   # 예: 'non_empty','money','date_range'
@dataclass(frozen=True, slots=True)
class TemplateSection: key: str; title: str; guidance: str; knowledge_hints: tuple[str,...]
@dataclass(frozen=True, slots=True)
class AuthoringTemplate:
    template_id: str; title: str; version: int
    inputs: tuple[TemplateInput,...]; knowledge: tuple[KnowledgeStep,...]
    sections: tuple[TemplateSection,...]; checks: tuple[CheckSpec,...]
    output: OutputSpec                      # formats, user_selectable
class TemplateRegistry:
    def load_all(self, directory) -> None; def get(template_id) -> AuthoringTemplate; def list() -> list[Mapping]
```
- JSON 스키마 검증(구조·필드 길이·`kind` 허용값·`knowledge[].tool` 이 Contract v0 도구명인지). 잘못된 템플릿은 서버 기동 시 오류.
- **파일**: `API/authoring_templates/rfp_response_proposal.json`(내용은 설계서 §7A.5.1 RFP 예시: 입력 4개(rfp_document, reference_proposals 필수 / proposer_profile, price_schedule 선택), knowledge: `list_documents(document_type=proposal)`, `get_document_outline`, `search_document_evidence`, `ontology_search_concepts`; sections 6개; checks: `rfp_requirement_coverage`(derived), `proposal_required_sections`(ruleset); output docx/pptx).
- **테스트** `TESTS/test_authoring_templates.py`.

### T-A1-02. 저장(마이그레이션 포함)

- 테이블(WO-F1 T1-03과 같은 패턴, 소유자 `daon_app`, RLS):
  - `authoring_sessions`: PK `(tenant_id, workspace_id, session_id)`, `notebook_id`, `output_id`(FK studio_v2_outputs), `template_id`, `template_version`, `owner_actor_id`, `state CHECK (IN ('collecting','awaiting_answer','planning','plan_confirm','generating','checking','completed','failed','cancelled'))`, `inputs_json jsonb`(확정된 입력), `pending_questions_json jsonb`, `assumptions_json jsonb`, `plan_json jsonb`, `requirements_json jsonb`(RFP 요구사항 목록), `step_index int`, `version int`, `created_at`, `updated_at`.
  - `authoring_session_events`(append-only): `event_id`, `session_id`, `seq`, `kind`(question/answer/plan/confirm/step/error), `payload_json`, `created_at`.
- **마이그레이션**: WO-F1 `0074`에 포함(권장, 한 번의 리비전 증가·준비 검사 수정으로 처리). `0074` 범위 확정은 WO-F1 T1-03 착수 전에 이 WO의 테이블 목록과 합친다.

### T-A1-03. 세션 상태 기계 `API/authoring_session.py`

상태·전이(코드로 고정, 위반 시 `AUTHORING_STATE_INVALID` 409):

```text
collecting ──(필수 입력 부족)──> awaiting_answer ──(답변 제출)──> collecting
collecting ──(필수 입력 충족)──> planning ──(계획 생성)──> plan_confirm
plan_confirm ──(사용자 수정)──> plan_confirm | ──(확정)──> generating
generating ──(섹션 반복)──> checking ──> completed
* ──(취소)──> cancelled,   * ──(오류)──> failed
```
- **입력 수집 규칙**(설계서 §7A.5.2): ① `inputs_json`에 값이 있고 검증을 통과한 키는 묻지 않는다. ② 필수 중 비어 있는 키를 **최대 3개씩** 묶어 질문(`pending_questions_json`). ③ 선택 입력은 한 번만 제안하고 "건너뛰기"를 허용하며 건너뛴 항목은 `assumptions_json`에 `{"key","reason":"user_skipped","default":"[작성 필요]"}` 기록. ④ `source_ref`/`knowledge_ref` 입력은 질문 대신 **자료 요청**(`{"request":"select_source"|"select_knowledge","hint":…}`)으로 표현.
- **기본값 추론**: 대화·소스에서 확정 가능한 값은 LLM이 아니라 규칙으로 채운다(예: 노트북에 RFP로 분류된 소스가 하나뿐이면 `rfp_document` 후보로 제안). 모호하면 후보를 선택형으로 제시.
- **중단·재개**: 세션은 서버에 저장, `GET /sessions/{id}`로 현재 질문·단계 복원. 24시간 무활동 시 `expired`로 정리(후속).
- **동시성**: 세션 행에 `version` 낙관적 잠금.
- **테스트** `TESTS/test_authoring_session.py`: FakeRepository로 모든 전이, 질문 묶음(3개 상한), 건너뛰기→가정, 재개, 잘못된 전이.

### T-A1-04. 세션 API (`runtime.py`, 플래그 `DAON_STUDIO_V2_ENABLED`)

경로: `/api/v1/workspaces/{ws}/notebooks/{nb}/authoring/...`

| 메서드·경로 | 요청 | 응답 |
| --- | --- | --- |
| `GET …/authoring/templates` | — | 템플릿 목록(id·제목·입력 요약·출력 형식) |
| `POST …/authoring/sessions` | `{template_id?, request_text?}` (둘 중 하나, `Idempotency-Key`) | 201 `{session_id, output_id, state, pending_questions, requests}`. `request_text`만 있으면 템플릿 분류(규칙: 키워드 매칭 + 후보 제시), 모호하면 `state='awaiting_answer'`로 템플릿 선택 질문 |
| `GET …/authoring/sessions/{sid}` | — | 현재 상태 전체(확정 입력·질문·계획·요구사항·단계) |
| `POST …/sessions/{sid}/answers` | `{answers:[{key, value}|{key, source_version_id}|{key, knowledge_ref}]}` | 갱신 상태 |
| `PUT …/sessions/{sid}/requirements` | `{requirements:[{id,text,mandatory}], expected_version}` | RFP 요구사항 목록 수정(추가·삭제·수정) |
| `POST …/sessions/{sid}/plan/confirm` | `{plan: {sections:[…], assumptions:[…]}, output_formats:["docx","pptx"], expected_version}` | 202, 생성 시작(큐 작업 등록) |
| `POST …/sessions/{sid}/cancel` | — | 202 |

- 라우트 규칙은 WO-F1 T1-09와 동일(권한 EDIT, Idempotency-Key, `extra=forbid`, 오류 코드 화이트리스트: `AUTHORING_STATE_INVALID`(409), `AUTHORING_INPUT_INVALID`(422), `AUTHORING_TEMPLATE_UNKNOWN`(404), `AUTHORING_KNOWLEDGE_UNAVAILABLE`(503), `AUTHORING_PLAN_REQUIRED`(409)).
- BFF·OpenAPI 갱신은 WO-F1 T1-10·11과 같은 절차.

### T-A1-05. 지식 수집 실행기 `API/authoring_knowledge.py`

- 입력: 확정 입력(`inputs_json`), 템플릿 `knowledge` 단계 목록, Connector 서비스(WO-M0).
- 단계 실행: 각 `KnowledgeStep(tool, args_template)`를 입력 값으로 인자 치환(`{{inputs.rfp_document}}` 같은 자리표시자는 **화이트리스트 키만** 허용, 임의 표현식 금지) → `knowledge_connector_service.call(...)`. 결과는 `KnowledgeBundle`로 모으고 라벨(`K1..`)을 부여, **스냅샷 저장**(WO-M0 T-M0-08).
- 사용자 Source(노트북 소스)는 WO-F2 `StudioSourceReader`로 읽는다. RFP 문서는 반드시 소스에서.
- 실패 정책: 필수 단계 실패 → 세션 `failed`(`AUTHORING_KNOWLEDGE_UNAVAILABLE`, 사용자에게 "지식 서버에 연결할 수 없습니다" + 재시도), 선택 단계 실패 → 경고 + 계속.
- 결과 크기 상한 단계별 1 MiB, 총 4 MiB.
- **테스트** `TESTS/test_authoring_knowledge.py`: 가상 서버 응답 픽스처(`FakeConnectorService`), 자리표시자 치환, 실패 정책.

### T-A1-06. RFP 요구사항 추출기 `API/authoring_rfp.py` (F6-06)

- 입력: RFP 문서 본문(`StudioSourceReader` 결과), 출력: `requirements=[{id:"REQ-001", text, mandatory:bool, source_ref:"S3", category}]`.
- **전략**: (1) 구조 기반 1차: 번호가 붙은 항목(`REQ-\d+`, `\d+\.\d+`, "해야 한다/하여야 한다/할 것") 패턴으로 후보 추출(규칙), (2) LLM 보정 호출로 후보를 정리·누락 보완·필수 여부 판정(JSON 스키마: `{requirements:[{text, mandatory, category, refs[]}]}`), (3) 규칙 후보와 LLM 결과를 병합·중복 제거, `refs` 검증(WO-F2 T2-04).
- 평가 지표(수동 평가, F8-06): 합성 RFP 2건의 정답 요구사항 목록 대비 재현율·정밀도 기록. 목표는 첫 평가 후 설정.
- 출력은 세션 `requirements_json`에 저장하고 **사용자 확인 화면에서 수정 가능**(필수 단계, 설계서 §7A.5.1). 확정 전에는 초안 생성 불가(`AUTHORING_PLAN_REQUIRED`).
- **테스트** `TESTS/test_authoring_rfp.py`: 합성 RFP에서 규칙 추출·병합·중복 제거(FakeTransport).

### T-A1-07. 계획 생성 `API/authoring_plan.py`

- 계획(`plan_json`) 구조: `{sections:[{key,title,purpose,knowledge_refs:["K2","S1"],requirement_ids:["REQ-001",…]}], sources:[…], checks:[…], assumptions:[…]}`.
- 생성: 템플릿 `sections` + 요구사항 목록 + 지식 번들로 LLM 1회 호출(섹션별 목적·사용할 근거·대응 요구사항 매핑) → 검증(모든 요구사항이 최소 한 섹션에 배정, 템플릿 필수 섹션 포함).
- 사용자가 계획 확인 화면에서 목차 순서·섹션 추가/삭제·가정 수정 가능(PUT plan은 `plan/confirm` 요청 본문으로 한 번에 확정).

### T-A1-08. 섹션별 초안 생성 `API/authoring_generate.py`

- 섹션 루프: 각 섹션에 대해 (1) 컨텍스트 팩(해당 섹션의 `knowledge_refs`와 `requirement_ids`에 해당하는 구간·요구사항) 구성, (2) 프롬프트(`authoring-<template>-<section>-v1`: 섹션 목적·요구사항·참고 근거·사용자 입력(주체 정보·가격·일정)·맞춤설정), (3) JSON 응답 `{paragraphs:[{text, refs[]}], tables?:[…], open_items:[str]}`, (4) 검증·경고, (5) `progress` 갱신·취소 확인.
- **미입력 처리**: 선택 입력(제안 주체·가격/일정)이 비었으면 해당 위치에 `[작성 필요]`를 삽입하고 `open_items`·가정 목록에 기록(설계서 부록 D).
- **새로 쓴 문장 표시**: 근거 없는 신규 문장은 `refs`가 비어 `origin='new'` 로 표기, UI는 구분 표시(S4-08).
- 결과는 `studio_v2_revisions`(`type_id='authored_document'`)의 `content_json`: `{"schema":"studio.authored.v1","template_id","sections":[…],"requirements":[…],"coverage":[…],"assumptions":[…],"open_items":[…]}`.

### T-A1-09. 요구사항 대응표·점검 `API/authoring_checks.py` (F6-08, F6-13 일부)

- **대응표(derived check `rfp_requirement_coverage`)**: 각 요구사항 → 대응 섹션/문단 → 상태(`covered`/`partial`/`missing`), 근거 refs. 판정은 (1) 계획 매핑, (2) 생성 문단이 요구사항을 언급·충족하는지 LLM 판정 1회(JSON), (3) 누락은 경고.
- **RuleSet 점검**(`proposal_required_sections`): 가상/실제 Daon2의 `ruleset_evaluate` 호출(WO-M0) — 입력은 `draft.sections[{id,title,text}]`. 서버 미연결 시 점검을 `skipped`로 표시하고 이유를 기록.
- **근거 무결성**: WO-F2 T2-04의 `validate_content` 재사용.
- 결과를 `content_json.checks`에 저장, UI 점검 탭(S4-10)이 표시.
- **테스트** `TESTS/test_authoring_checks.py`.

### T-A1-10. 출력(DOCX/PPTX) `API/studio_v2_export.py` 확장 (F6-10)

- **DOCX(제안서)**: 표지(제목·제안사·날짜) → 목차(제목 스타일 기반, 필드 코드 TOC) → 섹션 본문(WO-F2 DOCX 렌더러 재사용) → **부록 A 요구사항 대응표**(표: ID·요구사항·대응 섹션·상태) → 부록 B 근거 목록 → 부록 C 가정·미결 항목(`[작성 필요]` 목록).
- **PPTX(발표용, "별도 구성")**: 슬라이드 계획은 별도 LLM 호출 1회(섹션 결과를 입력으로 "발표 흐름" JSON: 표지·사업 이해·핵심 제안 3~5·수행 방안·일정·조직·가격·Q&A, 각 슬라이드 불릿 ≤ 5·노트)로 만들고 WO-F2 PPTX 렌더러로 출력. 사용자가 생성 시 선택한 형식만 생성(둘 다 선택 시 두 파일을 같은 산출물의 자산으로 저장, 같은 리비전).
- 고정 문구 "AI 작성 초안, 전문가 검토 필요"를 DOCX 표지 하단·PPTX 마지막 슬라이드 노트에 삽입(설계서 §7A.8).

### T-A1-11. 작성 화면 (S4-01 ~ S4-09) — UI

- **진입**: Studio 패널에 "작성" 타일(또는 `+ 문서 작성`) → 템플릿 목록 대화상자 → 선택 시 세션 생성 → **작성 패널**(Studio 영역을 점유하는 단계형 화면, 상단 단계 표시줄: 입력 → 요구사항 확인 → 계획 확인 → 생성 → 결과).
- **요구 확인 화면**(S4-02/03): 질문 카드(최대 3개 묶음), 선택형은 버튼, 텍스트는 입력창+건너뛰기(선택 항목만), 자료 요청은 "소스 선택"(체크된 소스 목록에서) / "기존 제안서 선택"(MCP `list_documents` 결과 목록, 로딩·빈 상태·오류 상태 포함), 진행 표시 "입력 n/m 확정".
- **요구사항 확인**(S4-05): 표(ID·요구사항·필수/선택 토글·삭제·행 추가·인라인 편집), "확정하고 계속" 버튼, 원문 근거 보기.
- **계획 확인**(S4-04): 목차 드래그 정렬(또는 위/아래 버튼), 섹션별 사용 지식·대응 요구사항 표시, 가정 목록 편집, 출력 형식 체크(DOCX/PPTX/둘 다, S4-07).
- **생성 중**(S4-06): 진행률·현재 섹션명·취소, 카드 배지 "작성 중/입력 필요".
- **결과**(S4-08/09/10): 탭 — 본문(`[작성 필요]` 강조, 신규 문장 구분, 근거 번호) / 요구사항 대응표 / 점검 / 가정·미결 항목.
- 컴포넌트는 `UI/authoring-*.jsx`(신규), 모델 `UI/authoring-model.js`, API `WEB/lib/authoring-api.js`, 카탈로그 키 `authoring.*`. WO-S1의 규칙(어댑터 주입, 린트, 경계 토큰 금지)을 따른다.
- **테스트** `T/authoring-*.test.mjs`(모델 순수 함수 + 마운트).

### T-A1-12. 평가(F8-06)

- 합성 RFP 2건 × 기존 제안서 3건으로 AU-S2 시나리오를 실행하고 `docs/04_test_reports/studio_eval/authoring-rfp-eval.md`에 기록: 요구사항 추출 재현율/정밀도, 대응표 정확도, `[작성 필요]` 처리 적정성, 근거 일치, 형식 준수(DOCX/PPTX 열기), 소요 시간. **수동 평가표**로 사람이 채점.
- **완료 기준(Phase A1 종료)**: 위 평가서 1회분 작성, AU-S2 종단 시나리오가 WSL에서 가상 서버로 처음부터 끝까지 동작(질문 → 요구사항 확인 → 계획 확인 → 생성 → 점검 → DOCX/PPTX 내려받기).

### T-A2-xx. 약관·계약서 템플릿 (Phase A2)

- `insurance_terms_draft.json`: 입력(상품 유형, 기준 약관 `knowledge_ref`, 변경점), 지식(`search_document_evidence`, `get_document_outline`, `read_document_section`, `ontology_search_concepts`, `ruleset_get`), 섹션(총칙·보장 내용·지급사유·면책·보험료·계약 해지·분쟁 해결), 점검(ruleset `insurance_terms_required_clauses`). **변경 표시**: 기존 조항과 신규 조항을 문장 단위로 비교(공백·구두점 정규화 후 유사도)해 `unchanged/modified/new/delete_suggested` 태그(`API/authoring_diff.py`).
- `contract_draft.json`: 입력(계약 유형, 기준 계약서, 당사자·기간·금액), 지식(계약서 조항 구조 + 법령 MCP `search_law`/`get_law_text`), 점검(법령 대조표: 조항별 관련 조문·충돌 가능 표시, "법률 자문이 아닌 근거 대조" 문구).
- 법령 MCP는 기존 `OpenLawMcpClient`(qa workspace 한정) 사용 가능성을 확인하고, 아니면 가상 서버 법령 도구(`search_law` 동일 이름)로 개발.

### T-A3-xx. RuleSet 점검 연동·템플릿 관리 (Phase A3)

- 실제 Daon2 `ruleset_evaluate` 연동 전환(WO-M0 M1), 템플릿 관리 UI(관리자 목록·JSON 편집·검증·버전)는 요청 R-D2-07 회신 후 별도 WO로 확정.

---

## 2. 의존 관계·순서

```text
WO-F2(리더·생성 어댑터·렌더러) + WO-M0(클라이언트·가상 서버) 완료 후 착수
T-A1-01(템플릿) → T-A1-02(저장) → T-A1-03(상태 기계) → T-A1-04(API)
                                   ↘ T-A1-05(지식 수집) → T-A1-06(RFP 추출) → T-A1-07(계획) → T-A1-08(생성) → T-A1-09(점검) → T-A1-10(출력)
T-A1-11(UI)은 T-A1-04 계약 후 가짜 어댑터로 병행, T-A1-12(평가)는 마지막
```
- 첫 수직 슬라이스: **입력 수집 → 요구사항 추출 → 확인 → 계획 → 한 섹션 생성 → DOCX** 를 가상 서버와 합성 RFP 1건으로 끝까지 연결한 뒤 확장.

## 3. 위험과 대응

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| 요구사항 추출 품질 | 제안서 품질의 핵심 | 규칙+LLM 병합, 사용자 확인 필수 단계, 수동 평가 반복 |
| 긴 생성 시간(섹션 반복) | 사용자 대기 | 진행률·취소, 섹션 병렬화는 하지 않음(서버 메모리), 워커 lease+하트비트 |
| 지식 서버 미연결·지연 | 흐름 중단 | 필수/선택 단계 구분, 재시도, 가상 서버로 개발 지속 |
| 세션 상태 일관성 | 이중 제출 | `version` 낙관적 잠금, Idempotency-Key |
| 환각된 법령·조항 인용 | 신뢰 하락 | 모든 인용은 MCP 결과 라벨만 허용, 라벨 없는 법령 언급은 경고 |
