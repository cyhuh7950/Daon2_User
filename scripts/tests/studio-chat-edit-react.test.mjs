import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

const OID = `sv2-${"a".repeat(32)}`;
const TURN = `svt-${"b".repeat(32)}`;
const turn = (over = {}) => ({ turn_id: TURN, output_id: OID, base_revision: 3, instruction: "둘째 문단을 고쳐 줘", state: "ready", reply: "고쳤습니다",
  changes: [{ op: "replace", id: "s1.b2", before_text: "고치기 전 문장", after_text: "고친 뒤 문장", reason: "요청" }], error_code: null, applied_revision: null, created_at: "2026-11-10T00:00:00+00:00", ...over });

async function bundle(output) {
  const root = path.resolve(import.meta.dirname, "../..");
  const { build } = await import("vite");
  await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
    lib: { entry: path.join(root, "packages/ui/src/studio-chat-edit.jsx"), formats: ["es"], fileName: "studio-chat-edit-react" },
    rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
  const built = (await readdir(output)).find((name) => name.startsWith("studio-chat-edit-react") && /\.m?js$/u.test(name));
  return import(`${pathToFileURL(path.join(output, built)).href}?v=${Date.now()}`);
}

function fakeStudio(pages) {
  const queue = [...pages];
  const calls = [];
  return { calls,
    listEditTurns: async () => { calls.push(["list"]); return queue.length > 1 ? queue.shift() : queue[0]; },
    createEditTurn: async (id, input) => { calls.push(["create", id, input]); return { turn_id: TURN, job_id: "sve", state: "queued" }; },
    applyEditTurn: async (id, turnId) => { calls.push(["apply", id, turnId]); return { output_id: id, turn_id: turnId, revision_no: 4 }; },
    discardEditTurn: async (id, turnId) => { calls.push(["discard", id, turnId]); } };
}

async function mount(studio, props = {}) {
  const dom = installMinimalDom();
  const root = path.resolve(import.meta.dirname, "../..");
  const output = await mkdtemp(path.join(root, ".studio-chat-edit-react-"));
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { StudioChatEdit } = await bundle(output);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 15)); });
  await act(async () => { reactRoot.render(createElement(StudioChatEdit, { studio, outputId: OID, pollMs: 5, ...props })); });
  await flush();
  return { container, act, flush, unmount: () => act(async () => reactRoot.unmount()),
    close: async (mounted = true) => { if (mounted) await act(async () => reactRoot.unmount()); dom.restore(); await rm(output, { recursive: true, force: true }); } };
}

const props = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];
const box = (view) => findElements(view.container, (n) => n.tagName === "TEXTAREA")[0];
const count = (studio, name) => studio.calls.filter((call) => call[0] === name).length;
async function type(view, value) {
  const node = box(view);
  node.value = value;
  await view.act(async () => props(node).onChange({ target: node, currentTarget: node }));
}
const key = (over = {}) => ({ key: "Enter", shiftKey: false, nativeEvent: { isComposing: false, keyCode: 13 }, preventDefault() {}, ...over });

test("Enter sends, IME composition does not", async () => {
  const studio = fakeStudio([[]]);
  const view = await mount(studio);
  try {
    await type(view, "제목을 줄여 줘");
    await view.act(async () => props(box(view)).onKeyDown(key({ nativeEvent: { isComposing: true, keyCode: 229 } })));
    await view.act(async () => props(box(view)).onKeyDown(key({ shiftKey: true })));
    assert.equal(count(studio, "create"), 0);
    await view.act(async () => props(box(view)).onKeyDown(key()));
    await view.flush();
    assert.deepEqual(studio.calls.find((call) => call[0] === "create"), ["create", OID, { instruction: "제목을 줄여 줘" }]);
    assert.equal(box(view).value, "");
  } finally { await view.close(); }
});

test("shows before and after with apply and discard", async () => {
  const view = await mount(fakeStudio([[turn()]]));
  try {
    for (const expected of ["둘째 문단을 고쳐 줘", "고쳤습니다", "고치기 전 문장", "고친 뒤 문장"]) assert.ok(view.container.textContent.includes(expected), expected);
    assert.ok(buttonByText(view.container, "반영"));
    assert.ok(buttonByText(view.container, "취소"));
  } finally { await view.close(); }
});

