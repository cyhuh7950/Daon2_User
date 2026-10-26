import assert from "node:assert/strict";
import test from "node:test";

import { createBffProxy } from "../../apps/web/lib/bff-api-proxy.js";

const COOKIE = "__Host-daon_session=opaque-session";
const ORIGIN = "https://app.example.com";
const BASE = ["workspaces", "workspace-1", "notebooks", "notebook-1", "studio"];
const URL_BASE = `${ORIGIN}/bff/api/workspaces/workspace-1/notebooks/notebook-1/studio`;

function makeProxy(captured, response = () => Response.json({ data: {}, meta: {} })) {
  return createBffProxy({
    baseUrl: new URL("https://api.example.com"),
    publicOrigin: new URL(ORIGIN),
    fetchImpl: async (url, init) => {
      captured.push({ url: String(url), method: init.method, headers: init.headers, body: init.body });
      return response();
    },
  });
}

const get = (path, query = "") => new Request(`${URL_BASE}${path}${query}`, { headers: { Cookie: COOKIE } });
const write = (method, path, body = "{}") => new Request(`${URL_BASE}${path}`, {
  method, body,
  headers: { Cookie: COOKIE, Origin: ORIGIN, Referer: `${ORIGIN}/notebooks/notebook-1`, "Content-Type": "application/json", "Idempotency-Key": "studio-v2-key-000001" },
});
const seg = (...rest) => [...BASE, ...rest];

test("Studio v2 읽기 경로는 정확한 세그먼트로만 전달된다", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const cases = [
    [get("/types"), seg("types"), "/types"],
    [get("/outputs", "?limit=10&cursor=abc"), seg("outputs"), "/outputs?limit=10&cursor=abc"],
    [get("/outputs/sv2-1", "?revision=2"), seg("outputs", "sv2-1"), "/outputs/sv2-1?revision=2"],
    [get("/outputs/sv2-1/provenance"), seg("outputs", "sv2-1", "provenance"), "/outputs/sv2-1/provenance"],
    [get("/outputs/sv2-1/learning-attempts"), seg("outputs", "sv2-1", "learning-attempts"), "/outputs/sv2-1/learning-attempts"],
    [get("/customization"), seg("customization"), "/customization"],
    [get("/outputs/sv2-1/exports/docx"), seg("outputs", "sv2-1", "exports", "docx"), "/outputs/sv2-1/exports/docx"],
    [get("/outputs/sv2-1/audio"), seg("outputs", "sv2-1", "audio"), "/outputs/sv2-1/audio"],
    [get("/outputs/sv2-1/video"), seg("outputs", "sv2-1", "video"), "/outputs/sv2-1/video"],
    [get("/outputs/sv2-1/exports/vtt"), seg("outputs", "sv2-1", "exports", "vtt"), "/outputs/sv2-1/exports/vtt"],
    [get("/outputs/sv2-1/evidence/ref-1/content", "?revision=1"), seg("outputs", "sv2-1", "evidence", "ref-1", "content"), "/outputs/sv2-1/evidence/ref-1/content?revision=1"],
  ];
  for (const [request, segments, suffix] of cases) {
    const response = await proxy(request, segments);
    assert.equal(response.status, 200, suffix);
    assert.equal(captured.at(-1).url, `https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1/studio${suffix}`);
  }
});

