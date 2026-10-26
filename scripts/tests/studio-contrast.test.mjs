// Studio 패널 색 토큰의 본문 글자 대비(S6-01): 일반 텍스트 4.5:1 이상. 라이트·다크 모두 확인한다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const css = await readFile(path.resolve(import.meta.dirname, "../../packages/ui/src/studio-panel.css"), "utf8");

function tokens(selectorStart) {
  const start = css.indexOf(selectorStart);
  assert.ok(start >= 0, selectorStart);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/--(studio-[a-z-]+):\s*(#[0-9a-fA-F]{6});/gu)].map((m) => [m[1], m[2]]));
}

const channel = (value) => { const v = value / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
const luminance = (hex) => { const n = Number.parseInt(hex.slice(1), 16); return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255); };
const contrast = (a, b) => { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

const PAIRS = [
  ["studio-text", "studio-surface"], ["studio-text", "studio-tile"], ["studio-text", "studio-tile-hover"],
  ["studio-muted", "studio-surface"], ["studio-muted", "studio-tile"],
  ["studio-primary-text", "studio-primary"], ["studio-danger", "studio-surface"], ["studio-primary", "studio-surface"],
];

for (const [name, selector] of [["라이트", ".studio-panel {"], ["다크", ':root[data-theme="dark"] .studio-panel {']]) {
  test(`${name} 테마의 글자 대비는 4.5:1 이상이다`, () => {
    const t = tokens(selector);
    for (const [foreground, background] of PAIRS) {
      assert.ok(t[foreground] && t[background], `${foreground}/${background}`);
      const ratio = contrast(t[foreground], t[background]);
      assert.ok(ratio >= 4.5, `${name} ${foreground} ${t[foreground]} / ${background} ${t[background]} = ${ratio.toFixed(2)}`);
    }
  });
}

test("기본(primary) 버튼 글자색은 `.studio-panel button { color: inherit }`에 덮이지 않는다", async () => {
  const { readFile } = await import("node:fs/promises");
  const css = await readFile(new URL("../../packages/ui/src/studio-panel.css", import.meta.url), "utf8");
  const lines = css.split(/\r?\n/u);
  const inherit = lines.findIndex((line) => line.startsWith(".studio-panel button {") && line.includes("color: inherit"));
  const fix = lines.findIndex((line) => line.includes(".studio-panel .studio-fab") && line.includes(".studio-panel .studio-btn--primary") && line.includes("--studio-primary-text"));
  assert.ok(inherit >= 0, "상속 규칙이 있다");
  assert.ok(fix > inherit, "같은 명시도의 덮어쓰기 규칙이 뒤에 있다");
});
