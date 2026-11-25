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
  // N1-B15: 설정 페이지도 공용 ManualHubView를 쓰고, 부품이 ManualMarkdown으로 본문을 그린다.
  const view = await read("packages/ui/src/manual-hub-view.jsx");
  assert.equal(JSON.parse(manifest).exports["./manual-hub-view"], "./src/manual-hub-view.jsx");
  assert.match(pane, /<ManualHubView\b/u);
  assert.match(view, /import \{ ManualMarkdown \} from "\.\/manual-markdown\.jsx";/u);
  assert.match(view, /<ManualMarkdown text=\{opened\.text\} \/>/u);
  assert.doesNotMatch(view, /<pre>/u);
});

test("설정 설명서 화면 CSS는 표·그림·제목을 꾸민다", async () => {
  const css = await read("packages/ui/src/manual-hub.css");
  for (const selector of [".manual-reader-table", ".manual-reader-figure img", ".manual-reader-body h5", ".manual-reader-list"]) {
    assert.ok(css.includes(selector), `${selector} 없음`);
  }
});