test("Studio v2 쓰기 경로는 Idempotency-Key·If-Match를 전달하고 CSRF Referer를 요구한다", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const create = await proxy(write("POST", "/outputs", '{"type_id":"report"}'), seg("outputs"));
  assert.equal(create.status, 200);
  assert.equal(captured.at(-1).method, "POST");
  assert.equal(captured.at(-1).headers.get("idempotency-key"), "studio-v2-key-000001");
  assert.equal(captured.at(-1).headers.get("x-daon-csrf-referer"), `${ORIGIN}/notebooks/notebook-1`);
  for (const [method, path, segments] of [
    ["PATCH", "/outputs/sv2-1", seg("outputs", "sv2-1")], ["DELETE", "/outputs/sv2-1", seg("outputs", "sv2-1")],
    ["POST", "/outputs/sv2-1/revisions", seg("outputs", "sv2-1", "revisions")],
    ["POST", "/outputs/sv2-1/regenerate", seg("outputs", "sv2-1", "regenerate")],
    ["POST", "/outputs/sv2-1/cancel", seg("outputs", "sv2-1", "cancel")],
    ["POST", "/outputs/sv2-1/learning-attempts", seg("outputs", "sv2-1", "learning-attempts")],
    ["PUT", "/customization", seg("customization")], ["POST", "/memos", seg("memos")],
  ]) {
    const response = await proxy(write(method, path), segments);
    assert.equal(response.status, 200, `${method} ${path}`);
  }
  const noReferer = await proxy(new Request(`${URL_BASE}/outputs`, {
    method: "POST", body: "{}", headers: { Cookie: COOKIE, Origin: ORIGIN, "Content-Type": "application/json", "Idempotency-Key": "studio-v2-key-000001" },
  }), seg("outputs"));
  assert.equal(noReferer.status, 403);
});

test("Studio v2는 허용하지 않는 메서드·쿼리·형식을 upstream 전에 거부한다", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  assert.equal((await proxy(write("DELETE", "/types"), seg("types"))).status, 405);
  assert.equal((await proxy(write("PUT", "/outputs"), seg("outputs"))).status, 405);
  assert.equal((await proxy(get("/outputs", "?evil=1"), seg("outputs"))).status, 400);
  assert.equal((await proxy(get("/outputs", "?limit=1&limit=2"), seg("outputs"))).status, 400);
  assert.equal((await proxy(get("/outputs/sv2-1", "?workspace_id=x"), seg("outputs", "sv2-1"))).status, 400);
  assert.equal((await proxy(get("/outputs/sv2-1/exports/exe"), seg("outputs", "sv2-1", "exports", "exe"))).status, 404);
  assert.equal((await proxy(get("/unknown"), seg("unknown"))).status, 404);
  assert.equal((await proxy(get("/outputs/bad%20id"), seg("outputs", "bad id"))).status, 404);
  assert.equal(captured.length, 0);
});

test("Studio v2 내보내기는 32 MiB 응답 상한과 첨부 헤더를 유지한다", async () => {
  const captured = [];
  const small = makeProxy(captured, () => new Response(new Uint8Array(1024), {
    headers: { "Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="a.pdf"', ETag: '"sha256:x"' },
  }));
  const ok = await small(get("/outputs/sv2-1/exports/pdf"), seg("outputs", "sv2-1", "exports", "pdf"));
  assert.equal(ok.status, 200);
  assert.equal(ok.headers.get("content-disposition"), 'attachment; filename="a.pdf"');
  assert.equal(ok.headers.get("cache-control"), "no-store");
  const big = makeProxy(captured, () => new Response("x", { headers: { "Content-Length": String(40 * 1024 * 1024) } }));
  const rejected = await big(get("/outputs/sv2-1/exports/pdf"), seg("outputs", "sv2-1", "exports", "pdf"));
  assert.equal(rejected.status, 502);
});

test("작성(Authoring)과 지식 Connector 경로는 정확한 세그먼트·메서드만 전달한다", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const ok = [
    [get("/authoring/templates"), seg("authoring", "templates"), "/authoring/templates"],
    [write("POST", "/authoring/sessions"), seg("authoring", "sessions"), "/authoring/sessions"],
    [get("/authoring/sessions/sv2-1"), seg("authoring", "sessions", "sv2-1"), "/authoring/sessions/sv2-1"],
    [write("POST", "/authoring/sessions/sv2-1/answers"), seg("authoring", "sessions", "sv2-1", "answers"), "/authoring/sessions/sv2-1/answers"],
    [write("PUT", "/authoring/sessions/sv2-1/review"), seg("authoring", "sessions", "sv2-1", "review"), "/authoring/sessions/sv2-1/review"],
  ];
  for (const [request, segments, suffix] of ok) {
    const response = await proxy(request, segments);
    assert.equal(response.status, 200, suffix);
    assert.ok(captured.at(-1).url.endsWith(`/studio${suffix}`), suffix);
  }
  assert.equal((await proxy(write("DELETE", "/authoring/sessions/sv2-1"), seg("authoring", "sessions", "sv2-1"))).status, 405);
  assert.equal((await proxy(get("/authoring/unknown"), seg("authoring", "unknown"))).status, 404);
  const count = captured.length;
  const connectors = [
    [new Request(`${ORIGIN}/bff/api/knowledge-connectors`, { headers: { Cookie: COOKIE } }), ["knowledge-connectors"], "/api/v1/knowledge-connectors"],
    [new Request(`${ORIGIN}/bff/api/admin/knowledge-connectors`, { method: "POST", body: "{}", headers: { Cookie: COOKIE, Origin: ORIGIN, Referer: `${ORIGIN}/settings`, "Content-Type": "application/json", "Idempotency-Key": "connector-key-000001" } }),
      ["admin", "knowledge-connectors"], "/api/v1/admin/knowledge-connectors"],
    [new Request(`${ORIGIN}/bff/api/admin/knowledge-connectors/kc-1/verify`, { method: "POST", body: "{}", headers: { Cookie: COOKIE, Origin: ORIGIN, Referer: `${ORIGIN}/settings`, "Content-Type": "application/json" } }),
      ["admin", "knowledge-connectors", "kc-1", "verify"], "/api/v1/admin/knowledge-connectors/kc-1/verify"],
  ];
  for (const [request, segments, path] of connectors) {
    const response = await proxy(request, segments);
    assert.equal(response.status, 200, path);
    assert.equal(captured.at(-1).url, `https://api.example.com${path}`);
  }
  assert.equal(captured.length, count + 3);
  assert.equal((await proxy(new Request(`${ORIGIN}/bff/api/knowledge-connectors`, { method: "DELETE", headers: { Cookie: COOKIE, Origin: ORIGIN, Referer: ORIGIN } }), ["knowledge-connectors"])).status, 405);
});

