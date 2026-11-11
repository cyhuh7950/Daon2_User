// 설명서 촬영 중 ysna 실제 화면에서 찾은 화면 결함(2026-11-11)이 다시 생기지 않게 고정한다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const root = path.resolve(import.meta.dirname, "../..");
const read = (file) => readFile(path.join(root, file), "utf8");
const load = (file) => import(pathToFileURL(path.join(root, file)).href);

test("스튜디오 타일 연필은 타일 묶음에 마우스를 올리거나 초점이 가면 보인다", async () => {
  // 연필은 .studio-tile의 형제라서 .studio-tile:hover 아래 선택자로는 영영 보이지 않았다.
  const [panel, css] = await Promise.all([read("packages/ui/src/studio-panel.jsx"), read("packages/ui/src/studio-panel.css")]);
  assert.match(panel, /<div key=\{typeId\} className="studio-tile-wrap"/u);
  assert.match(css, /\.studio-tile-wrap:hover \.studio-tile__edit, \.studio-tile-wrap:focus-within \.studio-tile__edit \{ display: inline-flex; \}/u);
  assert.match(css, /@media \(hover: none\) \{ \.studio-tile__edit \{ display: inline-flex; \} \}/u);
  assert.doesNotMatch(css, /\.studio-tile:hover \.studio-tile__edit/u);
});

test("설정 창 체크칸은 입력칸 폭으로 늘어나지 않는다", async () => {
  const css = await read("packages/ui/src/studio-panel.css");
  assert.match(css, /\.studio-dialog input:not\(\[type="checkbox"\]\):not\(\[type="radio"\]\)/u);
  assert.match(css, /\.studio-dialog label:has\(> input\[type="checkbox"\]\) \{ display: flex;/u);
});

test("아이콘 없는 메뉴 항목은 글자가 두 칸을 모두 쓴다(노트북 ⋮ 메뉴 세로 줄바꿈)", async () => {
  const css = await read("packages/ui/src/workspace.css");
  assert.match(css, /\.settings-menu > button > span:only-child \{ grid-column: 1 \/ -1; \}/u);
});

test("실패한 Source 줄은 재처리 버튼이 다음 줄로 내려가고 파일 이름 자리를 남긴다", async () => {
  const css = await read("packages/ui/src/workspace-polish.css");
  assert.match(css, /\.source-list-row > button:not\(\.source-action-trigger\):not\(\.source-retry-button\) \{ flex: 1 1 140px;/u);
  assert.match(css, /\.source-list-row > \.source-retry-button \{[^}]*margin-left: auto;/u);
});

test("새 메모 제목은 서버 UTC가 아니라 사용자의 현지 시각으로 붙는다", async () => {
  const { localMemoTitle } = await load("apps/web/lib/memo-title.js");
  assert.equal(localMemoTitle(new Date(2026, 10, 11, 8, 2)), "메모 2026-11-11 08:02");
  const adapter = await read("apps/web/lib/studio-v2-adapter.js");
  assert.match(adapter, /createMemo: \(input\) => createStudioMemo\(workspaceId, scope\(\{ \.\.\.input, title: input\?\.title \?\? localMemoTitle\(\) \}\)\)/u);
});

test("알림 시각은 읽기 쉬운 현지 시각이고 Trace ID 원문은 보이지 않는다", async () => {
  const { formatNotificationTime } = await load("packages/ui/src/notification-time.js");
  const shown = formatNotificationTime("2026-11-10T22:44:14.561771+00:00", { timeZone: "Asia/Seoul" });
  assert.match(shown, /2026/u);
  assert.match(shown, /7:44/u);
  assert.doesNotMatch(shown, /T22|\+00:00/u);
  assert.equal(formatNotificationTime(null), "기한 없음");
  const pane = await read("packages/ui/src/notification-inbox-pane.jsx");
  assert.doesNotMatch(pane, /· Trace \{/u);
  assert.match(pane, /formatNotificationTime\(item\.created_at \?\? item\.due_at\)/u);
});

test("운영 상태 화면은 operations 스타일이 있는 workspace.css를 불러온다", async () => {
  // 시험이 recovery-workspace.jsx를 직접 묶으므로 CSS는 Next 페이지 파일에서 불러온다.
  const [page, manifest] = await Promise.all([read("apps/web/app/operations/page.jsx"), read("packages/ui/package.json")]);
  assert.equal(JSON.parse(manifest).exports["./workspace.css"], "./src/workspace.css");
  assert.match(page, /^import "@daon2-user\/ui\/workspace\.css";$/mu);
});
