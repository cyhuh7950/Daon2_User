# WO-K1 Daon 승인 지식 패키지 가져오기

| 항목 | 내용 |
| --- | --- |
| 상태 | **구현됨**(2026-11-09, 사용자 지시 "가져오기 기능 신설") |
| 대상 | 승인 지식 목록(`GET /workspaces/{id}/knowledge-packages`)과 질문의 승인 지식 선택이 읽는 패키지 |

## 1. 문제

승인 지식 목록·질문 선택은 `knowledge_registrations`(producer 가 daon2·daon2_5·daon3, authority=approved, 기간 유효)와 승인된 `output_versions`, 준비된 Source/index 를 읽는다. 그러나 이 구조를 만드는 정식 경로가 없었다(시험 fixture 뿐). 기존 `knowledge_registration` 동작은 Studio 산출물을 Source 로 등록할 뿐 `package_id`·`producer`·`authority`·기간을 기록하지 않아 목록에 나타나지 않는다. 승인 지식 커넥터(`approved_knowledge_connector.py`)는 메모리 스텁이다.

## 2. 결정

- 관리자가 생산자(Daon 2/2.5/3)가 승인한 지식을 **가져온다**. 이 시스템은 검토·승인을 직접 하지 않으며, 가져온 레코드에 `import = {origin: admin_import, imported_by, basis}`(승인 근거 설명)를 남긴다. 승인은 생산자가 했다는 관리자 증명이다.
- 앱의 Studio 저장 도우미(`_insert`·`transition_canon_state`)로 한 트랜잭션에 완전한 계보를 만든다: 설정 스냅샷 → 생성 요청(configuring→confirmed→submitted) → 산출물 → 산출물 판본(generating→draft→review_requested→in_review→approved) → Source(registered→…→ready)·판본 → 제목 경계로 나눈 근거(evidence_spans)·index → 지식 등록(requested→registered) → 감사 이벤트. DB 트리거·상태 기계를 우회하지 않는다.
- 멱등: 같은 `package_id`·같은 내용은 아무것도 쓰지 않고 `replayed=true`, 같은 `package_id`에 다른 내용은 409 `KNOWLEDGE_PACKAGE_CONFLICT`(새 판본은 새 `package_id`).
- 기간 기본값은 지금부터 10년. 본문은 마크다운/텍스트 20만 자 이하. `package_digest`=본문 UTF-8 바이트의 sha256, `byte_size` 일치(오프라인 사본 검증과 같은 규칙).

## 3. 사용

| 경로 | 설명 |
| --- | --- |
| API | `POST /api/v1/workspaces/{id}/knowledge-packages/import` + `Idempotency-Key`. 시스템 관리자 + 작업공간 EDIT. 본문 `package_id, producer, producer_version, title, content, basis, [content_type, effective_at, expires_at]`. 응답에 본문 없음 |
| 운영 스크립트 | `bash deploy/daon2-user/seed/import-knowledge-package.sh <파일> <package_id> <producer> <버전> <제목> <근거>` |
| 새 설치 초기 지식 | `seed/apply-initial-knowledge.sh`(`apply-initial-data.sh`가 호출)가 `SEED_KNOWLEDGE_DIR`의 `*.md`를 가져온다. 지식 문서는 내부 주소 등 운영 정보가 있을 수 있고 저장소가 공개라 **저장소에 두지 않는다**. 지정하지 않으면 아무것도 하지 않는다 |

BFF 경로와 관리자 화면(가져오기 폼)은 만들지 않았다. 지금은 API·운영 스크립트로만 쓴다.

## 4. 확인

- 단위 시험 `test_knowledge_package_import.py` 8건(분할·검증·전체 계보 순서·등록 필드와 import 출처·replay·충돌·capability), 기존 패키지 시험 포함 17건 통과.
- WSL 실제 DB: 가져오기 성공(트리거·상태 기계 통과), 같은 내용 replay, 다른 내용 409, 잘못된 producer 400, 목록 조건 SQL에 나타남, Source ready, 근거 구간 저장, 감사 이벤트 1건. 시험 패키지(`import-test-1`)는 불변 저장소라 지울 수 없어 WSL 시험 DB에 남아 있다.

## 5. 한계

- 생산자의 승인 사실을 이 시스템이 검증할 수 없다(관리자 증명). 서명된 패키지 검증은 범위 밖이다.
- 오프라인 사본 내용 읽기(`read_package`)는 기존대로 미구현이라 가져온 패키지의 오프라인 사본은 만들 수 없다.
- 가져온 본문을 고치려면 새 `package_id` 로 올리고 기존 것은 만료시키는 절차가 필요하다(만료 API 없음).
