# WO-F1. Studio v2 백엔드 기반 (Phase 0)

| 항목 | 내용 |
| --- | --- |
| 대상 계획 항목 | F1-01 ~ F1-16, F3-04, F3-05 (일부) |
| 기준 설계서 | `docs/daon2-user-studio-design.md` §6~§9, §12 |
| 작성 근거 | 2026-10-20 코드 조사(백엔드 Studio, 큐·마이그레이션, LLM·검색). 경로는 모두 `D:\Project\Daon2_User` 기준 |
| 상태 관리 | 항목 상태는 `docs/daon2_user_development_plan.md`가 정본. 이 문서는 작업 내용만 적는다 |

경로 약어: `API` = `services/api/src/daon2_user_api`, `MIG` = `services/api/migrations/versions`, `TESTS` = `services/api/tests`.

---

## 0. 설계 결정 (조사 결과를 반영해 확정)

조사에서 확인된 제약 때문에 설계서 §8~§9의 구현 방식을 아래와 같이 구체화한다. 이 결정을 바꾸려면 이 절부터 고친다.

| # | 결정 | 이유(조사 근거) |
| --- | --- | --- |
| D1 | **기존 Studio(캐논 테이블 `studio_outputs`/`output_versions`, 승인 흐름)는 손대지 않고, 새 `studio_v2_*` 테이블과 새 API 경로로 만든다.** 기존 API·화면은 읽기 호환으로 남기고 새 UI는 v2만 쓴다. | `studio_outputs`·`evidence_references`·`generation_settings_snapshots`는 불변 트리거로 보호되고, `output_versions`는 `transition_canon_state`로 상태만 바뀐다. cancelled/stale/제목 변경/삭제/공유를 UPDATE로 넣을 수 없다. `validate_canon_insert`·`reject_canon_immutable_mutation`은 본문 MD5가 `cloud_storage.py`에 고정되어 있어 수정하면 준비 검사가 깨진다. |
| D2 | **내보내기·공유·전달에서 승인(`approved`)과 step-up을 요구하지 않는다.** 승인 흐름은 후속(Phase 5)에서 v2 위에 선택 기능으로 얹는다. | 기존 `export_output`은 `state='approved'` + step-up이 필수(`runtime.py:5400`). 설계서 §10.1·부록 D 결정(1차 UI 미표시). |
| D3 | **작업 큐는 새 테이블 `studio_v2_jobs`를 쓴다.** 기존 `studio_generation_jobs`는 건드리지 않는다. | 기존 테이블은 트리거 `guard_studio_generation_job`(0069)이 허용 전이를 고정하고 `cancelled`가 없다. 알림 SQL(0069)이 완료/실패/unavailable만 안다. |
| D4 | **새 테이블은 SECURITY DEFINER 함수·트리거 없이 만든다.** 소유자 `daon_notebook_delete`(D11), `ENABLE`+`FORCE ROW LEVEL SECURITY`, 정책 `tenant_id`+`workspace_id`(+`notebook_id`는 쿼리 조건). 큐 claim은 앱 SQL(`FOR UPDATE SKIP LOCKED`)로 한다. | 함수 본문 MD5를 `cloud_storage.py`에 고정하는 부담과 해시 불일치 위험을 피한다. 읽기 전용 카탈로그 검사(`_studio_v2_storage_is_protected`)만 추가한다. |
| D5 | **v2 워커는 별도 Compose 서비스 `studio-v2-worker`** 로 둔다. 워커 telemetry는 발행하지 않는다. | telemetry 종류는 0071 CHECK(`document,studio,object`)에 고정. 변경 시 마이그레이션과 기대 카탈로그 상수를 함께 바꿔야 한다. |
| D6 | **상태 갱신은 SSE 대신 폴링으로 시작한다**(활성 작업이 있으면 1.5초, 없으면 중지). | BFF 프록시는 응답을 `arrayBuffer()`로 버퍼링하고 10초 타임아웃·헤더 허용 목록이 있어 스트리밍이 불가능하다. 폴링은 기존 패턴(`studio-generation-jobs` 500ms×120)과 같다. SSE는 후속(프록시 `stream` 플래그 필요). |
| D7 | **새 기능은 플래그 `DAON_STUDIO_V2_ENABLED`(기본 false)로 감싼다.** API 라우트·워커·UI 모두 플래그 뒤에 둔다. | 안전한 단계 배포. 플래그 추가는 5곳 수정이 필요(T1-02). |
| D8 | **1차 LLM은 로컬/서버 내부 Provider(`local`, `server_internal`, `local_runtime`, 즉 Ollama 계열)만 허용**한다. 외부 Provider는 `STUDIO_EXTERNAL_PROVIDER_UNSUPPORTED`로 거부한다. 외부 허용은 F1-14(전용 egress 승인 계층) 완료 후. | 기존 egress 승인 계층(`PostgresQuestionEgressAuthorizer`)은 `QuestionContext`·질문 run 테이블에 묶여 있어 그대로 쓸 수 없다. |
| D9 | **새 마이그레이션 번호는 `0074`.** 추가하면 API가 `not_ready`가 되므로 T1-04의 수정 지점을 **같은 커밋**에서 모두 바꾼다. | 준비 검사·질문 응답·비용 기록이 리비전 `0073`을 하드코딩. |
| D10 | **스키마 변경 호환**: 기존 `OUTPUT_TYPES` 11종은 그대로 두고 v2 유형 레지스트리를 따로 둔다(`type_id`: report, data_table, mind_map, flashcards, quiz, slides, infographic, audio_overview, video_overview, memo). | 기존 `output_version_settings.OUTPUT_FORMATS`·DB CHECK가 5종에 고정되어 있다. |
| D11 | **노트북 삭제 방식(T1-01 결과)**: v2 테이블은 `notebooks`에 `ON DELETE CASCADE` FK를 건다. 소유자는 `daon_notebook_delete`(기존 `studio_generation_jobs`, 0069와 같은 방식), 앱 역할 `daon_app`은 SELECT/INSERT/UPDATE만 갖는다(리비전·근거·소스·학습 시도는 SELECT/INSERT만 = 불변). RI 캐스케이드는 FORCE RLS를 우회하므로 삭제 함수(`delete_notebook_scope`)를 수정하지 않아 MD5 고정값이 유지된다. | 0056이 노트북 FK 자식을 `daon_notebook_delete` 소유로 두고 `daon_app`에 DELETE를 주지 않는 구조다. 앱 소유 테이블이면 리비전 불변을 권한으로 만들 수 없다. 실DB 확인은 WSL 적용 시 수행. |
| D12 | **LLM Provider 우선순위·설정(사용자 지시 2026-10-20)**: 사용 순서는 1 Media Bridge Server → 2 Upstage → 3 OmniRoute → 4 Ollama(`https://ollama-api.sinsan.kr`). 설정은 daon-user 방식(관리자 화면의 Provider 연결·기본 모델·허용 모델, **API Key는 .env가 아니라 DB에 암호화 저장**)을 그대로 쓴다. 따라서 D8의 "로컬 Provider만"은 **폐기**하고, 생성 어댑터는 `PostgresWorkspaceModelResolver`가 돌려주는 연결을 순서대로 시도(폴백)한다. 외부 Provider 사용 시의 egress 승인(F1-14)은 WO-F2에서 처리한다. | 사용자 지시. 키를 환경 변수에 두지 않는다. |

