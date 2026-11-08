#!/usr/bin/env bash
# 승인 지식 패키지(마크다운 파일)를 Daon 승인 지식으로 가져온다. 멱등.
# 사용: bash deploy/daon2-user/seed/import-knowledge-package.sh <파일> <package_id> <producer:daon2|daon2_5|daon3> <생산자버전> <제목> <근거설명> [tenant=admin] [actor=admin] [API컨테이너] [DB컨테이너]
set -euo pipefail
cd "$(dirname "$0")/../../.."
FILE=$1; PKG=$2; PRODUCER=$3; VERSION=$4; TITLE=$5; BASIS=$6
TENANT=${7:-admin}; ACTOR=${8:-admin}; API=${9:-daon2_user-api-1}; PG=${10:-daon2_user-postgres-1}
WS=$(docker exec "$PG" psql -U postgres -d "${DAON_DB_NAME:-daon2_user}" -qAt -c "SELECT workspace_id FROM public.workspaces WHERE tenant_id='$TENANT' ORDER BY workspace_id LIMIT 1")
[ -n "$WS" ] || { echo "조직 $TENANT 의 Workspace가 없습니다(앱을 한 번 기동한 뒤 다시 실행)."; exit 1; }
docker cp deploy/daon2-user/seed/import_knowledge_package.py "$API":/tmp/import_knowledge_package.py
docker cp "$FILE" "$API":/tmp/import_package_content.md
docker exec "$API" python /tmp/import_knowledge_package.py "$TENANT" "$WS" "$ACTOR" /tmp/import_package_content.md "$PKG" "$PRODUCER" "$VERSION" "$TITLE" "$BASIS"
docker exec "$API" rm -f /tmp/import_knowledge_package.py /tmp/import_package_content.md
