// 설정 → 사용자 설명서 화면도 앱 안 설명서 창과 같은 부품으로 표·그림을 그린다(원문 <pre> 금지).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "../..");
const read = (file) => readFile(path.join(root, file), "utf8");

test("설정 설명서 화면은 ManualMarkdown으로 본문을 그린다", async () => {
  const [pane, manifest] = await Promise.all([read("apps/web/components/manual-settings-pane.jsx"), read("packages/ui/package.json")]);
  assert.equal(JSON.parse(manifest).exports["./manual-markdown"], "./src/manual-markdown.jsx");
  assert.match(pane, /import \{ ManualMarkdown \} from "@daon2-user\/ui\/manual-markdown";/u);
  assert.match(pane, /<ManualMarkdown text=\{selected\.text\} \/>/u);
  assert.doesNotMatch(pane, /<pre>\{selected\.text\}<\/pre>/u);
});

test("설정 설명서 화면 CSS는 표·그림·제목을 꾸민다", async () => {
  const css = await read("apps/web/app/globals.css");
  for (const selector of [".manual-page-reader .manual-reader-table", ".manual-page-reader .manual-reader-figure img", ".manual-page-reader .manual-reader-body h5", ".manual-page-reader .manual-reader-list"]) {
    assert.ok(css.includes(selector), `${selector} 없음`);
  }
});