---

## 1. 작업 목록

### T1-01. 스파이크: 노트북 삭제·복사와 v2 테이블의 관계

- **목적**: 노트북 삭제 시 v2 테이블이 고아로 남거나 삭제가 FK로 실패하지 않게 한다.
- **조사 대상**: `MIG/0023_notebook_deletion.py`, `MIG/0056_notebook_delete_acl.sql`, `API/notebook_deletion.py`, `API/notebook_postgres.py`(삭제·바인딩 SQL), `daon_notebook_delete` 소유 테이블 43개 목록.
- **산출**: 이 문서 §0에 "삭제 방식" 결정을 한 줄 추가. 후보 (a) v2 테이블에 `notebooks` FK `ON DELETE CASCADE`, (b) 삭제 경로의 테이블 목록에 v2를 추가(함수 본문 변경 → MD5 재고정 필요, 비권장). **(a)를 우선 검증**한다.
- **완료 기준**: 로컬 Postgres(WSL 전용 DB)에서 노트북 삭제 요청 후 v2 행이 남지 않음을 SQL로 확인한 기록.
- 선행: 없음. 소요: 0.5일.

### T1-02. 기능 플래그 `DAON_STUDIO_V2_ENABLED`

- **변경 파일**
  - `API/runtime.py` `RuntimeSettings`: 필드 `studio_v2_enabled: bool = False`(~l.575 근처 다른 플래그 옆).
  - 같은 파일 `from_env()`(~l.738): `os.environ.get("DAON_STUDIO_V2_ENABLED","false")`가 정확히 `"true"|"false"`가 아니면 `ValueError("DAON_STUDIO_V2_ENABLED_FLAG_INVALID")`.
  - `__post_init__`: `type(self.studio_v2_enabled) is not bool`이면 오류(다른 플래그와 동일 문구 형식).
  - `deploy/daon2-user/compose.yaml`: `api`와 신규 `studio-v2-worker`에 `DAON_STUDIO_V2_ENABLED: ${DAON_STUDIO_V2_ENABLED-false}`.
  - `.env.example` 에 주석 포함 한 줄.
- **테스트**: `TESTS/test_runtime_http.py`의 설정 테스트 패턴을 따라 `TESTS/test_studio_v2_settings.py` 신규(참/거짓/잘못된 값/기본값).
- **완료 기준**: `PYTHONPATH=src uv run --frozen pytest tests/test_studio_v2_settings.py -q` 통과, `verify:api-runtime` 영향 없음.

### T1-03. 마이그레이션 `0074` (py+sql 쌍)

