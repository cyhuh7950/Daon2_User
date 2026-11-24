// N1-B12 (UAT-09): 좁은 스튜디오 창의 슬라이드 보기에서 장 목록 글자가 겹치고 슬라이드 본문 위쪽이 잘렸다.
// 창 배치 원칙: 칸마다 내용이 넘치면 그 칸 안에서 스크롤하고, 글자를 겹치거나 잘라 숨기지 않는다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const css = await readFile(new URL("../../packages/ui/src/studio-panel.css", import.meta.url), "utf8");
const viewer = await readFile(new URL("../../packages/ui/src/studio-viewers.jsx", import.meta.url), "utf8");

function rulesFor(selector) {
  const bodies = [];
  for (const block of css.split("}")) {
    const open = block.indexOf("{");
    if (open < 0) continue;
    const head = block.slice(0, open).replace(/\/\*[\s\S]*?\*\//g, "").trim();
    if (head === selector) bodies.push(block.slice(open + 1));
  }
  return bodies.join(";");
}

test("장 목록 버튼은 높이 제한 목록 안에서 줄어들지 않는다(글자 겹침 방지)", () => {
  assert.match(rulesFor(".studio-thumb"), /flex:\s*none/u);
  assert.match(rulesFor(".studio-thumbs"), /overflow-y:\s*auto/u);
});

test("슬라이드 본문은 넘치면 숨기지 않고 슬라이드 칸 안에서 세로 스크롤한다", () => {
  const slide = rulesFor(".studio-slide");
  assert.match(slide, /overflow-y:\s*auto/u);
  assert.doesNotMatch(slide, /overflow:\s*hidden/u);
});

test("표지 장의 가운데 정렬은 넘칠 때 위쪽을 잘라내지 않는 safe center를 쓴다", () => {
  assert.match(viewer, /justifyContent:\s*"safe center"/u);
});

test("슬라이드 보기 너비가 좁으면(창 기준) 장 목록을 위쪽 가로 줄로 옮긴다", () => {
  assert.match(rulesFor(".studio-slides"), /container-type:\s*inline-size/u);
  assert.match(css, /@container\s*\(max-width:\s*\d+px\)\s*\{[^@]*\.studio-slides\s*\{[^}]*grid-template-columns:\s*1fr/u);
});
