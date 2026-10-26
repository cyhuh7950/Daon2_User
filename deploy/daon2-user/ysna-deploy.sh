#!/usr/bin/env bash
# ysna-server 배포(멱등): DB 준비 → 마이그레이션 → 빌드·기동 → 헬스 확인. ~/deploy/daon2-user 에서 실행한다.
# 사전: ysna-bootstrap.sh 로 secrets/.env 준비. uv 가 없어 uv-docker-shim.sh 를 쓴다.
# 사용: bash deploy/daon2-user/ysna-deploy.sh [서비스...]   (기본: api web studio-v2-worker document-worker studio-worker)
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
export UV_BIN="$ROOT/deploy/daon2-user/uv-docker-shim.sh"
export DAON_COMPOSE_OVERLAY=compose.ysna.yaml
COMPOSE=(docker compose --env-file .env -f deploy/daon2-user/compose.yaml -f deploy/daon2-user/compose.ysna.yaml)
chmod +x deploy/daon2-user/*.sh

echo "[0/4] 전용 PostgreSQL 기동"
"${COMPOSE[@]}" up -d postgres 2>&1 | tail -n 3
for _ in $(seq 1 40); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' daon2_user-postgres-1 2>/dev/null)" = healthy ] && break
  sleep 3
done
if [ "$(docker exec daon2_user-postgres-1 psql -U postgres -qAt -d postgres -c "SELECT 1 FROM pg_database WHERE datname='daon2_user'")" != 1 ]; then
  echo "[1/4] DB 최초 생성(부트스트랩)"
  bash deploy/daon2-user/wsl-bootstrap-db.sh
fi
bash deploy/daon2-user/wsl-deploy.sh "$@"
