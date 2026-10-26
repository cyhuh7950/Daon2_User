import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import {
  AuthoringTemplateError, exportAuthoringTemplate, listAuthoringTemplates, registerAuthoringTemplate, setAuthoringTemplateStatus, updateAuthoringTemplate,
} from "../../apps/web/lib/authoring-templates-api.js";
import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

const root = path.resolve(import.meta.dirname, "../..");
const summary = (patch = {}) => ({ template_id: "org_sample", title: "조직 템플릿", description: "", version: 2, status: "active", sections: 2, style: "proposal", output_formats: ["docx"], ...patch });

async function mount(api, props = {}) {
  const output = await mkdtemp(path.join(root, ".authoring-templates-ui-"));
  const dom = installMinimalDom();
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { build } = await import("vite");
  await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
    lib: { entry: path.join(root, "packages/ui/src/authoring-templates-pane.jsx"), formats: ["es"], fileName: "at-pane" },
    rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
  const entry = (await readdir(output)).find((name) => name.startsWith("at-pane") && /\.m?js$/u.test(name));
  const { AuthoringTemplatesPane } = await import(`${pathToFileURL(path.join(output, entry)).href}?v=${Date.now()}`);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(AuthoringTemplatesPane, { api, ...props })); await Promise.resolve(); });
  const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 15)); });
  const reactProps = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];
  return { container, flush, act,
    click: async (node) => { await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await flush(); },
    setValue: async (label, value) => { const input = findElements(container, (node) => node.getAttribute?.("aria-label") === label)[0];
      input.value = value; await act(async () => reactProps(input).onChange({ target: input, currentTarget: input })); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await rm(output, { recursive: true, force: true }); } };
}

const text = (view) => view.container.textContent;
const byLabel = (view, label) => findElements(view.container, (node) => node.getAttribute?.("aria-label") === label)[0];

test("목록·편집(새 버전 저장)·비활성·내보내기를 연결하고, 검증 오류는 위치와 함께 보인다(F6-14)", async () => {
  const calls = [];
  let fail = null;
  const downloads = [];
  const api = {
    list: async () => [summary()],
    export: async (id) => ({ template_id: id, title: "조직 템플릿", description: "설명", version: 2, sections: [] }),
    update: async (id, version, definition) => {
      if (fail) throw Object.assign(new Error("x"), fail);
      calls.push(["update", id, version, definition.title]);
      return summary({ title: definition.title, version: version + 1 });
    },
    register: async () => summary(),
    setStatus: async (id, enabled) => { calls.push(["status", id, enabled]); return summary({ status: enabled ? "active" : "disabled" }); },
  };
  const view = await mount(api, { download: (name, body) => downloads.push([name, JSON.parse(body).template_id]) });
  try {
    await view.flush();
    assert.ok(text(view).includes("org_sample"));
    await view.click(byLabel(view, "조직 템플릿 내보내기"));
    assert.deepEqual(downloads, [["org_sample.json", "org_sample"]]);
    await view.click(byLabel(view, "조직 템플릿 편집"));
    await view.setValue("제목", "바뀐 제목");
    assert.ok(byLabel(view, "템플릿 정의(JSON)").value.includes("바뀐 제목"));
    fail = { code: "AUTHORING_TEMPLATE_INVALID", reason: "sections[0].key" };
    await view.click(buttonByText(view.container, "검증 후 저장"));
    assert.ok(text(view).includes("위치: sections[0].key"));
    fail = null;
    await view.click(buttonByText(view.container, "검증 후 저장"));
    assert.deepEqual(calls[0], ["update", "org_sample", 2, "바뀐 제목"]);
    assert.ok(text(view).includes("저장했습니다(버전 3)"));
    await view.click(byLabel(view, "조직 템플릿 비활성"));
    assert.deepEqual(calls[1], ["status", "org_sample", false]);
  } finally { await view.close(); }
});

test("JSON이 깨졌으면 서버에 보내지 않고, 비관리자(403)에게는 안내만 보인다", async () => {
  let registered = 0;
  const view = await mount({ list: async () => [], register: async () => { registered += 1; return summary(); }, export: async () => ({}), update: async () => ({}), setStatus: async () => ({}) });
  try {
    await view.flush();
    assert.ok(text(view).includes("등록된 조직 템플릿이 없습니다"));
    await view.click(buttonByText(view.container, "새 템플릿"));
    await view.setValue("템플릿 정의(JSON)", "{ 깨진");
    await view.click(buttonByText(view.container, "검증 후 저장"));
    assert.ok(text(view).includes("JSON 형식이 올바르지 않습니다"));
    assert.equal(registered, 0);
    await view.click(buttonByText(view.container, "예시 채우기"));
    await view.click(buttonByText(view.container, "검증 후 저장"));
    assert.equal(registered, 1);
  } finally { await view.close(); }
  const forbidden = await mount({ list: async () => { throw Object.assign(new Error("x"), { status: 403 }); } });
  try {
    await forbidden.flush();
    assert.ok(text(forbidden).includes("관리자만 작성 템플릿을 관리할 수 있습니다"));
    assert.equal(buttonByText(forbidden.container, "새 템플릿").disabled, true);
  } finally { await forbidden.close(); }
});

test("BFF 클라이언트는 If-Match와 위치 사유만 쓰고 원문 오류는 숨긴다", async () => {
  const requests = [];
  const respond = (data, status = 200) => new Response(JSON.stringify({ data, meta: { trace_id: "t" } }), { status });
  const fetchImpl = async (url, init) => {
    requests.push({ url, init });
    if (init.method === "GET" && url.endsWith("/authoring-templates")) return respond({ templates: [summary()] });
    if (init.method === "GET") return respond({ definition: { template_id: "org_sample" } });
    if (init.method === "POST" && url.endsWith("/disable")) return respond(summary({ status: "disabled" }));
    if (init.method === "POST") return respond(summary(), 201);
    return respond(summary({ version: 3 }));
  };
  assert.equal((await listAuthoringTemplates({ fetchImpl })).length, 1);
  await registerAuthoringTemplate({ template_id: "org_sample" }, { fetchImpl });
  assert.equal((await exportAuthoringTemplate("org_sample", { fetchImpl })).template_id, "org_sample");
  await updateAuthoringTemplate("org_sample", 2, { template_id: "org_sample" }, { fetchImpl });
  await setAuthoringTemplateStatus("org_sample", false, { fetchImpl });
  const put = requests.find((request) => request.init.method === "PUT");
  assert.equal(put.init.headers["If-Match"], '"authoring-template:org_sample:2"');
  assert.ok(requests.at(-1).url.endsWith("/org_sample/disable"));
  const failing = async () => new Response(JSON.stringify({ error: { code: "AUTHORING_TEMPLATE_INVALID", message: "http://10.0.0.5 내부", details: { reason: "sections[2].key" } } }), { status: 422 });
  await assert.rejects(() => registerAuthoringTemplate({ a: 1 }, { fetchImpl: failing }),
    (error) => error instanceof AuthoringTemplateError && error.code === "AUTHORING_TEMPLATE_INVALID" && error.reason === "sections[2].key" && !String(error.message).includes("10.0.0.5"));
  await assert.rejects(() => exportAuthoringTemplate("not-org", { fetchImpl }), AuthoringTemplateError);
});
