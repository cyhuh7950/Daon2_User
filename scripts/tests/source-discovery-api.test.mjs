import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createBffProxy } from "../../apps/web/lib/bff-api-proxy.js";
import { addSourceDiscovery, searchSourceDiscovery, StudioV2Error } from "../../apps/web/lib/studio-v2-api.js";
import { createStudioV2Adapter } from "../../apps/web/lib/studio-v2-adapter.js";
import { validateOpenApiDocument } from "../verify-openapi-contract.mjs";

// 자료 찾기·빠른 찾기(WO-N1 NB4-F1, 결정 D-02 내부만): BFF 경로 허용, 웹 API 클라이언트 요청·응답 검사, 노트북 범위 어댑터, OpenAPI.
const COOKIE = "__Host-daon_session=opaque-session";
const ORIGIN = "https://app.example.com";
const BASE_SEGMENTS = ["workspaces", "workspace-1", "notebooks", "notebook-1", "source-discovery"];
const BASE_URL = `${ORIGIN}/bff/api/workspaces/workspace-1/notebooks/notebook-1/source-discovery`;
const UPSTREAM = "https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1/source-discovery";
const DOC_REF = { kind: "document", project_id: "p-bid", work_package_id: "wp-1", document_id: "doc-a", document_version: "v-a" };
const PKG_REF = { kind: "knowledge_package", project_id: "p-bid", work_package_id: "wp-1" };
const CANDIDATES = {
  candidates: [
    { candidate_id: "kp-1", kind: "knowledge_package", title: "입찰 / 제안서", origin_label: "승인 지식", reason: "업무 패키지 이름이 검색어와 일치합니다",
      preview: "입찰 / 제안서 · 승인 문서 3건", action: "add_scope", ref: PKG_REF },
    { candidate_id: "doc-1", kind: "document", title: "평가 기준서", origin_label: "문서 근거 · 제안서", reason: "2쪽 내용이 검색어와 관련 있습니다",
      preview: "평가 기준은 기술 70점", action: "add_source", ref: DOC_REF },
  ],
  unavailable: [{ scope: "knowledge", reason: "DISCOVERY_CONNECTOR_FAILED" }],
};

const writeHeaders = (extra = {}) => ({
  Cookie: COOKIE, Origin: ORIGIN, Referer: `${ORIGIN}/notebooks/notebook-1`, "Content-Type": "application/json", ...extra,
});

function fakeFetch(captured, data, status = 200) {
  return async (url, init) => {
    captured.push({ url: String(url), init });
    return status === 200 ? Response.json({ data, meta: { trace_id: "t" } })
      : Response.json({ error: { code: data, trace_id: "t" } }, { status });
  };
}

