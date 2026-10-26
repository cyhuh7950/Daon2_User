// Studio 화면의 자동 접근성 검사(F8-07/S6-01). 실제 렌더 결과 DOM에서 기계적으로 확인할 수 있는 규칙만 본다:
// 버튼·입력의 접근 가능한 이름, 대화상자 이름과 aria-modal, 탭 role의 aria-selected, 이미지 대체 텍스트.
// 색 대비는 아이콘 시험(studio-icon.test)과 디자인 토큰 시험이 맡고, 스크린리더 읽기 순서는 수동 확인이다.
import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

const root = path.resolve(import.meta.dirname, "../..");

async function bundle(entry, fileName) {
  const output = await mkdtemp(path.join(root, ".studio-a11y-"));
  const { build } = await import("vite");
  await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
    lib: { entry: path.join(root, entry), formats: ["es"], fileName },
    rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
  const built = (await readdir(output)).find((name) => name.startsWith(fileName) && /\.m?js$/u.test(name));
  return { module: await import(`${pathToFileURL(path.join(output, built)).href}?v=${Date.now()}`), cleanup: () => rm(output, { recursive: true, force: true }) };
}

const byId = (container, id) => findElements(container.getRootNode(), (n) => n.getAttribute?.("id") === id)[0];
const attr = (node, name) => (node.getAttribute?.(name) ?? "").trim();

function accessibleName(node, container) {
  if (attr(node, "aria-label")) return attr(node, "aria-label");
  const labelledBy = attr(node, "aria-labelledby");
  if (labelledBy) return labelledBy.split(/\s+/u).map((id) => byId(container, id)?.textContent ?? "").join(" ").trim();
  if (attr(node, "title")) return attr(node, "title");
  for (let up = node.parentNode; up; up = up.parentNode) if (up.tagName === "LABEL") return up.textContent.trim();
  const id = attr(node, "id");
  if (id) { const label = findElements(container.getRootNode(), (n) => n.tagName === "LABEL" && attr(n, "for") === id)[0]; if (label) return label.textContent.trim(); }
  return node.tagName === "BUTTON" ? node.textContent.trim() : "";
}

export function a11yViolations(container) {
  const found = [];
  for (const node of findElements(container, () => true)) {
    const tag = node.tagName;
    const role = attr(node, "role");
    if (tag === "BUTTON" || role === "button") {
      if (!accessibleName(node, container)) found.push(`button without name: ${node.textContent.slice(0, 20)}`);
    }
    if ((tag === "INPUT" && !["hidden"].includes(attr(node, "type"))) || tag === "TEXTAREA" || tag === "SELECT") {
      if (!accessibleName(node, container)) found.push(`${tag.toLowerCase()} without name`);
    }
    if (role === "dialog") {
      if (attr(node, "aria-modal") !== "true") found.push("dialog without aria-modal");
      if (!accessibleName(node, container)) found.push("dialog without name");
    }
    if (role === "tab" && !node.attributes.has("aria-selected")) found.push("tab without aria-selected");
    if (tag === "IMG" && !node.attributes.has("alt")) found.push("img without alt");
    if (tag === "svg" || tag === "SVG") {
      const labelled = role === "img" && node.textContent.trim();
      if (attr(node, "aria-hidden") !== "true" && !labelled) found.push("svg neither hidden nor labelled");
    }
  }
  return found;
}

async function mount(Component, props, file, name) {
  const dom = installMinimalDom();
  // React는 번들 빌드(NODE_ENV=production 설정)보다 먼저 불러와야 act가 있는 개발 빌드를 쓴다.
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const built = await bundle(file, name);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  const element = createElement(built.module[Component], props);
  await act(async () => { reactRoot.render(element); });
  const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  return { container, act, flush, click: async (node) => { await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await flush(); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await built.cleanup(); } };
}

test("검사기 자체: 이름 없는 버튼·입력·대화상자를 잡아낸다", async () => {
  const dom = installMinimalDom();
  try {
    const wrap = dom.document.createElement("div"); dom.document.body.appendChild(wrap);
    const button = dom.document.createElement("button"); wrap.appendChild(button);
    const input = dom.document.createElement("input"); wrap.appendChild(input);
    const dialog = dom.document.createElement("section"); dialog.setAttribute("role", "dialog"); wrap.appendChild(dialog);
    assert.deepEqual(a11yViolations(wrap).sort(), ["button without name: ", "dialog without aria-modal", "dialog without name", "input without name"].sort());
  } finally { dom.restore(); }
});

test("노트북 도구(메뉴·맞춤설정 대화상자)는 접근성 규칙을 지킨다", async () => {
  const studio = { getCustomization: async () => ({ instruction: "", version: 0, etag: null }), saveCustomization: async () => ({ instruction: "", version: 1, etag: '"e"' }) };
  const view = await mount("NotebookTools", { studio, onOpenChatSettings: () => {} }, "packages/ui/src/notebook-menu.jsx", "a11y-notebook-menu");
  try {
    await view.click(findElements(view.container, (n) => attr(n, "aria-label") === "노트북 메뉴")[0]);
    assert.deepEqual(a11yViolations(view.container), []);
    await view.click(findElements(view.container, (n) => attr(n, "role") === "menuitem")[1]);
    await view.flush();
    assert.ok(findElements(view.container, (n) => attr(n, "role") === "dialog").length === 1);
    assert.deepEqual(a11yViolations(view.container), []);
  } finally { await view.close(); }
});

