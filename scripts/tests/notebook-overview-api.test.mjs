import assert from "node:assert/strict";
import test from "node:test";

import { createBffProxy } from "../../apps/web/lib/bff-api-proxy.js";
import { getNotebookOverview, regenerateNotebookOverview, StudioV2Error } from "../../apps/web/lib/studio-v2-api.js";
import { createStudioV2Adapter } from "../../apps/web/lib/studio-v2-adapter.js";

// 노트북 개요·추천 질문(WO-N1 NB2-F2): BFF 경로 허용, 웹 API 클라이언트 응답 검사, 노트북 범위 어댑터.
const COOKIE = "__Host-daon_session=opaque-session";
const ORIGIN = "https://app.example.com";
const URL_PATH = `${ORIGIN}/bff/api/workspaces/workspace-1/notebooks/notebook-1/overview`;
const SEGMENTS = ["workspaces", "workspace-1", "notebooks", "notebook-1", "overview"];
const REGEN_SEGMENTS = [...SEGMENTS, "regenerate"];

const READY = {
  state: "ready",
  summary: "보험금은 3일 이내에 지급한다. [1] 면책 기간은 90일이다. [2]",
  questions: ["보험금은 언제 지급되나요?", "면책 기간은 얼마인가요?", "사고가 나면 무엇을 해야 하나요?"],
  citations: [{ label: "1", source_title: "약관.pdf", page: 1 }, { label: "2", source_title: "약관.pdf", page: null }],
  stale: false,
  generated_at: "2026-11-24T00:00:00+00:00",
  error_code: null,
};
const EMPTY = { state: "queued", summary: null, questions: [], citations: [], stale: false, generated_at: null, error_code: null };

function makeProxy(captured) {
  return createBffProxy({
    baseUrl: new URL("https://api.example.com"),
    publicOrigin: new URL(ORIGIN),
    fetchImpl: async (url, init) => {
      captured.push({ url: String(url), method: init.method });
      return Response.json({ data: EMPTY, meta: {} });
    },
  });
}

test("BFF는 개요 GET과 다시 만들기 POST만 정확한 경로로 전달하고 POST는 CSRF Referer를 요구한다", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const got = await proxy(new Request(URL_PATH, { headers: { Cookie: COOKIE } }), SEGMENTS);
  assert.equal(got.status, 200);
  assert.equal(captured.at(-1).url, "https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1/overview");
  const headers = { Cookie: COOKIE, Origin: ORIGIN, Referer: `${ORIGIN}/notebooks/notebook-1`, "Content-Type": "application/json" };
  const post = await proxy(new Request(`${URL_PATH}/regenerate`, { method: "POST", body: "{}", headers }), REGEN_SEGMENTS);
  assert.equal(post.status, 200);
  assert.equal(captured.at(-1).url, "https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1/overview/regenerate");
  assert.equal(captured.at(-1).method, "POST");
  const noReferer = await proxy(new Request(`${URL_PATH}/regenerate`, {
    method: "POST", body: "{}", headers: { Cookie: COOKIE, Origin: ORIGIN, "Content-Type": "application/json" },
  }), REGEN_SEGMENTS);
  assert.notEqual(noReferer.status, 200);
  const postOverview = await proxy(new Request(URL_PATH, { method: "POST", body: "{}", headers }), SEGMENTS);
  assert.equal(postOverview.status, 405);
  const getRegen = await proxy(new Request(`${URL_PATH}/regenerate`, { headers: { Cookie: COOKIE } }), REGEN_SEGMENTS);
  assert.equal(getRegen.status, 405);
  const query = await proxy(new Request(`${URL_PATH}?x=1`, { headers: { Cookie: COOKIE } }), SEGMENTS);
  assert.notEqual(query.status, 200);
  assert.equal(captured.length, 2);
});

function respond(data, status = 200) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    const ok = status < 300;
    return Response.json(ok ? { data, meta: { trace_id: "trace-1", workspace_id: "workspace-1" } } : { error: { code: data } }, { status });
  };
  return { calls, fetchImpl };
}

test("getNotebookOverview는 개요를 그대로 돌려준다(GET)", async () => {
  for (const data of [READY, EMPTY, { ...EMPTY, state: "none" }, { ...EMPTY, state: "working" },
    { ...EMPTY, state: "failed", error_code: "OVERVIEW_UNGROUNDED", stale: true }, { ...EMPTY, state: "blocked", error_code: "OVERVIEW_BLOCKED" },
    { ...READY, stale: true }]) {
    const { calls, fetchImpl } = respond(data);
    assert.deepEqual(await getNotebookOverview("workspace-1", { notebookId: "notebook-1", fetchImpl }), data);
    assert.equal(calls[0].url, "/bff/api/workspaces/workspace-1/notebooks/notebook-1/overview");
    assert.equal(calls[0].init.method, "GET");
  }
});

