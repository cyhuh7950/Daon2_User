// 좁은 화면(820px 이하) 노트북 작업 화면: 하단 탭으로 한 면만 보이는데도 높이 고정이 풀려 페이지 전체가 스크롤됐다
// (800×900에서 대화 면 칸 2,069px·페이지 2,317px). 신산님 창 배치 원칙: 창을 먼저 배치하고, 넘침은 창 안에서 스크롤,
// 페이지 전체에는 스크롤이 없어야 한다. 설계 승인 2026-11-25.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (file) => readFile(new URL(`../../${file}`, import.meta.url), "utf8");
const sources = { workspace: await read("packages/ui/src/workspace.css"), polish: await read("packages/ui/src/workspace-polish.css") };

// @media (max-width: 820px) { ... } 블록 본문들(중첩 괄호 고려)
function narrowBlocks(css) {
  const out = [];
  let at = 0;
  while ((at = css.indexOf("@media (max-width: 820px)", at)) >= 0) {
    let i = css.indexOf("{", at) + 1;
    let depth = 1;
    const start = i;
    while (depth > 0 && i < css.length) { if (css[i] === "{") depth += 1; else if (css[i] === "}") depth -= 1; i += 1; }
    out.push(css.slice(start, i - 1));
    at = i;
  }
  return out.join("\n");
}
const narrow = narrowBlocks(sources.workspace) + "\n" + narrowBlocks(sources.polish);
const rule = (selector) => {
  const found = [];
  for (const block of narrow.split("}")) {
    const open = block.indexOf("{");
    if (open >= 0 && block.slice(0, open).replace(/\/\*[\s\S]*?\*\//g, "").trim() === selector) found.push(block.slice(open + 1));
  }
  return found.join(";");
};

test("좁은 화면에서도 작업 화면은 화면 높이에 고정되고 페이지 전체가 스크롤되지 않는다", () => {
  assert.doesNotMatch(narrow, /height:\s*auto/u);
  assert.doesNotMatch(narrow, /overflow:\s*visible/u);
  assert.doesNotMatch(narrow, /min-height:\s*480px/u);
  const shell = rule(".adaptive-workspace[data-product-workspace-state]");
  assert.match(shell, /height:\s*100dvh/u);
  assert.match(shell, /min-height:\s*0/u);
  assert.match(shell, /overflow:\s*hidden/u);
});

test("고른 면 하나가 머리줄과 하단 탭 사이 높이를 채우고, 넘침은 그 면 안에서 스크롤한다", () => {
  const panes = rule('.adaptive-workspace .workspace-panes[data-layout="source-conversation-studio"]');
  assert.match(panes, /grid-template-rows:\s*minmax\(0,\s*1fr\)/u);
  assert.match(panes, /min-height:\s*0/u);
  assert.match(panes, /overflow:\s*hidden/u);
  assert.match(narrow, /\[data-narrow-active="conversation"\] \.pane-slot:not\(:has\(#product-pane-conversation\)\)/u);
});

test("하단 탭 자리는 작업 화면 아래 여백 한 곳에서만 잡는다(칸 묶음 아래 여백 0, 빈 띠 없음)", () => {
  // 1023px 이하 규칙의 칸 묶음 padding-bottom: 52px와 820px 이하 화면 padding-bottom: 64px가 겹쳐 칸 아래에 약 60px 빈 띠가 생겼다.
  assert.match(rule('.adaptive-workspace .workspace-panes[data-layout="source-conversation-studio"]'), /padding-bottom:\s*0/u);
});
