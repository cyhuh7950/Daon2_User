import assert from "node:assert/strict";
import test from "node:test";

import { createBffProxy } from "../../apps/web/lib/bff-api-proxy.js";
import {
  createSourceGroup, deleteSourceGroup, listSourceGroups, setSourceGroupMembers, StudioV2Error, updateSourceGroup,
} from "../../apps/web/lib/studio-v2-api.js";
import { createStudioV2Adapter } from "../../apps/web/lib/studio-v2-adapter.js";

// 소스 묶음(WO-N1 NB3-F2, 결정 D-11): BFF 경로 허용, 웹 API 클라이언트 요청 헤더·응답 검사, 노트북 범위 어댑터.
const COOKIE = "__Host-daon_session=opaque-session";
const ORIGIN = "https://app.example.com";
const GID = `sg-${"a".repeat(32)}`;
const BASE_SEGMENTS = ["workspaces", "workspace-1", "notebooks", "notebook-1", "source-groups"];
const BASE_URL = `${ORIGIN}/bff/api/workspaces/workspace-1/notebooks/notebook-1/source-groups`;
const UPSTREAM = "https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1/source-groups";
const ETAG = `"sg-${"b".repeat(32)}"`;
const GROUPS = { groups: [{ group_id: GID, name: "계약 조건", position: 0, source_ids: ["src-a", "src-b"] }] };

function makeProxy(captured) {
  return createBffProxy({
    baseUrl: new URL("https://api.example.com"),
    publicOrigin: new URL(ORIGIN),
    fetchImpl: async (url, init) => {
      captured.push({ url: String(url), method: init.method, headers: new Headers(init.headers) });
      return Response.json({ data: GROUPS, meta: {} }, { headers: { ETag: ETAG } });
    },
  });
}

const writeHeaders = (extra = {}) => ({
  Cookie: COOKIE, Origin: ORIGIN, Referer: `${ORIGIN}/notebooks/notebook-1`, "Content-Type": "application/json", ...extra,
});

test("BFF는 묶음 목록 GET·POST, 묶음 PATCH·DELETE, 구성원 PUT만 정확한 경로로 전달하고 쓰기는 CSRF Referer를 요구한다", async () => {
  const captured = [];
  const proxy = makeProxy(captured);
  const got = await proxy(new Request(BASE_URL, { headers: { Cookie: COOKIE } }), BASE_SEGMENTS);
  assert.equal(got.status, 200);
  assert.equal(got.headers.get("etag"), ETAG);
  assert.equal(captured.at(-1).url, UPSTREAM);

  const post = await proxy(new Request(BASE_URL, {
    method: "POST", body: JSON.stringify({ name: "묶음" }), headers: writeHeaders({ "Idempotency-Key": "source-group-key-0001" }),
  }), BASE_SEGMENTS);
  assert.equal(post.status, 200);
  assert.equal(captured.at(-1).method, "POST");
  assert.equal(captured.at(-1).headers.get("idempotency-key"), "source-group-key-0001");

  const patch = await proxy(new Request(`${BASE_URL}/${GID}`, {
    method: "PATCH", body: JSON.stringify({ name: "새 이름" }), headers: writeHeaders({ "If-Match": ETAG }),
  }), [...BASE_SEGMENTS, GID]);
  assert.equal(patch.status, 200);
  assert.equal(captured.at(-1).url, `${UPSTREAM}/${GID}`);
  assert.equal(captured.at(-1).headers.get("if-match"), ETAG);

  const del = await proxy(new Request(`${BASE_URL}/${GID}`, { method: "DELETE", body: "{}", headers: writeHeaders({ "If-Match": ETAG }) }),
    [...BASE_SEGMENTS, GID]);
  assert.equal(del.status, 200);
  assert.equal(captured.at(-1).method, "DELETE");

  const put = await proxy(new Request(`${BASE_URL}/${GID}/members`, {
    method: "PUT", body: JSON.stringify({ source_ids: ["src-a"] }), headers: writeHeaders({ "If-Match": ETAG }),
  }), [...BASE_SEGMENTS, GID, "members"]);
  assert.equal(put.status, 200);
  assert.equal(captured.at(-1).url, `${UPSTREAM}/${GID}/members`);
  assert.equal(captured.length, 5);

  // 막히는 요청: 다른 메서드, 잘못된 묶음 ID, Referer 없는 쓰기, 질의 문자열, 모르는 하위 경로.
  const rejected = [
    [new Request(BASE_URL, { method: "PUT", body: "{}", headers: writeHeaders() }), BASE_SEGMENTS, 405],
    [new Request(`${BASE_URL}/${GID}`, { headers: { Cookie: COOKIE } }), [...BASE_SEGMENTS, GID], 405],
    [new Request(`${BASE_URL}/${GID}/members`, { headers: { Cookie: COOKIE } }), [...BASE_SEGMENTS, GID, "members"], 405],
    [new Request(`${BASE_URL}/not-a-group`, { method: "PATCH", body: "{}", headers: writeHeaders() }), [...BASE_SEGMENTS, "not-a-group"], null],
    [new Request(BASE_URL, { method: "POST", body: "{}", headers: { Cookie: COOKIE, Origin: ORIGIN, "Content-Type": "application/json" } }), BASE_SEGMENTS, null],
    [new Request(`${BASE_URL}?x=1`, { headers: { Cookie: COOKIE } }), BASE_SEGMENTS, null],
    [new Request(`${BASE_URL}/${GID}/other`, { method: "PUT", body: "{}", headers: writeHeaders() }), [...BASE_SEGMENTS, GID, "other"], null],
  ];
  for (const [request, segments, status] of rejected) {
    const response = await proxy(request, segments);
    if (status === null) assert.notEqual(response.status, 200, `${request.method} ${request.url}`);
    else assert.equal(response.status, status, `${request.method} ${request.url}`);
  }
  assert.equal(captured.length, 5);
});

