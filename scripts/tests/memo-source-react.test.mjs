// NB1-U2 메모를 소스로 화면(WO-N1 N1-3, 결정 D-10): 버튼 3상태, 진행 중 비활성, 오류 문구, 보기 권한일 때 버튼 없음,
// 소스 줄의 메모 표시(누르면 메모 보기)·원본 메모 없음, 만들기 성공 뒤 소스 목록 새로고침과 새 줄 스크롤.
import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

const root = path.resolve(import.meta.dirname, "../..");

// react·react-dom은 묶기(vite build가 NODE_ENV를 production으로 바꿈) 전에, DOM이 있는 상태로 한 번 읽어 둔다(다른 React 시험과 같은 순서).
{
  const dom = installMinimalDom();
  await import("react");
  await import("react-dom/client");
  dom.restore();
}

const bundles = new Map();
async function bundle(entry, name) {
  if (bundles.has(name)) return bundles.get(name).module;
  const output = await mkdtemp(path.join(root, `.${name}-`));
  try {
    const { build } = await import("vite");
    await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
      lib: { entry: path.join(root, entry), formats: ["es"], fileName: name },
      rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
    const built = (await readdir(output)).find((file) => file.startsWith(name) && /\.m?js$/u.test(file));
    const module = await import(`${pathToFileURL(path.join(output, built)).href}?v=${Date.now()}`);
    bundles.set(name, { module, output });
    return module;
  } catch (error) { await rm(output, { recursive: true, force: true }); throw error; }
}
test.after(async () => { for (const { output } of bundles.values()) await rm(output, { recursive: true, force: true }); });

const OID = (c) => `sv2-${c.repeat(32)}`;
const MEMO_ID = OID("m");
const memoItem = (over = {}) => ({ output_id: MEMO_ID, type_id: "memo", format_id: null, title: "회의 메모", status: "completed", error_code: null, source_count: 0,
  current_revision: 2, created_at: "2026-11-20T00:00:00Z", updated_at: "2026-11-20T00:00:00Z", stale: false, ...over });
const failure = (code, status) => Object.assign(new Error(code), { code, status });
const deferred = () => { let resolve; let reject; const promise = new Promise((ok, no) => { resolve = ok; reject = no; }); return { promise, resolve, reject }; };

// sourceLink: undefined면 키 없음(이전 서버), null이면 연결 없음, 객체면 연결.
function fakeStudio(options = {}) {
  const { create, reflect, withMemoSource = true } = options;
  const calls = [];
  const state = { link: Object.hasOwn(options, "sourceLink") ? options.sourceLink : null, revision: 2 };
  const studio = {
    calls, state,
    listTypes: async () => [{ type_id: "memo", available: true, formats: [], presets: [], export_formats: [], default_format: null, settings_schema: null }],
    listOutputs: async () => ({ items: [memoItem({ current_revision: state.revision })], nextCursor: null }),
    getOutput: async (id) => {
      calls.push(["get", id]);
      const output = { ...memoItem({ output_id: id, current_revision: state.revision }), settings: {}, evidence: [], assets: [],
        revision: { content: { body: { markdown: "# 회의\n결정 사항" }, warnings: [] } } };
      if (state.link !== undefined) output.source_link = state.link;
      return output;
    },
    createRevision: async (id, input) => { calls.push(["revision", id, input]); state.revision += 1; return { revision_no: state.revision }; },
    exportFormats: () => [],
  };
  if (withMemoSource) {
    studio.createMemoSource = async (id) => {
      calls.push(["createSource", id]);
      if (create) return create(state);
      state.link = { source_id: "memo-source-1", reflected_revision_no: state.revision, outdated: false };
      return { source_id: "memo-source-1", source_version_id: "memo-version-1", state: "registered" };
    };
    studio.reflectMemoSource = async (id) => {
      calls.push(["reflectSource", id]);
      if (reflect) return reflect(state);
      state.link = { ...state.link, reflected_revision_no: state.revision, outdated: false };
      return { source_id: state.link.source_id, source_version_id: "memo-version-2" };
    };
  }
  return studio;
}

const settle = async (act) => act(async () => { for (let i = 0; i < 6; i += 1) await Promise.resolve(); });

