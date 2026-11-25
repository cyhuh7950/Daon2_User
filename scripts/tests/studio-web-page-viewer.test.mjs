import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
// vite build가 NODE_ENV를 production으로 바꾸기 전에 React(act 포함 개발판)를 먼저 읽는다.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";

import { MinimalEvent, findElements, installMinimalDom } from "./product-studio-dom.mjs";
import { acceptRefMessage } from "../../packages/ui/src/studio-web-page-bridge.js";
import { downloadStudioExport } from "../../apps/web/lib/studio-v2-api.js";

const root = path.resolve(import.meta.dirname, "../..");
const read = (file) => readFile(path.join(root, file), "utf8");
const OID = `sv2-${"a".repeat(32)}`;
const TURN = `svt-${"b".repeat(32)}`;
// 실제 DOM의 setAttribute는 HTML 속성 이름을 소문자로 바꾼다. 최소 DOM은 그대로 두므로 대소문자 없이 읽는다.
const attr = (node, name) => { for (const [key, value] of node.attributes) if (key.toLowerCase() === name) return value; return null; };

// ---- acceptRefMessage(순수 함수) ----
const frame = { name: "own-frame" };
const known = new Set(["S1", "S2"]);
const message = (data, source = frame) => ({ source, data, origin: "null" });

test("accepts own frame daon-ref", () => {
  assert.equal(acceptRefMessage(message({ type: "daon-ref", ref: "S2" }), frame, known), "S2");
});

test("rejects other source", () => {
  assert.equal(acceptRefMessage(message({ type: "daon-ref", ref: "S2" }, { name: "other" }), frame, known), null);
  assert.equal(acceptRefMessage(message({ type: "daon-ref", ref: "S2" }, null), frame, known), null);
  assert.equal(acceptRefMessage(message({ type: "daon-ref", ref: "S2" }, undefined), undefined, known), null);
});

test("rejects wrong shape", () => {
  for (const data of [{ type: "other", ref: "S2" }, { type: "daon-ref", ref: "S2;x" }, { type: "daon-ref", ref: 2 }, { type: "daon-ref" },
    "daon-ref:S2", null, ["daon-ref", "S2"], { type: "daon-ref", ref: " S2" }, { type: "daon-ref", ref: "s2" }]) {
    assert.equal(acceptRefMessage(message(data), frame, known), null, JSON.stringify(data));
  }
});

test("ignores unknown ref", () => {
  assert.equal(acceptRefMessage(message({ type: "daon-ref", ref: "S99" }), frame, known), null);
  assert.equal(acceptRefMessage(message({ type: "daon-ref", ref: "S1" }), frame, new Set()), null);
});

// ---- 실제 렌더(vite 묶음 + 최소 DOM) ----
async function bundle(entry, name) {
  const output = await mkdtemp(path.join(root, `.${name}-`));
  const { build } = await import("vite");
  await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
    lib: { entry: path.join(root, entry), formats: ["es"], fileName: name },
    rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
  const built = (await readdir(output)).find((file) => file.startsWith(name) && /\.m?js$/u.test(file));
  const module = await import(`${pathToFileURL(path.join(output, built)).href}?v=${Date.now()}`);
  return { module, cleanup: () => rm(output, { recursive: true, force: true }) };
}

async function mount(Component, props) {
  const dom = installMinimalDom();
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(Component, props)); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 15)); });
  return { dom, container, act, unmount: () => act(async () => reactRoot.unmount()), restore: () => dom.restore() };
}

const HTML = '<!DOCTYPE html><html><head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'"></head><body><h1>제목</h1><a data-ref="S2">[S2]</a></body></html>';
const content = {
  body: { title: "안내 페이지", request: "요청", title_insufficient: false, html: HTML, sections: [
    { heading: "개요", blocks: [
      { type: "paragraph", text: "확인된 문장", refs: ["S1"], insufficient: false },
      { type: "paragraph", text: "<b>근거 없는</b> 문장", refs: [], insufficient: true },
      { type: "metric", label: "한도", value: "300만 원", refs: ["S9"], insufficient: true },
    ] },
  ] },
  warnings: [],
};
const evidence = [
  { ref_id: "S1", source_name: "약관.pdf", locator_kind: "page", locator_value: "1" },
  { ref_id: "S2", source_name: "안내서.docx", locator_kind: "section", locator_value: "2장" },
];

