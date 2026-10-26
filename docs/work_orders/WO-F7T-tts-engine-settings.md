# WO-F7T. TTS 엔진 관리 화면(설정) — WO-F7 후속

| 항목 | 내용 |
| --- | --- |
| 대상 계획 항목 | F7-02 후속(엔진 등록·선택), S5 계열 설정 화면 |
| 상태 | **구현됨**(2026-10-26, 사용자 지시 "설계해 진행해"; 편차는 §8) |
| 선행 | WO-F7(배포 설정 파일 `DAON_TTS_CONFIG_FILE`로 엔진 등록), WO-M0(지식 Connector 관리 — 같은 구조를 따른다) |
| 기준 | `knowledge_connector_service.py`·`knowledge_connector_routes.py`·`knowledge-connectors-pane.jsx`(등록·확인·해제·한도 관리의 선례) |

## 1. 문제

WO-F7의 엔진 등록은 서버의 JSON 파일(키 포함)을 직접 고쳐야 한다. 관리자가 화면에서 엔진을 추가·확인·기본 지정·해제하고, 키를 화면 밖으로 꺼내지 않게 해야 한다.

## 2. 결정(권고안을 그대로 채택)

| ID | 결정 | 근거 |
| --- | --- | --- |
| D1 | **조직(tenant) 단위 DB 테이블 `tts_engines`**(마이그레이션 0078). API 키는 `ProviderCredentialCipher`(AES-GCM)로 암호화해 저장하고 호출 직전에만 복호화한다. 목록 응답에 키는 없고 `has_credential`만 준다 | Connector와 같은 방식 |
| D2 | **배포 설정 파일은 유지**(하위 호환). 한 조직의 유효 설정 = 화면에서 등록한 엔진(우선) + 배포 파일 엔진. 같은 `slug`면 화면 등록이 이긴다. 화면에는 배포 엔진이 "배포 설정"으로 읽기 전용 표시된다 | 기존 WSL 시험 스택이 그대로 동작 |
| D3 | 관리 권한은 **시스템 관리자**(`system_admin_user_ids`). 일반 사용자는 엔진 이름·상태 없이 생성 설정의 선택지(엔진·보이스)만 본다 | Connector와 같음 |
| D4 | **SSRF 방어**: 등록 주소는 `validate_endpoint`(스킴·자격증명·쿼리 금지, 사설·루프백 주소는 `DAON_MCP_ALLOW_PRIVATE_ENDPOINTS`가 켜진 시험 스택에서만). 외부 전송 정책 판정은 그대로 `provider_kind`(기본 `external_api`)로 한다 | 관리자 입력 URL을 서버가 호출하므로 |
| D5 | **연결 확인(verify)** = `/health` + `/v1/voices`. 성공하면 `status=verified`와 엔진이 알려 준 보이스 목록을 `voice_choices`에 채운다(관리자가 손으로 적지 않아도 된다). 확인이 성공했다는 것은 "연결됨"이지 "합성 성공"이 아니다 | WO-F7 D2와 같은 원칙 |
| D6 | **기본 엔진**은 조직당 하나(`is_default`, 부분 유일 인덱스). 기본이 없으면 첫 번째 사용 가능한 엔진. 생성 설정의 `engine`은 유효 목록에 있는 것만 허용 | WO-F7 D1 |
| D7 | 엔진 설정은 **15초 캐시**(프로세스별)로 읽는다. 같은 프로세스의 변경은 즉시 반영하고 다른 프로세스(워커)는 최대 15초 뒤 반영한다 | 요청마다 DB를 읽지 않기 위해 |
| D8 | 상태 `disabled`는 선택지와 생성에서 제외한다(삭제하지 않고 끄기) | 키를 다시 입력하지 않고 일시 중지 |

## 3. 데이터

`tts_engines(tenant_id, engine_id 'te-<32hex>', slug, label, base_url, provider_kind, language, timeout_seconds, voice_a, voice_b, voice_choices text[], credential_ciphertext/nonce/version/encryption_key_version, status, last_checked_at, error_code, is_default, version, created_by, created_at, updated_at)`
- 유일: `(tenant_id, slug)`, 기본 엔진은 `(tenant_id) WHERE is_default`.
- RLS: `tenant_id = app.tenant_id`. 삭제는 행 삭제(Connector와 같음).

## 4. API(관리자)

| 메서드·경로 | 설명 |
| --- | --- |
| `GET /api/v1/admin/tts-engines` | 화면 등록 엔진(주소·상태·보이스·기본 여부, 키 없음) + 배포 엔진(읽기 전용) |
| `POST /api/v1/admin/tts-engines` | 등록(`slug`·`label`·`base_url`·`api_key?`·`provider_kind?`·`language?`·`timeout_seconds?`·`voices{A,B}`·`voice_choices?`), `Idempotency-Key` |
| `POST …/{id}/verify` | 연결 확인(D5) |
| `PATCH …/{id}` | `label`·`voices`·`voice_choices`·`timeout_seconds`·`provider_kind`·`is_default`·`enabled`·`api_key`(교체), `If-Match` |
| `DELETE …/{id}` | 해제 |

