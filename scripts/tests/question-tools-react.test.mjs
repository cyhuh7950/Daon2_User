// NB2-U1 질문 도구 화면(WO-N1 N1-2, 결정 D-02 웹 제외): 입력창 아래 "도구" 버튼·켠 도구 수 배지·목록 팝오버.
// 상태: 불러오는 중 / 정상 / 사용할 수 없는 도구(흐리게·이유) / 모두 꺼짐(소스만으로 답함) / 저장 실패(되돌림·알림).
// 조작: 켜고 끄면 바로 저장하고 바꾼 도구만 보낸다. 노트북을 다시 열면 서버에 저장된 같은 선택이 보인다.
import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { MinimalEvent, findElements, installMinimalDom } from "./product-studio-dom.mjs";

const root = path.resolve(import.meta.dirname, "../..");

// react·react-dom은 묶기 전에 DOM이 있는 상태로 한 번 읽어 둔다(다른 React 시험과 같은 순서).
{
  const dom = installMinimalDom();
  await import("react");
  await import("react-dom/client");
  dom.restore();
}

let built = null;
async function bundle() {
  if (built) return built.module;
  const name = "question-tools-menu";
  const output = await mkdtemp(path.join(root, `.${name}-`));
  try {
    const { build } = await import("vite");
    await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
      lib: { entry: path.join(root, "packages/ui/src/question-tools-menu.jsx"), formats: ["es"], fileName: name },
      rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
    const file = (await readdir(output)).find((item) => item.startsWith(name) && /\.m?js$/u.test(item));
    const module = await import(`${pathToFileURL(path.join(output, file)).href}?v=${Date.now()}`);
    built = { module, output };
    return module;
  } catch (error) { await rm(output, { recursive: true, force: true }); throw error; }
}
test.after(async () => { if (built) await rm(built.output, { recursive: true, force: true }); });

const deferred = () => { let resolve; let reject; const promise = new Promise((ok, no) => { resolve = ok; reject = no; }); return { promise, resolve, reject }; };
const failure = (code, status) => Object.assign(new Error(code), { code, status });

const KNOWLEDGE = { id: "approved_knowledge", kind: "approved_knowledge", label: "승인 지식", available: true, enabled: true };
const RAG = { id: "connector:kc-rag", kind: "connector", connector_kind: "daon2_rag", label: "Daon2-RAG 문서", available: true, enabled: true };
const LAW = { id: "connector:kc-law", kind: "connector", connector_kind: "law", label: "법령 검색", available: true, enabled: true };

// 노트북별 저장값을 가진 가짜 서버. 저장은 바꾼 도구만 합치고, 사용할 수 없는 도구는 저장해도 응답에서 꺼짐이다.
function fakeServer(byNotebook) {
  const saved = new Map(Object.entries(byNotebook).map(([id, tools]) => [id, tools.map((tool) => ({ ...tool }))]));
  const calls = [];
  const view = (id) => ({ tools: saved.get(id).map((tool) => ({ ...tool, enabled: tool.available ? tool.enabled : false })) });
  const studioFor = (notebookId, { load, save } = {}) => ({
    getQuestionTools: async (options) => { calls.push(["get", notebookId]); if (load) return load(options); return view(notebookId); },
    saveQuestionTools: async (enabled) => {
      calls.push(["save", notebookId, enabled]);
      if (save) await save(enabled);
      for (const [id, value] of Object.entries(enabled)) {
        const tool = saved.get(notebookId).find((item) => item.id === id);
        if (!tool) throw failure("QUESTION_TOOL_UNKNOWN", 422);
        tool.enabled = value;
      }
      return view(notebookId);
    },
  });
  return { calls, studioFor };
}

const settle = async (act) => act(async () => { for (let i = 0; i < 6; i += 1) await Promise.resolve(); });

async function mountMenu(studio, props = {}) {
  const dom = installMinimalDom();
  const module = await bundle();
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(module.QuestionToolsMenu, { studio, ...props })); });
  await settle(act);
  return { container, act, dom,
    click: async (node) => { await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await settle(act); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); } };
}

