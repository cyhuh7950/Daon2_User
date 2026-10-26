// Studio 화면의 L10N 규칙(S6-02): 화면 문구는 카탈로그 키로만 쓴다. 코드에 한글 문구를 직접 두지 않는다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

import { STUDIO_MESSAGES } from "../../packages/ui/src/studio-messages.ko.js";

const SRC = path.resolve(import.meta.dirname, "../../packages/ui/src");
const FILES = ["studio-panel.jsx", "studio-dialogs.jsx", "studio-viewers.jsx", "studio-editor.jsx", "authoring-wizard.jsx", "notebook-menu.jsx", "authoring-templates-pane.jsx", "export-policy-pane.jsx"];

const stripComments = (code) => code.replace(/\/\*[\s\S]*?\*\//gu, "").split("\n").map((line) => line.replace(/(^|[^:"'`])\/\/.*$/u, "$1")).join("\n");

for (const file of FILES) {
  test(`${file}: 한글 문구를 직접 쓰지 않는다`, async () => {
    const code = stripComments(await readFile(path.join(SRC, file), "utf8"));
    const offenders = code.split("\n").map((line, index) => [index + 1, line]).filter(([, line]) => /[가-힣]/u.test(line));
    assert.deepEqual(offenders.map(([n, line]) => `${file}:${n} ${line.trim().slice(0, 80)}`), []);
  });

  test(`${file}: 쓰는 msg 키가 모두 카탈로그에 있다`, async () => {
    const code = await readFile(path.join(SRC, file), "utf8");
    const keys = [...code.matchAll(/\bmsg\(\s*"([a-z0-9_.]+)"/gu)].map((m) => m[1]);
    const missing = keys.filter((key) => typeof STUDIO_MESSAGES[key] !== "string");
    assert.deepEqual(missing, []);
  });
}

test("카탈로그 값에 치환자({name})가 있으면 이름이 영문 소문자·밑줄이다", () => {
  for (const [key, value] of Object.entries(STUDIO_MESSAGES)) {
    for (const [, name] of value.matchAll(/\{(\w+)\}/gu)) assert.match(name, /^[a-z_]+$/u, key);
  }
});
