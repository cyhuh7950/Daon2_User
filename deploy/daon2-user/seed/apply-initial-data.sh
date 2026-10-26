#!/usr/bin/env bash
# 새 설치의 초기 데이터(앱을 한 번 기동해 admin 조직·Workspace가 생긴 뒤): 조직 외부 전송 정책, 화면 설정을 적용하고
# 라이선스(개발 단계 설정)와 사용자 설명서(웹에 포함된 파일)를 확인한다. 멱등.
# 사용: bash deploy/daon2-user/seed/apply-initial-data.sh [tenant=admin] [DB컨테이너] [API컨테이너] [WEB컨테이너]
set -uo pipefail
cd "$(dirname "$0")/../../.."
TENANT=${1:-admin}; PG=${2:-daon2_user-postgres-1}; API=${3:-daon2_user-api-1}; WEB=${4:-daon2_user-web-1}
bash deploy/daon2-user/seed/apply-initial-policy.sh "$TENANT" "$PG" "$API"
bash deploy/daon2-user/seed/apply-initial-tts.sh "$TENANT" "$PG" "$API"
docker cp deploy/daon2-user/seed/initial_screen.py "$API":/tmp/initial_screen.py
docker exec "$API" python /tmp/initial_screen.py "$TENANT" admin
docker exec "$API" rm -f /tmp/initial_screen.py
STAGE=$(docker exec "$API" printenv DAON_DEVELOPMENT_STAGE 2>/dev/null || echo unset)
echo "라이선스: DAON_DEVELOPMENT_STAGE=$STAGE (true 이면 개발 단계로 라이선스 없이 전 기능 사용. 운영에서는 서명된 라이선스를 화면에서 적용)"
CODE=$(docker exec "$WEB" node -e "fetch('http://127.0.0.1:3330/manual/daon-user-manual.pdf').then(r=>console.log(r.status)).catch(()=>console.log('fail'))" 2>/dev/null || true)
echo "사용자 설명서: /manual/daon-user-manual.pdf → HTTP ${CODE:-확인 못함} (웹 이미지에 포함)"
