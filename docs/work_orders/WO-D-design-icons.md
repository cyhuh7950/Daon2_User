# WO-D. 디자인 시스템·아이콘

| 항목 | 내용 |
| --- | --- |
| 대상 계획 항목 | 신규 S7-01 ~ S7-08 (디자인), S1-01·S1-05(타일·카드 스타일), S6-01(대비·접근성) |
| 요청 | 2026-10-20 사용자: "NotebookLM을 참조해서 아이콘을 제작해서 추가하자. 지금은 너무 디자인이 구려" |
| 참조 | 사용자가 제공한 NotebookLM 화면 캡처(스튜디오 패널 2장, 채팅 화면, ⋮ 메뉴 2장). **형태·색·간격의 인상을 참고만 하고 아이콘·문구를 복제하지 않는다.** 아이콘은 모두 자체 제작한 도형이다. |
| 현재 상태 | `packages/design-tokens/tokens.css`는 `--daon-*` 변수(본문 12px, 설명 10px, 라이트 기본 `#F4F7FB`, 다크는 `globals.css`의 `:root[data-theme="dark"]` 오버라이드), 아이콘은 일부 CSS 마스크·텍스트 글리프(`PANE_ICONS`, `tile-<icon>` 클래스). 글자 크기가 작고(9~12px) 평평하며 타일이 정사각 버튼형이다. |

---

## 1. 참조 화면에서 읽은 디자인 특징

| 요소 | 관찰 | 우리 설계에 반영 |
| --- | --- | --- |
| 전체 | 어두운 배경에 **둥근 패널**(큰 반경 ~24px), 패널 안에서 콘텐츠가 스크롤 | 패널 반경 20~24px, 3개 면이 각각 카드처럼 분리(간격 12px) |
| 타일 | **2열 격자, 필(pill) 모양**(높이 ~56px, 반경 ~28px), 좌측 컬러 아이콘 + 우측 라벨, 배경은 패널보다 한 단계 밝은 회색(`#2b2d31` 계열) | 같은 구조. 호버 시 한 단계 밝아지고 연필 아이콘이 나타남 |
| 아이콘 색 | 유형마다 고유 강조색(파랑·분홍·초록·보라·노랑 등), **선(outline) 스타일 + 작은 스파클(AI 표시)** | 선 아이콘 24px, stroke 1.75, 유형별 강조색(토큰) |
| 배지 | "New!" 소형 둥근 라벨 | `studio-badge` |
| 툴팁 | 어두운 배경의 흰색 둥근 말풍선(예: "소스를 기반으로 보고서 생성") | 접근 가능한 툴팁(`role="tooltip"`, 포커스에서도 표시) |
| 카드 목록 | 행: 좌 아이콘 · 제목(굵게) · 부제(작은 회색 "소스 14개 · 93일 전") · 우 재생/⋮ | 설계서 §6.4와 일치 |
| 하단 | 가운데 떠 있는 **"메모 추가" 필 버튼**(아이콘+텍스트, 그림자) | `studio-fab` 필 버튼, 스크롤 영역 위에 고정 |
| 메뉴 | 둥근 팝오버, 항목 좌측 아이콘, 구분선, 위험 항목(삭제)은 마지막 | 같은 구조 |
| 채팅 | 답변 하단에 작은 아이콘 줄(메모에 저장·복사·👍👎), 입력창은 둥근 필, 우측에 "소스 N개"와 전송 원형 버튼 | S1-15 |
| 글자 크기 | 본문 14px 안팎, 제목 16~18px(우리 12px보다 큼) | 새 토큰: 본문 14px, 캡션 12px |

---

## 2. 작업 목록

### T-D-01. 아이콘 세트 (이번 작업에서 구현 — 아래 §3)

- **파일**: `packages/ui/src/studio-icon-data.js`(순수 데이터), `studio-icon.js`(컴포넌트, JSX 없이 `createElement`), `studio-icon.css`, `scripts/build-studio-icon-preview.mjs`(미리보기 HTML 생성), `scripts/tests/studio-icon.test.mjs`, `packages/ui/package.json` exports 항목.
- **아이콘 목록(36개)**
  - 유형(10): `audio_overview`, `slides`, `video_overview`, `mind_map`, `report`, `flashcards`, `quiz`, `infographic`, `data_table`, `memo`
  - 동작(26): `add`, `close`, `more_vertical`, `share`, `edit`, `download`, `info_sparkle`(프롬프트 및 소스 보기), `delete`, `play`, `panel_toggle`, `settings_sliders`, `copy`, `pin`(메모에 저장), `chart`(애널리틱스), `history`, `refresh`, `check`, `warning`, `chat`, `spinner`, `sparkle`, `source_stack`, `cancel`, `chevron_right`, `chevron_down`, `upload`