test("웹 페이지 뷰어: iframe은 srcDoc + sandbox=allow-scripts만, 뺀 내용 안내와 목록을 보인다", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-web-page-viewer.jsx", "studio-web-page-viewer");
  const opened = [];
  let view = null;
  try {
    view = await mount(module.WebPageViewer, { content, evidence, onOpenEvidence: (ref) => opened.push(ref) });
    const frames = findElements(view.container, (n) => n.tagName === "IFRAME");
    assert.equal(frames.length, 1);
    const iframe = frames[0];
    assert.equal(attr(iframe, "sandbox"), "allow-scripts");
    assert.equal(attr(iframe, "srcdoc"), HTML);
    assert.equal(attr(iframe, "referrerpolicy"), "no-referrer");
    assert.ok(attr(iframe, "title"));
    assert.equal(attr(iframe, "src"), null);
    const text = view.container.textContent;
    assert.ok(text.includes("근거 부족으로 뺀 내용 2건"), text);
    assert.ok(text.includes("<b>근거 없는</b> 문장"), "뺀 글은 글자 그대로(태그로 해석하지 않고) 보인다");
    assert.ok(text.includes("한도: 300만 원"));
    assert.equal(findElements(view.container, (n) => n.tagName === "B").length, 0);
    assert.ok(text.includes("약관.pdf") && text.includes("안내서.docx"));

    // 페이지 안 [S2] 클릭 → 근거 칸에서 그 항목으로 스크롤·강조, onOpenEvidence 호출
    const frameWindow = { name: "frame-window" };
    iframe.contentWindow = frameWindow;
    const item = findElements(view.container, (n) => n.tagName === "LI" && n.getAttribute("data-ref") === "S2")[0];
    const scrolled = [];
    item.scrollIntoView = (options) => scrolled.push(options);
    // 근거 칸 자체의 scrollTop만 바꾼다(바깥 칸은 움직이지 않는다). 항목은 칸 기준 500px, 높이 30px, 칸 높이 200px.
    const pane = findElements(view.container, (n) => n.tagName === "ASIDE")[0];
    Object.assign(pane, { scrollTop: 0, clientHeight: 200 });
    Object.assign(item, { offsetTop: 500, offsetHeight: 30 });
    const post = async (data, source) => {
      const event = new MinimalEvent("message", { bubbles: false });
      event.data = data; event.source = source; event.origin = "null";
      await view.act(async () => { view.dom.document.dispatchEvent(event); });
    };
    await post({ type: "daon-ref", ref: "S2" }, { name: "other-window" });
    await post({ type: "daon-ref", ref: "S99" }, frameWindow);
    assert.deepEqual(opened, []);
    await post({ type: "daon-ref", ref: "S2" }, frameWindow);
    assert.deepEqual(opened, ["S2"]);
    assert.equal(scrolled.length, 0, "scrollIntoView는 바깥 조상까지 움직이므로 쓰지 않는다");
    assert.equal(pane.scrollTop, 330);
    assert.equal(findElements(view.container, (n) => n.tagName === "LI" && n.getAttribute("data-ref") === "S2")[0].getAttribute("aria-current"), "true");

    // 근거 칸 항목을 누르면 기존 근거 창을 연다
    const button = findElements(item, (n) => n.tagName === "BUTTON")[0];
    await view.act(async () => { button[Object.keys(button).find((k) => k.startsWith("__reactProps$"))].onClick({}); });
    assert.deepEqual(opened, ["S2", "S2"]);

    // 뷰어가 떨어지면 message 듣기를 떼어 낸다
    await view.unmount();
    await post({ type: "daon-ref", ref: "S2" }, frameWindow);
    assert.deepEqual(opened, ["S2", "S2"]);
    assert.equal((view.dom.document.listeners.get("message") ?? []).length, 0);
  } finally { view?.restore(); await cleanup(); }
});

