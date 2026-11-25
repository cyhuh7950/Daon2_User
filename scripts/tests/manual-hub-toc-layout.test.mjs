// N1-B15 (UAT-14): 설명서 창 위쪽이 비고(격자 줄 높이 미지정), "목록 보기"를 눌러도 목차가 없었다.
// 설계(신산님 승인 2026-11-25): 위 도구줄 고정 + 아래 두 칸(왼쪽 문서·목차, 오른쪽 본문), 칸 안에서만 스크롤,
// 문서를 열면 목차, 절을 누르면 그 절로 이동, 검색은 절 이름도 거름, "목록 보기" 없음, 문서가 하나면 바로 연다.
// 재인수에서 노트북 목록의 설정 → 설명서(/settings/manual)가 옛 화면이었다 → 두 곳이 같은 공용 부품을 쓴다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (file) => readFile(new URL(`../../${file}`, import.meta.url), "utf8");
const [view, shell, pane, css, globals] = await Promise.all([
  read("packages/ui/src/manual-hub-view.jsx"),
  read("packages/ui/src/product-workspace-shell.jsx"),
  read("apps/web/components/manual-settings-pane.jsx"),
  read("packages/ui/src/manual-hub.css"),
  read("apps/web/app/globals.css"),
]);

function rules(source, selector) {
  const bodies = [];
  for (const block of source.split("}")) {
    const open = block.indexOf("{");
    if (open < 0) continue;
    const head = block.slice(0, open).replace(/\/\*[\s\S]*?\*\//g, "").trim();
    if (head === selector) bodies.push(block.slice(open + 1));
  }
  return bodies.join(";");
}

test("노트북 안 설명서 창과 설정 → 설명서 페이지가 같은 공용 부품을 쓴다", () => {
  assert.match(shell, /import \{ ManualHubView \} from "\.\/manual-hub-view\.jsx";/u);
  assert.match(shell, /<ManualHubView\b/u);
  assert.match(pane, /import \{ ManualHubView \} from "@daon2-user\/ui\/manual-hub-view";/u);
  assert.match(pane, /<ManualHubView\b/u);
  for (const [name, source] of [["shell", shell], ["pane", pane], ["view", view]]) assert.doesNotMatch(source, /목록 보기/u, name);
});

test("공용 부품: 문서를 열면 왼쪽에 목차, 검색으로 거르기, 절로 이동, 지금 절 표시·따라가기, 문서가 하나면 바로 열기", () => {
  assert.match(view, /import \{[^}]*filterManualToc[^}]*manualToc[^}]*\} from "\.\/manual-toc\.js"/u);
  assert.match(view, /import "\.\/manual-hub\.css";/u);
  assert.match(view, /className="manual-toc"/u);
  assert.match(view, /aria-label="설명서 목차"/u);
  assert.match(view, /filterManualToc\(/u);
  assert.match(view, /scrollIntoView\(\{ block: "start" \}\)/u);
  assert.match(view, /scrollIntoView\(\{ block: "nearest" \}\)/u);
  assert.match(view, /aria-current=/u);
  assert.match(view, /documents\.length === 1[\s\S]{0,160}onRead\?\.\(/u);
  assert.match(view, /<ManualMarkdown text=\{opened\.text\} \/>/u);
});

test("창 배치: 도구줄은 늘어나지 않고 아래 두 칸이 남은 높이를 채우며, 칸 안에서만 세로 스크롤한다", () => {
  const hub = rules(css, ".manual-hub");
  assert.match(hub, /display:\s*flex/u);
  assert.match(hub, /flex-direction:\s*column/u);
  assert.match(rules(css, ".manual-hub-toolbar"), /flex:\s*none/u);
  const layout = rules(css, ".manual-hub-layout");
  assert.match(layout, /flex:\s*1 1 auto/u);
  assert.match(layout, /min-height:\s*0/u);
  assert.match(rules(css, ".manual-hub-side"), /overflow-y:\s*auto/u);
  assert.match(rules(css, ".manual-reader-body"), /overflow-y:\s*auto/u);
});

test("설정 페이지: 노트북 화면과 같은 색 변수, 페이지 전체가 아니라 칸 안에서 스크롤, 본문을 가운데로 모는 옛 규칙 없음", () => {
  const page = rules(globals, ".manual-settings-page");
  assert.match(page, /--workspace-border:/u);
  assert.match(page, /height:\s*100dvh/u);
  assert.match(page, /overflow:\s*hidden/u);
  assert.match(globals, /\.manual-settings-page \.manual-hub \{[^}]*flex:\s*1 1 auto/u);
  assert.doesNotMatch(globals, /\.manual-page-reader > div \{/u);
  assert.match(pane, /className="common-settings-page manual-settings-page"/u);
});
