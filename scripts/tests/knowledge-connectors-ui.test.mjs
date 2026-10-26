import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import {
  KnowledgeConnectorError, disconnectKnowledgeConnector, listKnowledgeConnectors, registerKnowledgeConnector, updateKnowledgeConnectorLimits,
  updateKnowledgeConnectorTools, verifyKnowledgeConnector,
} from "../../apps/web/lib/knowledge-connectors-api.js";
import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

const root = path.resolve(import.meta.dirname, "../..");
const ID = `kc-${"a".repeat(32)}`;
const connector = (patch = {}) => ({ connector_id: ID, kind: "daon2_rag", name: "가상 Daon2-RAG", status: "verified", virtual: true, last_checked_at: "2026-10-20T08:15:00+00:00", error_code: null, ...patch });

async function mount(api) {
  const output = await mkdtemp(path.join(root, ".knowledge-connectors-ui-"));
  const dom = installMinimalDom();
  const { build } = await import("vite");
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
    lib: { entry: path.join(root, "packages/ui/src/knowledge-connectors-pane.jsx"), formats: ["es"], fileName: "kc-pane" },
    rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
  const entry = (await readdir(output)).find((name) => name.startsWith("kc-pane") && /\.m?js$/u.test(name));
  const { KnowledgeConnectorsPane } = await import(`${pathToFileURL(path.join(output, entry)).href}?v=${Date.now()}`);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(KnowledgeConnectorsPane, { api })); await Promise.resolve(); });
  const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 15)); });
  const props = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];
  return { container, flush, act,
    click: async (node) => { await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await flush(); },
    type: async (label, value) => { const input = findElements(container, (node) => node.getAttribute?.("aria-label") === label)[0];
      input.value = value; await act(async () => props(input).onChange({ target: input, currentTarget: input })); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await rm(output, { recursive: true, force: true }); } };
}

const text = (view) => view.container.textContent;

test("목록은 이름·종류·상태 배지·가상 배지·마지막 확인을 보이고, 연결 확인은 진행 뒤 결과를 알린다", async () => {
  let status = "registered";
  const verified = [];
  const view = await mount({ list: async () => [connector({ status })],
    verify: async (id) => { verified.push(id); status = "verified"; return { status: "verified" }; } });
  try {
    await view.flush();
    assert.ok(text(view).includes("가상 Daon2-RAG"));
    assert.ok(text(view).includes("가상"));
    assert.ok(text(view).includes("확인 전"));
    assert.ok(text(view).includes("2026-10-20 08:15"));
    await view.click(buttonByText(view.container, "연결 확인"));
    assert.deepEqual(verified, [ID]);
    assert.ok(text(view).includes("연결을 확인했습니다"));
    assert.ok(text(view).includes("연결됨"));
  } finally { await view.close(); }
});

test("등록 대화상자: 이름·주소가 있어야 등록되고 토큰·허용 도구·컬렉션이 전달되며 오류는 안전한 문구만 보인다", async () => {
  const calls = [];
  let attempt = 0;
  const view = await mount({ list: async () => [],
    register: async (input) => { calls.push(input); attempt += 1; if (attempt === 1) { const error = new Error("x"); error.code = "CONNECTOR_ENDPOINT_PRIVATE_DENIED"; throw error; } return connector(); } });
  try {
    await view.flush();
    assert.ok(text(view).includes("등록된 지식 연결이 없습니다"));
    await view.click(buttonByText(view.container, "연결 추가"));
    assert.equal(buttonByText(view.container, "등록").disabled, true);
    await view.type("이름", "지식 서버");
    await view.type("서버 주소", "https://knowledge.example/mcp");
    await view.type("인증 토큰", "secret-token-value");
    await view.type("프로젝트 1", "proj-alpha");
    await view.type("작업 패키지 1", "wp-proposals");
    const toolLabel = findElements(view.container, (node) => node.tagName === "LABEL" && node.textContent === "get_document_evidence")[0];
    await view.click(findElements(toolLabel, (node) => node.tagName === "INPUT")[0]);
    await view.click(buttonByText(view.container, "등록"));
    assert.deepEqual(calls[0], { kind: "daon2_rag", name: "지식 서버", endpointUrl: "https://knowledge.example/mcp", token: "secret-token-value",
      allowedTools: ["get_document_evidence"], allowedScopes: [{ projectId: "proj-alpha", workPackageId: "wp-proposals" }] });
    assert.ok(findElements(view.container, (node) => node.getAttribute?.("role") === "alert")[0].textContent.includes("사설 주소는 이 환경에서 연결할 수 없습니다"));
    await view.click(buttonByText(view.container, "등록"));
    assert.equal(calls.length, 2);
    assert.ok(text(view).includes("지식 연결을 등록했습니다"));
    assert.equal(findElements(view.container, (node) => node.getAttribute?.("role") === "dialog").length, 0);
  } finally { await view.close(); }
});

