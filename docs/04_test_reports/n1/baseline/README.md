# WO-N1 시험 기준선 (NB0-P, 2026-11-23)

- 기준 커밋: origin/main 86608a5e
- API: `PYTHONPATH="src;tests" /d/Project/Daon2_User/services/api/.venv/Scripts/python -m pytest -q -p no:cacheprovider tests -rf` → 9 실패, 3364 통과, 532 건너뜀. 실패 이름 `api-fails.txt` (test_tts_audio 6, test_notification_dispatch_runtime 1, test_recovery_postgres 2 — 2026-11-16 기준선과 같음)
- Node: `node --test scripts/tests/*.test.mjs` → 1783 중 98 실패. 고유 실패 이름 96개 `node-fails.txt` (같은 이름이 두 번 나오는 시험 포함, 2026-11-16 기준선 98건과 같음)
- 비교 방법: 새 실행의 실패 이름 목록을 같은 방법으로 뽑아 이 파일과 `comm -13 <(sort 기준선) <(sort 새목록)` 으로 비교한다. 출력이 비어 있어야 "새 실패 0"
  - API 이름 뽑기: `grep "^FAILED" api.log | sed 's/ - .*//' | sort -u`
  - Node 이름 뽑기: `awk '/^✖ failing tests:/{f=1;next} f && /^✖ /{sub(/ \([0-9.]+m?s\)$/,"");print}' node.log | sort -u`
- 알려진 간헐 실패: 부하 시 `website_source_import`, node_modules junction 없는 worktree의 `NEXT_CLI_NOT_FOUND`
