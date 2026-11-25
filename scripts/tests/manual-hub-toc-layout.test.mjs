// N1-B15 (UAT-14): 설명서 창 위쪽이 비고(격자 줄 높이 미지정), "목록 보기"를 눌러도 목차가 없었다.
// 설계(신산님 승인 2026-11-25): 위 도구줄 고정 + 아래 두 칸(왼쪽 문서·목차, 오른쪽 본문), 칸 안에서만 스크롤,
// 문서를 열면 목차, 절을 누르면 그 절로 이동, 검색은 절 이름도 거름, "목록 보기" 없음, 문서가 하나면 바로 연다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const shell = await readFile(new URL("../../packages/ui/src/product-workspace-shell.jsx", import.meta.url), "utf8");
const css = await readFile(new URL("../../packages/ui/src/workspace.css", import.meta.url), "utf8");
const hub = shell.slice(shell.indexOf('modalView === "manual"'), shell.indexOf('className="operations-status-grid"'));

function rules(selector) {
  const bodies = [];
  for (const block of css.split("}")) {
    const open = block.indexOf("{");
    if (open < 0) continue;
    const head = block.slice(0, open).replace(/\/\*[\s\S]*?\*\//g, "").trim();
    if (head === selector) bodies.push(block.slice(open + 1));
  }
  return bodies.join(";");
}

test("설명서 창에는 '목록 보기'가 없고, 문서를 열면 왼쪽에 목차가 있다", () => {
  assert.ok(hub.length > 0, "설명서 창 구간을 찾아야 한다");
  assert.doesNotMatch(hub, /목록 보기/u);
  assert.match(hub, /className="manual-toc"/u);
  assert.match(hub, /aria-label="설명서 목차"/u);
});

test("목차는 검색어로 거르고, 절을 누르면 본문이 그 절로 이동하며 지금 절을 표시한다", () => {
  assert.match(shell, /import \{[^}]*filterManualToc[^}]*manualToc[^}]*\} from "\.\/manual-toc\.js"/u);
  assert.match(hub, /filterManualToc\(/u);
  assert.match(hub, /scrollIntoView/u);
  assert.match(hub, /aria-current=/u);
});

test("문서가 하나뿐이면 창을 열 때 바로 그 문서를 연다", () => {
  assert.match(shell, /documents\.length === 1[\s\S]{0,200}readManual\(/u);
});

test("창 배치: 도구줄은 늘어나지 않고 아래 두 칸이 남은 높이를 채우며, 칸 안에서만 세로 스크롤한다", () => {
  const hubRule = rules(".manual-hub");
  assert.match(hubRule, /display:\s*flex/u);
  assert.match(hubRule, /flex-direction:\s*column/u);
  assert.match(hubRule, /height:\s*min\(/u);
  assert.match(rules(".manual-hub-toolbar"), /flex:\s*none/u);
  const layout = rules(".manual-hub-layout");
  assert.match(layout, /flex:\s*1 1 auto/u);
  assert.match(layout, /min-height:\s*0/u);
  assert.match(rules(".manual-hub-side"), /overflow-y:\s*auto/u);
  assert.match(rules(".manual-reader-body"), /overflow:\s*auto|overflow-y:\s*auto/u);
});
