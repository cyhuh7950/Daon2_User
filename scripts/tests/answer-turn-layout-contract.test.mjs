// 후속 A-4·A-5: 답변 아래 근거 칩에 같은 이름이 두 번 보였고, "근거 부족"·"승인 지식 사용" 같은 상태 줄이
// 칩·답변 과정(38px 들여쓰기)과 달리 왼쪽 끝에 붙어 어긋났다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (file) => readFile(new URL(`../../${file}`, import.meta.url), "utf8");
const [shell, css] = await Promise.all([read("packages/ui/src/product-workspace-shell.jsx"), read("packages/ui/src/workspace.css")]);

test("답변 근거 칩 이름은 같은 이름끼리 순번을 붙여 만든다", () => {
  const block = shell.slice(shell.indexOf("const renderCitations"), shell.indexOf("return turns.map"));
  assert.match(block, /numberDuplicateLabels\(/u);
});

test("답변 아래 상태 줄은 근거 칩과 같은 38px 들여쓰기를 쓴다", () => {
  assert.match(css, /\.conversation-turn > \.context-selection-status \{[^}]*margin:\s*4px 38px 0/u);
});
