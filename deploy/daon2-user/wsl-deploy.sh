#!/usr/bin/env bash
# WSL-server 배포 3단계(F0-11): 마이그레이션 → 이미지 빌드·기동 → 헬스 확인. ~/deploy/daon2-user 에서 실행한다.
# 코드 전송은 scripts/deploy-wsl.sh(로컬)가 맡는다. 비밀번호는 출력하지 않는다.
# 사용: wsl-deploy.sh [서비스...]   (기본: api web studio-v2-worker document-worker studio-worker)
set -euo pipefail
cd "$(dirname "$0")/../.."
SERVICES=("$@"); [ "${#SERVICES[@]}" -gt 0 ] || SERVICES=(api web studio-v2-worker document-worker studio-worker)
COMPOSE=(docker compose --env-file .env -f deploy/daon2-user/compose.yaml -f deploy/daon2-user/${DAON_COMPOSE_OVERLAY:-compose.wsl-dedicated-postgres.yaml})
PROJECT=${DAON_COMPOSE_PROJECT:-daon2_user}

echo "[1/3] 마이그레이션"
bash deploy/daon2-user/wsl-migrate.sh

echo "[2/3] 빌드·기동: ${SERVICES[*]}"
"${COMPOSE[@]}" up -d --build "${SERVICES[@]}" 2>&1 | tail -n 5

echo "[3/3] 헬스 확인"
FAILED=0
for svc in api web; do
  name="${PROJECT}-${svc}-1"
  status=starting
  for _ in $(seq 1 60); do
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name" 2>/dev/null || echo missing)
    case "$status" in healthy|running) break ;; esac
    sleep 3
  done
  echo "  $svc: $status"
  case "$status" in healthy|running) ;; *) FAILED=1 ;; esac
done
for svc in "${SERVICES[@]}"; do
  case "$svc" in api|web) continue ;; esac
  echo "  $svc: $(docker inspect --format '{{.State.Status}}' "${PROJECT}-${svc}-1" 2>/dev/null || echo missing)"
done
[ "$FAILED" = 0 ] || { echo "배포 실패: 헬스 확인을 통과하지 못했습니다"; exit 1; }
echo "배포 완료"
