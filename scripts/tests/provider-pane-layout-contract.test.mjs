// Provider 설정이 노트북 설정 창(모달) 안에 들어갈 때도 세 창 배치(flex 세로)를 써야 한다.
// packages/ui/src/workspace.css의 `.provider-settings-shell.is-embedded { display: grid }`가 더 구체적이라
// 같은 구체성으로는 덮이지 않는다 → 설정 창 안 규칙에서 flex 배치를 명시한다(레이아웃 시험 가짜 화면은 workspace.css를 읽지 않음).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const providerCss = await readFile(new URL("../../apps/web/app/settings/model-connections/provider-settings.css", import.meta.url), "utf8");
const workspaceCss = await readFile(new URL("../../packages/ui/src/workspace.css", import.meta.url), "utf8");

function rulesFor(css, selector) {
  // 선택자 목록이 정확히 selector 하나인 규칙의 본문들
  const bodies = [];
  for (const block of css.split("}")) {
    const open = block.indexOf("{");
    if (open < 0) continue;
    const head = block.slice(0, open).replace(/\/\*[\s\S]*?\*\//g, "").trim();
    if (head === selector) bodies.push(block.slice(open + 1));
  }
  return bodies;
}

test("workspace.css는 임베디드 틀을 grid로 둔다(이 시험의 전제)", () => {
  assert.ok(rulesFor(workspaceCss, ".provider-settings-shell.is-embedded").some((body) => /display:\s*grid/u.test(body)));
});

test("설정 창 안 임베디드 틀은 더 구체적인 선택자로 flex 세로 배치를 명시한다", () => {
  const bodies = rulesFor(providerCss, ".workspace-modal .provider-settings-shell.is-embedded").join(";");
  assert.match(bodies, /display:\s*flex/u);
  assert.match(bodies, /flex-direction:\s*column/u);
  assert.match(bodies, /overflow-y:\s*auto/u);
});