const reactProps = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];
const toolsButton = (container) => findElements(container, (node) => node.tagName === "BUTTON" && node.getAttribute("aria-controls") !== null)[0];
const switches = (container) => findElements(container, (node) => node.tagName === "INPUT" && node.getAttribute("role") === "switch");
const switchFor = (container, label) => {
  const labels = findElements(container, (node) => node.tagName === "LABEL" && node.textContent.includes(label));
  return labels.length ? findElements(labels[0], (node) => node.tagName === "INPUT")[0] : undefined;
};
const badge = (container) => findElements(container, (node) => node.getAttribute?.("data-question-tools-count") !== null)[0]?.textContent;
const alertText = (container) => findElements(container, (node) => node.getAttribute?.("role") === "alert").map((node) => node.textContent).join(" ");
const toggle = async (view, input) => {
  await view.act(async () => { reactProps(input).onChange({ target: input, currentTarget: input }); });
  await settle(view.act);
};
async function openMenu(view) {
  const button = toolsButton(view.container);
  assert.ok(button, "도구 버튼");
  if (button.getAttribute("aria-expanded") !== "true") await view.click(button);
  assert.equal(toolsButton(view.container).getAttribute("aria-expanded"), "true");
}

test("불러오는 중에는 도구 버튼이 잠기고 불러오는 중 문구를 보인다", async () => {
  const gate = deferred();
  const server = fakeServer({ "nb-1": [KNOWLEDGE, RAG, LAW] });
  const view = await mountMenu(server.studioFor("nb-1", { load: () => gate.promise }));
  try {
    const button = toolsButton(view.container);
    assert.ok(button, "불러오는 동안에도 버튼 자리는 보인다");
    assert.equal(button.disabled, true);
    assert.equal(button.getAttribute("aria-busy"), "true");
    assert.match(view.container.textContent, /도구를 불러오는 중/u);
    await view.act(async () => { gate.resolve({ tools: [KNOWLEDGE, RAG, LAW] }); });
    await settle(view.act);
    assert.equal(toolsButton(view.container).disabled, false);
    assert.doesNotMatch(view.container.textContent, /도구를 불러오는 중/u);
  } finally { await view.close(); }
});

test("정상: 도구 3개가 모두 켜져 있으면 배지는 3이고, 버튼을 누르면 목록이 열려 스위치 3개가 켜진 상태다", async () => {
  const server = fakeServer({ "nb-1": [KNOWLEDGE, RAG, LAW] });
  const view = await mountMenu(server.studioFor("nb-1"));
  try {
    const button = toolsButton(view.container);
    assert.match(button.textContent, /도구/u);
    assert.equal(button.getAttribute("aria-expanded"), "false");
    assert.equal(badge(view.container), "3");
    assert.equal(switches(view.container).length, 0, "닫혀 있으면 목록이 없다");
    await openMenu(view);
    const list = findElements(view.container, (node) => node.getAttribute?.("id") === toolsButton(view.container).getAttribute("aria-controls"))[0];
    assert.ok(list, "aria-controls가 목록을 가리킨다");
    const items = switches(view.container);
    assert.equal(items.length, 3);
    assert.deepEqual(items.map((item) => item.checked), [true, true, true]);
    assert.ok(switchFor(view.container, "승인 지식"));
    assert.ok(switchFor(view.container, "Daon2-RAG 문서"));
    assert.ok(switchFor(view.container, "법령 검색"));
    assert.doesNotMatch(view.container.textContent, /소스만으로 답합니다/u);
    assert.doesNotMatch(view.container.textContent, /웹/u, "웹 도구는 없다(D-02)");
  } finally { await view.close(); }
});