test("regenerateNotebookOverview는 POST .../overview/regenerate로 보내고 202 응답을 받는다", async () => {
  const { calls, fetchImpl } = respond(EMPTY, 202);
  assert.deepEqual(await regenerateNotebookOverview("workspace-1", { notebookId: "notebook-1", fetchImpl }), EMPTY);
  assert.equal(calls[0].url, "/bff/api/workspaces/workspace-1/notebooks/notebook-1/overview/regenerate");
  assert.equal(calls[0].init.method, "POST");
});

test("진행 중 다시 만들기는 409 OVERVIEW_IN_PROGRESS 오류로 전달된다", async () => {
  const { fetchImpl } = respond("OVERVIEW_IN_PROGRESS", 409);
  await assert.rejects(regenerateNotebookOverview("workspace-1", { notebookId: "notebook-1", fetchImpl }),
    (error) => error instanceof StudioV2Error && error.code === "OVERVIEW_IN_PROGRESS" && error.status === 409);
});

test("잘못된 노트북 ID는 보내기 전에 막는다", async () => {
  const { calls, fetchImpl } = respond(EMPTY);
  await assert.rejects(getNotebookOverview("workspace-1", { notebookId: "bad id", fetchImpl }), (error) => error.code === "STUDIO_INPUT_INVALID");
  assert.equal(calls.length, 0);
});

test("모양이 다른 개요 응답은 받지 않는다", async () => {
  const bad = [
    { ...READY, extra: 1 },
    { ...READY, state: "done" },
    { ...READY, questions: READY.questions.slice(0, 2) },
    { ...READY, questions: [...READY.questions, "넷?"] },
    { ...READY, summary: null },
    { ...READY, citations: [{ label: "1", source_title: "약관.pdf" }] },
    { ...READY, citations: [{ label: "1", source_title: "약관.pdf", page: "1" }] },
    { ...READY, stale: "no" },
    { ...EMPTY, questions: ["?"] },
    { ...EMPTY, state: "failed", error_code: "secret text" },
    { ...EMPTY, summary: "요약" },
    (({ error_code, ...rest }) => rest)(READY),
  ];
  for (const data of bad) {
    const { fetchImpl } = respond(data);
    await assert.rejects(getNotebookOverview("workspace-1", { notebookId: "notebook-1", fetchImpl }), (error) => error.code === "STUDIO_RESPONSE_INVALID");
  }
});

test("어댑터는 개요 조회·다시 만들기를 노트북 범위로 묶는다", async () => {
  const { calls, fetchImpl } = respond(READY);
  const adapter = createStudioV2Adapter("workspace-1", "notebook-1", { fetchImpl });
  assert.deepEqual(await adapter.getNotebookOverview(), READY);
  await adapter.regenerateNotebookOverview();
  assert.deepEqual(calls.map((call) => [call.init.method, call.url]), [
    ["GET", "/bff/api/workspaces/workspace-1/notebooks/notebook-1/overview"],
    ["POST", "/bff/api/workspaces/workspace-1/notebooks/notebook-1/overview/regenerate"],
  ]);
});

test("OpenAPI는 개요 GET·다시 만들기 POST와 정확한 응답 모양·오류 코드를 공개한다", async () => {
  const { readFile } = await import("node:fs/promises");
  const contract = JSON.parse(await readFile(new URL("../../packages/contracts/openapi/v1/openapi.json", import.meta.url), "utf8"));
  const get = contract.paths["/api/v1/workspaces/{id}/notebooks/{notebook_id}/overview"];
  const post = contract.paths["/api/v1/workspaces/{id}/notebooks/{notebook_id}/overview/regenerate"];
  assert.deepEqual(Object.keys(get), ["get"]);
  assert.deepEqual(Object.keys(post), ["post"]);
  assert.equal(get.get.responses["200"].content["application/json"].schema.$ref, "#/components/schemas/NotebookOverviewEnvelope");
  assert.equal(post.post.responses["202"].content["application/json"].schema.$ref, "#/components/schemas/NotebookOverviewEnvelope");
  assert.ok(post.post.responses["409"]);
  const overview = contract.components.schemas.NotebookOverview;
  assert.equal(overview.additionalProperties, false);
  assert.deepEqual(overview.required, ["state", "summary", "questions", "citations", "stale", "generated_at", "error_code"]);
  assert.deepEqual(overview.properties.state.enum, ["none", "queued", "working", "ready", "failed", "blocked"]);
  for (const code of ["OVERVIEW_IN_PROGRESS", "OVERVIEW_NO_READY_SOURCE", "OVERVIEW_UNAVAILABLE"]) {
    assert.ok(contract.components.schemas.SafeErrorCode.enum.includes(code), code);
  }
});
