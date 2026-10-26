#!/usr/bin/env bash
# 로컬에서 WSL-server 테스트 스택으로 배포한다(F0-11). 커밋된 HEAD만 전송한다(LF 유지 — CRLF면 DB 함수 해시가 어긋난다).
# 사용: scripts/deploy-wsl.sh [서비스...]    예) scripts/deploy-wsl.sh api web
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -n "$(git status --porcelain)" ]; then echo "경고: 커밋되지 않은 변경은 배포되지 않습니다(HEAD만 전송)." >&2; fi
git -c core.autocrlf=false archive HEAD | ssh WSL-server "cd ~/deploy/daon2-user && tar xf - && bash deploy/daon2-user/wsl-deploy.sh $*"