- **파일**: `MIG/0074_studio_v2.py`, `MIG/0074_studio_v2.sql`. `down_revision = "0073"`. 형식은 `0073_operations_cost_capacity.py`를 따른다(`.py`가 같은 이름 `.sql`을 읽어 `exec_driver_sql`, `execution_options(no_parameters=True)`).
- **SQL 선두 precondition DO 블록**: 실행 역할이 superuser, `alembic_version`이 1행이고 `'0073'`, 역할 `daon_app` 존재·`NOT rolsuper AND NOT rolbypassrls`. 실패 시 `STUDIO_V2_PRECONDITION` (ERRCODE `55000`).
- **테이블**(모두 `tenant_id text`, `workspace_id text`, 소유자 `daon_app`, `ENABLE`+`FORCE RLS`, 정책 `<table>_scope USING/WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'') AND workspace_id=nullif(current_setting('app.workspace_id',true),''))`, `GRANT SELECT,INSERT,UPDATE[,DELETE] ... TO daon_app`):

  1. `studio_v2_outputs` — PK `(tenant_id, workspace_id, output_id)`
     - `output_id text`(패턴 `^sv2-[0-9a-f]{32}$`), `notebook_id text NOT NULL`, `owner_actor_id text NOT NULL`
     - `type_id text NOT NULL CHECK (type_id IN ('report','data_table','mind_map','flashcards','quiz','slides','infographic','audio_overview','video_overview','memo'))`
     - `format_id text`, `title text NOT NULL CHECK (length(title) BETWEEN 1 AND 160)`
     - `status text NOT NULL CHECK (status IN ('queued','generating','completed','failed','cancelled'))`
     - `error_code text`, `settings_json jsonb NOT NULL DEFAULT '{}'`, `source_version_ids text[] NOT NULL`
     - `current_revision int NOT NULL DEFAULT 0`, `idempotency_key_sha256 text NOT NULL`
     - `created_at timestamptz NOT NULL DEFAULT now()`, `updated_at timestamptz NOT NULL DEFAULT now()`, `deleted_at timestamptz`
     - UNIQUE `(tenant_id, workspace_id, owner_actor_id, idempotency_key_sha256)`
     - FK `(tenant_id, workspace_id, notebook_id)` → `notebooks` `ON DELETE CASCADE` (T1-01 결과에 따라 확정)
     - 인덱스 `(tenant_id, workspace_id, notebook_id, created_at DESC) WHERE deleted_at IS NULL`
  2. `studio_v2_revisions` — PK `(tenant_id, workspace_id, output_id, revision_no)`
     - `revision_no int CHECK (revision_no > 0)`, `revision_type text CHECK (IN ('generated','user_edit','regenerated'))`
     - `content_json jsonb NOT NULL` (봉투: 설계서 §8.3), `content_sha256 text NOT NULL`, `warnings_json jsonb NOT NULL DEFAULT '[]'`
     - `generated_with jsonb NOT NULL DEFAULT '{}'` (provider/model/prompt_version, UI 비노출)
     - `created_by text NOT NULL`, `created_at timestamptz NOT NULL DEFAULT now()`
     - 불변: `GRANT SELECT,INSERT` 만(UPDATE 없음). FK → outputs `ON DELETE CASCADE`.
  3. `studio_v2_sources` — 생성 당시 Source 스냅샷. PK `(tenant_id, workspace_id, output_id, revision_no, source_version_id)`, `source_id text`, `content_digest_sha256 text`.
  4. `studio_v2_evidence` — PK `(tenant_id, workspace_id, output_id, revision_no, ref_id)`; `source_version_id`, `evidence_span_id text`, `locator_kind text`, `locator_value text`, `quote_sha256 text`, `origin text CHECK (IN ('notebook_source','mcp_daon_rag','mcp_daon','mcp_law'))`, `external_ref jsonb`.
  5. `studio_v2_assets` — PK `(…, asset_id)`; `kind CHECK (IN ('docx','pdf','xlsx','csv','md','json','svg','png','pptx','mp3','wav','mp4'))`, `object_key text`, `bytes bigint`, `sha256 text`, `duration_ms int`, `content_type text`, `revision_no int`.
  6. `studio_v2_jobs` — PK `(…, job_id)`; `output_id text NOT NULL`, `state text CHECK (IN ('queued','leased','generating','completed','failed','cancelled'))`, `attempt int DEFAULT 0`, `max_attempts int DEFAULT 3 CHECK (1..10)`, `lease_owner text`, `lease_until timestamptz`, `next_attempt_at timestamptz DEFAULT now()`, `cancel_requested boolean DEFAULT false`, `progress_pct smallint CHECK (0..100)`, `progress_note text`, `safe_error_code text`, `request_json jsonb NOT NULL`, `version int NOT NULL DEFAULT 1`, `created_at`, `updated_at`, `completed_at`. 부분 인덱스 `(next_attempt_at) WHERE state IN ('queued','leased','generating')`.
     - 불변식 CHECK: `(state IN ('leased','generating')) = (lease_owner IS NOT NULL AND lease_until IS NOT NULL)`.
  7. `studio_v2_learning_attempts` — PK `(…, attempt_id)`; `output_id`, `revision_no`, `user_id`, `kind CHECK (IN ('flashcard','quiz'))`, `payload_json jsonb`, `created_at`. RLS 정책에 `user_id = nullif(current_setting('app.actor_id',true),'')` 추가(본인 범위).
  8. `studio_v2_memos`는 별도 두지 않는다. 메모는 `type_id='memo'` 산출물이다(리비전 본문은 `{markdown, refs?}`).
  9. `workspace_studio_v2_customization` — PK `(tenant_id, workspace_id, notebook_id)`; `instruction text CHECK (length <= 4000)`, `version int`, `updated_by`, `updated_at` (맞춤설정, F3-01).
- **downgrade**: DO 블록으로 superuser 확인·`alembic_version = '0074'`·모든 v2 테이블 행 수 합 0 확인, 하나라도 있으면 `STUDIO_V2_FORWARD_RECOVERY_REQUIRED`. 비어 있으면 DROP.
- **테스트**: `TESTS/test_studio_v2_migration.py`(정적: SQL 텍스트에서 테이블·RLS·GRANT·CHECK 존재, `0073` 선행조건 문구, downgrade 가드). 형식은 `TESTS/test_account_settings_migration.py`.
- **완료 기준**: 정적 테스트 통과 + WSL에서 `wsl-bootstrap-db.sh --recreate`(CONFIRM_DROP 필요) 또는 `alembic upgrade head`로 `0074 (head)` 적용, `\d+` 로 8개 테이블·RLS 확인 기록.

### T1-04. 준비 검사·리비전 하드코딩 갱신 (0074 대응, 마이그레이션과 같은 커밋)

0074를 적용하면 아래가 모두 0073 고정이라 API가 `not_ready`/503이 된다. **전부 수정**한다.

