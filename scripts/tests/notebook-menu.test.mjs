import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

async function bundle(output) {
  const root = path.resolve(import.meta.dirname, "../..");
  const { build } = await import("vite");
  await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
    lib: { entry: path.join(root, "packages/ui/src/notebook-menu.jsx"), formats: ["es"], fileName: "notebook-menu-react" },
    rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
  const built = (await readdir(output)).find((name) => name.startsWith("notebook-menu-react") && /\.m?js$/u.test(name));
  return import(`${pathToFileURL(path.join(output, built)).href}?v=${Date.now()}`);
}

const reactProps = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];
const byLabel = (container, label) => findElements(container, (n) => n.getAttribute?.("aria-label") === label)[0];

async function mount(props) {
  const dom = installMinimalDom();
  const root = path.resolve(import.meta.dirname, "../..");
  const output = await mkdtemp(path.join(root, ".notebook-menu-react-"));
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { NotebookTools } = await bundle(output);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(NotebookTools, props)); });
  const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  return { container, act, flush, click: async (node) => { await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await flush(); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await rm(output, { recursive: true, force: true }); } };
}

test("상단 바: 만들기 버튼, 준비 중인 공유, ⋮ 메뉴(맞춤설정 열기·준비 중 항목 비활성)", async () => {
  const calls = [];
  const view = await mount({ studio: { getCustomization: async () => ({ instruction: "기존 지시", version: 2, etag: '"e2"' }),
    saveCustomization: async (text, options) => { calls.push([text, options]); return { instruction: text, version: 3, etag: '"e3"' }; } },
    onCreateNotebook: () => calls.push("create"), onOpenChatSettings: () => calls.push("chat") });
  try {
    await view.click(buttonByText(view.container, "+ 노트북 만들기"));
    assert.equal(calls[0], "create");
    assert.equal(buttonByText(view.container, "공유").disabled, true);
    await view.click(byLabel(view.container, "노트북 메뉴"));
    const items = findElements(view.container, (n) => n.getAttribute?.("role") === "menuitem");
    assert.deepEqual(items.map((n) => n.disabled === true), [false, false, true, true]);
    await view.click(items[0]);
    assert.equal(calls[1], "chat");
    await view.click(byLabel(view.container, "노트북 메뉴"));
    await view.click(findElements(view.container, (n) => n.getAttribute?.("role") === "menuitem")[1]);
    await view.flush();
    const area = byLabel(view.container, "맞춤설정 지시");
    assert.equal(area.value, "기존 지시");
    area.value = " 결론부터 말해 주세요 ";
    await view.act(async () => reactProps(area).onChange({ target: area, currentTarget: area }));
    await view.click(buttonByText(view.container, "저장"));
    assert.deepEqual(calls[2], ["결론부터 말해 주세요", { etag: '"e2"' }]);
    assert.ok(view.container.textContent.includes("저장했습니다"));
  } finally { await view.close(); }
});

test("맞춤설정 저장 충돌이면 안내하고 저장을 막는다", async () => {
  const view = await mount({ studio: { getCustomization: async () => ({ instruction: "", version: 0, etag: null }),
    saveCustomization: async () => { throw Object.assign(new Error("x"), { code: "STUDIO_VERSION_CONFLICT" }); } } });
  try {
    await view.click(byLabel(view.container, "노트북 메뉴"));
    await view.click(findElements(view.container, (n) => n.getAttribute?.("role") === "menuitem")[1]);
    await view.flush();
    await view.click(buttonByText(view.container, "저장"));
    assert.ok(view.container.textContent.includes("다른 곳에서 먼저 수정했습니다"));
    assert.equal(buttonByText(view.container, "저장").disabled, true);
  } finally { await view.close(); }
});