test("산출물 편집기 4종은 모든 입력과 삭제 버튼에 이름이 있다", async () => {
  const bodies = {
    report: { title: "t", summary: "s", sections: [{ heading: "h", blocks: [{ type: "paragraph", text: "p", refs: [] }, { type: "bullets", items: ["a"], refs: [] }, { type: "table", rows: [["a"]], refs: [] }] }] },
    slides: { title: "t", slides: [{ layout: "bullets", title: "s", bullets: ["a"], notes: "n", refs: [] }] },
    flashcards: { cards: [{ front: "f", back: "b", refs: [] }] },
    quiz: { questions: [{ q: "q", options: ["a", "b", "c", "d"], answer_index: 0, explanation: "e", refs: [] }] },
  };
  for (const [type, body] of Object.entries(bodies)) {
    const output = { type_id: type, revision: { content: { body } } };
    const view = await mount("StudioEditor", { output, onSave: async () => {}, onCancel: () => {} }, "packages/ui/src/studio-editor.jsx", `a11y-editor-${type}`);
    try {
      assert.ok(buttonByText(view.container, "저장"));
      assert.deepEqual(a11yViolations(view.container), [], type);
    } finally { await view.close(); }
  }
});

test("작성 마법사(템플릿 목록·검토·완료 화면)는 접근성 규칙을 지킨다", async () => {
  const base = { output_id: "sv2-" + "c".repeat(32), template_id: "rfp_response_proposal", request_text: "", inputs: {}, assumptions: [], requirements: [], plan: null,
    output_formats: ["docx"], error_code: null, document: null, knowledge_count: 0, job_status: "completed", revision_no: 3, pending_questions: [], requests: [] };
  const review = { ...base, state: "review", requirements: [{ id: "REQ-001", text: "다중 인증", mandatory: true, category: "", refs: [] }],
    plan: { sections: [{ key: "a", title: "1. 사업의 이해", purpose: "", knowledge_refs: [], requirement_ids: ["REQ-001"] }] } };
  const done = { ...base, state: "completed", document: { notice: "AI 작성 초안", sections: [{ key: "a", title: "1. 사업의 이해", paragraphs: [{ text: "문장", refs: ["S1"] }], open_items: [] }],
    coverage: [{ requirement_id: "REQ-001", text: "다중 인증", status: "covered" }], checks: [{ id: "x", title: "점검", status: "done", results: [{ rule_id: "r", status: "pass", message: "확인" }] }],
    open_items: [], assumptions: [], style: "proposal" } };
  const studio = (session) => ({ downloadExport: async () => ({}), authoring: { listTemplates: async () => [{ template_id: "rfp_response_proposal", title: "RFP 대응 제안서", description: "설명", version: 1 }],
    createSession: async () => ({ created: true, ...session }), getSession: async () => session, answer: async () => ({}), review: async () => ({}), listConnectors: async () => [], listDocuments: async () => [] } });
  const sources = [{ sourceVersionId: "sv-rfp", filename: "rfp.txt", ready: true }];
  for (const [label, props] of [["목록", { studio: studio(review) }], ["검토", { studio: studio(review), outputId: base.output_id }], ["완료", { studio: studio(done), outputId: base.output_id }]]) {
    const view = await mount("AuthoringWizard", { sources, ...props }, "packages/ui/src/authoring-wizard.jsx", `a11y-wizard-${label === "목록" ? "a" : label === "검토" ? "b" : "c"}`);
    try {
      await view.flush();
      assert.deepEqual(a11yViolations(view.container), [], label);
    } finally { await view.close(); }
  }
});

test("노트북 복사·채팅 기록 삭제 대화상자는 접근성 규칙을 지킨다", async () => {
  const studio = { copyNotebook: async () => ({}), clearChatHistory: async () => {}, getCustomization: async () => ({}), saveCustomization: async () => ({}) };
  const view = await mount("NotebookTools", { studio, title: "원본" }, "packages/ui/src/notebook-menu.jsx", "a11y-notebook-dialogs");
  try {
    for (const index of [2, 3]) {
      await view.click(findElements(view.container, (n) => attr(n, "aria-label") === "노트북 메뉴")[0]);
      await view.click(findElements(view.container, (n) => attr(n, "role") === "menuitem")[index]);
      assert.equal(findElements(view.container, (n) => attr(n, "role") === "dialog").length, 1);
      assert.deepEqual(a11yViolations(view.container), [], `menu ${index}`);
      await view.click(findElements(view.container, (n) => attr(n, "aria-label") === "대화상자 닫기")[0]);
    }
  } finally { await view.close(); }
});

test("인용 번호 버튼은 WCAG 2.2 최소 대상 크기(24px)를 가로로도 지킨다", async () => {
  const { readFile } = await import("node:fs/promises");
  const css = await readFile(new URL("../../packages/ui/src/studio-panel.css", import.meta.url), "utf8");
  const rule = css.split("\n").find((line) => line.startsWith(".studio-ref {"));
  assert.ok(rule, ".studio-ref 규칙이 있다");
  assert.match(rule, /min-width:\s*24px/u);
});

test("산출물 카드는 목록이 길어도 줄어들지 않는다(긴 오류 문구가 다음 카드와 겹치지 않게 flex: none)", async () => {
  const { readFile } = await import("node:fs/promises");
  const css = await readFile(new URL("../../packages/ui/src/studio-panel.css", import.meta.url), "utf8");
  const rule = css.split(/\r?\n/u).find((line) => line.startsWith(".studio-card {"));
  assert.ok(rule, ".studio-card 규칙이 있다");
  assert.match(rule, /flex:\s*none/u);
});
