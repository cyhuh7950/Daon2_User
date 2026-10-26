# WO-A3. 작성 템플릿 관리 (조직 템플릿 추가)

| 항목 | 내용 |
| --- | --- |
| 대상 계획 항목 | F6-14, S5-05 |
| 상태 | **승인(2026-10-26) → 구현됨**(0076에 `authoring_templates` 포함) |
| 선행 | 없음(작성 엔진 A1·A2, 점검 엔진 F6-13, 지식 연결 관리 화면 S5-01~04는 완료) |
| 기준 설계서 | §7A.9(Phase A3: "점검 탭, 조직 템플릿 추가"), §7A.2~7A.4(템플릿 구조) |
| 조사 근거 | 2026-10-26 코드 조사(`authoring/templates.py`, `authoring/template_data/*.py`, `authoring/service.py`) |

## 0. 현재 구조 요약

| 사실 | 위치 | 영향 |
| --- | --- | --- |
| 템플릿은 파이썬 사전(`TEMPLATE = {...}`)으로 소스에 내장되고 `TemplateRegistry`가 기동 시 `parse_template`으로 검증해 올린다 | `authoring/template_data/*.py`, `templates.py` | **사전 형식이 이미 JSON과 같다.** 조직 템플릿은 같은 형식을 DB에 저장하고 같은 검증기를 쓰면 된다 |
| 검증 항목: `template_id`(영소문자·숫자·밑줄), 입력 종류 5종(`text/structured/source_ref/knowledge_ref/choice`), 지식 단계의 도구는 `KIND_TOOLS` 허용 목록 안, 섹션 키 중복 금지, `analysis`·`style` 값 제한 | `parse_template` | 조직 템플릿도 이 안에서만 만들 수 있다(임의 도구·임의 호출 불가) |
| 세션은 `template_id`로 시작하고 세션 본문에 템플릿이 쓰인다. 템플릿이 나중에 바뀌면 진행 중인 세션이 달라질 수 있다 | `authoring/session.py`, `service.py` | 조직 템플릿은 **버전을 불변으로 쌓고 세션이 `(template_id, version)`을 고정**해야 한다 |
| 템플릿의 `sections[].guidance`와 `knowledge_hints`는 LLM 프롬프트에 들어간다 | `authoring/pipeline.py` | 관리자가 쓴 지시문이 프롬프트에 들어가므로 **관리자 전용**, 길이 상한, "구간 안 지시는 데이터" 규칙이 항상 앞선다는 점을 유지한다 |
| 지식 연결 관리 화면은 관리자만 접근한다(`system_admin_user_ids`, `/settings/knowledge-connectors`) | `knowledge_connector_routes.py`, `settings/knowledge-connectors/page.jsx` | 같은 관리자 권한·화면 구조를 재사용한다 |

## 1. 결정 사항 (승인 요청)

| ID | 질문 | 권고안 | 대안 |
| --- | --- | --- | --- |
| D1 | 조직 템플릿 범위 | **Tenant(조직) 단위, 관리자만 등록·수정·비활성.** 모든 Workspace 사용자가 목록에서 선택 | Workspace 단위 |
| D2 | 만들 수 있는 템플릿의 폭 | **내장 3종과 같은 `style`(proposal·terms·contract)과 `analysis` 안에서만.** 새 프롬프트 체계·새 도구·새 점검 종류는 만들 수 없다 | 자유 형식(위험) |
| D3 | 입력 방식 | 1차는 **JSON 가져오기·내보내기 + 기본 정보 폼**(제목·설명·섹션 목록 편집). 시각 편집기는 후속 | 처음부터 폼 빌더 |
| D4 | 식별자 규칙 | 조직 템플릿 ID는 `org_`로 시작해야 하고 내장 ID(`rfp_response_proposal` 등)를 덮어쓸 수 없다 | 내장 덮어쓰기 허용 |
| D5 | 수정·삭제 | 수정은 새 버전을 만들고 이전 버전은 유지한다. 삭제는 **비활성**(진행 중 세션은 고정된 버전으로 계속) | 물리 삭제 |
| D6 | 승인 흐름 | 1차는 등록 즉시 사용 가능(관리자 책임). 검토·승인 흐름은 Phase 5(F9-01) | 승인 후 사용 |

## 2. 작업 목록