async function mountPanel(studio, props = {}) {
  const dom = installMinimalDom();
  const module = await bundle("packages/ui/src/studio-panel.jsx", "memo-source-panel");
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(module.StudioPanel, { studio, sourceStats: { sourceCount: 1, readySourceCount: 1 }, ...props })); });
  await settle(act);
  const view = { container, act,
    click: async (node) => { await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await settle(act); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); } };
  // 목록의 메모 카드를 눌러 메모 보기를 연다.
  const card = findElements(container, (node) => node.tagName === "BUTTON" && node.getAttribute("aria-label") === "열기: 회의 메모")[0];
  assert.ok(card, "메모 카드");
  await view.click(card);
  return view;
}

const sourceButton = (container) => findElements(container, (node) => node.tagName === "BUTTON" && node.getAttribute("data-memo-source") !== null)[0];
const alertText = (container) => findElements(container, (node) => node.getAttribute?.("role") === "alert").map((node) => node.textContent).join(" ");

test("메모 보기 버튼은 연결 없음·바뀜·같음에 따라 '소스로 사용'·'소스에 반영'·'소스와 같음(비활성)'이다", async () => {
  for (const [link, label, disabled] of [
    [null, "소스로 사용", false],
    [{ source_id: "memo-source-1", reflected_revision_no: 1, outdated: true }, "소스에 반영", false],
    [{ source_id: "memo-source-1", reflected_revision_no: 2, outdated: false }, "소스와 같음", true],
  ]) {
    const view = await mountPanel(fakeStudio({ sourceLink: link }));
    try {
      const button = sourceButton(view.container);
      assert.ok(button, `${label} 버튼`);
      assert.equal(button.textContent.trim(), label);
      assert.equal(button.disabled, disabled, `${label} 비활성 여부`);
    } finally { await view.close(); }
  }
});

test("'소스로 사용'을 누르면 진행 중에는 버튼이 비활성이고, 성공하면 '소스와 같음'·완료 알림과 함께 셸에 새 소스를 알린다", async () => {
  const gate = deferred();
  const changed = [];
  const studio = fakeStudio({ create: async (state) => { await gate.promise; state.link = { source_id: "memo-source-9", reflected_revision_no: state.revision, outdated: false };
    return { source_id: "memo-source-9", source_version_id: "memo-version-9", state: "registered" }; } });
  const view = await mountPanel(studio, { onMemoSourceChanged: (event) => changed.push(event) });
  try {
    await view.click(sourceButton(view.container));
    const busy = sourceButton(view.container);
    assert.equal(busy.disabled, true);
    assert.equal(busy.getAttribute("aria-busy"), "true");
    assert.match(view.container.textContent, /소스로 만드는 중/u);
    await view.click(busy);
    assert.equal(studio.calls.filter(([kind]) => kind === "createSource").length, 1, "진행 중 두 번 누를 수 없다");
    await view.act(async () => { gate.resolve(); });
    await settle(view.act);
    assert.equal(sourceButton(view.container).textContent.trim(), "소스와 같음");
    assert.match(view.container.textContent, /소스로 만들었습니다/u);
    assert.deepEqual(changed, [{ kind: "created", sourceId: "memo-source-9", outputId: MEMO_ID }]);
  } finally { await view.close(); }
});

test("'소스에 반영'을 누르면 반영을 부르고 완료 알림 뒤 '소스와 같음'이 된다", async () => {
  const changed = [];
  const studio = fakeStudio({ sourceLink: { source_id: "memo-source-1", reflected_revision_no: 1, outdated: true } });
  const view = await mountPanel(studio, { onMemoSourceChanged: (event) => changed.push(event) });
  try {
    await view.click(sourceButton(view.container));
    assert.deepEqual(studio.calls.filter(([kind]) => kind === "reflectSource"), [["reflectSource", MEMO_ID]]);
    assert.equal(sourceButton(view.container).textContent.trim(), "소스와 같음");
    assert.match(view.container.textContent, /소스에 반영했습니다/u);
    assert.deepEqual(changed, [{ kind: "reflected", sourceId: "memo-source-1", outputId: MEMO_ID }]);
  } finally { await view.close(); }
});