test("웹 페이지 뷰어: 뺀 내용이 없으면 안내 줄이 없고, 제목 근거 부족도 센다", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-web-page-viewer.jsx", "studio-web-page-viewer-b");
  try {
    const clean = { body: { ...content.body, sections: [{ heading: "개요", blocks: [content.body.sections[0].blocks[0]] }] } };
    assert.deepEqual(module.excludedItems(clean.body), []);
    const withTitle = { ...content.body, title_insufficient: true };
    assert.deepEqual(module.excludedItems(withTitle), ["안내 페이지", "<b>근거 없는</b> 문장", "한도: 300만 원"]);
    const bullets = { sections: [{ heading: "h", blocks: [{ type: "bullets", items: ["가", "나"], insufficient: true }, { type: "table", rows: [["a", "b"], ["1", "2"]], insufficient: true }] }] };
    assert.deepEqual(module.excludedItems(bullets), ["가 · 나", "a | b / 1 | 2"]);
    // 칸 안 스크롤 위치: 이미 보이면 그대로, 위에 있으면 위 끝, 아래에 있으면 아래 끝을 맞춘다.
    assert.equal(module.paneScrollTop({ itemTop: 50, itemHeight: 30, scrollTop: 0, paneHeight: 200 }), 0);
    assert.equal(module.paneScrollTop({ itemTop: 50, itemHeight: 30, scrollTop: 100, paneHeight: 200 }), 50);
    assert.equal(module.paneScrollTop({ itemTop: 500, itemHeight: 30, scrollTop: 0, paneHeight: 200 }), 330);
    const view = await mount(module.WebPageViewer, { content: clean, evidence, onOpenEvidence: () => {} });
    try { assert.ok(!view.container.textContent.includes("근거 부족으로 뺀 내용")); } finally { await view.unmount(); view.restore(); }
  } finally { await cleanup(); }
});

test("대화 수정: 준비된 고친 안의 preview_html은 같은 격리 iframe으로만 보인다", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-chat-edit.jsx", "studio-chat-edit-web-page");
  const turn = (over) => ({ turn_id: TURN, output_id: OID, base_revision: 3, instruction: "제목을 바꿔 줘", state: "ready", reply: "고쳤습니다",
    changes: [], error_code: null, applied_revision: null, created_at: "2026-11-10T00:00:00+00:00", preview_html: HTML, ...over });
  try { for (const [turns, expected] of [[[turn({})], 1], [[turn({ state: "working" })], 0], [[turn({ preview_html: undefined })], 0], [[turn({ state: "applied" })], 0]]) {
    const studio = { listEditTurns: async () => turns, createEditTurn: async () => ({}), applyEditTurn: async () => ({}), discardEditTurn: async () => {} };
    const view = await mount(module.StudioChatEdit, { studio, outputId: OID, pollMs: 100000 });
    try {
      const frames = findElements(view.container, (n) => n.tagName === "IFRAME");
      assert.equal(frames.length, expected, JSON.stringify(turns[0].state));
      for (const iframe of frames) {
        assert.equal(attr(iframe, "sandbox"), "allow-scripts");
        assert.equal(attr(iframe, "srcdoc"), HTML);
        assert.equal(attr(iframe, "referrerpolicy"), "no-referrer");
      }
    } finally { await view.unmount(); view.restore(); }
  } } finally { await cleanup(); }
});

