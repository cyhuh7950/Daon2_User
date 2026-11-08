#!/usr/bin/env bash
# 초기 Daon 승인 지식을 가져온다(앱이 한 번 기동해 admin 조직·Workspace가 생긴 뒤). 멱등.
# 지식 문서(마크다운)는 저장소에 두지 않는다(내부 주소 등 운영 정보가 들어 있을 수 있음). 운영자가 서버의 디렉터리에 두고 지정한다.
#   SEED_KNOWLEDGE_DIR      가져올 *.md 가 있는 디렉터리(지정하지 않으면 아무것도 하지 않음)
#   SEED_KNOWLEDGE_PRODUCER daon2 | daon2_5 | daon3 (기본 daon2)
#   SEED_KNOWLEDGE_VERSION  생산자 버전(기본 오늘 날짜)
#   SEED_KNOWLEDGE_BASIS    승인 근거 설명(기본 "운영자 지정 승인 지식")
# package_id 는 파일 이름(확장자 제외), 제목은 첫 줄의 "# 제목"이다. 같은 package_id·같은 내용이면 건너뛰고, 내용이 바뀌었으면 충돌로 건너뛴다.
# 사용: SEED_KNOWLEDGE_DIR=~/seed-knowledge bash deploy/daon2-user/seed/apply-initial-knowledge.sh [tenant=admin] [DB컨테이너] [API컨테이너]
set -uo pipefail
cd "$(dirname "$0")/../../.."
TENANT=${1:-admin}; PG=${2:-daon2_user-postgres-1}; API=${3:-daon2_user-api-1}
DIR=${SEED_KNOWLEDGE_DIR:-}
[ -n "$DIR" ] && [ -d "$DIR" ] || { echo "초기 승인 지식: SEED_KNOWLEDGE_DIR 가 지정되지 않아 건너뜁니다."; exit 0; }
PRODUCER=${SEED_KNOWLEDGE_PRODUCER:-daon2}; VERSION=${SEED_KNOWLEDGE_VERSION:-$(date +%Y-%m-%d)}; BASIS=${SEED_KNOWLEDGE_BASIS:-운영자 지정 승인 지식}
for FILE in "$DIR"/*.md; do
  [ -f "$FILE" ] || continue
  PKG=$(basename "$FILE" .md)
  TITLE=$(head -n 1 "$FILE" | sed 's/^# *//')
  bash deploy/daon2-user/seed/import-knowledge-package.sh "$FILE" "$PKG" "$PRODUCER" "$VERSION" "${TITLE:-$PKG}" "$BASIS" "$TENANT" admin "$API" "$PG" || echo "가져오기 건너뜀: $PKG"
done