const ADMIN_ORIGIN = `${ORIGIN}/bff/api`;
const writeAt = (method, url, body = "{}", extra = {}) => new Request(url, {
  method, body, headers: { Cookie: COOKIE, Origin: ORIGIN, Referer: `${ORIGIN}/notebooks/notebook-1`, "Content-Type": "application/json", "Idempotency-Key": "studio-v2-key-000001", ...extra },
});

test("TTS 엔진 관리 경로는 정확한 메서드와 경로만 전달되고 그 밖은 거부된다(WO-F7T)", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const eid = `te-${"a".repeat(32)}`;
  const base = "https://api.example.com/api/v1/admin/tts-engines";
  const cases = [
    [new Request(`${ORIGIN}/bff/api/admin/tts-engines`, { headers: { Cookie: COOKIE } }), ["admin", "tts-engines"], base, "GET"],
    [writeAt("POST", `${ADMIN_ORIGIN}/admin/tts-engines`, "{}", { "Idempotency-Key": "tts-engine-key-000001" }), ["admin", "tts-engines"], base, "POST"],
    [writeAt("PATCH", `${ADMIN_ORIGIN}/admin/tts-engines/${eid}`, "{}", { "If-Match": `"tts-engine:${eid}:1"` }), ["admin", "tts-engines", eid], `${base}/${eid}`, "PATCH"],
    [writeAt("DELETE", `${ADMIN_ORIGIN}/admin/tts-engines/${eid}`, null), ["admin", "tts-engines", eid], `${base}/${eid}`, "DELETE"],
    [writeAt("POST", `${ADMIN_ORIGIN}/admin/tts-engines/${eid}/verify`), ["admin", "tts-engines", eid, "verify"], `${base}/${eid}/verify`, "POST"],
  ];
  for (const [request, segments, url, method] of cases) {
    const response = await proxy(request, segments);
    assert.ok([200, 204].includes(response.status), `${method} ${url} -> ${response.status}`);
    assert.equal(captured.at(-1).url, url);
    assert.equal(captured.at(-1).init?.method ?? method, method);
  }
  const count = captured.length;
  assert.equal((await proxy(writeAt("PUT", `${ADMIN_ORIGIN}/admin/tts-engines/${eid}`), ["admin", "tts-engines", eid])).status, 405);
  assert.equal((await proxy(writeAt("DELETE", `${ADMIN_ORIGIN}/admin/tts-engines`, null), ["admin", "tts-engines"])).status, 405);
  assert.equal((await proxy(writeAt("GET", `${ADMIN_ORIGIN}/admin/tts-engines/${eid}/verify`, null), ["admin", "tts-engines", eid, "verify"])).status, 405);
  assert.equal((await proxy(writeAt("POST", `${ADMIN_ORIGIN}/admin/tts-engines/${eid}/other`), ["admin", "tts-engines", eid, "other"])).status, 404);
  assert.equal((await proxy(writeAt("POST", `${ADMIN_ORIGIN}/admin/tts-engines/bad%2Fid/verify`), ["admin", "tts-engines", "bad/id", "verify"])).status, 404);
  assert.equal(captured.length, count);           // 거부된 요청은 API까지 가지 않는다
});