test("사용할 수 없는 도구는 흐리게(스위치 잠금) 이유 문구를 보이고 배지 수에서 빠진다", async () => {
  const server = fakeServer({ "nb-1": [
    { ...KNOWLEDGE, available: false, enabled: false, reason: "NO_SCOPE_SELECTED" },
    { ...RAG, available: false, enabled: false, reason: "CONNECTOR_NOT_READY" },
    { ...LAW, available: false, enabled: false, reason: "CONNECTOR_DISABLED" },
  ] });
  const ready = fakeServer({ "nb-1": [KNOWLEDGE, { ...RAG, available: false, enabled: false, reason: "CONNECTOR_NOT_READY" }, LAW] });
  const view = await mountMenu(ready.studioFor("nb-1"));
  try {
    assert.equal(badge(view.container), "2");
    await openMenu(view);
    const rag = switchFor(view.container, "Daon2-RAG 문서");
    assert.equal(rag.disabled, true);
    assert.equal(rag.checked, false);
    assert.match(view.container.textContent, /연결이 아직 준비되지 않았습니다/u);
    assert.doesNotMatch(view.container.textContent, /CONNECTOR_NOT_READY/u, "오류 코드를 그대로 보이지 않는다");
    const row = findElements(view.container, (node) => node.getAttribute?.("data-available") === "false");
    assert.equal(row.length, 1, "사용할 수 없는 줄은 흐리게 표시할 표지를 가진다");
    const describedBy = rag.getAttribute("aria-describedby");
    assert.ok(describedBy, "스위치가 이유 문구를 가리킨다");
    assert.match(findElements(view.container, (node) => node.getAttribute?.("id") === describedBy)[0].textContent, /준비되지 않았습니다/u);
  } finally { await view.close(); }
  const all = await mountMenu(server.studioFor("nb-1"));
  try {
    await openMenu(all);
    assert.match(all.container.textContent, /승인 지식 범위가 선택되지 않았습니다/u);
    assert.match(all.container.textContent, /관리자가 끈 연결입니다/u);
    assert.deepEqual(switches(all.container).map((item) => item.disabled), [true, true, true]);
  } finally { await all.close(); }
});

test("모든 도구가 꺼져 있으면 배지는 0이고 소스만으로 답한다는 한 줄 안내를 보인다", async () => {
  const server = fakeServer({ "nb-1": [{ ...KNOWLEDGE, enabled: false }, { ...RAG, enabled: false }, { ...LAW, enabled: false }] });
  const view = await mountMenu(server.studioFor("nb-1"));
  try {
    assert.equal(badge(view.container), "0");
    assert.match(view.container.textContent, /켜진 도구가 없어 소스만으로 답합니다/u);
    await openMenu(view);
    assert.deepEqual(switches(view.container).map((item) => item.checked), [false, false, false]);
  } finally { await view.close(); }
});

test("스위치를 끄면 바로 저장하고 바꾼 도구 하나만 보내며 배지 수가 바뀐다", async () => {
  const server = fakeServer({ "nb-1": [KNOWLEDGE, RAG, LAW] });
  const view = await mountMenu(server.studioFor("nb-1"));
  try {
    await openMenu(view);
    await toggle(view, switchFor(view.container, "Daon2-RAG 문서"));
    assert.deepEqual(server.calls.filter(([kind]) => kind === "save"), [["save", "nb-1", { "connector:kc-rag": false }]]);
    assert.equal(switchFor(view.container, "Daon2-RAG 문서").checked, false);
    assert.equal(badge(view.container), "2");
    await toggle(view, switchFor(view.container, "Daon2-RAG 문서"));
    assert.deepEqual(server.calls.filter(([kind]) => kind === "save").at(-1), ["save", "nb-1", { "connector:kc-rag": true }]);
    assert.equal(badge(view.container), "3");
  } finally { await view.close(); }
});

test("저장 중에는 스위치를 잠그고, 저장에 실패하면 이전 값으로 되돌리고 알린다", async () => {
  const gate = deferred();
  const server = fakeServer({ "nb-1": [KNOWLEDGE, RAG, LAW] });
  const view = await mountMenu(server.studioFor("nb-1", { save: () => gate.promise }));
  try {
    await openMenu(view);
    await toggle(view, switchFor(view.container, "승인 지식"));
    assert.equal(switchFor(view.container, "승인 지식").checked, false, "누르면 바로 바뀐 값이 보인다");
    assert.deepEqual(switches(view.container).map((item) => item.disabled), [true, true, true], "저장 중에는 잠근다");
    assert.equal(badge(view.container), "2");
    await view.act(async () => { gate.reject(failure("QUESTION_TOOLS_UNAVAILABLE", 503)); });
    await settle(view.act);
    assert.equal(switchFor(view.container, "승인 지식").checked, true, "실패하면 이전 값으로 되돌린다");
    assert.equal(badge(view.container), "3");
    assert.match(alertText(view.container), /저장하지 못해 이전 선택으로 되돌렸습니다/u);
    assert.doesNotMatch(alertText(view.container), /QUESTION_TOOLS_UNAVAILABLE/u);
    assert.deepEqual(switches(view.container).map((item) => item.disabled), [false, false, false]);
  } finally { await view.close(); }
});

