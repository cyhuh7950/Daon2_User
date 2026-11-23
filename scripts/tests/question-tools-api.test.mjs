import assert from "node:assert/strict";
import test from "node:test";

import { createBffProxy } from "../../apps/web/lib/bff-api-proxy.js";
import { getQuestionTools, saveQuestionTools, StudioV2Error } from "../../apps/web/lib/studio-v2-api.js";

// 질문 도구 켜고 끄기(WO-N1 NB2-F1): BFF 경로 허용과 웹 API 클라이언트의 응답 검사.
const COOKIE = "__Host-daon_session=opaque-session";
const ORIGIN = "https://app.example.com";
const URL_PATH = `${ORIGIN}/bff/api/workspaces/workspace-1/notebooks/notebook-1/question-tools`;
const SEGMENTS = ["workspaces", "workspace-1", "notebooks", "notebook-1", "question-tools"];

const TOOLS = [
  { id: "approved_knowledge", kind: "approved_knowledge", label: "승인 지식", available: true, enabled: true },
  { id: "connector:kc-rag", kind: "connector", connector_kind: "daon2_rag", label: "Daon2-RAG", available: true, enabled: false },
  { id: "connector:kc-law", kind: "connector", connector_kind: "law", label: "법령", available: false, enabled: false, reason: "CONNECTOR_NOT_READY" },
];

function makeProxy(captured) {
  return createBffProxy({
    baseUrl: new URL("https://api.example.com"),
    publicOrigin: new URL(ORIGIN),
    fetchImpl: async (url, init) => {
      captured.push({ url: String(url), method: init.method, body: init.body });
      return Response.json({ data: { tools: [] }, meta: {} });
    },
  });
}

test("BFF는 질문 도구 GET·PUT만 정확한 경로로 전달하고 PUT은 CSRF Referer를 요구한다", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const got = await proxy(new Request(URL_PATH, { headers: { Cookie: COOKIE } }), SEGMENTS);
  assert.equal(got.status, 200);
  assert.equal(captured.at(-1).url, "https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1/question-tools");
  const put = await proxy(new Request(URL_PATH, {
    method: "PUT", body: '{"enabled":{"approved_knowledge":false}}',
    headers: { Cookie: COOKIE, Origin: ORIGIN, Referer: `${ORIGIN}/notebooks/notebook-1`, "Content-Type": "application/json" },
  }), SEGMENTS);
  assert.equal(put.status, 200);
  assert.equal(captured.at(-1).method, "PUT");
  const noReferer = await proxy(new Request(URL_PATH, {
    method: "PUT", body: "{}", headers: { Cookie: COOKIE, Origin: ORIGIN, "Content-Type": "application/json" },
  }), SEGMENTS);
  assert.notEqual(noReferer.status, 200);
  const post = await proxy(new Request(URL_PATH, {
    method: "POST", body: "{}", headers: { Cookie: COOKIE, Origin: ORIGIN, Referer: `${ORIGIN}/notebooks/notebook-1`, "Content-Type": "application/json" },
  }), SEGMENTS);
  assert.equal(post.status, 405);
  const query = await proxy(new Request(`${URL_PATH}?x=1`, { headers: { Cookie: COOKIE } }), SEGMENTS);
  assert.notEqual(query.status, 200);
  assert.equal(captured.length, 2);
});

function respond(data, status = 200) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return Response.json(status === 200 ? { data, meta: { trace_id: "trace-1", workspace_id: "workspace-1" } } : { error: { code: data } }, { status });
  };
  return { calls, fetchImpl };
}

test("getQuestionTools는 도구 목록을 그대로 돌려준다", async () => {
  const { calls, fetchImpl } = respond({ tools: TOOLS });
  const data = await getQuestionTools("workspace-1", { notebookId: "notebook-1", fetchImpl });
  assert.deepEqual(data, { tools: TOOLS });
  assert.equal(calls[0].url, "/bff/api/workspaces/workspace-1/notebooks/notebook-1/question-tools");
  assert.equal(calls[0].init.method, "GET");
});

test("saveQuestionTools는 바꾼 도구만 {enabled}로 보낸다", async () => {
  const { calls, fetchImpl } = respond({ tools: TOOLS });
  await saveQuestionTools("workspace-1", { notebookId: "notebook-1", enabled: { "connector:kc-rag": false }, fetchImpl });
  assert.equal(calls[0].init.method, "PUT");
  assert.deepEqual(JSON.parse(calls[0].init.body), { enabled: { "connector:kc-rag": false } });
});

