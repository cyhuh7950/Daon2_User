# WO-UM1 사용자 매뉴얼 재구성 작업 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매뉴얼 3권을 그림·표가 있는 한 권(1부 흐름·2부 화면·3부 관리자·부록)으로 다시 쓰고, 원본·docx·pdf·웹 공개 사본을 한 명령으로 함께 만든다.

**Architecture:** 원본은 `docs/manual/daon-user-manual/index.md` 하나와 `images/`. `scripts/build-daon-manuals.py all`이 docx(표·그림 포함)·pdf(LibreOffice)·공개 사본·목록 파일을 만든다. 앱 안 매뉴얼 보기(`ManualMarkdown`)는 표와 `/manual/images/` 그림을 그린다. 시험이 구조·문구·사본 동일성을 지킨다.

**Tech Stack:** Python 3.14 + python-docx + Pillow, LibreOffice `soffice --headless`, React(`packages/ui`), Node `node:test`.

**실행 환경:** python-docx가 어느 가상환경에도 없다. 가상환경을 바꾸지 않고 `uv run --no-project --with python-docx --with pillow==12.3.0 --with pypdf==6.21.2 --with pytest==9.0.3 python ...`로 실행한다(이하 `PYDOC`). 첫 실행 때 PyPI에서 받는다.

**Spec:** `docs/work_orders/WO-UM1-user-manual.md`

## Global Constraints

- 한 권: 문서 ID `daon-user-manual`, 제목 `Daon 사용자 설명서`, 판 `2.0.0`, 언어 `ko-KR`. `daon-getting-started`·`daon-knowledge-llm-guide`는 은퇴.
- 웹 화면만 설명. 데스크톱·모바일은 부록 D 한 줄.
- 제목 단계: 부 `##`(예: `## 2부 화면별 설명`), 절 `###`(예: `### 1-3 노트북 만들기`, `### 2-6 스튜디오`), 화면 절의 하위 제목 `####`.
- 2부·3부 모든 화면 절의 하위 제목 6개(순서 고정): `#### 기능·목적`, `#### 쓸 수 있는 사람`, `#### 사용 순서`, `#### 화면 구성`, `#### 주의·오류`, `#### 관련`.
- 버튼·메뉴 이름은 화면 문구와 똑같이 `**굵게**`.
- 내부 주소·키·토큰·호스트 목록 금지(현재 `manual-content` 금지 패턴 유지).
- 화면 그림: 1280×800 PNG, ①②③ 번호, 개인정보·키는 비우거나 가림. 위치 `docs/manual/daon-user-manual/images/`, 공개 사본 `apps/web/public/manual/images/`.
- 지금 `manual-content`가 요구하는 핵심 문구(모델 연결 방식, 조직 정책·ETag, 라이선스 한도·`can_apply=true`, 보호 admin·`admin_cli`·`PROTECTED_ADMIN_ACCOUNT`, 지식 원칙 7개·용어 6개)는 새 매뉴얼에 남긴다.
- ysna 시험 데이터는 다 쓰고 지운다. ysna 배포는 따로 승인.
- 커밋 작성자: `git -c user.name=cyhuh7950 -c user.email=cyhuh7950@users.noreply.github.com` (사용자 Git 설정 파일 없음). 커밋 말미 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. 표 셀 안의 `|`·굵게·코드 표시 → docx와 앱 보기에서 셀이 깨지지 않고 글자만 보인다 (Task 1·2 시험).
2. 그림 경로 조작(`../`, 절대 경로, 외부 URL) → 앱 보기는 `/manual/images/` 밖 그림을 그리지 않고 설명 글만 보인다 (Task 2 시험).
3. LibreOffice가 없거나 실패 → 빌드가 멈추고 옛 pdf를 남긴 채 목록 파일을 만들지 않는다 (Task 1 시험).
4. 화면 절에 제목 하나가 빠지거나 순서가 바뀜 → 구조 시험이 그 절 이름으로 실패한다 (Task 3 시험).
5. 화면 문구가 바뀌어 매뉴얼의 굵은 버튼 이름이 사라짐 → 문구 대조 시험이 그 이름으로 실패한다 (Task 3 시험).

---

### Task 1: 생성 스크립트 — 한 권, 표, PDF, 한 명령

**Files:**
- Modify: `scripts/build-daon-manuals.py`
- Create: `scripts/tests/test_build_daon_manuals.py` (pytest, `PYDOC`로 실행)