test("apply reloads output once", async () => {
  const studio = fakeStudio([[turn()], [turn({ state: "applied", applied_revision: 4 })]]);
  let applied = 0;
  const view = await mount(studio, { onApplied: async () => { applied += 1; } });
  try {
    const button = buttonByText(view.container, "반영");
    await view.act(async () => { button.dispatchEvent(new MinimalEvent("click")); button.dispatchEvent(new MinimalEvent("click")); });
    await view.flush();
    assert.equal(count(studio, "apply"), 1);
    assert.equal(applied, 1);
    assert.ok(view.container.textContent.includes("반영했습니다"));
  } finally { await view.close(); }
});

test("discard keeps the output and shows the note", async () => {
  const studio = fakeStudio([[turn()], [turn({ state: "discarded" })]]);
  let applied = 0;
  const view = await mount(studio, { onApplied: () => { applied += 1; } });
  try {
    const button = buttonByText(view.container, "취소");
    await view.act(async () => { button.dispatchEvent(new MinimalEvent("click")); });
    await view.flush();
    assert.deepEqual(studio.calls.find((call) => call[0] === "discard"), ["discard", OID, TURN]);
    assert.equal(applied, 0);
    assert.ok(view.container.textContent.includes("취소했습니다"));
  } finally { await view.close(); }
});

test("no_change shows only the reply", async () => {
  const view = await mount(fakeStudio([[turn({ state: "no_change", reply: "그건 할 수 없습니다", changes: [] })]]));
  try {
    assert.ok(view.container.textContent.includes("그건 할 수 없습니다"));
    assert.equal(buttonByText(view.container, "반영"), undefined);
  } finally { await view.close(); }
});

test("active turn disables input and polls", async () => {
  const studio = fakeStudio([[turn({ state: "queued", reply: null, changes: [] })], [turn({ state: "working", reply: null, changes: [] })], [turn()]]);
  const view = await mount(studio);
  try {
    await view.flush();
    await view.flush();
    assert.ok(buttonByText(view.container, "반영"));
    assert.equal(box(view).disabled, false);
    const settled = count(studio, "list");
    await view.flush();
    assert.equal(count(studio, "list"), settled);
  } finally { await view.close(); }
});

test("input is disabled while a turn is active", async () => {
  const view = await mount(fakeStudio([[turn({ state: "queued", reply: null, changes: [] })]]), { pollMs: 100000 });
  try {
    assert.equal(box(view).disabled, true);
    assert.ok(view.container.textContent.includes("수정안을 만들고 있습니다"));
  } finally { await view.close(); }
});

test("polling stops after unmount", async () => {
  const studio = fakeStudio([[turn({ state: "queued", reply: null, changes: [] })]]);
  const view = await mount(studio);
  try {
    await view.unmount();
    const after = count(studio, "list");
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(count(studio, "list"), after);
  } finally { await view.close(false); }
});

test("restores history on open", async () => {
  const view = await mount(fakeStudio([[turn({ turn_id: `svt-${"c".repeat(32)}`, instruction: "앞선 지시", state: "applied", changes: [] }), turn()]]));
  try {
    assert.ok(view.container.textContent.includes("앞선 지시"));
    assert.ok(buttonByText(view.container, "반영"));
  } finally { await view.close(); }
});

test("failed and stale show safe message", async () => {
  const studio = fakeStudio([[turn(), turn({ turn_id: `svt-${"d".repeat(32)}`, state: "failed", reply: null, changes: [], error_code: "CHAT_EDIT_INVALID" })]]);
  studio.applyEditTurn = async () => { throw Object.assign(new Error("raw internal detail"), { code: "CHAT_EDIT_STALE" }); };
  const view = await mount(studio);
  try {
    assert.ok(view.container.textContent.includes("수정안을 만들지 못했습니다"));
    const button = buttonByText(view.container, "반영");
    await view.act(async () => { button.dispatchEvent(new MinimalEvent("click")); });
    await view.flush();
    assert.ok(view.container.textContent.includes("자료가 바뀌었습니다"));
    assert.ok(!view.container.textContent.includes("raw internal detail"));
  } finally { await view.close(); }
});
