#!/usr/bin/env bash
# 새 설치(마이그레이션 직후)에서 Provider 시드를 한 번 적용한다. 이미 연결이 하나라도 있으면 아무것도 하지 않는다.
# 사용: bash deploy/daon2-user/seed/load-provider-seed.sh [DB컨테이너=daon2_user-postgres-1]
set -euo pipefail
cd "$(dirname "$0")/../../.."
PG=${1:-daon2_user-postgres-1}
SEED=deploy/daon2-user/seed/provider-seed.sql
[ -f "$SEED" ] || { echo "시드 파일 없음: $SEED"; exit 0; }
COUNT=$(docker exec "$PG" psql -U postgres -d "${DAON_DB_NAME:-daon2_user}" -qAt -c "SELECT count(*) FROM public.system_provider_connections")
if [ "$COUNT" != 0 ]; then echo "Provider 연결이 이미 $COUNT 개 있어 시드를 적용하지 않습니다."; exit 0; fi
docker exec -i "$PG" psql -U postgres -d "${DAON_DB_NAME:-daon2_user}" -v ON_ERROR_STOP=1 -q < "$SEED"
echo "Provider 시드 적용: 연결 $(docker exec "$PG" psql -U postgres -d "${DAON_DB_NAME:-daon2_user}" -qAt -c "SELECT count(*) FROM public.system_provider_connections")개"
