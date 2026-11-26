import assert from "node:assert/strict";
import test from "node:test";

test('S42 context BFF는 단일 정확 선택만 전달하고 중복·동시·빈 선택은 upstream 전에 거부한다', async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const segments = ['workspaces','workspace-1','notebooks','notebook-1','context'];
  const base = `${ORIGIN}/bff/api/workspaces/workspace-1/notebooks/notebook-1/context`;
  for (const query of ['run_id=run-1', 'studio_job_id=job-1']) {
    const response = await proxy(new Request(`${base}?${query}`, { headers:{ Cookie:COOKIE } }), segments);
    assert.equal(response.status, 200);
    assert.equal(captured.at(-1).url, `https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1/context?${query}`);
  }
  for (const query of ['run_id=a&run_id=b','studio_job_id=a&studio_job_id=b',
    'run_id=a&studio_job_id=b','run_id=','studio_job_id=','run_id=a&extra=b','run_id=a%0A']) {
    const response = await proxy(new Request(`${base}?${query}`, { headers:{ Cookie:COOKIE } }), segments);
    assert.equal(response.status, 400, query);
    assert.equal((await response.json()).error.code, 'INVALID_REQUEST', query);
  }
  assert.equal(captured.length, 2);
});

import { createBffProxy, createNativeBffProxy } from "../../apps/web/lib/bff-api-proxy.js";

const COOKIE = "__Host-daon_session=opaque-session";
const ORIGIN = "https://app.example.com";

test("Windows Notebook BFF는 Bearer로 정확한 조회 세 경로만 전달한다", async () => {
  const calls = [];
  const token = "Bearer native-notebook-fixture-credential";
  const proxy = createNativeBffProxy({
    baseUrl: new URL("https://api.example.com"),
    publicOrigin: new URL(ORIGIN),
    fetchImpl: async (url, init) => {
      calls.push([url.pathname, init.method, init.headers.get("authorization"), init.headers.get("cookie")]);
      return Response.json({ data: {}, meta: {} });
    },
  });
  const get = (parts, { headers = { Authorization: token }, method = "GET", query = "" } = {}) =>
    proxy(new Request(`${ORIGIN}/api/v1/${parts.join("/")}${query}`, { headers, method }), parts);
  const collection = ["workspaces", "workspace-1", "notebooks"];
  const paths = [collection, [...collection, "notebook-1"], [...collection, "notebook-1", "context"]];
  for (const path of paths) assert.equal((await get(path)).status, 200);
  assert.deepEqual(calls, paths.map((parts) => [`/api/v1/${parts.join("/")}`, "GET", token, null]));
  assert.equal((await get(collection, { headers: {} })).status, 401);
  assert.equal((await get(collection, { headers: { Cookie: COOKIE } })).status, 400);
  assert.equal((await get(collection, { method: "POST" })).status, 405);
  assert.equal((await get(paths[2], { query: "?notebook_id=other" })).status, 404);
  assert.equal((await get([...paths[2], "extra"])).status, 404);
  assert.equal(calls.length, 3);
});

function makeProxy(captured) {
  return createBffProxy({
    baseUrl: new URL("https://api.example.com"),
    publicOrigin: new URL(ORIGIN),
    fetchImpl: async (url, init) => {
      captured.push({
        url: String(url), method: init.method,
        idempotency: init.headers.get("idempotency-key"),
        ifMatch: init.headers.get("if-match"),
      });
      return Response.json({ data: [], meta: {} });
    },
  });
}

