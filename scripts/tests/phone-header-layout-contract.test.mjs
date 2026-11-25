// 휴대폰 폭(375px)에서 노트북 머리줄의 상태 표시와 글자 버튼 5개가 세 줄로 접혀 위쪽 약 180px를 차지했다.
// 설계(신산님 승인 2026-11-25): 600px 이하에서만 머리줄 한 줄, 상태는 색 점만, 버튼 5개는 아이콘 버튼(이름은 낭독·설명으로 유지).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (file) => readFile(new URL(`../../${file}`, import.meta.url), "utf8");
const [shell, menu, css] = await Promise.all([read("packages/ui/src/product-workspace-shell.jsx"), read("packages/ui/src/notebook-menu.jsx"), read("packages/ui/src/workspace-polish.css")]);

function block(source, query) {
  const at = source.indexOf(query);
  if (at < 0) return "";
  let i = source.indexOf("{", at) + 1; const start = i; let depth = 1;
  while (depth > 0 && i < source.length) { if (source[i] === "{") depth += 1; else if (source[i] === "}") depth -= 1; i += 1; }
  return source.slice(start, i - 1);
}

test("머리줄 버튼 5개는 아이콘과 글자 칸을 함께 갖고, 이름을 낭독·설명으로 남긴다", () => {
  assert.match(menu, /className="notebook-create"[^>]*aria-label=\{msg\("notebook\.create"\)\}[^>]*title=/u);
  assert.match(menu, /<StudioIcon name="add"[^>]*className="app-action-icon"/u);
  assert.match(menu, /className="notebook-share"[^>]*aria-label=\{msg\("notebook\.share"\)\}/u);
  assert.match(menu, /<StudioIcon name="share"[^>]*className="app-action-icon"/u);
  assert.match(menu, /<span className="app-action-label">\{msg\("notebook\.create"\)\}<\/span>/u);
  assert.match(shell, /aria-label="운영상태" title="운영상태"[^>]*>[\s\S]{0,120}<StudioIcon name="chart"[^>]*className="app-action-icon"[\s\S]{0,80}<span className="app-action-label">운영상태<\/span>/u);
  assert.match(shell, /aria-label="설정" title="설정"[^>]*>[\s\S]{0,120}<StudioIcon name="settings_sliders"[^>]*className="app-action-icon"[\s\S]{0,80}<span className="app-action-label">설정<\/span>/u);
});

test("넓은 화면은 지금처럼 글자 버튼(아이콘 숨김)이다", () => {
  assert.match(css, /\.workspace-app-bar \.app-action-icon \{\s*display:\s*none;?\s*\}/u);
});

test("600px 이하: 머리줄 한 줄, 이름 줄임, 상태는 점만, 버튼은 36px 아이콘(글자는 화면에서만 숨김)", () => {
  const phone = block(css, "@media (max-width: 600px)");
  assert.ok(phone, "600px 이하 규칙이 있어야 한다");
  assert.match(phone, /\.workspace-app-bar[^{]*\{[^}]*flex-wrap:\s*nowrap/u);
  assert.match(phone, /\.workspace-brand h1[^{]*\{[^}]*text-overflow:\s*ellipsis/u);
  assert.match(phone, /\.workspace-app-bar \.app-action-icon \{[^}]*display:\s*inline-block/u);
  assert.match(phone, /\.workspace-app-bar \.app-action-label[^{]*\{[^}]*clip:\s*rect\(0 0 0 0\)/u);
  assert.match(phone, /\.workspace-app-actions button[^{]*\{[^}]*width:\s*36px/u);
  assert.match(phone, /\.workspace-status \.status-text[^{]*\{[^}]*clip:\s*rect\(0 0 0 0\)/u);
});