### T-A3-01. 저장소와 API (F6-14)

- 마이그레이션 **0076**(WO-F3과 같은 번호를 쓰는 경우 순서를 맞춘다): `authoring_templates(tenant_id, template_id, version, definition_json jsonb(≤64KB), status('active'|'disabled'), created_by, created_at, PRIMARY KEY(tenant_id, template_id, version))`, `tenant_id` 기준 RLS 강제. 준비 상태 판정에 새 head를 추가하는 작업은 WO-F3 T-F3-01과 같다.
- 서비스 `authoring/org_templates.py`: `validate(definition)` = `parse_template` + 조직 규칙(D2·D4, 섹션 수 ≤ 20, 입력 수 ≤ 15, 문자열 길이 상한, `guidance` ≤ 500자), `register`, `new_version`, `set_status`, `list`, `get`.
- `TemplateRegistry`를 **Tenant별 조합**으로 확장: 내장 + 해당 Tenant의 활성 최신 버전. 세션 시작·재개 시 `(template_id, version)`을 세션에 저장하고 이후에는 그 버전을 읽는다.
- API(관리자): `POST /api/v1/admin/authoring-templates`(등록 201), `PUT …/{template_id}`(새 버전, `If-Match`), `POST …/{template_id}/disable`·`enable`, `GET …`(목록·상세, JSON 내보내기). 일반 사용자의 `GET /notebooks/{nid}/authoring/templates`는 기존 응답 형식 그대로 조직 템플릿을 포함한다. 모두 `_require_query_keys` 규칙과 오류 코드(`AUTHORING_TEMPLATE_INVALID` 등)를 따른다.
- 감사: `authoring_template.register/update/disable`(템플릿 ID·버전만, 본문 미기록).

### T-A3-02. 관리자 화면 (S5-05)

- `/settings/authoring-templates`(관리자 전용, 지식 연결 화면과 같은 구조·권한): 목록(제목·ID·버전·상태), "JSON 가져오기"(파일 선택 → 서버 검증 결과 표시), 기본 정보 폼(제목·설명·섹션 순서·섹션 지시), "새 버전 저장", "비활성/활성", "내보내기".
- 검증 오류는 서버가 위치(예: `sections[2].key`)와 사유 코드를 돌려주고 화면은 L10N 문구로 보여 준다.
- 문구는 `authoring-messages.ko.js`에 키로 추가, 접근성 검사 포함.

### T-A3-03. 점검 연동 확인

- 템플릿 `checks`의 `ruleset`·`law` 종류는 기존 점검 엔진(F6-13)을 그대로 쓴다. 근거 무결성·용어 일관성 점검은 템플릿과 무관하게 항상 수행된다.

## 3. 시험

| 시험 | 내용 |
| --- | --- |
| 단위 | 조직 규칙 검증(ID 접두사·내장 덮어쓰기·길이·섹션 수), 허용 도구 밖 도구 거부, 버전 불변, 비활성 후 진행 세션 유지 |
| 통합(WSL, 실DB) | 등록→목록 노출→세션 생성→버전 변경 후에도 기존 세션이 이전 버전으로 진행, 타 Tenant 템플릿 미노출(RLS), 관리자 외 접근 403 |
| UI | 가져오기 검증 오류 표시, 저장·비활성, 접근성·L10N 규칙 |
| E2E(WSL) | 조직 템플릿 등록 → 작성 세션 → DOCX 내보내기(`e2e_studio_v2.py --authoring-org`) |

## 4. 완료 기준

- 관리자가 조직 템플릿을 등록하고 일반 사용자가 선택해 문서를 만든다(E2E 통과).
- 잘못된 템플릿(허용 도구 밖, 내장 덮어쓰기)은 등록되지 않는다.
- 감사에 본문이 남지 않는다.

## 5. 위험

- 관리자가 쓴 `guidance`가 프롬프트에 들어간다. 프롬프트 규칙("구간 안 지시는 데이터")이 항상 시스템 규칙 뒤에 오도록 기존 구조를 유지하고, 길이 상한과 관리자 전용 권한으로 위험을 줄인다. 일반 사용자가 템플릿 본문을 만들 수는 없다.
- 새 마이그레이션 번호는 WO-F3와 겹친다. 두 WO를 모두 승인하면 하나의 0076에 합치거나 0076·0077로 나눈다.