// ---- 소스 계약 ----
test("iframe 소스 계약: sandbox는 정확히 allow-scripts, srcDoc 사용, 이 HTML에 dangerouslySetInnerHTML 없음", async () => {
  const viewer = await read("packages/ui/src/studio-web-page-viewer.jsx");
  assert.match(viewer, /sandbox="allow-scripts"/u);
  assert.match(viewer, /srcDoc=\{html\}/u);
  assert.doesNotMatch(viewer, /allow-same-origin|allow-forms|allow-popups|allow-top-navigation|allow-modals/u);
  for (const file of ["packages/ui/src/studio-web-page-viewer.jsx", "packages/ui/src/studio-chat-edit.jsx"]) {
    assert.doesNotMatch(await read(file), /dangerouslySetInnerHTML/u, file);
  }
  assert.match(viewer, /addEventListener\("message"/u);
  assert.match(viewer, /removeEventListener\("message"/u);
  const viewers = await read("packages/ui/src/studio-viewers.jsx");
  assert.match(viewers, /case "web_page": return <WebPageViewer \{\.\.\.common\} \/>;/u);
  assert.match(await read("packages/ui/src/studio-chat-edit.jsx"), /turn\.state === "ready" && typeof turn\.preview_html === "string"/u);
});

test("뷰어 배치: 두 칸 grid, 칸마다 min-height:0 + overflow:auto, 820px 이하에서 위아래로 쌓는다", async () => {
  const css = await read("packages/ui/src/studio-panel.css");
  const rule = (selector) => {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
    return new RegExp(`(^|\\n)\\s*${escaped}\\s*\\{([^}]*)\\}`, "u").exec(css)?.[2] ?? "";
  };
  const root = rule(".studio-web-page");
  assert.match(root, /display:\s*grid/u);
  assert.match(root, /grid-template-columns:\s*minmax\(0,\s*1fr\)\s+minmax\(/u);
  assert.match(root, /height:\s*100%/u);
  const pane = rule(".studio-web-page__page, .studio-web-page__evidence");
  assert.match(pane, /min-height:\s*0/u);
  assert.match(pane, /overflow:\s*auto/u);
  assert.doesNotMatch(root, /min-height:\s*360px/u);
  const body = rule(".studio-detail__body--web-page");
  assert.match(body, /display:\s*flex/u);
  assert.match(body, /flex-direction:\s*column/u);
  assert.match(body, /overflow:\s*hidden/u);
  const viewerInBody = rule(".studio-detail__body--web-page > .studio-web-page");
  assert.match(viewerInBody, /flex:\s*1 1 auto/u);
  assert.match(viewerInBody, /min-height:\s*0/u);
  const chatInBody = rule(".studio-detail__body--web-page > .studio-chat-edit");
  assert.match(chatInBody, /flex:\s*none/u);
  assert.match(chatInBody, /max-height:/u);
  assert.match(chatInBody, /min-height:\s*0/u);
  const turnsInBody = rule(".studio-detail__body--web-page .studio-chat-edit__turns");
  assert.match(turnsInBody, /overflow:\s*auto/u);
  assert.match(turnsInBody, /min-height:\s*0/u);
  assert.match(rule(".studio-web-page__preview"), /height:\s*min\(/u);
  assert.match(rule(".studio-web-page__evidence"), /position:\s*relative/u);
  const narrow = /@media \(max-width: 820px\)\s*\{\s*\.studio-web-page\s*\{([^}]*)\}/u.exec(css)?.[1] ?? "";
  assert.match(narrow, /grid-template-columns:\s*minmax\(0,\s*1fr\)/u);
  assert.match(narrow, /grid-template-rows:\s*minmax\(0,\s*2fr\)\s+minmax\(0,\s*1fr\)/u);
});

test("내려받기: include_sources 쿼리를 0/1로 붙이고, 패널은 html일 때만 '출처 목록 넣기'(기본 켬)를 보인다", async () => {
  const urls = [];
  const fetchImpl = async (url) => { urls.push(url); return new Response(new Uint8Array([60]), { headers: { "Content-Type": "text/html" } }); };
  await downloadStudioExport("ws-1", OID, "html", { notebookId: "nb-1", includeSources: false, fetchImpl });
  await downloadStudioExport("ws-1", OID, "html", { notebookId: "nb-1", includeSources: true, revision: 3, fetchImpl });
  await downloadStudioExport("ws-1", OID, "pdf", { notebookId: "nb-1", fetchImpl });
  assert.ok(urls[0].endsWith(`/outputs/${OID}/exports/html?include_sources=0`), urls[0]);
  assert.ok(urls[1].endsWith(`/outputs/${OID}/exports/html?revision=3&include_sources=1`), urls[1]);
  assert.ok(urls[2].endsWith(`/outputs/${OID}/exports/pdf`), urls[2]);
  const panel = await read("packages/ui/src/studio-panel.jsx");
  assert.match(panel, /const \[includeSources, setIncludeSources\] = useState\(true\)/u);
  assert.match(panel, /format === "html" && <div role="menuitemcheckbox" aria-checked=\{includeSources\}/u);
  assert.match(panel, /msg\("studio\.web_page\.include_sources"\)/u);
  assert.match(panel, /format === "html" \? \{ includeSources \}/u);
  // BFF가 html 내려받기와 include_sources 쿼리를 통과시킨다
  const proxy = await read("apps/web/lib/bff-api-proxy.js");
  assert.match(proxy, /STUDIO_V2_EXPORT_FORMATS = new Set\(\[[^\]]*"html"/u);
  assert.match(proxy, /STUDIO_V2_EXPORT_QUERY = new Set\(\["revision", "include_sources"\]\)/u);
});
