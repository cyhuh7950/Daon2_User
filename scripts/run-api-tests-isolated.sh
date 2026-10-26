#!/usr/bin/env bash
# 전체 API 단위 시험. D1 계열 시험은 "새 고정 루트"(D:/tmp/daon2-user-s44-d1-*)를 요구하므로 파일마다 새 루트로 따로 실행한다.
set -u
cd "$(dirname "$0")/../services/api"
ISOLATED="test_recovery_destinations test_service_image_archive test_service_snapshot test_recovery_lineage_capture test_recovery_lineage_restore test_recovery_postgres test_service_snapshot_postgres"
ROOT_EOUL2="D:/tmp/daon2-user-s44-d1-eoul2-20261019"
ROOT_MAIN="D:/tmp/daon2-user-s44-d1-main-20261019"
IGN=""
for f in $ISOLATED; do IGN="$IGN --ignore=tests/$f.py"; done
export PYTHONPATH=src
echo "== main suite"; uv run --no-sync python -m pytest tests -p no:cacheprovider --maxfail=0 -q $IGN 2>&1 | tail -n 25
for f in $ISOLATED; do
  rm -rf "$ROOT_EOUL2" "$ROOT_MAIN"; mkdir -p "$ROOT_MAIN"
  echo "== $f"; TMP="$ROOT_MAIN" uv run --no-sync python -m pytest "tests/$f.py" -p no:cacheprovider -q 2>&1 | tail -n 3
done
rm -rf "$ROOT_EOUL2" "$ROOT_MAIN"