test("노트북 복사·채팅 기록 삭제·조직 템플릿·내보내기 정책 경로는 정확한 메서드와 경로만 전달된다", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const nb = ["workspaces", "workspace-1", "notebooks", "notebook-1"];
  const api = "https://api.example.com/api/v1";
  const cases = [
    [writeAt("POST", `${ADMIN_ORIGIN}/workspaces/workspace-1/notebooks/notebook-1/copies`), [...nb, "copies"], `${api}/workspaces/workspace-1/notebooks/notebook-1/copies`, "POST"],
    [writeAt("DELETE", `${ADMIN_ORIGIN}/workspaces/workspace-1/notebooks/notebook-1/chat-history`), [...nb, "chat-history"], `${api}/workspaces/workspace-1/notebooks/notebook-1/chat-history`, "DELETE"],
    [new Request(`${ADMIN_ORIGIN}/workspaces/workspace-1/notebooks/notebook-1/chat-history`, { headers: { Cookie: COOKIE } }), [...nb, "chat-history"], `${api}/workspaces/workspace-1/notebooks/notebook-1/chat-history`, "GET"],
    [new Request(`${ADMIN_ORIGIN}/admin/authoring-templates`, { headers: { Cookie: COOKIE } }), ["admin", "authoring-templates"], `${api}/admin/authoring-templates`, "GET"],
    [writeAt("PUT", `${ADMIN_ORIGIN}/admin/authoring-templates/org_a`, "{}", { "If-Match": '"authoring-template:org_a:1"' }), ["admin", "authoring-templates", "org_a"], `${api}/admin/authoring-templates/org_a`, "PUT"],
    [writeAt("POST", `${ADMIN_ORIGIN}/admin/authoring-templates/org_a/disable`), ["admin", "authoring-templates", "org_a", "disable"], `${api}/admin/authoring-templates/org_a/disable`, "POST"],
    [new Request(`${ADMIN_ORIGIN}/admin/export-policy`, { headers: { Cookie: COOKIE } }), ["admin", "export-policy"], `${api}/admin/export-policy`, "GET"],
    [writeAt("PUT", `${ADMIN_ORIGIN}/admin/export-policy`, '{"require_step_up":true}'), ["admin", "export-policy"], `${api}/admin/export-policy`, "PUT"],
  ];
  for (const [request, segments, url, method] of cases) {
    const response = await proxy(request, segments);
    assert.equal(response.status, 200, `${method} ${url}`);
    assert.equal(captured.at(-1).url, url);
    assert.equal(captured.at(-1).method, method);
  }
  for (const [method, segments] of [["GET", [...nb, "copies"]], ["POST", [...nb, "chat-history"]], ["DELETE", ["admin", "export-policy"]], ["PATCH", ["admin", "authoring-templates", "org_a"]]]) {
    const url = `${ADMIN_ORIGIN}/${segments.join("/")}`;
    const response = await proxy(method === "GET" ? new Request(url, { headers: { Cookie: COOKIE } }) : writeAt(method, url), segments);
    assert.equal(response.status, 405, `${method} ${url}`);
  }
});