test("노트북을 다시 열면 서버에 저장된 같은 선택이 보이고, 다른 노트북은 따로다", async () => {
  const server = fakeServer({ "nb-1": [KNOWLEDGE, RAG, LAW], "nb-2": [KNOWLEDGE, RAG, LAW] });
  const first = await mountMenu(server.studioFor("nb-1"));
  try {
    await openMenu(first);
    await toggle(first, switchFor(first.container, "법령 검색"));
    assert.equal(badge(first.container), "2");
  } finally { await first.close(); }
  const reopened = await mountMenu(server.studioFor("nb-1"));
  try {
    assert.equal(badge(reopened.container), "2");
    await openMenu(reopened);
    assert.equal(switchFor(reopened.container, "법령 검색").checked, false);
    assert.equal(switchFor(reopened.container, "승인 지식").checked, true);
  } finally { await reopened.close(); }
  const other = await mountMenu(server.studioFor("nb-2"));
  try {
    assert.equal(badge(other.container), "3", "다른 노트북의 선택은 영향을 받지 않는다");
  } finally { await other.close(); }
});

test("노트북이 바뀌면(studio 교체) 새 노트북의 선택을 다시 불러온다", async () => {
  const server = fakeServer({ "nb-1": [KNOWLEDGE, RAG, LAW], "nb-2": [{ ...KNOWLEDGE, enabled: false }, RAG, LAW] });
  const dom = installMinimalDom();
  const module = await bundle();
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  try {
    await act(async () => { reactRoot.render(createElement(module.QuestionToolsMenu, { studio: server.studioFor("nb-1") })); });
    await settle(act);
    assert.equal(badge(container), "3");
    await act(async () => { reactRoot.render(createElement(module.QuestionToolsMenu, { studio: server.studioFor("nb-2") })); });
    await settle(act);
    assert.equal(badge(container), "2");
  } finally { await act(async () => reactRoot.unmount()); dom.restore(); }
});

test("Esc를 누르면 목록이 닫히고 버튼으로 초점이 돌아간다", async () => {
  const server = fakeServer({ "nb-1": [KNOWLEDGE, RAG, LAW] });
  const view = await mountMenu(server.studioFor("nb-1"));
  try {
    await openMenu(view);
    const popover = findElements(view.container, (node) => node.getAttribute?.("id") === toolsButton(view.container).getAttribute("aria-controls"))[0];
    await view.act(async () => { reactProps(popover).onKeyDown({ key: "Escape", preventDefault() {}, stopPropagation() {} }); });
    await settle(view.act);
    assert.equal(toolsButton(view.container).getAttribute("aria-expanded"), "false");
    assert.equal(switches(view.container).length, 0);
    assert.equal(view.dom.document.activeElement, toolsButton(view.container));
  } finally { await view.close(); }
});

test("목록을 불러오지 못하면 알림과 다시 시도 버튼을 보이고, 다시 시도하면 다시 읽는다", async () => {
  let fail = true;
  const server = fakeServer({ "nb-1": [KNOWLEDGE, RAG, LAW] });
  const studio = server.studioFor("nb-1", { load: async () => { if (fail) throw failure("QUESTION_TOOLS_UNAVAILABLE", 503); return { tools: [KNOWLEDGE, RAG, LAW] }; } });
  const view = await mountMenu(studio);
  try {
    assert.match(alertText(view.container), /도구 목록을 불러오지 못했습니다/u);
    const retry = findElements(view.container, (node) => node.tagName === "BUTTON" && node.textContent.trim() === "다시 시도")[0];
    assert.ok(retry);
    fail = false;
    await view.click(retry);
    assert.equal(badge(view.container), "3");
    assert.equal(alertText(view.container), "");
  } finally { await view.close(); }
});

test("어댑터에 질문 도구 함수가 없으면 아무것도 그리지 않는다", async () => {
  const view = await mountMenu({ getModelSelection: async () => ({}) });
  try {
    assert.equal(view.container.textContent, "");
    assert.equal(toolsButton(view.container), undefined);
  } finally { await view.close(); }
});