test("메모를 고쳐 저장 중이면 버튼을 잠그고, 저장된 새 리비전이 반영 리비전과 다르면 '소스에 반영'이 된다", async () => {
  const studio = fakeStudio({ sourceLink: { source_id: "memo-source-1", reflected_revision_no: 2, outdated: false } });
  const view = await mountPanel(studio);
  try {
    assert.equal(sourceButton(view.container).textContent.trim(), "소스와 같음");
    const textarea = findElements(view.container, (node) => node.tagName === "TEXTAREA")[0];
    const props = textarea[Object.keys(textarea).find((key) => key.startsWith("__reactProps$"))];
    textarea.value = "# 회의\n결정 사항 추가";
    await view.act(async () => props.onChange({ target: textarea, currentTarget: textarea }));
    assert.equal(sourceButton(view.container).disabled, true, "저장 전에는 누를 수 없다");
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 1600)); });
    await settle(view.act);
    const button = sourceButton(view.container);
    assert.equal(button.textContent.trim(), "소스에 반영");
    assert.equal(button.disabled, false);
  } finally { await view.close(); }
});

const CREATE_ERRORS = {
  MEMO_EMPTY: /메모가 비어 있어/u,
  MEMO_SOURCE_EXISTS: /이미 이 메모로 만든 소스가 있습니다/u,
  MEMO_TOO_LARGE: /메모가 너무 깁니다/u,
  STUDIO_OUTPUT_NOT_FOUND: /메모를 찾을 수 없습니다/u,
  OUTPUT_NOT_MEMO: /메모만 소스로/u,
};
const REFLECT_ERRORS = {
  MEMO_SOURCE_UNCHANGED: /이미 지금 메모와 같습니다/u,
  MEMO_SOURCE_NOT_LINKED: /연결된 소스가 없습니다/u,
  SOURCE_PROCESSING_ACTIVE: /처리하고 있습니다/u,
  MEMO_EMPTY: /메모가 비어 있어/u,
  MEMO_TOO_LARGE: /메모가 너무 깁니다/u,
};

test("만들기 실패는 오류 코드별 문구를 보이고 원문 코드를 그대로 보이지 않는다", async () => {
  for (const [code, pattern] of Object.entries(CREATE_ERRORS)) {
    const studio = fakeStudio({ create: async () => { throw failure(code, code === "MEMO_SOURCE_EXISTS" ? 409 : 422); } });
    const view = await mountPanel(studio);
    try {
      await view.click(sourceButton(view.container));
      const text = alertText(view.container);
      assert.match(text, pattern, code);
      assert.doesNotMatch(text, new RegExp(code, "u"), `${code} 원문 없음`);
      assert.equal(sourceButton(view.container)?.getAttribute("aria-busy"), null, `${code} 뒤 진행 표시 해제`);
    } finally { await view.close(); }
  }
});

test("반영 실패는 오류 코드별 문구를 보인다", async () => {
  for (const [code, pattern] of Object.entries(REFLECT_ERRORS)) {
    const studio = fakeStudio({ sourceLink: { source_id: "memo-source-1", reflected_revision_no: 1, outdated: true }, reflect: async () => { throw failure(code, 409); } });
    const view = await mountPanel(studio);
    try {
      await view.click(sourceButton(view.container));
      assert.match(alertText(view.container), pattern, code);
    } finally { await view.close(); }
  }
});

test("이미 소스가 있거나 변경 없음이면 메모 상태를 다시 읽어 버튼을 맞춘다", async () => {
  const studio = fakeStudio({ create: async (state) => { state.link = { source_id: "memo-source-1", reflected_revision_no: state.revision, outdated: false }; throw failure("MEMO_SOURCE_EXISTS", 409); } });
  const view = await mountPanel(studio);
  try {
    await view.click(sourceButton(view.container));
    assert.equal(sourceButton(view.container).textContent.trim(), "소스와 같음");
    assert.match(alertText(view.container), /이미 이 메모로 만든 소스가 있습니다/u);
  } finally { await view.close(); }
});

test("권한 없음(403)이면 문구를 보이고 버튼을 숨긴다", async () => {
  const studio = fakeStudio({ create: async () => { throw failure("FORBIDDEN", 403); } });
  const view = await mountPanel(studio);
  try {
    await view.click(sourceButton(view.container));
    assert.match(alertText(view.container), /편집할 권한이 없습니다/u);
    assert.equal(sourceButton(view.container) === undefined, true);
  } finally { await view.close(); }
});