function fakeFetch(responses) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    const next = responses.shift();
    return typeof next === "function" ? next() : next;
  };
  return { calls, fetchImpl };
}

const ok = (data, status = 200, meta = {}) => Response.json({ data, meta }, { status, headers: { ETag: ETAG } });

test("웹 API 클라이언트: 목록·만들기·수정·삭제·구성원 저장은 정확한 메서드·헤더로 보내고 ETag를 돌려준다", async () => {
  const { calls, fetchImpl } = fakeFetch([
    ok(GROUPS), ok({ group_id: GID }, 201, { replayed: false }), ok(GROUPS), ok({ groups: [] }), ok(GROUPS),
  ]);
  const listed = await listSourceGroups("workspace-1", { notebookId: "notebook-1", fetchImpl });
  assert.deepEqual(listed, { groups: GROUPS.groups, etag: ETAG });
  assert.equal(calls[0].url, "/bff/api/workspaces/workspace-1/notebooks/notebook-1/source-groups");
  assert.equal(calls[0].init.method, "GET");

  const created = await createSourceGroup("workspace-1", { notebookId: "notebook-1", name: "계약 조건", idempotencyKey: "source-group-key-0001", fetchImpl });
  assert.deepEqual(created, { groupId: GID, etag: ETAG, replayed: false });
  assert.equal(calls[1].init.method, "POST");
  assert.equal(calls[1].init.headers["Idempotency-Key"], "source-group-key-0001");
  assert.deepEqual(JSON.parse(calls[1].init.body), { name: "계약 조건" });

  const updated = await updateSourceGroup("workspace-1", GID, { notebookId: "notebook-1", name: "가격", position: 2, etag: ETAG, fetchImpl });
  assert.equal(updated.etag, ETAG);
  assert.equal(calls[2].url, `/bff/api/workspaces/workspace-1/notebooks/notebook-1/source-groups/${GID}`);
  assert.equal(calls[2].init.method, "PATCH");
  assert.equal(calls[2].init.headers["If-Match"], ETAG);
  assert.deepEqual(JSON.parse(calls[2].init.body), { name: "가격", position: 2 });

  const deleted = await deleteSourceGroup("workspace-1", GID, { notebookId: "notebook-1", etag: ETAG, fetchImpl });
  assert.deepEqual(deleted, { groups: [], etag: ETAG });
  assert.equal(calls[3].init.method, "DELETE");
  assert.equal(calls[3].init.headers["If-Match"], ETAG);

  const saved = await setSourceGroupMembers("workspace-1", GID, { notebookId: "notebook-1", sourceIds: ["src-b", "src-a"], etag: ETAG, fetchImpl });
  assert.deepEqual(saved.groups, GROUPS.groups);
  assert.equal(calls[4].url, `/bff/api/workspaces/workspace-1/notebooks/notebook-1/source-groups/${GID}/members`);
  assert.equal(calls[4].init.method, "PUT");
  assert.deepEqual(JSON.parse(calls[4].init.body), { source_ids: ["src-b", "src-a"] });
});

test("웹 API 클라이언트: 만들기의 Idempotency-Key는 지정하지 않아도 붙는다", async () => {
  const { calls, fetchImpl } = fakeFetch([ok({ group_id: GID }, 201)]);
  await createSourceGroup("workspace-1", { notebookId: "notebook-1", name: "묶음", fetchImpl });
  assert.match(calls[0].init.headers["Idempotency-Key"], /^studio-v2-/u);
});

