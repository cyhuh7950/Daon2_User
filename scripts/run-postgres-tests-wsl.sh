#!/usr/bin/env bash
# WSL 전용 Postgres 통합 시험(F8-11). ~/deploy/daon2-user 에서 실행한다. 비밀번호는 출력하지 않는다.
#
# 운영 중인 daon2_user DB에는 시험 데이터를 넣지 않는다. 대신 같은 이미지로 "임시 Postgres 컨테이너"를 따로 띄워
# (클러스터 전역 역할이 운영과 충돌하지 않는다) 마이그레이션 후 시험을 돌리고, 끝나면 컨테이너와 볼륨을 지운다.
#
# 사용: scripts/run-postgres-tests-wsl.sh [pytest 인자...]   (기본: services/api/tests 전체)
#   test_studio_v2_postgres_integration.py 는 기존 시험 Workspace가 있는 운영형 DB를 전제로 하므로
#   기본 실행에서 제외한다(deploy/daon2-user/wsl-run-studio-v2-it.sh 로 따로 실행).
#   DAON_TEST_PG_PORT(기본 5437), DAON_TEST_PG_MEM(기본 768m), UV_BIN
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
NAME=daon2_user-testpg
PORT=${DAON_TEST_PG_PORT:-5437}
MEM=${DAON_TEST_PG_MEM:-768m}
IMAGE=$(grep -o 'pgvector/pgvector:[^"[:space:]]*' deploy/daon2-user/compose.wsl-dedicated-postgres.yaml | head -1)
APP_PW=$(cat "$ROOT/secrets/db_app_password"); SU_PW=$(cat "$ROOT/secrets/db_superuser_password")
UV=${UV_BIN:-/home/daon/.local/bin/uv}

cleanup() { docker rm -f -v "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
docker run -d --name "$NAME" --memory "$MEM" -e POSTGRES_USER=postgres -e POSTGRES_DB=postgres -e "POSTGRES_PASSWORD=$SU_PW" \
  -p "127.0.0.1:${PORT}:5432" "$IMAGE" postgres -c shared_buffers=128MB -c max_connections=100 >/dev/null
for _ in $(seq 1 60); do
  docker exec "$NAME" pg_isready -U postgres -d postgres >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$NAME" pg_isready -U postgres -d postgres >/dev/null

# 같은 부트스트랩(0040까지 앱 역할, 이후 superuser)을 임시 컨테이너에 적용한다.
DAON_DB_CONTAINER="$NAME" DAON_DB_ADMIN_HOST_PORT="$PORT" bash deploy/daon2-user/wsl-bootstrap-db.sh

APP="postgresql://daon_app:${APP_PW}@127.0.0.1:${PORT}/daon2_user"
ADMIN="postgresql://postgres:${SU_PW}@127.0.0.1:${PORT}/daon2_user"
export DAON_TEST_POSTGRES_DSN="$APP" DAON_STUDIO_TEST_APP_DSN="$APP" DAON_STUDIO_TEST_DSN="$APP"
export DAON_NOTIFICATION_TEST_DSN="$APP" DAON_NOTIFICATION_GUARD_TEST_DSN="$APP" DAON_ORGANIZATION_TEST_DSN="$APP"
export DAON_PROVIDER_TEST_DSN="$APP" DAON_PROVIDER_ADMIN_DSN="$ADMIN" DAON_OPERATIONS_TEST_DSN="$APP"
export DAON_STUDIO_V2_TEST_DSN="$APP" DAON_STUDIO_V2_TEST_SEED_DSN="$ADMIN"

cd services/api
ARGS=("$@")
[ "${#ARGS[@]}" -gt 0 ] || ARGS=(tests --ignore=tests/test_studio_v2_postgres_integration.py)
set +e
PYTHONPATH=src "$UV" run --frozen pytest -q -p no:cacheprovider "${ARGS[@]}"
STATUS=$?
set -e
echo "postgres tests exit=$STATUS (임시 컨테이너 $NAME 은 종료 시 삭제됩니다)"
exit "$STATUS"