test("보기 권한(canEdit=false)이거나 어댑터에 메모-소스 함수가 없거나 서버가 source_link를 주지 않으면 버튼이 없다", async () => {
  for (const [label, studio, props] of [
    ["보기 권한", fakeStudio(), { canEdit: false }],
    ["함수 없음", fakeStudio({ withMemoSource: false }), {}],
    ["source_link 없음", fakeStudio({ sourceLink: undefined }), {}],
  ]) {
    const view = await mountPanel(studio, props);
    try {
      assert.ok(findElements(view.container, (node) => node.tagName === "TEXTAREA")[0], `${label}: 메모 보기는 열린다`);
      assert.equal(sourceButton(view.container) === undefined, true, label);
    } finally { await view.close(); }
  }
});

test("패널 밖에서 메모 열기 요청(openOutputRequest)을 받으면 그 메모 보기를 연다", async () => {
  const dom = installMinimalDom();
  const module = await bundle("packages/ui/src/studio-panel.jsx", "memo-source-panel");
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  const studio = fakeStudio();
  try {
    await act(async () => { reactRoot.render(createElement(module.StudioPanel, { studio, sourceStats: {} })); });
    await settle(act);
    assert.equal(findElements(container, (node) => node.tagName === "TEXTAREA").length, 0);
    await act(async () => { reactRoot.render(createElement(module.StudioPanel, { studio, sourceStats: {}, openOutputRequest: { outputId: MEMO_ID, nonce: 1 } })); });
    await settle(act);
    assert.ok(findElements(container, (node) => node.tagName === "TEXTAREA")[0], "메모 보기");
    assert.deepEqual(studio.calls.filter(([kind]) => kind === "get").at(-1), ["get", MEMO_ID]);
  } finally { await act(async () => reactRoot.unmount()); dom.restore(); }
});

