import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { getNotebookKnowledgeScopes, listDaonKnowledgeScopes, saveNotebookKnowledgeScopes } from "../../apps/web/lib/daon-knowledge-scopes-api.js";
import { registerKnowledgeConnector } from "../../apps/web/lib/knowledge-connectors-api.js";
import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

const root = path.resolve(import.meta.dirname, "../..");
const CATALOG = { projects: [{ project_id: "p1", project_name: "데모 프로젝트", work_packages: [
  { work_package_id: "w1", work_package_name: "제안서 작업", updated_at: null },
  { work_package_id: "w2", work_package_name: "보험 지원", updated_at: null }] }] };
const selected = (id, name) => ({ project_id: "p1", project_name: "데모 프로젝트", work_package_id: id, work_package_name: name });

async function mount(adapter) {
  const output = await mkdtemp(path.join(root, ".daon-scope-ui-"));
  const dom = installMinimalDom();
  const { build } = await import("vite");
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
    lib: { entry: path.join(root, "packages/ui/src/daon-knowledge-scope-section.jsx"), formats: ["es"], fileName: "scope-section" },
    rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
  const entry = (await readdir(output)).find((name) => name.startsWith("scope-section") && /\.m?js$/u.test(name));
  const { DaonKnowledgeScopeSection } = await import(`${pathToFileURL(path.join(output, entry)).href}?v=${Date.now()}`);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 15)); });
  await act(async () => { reactRoot.render(createElement(DaonKnowledgeScopeSection, { adapter })); });
  await flush();
  return { container, flush, click: async (node) => { await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await flush(); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await rm(output, { recursive: true, force: true }); } };
}

const byLabel = (view, label) => findElements(view.container, (node) => node.getAttribute?.("aria-label") === label)[0];
const dialogs = (view) => findElements(view.container, (node) => node.getAttribute?.("role") === "dialog");

test("패널은 선택한 업무 패키지만 보이고 제목을 누르면 팝업이 전체 목록을 보여 준다", async () => {
  const view = await mount({ getNotebookKnowledgeScopes: async () => ({ items: [selected("w1", "제안서 작업")] }), listDaonKnowledgeScopes: async () => CATALOG });
  try {
    assert.ok(view.container.textContent.includes("제안서 작업"));
    assert.ok(!view.container.textContent.includes("보험 지원"));
    assert.equal(dialogs(view).length, 0);
    await view.click(buttonByText(view.container, "Daon 승인 지식"));
    assert.equal(dialogs(view).length, 1);
    assert.ok(view.container.textContent.includes("데모 프로젝트"));
    assert.ok(view.container.textContent.includes("보험 지원"));
    assert.equal(byLabel(view, "데모 프로젝트 제안서 작업 선택").checked, true);
    assert.equal(byLabel(view, "데모 프로젝트 보험 지원 선택").checked, false);
  } finally { await view.close(); }
});

test("여러 업무 패키지를 골라 적용하면 저장 결과가 패널에 반영된다", async () => {
  const saved = [];
  const view = await mount({ getNotebookKnowledgeScopes: async () => ({ items: [selected("w1", "제안서 작업")] }), listDaonKnowledgeScopes: async () => CATALOG,
    saveNotebookKnowledgeScopes: async (items) => { saved.push(items); return { items: [selected("w1", "제안서 작업"), selected("w2", "보험 지원")] }; } });
  try {
    await view.click(buttonByText(view.container, "Daon 승인 지식"));
    await view.click(byLabel(view, "데모 프로젝트 보험 지원 선택"));
    await view.click(buttonByText(view.container, "적용"));
    assert.deepEqual(saved, [[{ project_id: "p1", work_package_id: "w1" }, { project_id: "p1", work_package_id: "w2" }]]);
    assert.equal(dialogs(view).length, 0);
    assert.ok(view.container.textContent.includes("보험 지원"));
  } finally { await view.close(); }
});

test("목록 오류는 안전한 문구로 보이고 빈 목록과 구분된다", async () => {
  const failing = await mount({ getNotebookKnowledgeScopes: async () => ({ items: [] }),
    listDaonKnowledgeScopes: async () => { const error = new Error("raw detail"); error.code = "KNOWLEDGE_CONNECTOR_NOT_CONFIGURED"; throw error; } });
  try {
    await failing.click(buttonByText(failing.container, "Daon 승인 지식"));
    assert.ok(failing.container.textContent.includes("Daon2-RAG 연결이 준비되지 않았습니다"));
    assert.ok(!failing.container.textContent.includes("raw detail"));
    assert.ok(!failing.container.textContent.includes("승인된 업무 패키지가 없습니다"));
  } finally { await failing.close(); }
  const empty = await mount({ getNotebookKnowledgeScopes: async () => ({ items: [] }), listDaonKnowledgeScopes: async () => ({ projects: [] }) });
  try {
    await empty.click(buttonByText(empty.container, "Daon 승인 지식"));
    assert.ok(empty.container.textContent.includes("승인된 업무 패키지가 없습니다"));
  } finally { await empty.close(); }
});

const respond = (data, status = 200) => ({ ok: status < 400, status, json: async () => data, headers: { get: () => null } });

test("API 클라이언트는 노트북 경로로 조회·저장하고 오류 코드만 전달한다", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push([url, init]); return respond({ data: { items: [] }, meta: {} }); };
  await getNotebookKnowledgeScopes("ws-1", "nb-1", { fetchImpl });
  await saveNotebookKnowledgeScopes("ws-1", "nb-1", [{ project_id: "p1", work_package_id: "w1" }], { fetchImpl });
  assert.equal(calls[0][0], "/bff/api/workspaces/ws-1/notebooks/nb-1/knowledge-scopes");
  assert.equal(calls[1][1].method, "PUT");
  assert.deepEqual(JSON.parse(calls[1][1].body), { items: [{ project_id: "p1", work_package_id: "w1" }] });
  await assert.rejects(listDaonKnowledgeScopes("ws-1", { fetchImpl: async () => respond({ error: { code: "KNOWLEDGE_SERVER_UNAVAILABLE", message: "secret detail" } }, 503) }),
    (error) => error.code === "KNOWLEDGE_SERVER_UNAVAILABLE" && !error.message.includes("secret detail"));
});

test("토큰 발급 방식 등록은 서버 형식으로 보낸다", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push([url, init]); return respond({ data: { connector_id: `kc-${"a".repeat(32)}`, name: "RAG", kind: "daon2_rag", status: "unverified" } }, 201); };
  await registerKnowledgeConnector({ kind: "daon2_rag", name: "RAG", endpointUrl: "https://rag.example/mcp",
    oauth: { tokenUrl: "https://issuer.example/oauth/token", clientId: "stc_x", clientSecret: "s3cret", resource: "https://rag.example/mcp", scope: "rag.mcp.evidence.read" }, fetchImpl });
  assert.deepEqual(JSON.parse(calls[0][1].body).oauth, { token_url: "https://issuer.example/oauth/token", client_id: "stc_x", client_secret: "s3cret", resource: "https://rag.example/mcp", scope: "rag.mcp.evidence.read" });
});

test("BFF는 목록·선택 경로만 열고 선택 저장에 CSRF 출처 확인을 요구한다", async () => {
  const source = await readFile(path.join(root, "apps/web/lib/bff-api-proxy.js"), "utf8");
  assert.match(source, /segments\[2\] === "daon-knowledge-scopes"/u);
  assert.match(source, /segments\[4\] === "knowledge-scopes"[\s\S]{0,400}csrfProvenanceRequired: method === "PUT"/u);
});
