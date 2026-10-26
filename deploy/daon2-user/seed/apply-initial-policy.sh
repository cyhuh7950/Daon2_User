#!/usr/bin/env bash
# 새 설치의 초기 외부 전송 정책을 적용한다(앱이 한 번 기동해 admin 조직·Workspace가 만들어진 뒤). 멱등.
# 사용: bash deploy/daon2-user/seed/apply-initial-policy.sh [tenant=admin] [DB컨테이너] [API컨테이너]
set -euo pipefail
cd "$(dirname "$0")/../../.."
TENANT=${1:-admin}; PG=${2:-daon2_user-postgres-1}; API=${3:-daon2_user-api-1}
WS=$(docker exec "$PG" psql -U postgres -d "${DAON_DB_NAME:-daon2_user}" -qAt -c "SELECT workspace_id FROM public.workspaces WHERE tenant_id='$TENANT' ORDER BY workspace_id" | tr '\n' ' ')
docker cp deploy/daon2-user/seed/initial_policy.py "$API":/tmp/initial_policy.py
# shellcheck disable=SC2086
docker exec "$API" python /tmp/initial_policy.py "$TENANT" $WS
docker exec "$API" rm -f /tmp/initial_policy.py