| 파일 | 위치 | 변경 |
| --- | --- | --- |
| `API/cloud_storage.py` | `readiness().compatible` (l.367~) | `if revision == "0074":` 분기 추가. 0073 분기와 같은 검사에 각 helper를 `expected_revision="0074"`로 호출 + `_studio_v2_storage_is_protected(connection)` |
| 같은 파일 | `_registered_restore_storage_is_protected`(l.432), `_telemetry_storage_is_protected`(l.508), `_document_readiness_storage_is_protected`(l.689) | 허용 리비전 집합에 `"0074"` 추가 |
| 같은 파일 | `_operations_cost_capacity_storage_is_protected`(l.615) | 리터럴 `"0073"`을 인자로 받도록 바꾸거나 `{"0073","0074"}` 허용 |
| `API/runtime.py` | l.542 `_build_run_cost_sessions`, l.552 `_build_host_capacity_collector` | `schema_revision != '0073'` → `not in {'0073','0074'}` |
| 같은 파일 | l.878 `_build_document_readiness_runtime`, l.1683, l.2403 | 집합에 `"0074"` |
| `API/question_answering_postgres.py` | l.1207 `_record_run_cost`, l.1212 | 허용 `{'0071','0072','0073','0074'}`, 가격표 영수증 조건 `in {'0073','0074'}` |
| 테스트 | `TESTS/test_cloud_storage.py`(~92-108, 402-407: 현재 "0074는 not ready"를 단언), `test_runtime_http.py`(~67, 887, 1621, 1676), `test_notification_dispatch_runtime.py`(~68-73), `test_question_answering_postgres.py`(~224-241), `operations_cost_capacity_live_probe.py` | 0074를 정상 리비전으로 바꾸고 "미지의 미래 리비전" 음성 사례는 `0075`로 변경 |

- **`_studio_v2_storage_is_protected`** (신규, 읽기 전용 카탈로그 조회 — `_operations_cost_capacity_storage_is_protected`의 형식을 따르되 함수/트리거 검사는 없음): alembic 버전이 `0074`, 8개 테이블 존재·`relkind='r'`·`relpersistence='p'`·소유자 `daon_app`·`relrowsecurity`+`relforcerowsecurity`, `studio_v2_revisions`에 `daon_app`의 `UPDATE/DELETE` 권한 없음, 각 테이블의 PK 컬럼 목록 일치.
- **완료 기준**: `/health/ready` 200(WSL에서 `0074` 적용 상태), 수정한 테스트 전부 통과, `verify:api-cloud` 통과.

### T1-05. v2 유형 레지스트리 `API/studio_v2_types.py` (신규)

```python
@dataclass(frozen=True, slots=True)
class StudioV2Type:
    type_id: str                 # 'report', ...
    formats: tuple[str, ...]     # 내보내기 형식
    default_format: str          # 생성 시 'format_id' 기본값 (예: report → 'summary')
    presets: tuple[str, ...]     # 'format_id' 허용값(보고서 5종 등), 없으면 ()
    settings_schema: Mapping     # JSON Schema(선택 설정)
    requires_llm: bool
    phase: str                   # '1'|'2'|'3'|'4'
    export_formats: tuple[str, ...]
STUDIO_V2_TYPES: Mapping[str, StudioV2Type]
def available_types(settings: RuntimeSettings, *, tts_enabled: bool=False) -> list[Mapping]  # /studio/types 응답
```
- 유형·형식 표는 설계서 §5, §5.1 그대로: report(presets `summary,briefing,blog,study_guide,custom`, export docx/pdf/md), data_table(xlsx/csv/pdf), mind_map(svg/png/json), flashcards(csv/json/pdf), quiz(csv/json/pdf), slides(pptx/pdf), infographic(png/svg/pdf, phase 2), audio_overview(mp3/wav, phase 3), video_overview(mp4, phase 4), memo(md/txt).
- `available_types()`는 Phase 4 이전 유형을 `{"available": false, "reason": "STUDIO_TYPE_UNAVAILABLE"}`로 반환한다(UI가 타일을 비활성 표시).
- **테스트** `TESTS/test_studio_v2_types.py`: 모든 설계서 §5 유형 존재, 형식 중복 없음, 비활성 유형 사유 반환.

### T1-06. 저장소 `API/studio_v2_postgres.py` (신규)

`class PostgresStudioV2Repository(cloud_store)` — 트랜잭션은 `cloud_store._transaction(context)`(app.tenant_id/workspace_id/actor_id GUC 설정)를 사용한다. 문맥 타입은 기존 `StudioContext`(`API/studio_workspace.py:131`)를 재사용한다.

| 메서드 | 동작·계약 |
| --- | --- |
| `require_scope(connection, context, notebook_id, source_version_ids)` | 기존 `_require_generation_scope`(`studio_workspace_postgres.py:30`)와 같은 규칙: 노트북 바인딩·미해제·미삭제·`identity_auth_source_access` 거부 없음. 코드를 **복사하지 말고** 공통 함수로 추출해 양쪽이 쓰게 한다(추출 시 기존 테스트 `test_studio_workspace_postgres.py` 유지). |
| `enqueue(context, request, idempotency_key)` | 한 트랜잭션: 스코프 검증 → `output_id=_opaque("sv2", tenant, workspace, actor, key)` 결정적 생성 → `studio_v2_outputs`(status `queued`) + `studio_v2_jobs`(`queued`) 삽입 → 이미 있으면 같은 요청이면 재생(replay), 다르면 `IDEMPOTENCY_CONFLICT`. 반환 `{output_id, job_id, status}`. 동시 한도 검사: 해당 actor의 `queued/leased/generating` 작업이 `DAON_STUDIO_V2_USER_CONCURRENCY`(기본 2)를 넘으면 **거부하지 않고 큐에 둔다**(대기). 한도는 claim 시점에 적용(T1-07). |
| `list_outputs(context, notebook_id, cursor, limit<=50)` | `deleted_at IS NULL`, 최신순. 각 항목: `output_id,type_id,format_id,title,status,error_code,source_count,current_revision,created_at,updated_at,stale`. **stale은 조회 시 계산**(T1-15). 삭제된 근거 Source가 있는 산출물은 표시 제한(기존 `list_outputs`와 같은 규칙). |
| `get_output(context, output_id, revision=None)` | 최신(또는 지정) 리비전 본문 + 근거 목록. 소유권/노트북 일치 검증. |
| `rename(context, output_id, title, expected_updated_at)` | `UPDATE ... WHERE updated_at = expected` (낙관적 잠금, 불일치 시 `STUDIO_VERSION_CONFLICT` 409). |
| `soft_delete(context, output_id)` | `deleted_at=now()`, 진행 중 작업이면 취소 요청 먼저. 객체 저장소 자산 삭제는 비동기 정리(T1-12). |
| `request_cancel(context, output_id)` | `studio_v2_jobs.cancel_requested=true` (진행 중), `queued`면 즉시 `cancelled`. 응답 202. |
| `add_revision(context, output_id, revision_type, content_json, warnings, generated_with)` | `revision_no = current_revision+1`을 `UPDATE ... SET current_revision=current_revision+1 RETURNING` 으로 얻고 삽입. 사용자 편집은 `user_edit`. 본문 크기 상한 2 MiB. |
| `regenerate(context, output_id, settings_override, idempotency_key)` | 새 `output_id` 를 만들지 않고 같은 산출물에 새 작업을 추가(`regenerated` 리비전). 이전 리비전은 보존. |
| `provenance(context, output_id, revision)` | 설계서 §6.5.2: 지시문(포커스·맞춤설정 적용 여부), 설정 스냅샷, Source 목록(이름·버전·변경됨 여부), 근거 목록. **시스템 프롬프트 원문 제외**. |
| `record_learning_attempt` / `list_learning_attempts` | 본인 범위(RLS `user_id`). |
| `copy_notebook_outputs(...)` | T1-16에서 정의. |