**Interfaces:**
- Produces: `python scripts/build-daon-manuals.py all` → `docs/manual/dist/daon-user-manual.{docx,pdf}`, `apps/web/public/manual/{daon-user-manual.md,.docx,.pdf,manifest.json,images/*}`, `docs/manual/release-manifest.json`. 모드 `docx`·`pdf`·`manifest`·`all`.
- Produces: `parse_table(lines: list[str], start: int) -> tuple[list[list[str]], int]` (행 목록, 다음 줄 번호), `convert_pdf(docx: Path, out_dir: Path, soffice: str) -> Path`.

- [ ] **Step 1: Write the failing tests**

`test_table_rows_are_split_on_unescaped_pipes` — `parse_table(["| a | b |","| --- | --- |","| `x\|y` | **굵게** |"],0)` → `([["a","b"],["x|y","굵게"]], 3)`.
`test_docx_renders_markdown_tables_as_word_tables` — 표 하나 있는 임시 md로 docx 생성 → `Document(...).tables`에 2열 표가 있고 본문에 `| a |` 글자가 없다.
`test_docx_embeds_images_with_alt_caption` — 그림 줄 `![① 스튜디오 패널](images/x.png)`이 그림 1개와 캡션으로 들어간다.
`test_pdf_failure_keeps_previous_pdf_and_skips_manifest` — `soffice` 경로가 없을 때 `all`이 `SystemExit`로 끝나고 기존 pdf·manifest 바이트가 그대로다.
`test_level_four_headings_become_word_heading_3` — `#### 기능·목적`이 Word 제목 3 단계 문단이 되고 본문에 `####` 글자가 없다.
`test_manifest_lists_one_document_version_2` — manifest `documents` 길이 1, `release_version == "2.0.0"`, 문서 ID `daon-user-manual`.

- [ ] **Step 2: Run** `PYDOC -m pytest scripts/tests/test_build_daon_manuals.py -q` → FAIL (`parse_table` 없음).
- [ ] **Step 3: Implement** — 제목 정규식을 `#{2,4}`로 넓혀 `####`를 Word 제목 3으로. `DOCS`를 한 권으로, `RELEASE="2.0.0"`, `RELEASED_AT`은 작성일. `add_markdown_body`가 `|`로 시작하는 연속 줄을 `parse_table`로 읽어 Word 표(머리행 굵게, 테두리, 셀 여백 기존 `set_cell_margins`)로 그린다. `convert_pdf`는 `soffice --headless --convert-to pdf --outdir`를 임시 폴더로 실행해 성공 시에만 `dist`로 옮긴다. `all` = docx → pdf → manifest. manifest 단계는 `images/`를 공개 사본으로 복사하고 은퇴 문서의 공개 사본을 지운다.
- [ ] **Step 4: Run** 같은 명령 → PASS.
- [ ] **Step 5: Commit** `feat(manual): build one manual with tables, images and PDF in one command`.

### Task 2: 앱 안 매뉴얼 보기 — 한 권, 표, 그림

**Files:**
- Modify: `apps/web/lib/manual-api.js` (허용 문서 1개, `documents.length === 1`, `APPROVED_RELEASE_VERSION = "2.0.0"`)
- Modify: `packages/ui/src/product-workspace-shell.jsx` (`ManualMarkdown`, `readableManualLine`)
- Modify: `packages/ui/src/workspace.css` (`.manual-reader-body table`, `img` 최대 폭 100%)
- Modify: `scripts/test-harness/manual-hub/vite.config.mjs`, `scripts/tests/manual-hub.test.mjs`
- Test: `scripts/tests/manual-reader-react.test.mjs` (새 파일)

**Interfaces:**
- Produces: `ManualMarkdown({ text })`가 `####` 제목을 `<h5>`로, 표를 `<table>`로, `![alt](images/name.png)`를 `<img src="/manual/images/name.png" alt=...>`로 그린다. 허용 그림 이름 `/^[a-z0-9-]+\.png$/`.

- [ ] **Step 1: Write the failing tests** (`manual-reader-react.test.mjs`, 기존 React 시험처럼 vite 번들 + MinimalDom)
`표는 table로 그리고 셀 안 굵게·코드 표시는 글자만 남긴다` — 머리행 `th` 2개, 본문 `td` 텍스트 `x|y`, `굵게`.
`네 단계 제목은 h5로 그린다` — `#### 사용 순서` → `h5` 글자 `사용 순서`.
`그림은 /manual/images 안의 png만 img로 그린다` — `images/studio-panel.png` → `img[src="/manual/images/studio-panel.png"][alt="① 스튜디오 패널"]`; `../x.png`, `/etc/x.png`, `https://e.com/x.png`, `images/x.svg` → `img` 없음, 캡션 글자만.
`manual-hub.test.mjs`: 문서 1개 manifest를 받아들이고, 문서 3개·은퇴 ID·판 `1.0.0` manifest는 거부.
- [ ] **Step 2: Run** `node --test scripts/tests/manual-reader-react.test.mjs scripts/tests/manual-hub.test.mjs` → FAIL.
- [ ] **Step 3: Implement** 위 Interfaces대로. 표는 `|` 연속 줄 묶음, 둘째 줄 구분선 생략.
- [ ] **Step 4: Run** 같은 명령 → PASS.
- [ ] **Step 5: Commit** `feat(manual): in-app reader draws tables and manual images; one document`.

