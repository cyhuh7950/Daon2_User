import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { TILE_ORDER } from "../../packages/ui/src/studio-panel-model.js";
import { STUDIO_MESSAGES } from "../../packages/ui/src/studio-messages.ko.js";
import { STUDIO_ICONS, STUDIO_TYPE_STYLE } from "../../packages/ui/src/studio-icon-data.js";

const root = path.resolve(import.meta.dirname, "../..");
const read = (file) => readFileSync(path.join(root, file), "utf8");

test("web_page 타일이 순서·아이콘·문구에 연결된다", () => {
  assert.ok(TILE_ORDER.includes("web_page"));
  assert.equal(TILE_ORDER.at(-1), "web_page");
  assert.equal(STUDIO_TYPE_STYLE.web_page.labelKey, "studio.tile.web_page");
  assert.ok(Object.hasOwn(STUDIO_ICONS, STUDIO_TYPE_STYLE.web_page.icon));
  assert.ok(STUDIO_MESSAGES["studio.tile.hint.web_page"]);
});

test("설정 창에 page_request 입력이 maxLength 2000, required로 있고 빈칸이면 만들기가 꺼진다", () => {
  const source = read("packages/ui/src/studio-dialogs.jsx");
  assert.match(source, /properties\.page_request/u);
  assert.match(source, /<textarea id="studio-page-request" maxLength=\{2000\} required/u);
  assert.match(source, /settings\.page_request = pageRequest\.trim\(\)/u);
  assert.match(source, /pageRequestMissing = Boolean\(properties\.page_request\) && !pageRequest\.trim\(\)/u);
  assert.match(source, /type="submit"[^>]*disabled=\{pageRequestMissing \|\| loading\}/u);
});

test("설정을 바꿔 다시 만들 때 출력 상세를 읽어 지난 요청 글을 채우고, 읽는 동안 버튼이 꺼진다", () => {
  const panel = read("packages/ui/src/studio-panel.jsx");
  assert.match(panel, /studio\.getOutput\(dialog\.output\.output_id\)/u);
  assert.match(panel, /page_request: regenSettings\?\.page_request/u);
  assert.match(panel, /loading=\{regenLoading\}/u);
  const dialogs = read("packages/ui/src/studio-dialogs.jsx");
  assert.match(dialogs, /loading = false/u);
  assert.match(dialogs, /disabled=\{pageRequestMissing \|\| loading\}/u);
  assert.match(dialogs, /setPageRequest\(String\(initial\.page_request/u);
});

test("web_page 문구 키가 모두 있다", () => {
  const expected = {
    "studio.tile.web_page": "웹 페이지",
    "studio.web_page.request": "요청 글",
    "studio.web_page.excluded": "근거 부족으로 뺀 내용 {n}건",
    "studio.web_page.include_sources": "출처 목록 넣기",
    "studio.progress.web_page.content": "내용 만드는 중",
    "studio.progress.web_page.html": "페이지 만드는 중",
  };
  for (const [key, text] of Object.entries(expected)) assert.equal(STUDIO_MESSAGES[key], text, key);
  assert.ok(STUDIO_MESSAGES["studio.web_page.request.hint"]);
});

test("대화로 고치기 유형에 web_page가 있고, 예전 제품 스튜디오 화면에는 없다(최종 검토 I5)", () => {
  assert.match(read("packages/ui/src/studio-chat-edit.jsx"), /CHAT_EDIT_TYPES = \[[^\]]*"web_page"/u);
  assert.doesNotMatch(read("apps/web/lib/product-workspace-api.js"), /STUDIO_OUTPUT_TYPES = new Set\(\[[^\]]*"web_page"/u);
  assert.doesNotMatch(read("packages/ui/src/product-studio-model.js"), /web_page/u);
});

test("출처 목록 넣기 메뉴 항목은 키보드 초점 테두리가 보인다(최종 검토 M3)", () => {
  assert.match(read("packages/ui/src/studio-panel.css"), /\.studio-panel \.studio-menu__check:focus-visible \{ outline: 3px solid var\(--studio-focus\); \}/u);
});

test("요청 글이 필요한 유형은 타일을 눌러도 바로 만들지 않고 설정 창을 연다", () => {
  const panel = read("packages/ui/src/studio-panel.jsx");
  assert.match(panel, /settings_schema\?\.properties\?\.page_request\) setDialog\(\{ kind: "settings", typeId \}\)/u);
});

test("노트북 화면은 포커스가 앱 안 웹 페이지 iframe으로 옮겨 갈 때 화면을 가리지 않는다", () => {
  const workspace = read("apps/web/components/notebook-product-workspace.jsx");
  const onBlur = workspace.match(/const onBlur = \(\) => \{[\s\S]*?\n    \};/u)?.[0] ?? "";
  assert.match(onBlur, /document\.activeElement instanceof HTMLIFrameElement && document\.hasFocus\(\)/u);
  assert.match(onBlur, /conceal\(\)/u);
  assert.match(workspace, /if \(document\.visibilityState === "hidden"\) conceal\(\)/u);
});
