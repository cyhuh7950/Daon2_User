# Daon2-User 개발·테스트 환경

| 항목 | 내용 |
| --- | --- |
| 문서 버전 | 0.1 초안 (2026-10-20) |
| 상태 | 확인된 사실과 **제안값**을 구분해 기록. 제안값은 신산님 확정 전까지 적용하지 않음 |
| 기준 설계서 | `docs/daon2-user-studio-design.md` |
| 이전 문서 | daon-user의 환경 문서는 `Backup/docs/DEVELOPMENT_ENVIRONMENT.md`에 원문 보존 (참조 전용, 수정하지 않음) |
| 비밀 | 이 문서에는 Secret·키·토큰 값을 기록하지 않는다. 경로와 이름만 기록한다. |

표기: **[확인]** 2026-10-20 실제 확인한 사실 · **[제안]** 확정 전 제안 · **[미정]** 결정 필요

---

## 1. 개발 방식

| 구분 | 규칙 |
| --- | --- |
| 개발 | 로컬(Windows)에서만 코드를 수정한다. |
| 테스트 | WSL-server `~/deploy/daon2-user`에 배포해서 진행한다. 서버에서 코드를 직접 수정하지 않는다. |
| 배포 소스 | 로컬에서 커밋·푸시한 Git 커밋을 서버가 가져와서(`git fetch` → exact commit checkout) 사용한다. Windows에서 파일을 복사하지 않는다. |
| 검증 | 로컬 단위·계약 테스트 통과 → 서버 배포 → 서버 통합·E2E 테스트 |
| 완료 판정 | 로컬 테스트 통과만으로 기능 완료로 보지 않는다. 서버 배포 검증 기록이 있어야 한다. |

---

## 2. 저장소

