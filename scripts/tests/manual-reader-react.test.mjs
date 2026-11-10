import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { findElements, installMinimalDom } from "./product-studio-dom.mjs";

// 매뉴얼 본문을 그린 뒤, 지우기(unmount) 전에 inspect로 검사한다.
async function render(text, inspect) {
  const root = path.resolve(import.meta.dirname, "../..");
  const output = await mkdtemp(path.join(root, ".manual-reader-react-"));
  const dom = installMinimalDom();
  // vite 빌드가 NODE_ENV를 production으로 바꾸므로 React(개발판, act 포함)를 먼저 불러온다.
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  try {
    const { build } = await import("vite");
    await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
      lib: { entry: path.join(root, "packages/ui/src/manual-markdown.jsx"), formats: ["es"], fileName: "manual-markdown" },
      rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
    const built = (await readdir(output)).find((name) => name.startsWith("manual-markdown") && /\.m?js$/u.test(name));
    const { ManualMarkdown } = await import(`${pathToFileURL(path.join(output, built)).href}?v=${Date.now()}`);
    const container = dom.document.createElement("div");
    dom.document.body.appendChild(container);
    const reactRoot = createRoot(container);
    await act(async () => { reactRoot.render(createElement(ManualMarkdown, { text })); });
    try {
      inspect({ container, text: container.textContent });
    } finally {
      await act(async () => reactRoot.unmount());
    }
  } finally {
    dom.restore();
    await rm(output, { recursive: true, force: true });
  }
}

const tags = (container, tag) => findElements(container, (node) => node.tagName === tag);

test("표는 table로 그리고 셀 안 굵게·코드 표시는 글자만 남긴다", async () => {
  await render("| 번호 | 항목 |\n| --- | --- |\n| ① | `x\\|y` **굵게** |\n\n다음 문단", ({ container }) => {
    assert.deepEqual(tags(container, "TH").map((node) => node.textContent), ["번호", "항목"]);
    assert.deepEqual(tags(container, "TD").map((node) => node.textContent), ["①", "x|y 굵게"]);
    assert.equal(tags(container, "TABLE").length, 1);
    assert.ok(tags(container, "P").some((node) => node.textContent === "다음 문단"));
  });
});

test("네 단계 제목은 h5로 그린다", async () => {
  await render("## 2부 화면별 설명\n### 2-6 스튜디오\n#### 사용 순서", ({ container }) => {
    assert.deepEqual(tags(container, "H5").map((node) => node.textContent), ["사용 순서"]);
    assert.equal(tags(container, "H4").length, 2);
  });
});

test("그림은 /manual/images 안의 png만 img로 그린다", async () => {
  await render("![① 스튜디오 패널](images/studio-panel.png)", ({ container }) => {
    const [image] = tags(container, "IMG");
    assert.equal(image.getAttribute("src"), "/manual/images/studio-panel.png");
    assert.equal(image.getAttribute("alt"), "① 스튜디오 패널");
  });
  for (const unsafe of ["../x.png", "/etc/x.png", "https://e.example/x.png", "images/x.svg", "images/../x.png", "images/sub/x.png"]) {
    await render(`![위험한 그림](${unsafe})`, ({ container, text }) => {
      assert.equal(tags(container, "IMG").length, 0, unsafe);
      assert.ok(text.includes("위험한 그림"), unsafe);
    });
  }
});
