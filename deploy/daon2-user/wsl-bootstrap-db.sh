#!/usr/bin/env bash
# daon2_user 전용 PostgreSQL 부트스트랩(WSL-server QA). ~/deploy/daon2-user 에서 실행한다.
# 전제: 전용 postgres 컨테이너가 healthy 이고 secrets/db_app_password, secrets/db_superuser_password 가 있다.
# 마이그레이션 순서(검증됨, 2026-10-20): 0040까지 앱 역할(daon_app)로, 이후 head까지 superuser(postgres)로 실행한다.
#   - 0042가 앱 역할 소유 테이블을, 0056/0058 등이 superuser 실행자를 요구한다.
# 기존 DB를 지우려면 CONFIRM_DROP=daon2_user 와 --recreate 를 모두 지정해야 한다.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
RECREATE=0; [ "${1:-}" = "--recreate" ] && RECREATE=1
PG=${DAON_DB_CONTAINER:-daon2_user-postgres-1}
PORT=${DAON_DB_ADMIN_HOST_PORT:-5436}
APP_PW=$(cat "$ROOT/secrets/db_app_password"); SU_PW=$(cat "$ROOT/secrets/db_superuser_password")
PA() { docker exec "$PG" psql -U postgres -qAt "$@"; }
UV=${UV_BIN:-/home/daon/.local/bin/uv}
ALEMBIC=("$UV" run --isolated --with alembic==1.18.5 --with sqlalchemy==2.0.46 --with 'psycopg[binary]==3.3.4' alembic)

if [ "$(PA -d postgres -c "SELECT 1 FROM pg_database WHERE datname='daon2_user'")" = 1 ]; then
  if [ "$RECREATE" != 1 ]; then echo "DB exists; use --recreate with CONFIRM_DROP=daon2_user to rebuild"; exit 0; fi
  [ "${CONFIRM_DROP:-}" = daon2_user ] || { echo "CONFIRM_DROP=daon2_user required"; exit 2; }
  PA -d postgres -c "DROP DATABASE daon2_user"
  # 이전 시도가 남긴 클러스터 전역 역할(마이그레이션이 부분 상태로 판단한다)
  for r in daon_notebook_delete daon_account_owner daon_organization_owner; do PA -d postgres -c "DROP ROLE IF EXISTS $r"; done
fi
[ "$(PA -d postgres -c "SELECT 1 FROM pg_roles WHERE rolname='daon_app'")" = 1 ] || \
  PA -d postgres -c "CREATE ROLE daon_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '$APP_PW'"
PA -d postgres -c "CREATE DATABASE daon2_user OWNER daon_app"
PA -d daon2_user -c "CREATE EXTENSION IF NOT EXISTS vector"
PA -d daon2_user -c "ALTER SCHEMA public OWNER TO daon_app"

cd services/api
DAON_DB_MIGRATION_DSN="postgresql+psycopg://daon_app:${APP_PW}@127.0.0.1:${PORT}/daon2_user" "${ALEMBIC[@]}" upgrade 0040
DAON_DB_MIGRATION_DSN="postgresql+psycopg://postgres:${SU_PW}@127.0.0.1:${PORT}/daon2_user" "${ALEMBIC[@]}" upgrade head
# superuser 실행 구간에서 만들어진 테이블 중 앱 역할이 소유해야 하는 것(daon-user 운영 DB와 동일하게)
PA -d daon2_user -c "ALTER TABLE public.identity_auth_admin_role_operations OWNER TO daon_app"
PA -d daon2_user -c "ALTER TABLE public.identity_session_tenant_switch_outbox OWNER TO daon_app"
echo "alembic: $(PA -d daon2_user -c 'SELECT version_num FROM alembic_version')"