### Task 3: 매뉴얼 시험 — 한 권 기준과 새 검사 4개

**Files:**
- Modify: `scripts/tests/manual-content.test.mjs`
- Create: `scripts/tests/manual-structure.test.mjs`

**Interfaces:**
- Consumes: Task 1 산출물 경로, 4절 화면 목록.
- Produces: 화면 절 규칙 — 2부·3부 화면 절은 `### 2-<n> ` 또는 `### 3-<n> `로 시작, 하위 제목은 `#### 기능·목적` … `#### 관련`.

- [ ] **Step 1: Write the failing tests**
`manual-content.test.mjs`: `docs`를 한 권으로. S33 Provider 문구·조직 정책·라이선스·보호 admin·조직 가입 단언은 `daon-user-manual`에 그대로. 지식 원칙 7줄·용어 6줄 단언은 대상을 `daon-user-manual`의 `부록 B 용어집`과 `3-3` 절로 옮김. 은퇴 문서 파일이 `docs/manual`·`apps/web/public/manual`에 **없음**을 단언. 사본 동일성·manifest 결속은 1문서×3형식 + `images/*` 바이트 동일.
`manual-structure.test.mjs`:
- `화면 절은 여섯 제목을 순서대로 가진다` — 설계 4.2·4.3의 21개 절(2-1~2-11, 3-1~3-10) 각각.
- `화면 절마다 번호 그림이 하나 이상 있고 파일이 존재한다`.
- `굵게 쓴 버튼·메뉴 이름은 화면 문구에 있다` — `**…**` 중 화면 이름 후보(공백 포함 20자 이하, 한글 포함)를 `packages/ui/src`·`apps/web/components`·`apps/web/app`의 `.js/.jsx` 글자에서 찾음. 화면 문구가 아닌 강조는 시험 안 `NOT_UI_TEXT` 배열에 명시.
- `1부는 8단계이고 각 단계에 2부 연결이 있다` — `### 1-1`~`### 1-8`, 각 단계에 `자세히: 2-` 포함.
- [ ] **Step 2: Run** `node --test scripts/tests/manual-content.test.mjs scripts/tests/manual-structure.test.mjs` → FAIL(새 매뉴얼 없음). 이 실패는 Task 5·6이 끝나야 풀린다.
- [ ] **Step 3: Commit** `test(manual): pin one-manual structure, UI wording and copies`.

### Task 4: 그림 번호 표시 도구

**Files:**
- Create: `scripts/annotate-manual-images.py`, `docs/manual/daon-user-manual/images/annotations.json`
- Test: `scripts/tests/test_annotate_manual_images.py`

**Interfaces:**
- Produces: `annotate(source: Path, marks: list[dict], out: Path) -> None`. `marks` 항목 `{"n": 1, "x": 120, "y": 64}` 또는 가리기 `{"mask": [x, y, w, h]}`. `annotations.json` = `{ "<그림 이름>.png": [marks…] }`. 원본 `images/raw/<이름>.png` → 결과 `images/<이름>.png`.

