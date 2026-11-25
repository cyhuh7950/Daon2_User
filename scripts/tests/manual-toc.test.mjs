// N1-B15 (UAT-14): 설명서 창의 "목록 보기"를 눌러도 장·절 목차가 없었다. 문서를 열면 목차를 보이고 절로 이동한다.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { filterManualToc, manualHeadingId, manualToc } from "../../packages/ui/src/manual-toc.js";

const TEXT = [
  "# Daon 사용자 설명서",
  "",
  "## 1부 처음 시작하기",
  "### 1-1 이 설명서 읽는 법",
  "본문",
  "#### 기능·목적",
  "## 2부 화면별 설명",
  "### 2-19 빠른 찾기",
  "### 2-20 **심층** 조사",
].join("\n");

test("부(##)와 절(###)을 2단계 목차로 뽑고, 줄 번호로 만든 id를 붙인다(#·#### 제외)", () => {
  assert.deepEqual(manualToc(TEXT), [
    { id: manualHeadingId(2), level: 2, title: "1부 처음 시작하기" },
    { id: manualHeadingId(3), level: 3, title: "1-1 이 설명서 읽는 법" },
    { id: manualHeadingId(6), level: 2, title: "2부 화면별 설명" },
    { id: manualHeadingId(7), level: 3, title: "2-19 빠른 찾기" },
    { id: manualHeadingId(8), level: 3, title: "2-20 심층 조사" },
  ]);
  assert.match(manualHeadingId(7), /^manual-section-7$/u);
});

test("검색은 절 이름으로 거르고, 남은 절의 부 제목은 함께 남긴다", () => {
  const toc = manualToc(TEXT);
  assert.deepEqual(filterManualToc(toc, "빠른 찾기").map((item) => item.title), ["2부 화면별 설명", "2-19 빠른 찾기"]);
  assert.deepEqual(filterManualToc(toc, "1부").map((item) => item.title), ["1부 처음 시작하기", "1-1 이 설명서 읽는 법"]);
  assert.equal(filterManualToc(toc, "").length, toc.length);
  assert.deepEqual(filterManualToc(toc, "없는 말"), []);
});

test("본문 렌더러는 목차와 같은 id를 부·절 제목에 붙인다", async () => {
  const source = await readFile(new URL("../../packages/ui/src/manual-markdown.jsx", import.meta.url), "utf8");
  assert.match(source, /import \{[^}]*manualHeadingId[^}]*\} from "\.\/manual-toc\.js"/u);
  assert.match(source, /id=\{manualHeadingId\(index\)\}/u);
});