test("문구는 notebook-messages.ko.js의 notebook.memo_source.* 키에만 있고 새 컴포넌트 코드에는 한글이 없다", async () => {
  const source = await readFile(path.join(root, "packages/ui/src/memo-source.jsx"), "utf8");
  const code = source.replace(/\/\*[\s\S]*?\*\//gu, "").replace(/(^|[^:])\/\/.*$/gmu, "$1");
  assert.doesNotMatch(code, /[가-힣]/u);
  assert.doesNotMatch(code, /\bfetch\(/u);
  const { NOTEBOOK_MESSAGES } = await import(pathToFileURL(path.join(root, "packages/ui/src/notebook-messages.ko.js")).href);
  const used = [...new Set([...code.matchAll(/["'`](notebook\.memo_source\.[a-z0-9_.]+)["'`]/gu)].map((match) => match[1]))];
  assert.ok(used.length >= 10, `사용 키 ${used.length}개`);
  for (const key of used) assert.equal(typeof NOTEBOOK_MESSAGES[key], "string", key);
});

// ---- 소스 목록(product-workspace-shell) ----

const rawSource = (over = {}) => ({ source_id: "source-1", source_version_id: "version-1", filename: "약관.txt", source_state: "ready", processing_state: "completed", job_state: "completed", ...over });
const memoSource = (exists, over = {}) => rawSource({ source_id: "memo-source-1", source_version_id: "memo-version-1", filename: "회의 메모.txt",
  memo_origin: { memo_output_id: MEMO_ID, memo_exists: exists }, ...over });

async function mountShell(adapter, props = {}) {
  const dom = installMinimalDom();
  const scrolled = [];
  globalThis.HTMLElement.prototype.scrollIntoView = function scrollIntoView() { scrolled.push(this.getAttribute("data-source-id")); };
  const module = await bundle("packages/ui/src/product-workspace-shell.jsx", "memo-source-shell");
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(module.ProductWorkspaceShell, { workspaceId: "workspace-1", adapter, ...props })); await Promise.resolve(); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  return { container, act, scrolled,
    wait: async () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); }),
    close: async () => { await act(async () => reactRoot.unmount()); delete globalThis.HTMLElement.prototype.scrollIntoView; dom.restore(); } };
}
const shellAdapter = (studio, listSources) => ({ listSources, uploadPdf() {}, getProcessingStatus() {}, askQuestion() {}, citationUrl: () => null,
  createReport() {}, listStudioOutputs: async () => [], listConnectors: async () => [], listKnowledgePackages: async () => [], studioV2: studio });

test("메모로 만든 소스 줄의 '메모' 표시를 누르면 스튜디오에서 그 메모 보기를 연다", async () => {
  const studio = fakeStudio({ sourceLink: { source_id: "memo-source-1", reflected_revision_no: 2, outdated: false } });
  const view = await mountShell(shellAdapter(studio, async () => [rawSource(), memoSource(true)]));
  try {
    const badges = findElements(view.container, (node) => node.tagName === "BUTTON" && node.getAttribute("data-memo-origin") !== null);
    assert.equal(badges.length, 1, "메모로 만든 소스에만 표시");
    assert.equal(badges[0].textContent.trim(), "메모");
    assert.match(badges[0].getAttribute("aria-label"), /회의 메모\.txt/u);
    await view.act(async () => { badges[0].dispatchEvent(new MinimalEvent("click")); });
    await view.wait();
    assert.deepEqual(studio.calls.filter(([kind]) => kind === "get").at(-1), ["get", MEMO_ID]);
    assert.ok(findElements(view.container, (node) => node.tagName === "TEXTAREA" && node.getAttribute("id") === "studio-memo-text")[0], "메모 보기");
  } finally { await view.close(); }
});

test("원본 메모가 지워진 소스는 '원본 메모 없음'만 보이고 누를 수 없다", async () => {
  const studio = fakeStudio();
  const view = await mountShell(shellAdapter(studio, async () => [memoSource(false)]));
  try {
    assert.match(view.container.textContent, /원본 메모 없음/u);
    assert.equal(findElements(view.container, (node) => node.tagName === "BUTTON" && node.getAttribute("data-memo-origin") !== null).length, 0);
    const missing = findElements(view.container, (node) => node.getAttribute?.("data-memo-origin-missing") !== null)[0];
    assert.ok(missing);
    assert.notEqual(missing.tagName, "BUTTON");
    assert.equal(buttonByText(view.container, "원본 메모 없음") === undefined, true);
  } finally { await view.close(); }
});

test("메모로 소스를 만들면 소스 목록을 다시 읽고 새 줄로 스크롤한다", async () => {
  const studio = fakeStudio();
  let created = false;
  let listCount = 0;
  const view = await mountShell(shellAdapter(studio, async () => { listCount += 1; return created ? [rawSource(), memoSource(true)] : [rawSource()]; }));
  try {
    const before = listCount;
    const card = findElements(view.container, (node) => node.tagName === "BUTTON" && node.getAttribute("aria-label") === "열기: 회의 메모")[0];
    assert.ok(card, "메모 카드");
    await view.act(async () => { card.dispatchEvent(new MinimalEvent("click")); });
    await view.wait();
    created = true;
    await view.act(async () => { sourceButton(view.container).dispatchEvent(new MinimalEvent("click")); });
    await view.wait();
    await view.wait();
    assert.ok(listCount > before, "소스 목록 새로고침");
    assert.ok(findElements(view.container, (node) => node.tagName === "LI" && node.getAttribute("data-source-id") === "memo-source-1")[0], "새 줄");
    assert.deepEqual(view.scrolled, ["memo-source-1"]);
  } finally { await view.close(); }
});

test("메모로 만든 소스가 처리 중이면 처리가 끝날 때까지 소스 목록을 다시 읽어 '사용 가능'으로 바꾼다(NB1-I2 N1-B02)", async () => {
  const studio = fakeStudio();
  let created = false;
  let reads = 0;
  const view = await mountShell(shellAdapter(studio, async () => {
    if (!created) return [rawSource()];
    reads += 1;
    return [rawSource(), memoSource(true, reads < 3 ? { source_state: "processing", processing_state: "processing", job_state: "processing" } : {})];
  }), { memoSourcePollMs: 5 });
  try {
    const card = findElements(view.container, (node) => node.tagName === "BUTTON" && node.getAttribute("aria-label") === "열기: 회의 메모")[0];
    await view.act(async () => { card.dispatchEvent(new MinimalEvent("click")); });
    await view.wait();
    created = true;
    await view.act(async () => { sourceButton(view.container).dispatchEvent(new MinimalEvent("click")); });
    for (let i = 0; i < 10 && reads < 3; i += 1) await view.wait();
    await view.wait();
    const row = findElements(view.container, (node) => node.tagName === "LI" && node.getAttribute("data-source-id") === "memo-source-1")[0];
    assert.ok(reads >= 3, "처리 중인 동안 다시 읽음");
    assert.match(row.textContent, /사용 가능/u);
    const settled = reads;
    for (let i = 0; i < 3; i += 1) await view.wait();
    assert.equal(reads, settled, "준비되면 더 읽지 않음");
  } finally { await view.close(); }
});

test("메모를 소스에 반영해 새 소스가 처리 중이면 처리가 끝날 때까지 소스 목록을 다시 읽는다(NB1-I2 반영 경로)", async () => {
  // 반영은 새 소스를 만든다(C-1 정정): 응답의 source_id가 바뀐다.
  const studio = fakeStudio({ sourceLink: { source_id: "memo-source-1", reflected_revision_no: 1, outdated: true },
    reflect: (state) => { state.link = { source_id: "memo-source-2", reflected_revision_no: state.revision, outdated: false }; return { source_id: "memo-source-2", source_version_id: "memo-version-2", revision_no: state.revision }; } });
  let reflected = false;
  let reads = 0;
  const view = await mountShell(shellAdapter(studio, async () => {
    if (!reflected) return [rawSource(), memoSource(true)];
    reads += 1;
    return [rawSource(), memoSource(true, { source_id: "memo-source-2", source_version_id: "memo-version-2", ...(reads < 3 ? { source_state: "processing", processing_state: "processing", job_state: "processing" } : {}) })];
  }), { memoSourcePollMs: 5 });
  try {
    const card = findElements(view.container, (node) => node.tagName === "BUTTON" && node.getAttribute("aria-label") === "열기: 회의 메모")[0];
    await view.act(async () => { card.dispatchEvent(new MinimalEvent("click")); });
    await view.wait();
    reflected = true;
    await view.act(async () => { sourceButton(view.container).dispatchEvent(new MinimalEvent("click")); });
    for (let i = 0; i < 10 && reads < 3; i += 1) await view.wait();
    await view.wait();
    const row = findElements(view.container, (node) => node.tagName === "LI" && node.getAttribute("data-source-id") === "memo-source-2")[0];
    assert.ok(reads >= 3, "처리 중인 동안 다시 읽음");
    assert.match(row.textContent, /사용 가능/u);
  } finally { await view.close(); }
});

test("메모를 지우면 셸에 알려 소스 목록을 다시 읽게 한다(원본 메모 없음 표시, NB1-I2 N1-B06)", async () => {
  const changed = [];
  const studio = fakeStudio({ sourceLink: { source_id: "memo-source-1", reflected_revision_no: 2, outdated: false } });
  let deleted = false;
  studio.deleteOutput = async (id) => { studio.calls.push(["delete", id]); deleted = true; };
  studio.listOutputs = async () => ({ items: deleted ? [] : [memoItem({ current_revision: studio.state.revision })], nextCursor: null });
  const view = await mountPanel(studio, { onMemoSourceChanged: (event) => changed.push(event) });
  try {
    await view.click(findElements(view.container, (node) => node.tagName === "BUTTON" && node.getAttribute("aria-label") === "목록으로")[0]);
    await view.click(findElements(view.container, (node) => node.tagName === "BUTTON" && node.getAttribute("aria-label") === "더보기: 회의 메모")[0]);
    await view.click(findElements(view.container, (node) => node.tagName === "BUTTON" && node.textContent.trim() === "삭제")[0]);
    const confirm = findElements(view.container, (node) => node.tagName === "BUTTON" && node.textContent.trim() === "삭제").at(-1);
    await view.click(confirm);
    assert.deepEqual(studio.calls.filter(([kind]) => kind === "delete"), [["delete", MEMO_ID]]);
    assert.deepEqual(changed.at(-1), { kind: "deleted", outputId: MEMO_ID });
  } finally { await view.close(); }
});
