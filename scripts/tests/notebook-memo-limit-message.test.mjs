import assert from "node:assert/strict";
import test from "node:test";

import { NOTEBOOK_MESSAGES } from "../../packages/ui/src/notebook-messages.ko.js";

// NB4-F1b로 메모를 소스로 쓸 수 있는 크기가 2 MiB가 됐다. 화면 문구에 예전 32KB 상한이 남으면 안 된다.
test("메모 너무 김 문구는 지금 상한(2 MiB)을 말한다", () => {
  const text = NOTEBOOK_MESSAGES["notebook.memo_source.error.memo_too_large"];
  assert.match(text, /메모가 너무 깁니다/u);
  assert.match(text, /2 MiB/u);
  assert.doesNotMatch(text, /32 ?KB|32 ?KiB/u);
});