- **규격**: 24×24 viewBox, `fill="none"`, 선 `currentColor`, `stroke-width 1.75`, `stroke-linecap/linejoin round`. 일부 요소(스파클·점·재생)는 `fill`. 접근성: 장식용은 `aria-hidden="true"`, 단독 사용은 `role="img"`+`aria-label`.
- **유형별 강조색 토큰**(다크/라이트 각각 대비 4.5:1 이상 확인): `--studio-accent-audio`, `-slides`, `-video`, `-mindmap`, `-report`, `-flashcards`, `-quiz`, `-infographic`, `-table`, `-memo`.
- **완료 기준**: 미리보기 페이지에서 36개 아이콘이 다크·라이트에서 깨짐 없이 표시, 단위 테스트(중복 이름·허용 요소·viewBox·색 토큰 존재) 통과, 웹 빌드·`verify:product-ui-boundary` 통과.

### T-D-02. 디자인 토큰 개정 (S7-02)

- **파일**: `packages/design-tokens/tokens.json`(정본) → `tokens.css`, `tokens.ts` 동기 생성(`README.md`의 생성 방식 확인).
- **주의**: `product-foundation.test.mjs`가 "Design Token 정본은 승인된 정확값", "CSS와 TypeScript Adapter는 JSON Token 정본에서 파생되고 값이 일치", "Semantic Color는 WCAG 2.2 AA Contrast를 기계 검증"을 고정한다. **토큰 값을 바꾸면 이 테스트의 기대값도 함께 갱신해야 하며**, 변경 근거를 설계 기록(이 문서 §4)에 남긴다.
- **변경안(제안)**
  - 글자: 본문 `12px → 14px`, 설명 `10px → 12px`, 보조 `9px → 11px`, 화면 제목 `16px → 20px`, 패널 제목 `14px → 16px`; 행간 1.5.
  - 반경: `--daon-radius-3`을 20px까지 확장, 필(pill) 반경 `--daon-radius-pill: 999px` 신설.
  - 간격 스케일 유지, 새 `--daon-space-panel: 16px`.
  - **스튜디오 전용 토큰**(`--studio-*`)은 별도 파일 `packages/ui/src/studio-tokens.css`에 두어 기존 토큰 테스트와 분리한다(우선 적용, 전체 개정은 T-D-03 이후).
  - 다크 팔레트(참조 화면 인상): 캔버스 `#131418`, 패널 `#1b1c20`, 타일 `#2a2c31`, 타일 호버 `#34363c`, 텍스트 주 `#e8eaed`, 보조 `#9aa0a6`, 경계 `#3a3c42`. 라이트 팔레트: 캔버스 `#eef1f6`, 패널 `#ffffff`, 타일 `#f1f3f8`, 타일 호버 `#e6e9f1`, 텍스트 `#1b2230`, 보조 `#5b6577`.
- **테스트**: `verify:workspace`·`product-foundation.test.mjs`(기대값 갱신 포함) 통과, 자동 대비 검증 통과.

### T-D-03. 레이아웃·공통 컴포넌트 스타일 (S7-03~05)

- **3면 레이아웃**: 면마다 카드형(배경 `--daon-color-surface`, 반경 20px, 그림자 약), 면 사이 간격 12px, 헤더 56px 고정(제목 16px, 접기/정보 아이콘 버튼 40×40).
- **버튼 체계**: 기본(채움), 보조(외곽), 텍스트, 아이콘 단독(40×40, 호버 배경 원형), 필(타일·FAB). 포커스 링 3px(`--daon-color-focus`, 대비 확인).
- **폼**: 입력 높이 40px, 반경 12px, 레이블 상단, 오류는 텍스트로(색 단독 금지).
- **카드·행**: 행 높이 64px(부제 포함), 호버 배경 단계 상승, 선택 상태 좌측 강조 바.
- **모달·메뉴**: 반경 16px, 그림자 중간, 메뉴 항목 높이 44px(터치 대상 크기), 구분선.
- **모션**: 기본 160ms ease-out, `prefers-reduced-motion`이면 제거(이미 토큰 있음).
- **파일**: `packages/ui/src/workspace.css`(분산된 스타일 정리), 새 `studio-panel.css`·`studio-tokens.css`. 기존 클래스명 변경은 테스트(`data-*`·`aria-*` 기준)에 영향이 없는 범위로 제한.

