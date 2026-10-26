#!/usr/bin/env bash
# Studio v2 실DB 시험(WSL). ~/deploy/daon2-user 에서 실행. 비밀번호는 출력하지 않는다.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
PORT=${DAON_DB_ADMIN_HOST_PORT:-5436}
APP_PW=$(cat "$ROOT/secrets/db_app_password"); SU_PW=$(cat "$ROOT/secrets/db_superuser_password")
UV=${UV_BIN:-/home/daon/.local/bin/uv}
export DAON_STUDIO_V2_TEST_DSN="postgresql://daon_app:${APP_PW}@127.0.0.1:${PORT}/daon2_user"
export DAON_STUDIO_V2_TEST_SEED_DSN="postgresql://postgres:${SU_PW}@127.0.0.1:${PORT}/daon2_user"
cd services/api
PYTHONPATH=src "$UV" run --frozen pytest -q -p no:cacheprovider "${@:-tests/test_studio_v2_postgres_integration.py}"
