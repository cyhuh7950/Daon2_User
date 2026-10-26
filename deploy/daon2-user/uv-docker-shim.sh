#!/usr/bin/env bash
# uv가 없는 서버용 대체: `uv run --isolated --with <pkg> ... alembic <args>` 를 Docker(python:3.12-slim)에서 실행한다.
# 현재 디렉터리(services/api)를 마운트하고 호스트 네트워크를 쓴다(DB는 127.0.0.1:관리포트). 사용: UV_BIN=이 파일 경로
set -euo pipefail
[ "${1:-}" = run ] || { echo "uv shim: run 만 지원합니다" >&2; exit 2; }
shift
PKGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --isolated) shift ;;
    --with) PKGS+=("$2"); shift 2 ;;
    *) break ;;
  esac
done
[ "$#" -gt 0 ] || { echo "uv shim: 실행할 명령이 없습니다" >&2; exit 2; }
PIP=$(printf '%q ' "${PKGS[@]}")
exec docker run --rm --network host -v "$PWD":/work -w /work -e DAON_DB_MIGRATION_DSN \
  python:3.12-slim sh -c "pip install -q --disable-pip-version-check $PIP && exec \"\$@\"" sh "$@"