test("BFF는 찾기 search·add POST만 정확한 경로로 전달하고 쓰기 CSRF Referer를 요구한다", async () => {
  const captured = [];
  const proxy = createBffProxy({
    baseUrl: new URL("https://api.example.com"),
    publicOrigin: new URL(ORIGIN),
    fetchImpl: async (url, init) => {
      captured.push({ url: String(url), method: init.method, headers: new Headers(init.headers) });
      return Response.json({ data: CANDIDATES, meta: {} });
    },
  });
  const search = await proxy(new Request(`${BASE_URL}/search`, {
    method: "POST", body: JSON.stringify({ query: "제안서", scopes: ["documents"] }), headers: writeHeaders(),
  }), [...BASE_SEGMENTS, "search"]);
  assert.equal(search.status, 200);
  assert.equal(captured.at(-1).url, `${UPSTREAM}/search`);
  const add = await proxy(new Request(`${BASE_URL}/add`, {
    method: "POST", body: JSON.stringify({ ref: DOC_REF }), headers: writeHeaders({ "Idempotency-Key": "discovery-key-0001" }),
  }), [...BASE_SEGMENTS, "add"]);
  assert.equal(add.status, 200);
  assert.equal(captured.at(-1).url, `${UPSTREAM}/add`);
  assert.equal(captured.at(-1).headers.get("idempotency-key"), "discovery-key-0001");
  assert.equal(captured.length, 2);

  const rejected = [
    [new Request(`${BASE_URL}/search`, { headers: { Cookie: COOKIE } }), [...BASE_SEGMENTS, "search"], 405],
    [new Request(`${BASE_URL}/add`, { method: "PUT", body: "{}", headers: writeHeaders() }), [...BASE_SEGMENTS, "add"], 405],
    [new Request(`${BASE_URL}/search`, { method: "POST", body: "{}", headers: { Cookie: COOKIE, Origin: ORIGIN, "Content-Type": "application/json" } }),
      [...BASE_SEGMENTS, "search"], null],
    [new Request(`${BASE_URL}/search?x=1`, { method: "POST", body: "{}", headers: writeHeaders() }), [...BASE_SEGMENTS, "search"], null],
    [new Request(`${BASE_URL}/web`, { method: "POST", body: "{}", headers: writeHeaders() }), [...BASE_SEGMENTS, "web"], null],
    [new Request(BASE_URL, { method: "POST", body: "{}", headers: writeHeaders() }), BASE_SEGMENTS, null],
  ];
  for (const [request, segments, status] of rejected) {
    const response = await proxy(request, segments);
    if (status === null) assert.ok(response.status >= 400, `${request.method} ${request.url} → ${response.status}`);
    else assert.equal(response.status, status);
  }
  assert.equal(captured.length, 2);
});

test("searchSourceDiscovery는 검색어·범위를 확인해 보내고 응답 모양을 정확히 검사한다", async () => {
  const captured = [];
  const result = await searchSourceDiscovery("workspace-1", {
    notebookId: "notebook-1", query: "제안서 평가", scopes: ["knowledge", "documents"], fetchImpl: fakeFetch(captured, CANDIDATES),
  });
  assert.deepEqual(result, CANDIDATES);
  assert.equal(captured[0].url, "/bff/api/workspaces/workspace-1/notebooks/notebook-1/source-discovery/search");
  assert.equal(captured[0].init.method, "POST");
  assert.deepEqual(JSON.parse(captured[0].init.body), { query: "제안서 평가", scopes: ["knowledge", "documents"] });

  for (const [query, scopes] of [["", ["documents"]], ["   ", ["documents"]], ["가".repeat(501), ["documents"]], ["x", []], ["x", ["web"]],
    ["x", ["documents", "documents"]], [1, ["documents"]]]) {
    const calls = [];
    await assert.rejects(searchSourceDiscovery("workspace-1", { notebookId: "notebook-1", query, scopes, fetchImpl: fakeFetch(calls, CANDIDATES) }),
      (error) => error instanceof StudioV2Error && error.code === "STUDIO_INPUT_INVALID");
    assert.equal(calls.length, 0);
  }

  const bad = [
    { ...CANDIDATES, extra: 1 },
    { candidates: [{ ...CANDIDATES.candidates[0], action: "add_source" }], unavailable: [] },
    { candidates: [{ ...CANDIDATES.candidates[1], preview: "가".repeat(301) }], unavailable: [] },
    { candidates: [{ ...CANDIDATES.candidates[1], ref: { ...DOC_REF, url: "https://x" } }], unavailable: [] },
    { candidates: Array.from({ length: 21 }, (_, i) => ({ ...CANDIDATES.candidates[1], candidate_id: `doc-${i}` })), unavailable: [] },
    { candidates: [], unavailable: [{ scope: "web", reason: "X_Y" }] },
  ];
  for (const data of bad) {
    await assert.rejects(searchSourceDiscovery("workspace-1", { notebookId: "notebook-1", query: "x", scopes: ["documents"], fetchImpl: fakeFetch([], data) }),
      (error) => error instanceof StudioV2Error && error.code === "STUDIO_RESPONSE_INVALID");
  }
  await assert.rejects(searchSourceDiscovery("workspace-1", {
    notebookId: "notebook-1", query: "x", scopes: ["documents"], fetchImpl: fakeFetch([], "DISCOVERY_SCOPE_UNAVAILABLE", 422),
  }), (error) => error instanceof StudioV2Error && error.code === "DISCOVERY_SCOPE_UNAVAILABLE" && error.status === 422);
});