test("노트북 복사 대화상자는 범위를 골라 같은 멱등 키로 복사하고, 건너뛴 항목이 있으면 알린 뒤 이동한다(ST-T20)", async () => {
  const calls = [];
  const moved = [];
  let skipped = { sources: 1, memos: 0, outputs: 0 };
  const studio = { copyNotebook: async (input) => { calls.push(input); return { notebook_id: "notebook-new", title: "사본", copied: { sources: 2 }, skipped }; },
    clearChatHistory: async () => {}, getCustomization: async () => ({ instruction: "", version: 0, etag: null }), saveCustomization: async () => ({}) };
  const view = await mount({ studio, title: "원본", counts: { sources: 3 }, onNotebookCopied: (id) => moved.push(id) });
  try {
    await view.click(byLabel(view.container, "노트북 메뉴"));
    await view.click(findElements(view.container, (n) => n.getAttribute?.("role") === "menuitem")[2]);
    assert.equal(byLabel(view.container, "새 노트북 이름").value, "원본 사본");
    assert.ok(view.container.textContent.includes("소스 (3)"));
    await view.click(findElements(view.container, (n) => n.tagName === "INPUT" && (n.type === "checkbox" || n.getAttribute?.("type") === "checkbox"))[1]);  // 메모 제외
    await view.click(buttonByText(view.container, "복사"));
    assert.deepEqual(calls[0].include, { sources: false, memos: false, outputs: true, customization: true });
    assert.match(calls[0].idempotencyKey, /^studio-v2-/u);
    assert.deepEqual(moved, []);
    assert.ok(view.container.textContent.includes("권한이 없어 1개는 복사하지 않았습니다."));
    await view.click(buttonByText(view.container, "새 노트북 열기"));
    assert.deepEqual(moved, ["notebook-new"]);
  } finally { await view.close(); }
});

test("복사가 모두 성공하면 바로 이동하고, 너무 크면 안내한다", async () => {
  const moved = [];
  let fail = false;
  const studio = { copyNotebook: async () => { if (fail) throw Object.assign(new Error("x"), { code: "NOTEBOOK_COPY_TOO_LARGE" }); return { notebook_id: "notebook-new", title: "t", copied: {}, skipped: { sources: 0, memos: 0, outputs: 0 } }; },
    clearChatHistory: async () => {}, getCustomization: async () => ({}), saveCustomization: async () => ({}) };
  const view = await mount({ studio, onNotebookCopied: (id) => moved.push(id) });
  try {
    await view.click(byLabel(view.container, "노트북 메뉴"));
    await view.click(findElements(view.container, (n) => n.getAttribute?.("role") === "menuitem")[2]);
    fail = true;
    await view.click(buttonByText(view.container, "복사"));
    assert.ok(view.container.textContent.includes("항목이 너무 많아"));
    fail = false;
    await view.click(buttonByText(view.container, "복사"));
    assert.deepEqual(moved, ["notebook-new"]);
  } finally { await view.close(); }
});

test("채팅 기록 삭제는 확인 문구를 보이고 삭제 후 화면을 갱신한다(ST-T19)", async () => {
  let cleared = 0;
  const done = [];
  const studio = { copyNotebook: async () => ({}), clearChatHistory: async () => { cleared += 1; }, getCustomization: async () => ({}), saveCustomization: async () => ({}) };
  const view = await mount({ studio, onChatCleared: () => done.push(true) });
  try {
    await view.click(byLabel(view.container, "노트북 메뉴"));
    await view.click(findElements(view.container, (n) => n.getAttribute?.("role") === "menuitem")[3]);
    assert.ok(view.container.textContent.includes("채팅 기록은 나만 볼 수 있습니다. 삭제해도 메모와 산출물은 유지됩니다."));
    await view.click(buttonByText(view.container, "삭제"));
    assert.equal(cleared, 1);
    assert.deepEqual(done, [true]);
  } finally { await view.close(); }
});

test("대화상자를 닫으면 포커스가 ⋮ 버튼으로 돌아온다(소스 확인)", async () => {
  const { readFile } = await import("node:fs/promises");
  const source = await readFile(new URL("../../packages/ui/src/notebook-menu.jsx", import.meta.url), "utf8");
  assert.match(source, /closeDialog = \(\) => \{ setDialog\(null\);[^}]*focus\??\.?\(\)/);
  assert.equal((source.match(/onClose=\{closeDialog\}/g) ?? []).length, 3);
});
