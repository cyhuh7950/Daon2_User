# Daon2-User 운영 Web/API Compose

기존 `deploy/r1-m5-01`·`deploy/r1-m5-02` 검증 Compose와 분리된 운영 앱 패키지다. Web 컨테이너 포트는 `3330`이고 호스트 공개 포트는 `DAON_WEB_HOST_PORT`(WSL 테스트 `3340`)이며 Web/API는 전용 Compose network와 API runtime volume을 사용하고 외부 `proxy-network`에 연결한다.

브라우저 요청은 Web의 same-origin BFF가 처리하며 `DAON_API_INTERNAL_URL`은 서버 환경변수로만 주입한다. Upstage 및 객체 저장소 자격은 파일 secret reference로만 주입한다. `DAON_CLOUD_DATABASE_DSN`, Gateway URL, trusted proxy IP, object-storage endpoint/bucket과 세 secret 파일은 배포자가 제공해야 한다. 기존 공용 자원은 변경하지 않는다.

## ysna-server 배포(2026-10-27~)

- 소스: `https://github.com/cyhuh7950/Daon2_User` (main). 서버 경로 `~/deploy/daon2-user`, Compose 프로젝트 `daon2_user`(기존 `daon_user`와 분리).
- 최초: `DAON_GATEWAY_URL=https://daon2-user.sinsan.kr bash deploy/daon2-user/ysna-bootstrap.sh` (secrets·.env 생성, Provider 키는 같은 서버의 `~/deploy/daon-user/.env`에서 읽음)
- 배포·갱신: `git pull && bash deploy/daon2-user/ysna-deploy.sh` (uv가 없어 Docker로 alembic 실행, 마이그레이션 head까지)
- 웹은 호스트 3340 → 컨테이너 3330. nginx-proxy-manager 전달 대상은 `daon2-user-web`:`3330`(Docker 별칭, 컨테이너 포트).
- 첫 로그인: `admin` / `admin` (첫 로그인에서 비밀번호 변경).