### T-D-04. 로그인·홈·설정 화면 정돈 (S7-06)

- **로그인**(`apps/web/app/globals.css` + `UI/auth`): 중앙 카드(폭 420px), 제품명·한 줄 설명, 입력·버튼 새 규격, 오류는 카드 상단 `role="alert"`, 하단 링크(가입/이메일 인증/비밀번호 찾기).
- **Notebook 홈**(`UI/notebook-home.css`): 카드 격자(최소 260px, 반경 20px, 제목·소스 수·수정일), 생성 카드(`+ 새 노트북`) 첫 위치, 빈 상태 일러스트(자체 제작 SVG)와 안내 문구.
- **설정**: 좌측 목록+우측 본문 2단, 섹션 제목 18px.

### T-D-05. 아이콘 적용 (S7-07)

- 기존 `PANE_ICONS`·CSS 마스크 아이콘을 새 `StudioIcon`으로 교체(셸 헤더·면 제목·설정 메뉴·Source 목록 동작 버튼). 교체는 시각 변경만이며 라벨·`aria-*`·`data-*`는 유지해 테스트를 보존한다.

### T-D-06. 다크/라이트 검증 (S7-08)

- 두 테마에서 대비 측정(자동: 토큰 대비 테스트, 수동: 스크린샷 1440/1180/820/390 폭), 결과를 `docs/04_test_reports/design/`에 저장. 색약 시뮬레이션(적/녹, 청/황) 스크린샷 1회.

---

## 3. 아이콘 세트 구현 메모 (T-D-01 상세)

- 데이터 형식: `ICONS[name] = [["path",{d}], ["rect",{x,y,width,height,rx}], ["circle",{cx,cy,r}], ["line",{x1,y1,x2,y2}], ["path",{d, fill:"currentColor", stroke:"none"}]…]`.
- 컴포넌트: `StudioIcon({ name, size = 24, title, accent, className })` → `<svg viewBox="0 0 24 24" width height role aria-hidden|aria-label class="studio-icon studio-icon--<name>">`. `accent`가 true면 유형별 색 변수 적용 클래스를 붙인다.
- 유형 스타일 맵: `STUDIO_TYPE_STYLE = { report: { icon:"report", accentVar:"--studio-accent-report", labelKey:"studio.tile.report" }, … }`.
- 색: `studio-icon.css`에 `:root`·`[data-theme="dark"]`별 `--studio-accent-*` 정의, 클래스 `.studio-icon--accent-<type> { color: var(--studio-accent-<type>) }`.
- 미리보기: `scripts/build-studio-icon-preview.mjs`가 데이터를 읽어 `docs/design/studio-icons-preview.html`(단일 파일, 다크/라이트 토글, 이름 표시, 타일 시안)을 생성한다.

## 4. 설계 기록

| 일자 | 결정 |
| --- | --- |
| 2026-10-20 | 아이콘은 자체 제작 선(outline) 세트로 하고 참조 제품의 아이콘을 그대로 쓰지 않는다. 형태 언어(필 타일, 컬러 아이콘, 스파클 표식, 둥근 패널)만 참고한다. |
| 2026-10-20 | 스튜디오 전용 토큰은 `studio-tokens.css`로 분리해 기존 토큰 테스트와 독립적으로 적용한다. 전체 토큰 개정(T-D-02)은 기대값 갱신과 함께 별도 커밋으로 수행한다. |

## 5. 위험

| 위험 | 영향 | 대응 |
| --- | --- | --- |
| 토큰 변경이 기존 테스트 기대값과 충돌 | 대량 실패 | 스튜디오 전용 토큰 선적용, 전체 개정은 테스트 갱신과 같은 커밋 |
| 글자 크기 확대로 기존 레이아웃 붕괴 | 시각 회귀 | 스크린샷 4폭 확인, 셸의 고정 폭 규칙 점검 |
| 아이콘 교체가 라벨·접근성에 영향 | 접근성 회귀 | `aria-label`·텍스트 유지, 아이콘은 `aria-hidden` 기본 |
| 참조 제품 형태 과도 모방 | 법적·품질 위험 | 자체 도형, 색·형태 차별(둥근 필·선 아이콘은 일반적 언어) |
