# 로컬 전체 품질 게이트 실행 결과(F0-13)

실행: 2026-10-26, 기준 저장소 체크아웃(`npm run verify:quality-gate`, 약 30분). 실행 환경: Windows, Node v24.22.1, npm 11.19.1, Corepack 0.36.0.

| 범주 | 결과 |
| --- | --- |
| lint(8) | 통과 |
| contract(3) | 통과 |
| independence(1) | 통과(위반 0) |
| type(5) | **실패 1**: `desktop-rust-type` — `cargo` 없음(D-009) |
| unit(10) | **실패 1**: `desktop-shell-unit` — 게이트 실행 중 실패했으나 같은 환경에서 `npm run verify:desktop-unit`을 다시 실행하면 51건 모두 통과(게이트 실행과 동시에 서버 배포를 돌려 시간 초과·부하 영향 가능성, **원인 미확정**) |
| build(8) | **실패 1**: `toolchain-baseline` — 로컬 Node·npm·Corepack 버전이 고정 기준(`toolchain-versions.json`: Node 24.18.0, npm 11.12.1, Corepack 0.35.0)과 다르다. 기준 버전을 설치하거나 기준을 갱신해야 한다 |
| security(7) | **실패 2**: ① `production-dependency-audit` — 운영 의존성 취약점 3건: `next` 16.0.0~16.4.0(심각, 수정 16.4.3), `body-parser` 2.0.0~2.3.0(높음), `launch-editor` ≤2.14.1(높음) ② `local-service-full-environment-audit` — 파이썬 `pip-audit`가 4개 패키지의 취약점 17건 보고(`pypdf` 6.19.0 → 6.21.2, `certifi`, `filelock`, `setuptools`) |

## 해소 현황

- D-006(`security-static-scan`, `quality-gate-runner-tests`): 이번 실행에서 두 검사 모두 통과 → 해소 확인.
- 남은 5건 중 코드로 해소 가능한 것은 의존성 버전 올림(위 7건)과 `desktop-shell-unit` 재확인이다. 의존성 올림은 고정된 기준(`package.json`·`package-lock.json`·`uv.lock`·`toolchain-versions.json`)을 바꾸므로 승인 후 진행한다.
- `desktop-rust-type`은 Rust 툴체인 설치(F0-15)가 필요하며, 게이트의 Desktop 검사를 "해당 없음"으로 두는 방안은 게이트 약화라서 사용자 결정이 필요하다.
- `toolchain-baseline`은 개발자 PC의 Node 버전을 기준(24.18.0)에 맞추거나 기준을 올리는 결정이 필요하다.

## 재실행 결과(2026-10-26, 조치 후)

조치: 운영 의존성 보안 갱신(next 16.4.3 등), 고정 도구 버전을 개발 PC 기준(Node 24.22.1·npm 11.19.1·Corepack 0.36.0)으로 갱신(사용자 승인), Rust 1.97.1 설치, `desktop-tauri-shell.test.mjs`의 옛 `next` 버전 단언 수정.
결과: **lint 8 · type 5 · unit 10 · contract 3 · build 8 · security 7 · independence 1 모두 PASS, 실패 0건, high/critical 0건(종료 코드 0)**. 위 표의 5건은 모두 해소됐다.