test("saveQuestionTools는 참·거짓이 아닌 값과 웹 도구를 보내기 전에 막는다", async () => {
  const { calls, fetchImpl } = respond({ tools: TOOLS });
  for (const enabled of [{ approved_knowledge: 1 }, null, [], { "bad id": true }]) {
    await assert.rejects(saveQuestionTools("workspace-1", { notebookId: "notebook-1", enabled, fetchImpl }), (error) => error instanceof StudioV2Error && error.code === "STUDIO_INPUT_INVALID");
  }
  assert.equal(calls.length, 0);
});

test("모양이 다른 응답은 받지 않는다", async () => {
  const bad = [
    { tools: [{ ...TOOLS[0], extra: 1 }] },
    { tools: [{ ...TOOLS[0], kind: "web" }] },
    { tools: [{ ...TOOLS[0], enabled: "yes" }] },
    { tools: [{ ...TOOLS[2], reason: "SOMETHING_ELSE" }] },
    { tools: [{ ...TOOLS[1], connector_kind: "web" }] },
    { tools: [{ ...TOOLS[0], connector_kind: "daon2_rag" }] },
    { tools: [{ ...TOOLS[0], available: true, enabled: true, reason: "NO_SCOPE_SELECTED" }] },
    { tools: [{ ...TOOLS[2], enabled: true }] },
    { tools: TOOLS, extra: true },
  ];
  for (const data of bad) {
    const { fetchImpl } = respond(data);
    await assert.rejects(getQuestionTools("workspace-1", { notebookId: "notebook-1", fetchImpl }), (error) => error.code === "STUDIO_RESPONSE_INVALID");
  }
});

test("서버 오류 코드는 그대로 전달된다", async () => {
  const { fetchImpl } = respond("QUESTION_TOOL_UNKNOWN", 422);
  await assert.rejects(saveQuestionTools("workspace-1", { notebookId: "notebook-1", enabled: { "connector:kc-x": true }, fetchImpl }),
    (error) => error.code === "QUESTION_TOOL_UNKNOWN" && error.status === 422);
});

test("답변 과정 scope.tools의 켜진 도구 라벨 목록(빈 목록 포함)을 웹 검사가 받는다", async () => {
  const { validateAnswerProcess } = await import("../../apps/web/lib/answer-process.js");
  const base = {
    version: 1, scope: { source_count: 0, knowledge_packages: [], tools: ["승인 지식", "Daon2-RAG"] }, evidence: null,
    egress: { decision: "not_needed", masked: false, redacted: false, policy_ref: null }, model: null,
    verification: { citations: 0, valid: true, insufficient: true, retried: false },
  };
  assert.deepEqual(validateAnswerProcess(structuredClone(base)).scope.tools, ["승인 지식", "Daon2-RAG"]);
  assert.deepEqual(validateAnswerProcess({ ...structuredClone(base), scope: { ...base.scope, tools: [] } }).scope.tools, []);
});

test("OpenAPI는 질문 도구 GET·PUT과 정확한 항목 모양을 공개하고 웹 도구는 없다", async () => {
  const { readFile } = await import("node:fs/promises");
  const contract = JSON.parse(await readFile(new URL("../../packages/contracts/openapi/v1/openapi.json", import.meta.url), "utf8"));
  const path = contract.paths["/api/v1/workspaces/{id}/notebooks/{notebook_id}/question-tools"];
  assert.deepEqual(Object.keys(path).sort(), ["get", "put"]);
  for (const method of ["get", "put"]) {
    assert.equal(path[method].responses["200"].content["application/json"].schema.$ref, "#/components/schemas/QuestionToolsEnvelope");
  }
  assert.ok(path.put.responses["422"]);
  assert.equal(path.put.requestBody.content["application/json"].schema.$ref, "#/components/schemas/QuestionToolsUpdateRequest");
  const tool = contract.components.schemas.QuestionTool;
  assert.equal(tool.additionalProperties, false);
  assert.deepEqual(tool.required, ["id", "kind", "label", "available", "enabled"]);
  assert.deepEqual(tool.properties.kind.enum, ["approved_knowledge", "connector"]);
  assert.deepEqual(tool.properties.connector_kind.enum, ["daon2_rag", "daon2", "law"]);
  assert.deepEqual(tool.properties.reason.enum, ["NO_SCOPE_SELECTED", "CONNECTOR_NOT_READY", "CONNECTOR_DISABLED"]);
  for (const code of ["QUESTION_TOOL_UNKNOWN", "QUESTION_TOOLS_INVALID", "QUESTION_TOOLS_UNAVAILABLE"]) {
    assert.ok(contract.components.schemas.SafeErrorCode.enum.includes(code), code);
  }
});
