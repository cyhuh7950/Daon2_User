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
  assert.match(source, /type="submit"[^>]*disabled=\{pageRequestMissing\}/u);
});

test("설정을 바꿔 다시 만들 때 지난 요청 글이 채워진다", () => {
  assert.match(read("packages/ui/src/studio-panel.jsx"), /page_request: dialog\.output\.settings\?\.page_request/u);
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

test("대화로 고치기 유형과 API 허용 유형에 web_page가 있다", () => {
  assert.match(read("packages/ui/src/studio-chat-edit.jsx"), /CHAT_EDIT_TYPES = \[[^\]]*"web_page"/u);
  assert.match(read("apps/web/lib/product-workspace-api.js"), /STUDIO_OUTPUT_TYPES = new Set\(\[[^\]]*"web_page"/u);
  assert.match(read("packages/ui/src/product-studio-model.js"), /id: "web_page", label: "웹 페이지", formats: \["html"\]/u);
});