test("호출 한도 대화상자는 채운 항목만 저장하고 범위 오류는 안내한다(F4-02)", async () => {
  const saved = [];
  let fail = false;
  const view = await mount({ list: async () => [connector({ version: 1, limits: { timeout_seconds: 10 } })], updateLimits: async (id, version, limits) => {
    if (fail) { const error = new Error("x"); error.code = "CONNECTOR_LIMITS_INVALID"; throw error; }
    saved.push([id, version, limits]);
  } });
  try {
    await view.flush();
    await view.click(findElements(view.container, (node) => node.getAttribute?.("aria-label") === "가상 Daon2-RAG 호출 한도")[0]);
    const timeout = findElements(view.container, (node) => node.getAttribute?.("aria-label") === "호출 제한 시간(초)")[0];
    assert.equal(timeout.value, "10");
    const concurrent = findElements(view.container, (node) => node.getAttribute?.("aria-label") === "동시 호출 수")[0];
    concurrent.value = "2";
    await view.act(async () => concurrent[Object.keys(concurrent).find((key) => key.startsWith("__reactProps$"))].onChange({ target: concurrent }));
    fail = true;
    await view.click(buttonByText(view.container, "저장"));
    assert.ok(text(view).includes("한도 값이 허용 범위를 벗어났습니다."));
    fail = false;
    await view.click(buttonByText(view.container, "저장"));
    assert.deepEqual(saved, [[ID, 1, { max_concurrent: 2, timeout_seconds: 10 }]]);
    assert.ok(text(view).includes("호출 한도를 저장했습니다"));
  } finally { await view.close(); }
});

test("해제는 확인 대화상자를 거치고, 비관리자(403)에게는 안내만 보인다", async () => {
  const removed = [];
  const view = await mount({ list: async () => [connector()], disconnect: async (id) => { removed.push(id); } });
  try {
    await view.flush();
    await view.click(findElements(view.container, (node) => node.getAttribute?.("aria-label") === "가상 Daon2-RAG 해제")[0]);
    assert.deepEqual(removed, []);
    assert.ok(text(view).includes("연결을 해제할까요?"));
    await view.click(buttonByText(view.container, "해제 확인"));
    assert.deepEqual(removed, [ID]);
    assert.ok(text(view).includes("연결을 해제했습니다"));
  } finally { await view.close(); }
  const forbidden = await mount({ list: async () => { const error = new Error("x"); error.status = 403; throw error; } });
  try {
    await forbidden.flush();
    assert.ok(text(forbidden).includes("관리자만 지식 연결을 관리할 수 있습니다"));
    assert.equal(buttonByText(forbidden.container, "연결 추가").disabled, true);
  } finally { await forbidden.close(); }
});

test("BFF 클라이언트는 same-origin·Idempotency-Key·If-Match를 쓰고 오류 코드만 노출한다", async () => {
  const requests = [];
  const respond = (data, status = 200, headers = {}) => new Response(status === 204 ? null : JSON.stringify({ data, meta: { trace_id: "t" } }), { status, headers });
  const fetchImpl = async (url, init) => {
    requests.push({ url, init });
    if (init.method === "GET") return respond({ connectors: [connector()] });
    if (init.method === "POST" && url.endsWith("/verify")) return respond({ status: "verified" });
    if (init.method === "POST") return respond(connector(), 201);
    if (init.method === "PATCH") return respond(connector({ version: 2 }));
    return respond(null, 204);
  };
  assert.equal((await listKnowledgeConnectors({ fetchImpl })).length, 1);
  await registerKnowledgeConnector({ kind: "daon2_rag", name: "n", endpointUrl: "https://knowledge.example/mcp", token: "tok", allowedTools: ["list_documents"],
    allowedScopes: [{ projectId: "p", workPackageId: "w" }], fetchImpl });
  await verifyKnowledgeConnector(ID, { fetchImpl });
  await updateKnowledgeConnectorTools(ID, 3, ["list_documents"], { fetchImpl });
  await updateKnowledgeConnectorLimits(ID, 4, { calls_per_minute: 60 }, { fetchImpl });
  await disconnectKnowledgeConnector(ID, { fetchImpl });
  const [list, register, verify, patch, limitsPatch, remove] = requests;
  assert.deepEqual(JSON.parse(limitsPatch.init.body), { limits: { calls_per_minute: 60 } });
  assert.equal(limitsPatch.init.headers["If-Match"], `"knowledge-connector:${ID}:4"`);
  await assert.rejects(() => updateKnowledgeConnectorLimits(ID, 1, { nope: 1 }, { fetchImpl }), KnowledgeConnectorError);
  assert.equal(list.init.credentials, "same-origin");
  assert.match(register.init.headers["Idempotency-Key"], /^connector-/u);
  assert.deepEqual(JSON.parse(register.init.body), { kind: "daon2_rag", name: "n", endpoint_url: "https://knowledge.example/mcp", token: "tok",
    allowed_tools: ["list_documents"], allowed_scopes: [{ project_id: "p", work_package_id: "w" }] });
  assert.ok(verify.url.endsWith(`/admin/knowledge-connectors/${ID}/verify`));
  assert.equal(patch.init.headers["If-Match"], `"knowledge-connector:${ID}:3"`);
  assert.equal(remove.init.method, "DELETE");
  const failing = async () => new Response(JSON.stringify({ error: { code: "CONNECTOR_VERSION_CONFLICT", message: "내부 상세 http://10.0.0.5" } }), { status: 409 });
  await assert.rejects(() => updateKnowledgeConnectorTools(ID, 1, [], { fetchImpl: failing }), (error) => error instanceof KnowledgeConnectorError && error.code === "CONNECTOR_VERSION_CONFLICT" && !String(error.message).includes("10.0.0.5"));
  await assert.rejects(() => verifyKnowledgeConnector("bad-id", { fetchImpl }), (error) => error.code === "CONNECTOR_INPUT_INVALID");
});

test("소스 코드에는 서버 주소 리터럴(http://)이 없다(보안 스캔 규칙)", async () => {
  for (const file of ["apps/web/app/settings/knowledge-connectors/page.jsx", "apps/web/lib/knowledge-connectors-api.js", "packages/ui/src/knowledge-connectors-pane.jsx"]) {
    assert.ok(!(await readFile(path.join(root, file), "utf8")).includes("http://"), file);
  }
});
