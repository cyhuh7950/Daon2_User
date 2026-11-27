import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { createNativeBffProxy } from "../../apps/web/lib/bff-api-proxy.js";
import { createWindowsOnlineFeatures } from "../../apps/desktop/src/windows-online-features.js";
import { packNativeResponse } from "./support/native-notebook-response.mjs";
import { PUT, PATCH, DELETE } from "../../apps/web/app/api/v1/[...path]/route.js";

const baseUrl = new URL("http://api.internal");
const gateway = "https://daon2-user.sinsan.kr";
const scope = ["workspaces", "ws-one", "notebooks", "nb-one"];

test("native Studio v2 uses the same notebook routes, query and write headers", async () => {
  assert.equal(typeof PUT, "function");
  assert.equal(typeof PATCH, "function");
  assert.equal(typeof DELETE, "function");
  const calls = [];
  const proxy = createNativeBffProxy({ baseUrl, fetchImpl: async (url, init) => {
    calls.push([url.pathname, url.search, init.method, init.headers.get("if-match")]);
    return new Response("{}", { headers: { "content-type": "application/json", etag: '"next"' } });
  } });
  const request = (parts, { method = "GET", query = "", body } = {}) => proxy(
    new Request(`${gateway}/api/v1/${parts.join("/")}${query}`, {
      method, body, headers: { authorization: "Bearer test-credential-012345", "content-type": "application/json", "if-match": '"old"' },
    }), parts,
  );
  assert.equal((await request([...scope, "studio", "types"])).status, 200);
  assert.equal((await request([...scope, "studio", "outputs"], { query: "?limit=10" })).headers.get("etag"), '"next"');
  assert.equal((await request([...scope, "studio", "authoring", "sessions", "out-one", "review"], { method: "PUT", body: "{}" })).status, 200);
  assert.equal((await request([...scope, "studio", "outputs"], { query: "?limit=10&limit=11" })).status, 400);
  assert.equal((await request([...scope, "studio", "unsupported"])).status, 404);
  assert.deepEqual(calls, [
    ["/api/v1/workspaces/ws-one/notebooks/nb-one/studio/types", "", "GET", '"old"'],
    ["/api/v1/workspaces/ws-one/notebooks/nb-one/studio/outputs", "?limit=10", "GET", '"old"'],
    ["/api/v1/workspaces/ws-one/notebooks/nb-one/studio/authoring/sessions/out-one/review", "", "PUT", '"old"'],
  ]);
});

test("Windows accepts enriched answers and sends PDF and CSV together", async () => {
  const calls = [];
  const features = createWindowsOnlineFeatures("ws-one", "nb-one", async (command, args) => {
    calls.push([command, args]);
    if (args.request.path.includes("/citations/")) {
      return packNativeResponse("%PDF-1.4", { headers: [["content-type", "application/pdf"], ["x-citation-page", "1"]] });
    }
    return Array.from(new Uint8Array(packNativeResponse(JSON.stringify({ data: {
      run_id: "run-one", run_result_id: "result-one", answer: "답변", insufficient: false,
      citations: [], mode: "explicit_source_lookup", grounding: "source_backed",
      source_scope_summary: "선택한 Source 범위", mismatch: null, next_actions: [], process: null,
    }, meta: { workspace_id: "ws-one", trace_id: "trace-one" } }))));
  });
  const sources = ["pdf", "csv"].map((name) => ({ resourceKind: "source", resourceId: `source-${name}`, versionId: `version-${name}` }));
  const answer = await features.askQuestion({ question: "두 자료를 비교해 줘.", knowledgeContext: { mode: "raw_only", resources: sources } });
  assert.equal(answer.answer, "답변");
  assert.deepEqual(JSON.parse(calls[0][1].request.body).knowledge_context.resources.map((item) => item.resource_id), ["source-pdf", "source-csv"]);
  const pdf = await features.citationContent({ citation_id: "citation-one", locator: { kind: "page", value: "1" }, page: 1 });
  assert.equal(pdf.page, 1);
  assert.equal(calls[1][1].request.path, "/api/v1/workspaces/ws-one/citations/citation-one/content?notebook_id=nb-one");
});

test("Windows reader opens and validates the exact web manual assets", async () => {
  const media = {
    "manifest.json": "application/json", "daon-user-manual.md": "text/markdown; charset=utf-8",
    "daon-user-manual.pdf": "application/pdf",
    "daon-user-manual.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  };
  const features = createWindowsOnlineFeatures("ws-one", "nb-one", async (command, { asset }) => {
    assert.equal(command, "native_read_manual");
    assert.ok(Object.hasOwn(media, asset));
    const bytes = await readFile(new URL(`../../apps/web/public/manual/${asset}`, import.meta.url));
    return packNativeResponse(bytes, { headers: [["content-type", media[asset]]] });
  });
  const manifest = await features.getManualManifest();
  assert.equal(manifest.release_version, "2.0.0");
  const [{ document_id: id }] = manifest.documents;
  assert.match((await features.readManual(id, manifest)).text, /^# /);
  for (const format of ["pdf", "docx"]) {
    assert.equal((await features.downloadManual(id, format, manifest)).blob.size, manifest.documents[0].assets[format].bytes);
  }
});

test("Windows loads approved knowledge scopes and saves the current notebook selection", async () => {
  const calls = [];
  const item = { project_id: "project-one", work_package_id: "package-one" };
  const proxy = createNativeBffProxy({ baseUrl, fetchImpl: async (url, init) => {
    const body = init.body == null ? null : JSON.parse(new TextDecoder().decode(init.body));
    calls.push([init.method, url.pathname, body]);
    const data = url.pathname.endsWith("/daon-knowledge-scopes") ? { projects: [] } : { items: [item] };
    return new Response(JSON.stringify({ data }), { headers: { "content-type": "application/json" } });
  } });
  const features = createWindowsOnlineFeatures("ws-one", "nb-one", async (command, args) => {
    assert.equal(command, "native_notebook_request");
    assert.equal(args.notebookId, "nb-one");
    const { path, method, body } = args.request;
    const response = await proxy(new Request(gateway + path, {
      method, body, headers: { authorization: "Bearer test-credential-012345", "content-type": "application/json" },
    }), path.slice("/api/v1/".length).split("/"));
    return packNativeResponse(await response.text(), { status: response.status });
  });
  assert.deepEqual(await features.listDaonKnowledgeScopes(), { projects: [] });
  assert.deepEqual(await features.getNotebookKnowledgeScopes(), { items: [item] });
  assert.deepEqual(await features.saveNotebookKnowledgeScopes([item]), { items: [item] });
  assert.deepEqual(await features.getNotebookKnowledgeStatus(), { items: [item] });
  const path = "/api/v1/workspaces/ws-one/notebooks/nb-one/knowledge-scopes";
  const rejected = (url, method = "GET") => proxy(new Request(gateway + url, {
    method, headers: { authorization: "Bearer test-credential-012345" },
  }), url.split("?")[0].slice("/api/v1/".length).split("/"));
  assert.equal((await rejected(path + "/status", "PUT")).status, 405);
  assert.equal((await rejected(path + "?unexpected=1")).status, 400);
  assert.deepEqual(calls, [
    ["GET", "/api/v1/workspaces/ws-one/daon-knowledge-scopes", null],
    ["GET", path, null],
    ["PUT", path, { items: [item] }],
    ["GET", path + "/status", null],
  ]);
});