test("addSourceDiscovery는 ref를 Idempotency-Key와 함께 보내고 추가 결과를 돌려준다", async () => {
  const captured = [];
  const scope = await addSourceDiscovery("workspace-1", { notebookId: "notebook-1", ref: PKG_REF, fetchImpl: fakeFetch(captured, { added: "scope" }) });
  assert.deepEqual(scope, { added: "scope", sourceId: null });
  assert.equal(captured[0].url, "/bff/api/workspaces/workspace-1/notebooks/notebook-1/source-discovery/add");
  assert.deepEqual(JSON.parse(captured[0].init.body), { ref: PKG_REF });
  assert.match(captured[0].init.headers["Idempotency-Key"], /^studio-v2-/u);

  const source = await addSourceDiscovery("workspace-1", {
    notebookId: "notebook-1", ref: DOC_REF, idempotencyKey: "discovery-key-0001", fetchImpl: fakeFetch(captured, { added: "source", source_id: "src-1" }),
  });
  assert.deepEqual(source, { added: "source", sourceId: "src-1" });
  assert.equal(captured[1].init.headers["Idempotency-Key"], "discovery-key-0001");

  for (const ref of [{ kind: "web" }, { ...PKG_REF, extra: 1 }, { kind: "document", project_id: "p", work_package_id: "w" }, null]) {
    const calls = [];
    await assert.rejects(addSourceDiscovery("workspace-1", { notebookId: "notebook-1", ref, fetchImpl: fakeFetch(calls, { added: "scope" }) }),
      (error) => error instanceof StudioV2Error && error.code === "STUDIO_INPUT_INVALID");
    assert.equal(calls.length, 0);
  }
  for (const data of [{ added: "scope", source_id: "src-1" }, { added: "source" }, { added: "web" }]) {
    await assert.rejects(addSourceDiscovery("workspace-1", { notebookId: "notebook-1", ref: DOC_REF, fetchImpl: fakeFetch([], data) }),
      (error) => error instanceof StudioV2Error && error.code === "STUDIO_RESPONSE_INVALID");
  }
  await assert.rejects(addSourceDiscovery("workspace-1", {
    notebookId: "notebook-1", ref: DOC_REF, fetchImpl: fakeFetch([], "DISCOVERY_DOCUMENT_TOO_LARGE", 413),
  }), (error) => error.code === "DISCOVERY_DOCUMENT_TOO_LARGE" && error.status === 413);
});

test("어댑터는 노트북 범위로 찾기·추가를 부른다", async () => {
  const captured = [];
  const adapter = createStudioV2Adapter("workspace-1", "notebook-1", { fetchImpl: fakeFetch(captured, CANDIDATES) });
  await adapter.searchSourceDiscovery("제안서", ["documents"]);
  assert.equal(captured[0].url, "/bff/api/workspaces/workspace-1/notebooks/notebook-1/source-discovery/search");
  const adding = createStudioV2Adapter("workspace-1", "notebook-1", { fetchImpl: fakeFetch(captured, { added: "scope" }) });
  assert.deepEqual(await adding.addSourceDiscovery(PKG_REF), { added: "scope", sourceId: null });
  assert.equal(captured[1].url, "/bff/api/workspaces/workspace-1/notebooks/notebook-1/source-discovery/add");
});

test("OpenAPI 계약에 찾기 두 경로가 있고 검사기를 통과한다", () => {
  const document = JSON.parse(readFileSync(new URL("../../packages/contracts/openapi/v1/openapi.json", import.meta.url), "utf8"));
  for (const suffix of ["search", "add"]) {
    const operation = document.paths[`/api/v1/workspaces/{id}/notebooks/{notebook_id}/source-discovery/${suffix}`]?.post;
    assert.ok(operation, suffix);
    assert.equal(operation["x-implementation-owner"], "WO-N1-NB4-F1");
  }
  validateOpenApiDocument(document);
});
