// 후속 A-6: 소스 재처리 설정·소스 작업 확인 창에 스타일이 없어 소스 목록 맨 아래에 붙었고, 확인 버튼이 화면 가장자리에 걸렸다.
// 화면 가운데 떠 있는 작은 창으로 띄운다(넘치면 창 안 스크롤). 소스 추가 창은 그대로 둔다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const css = await readFile(new URL("../../packages/ui/src/workspace.css", import.meta.url), "utf8");

test("소스 작업 창(재처리 설정·작업 확인)은 화면 가운데 고정된 창이고, 넘치면 창 안에서 스크롤한다", () => {
  const match = /\.source-action-dialog:not\(\.source-add-dialog\) \{([^}]*)\}/u.exec(css);
  assert.ok(match, "소스 작업 창 규칙이 있어야 한다");
  const body = match[1];
  assert.match(body, /position:\s*fixed/u);
  assert.match(body, /translate\(-50%,\s*-50%\)/u);
  assert.match(body, /width:\s*min\(420px/u);
  assert.match(body, /max-height:\s*calc\(100dvh/u);
  assert.match(body, /overflow-y:\s*auto/u);
  assert.match(body, /z-index:\s*\d+/u);
});
