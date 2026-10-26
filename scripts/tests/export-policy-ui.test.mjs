import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { ExportPolicyError, getExportPolicy, setExportPolicy } from "../../apps/web/lib/export-policy-api.js";
import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

const root = path.resolve(import.meta.dirname, "../..");

async function mount(api) {
  const output = await mkdtemp(path.join(root, ".export-policy-ui-"));
  const dom = installMinimalDom();
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { build } = await import("vite");
  await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
    lib: { entry: path.join(root, "packages/ui/src/export-policy-pane.jsx"), formats: ["es"], fileName: "ep-pane" },
    rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
  const entry = (await readdir(output)).find((name) => name.startsWith("ep-pane") && /\.m?js$/u.test(name));
  const { ExportPolicyPane } = await import(`${pathToFileURL(path.join(output, entry)).href}?v=${Date.now()}`);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(ExportPolicyPane, { api })); await Promise.resolve(); });
  const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 15)); });
  return { container, flush, act, click: async (node) => { await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await flush(); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await rm(output, { recursive: true, force: true }); } };
}

test("정책을 켜고 저장하면 잠기고, 비관리자는 안내만 본다", async () => {
  const saved = [];
  const view = await mount({ get: async () => ({ require_step_up: false }), set: async (value) => { saved.push(value); return { require_step_up: value }; } });
  try {
    await view.flush();
    assert.equal(buttonByText(view.container, "저장").disabled, true);
    const box = findElements(view.container, (n) => n.tagName === "INPUT")[0];
    await view.click(box);
    await view.click(buttonByText(view.container, "저장"));
    assert.deepEqual(saved, [true]);
    assert.ok(view.container.textContent.includes("사용 중(되돌릴 수 없음)"));
    assert.equal(findElements(view.container, (n) => n.tagName === "INPUT")[0].disabled, true);
  } finally { await view.close(); }
  const forbidden = await mount({ get: async () => { throw Object.assign(new Error("x"), { status: 403 }); }, set: async () => ({}) });
  try {
    await forbidden.flush();
    assert.ok(forbidden.container.textContent.includes("관리자만 내려받기 정책을 관리할 수 있습니다"));
  } finally { await forbidden.close(); }
});

test("BFF 클라이언트는 요청 모양과 응답을 검사한다", async () => {
  const requests = [];
  const fetchImpl = async (url, init) => { requests.push({ url, init }); return new Response(JSON.stringify({ data: { require_step_up: true }, meta: {} }), { status: 200 }); };
  assert.equal((await getExportPolicy({ fetchImpl })).require_step_up, true);
  await setExportPolicy(true, { fetchImpl });
  assert.deepEqual(JSON.parse(requests[1].init.body), { require_step_up: true });
  assert.equal(requests[1].init.credentials, "same-origin");
  await assert.rejects(() => getExportPolicy({ fetchImpl: async () => new Response("{}", { status: 403 }) }), (error) => error instanceof ExportPolicyError && error.status === 403);
});