test("Notebook BFF는 collection/item exact method를 same-origin server route로 전달한다", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const list = await proxy(new Request(`${ORIGIN}/bff/api/workspaces/workspace-1/notebooks`, { headers: { Cookie: COOKIE } }), ["workspaces", "workspace-1", "notebooks"]);
  const create = await proxy(new Request(`${ORIGIN}/bff/api/workspaces/workspace-1/notebooks`, {
    method: "POST", headers: { Cookie: COOKIE, Origin: ORIGIN, "Content-Type": "application/json", "Idempotency-Key": "notebook-create-0001" }, body: '{"title":"Notebook"}',
  }), ["workspaces", "workspace-1", "notebooks"]);
  const get = await proxy(new Request(`${ORIGIN}/bff/api/workspaces/workspace-1/notebooks/notebook-1`, { headers: { Cookie: COOKIE } }), ["workspaces", "workspace-1", "notebooks", "notebook-1"]);
  const update = await proxy(new Request(`${ORIGIN}/bff/api/workspaces/workspace-1/notebooks/notebook-1`, {
    method: "PATCH", headers: { Cookie: COOKIE, Origin: ORIGIN, "Content-Type": "application/json", "Idempotency-Key": "notebook-update-0001", "If-Match": '"notebook:1"' }, body: '{"title":"Renamed"}',
  }), ["workspaces", "workspace-1", "notebooks", "notebook-1"]);
  const context = await proxy(new Request(`${ORIGIN}/bff/api/workspaces/workspace-1/notebooks/notebook-1/context`, {
    headers: { Cookie: COOKIE },
  }), ["workspaces", "workspace-1", "notebooks", "notebook-1", "context"]);

  assert.deepEqual([list.status, create.status, get.status, update.status, context.status], [200, 200, 200, 200, 200]);
  assert.deepEqual(captured, [
    { url: "https://api.example.com/api/v1/workspaces/workspace-1/notebooks", method: "GET", idempotency: null, ifMatch: null },
    { url: "https://api.example.com/api/v1/workspaces/workspace-1/notebooks", method: "POST", idempotency: "notebook-create-0001", ifMatch: null },
    { url: "https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1", method: "GET", idempotency: null, ifMatch: null },
    { url: "https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1", method: "PATCH", idempotency: "notebook-update-0001", ifMatch: '"notebook:1"' },
    { url: "https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1/context", method: "GET", idempotency: null, ifMatch: null },
  ]);
});

test("Notebook BFF는 Notebook 삭제를 전달하고 cross-origin write만 upstream 전에 차단한다", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const deleted = await proxy(new Request(`${ORIGIN}/bff/api/workspaces/workspace-1/notebooks/notebook-1`, { method: "DELETE", headers: { Cookie: COOKIE, Origin: ORIGIN } }), ["workspaces", "workspace-1", "notebooks", "notebook-1"]);
  const crossOrigin = await proxy(new Request(`${ORIGIN}/bff/api/workspaces/workspace-1/notebooks`, { method: "POST", headers: { Cookie: COOKIE, Origin: "https://evil.example", "Content-Type": "application/json", "Idempotency-Key": "notebook-create-0002" }, body: "{}" }), ["workspaces", "workspace-1", "notebooks"]);
  assert.deepEqual([deleted.status, crossOrigin.status], [200, 403]);
  assert.deepEqual(captured.map(({ url, method }) => ({ url, method })), [
    { url: "https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1", method: "DELETE" },
  ]);
});

test("Connector Source BFF는 목록·등록·재연결·해제·Source 목록을 API 계약으로 전달한다", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const requests = [
    ["GET", ["workspaces", "workspace-1", "connectors"]],
    ["POST", ["workspaces", "workspace-1", "connectors"]],
    ["POST", ["workspaces", "workspace-1", "connectors", "mcp-open-law-go-kr", "reconnect"]],
    ["POST", ["workspaces", "workspace-1", "connectors", "mcp-open-law-go-kr", "disconnect"]],
    ["GET", ["workspaces", "workspace-1", "connectors", "mcp-open-law-go-kr", "sources"]],
  ];
  const responses = [];
  for (const [method, path] of requests) {
    const response = await proxy(new Request(`${ORIGIN}/bff/api/${path.join("/")}`, {
      method,
      headers: method === "POST"
        ? { Cookie: COOKIE, Origin: ORIGIN, "Content-Type": "application/json", "Idempotency-Key": `connector-${responses.length + 1}` }
        : { Cookie: COOKIE },
      body: method === "POST" ? "{}" : undefined,
    }), path);
    responses.push(response.status);
  }
  assert.deepEqual(responses, [200, 200, 200, 200, 200]);
  assert.deepEqual(captured.map(({ url, method }) => ({ url, method })), [
    { url: "https://api.example.com/api/v1/workspaces/workspace-1/connectors", method: "GET" },
    { url: "https://api.example.com/api/v1/workspaces/workspace-1/connectors", method: "POST" },
    { url: "https://api.example.com/api/v1/workspaces/workspace-1/connectors/mcp-open-law-go-kr/reconnect", method: "POST" },
    { url: "https://api.example.com/api/v1/workspaces/workspace-1/connectors/mcp-open-law-go-kr/disconnect", method: "POST" },
    { url: "https://api.example.com/api/v1/workspaces/workspace-1/connectors/mcp-open-law-go-kr/sources", method: "GET" },
  ]);
});