test("웹 API 클라이언트: 잘못된 입력은 보내지 않는다", async () => {
  const { calls, fetchImpl } = fakeFetch([]);
  const bad = [
    () => createSourceGroup("workspace-1", { notebookId: "notebook-1", name: "", fetchImpl }),
    () => createSourceGroup("workspace-1", { notebookId: "notebook-1", name: "가".repeat(81), fetchImpl }),
    () => updateSourceGroup("workspace-1", GID, { notebookId: "notebook-1", etag: ETAG, fetchImpl }),
    () => updateSourceGroup("workspace-1", GID, { notebookId: "notebook-1", name: "새", fetchImpl }),
    () => updateSourceGroup("workspace-1", "not-a-group", { notebookId: "notebook-1", name: "새", etag: ETAG, fetchImpl }),
    () => updateSourceGroup("workspace-1", GID, { notebookId: "notebook-1", position: -1, etag: ETAG, fetchImpl }),
    () => deleteSourceGroup("workspace-1", GID, { notebookId: "notebook-1", fetchImpl }),
    () => setSourceGroupMembers("workspace-1", GID, { notebookId: "notebook-1", sourceIds: ["a", "a"], etag: ETAG, fetchImpl }),
    () => setSourceGroupMembers("workspace-1", GID, { notebookId: "notebook-1", sourceIds: "src-a", etag: ETAG, fetchImpl }),
    () => setSourceGroupMembers("workspace-1", GID, { notebookId: "notebook-1", sourceIds: ["bad id"], etag: ETAG, fetchImpl }),
  ];
  for (const call of bad) {
    await assert.rejects(call, (error) => error instanceof StudioV2Error && error.code === "STUDIO_INPUT_INVALID");
  }
  assert.equal(calls.length, 0);
});

test("웹 API 클라이언트: 응답 모양이 다르면 거부하고 서버 오류 코드를 그대로 전한다", async () => {
  const shapes = [
    { groups: [{ ...GROUPS.groups[0], extra: 1 }] },
    { groups: [{ ...GROUPS.groups[0], name: "" }] },
    { groups: [{ ...GROUPS.groups[0], position: -1 }] },
    { groups: [{ ...GROUPS.groups[0], source_ids: ["bad id"] }] },
    { groups: [GROUPS.groups[0], { ...GROUPS.groups[0], group_id: `sg-${"c".repeat(32)}` }] }, // 소스 하나가 두 묶음에
    { groups: [{ ...GROUPS.groups[0], group_id: "group-1" }] },
    { groups: Array.from({ length: 51 }, (_, i) => ({ group_id: `sg-${String(i).padStart(32, "0")}`, name: "n", position: i, source_ids: [] })) },
    { groups: [], more: true },
  ];
  for (const data of shapes) {
    const { fetchImpl } = fakeFetch([ok(data)]);
    await assert.rejects(listSourceGroups("workspace-1", { notebookId: "notebook-1", fetchImpl }),
      (error) => error.code === "STUDIO_RESPONSE_INVALID");
  }
  const errors = [
    [409, "SOURCE_GROUP_LIMIT"], [422, "SOURCE_NOT_IN_NOTEBOOK"], [412, "SOURCE_GROUP_ETAG_MISMATCH"], [403, "FORBIDDEN"],
  ];
  for (const [status, code] of errors) {
    const { fetchImpl } = fakeFetch([Response.json({ error: { code } }, { status })]);
    await assert.rejects(setSourceGroupMembers("workspace-1", GID, { notebookId: "notebook-1", sourceIds: ["src-z"], etag: ETAG, fetchImpl }),
      (error) => error.code === code && error.status === status);
  }
  const { fetchImpl } = fakeFetch([ok({ group_id: "sv2-x" }, 201)]);
  await assert.rejects(createSourceGroup("workspace-1", { notebookId: "notebook-1", name: "묶음", fetchImpl }),
    (error) => error.code === "STUDIO_RESPONSE_INVALID");
});

test("어댑터는 노트북 범위를 채워 묶음 함수를 부른다", async () => {
  const { calls, fetchImpl } = fakeFetch([ok(GROUPS), ok({ group_id: GID }, 201), ok(GROUPS), ok(GROUPS), ok({ groups: [] })]);
  const adapter = createStudioV2Adapter("workspace-1", "notebook-1", { fetchImpl });
  assert.deepEqual((await adapter.listSourceGroups()).groups, GROUPS.groups);
  assert.equal((await adapter.createSourceGroup("묶음")).groupId, GID);
  await adapter.updateSourceGroup(GID, { name: "새", etag: ETAG });
  await adapter.setSourceGroupMembers(GID, ["src-a"], { etag: ETAG });
  await adapter.deleteSourceGroup(GID, { etag: ETAG });
  assert.deepEqual(calls.map((call) => call.init.method), ["GET", "POST", "PATCH", "PUT", "DELETE"]);
  for (const call of calls) assert.ok(call.url.startsWith("/bff/api/workspaces/workspace-1/notebooks/notebook-1/source-groups"));
});
