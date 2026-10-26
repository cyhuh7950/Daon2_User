#!/usr/bin/env bash
# daon2_user 전용 DB를 head까지 올린다(superuser 실행). 기존 DB 보존. ~/deploy/daon2-user 에서 실행.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
PG=${DAON_DB_CONTAINER:-daon2_user-postgres-1}
PORT=${DAON_DB_ADMIN_HOST_PORT:-5436}
SU_PW=$(cat "$ROOT/secrets/db_superuser_password")
UV=${UV_BIN:-/home/daon/.local/bin/uv}
ALEMBIC=("$UV" run --isolated --with alembic==1.18.5 --with sqlalchemy==2.0.46 --with 'psycopg[binary]==3.3.4' alembic)
cd services/api
DAON_DB_MIGRATION_DSN="postgresql+psycopg://postgres:${SU_PW}@127.0.0.1:${PORT}/daon2_user" "${ALEMBIC[@]}" upgrade "${1:-head}"
echo "alembic: $(docker exec "$PG" psql -U postgres -qAt -d daon2_user -c 'SELECT version_num FROM alembic_version')"