- **오류**: `StudioError(code, status)`(기존 클래스 재사용). 신규 코드: `STUDIO_NO_READY_SOURCE`(409), `STUDIO_TYPE_UNAVAILABLE`(409), `STUDIO_VERSION_CONFLICT`(409), `STUDIO_VALIDATION_FAILED`(502), `STUDIO_GENERATION_FAILED`(502), `STUDIO_CANCELLED`(409), `STUDIO_EXTERNAL_PROVIDER_UNSUPPORTED`(409), `STUDIO_REVISION_TOO_LARGE`(413).
- **테스트** `TESTS/test_studio_v2_repository.py`: `test_studio_workspace_postgres.py` 앞부분(l.1-40)의 `Result`/`Connection`/`MagicMock` 스토어 패턴으로 SQL 호출 순서·인자 검증. Postgres 실DB 클래스는 `@unittest.skipUnless(os.environ.get("DAON_STUDIO_V2_TEST_DSN"))` — DSN 형식은 `NOSUPERUSER NOBYPASSRLS` 로그인 역할(`daon_app` 멤버).

### T1-07. 큐 `API/studio_v2_queue.py` (신규)

`class PostgresStudioV2Queue(dsn, cloud_store)` — `studio_generation_queue.py` 의 인터페이스(`claim/start/retry/finish/get/close`)를 따르되 아래가 다르다.

- **claim(worker_id, lease_seconds)**: 단일 SQL(CTE)로 후보 선택 → `FOR UPDATE SKIP LOCKED` → `state='leased'`, `attempt+1`, `lease_owner`, `lease_until=now()+lease`, `version+1`. 후보 조건:
  `(state='queued' AND next_attempt_at<=now()) OR (state IN ('leased','generating') AND lease_until<now() AND attempt<max_attempts)`. **동시 한도**: 같은 `owner_actor_id`의 `leased/generating` 수 < 사용자 한도(기본 2), 전체 `leased/generating` 수 < 서비스 한도(기본 4)(환경변수 `DAON_STUDIO_V2_USER_CONCURRENCY`, `DAON_STUDIO_V2_GLOBAL_CONCURRENCY`). 한도 초과 후보는 건너뛴다.
- **heartbeat(job, extend_seconds)**: `lease_until` 연장 + `progress_pct/note` 갱신(`WHERE version=%s AND lease_owner=%s`). 조사에서 기존 큐는 하트비트가 없어 LLM 호출이 lease(600초)를 넘으면 이중 claim 되므로 **필수**.
- **sweeper**: `attempt >= max_attempts` 이고 lease가 만료된 `leased/generating` 행은 claim 대상이 아니라 영구 고착된다(기존 큐의 결함). 워커 루프가 60초마다 `UPDATE ... SET state='failed', safe_error_code='STUDIO_DEAD_LETTER' WHERE ...`을 수행한다.
- **cancel**: `cancel_requested=true` 설정은 API가, 워커는 단계 경계마다 `is_cancel_requested(job)`을 확인해 `finish(state='cancelled')`.
- **finish(job, state, error_code, progress)**: `WHERE version=%s AND lease_owner=%s` 조건. 0행이면 `STUDIO_JOB_LEASE_LOST`.
- 산출물 `status` 동기화: `finish`와 `start`가 같은 트랜잭션에서 `studio_v2_outputs.status/error_code/updated_at`를 갱신한다.
- **테스트** `TESTS/test_studio_v2_queue.py`: 한도 초과 대기, lease 만료 재claim, 한도(attempt) 초과 후 dead-letter 전환, 취소, 버전 충돌(LEASE_LOST). 패턴은 `test_studio_generation_worker.py`의 `FakeQueue`.

### T1-08. 워커 `API/studio_v2_worker.py` + Compose 서비스

