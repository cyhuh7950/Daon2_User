# Daon2-User WSL-server 첫 배포 기록 (2026-10-20)

| 항목 | 내용 |
| --- | --- |
| 배포 소스 | `main` 커밋 `683d2338` (서버 `~/deploy/daon2-user/.deployed-sha`) |
| 방식 | 로컬 `git -c core.autocrlf=false archive` → ssh tar (서버에서 git 미사용). 반드시 LF 기준 |
| Compose | 프로젝트 `daon2_user`, `compose.yaml` + `compose.wsl-dedicated-postgres.yaml`, `.env`는 서버 전용 |
| 서비스 | web(호스트 3340→3330), api, document-worker, studio-worker, object-storage, **postgres(전용, 127.0.0.1:5436)** |
| DB | 전용 Postgres(pgvector 0.8.2 PG15), DB `daon2_user`, 앱 역할 `daon_app`, Alembic `0073 (head)` |
| 헬스 | `GET /health/ready` → 200 `ready`, 웹 `/` 200, `/settings/manual` 200, 미인증 `/bff/api/session` 401 |
| 기존 스택 영향 | `daon_user-*`, Daon2, Daon2-RAG 컨테이너·공유 `local-postgres` 변경 없음(정리 대상은 이번 작업에서 만든 DB 1개·역할 5개·컨테이너뿐) |

## 이번 배포에서 확정한 사실 (재발 방지)

1. **공유 Postgres 불가**: 마이그레이션이 만드는 DB 함수 본문의 MD5(111개)가 코드에 고정되어 있어, 역할 이름(`daon_app`, `daon_notebook_delete`, `daon_account_owner`, `daon_organization_owner`)이나 호스트 라벨(`wsl-server-daon-user`)을 바꾸면 준비 검사가 실패한다. 이름은 원본을 유지하고 **클러스터를 분리**한다.
2. **줄바꿈은 LF 고정**: Windows `git archive`는 CRLF로 내보내 SQL 본문 해시가 어긋난다. `.gitattributes`에 `eol=lf`를 고정했고 배포 시 `-c core.autocrlf=false`를 쓴다.
3. **마이그레이션 순서**: 0040까지 앱 역할(`daon_app`), 이후 superuser(`postgres`). 끝나면 `identity_auth_admin_role_operations`, `identity_session_tenant_switch_outbox` 소유자를 `daon_app`으로 맞춘다. `deploy/daon2-user/wsl-bootstrap-db.sh`가 이 순서를 구현한다.
4. **Windows 쪽 독립성 정책**: `daon2-user` 식별자를 자기 자신으로 허용하도록 `independence-check.mjs`를 수정했다.

## QA 계정과 로그인 E2E (2026-10-20, HTTP 수준)

| 단계 | 결과 |
| --- | --- |
| 초기 관리자 `admin` | API 시작 시 자동 생성(`initial_admin_v1`), 변경하지 않음 |
| QA 계정 `qa-e2e` | 서버 콘솔 방식으로 생성·승인(`active`), 비밀번호는 서버 `secrets/qa_e2e_password`(600)에만 보관 |
| 로그인 | `POST /bff/api/auth/login` 200 |
| 강제 비밀번호 변경 | 세션 `password_change_required=true` → `POST /bff/api/auth/password/change` 200 (Origin·Referer 필요) |
| 재로그인·세션 | 200, `password_change_required=false`, workspace 할당됨 |
| Notebook 홈 | `GET /bff/api/workspaces/{id}/notebooks` 200(빈 목록), `GET /notebooks` 200 |

브라우저 UI 클릭 E2E는 아직 수행하지 않았다(로그인 화면 렌더링만 확인). 절차 스크립트는 `deploy/daon2-user/qa/`.

## 미확인·미수행

- 전체 품질 게이트(`verify:quality-gate`)는 로컬에서 170초 내 끝나지 않아 실행 완료를 확인하지 못했다.
- 브라우저 UI 로그인 E2E(클릭 흐름)는 수행하지 않았다. 자가 가입의 이메일 인증은 SMTP 미설정으로 불가하며 관리자 생성 경로를 쓴다.
- 컨테이너 CPU·메모리 상한(E9)은 postgres(1 GiB)만 설정했다.
- 로컬 API 전체 pytest와 Postgres 통합 테스트는 실행하지 않았다.