감사: `tts_engine.register|verify|update|disconnect`(키·주소 본문은 기록하지 않고 slug·상태만).

## 5. 변경 범위

- 백엔드: `migrations/0078`, `tts_engine_service.py`(저장소·암호화·캐시·해석기), `tts_engine_routes.py`, `tts_engines.py`(엔진 `source`), `studio_audio.py`·`studio_video.py`(조직별 설정 해석), `studio_v2_routes.py`·`studio_v2_postgres.py`(조직별 사용 가능 판정), `runtime.py`(연결·리비전 허용 목록), 워커(해석기 주입).
- 프런트: BFF 경로, `tts-engines-api.js`, `packages/ui/src/tts-engines-pane.jsx`, `/settings/tts-engines` 페이지·내비게이션, 문구.
- 계약: OpenAPI에는 포함하지 않는다(관리자 API는 Connector도 별도 계약이 없음 — 경로 일치 시험 대상 아님).

## 6. 시험

단위(검증·암호화 왕복·캐시·병합·기본 엔진·SSRF), 서비스 HTTP(관리자만·키 비노출·ETag 충돌), 생성기가 조직 엔진을 쓰는지, UI(등록·확인·기본·삭제·배포 엔진 읽기 전용), 실DB IT, WSL E2E(화면 등록 API로 엔진을 등록 → 확인 → 그 엔진으로 오디오 생성 → 해제).

## 7. 범위 밖

엔진별 사용량·비용 한도, 보이스 미리듣기, 조직 간 엔진 공유, 엔진 키 자동 순환.

## 8. 구현 결과와 편차 (2026-10-26)

| 항목 | 설계 | 구현 |
| --- | --- | --- |
| 마이그레이션 | 0078 `tts_engines` | 그대로(RLS는 `tenant_id`만, 기본 엔진은 부분 유일 인덱스). 리비전 허용 목록 11곳과 "알 수 없는 미래 리비전" 시험을 0079 기준으로 올림 |
| 해석기 | 15초 캐시, 화면 등록 우선 | `TtsEngineService.for_tenant`. 같은 slug는 화면 등록이 이기고, `disabled`·사설 주소·복호화 실패 엔진은 그 엔진만 제외하며, DB 장애 시 배포 설정으로 동작한다 |
| 권한 | 시스템 관리자 | `DAON_SYSTEM_ADMIN_USER_IDS`(Connector와 같음). 라우트 단위 시험과 컨테이너 안 실서비스 점검(`qa/tts_engine_admin_check.py`)에 더해, **사용자 승인(2026-10-26)으로 WSL 시험 스택에서만 qa-e2e를 시스템 관리자로 잠시 지정**해 BFF를 거친 관리 API E2E(`e2e_studio_v2.py --tts-admin`)를 실행했고 바로 원복했다(`.env` 항목 삭제·api 재생성, 원복 뒤 다시 전 경로 403 확인) |
| 중복 slug | `UniqueViolation` | 저장소가 제약 위반을 `DATABASE_CONSTRAINT_VIOLATION`으로 바꿔 올리므로 그 코드를 `TTS_ENGINE_SLUG_EXISTS`(409)로 매핑(실DB 시험에서 발견) |
| 화면 | 등록·확인·기본·수정·사용 안 함·해제 | `/settings/tts-engines`(`tts-engines-pane.jsx`). 배포 엔진은 읽기 전용 행, 수정 대화상자는 엔진이 알려 준 목소리 선택지에서 고름, 주소·키를 바꾸면 다시 확인 필요 |
| 계약 | OpenAPI 제외 | 제외(Connector와 같음) |

검증: 서비스 단위 18(검증·암호화·병합·캐시·확인·수정 규칙), 라우트 5(관리자 전용·ETag·오류·키 비노출·`/types`가 조직별 설정을 따름), 생성기 조직별 해석 1, UI·클라이언트 8, BFF 경로 1, **실DB IT 6**(RLS 격리·기본 엔진 승격·버전 충돌·키 교체·사용 안 함), WSL 실서비스 점검(등록→암호화 저장→실제 음성 서버 연결 확인→목소리 10개 자동 채움→기본 지정→해석기가 복호화한 키로 해석), **실제 LLM+음성 서버 E2E**(`--audio --engine=supertonic-ui`: 화면 등록 엔진으로 생성, 본문에 엔진 slug 기록, 120초). **관리 API E2E(BFF 경유, 실제 음성 서버)**: 권한 부여 전 5개 경로 모두 403 → 부여 후 목록·등록(201, 키 비노출, ETag)·중복 slug 409·잘못된 주소/목소리 400·연결 확인(목소리 10개 자동 채움)·오래된 If-Match 409·잘못된 If-Match 400·수정(이름·기본·목소리)·기본은 하나뿐·생성 설정(`/types`)에 새 엔진과 기본값 반영·사용 안 함(기본 지정 거부 409, 선택지에서 사라짐)·해제 204·재해제 404·배포 엔진 읽기 전용 유지 24개 통과 → 원복 뒤 다시 403. **미검증**: 실제 브라우저에서의 화면 조작(시험 페이지 렌더만 확인), 여러 API·워커 프로세스 간 15초 캐시 지연의 체감 영향.