- `StudioV2WorkerSettings.from_env()`: 필수 `DAON_CLOUD_DATABASE_DSN`(없으면 `STUDIO_V2_WORKER_DATABASE_REQUIRED`), 선택 `DAON_STUDIO_V2_WORKER_ID`(기본 `studio-v2-worker-1`), `DAON_STUDIO_V2_LEASE_SECONDS`(기본 900), `DAON_STUDIO_V2_POLL_SECONDS`(0.5), `DAON_STUDIO_V2_USER_CONCURRENCY`, `DAON_STUDIO_V2_GLOBAL_CONCURRENCY`, `DAON_OBJECT_*`(자산 저장용, 문서 워커와 같은 파일 시크릿 방식), `DAON_PROVIDER_CREDENTIAL_KEY_FILE`.
- 루프(`run_once`): claim → `start`(generating) → `generator = registry[type_id]`(WO-F2의 생성기) → 단계별 `heartbeat` → 결과 `add_revision` + 근거 저장 + 자산 저장 → `finish(completed)`. 오류 분류: 재시도 가능(`PROVIDER_TIMEOUT`, `PROVIDER_UNAVAILABLE`, `STUDIO_DATABASE_UNAVAILABLE`, `OBJECT_STORAGE_UNAVAILABLE`) → `retry(delay 5s×2^attempt)`, 그 외 `StudioError`는 `failed`.
- `main()`은 `studio_generation_worker.main()`을 복사해 SIGTERM/SIGINT 처리·`run_forever(stop, poll)`. 플래그 `DAON_STUDIO_V2_ENABLED=false`이면 즉시 종료(코드 0).
- **Compose** `deploy/daon2-user/compose.yaml` 에 `studio-v2-worker` 추가: `build`는 `studio-worker`와 같음, `command: ["python","-m","daon2_user_api.studio_v2_worker"]`, `environment`는 위 변수, `secrets`: `object_access_key`, `object_secret_key`, `provider_credential_key`, `depends_on: object-storage(service_healthy)`, `healthcheck: disable: true`, `restart: unless-stopped`, 네트워크 `daon2_user`(+WSL 전용 Postgres는 같은 네트워크).
  - 컨테이너 상한: `mem_limit: 768m`, `cpus: 1.0`(서버 7.8 GiB 제약, 환경 E9).
- **테스트** `TESTS/test_studio_v2_worker.py`: `FakeQueue`/`FakeRepository`/`FakeGenerator`로 성공·재시도·취소·dead-letter. 플래그 off 종료.

### T1-09. HTTP 라우트 (`API/runtime.py`, 플래그 뒤)

경로는 BFF 패턴과 맞추기 위해 노트북 하위로 둔다: `/api/v1/workspaces/{workspace_id}/notebooks/{notebook_id}/studio/...`. 모든 핸들러는 `_principal` → `authorization_service.authorize_action(Action.VIEW|EDIT)` → `_require_query_keys`를 쓴다(기존 `create_studio_generation`(l.5080) 패턴). 쓰기는 `Idempotency-Key`(16~128자) 필수 + `x-daon-bff-transport: internal` 검사.

| 메서드·경로 | 권한 | 요청 | 응답 |
| --- | --- | --- | --- |
| `GET …/studio/types` | VIEW | — | `{data:{types:[{type_id,formats,presets,available,reason?,settings_schema}]}}` |
| `POST …/studio/outputs` | EDIT | `{type_id, format_id?, settings?, source_version_ids?}` (모두 선택, `extra=forbid`) | 202 `{data:{output_id,job_id,status}}`; Source가 없으면 409 `STUDIO_NO_READY_SOURCE` |
| `GET …/studio/outputs?cursor&limit` | VIEW | — | `{data:{items:[…], next_cursor}}` + `ETag` |
| `GET …/studio/outputs/{id}?revision` | VIEW | — | 상세(리비전 본문+근거) |
| `PATCH …/studio/outputs/{id}` | EDIT | `{title}` + `If-Match` | 200 |
| `DELETE …/studio/outputs/{id}` | EDIT | — | 204 |
| `POST …/studio/outputs/{id}/revisions` | EDIT | `{content, change_reason?}` | 201 |
| `POST …/studio/outputs/{id}/regenerate` | EDIT | `{settings?}` | 202 |
| `POST …/studio/outputs/{id}/cancel` | EDIT | — | 202 |
| `GET …/studio/outputs/{id}/provenance?revision` | VIEW | — | 6.5.2 형식 |
| `GET …/studio/outputs/{id}/exports/{format}?revision` | VIEW | — | 바이너리(Content-Disposition attachment, `Cache-Control: no-store`, `ETag` sha256). **승인·step-up 불필요**, `Idempotency-Key`는 선택(GET이므로 불필요, 7. 결정 D2) |
| `GET …/studio/outputs/{id}/sharing` | VIEW | — | 접근 대상(노트북 권한 기준) |
| `POST/GET …/studio/outputs/{id}/learning-attempts` | VIEW/EDIT | 본인 | |
| `GET·PUT …/customization` | VIEW/EDIT | `{instruction}` + `If-Match` | |
| `POST …/studio/memos` | EDIT | `{title?, markdown?, from_run_result_id?}` | 201 (`from_run_result_id`가 있으면 기존 질문 run의 답변과 인용을 메모로 변환) |

- `StudioError` 공개 코드 화이트리스트(`runtime.py:3211` 부근)에 T1-06의 신규 코드를 모두 추가한다. 빠지면 `INVALID_REQUEST`로 가려진다.
- 라이선스: `studio.generate` 기능은 생성 POST에서만 `license_service.require_new_generation`(기존 `runtime.py:5080` 방식) 호출.
- 감사: 생성·삭제·내보내기·이름변경에 감사 이벤트(`studio_v2.output.create|delete|export|rename`), **본문은 기록하지 않는다**(`audit_events`는 기존 `_finish` 방식 참고).
- **테스트** `TESTS/test_studio_v2_runtime_http.py`: `test_studio_workspace_runtime_http.py`(484줄) 패턴으로 `dependencies.studio_v2_service` 주입 후 상태코드·헤더·검증 오류·권한(VIEW만 있는 주체의 POST 403) 확인.

### T1-10. BFF 경로 (`apps/web/lib/bff-api-proxy.js`)