- [ ] **Step 1: Write the failing tests** — `번호 원이 지정 좌표에 그려진다`(해당 픽셀 색이 표시 색), `가리기 영역은 단색으로 덮인다`, `원본 그림은 바뀌지 않는다`, `annotations.json에 없는 raw 그림이 있으면 실패한다`.
- [ ] **Step 2: Run** `PYDOC -m pytest scripts/tests/test_annotate_manual_images.py -q` → FAIL.
- [ ] **Step 3: Implement** — Pillow로 원 번호를 그린다: 지름 28px, 흰 테두리·진한 파랑 채움·흰 숫자(본문 표의 ①②③과 같은 번호). 글꼴은 Windows `malgun.ttf`, 없으면 기본 글꼴.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(manual): number markers and masks for manual screenshots`.

### Task 5: 매뉴얼 본문 작성

**Files:**
- Rewrite: `docs/manual/daon-user-manual/index.md`
- Delete: `docs/manual/daon-getting-started/`, `docs/manual/daon-knowledge-llm-guide/`

- [ ] **Step 1:** 현행 화면 문구를 모은다 — 각 화면 컴포넌트와 `*messages*.ko.js`에서 버튼·메뉴·상태·오류 문구 목록(작업 메모, 커밋 안 함).
- [ ] **Step 2:** 1부 8단계를 쓴다(설계 4.1 순서, 단계마다 "무엇을 → 따라 하기 → 끝났는지 확인 → 자세히: 2-n").
- [ ] **Step 3:** 2부 2-1~2-11, 3부 3-1~3-10을 5절 틀로 쓴다. 그림 줄은 `![① … ② …](images/<절 이름>.png)`, 주요 항목 표 번호와 맞춘다. 3부에 Global Constraints의 보존 문구를 넣는다. 옛 3권에서 아직 맞는 절차(계정·관리자 복구·모델 연결·라이선스·조직 정책)는 옮기고, 옛 Studio(필수 8설정·Library·검토·승인·전달)와 호스트 목록은 버린다.
- [ ] **Step 4:** 부록 A(오류 색인)·B(용어집: 원칙 7줄·용어 6줄 포함)·C(찾아보기)·D(제공 범위) 작성.
- [ ] **Step 5: Run** `node --test scripts/tests/manual-structure.test.mjs` → 그림 존재 시험만 FAIL, 나머지 PASS. 문구 대조 실패는 문구를 고치거나 `NOT_UI_TEXT`에 사유와 함께 추가.
- [ ] **Step 6: Commit** `docs(manual): rewrite as one manual (flow, screens, admin, appendix)`.

### Task 6: ysna 화면 촬영과 1부 실제 수행

**Files:**
- Create: `docs/manual/daon-user-manual/images/raw/*.png`, `images/*.png`, `annotations.json` 채움

- [ ] **Step 1:** 신산님께 앱 안 브라우저에서 ysna 관리자 로그인을 요청한다(어울은 비밀번호를 입력하지 않는다). 창 크기 1280×800.
- [ ] **Step 2:** 1부 순서대로 수행하며 찍는다 — 노트북 `[매뉴얼] 예시` 생성, 비밀 없는 예시 자료(공개 공고문 형식의 짧은 텍스트·PDF) 등록, 질문, 스튜디오 보고서 1개, 대화로 수정 1회, 문서 작성 분석까지. 막힌 단계는 기록하고 매뉴얼에 반영하거나 보고.
- [ ] **Step 3:** 2부·3부 나머지 화면을 찍는다. 관리자 화면은 키·이메일 칸을 비운 상태 또는 가리기 좌표로 처리.
- [ ] **Step 4:** `annotations.json`에 번호 좌표를 넣고 `PYDOC scripts/annotate-manual-images.py`를 실행, 결과 그림을 하나씩 열어 번호 위치와 가림을 확인.
- [ ] **Step 5:** 시험 노트북을 영구 삭제하고 목록에서 사라졌는지 확인(그 밖에 만든 산출물·자료 포함).
- [ ] **Step 6: Run** `node --test scripts/tests/manual-structure.test.mjs` → PASS. **Commit** `docs(manual): screenshots with numbered markers`.

### Task 7: 빌드·은퇴 정리·전체 시험·병합

**Files:**
- Modify: `scripts/build-phase-c3-manual-evidence-manifest.mjs`(은퇴 문서 경로 제거), 은퇴 ID를 참조하는 나머지 파일(`git grep -n "daon-getting-started\|daon-knowledge-llm-guide"` 결과 전부)
- Generated: `docs/manual/dist/*`, `apps/web/public/manual/*`, `docs/manual/release-manifest.json`

- [ ] **Step 1:** `PYDOC scripts/build-daon-manuals.py all` → 성공, pdf 쪽수와 첫 쪽 글자(`pypdf`)로 한글이 보이는지 확인.
- [ ] **Step 2:** `git grep -n "daon-getting-started\|daon-knowledge-llm-guide"` → 결과 0(이력 문서 `WORK_STATUS.md`·작업지시서 제외).
- [ ] **Step 3: Run** `node --test scripts/tests/manual-*.test.mjs` → PASS, API 전체 `pytest`와 `node --test scripts/tests/*.test.mjs` → 실패 목록이 기준선(scratchpad `a.txt`)보다 늘지 않음.
- [ ] **Step 4:** `WORK_STATUS.md`에 결과 행 추가, 설계서 상태를 "완료"로. PR Broker로 병합.
- [ ] **Step 5:** ysna 배포안(대상·커밋·영향·검증: `/manual/daon-user-manual.md` 해시 = 원본, `/manual/images/*.png` 200·rollback)을 신산님께 제시하고 승인 후 배포.