| 항목 | 내용 |
| --- | --- |
| 개발 저장소 | `git@github-sinsan-develop:sinsan-develop/Daon2_User.git` (HTTPS: https://github.com/sinsan-develop/Daon2_User) |
| SSH 별칭 | `~/.ssh/config`의 `Host github-sinsan-develop` (키 `~/.ssh/sinsan-develop`, `IdentitiesOnly yes`) |
| 참조 원본 | `D:\Project\Daon2_User\Backup` (daon-user의 `docs`, `apps`). **읽기 전용**, 수정·커밋하지 않음 |
| 기본 브랜치 | [미정] 원격 저장소가 비어 있음(2026-10-20 확인). 첫 푸시로 결정 |
| 브랜치 규칙 | [제안] `master` 보호, 작업은 `feature/<주제>` 또는 `claude/<주제>` 브랜치 + PR |
| 커밋 메시지 | [제안] `type: 요약` (feat/fix/test/docs/chore) |

---

## 3. 로컬 개발 환경 (Windows)

### 3.1 툴체인 [확인]

로컬 설치 버전은 daon-user의 `toolchain-versions.json` 기준선과 일치한다.

| 도구 | 버전 | 용도 |
| --- | --- | --- |
| Node.js | 24.22.1 | Web, Desktop 프론트엔드 빌드, 스크립트 |
| npm | 11.19.1 | npm workspaces (`apps/*`, `packages/*`) |
| Python | 3.14.3 | API·로컬 서비스 |
| uv | 0.11.2 | Python 의존성(`services/api`, `services/local-service`) |
| Git | 2.53.0 (Windows) | |
| Rust | 1.97.1 (`rust-toolchain.toml`) | Desktop(Tauri, **후속 Phase**). 현재 로컬 PATH에 `cargo` 없음 → Desktop 착수 전 설치 |
| Docker | 로컬 미설치 | 컨테이너 빌드·실행은 WSL-server에서 수행 |

### 3.2 프레임워크 기준선 (daon-user 계승) [제안]

| 항목 | 버전 |
| --- | --- |
| Next.js | 16.4.3 |
| React | 19.2.8 |
| TypeScript | 7.0.2 |
| React Native | 0.86.3 |
| Tauri CLI | 2.11.4 |
| PostgreSQL | 18.4 (서버) |

신규 설계(Studio·MCP)가 요구하는 추가 의존성(MCP 클라이언트 SDK, PPTX·DOCX 생성, TTS 등)은 도입 시점에 이 표에 추가하고 버전을 고정한다.

### 3.3 저장소 구조 [제안: daon-user 구조 계승]

```text
apps/web            Next.js 웹 (핵심 사용자 경로)
apps/desktop        Tauri Windows 앱
apps/mobile         React Native (Phase 후속)
apps/evidence-hub   내부 검증 증거 도구 [미정: 계승 여부]
packages/contracts  OpenAPI·화면·내비게이션 계약
packages/design-tokens
packages/ui         Web·Desktop 공용 DOM UI
services/api        Python API, Worker (Alembic)
services/local-service  Desktop 로컬 서비스 (후속 Phase)
services/mcp-virtual    가상 MCP 서버 (Daon2-RAG·Daon2 대역, 개발·QA 전용, 설계서 §7A.10)
packages/mcp-contract-tests  실제·가상 MCP 서버 공통 계약 시험
deploy/             Compose 파일
docs/               설계서·계획서·환경 문서
```

### 3.4 로컬 명령

| 목적 | 명령 |
| --- | --- |
| 의존성 설치 | `npm ci` · `uv sync` (각 service 디렉터리) |
| 툴체인 검증 | `npm run verify:toolchain` |
| 웹 개발 서버 | `npm run dev --workspace @daon-user/web` (패키지명은 rename 전 기준, §8) |
| 워크스페이스 린트·테스트 | `npm run lint:workspace`, `npm run verify:workspace` |
| 품질 게이트 | `npm run verify:quality-gate` |

로컬에서는 외부 서비스(PostgreSQL, 객체 저장소, 모델)가 없어도 실행 가능한 단위·계약 테스트를 우선한다. DB·큐가 필요한 테스트는 서버에서 수행한다.

---

## 4. 테스트 서버 (WSL-server)

### 4.1 접속 [확인]

| 항목 | 내용 |
| --- | --- |
| SSH 별칭 | `WSL-server` |
| 호스트 | `172.27.253.53`, 포트 22, 사용자 `daon` |
| 키 | `C:\Users\cyhuh\.ssh\WSL_server.key` (경로만 기록) |
| 호스트명 | `SINSAN` |
| 접속 확인 | `ssh WSL-server hostname` |

### 4.2 서버 사양 [확인]

| 항목 | 값 |
| --- | --- |
| OS | Ubuntu 24.04.3 LTS (WSL2, 커널 6.18.54.1-microsoft-standard-WSL2) |
| CPU | 6 코어 |
| 메모리 | 총 7.8 GiB, 확인 시점 가용 약 3.7 GiB |
| 디스크 | `/` 1007 GB 중 428 GB 사용(45%) |
| GPU | `nvidia-smi` 없음. GPU 사용 가능 여부 [미확인] |
| Docker | 29.1.3, Compose v5.1.1 |
| Python | 3.12.3 (호스트 기본). 앱 런타임은 컨테이너 이미지 기준 |
| Node | v24.21.0 (호스트 기본) |

> 메모리가 여유롭지 않다. 같은 호스트에서 daon2, daon2-rag, daon-user, Ollama(11434) 등이 동시에 동작하므로 daon2-user 컨테이너의 CPU·메모리 상한을 Compose에 명시한다. 이미지 빌드·대량 생성 테스트는 다른 서비스 영향을 확인하며 진행한다.

### 4.3 배포 위치 [확인]

| 항목 | 내용 |
| --- | --- |
| 경로 | `/home/daon/deploy/daon2-user` |
| 현재 상태 | 2026-10-20 확인 시 **비어 있음**(디렉터리만 생성) |
| 이웃 디렉터리 | `daon-user`(기존 QA, 포트 3330), `daon-user-r1-9522dc2c`, `daon2`, `daon2-rag`, `daon3` 등 |
| 규칙 | 다른 프로젝트 디렉터리(`daon-user` 등)는 **사용·수정·덮어쓰기 금지**. daon2-user는 자기 디렉터리 안에서만 동작 |

### 4.4 현재 동작 중인 관련 서비스 [확인]

| 컨테이너 | 포트 | 비고 |
| --- | --- | --- |
| `daon2-rag-api` | 8040(내부) | **MCP 서버 `/mcp` 제공**, Daon2-User의 지식 소스 |
| `daon2-rag-web` | 172.27.253.53:8660 | |
| `daon2-api`, `daon2-web` | 내부 / 8670 | Daon2 |
| `daon2-ontology-graph-worker` | 내부 | 온톨로지 |
| `daon_user-*` (api, web, workers, object-storage) | web 3330 | 기존 daon-user QA. **분리 대상** |
| `local-postgres` | 5432 | 공유 PostgreSQL |
| `npm`(Nginx Proxy Manager) | 80/81/443 | 리버스 프록시 |
| `open-webui`, `bareun`, Ollama | 8080, 5656·9902, 11434 | 기타 |

사용 중인 호스트 포트(확인 시점): 22, 53, 80, 81, 443, 2222, 3330, 5432, 5656, 6379, 8080, 8642, 8660, 8670, 9902, 11434, 41805, 61209.

---

## 5. 서버 배포 구성 [제안]

daon-user의 `deploy/daon-user/compose.yaml`, `compose.wsl-postgres.yaml` 패턴을 계승하되 이름·포트·DB·볼륨을 분리한다.

| 항목 | 제안값 | 사유 |
| --- | --- | --- |
| Compose 프로젝트 | `daon2_user` | 컨테이너 `daon2_user-web-1` 등. `daon2-*`(Daon2), `daon_user-*`(기존)와 구분 |
| Web 포트 | **3340** | 사용 목록에 없음. 3330은 기존 daon-user |
| API | 내부 8000 (호스트 미공개) | BFF가 같은 Compose 네트워크로 접근 |
| 서비스 | `web`, `api`, `studio-worker`, `document-worker`, `object-storage`, **`mcp-virtual`**(QA 전용) | daon-user 구성 계승 + 가상 MCP. 작성 워커(Authoring)는 Phase A1에서 추가 검토 |
| 네트워크 | `daon2_user_network` (내부), 외부 연결은 아래 참조 | |
| 볼륨 | `daon2_user_api_runtime`, `daon2_user_object_storage` | 기존 daon_user 볼륨과 이름 분리 |
| DB | **daon2_user 전용 PostgreSQL 컨테이너**(`daon2_user-postgres-1`, pgvector 0.8.2 PG15, 공유 `local-postgres`와 분리), DB `daon2_user`, 앱 역할 `daon_app`. 관리 포트는 **`127.0.0.1:5436` 한정**(`DAON_DB_ADMIN_HOST_PORT`) | 2026-10-20 결정·적용. 공유 클러스터에서는 DB 함수 본문의 MD5 고정값 111개가 역할 이름 변경으로 어긋나 준비 상태 검사가 실패하므로 원래 역할 이름(`daon_app` 등)을 유지하고 클러스터를 분리했다. 스키마·RLS는 Alembic으로 관리 |
| 설정 | `/home/daon/deploy/daon2-user/.env` (Git 제외), 비밀은 `secrets/` 디렉터리 read-only 마운트 | 값은 문서·로그에 출력하지 않음 |
| 이미지 태그 | 배포 커밋 SHA 앞 8자 | 롤백·추적 |

### 5.1 MCP 연동 네트워크 [제안]

- **당분간 가상 MCP 서버(`mcp-virtual`, `daon2_user_network` 내부)에 연결**한다(2026-10-20 결정). Daon2-RAG·Daon2의 MCP가 준비되면 Connector 엔드포인트만 교체한다.
- 실제 Daon2-RAG 연결 시 API 컨테이너를 `daon2-rag-network`에 연결해 `daon2-rag-api:8040/mcp`를 호출한다. 호스트 포트를 새로 열지 않는다. 단, Daon2-RAG의 문서 RAG MCP는 현재 기본 OFF·미인수 상태이므로 활성화는 수신측 절차를 따른다(요청 설계서 R-RAG-01).
- 호출은 서비스 신원 인증을 거친다. 사용자 권한 전달 방식은 미정(설계서 §16-17, 요청 R-RAG-08·R-D2-08).
- 운영 환경에서는 가상 서버 Connector 등록을 거부한다.
- 외부 인터넷 호출(법령 API 등)은 기본 비활성, 환경 변수 플래그로 명시 활성화한다(daon-user의 `DAON_OPEN_LAW_ENABLED` 방식 계승).

### 5.2 프록시·접근 [미정]

- 브라우저 접근을 `http://172.27.253.53:3340` 직접으로 할지, Nginx Proxy Manager 도메인으로 할지 결정이 필요하다.

---

## 6. 배포 절차 [제안]

1. **로컬**: 테스트 통과 → 브랜치 커밋 → `git push`
2. **서버 가져오기**: `ssh WSL-server "cd ~/deploy/daon2-user && git fetch origin && git checkout --detach <SHA>"`
   - 최초에는 `git clone git@github-sinsan-develop:sinsan-develop/Daon2_User.git ~/deploy/daon2-user` (서버에서 같은 SSH 별칭·키 설정 필요, [미정])
3. **사전 기록**: 현재 실행 이미지 ID, checkout SHA, DB revision을 기록
4. **DB 백업**: 마이그레이션이 있으면 `daon2_user` DB의 custom-format dump를 `~/deploy/daon2-user-backups/<일자-SHA>/`에 mode 600으로 저장하고 SHA-256을 기록
5. **빌드·기동**: `docker compose -p daon2_user -f deploy/daon2-user/compose.yaml -f deploy/daon2-user/compose.wsl-postgres.yaml up -d --build`
6. **마이그레이션**: Alembic upgrade head
7. **헬스 확인**: `/health/ready`, 웹 3340 HTTP, same-origin BFF
8. **검증**: §7 시험 수행, 결과·SHA·이미지 digest·DB revision을 기록
9. **롤백**: 이전 이미지·SHA로 복귀. DB는 additive 마이그레이션을 유지하고, 덤프 복원은 이후 쓰기 손실을 별도 확인·승인한 경우에만 수행

배포 스크립트(`scripts/deploy-wsl.sh` 등)로 자동화하는 것은 첫 배포 이후에 [제안]한다.

---

## 7. 테스트 계층

| 계층 | 위치 | 예 |
| --- | --- | --- |
| 단위 | 로컬 | JS `node --test`, Python `pytest`, Rust `cargo test` |
| 계약 | 로컬 | OpenAPI 계약(`verify:openapi-contract`), 콘텐츠 JSON 스키마, MCP Contract v0 시험(`packages/mcp-contract-tests`) |
| 통합 | WSL-server | PostgreSQL·객체 저장소·큐·워커·MCP(가상 서버 → 준비되는 대로 실제 Daon2-RAG·Daon2) |
| E2E | WSL-server | 브라우저로 로그인 → Notebook → Source → Studio 생성 → 뷰어·다운로드 |
| 설계 검수 | WSL-server | `docs/daon2-user-studio-design.md` §14 시나리오 ST-T01~T27, 품질은 합성 코퍼스 + 수동 평가(§14.2) |

### 7.1 QA 계정과 데이터

- QA 전용 계정은 `qa-` 접두어를 쓰고 정식 Identity 흐름으로 만든다. 실제 사용자 계정의 비밀번호·세션·권한은 변경하지 않는다.
- QA용 Source·지식 컬렉션은 합성 데이터를 우선한다. 실제 업무 문서를 쓰려면 사용 범위를 별도 확인한다.
- 외부 유료 Provider(LLM·TTS 등) 호출은 **비용 승인 후**에만 한다. 기본은 로컬 모델(Ollama) 또는 모의(mock) Provider.

---

## 8. daon-user에서 이어받는 이름과 변경 대상

**결정(2026-10-20): daon-user 소스(`Backup/apps` 등)를 새 저장소로 복사한 뒤 이름을 daon2-user로 일괄 변경한다.** 시점은 첫 기능 개발 전, 별도 커밋이다. 아래 표는 변경 대상 목록이며 구체적 새 이름(`@daon2-user/*`, `daon2_user_api` 등)은 rename 작업 계획에서 확정한다.

| 위치 | 현재 이름 |
| --- | --- |
| npm 패키지 | `@daon-user/web`, `desktop`, `mobile`, `evidence-hub`, `contracts`, `design-tokens`, `ui` |
| Python | `daon_user_api`, `daon_user_local_service` |
| Desktop sidecar | `daon-user-local-service` |
| 환경 변수 | `DAON_*` 접두어 다수 |
| Compose·컨테이너 | `daon_user` |

rename은 대규모 기계적 변경이므로 **첫 기능 개발 전에 한 번에, 별도 커밋**으로 수행하는 것을 권고한다.

---

## 9. 보안·운영 원칙

1. Secret(키·토큰·비밀번호·DB 접속 문자열)은 문서·로그·커밋·채팅에 출력하지 않는다.
2. `.env`, `secrets/`는 Git에서 제외한다.
3. 서버의 다른 프로젝트 디렉터리·컨테이너·볼륨·DB는 변경하지 않는다. 대상은 `daon2_user` 이름의 자원만이다.
4. 서버 작업 전 읽기 전용 확인(상태·포트·디스크)을 먼저 한다.
5. 파괴적 작업(볼륨 삭제, DB drop, `docker system prune`)은 신산님 명시 승인 후 수행한다.
6. 배포·검증 결과는 SHA·이미지 digest·DB revision과 함께 `docs/04_test_reports/`에 기록한다.

---

## 10. 열린 항목

| # | 항목 | 비고 |
| --- | --- | --- |
| E1 | 원격 저장소 기본 브랜치와 브랜치·PR 규칙 | §2 |
| E2 | Web 포트 3340 확정, 직접 접근 vs 프록시 도메인 | §5, §5.2 |
| E3 | 서버에서 Git 가져오는 방식(서버용 deploy key 등록) | §6 |
| E4 | ~~DB·역할 생성 절차~~ 해소: 전용 Postgres 컨테이너, 마이그레이션은 0040까지 앱 역할로, 이후 superuser로 실행(수동 보정 없음) | §5 |
| E5 | rename 시점은 확정(첫 기능 개발 전 별도 커밋). 새 이름 규칙·범위(환경 변수 `DAON_*` 포함 여부) 확정 필요 | §8 |
| E6 | 로컬 Rust 툴체인 설치 여부 — Desktop은 후속 Phase(1차 Web만)이므로 **당장 불필요** | §3.1 |
| E7 | GPU 유무 확인. **오디오·영상은 로컬(WSL) 오픈소스 TTS로 결정**(2026-10-20)되어 GPU 유무·메모리(7.8 GiB)가 Phase 3 모델 선정의 전제가 됨 | §4.2 |
| E8 | 생성 LLM은 기존 Provider 라우터 재사용(결정). 기본 로컬 Ollama 모델명, 외부 Provider 허용 범위 | §7.1 |
| E9 | 서버 메모리(7.8 GiB) 한계 대응: 동시 생성 한도는 사용자당 2·서비스 전체 4로 결정. 컨테이너별 CPU·메모리 상한값 확정 필요 | §4.2 |
| E10 | CI(GitHub Actions) 도입 여부와 범위 | |
