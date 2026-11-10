# Daon2-User 디자인 기준

화면(`apps/web`, `packages/ui`)이 따르는 색·글자·틀의 단일 기준이다. 코드가 정본이며 이 문서는 그 요약이다.

## 개요
- 업무용 도구(Operate): 한국어 사용자가 소스·승인 지식을 올리고 근거 질문과 산출물을 만든다. 장식보다 읽기·찾기·일관성이 우선이다.
- 기준 색은 **보라**다. 노트북 화면의 로고·버튼 색을 관리·설정·로그인 화면까지 같게 쓴다(2026-11-10 결정).

## 색 (정본: `apps/web/app/globals.css` 맨 위 두 줄)
모든 화면은 `--daon-color-*` 와 `--daon-status-*` 토큰만 쓴다. 새 색은 여기에만 추가한다.

| 토큰 | 라이트 | 다크 | 용도 |
| --- | --- | --- | --- |
| `--daon-color-canvas` | #f5f4f8 | #17151c | 화면 바탕 |
| `--daon-color-surface` | #ffffff | #211e27 | 카드·패널 |
| `--daon-color-muted-surface` | #efedf6 | #292530 | 칩·입력·보조 면 |
| `--daon-color-text-primary` | #262231 | #f1edf6 | 본문 |
| `--daon-color-text-secondary` | #5f5970 | #b4aebf | 보조 글씨(4.5:1 이상) |
| `--daon-color-border` | #d9d5e3 | #3d3847 | 테두리 |
| `--daon-color-accent` | #6651cf | #a994ff | 주요 버튼·링크·선택 |
| `--daon-color-on-accent` | #ffffff | #17151c | accent 위의 글씨 |
| `--daon-status-{ok,warn,danger,info,neutral}-{fg,bg}` | 상태별 | 상태별 | 상태 배지(글자 4.5:1 이상) |

- `--workspace-*`(작업 화면)와 `--nh-*`(노트북 홈)은 위 토큰의 별칭이다. 값을 따로 정의하지 않는다.
- 테마는 `<html data-theme="light|dark">` 하나로 정한다(저장된 선택이 `system`이면 초기 스크립트가 OS 값으로 풀어 넣는다). `prefers-color-scheme` 로 따로 분기하지 않는다.
- 공유 토큰 패키지(`packages/design-tokens`, 모바일·데스크톱 공용)의 값은 해시로 고정되어 있어 바꾸지 않고, 웹은 `globals.css`에서 덮어쓴다.

## 글자
- 본문 14px, 작업 화면 12px 기준, **어느 글씨도 12px 미만으로 쓰지 않는다**(보조 글씨 포함).
- 한글은 어절 단위로 줄바꿈한다(`body { word-break: keep-all; overflow-wrap: break-word }`).

## 틀
- 관리 화면 내용 폭은 `--admin-content-width`(1120px) 하나다. 표는 카드 안에서만 가로 스크롤하고 문서 폭을 넘기지 않는다.
- 조작 대상은 가능하면 24×24px 이상, 버튼 글자는 줄바꿈하지 않는다(`white-space: nowrap`).
- 표의 작업 칸을 `display: flex`로 바꾸지 않는다(행 높이가 어긋나고 버튼 글자가 세로로 쪼개진다).

## 하지 않는 것
- 제목 위 영문 머리말(eyebrow/kicker), 3px 넘는 색 막대 `border-left`, 유니코드 기호를 아이콘 대신 쓰기.
- 개발용 상태 칩을 운영 화면의 머리 영역에 겹쳐 두기(왼쪽 아래에 둔다).
- 사용자 화면에 오류 코드를 그대로 보이기(한국어 안내가 먼저, 코드는 `title`/자세히).

## 모달·select·질문 입력창 (정리 완료)
- 모달 폭은 3단계 토큰: `--modal-sm` 460px(확인·입력), `--modal-md` 720px(설정·정책·라이선스), `--modal-lg` 1040px(설명서·큰 작업 창).
- select 는 `globals.css` 끝의 한 규칙(`select, option, optgroup`)이 테마 토큰으로 칠한다. 화면별 다크 패치를 만들지 않는다.
- 상태·강조용 `border-left` 색 막대는 1px 전체 테두리로 바꿨다.
- 질문 입력창 규칙은 `workspace-polish.css`의 "질문 창(정본 한 곳)" 블록이 최종이다(이전 두 겹의 덮어쓰기 제거).

## 남은 일 (2026-11-10 기준)
- 노트북 안 3열 화면(질문 입력창·모델 선택 바)은 화면 하네스에 없어 렌더로 확인하지 못했다. 소스 동등성만 검토했으니 배포 화면에서 확인한다.
- 유니코드 기호 아이콘(✦ ⋮ ◒ ⌕)은 그대로다. 남은 영문 머리말: 노트북 화면 상단의 "DAON WORKSPACE · NOTEBOOK".
- 상태 배지 외의 흩어진 고정 색(#b5473e 등)은 토큰으로 옮기지 않았다.