`routeFor(method, segments)`의 노트북 블록 **앞**(l.~459, 일반 4세그먼트 `workspaces/{w}/notebooks/{n}` 앞)에 길이별로 블록을 추가한다(세그먼트 수는 정확 일치).

- 6세그먼트 `workspaces/{w}/notebooks/{n}/studio/{types|outputs|memos}`·`customization`(5세그먼트)
- 7세그먼트 `.../studio/outputs/{id}`, 8세그먼트 `.../outputs/{id}/{revisions|regenerate|cancel|provenance|sharing|learning-attempts}`, 9세그먼트 `.../outputs/{id}/exports/{format}`.
- 플래그: 쓰기는 `csrfProvenanceRequired: true`; GET 목록은 `query: new Set(["cursor","limit"]), strictQuery: true`; 상세·프로비넌스·내보내기는 `query: new Set(["revision"]), strictQuery: true`; 내보내기 형식은 `docx|pdf|md|xlsx|csv|json|svg|png|pptx|mp3|wav|mp4` 화이트리스트(`SAFE_SEGMENT` 포함).
- 응답 헤더 허용 목록(`RESPONSE_HEADERS`, l.20)은 `content-disposition`, `etag` 이미 포함. 추가 불필요.
- 내보내기·큰 응답: 기본 라우트는 버퍼링이므로 **서버 측 상한 32 MiB**를 라우트 플래그 `maxResponseBytes`로 추가(새 플래그, `createBffProxy` l.1308~1372 부근 처리). 오디오·영상(Phase 3~4)에서 다시 검토.
- 기본 타임아웃 10초는 `POST outputs`(큐 삽입만)에는 충분. 내보내기 GET은 `timeoutMs: 60000`로 지정(새 플래그).
- 클라이언트: `apps/web/lib/studio-v2-api.js` 신규(WO-S1 참고). `lint-workspace.mjs` 규칙상 직접 `fetch(` 호출 금지 → `fetchImpl = fetch` 기본 인자 형식.
- **테스트** `scripts/tests/studio-v2-bff.test.mjs`: `notebook-bff.test.mjs` 패턴(`createBffProxy({baseUrl, publicOrigin, fetchImpl})`)으로 각 경로 허용·메서드 거부(405)·쿼리 위반(400)·CSRF(Referer 없음 403) 확인.

### T1-11. OpenAPI 계약

- `packages/contracts/openapi/v1/openapi.json`에 위 경로·스키마(`StudioV2Type`, `StudioV2CreateRequest`, `StudioV2Output`, `StudioV2OutputDetail`, `StudioV2Provenance`, `StudioV2Job` …) 추가.
- `scripts/verify-openapi-contract.mjs`는 Studio 경로 목록(l.76-89)·메서드 맵·요청/응답 `$ref`를 **고정**하므로 새 경로를 이 스크립트에도 등록해야 통과한다. 동시에 `evidence` 요약(R1-M5-07 레거시 요약)은 동결본이므로 새 경로는 **새 프로필**로 요약을 만들거나(권장) 레거시 요약 상수를 건드리지 않도록 경로 수 계산에 영향이 없는지 확인한다.
- 조사에서 확인된 **기존 계약 불일치**(`StudioGenerationRequest.output_type` 5종 등)는 이 작업과 별개로 두되, 새 문서에 "기존 v1 Studio 계약은 동결"이라고 명시한다.
- **완료 기준**: `npm run verify:openapi-contract` 통과.

### T1-12. 자산 저장·정리

- 내보내기 결과를 오브젝트 스토리지 영역 `output`에 저장한다(`ObjectKeyPolicy`, `object_id = sha256(tenant|workspace|output_id|revision|format)[:32]`; `_ALLOWED_AREAS={"source","output"}` 이므로 새 영역 불필요). 내보내기 요청 시 **지연 생성 후 캐시**: 같은 리비전·형식이면 저장된 자산을 반환.
- 삭제된 산출물의 자산은 워커가 주기적으로(`DAON_STUDIO_V2_CLEANUP_SECONDS` 기본 3600) 삭제(`storage.delete(key)`).
- `MinioObjectStorageAdapter.get`은 전체를 메모리로 읽는다(Range·스트리밍 없음). 상한 32 MiB(오디오·영상은 후속에서 재설계).
- 완료 기준: 내보내기 GET 두 번 → 두 번째는 저장 자산 재사용(로그/테스트로 확인), 삭제 후 객체가 정리됨.

### T1-13. stale 계산 (T1-15와 통합 구현)

`list_outputs`·`get_output` SQL에서 산출물의 최신 리비전이 참조한 각 `source_version_id`에 대해 다음 중 하나면 `stale=true`: (1) 같은 `source_id`에 더 큰 `source_versions.version`이 존재, (2) `notebook_source_unbindings`에 해제됨, (3) `deletion_requests.source_active=false`. 저장하지 않고 조회 시 계산한다(조사 §4 권고). 완료 기준: 단위 테스트(가짜 연결 SQL 응답) + WSL에서 Source 새 버전 등록 후 `stale` 전환 확인(ST-T09).

### T1-14. 맞춤설정·노트북 복사·채팅 기록(F3)

- 맞춤설정 저장소는 T1-03의 `workspace_studio_v2_customization`(ETag `"studio-v2-customization:{nb}:{version}"`). 생성기가 시스템 지시문 뒤에 사용자 지시문을 붙인다(WO-F2 T2-05). 채팅 적용은 `QuestionAnsweringService` 프롬프트 빌더에 동일 지시문을 주입하는 작업을 **별도 항목 F3-01b**로 분리(채팅 어댑터 `provider_payload` 클래스메서드 수정 필요).
- 노트북 복사(F3-02)는 WO-F1 범위 밖의 큰 작업이므로 `docs/work_orders/WO-F3-notebook-menu.md`(후속 작성)에서 다룬다. 여기서는 T1-01의 삭제 결정과 `studio_v2_*`의 `output_id` 재발급 규칙(복사본은 새 ID)만 고정한다.
- 채팅 기록 개인 범위(F3-03)는 현재 질문·답변이 노트북 `conversation_thread` 바인딩으로 노트북 공유 범위에 노출되는 구조이므로 **설계 변경이 필요**하다. 조사 후 별도 WO로 분리한다.

