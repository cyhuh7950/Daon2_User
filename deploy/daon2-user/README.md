# Daon2-User 운영 Web/API Compose

기존 `deploy/r1-m5-01`·`deploy/r1-m5-02` 검증 Compose와 분리된 운영 앱 패키지다. Web 컨테이너 포트는 `3330`이고 호스트 공개 포트는 `DAON_WEB_HOST_PORT`(WSL 테스트 `3340`)이며 Web/API는 전용 Compose network와 API runtime volume을 사용하고 외부 `proxy-network`에 연결한다.

브라우저 요청은 Web의 same-origin BFF가 처리하며 `DAON_API_INTERNAL_URL`은 서버 환경변수로만 주입한다. Upstage 및 객체 저장소 자격은 파일 secret reference로만 주입한다. `DAON_CLOUD_DATABASE_DSN`, Gateway URL, trusted proxy IP, object-storage endpoint/bucket과 세 secret 파일은 배포자가 제공해야 한다. 기존 공용 자원은 변경하지 않는다.

## ysna-server 배포(2026-10-27~)

- 소스: `https://github.com/cyhuh7950/Daon2_User` (main). 서버 경로 `~/deploy/daon2-user`, Compose 프로젝트 `daon2_user`(기존 `daon_user`와 분리).
- 최초: `DAON_GATEWAY_URL=https://daon2-user.sinsan.kr bash deploy/daon2-user/ysna-bootstrap.sh` (secrets·.env 생성, Provider 키는 같은 서버의 `~/deploy/daon-user/.env`에서 읽음)
- 배포·갱신: `git pull && bash deploy/daon2-user/ysna-deploy.sh` (uv가 없어 Docker로 alembic 실행, 마이그레이션 head까지)
- 웹은 호스트 3340 → 컨테이너 3330. nginx-proxy-manager 전달 대상은 `daon2-user-web`:`3330`(Docker 별칭, 컨테이너 포트).
- 첫 로그인: `admin` / `admin` (첫 로그인에서 비밀번호 변경).

## 새 설치용 초기 데이터(seed)

- `deploy/daon2-user/seed/provider-seed.sql`: Provider 연결 12개·허용 모델 35개·그 모델의 카탈로그 행(Key·암호문·확인 상태 없음, 모두 `unverified`). 설치 후 관리자가 각 Provider에 Key를 넣고 연결 시험을 한다.
- 적용: `bash deploy/daon2-user/seed/load-provider-seed.sh` (연결이 하나라도 있으면 건너뜀). `ysna-deploy.sh`가 마이그레이션 직후 자동 실행한다.
- 갱신: 기준 DB에서 `bash deploy/daon2-user/seed/export-provider-seed.sh [컨테이너] > deploy/daon2-user/seed/provider-seed.sql`
- 계정·노트북·소스·정책(조직·Workspace 외부 전송 정책)은 시드에 없다. 첫 로그인은 `admin`/`admin`이고, 외부 전송 정책은 화면에서 설정한다(허용 목적지 등).


### 초기 데이터 범위(새 설치)

| 항목 | 방식 |
| --- | --- |
| Provider | `seed/provider-seed.sql`(연결 12·모델 35, Key 없음). 마이그레이션 직후 자동 적용 |
| 조직 외부 전송 정책 | `seed/initial_policy.py`: 시드된 차단 정책인 조직·Workspace만 "추가 인증 없이 허용"(external_api·server_internal·local_runtime, 허용 목적지 4곳, 1 MiB, 마스킹·삭제 필수)로 올림. 이미 저장된 정책은 건드리지 않음 |
| 화면 설정 | `seed/initial_screen.py`: admin의 테마 초기값(기본 system, `SEED_SCREEN_THEME`로 변경). 이미 저장돼 있으면 건드리지 않음 |
| 음성(TTS) 엔진 | `seed/apply-initial-tts.sh`: supertonic 1개(주소·보이스 F1/M1·선택지, 기본 엔진, Key 없음·`unverified`)를 화면 등록 엔진으로 넣음. 배포 설정 파일에 엔진이 있거나 이미 등록된 엔진이 있으면 건드리지 않음. 설치 후 관리자가 설정 → 음성 엔진에서 Key를 넣고 연결 확인 |
| 라이선스 | 서명된 라이선스는 시드로 만들 수 없다. 개발 단계(`DAON_DEVELOPMENT_STAGE=true`, 이 오버레이가 설정)에서는 라이선스 없이 전 기능 사용. 운영 전환 시 화면에서 라이선스 파일 적용 |
| 사용자 설명서 | 웹 이미지에 포함(`/manual/daon-user-manual.pdf` 등). 별도 데이터 없음 |
| admin 계정 | 앱이 첫 기동 때 `admin`/`admin`(첫 로그인 비밀번호 변경)으로 만든다. 시드에 비밀번호·해시를 넣지 않는다 |

적용: `bash deploy/daon2-user/seed/apply-initial-data.sh admin` (`ysna-deploy.sh`가 배포 끝에 자동 실행).