### T1-16. v2 근거 콘텐츠 엔드포인트 (UI 근거 보기용)

- **경로**: `GET /api/v1/workspaces/{ws}/notebooks/{nb}/studio/outputs/{id}/evidence/{ref_id}/content?revision` (BFF 동일 경로, 9세그먼트).
- **동작**: `studio_v2_evidence`에서 `ref_id`의 `source_version_id`·`evidence_span_id`·`locator_kind/value`를 찾아, 기존 `PostgresQuestionAnsweringRepository.read_citation_content`(`API/question_answering_postgres.py:894`)·`read_citation_pdf`(l.847)와 **같은 원문 읽기 로직**으로 반환한다. 로직이 `citation_id`에 묶여 있으면 `evidence_span_id` 기반 공통 함수로 추출한다(기존 테스트 `test_question_answering_postgres.py` 유지).
- **응답 형식·헤더**: 질문 인용과 동일 — PDF는 `application/pdf`(+`#page`는 클라이언트), DOCX/PPTX/오디오/시트는 JSON(각 `validate*Content`가 통과하는 형태, 크기 상한 32 KB/256 KB), 이미지는 원본 + `x-citation-region`. `x-citation-locator-kind`, `x-citation-page`는 `RESPONSE_HEADERS`에 이미 있다.
- **권한**: 노트북 VIEW + Source 접근 재확인(삭제·해제된 Source는 404 `RESOURCE_UNAVAILABLE`).
- **MCP 근거**(`origin != notebook_source`)는 저장된 불변 스냅샷(`external_ref`)을 JSON으로 반환(WO-M0 T-M0-08).
- **테스트**: `TESTS/test_studio_v2_evidence_content.py`(형식별 응답·권한·삭제된 Source), BFF 테스트에 경로 추가.

### T1-15. 알림

1차에서는 산출물 완료 알림을 만들지 않는다(기존 알림 SQL(0069)이 `studio_job` 상태를 하드코딩). 후속.

---

## 2. 의존 관계·순서

```text
T1-01(스파이크) ─┐
T1-02(플래그) ───┼→ T1-03(마이그레이션) → T1-04(준비 검사, 같은 커밋) → T1-05(유형) → T1-06(저장소) → T1-07(큐) → T1-08(워커)
                 │                                                    ↓
                 └────────────────────────────────────────────→ T1-09(라우트) → T1-10(BFF) → T1-11(OpenAPI) → T1-12·13
```

- **병행 가능**: T1-05는 T1-03과 병행, T1-10은 T1-09의 계약이 정해지면 병행.
- **이 WO의 종료 기준(Phase 0 backend)**: `DAON_STUDIO_V2_ENABLED=true` 로 WSL에 배포했을 때 (1) `/health/ready` 200, (2) `POST …/studio/outputs`가 202와 `job_id`를 반환, (3) 생성기가 없는 유형(예: `report`의 스텁 생성기)에 대해 작업이 `completed`/`failed`로 종결, (4) 목록·상세·이름변경·삭제·취소가 동작, (5) 위 모든 테스트와 `verify:api-cloud`, `verify:openapi-contract`, `verify:independence`, `verify:public-repository-boundary` 통과. 스텁 생성기는 WO-F2에서 실제 생성기로 교체한다.

## 3. 검증 명령 모음

```bash
# 로컬 (서비스 디렉터리에서)
cd services/api && PYTHONPATH=src uv run --frozen pytest -q -p no:cacheprovider \
  tests/test_studio_v2_settings.py tests/test_studio_v2_types.py tests/test_studio_v2_migration.py \
  tests/test_studio_v2_repository.py tests/test_studio_v2_queue.py tests/test_studio_v2_worker.py \
  tests/test_studio_v2_runtime_http.py tests/test_cloud_storage.py
node --test scripts/tests/studio-v2-bff.test.mjs
npm run verify:openapi-contract && npm run verify:independence && npm run verify:public-repository-boundary
# WSL (실 DB): 마이그레이션 + 준비 검사 + 실DB 테스트
DAON_STUDIO_V2_TEST_DSN=... PYTHONPATH=src uv run --isolated --with pytest==9.0.3 --with 'psycopg[binary,pool]==3.3.4' python -m pytest tests/test_studio_v2_repository.py -q
```

## 4. 위험과 대응

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| 0074 적용 후 준비 검사 누락 수정 | API 503 | T1-04를 마이그레이션과 같은 커밋으로 묶고, WSL에서 `/health/ready` 확인을 완료 기준에 포함 |
| 노트북 삭제 경로가 v2 테이블을 모름 | 삭제 실패/고아 | T1-01 스파이크로 먼저 확인 |
| RLS 정책 오류로 워커가 행을 못 봄 | 작업 정지 | 워커도 `_transaction(context)`로 GUC 설정, 실DB 테스트로 확인 |
| 기존 `StudioError` 화이트리스트에 코드 누락 | 오류가 `INVALID_REQUEST`로 표시 | 라우트 테스트에서 각 코드의 공개 응답 단언 |
| 하트비트 없는 긴 생성 | 이중 실행 | T1-07 heartbeat 필수, 생성기 단계마다 호출 |
| `uv`·Python 3.14.3 고정 | 새 의존성 도입 지연 | 이 WO는 새 라이브러리를 도입하지 않는다 |
