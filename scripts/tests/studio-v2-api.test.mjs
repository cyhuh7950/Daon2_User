import assert from "node:assert/strict";
import test from "node:test";

import {
  StudioV2Error, cancelStudioOutput, createStudioMemo, createStudioOutput, deleteStudioOutput, downloadStudioExport, getStudioCustomization,
  getStudioEvidenceContent, getStudioOutput, listStudioOutputs, listStudioTypes, regenerateStudioOutput, renameStudioOutput, saveStudioCustomization,
} from "../../apps/web/lib/studio-v2-api.js";

const OID = `sv2-${"a".repeat(32)}`;
const BASE = "/bff/api/workspaces/ws-1/notebooks/nb-1/studio";
const ITEM = { output_id: OID, type_id: "report", format_id: "summary", title: "보고서", status: "queued", error_code: null, source_count: 2, current_revision: 0, created_at: "2026-10-20T00:00:00Z", updated_at: "2026-10-20T00:00:00Z", stale: false };
const reply = (data, init = {}) => new Response(JSON.stringify({ data, meta: { trace_id: "t" } }), { status: 200, headers: { "Content-Type": "application/json", ...(init.headers ?? {}) }, ...init });

function recorder(handler) {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push({ url, init }); return handler(url, init, calls.length); };
  return { calls, fetchImpl };
}

test("목록·유형 조회는 same-origin GET이며 모양을 검증한다", async () => {
  const { calls, fetchImpl } = recorder((url) => url.endsWith("/types")
    ? reply({ types: [{ type_id: "report", available: true, export_formats: ["docx"], presets: ["summary"] }], limits: { user_concurrency: 2 } })
    : reply({ items: [ITEM], next_cursor: "c2" }, { headers: { ETag: '"e1"' } }));
  const types = await listStudioTypes("ws-1", { notebookId: "nb-1", fetchImpl });
  assert.equal(types[0].type_id, "report");
  assert.equal(types.limits.userConcurrency, 2);
  const page = await listStudioOutputs("ws-1", { notebookId: "nb-1", limit: 10, cursor: "c1", fetchImpl });
  assert.equal(page.nextCursor, "c2");
  assert.equal(page.etag, '"e1"');
  assert.equal(calls[1].url, `${BASE}/outputs?limit=10&cursor=c1`);
  assert.equal(calls[1].init.credentials, "same-origin");
  assert.equal(calls[1].init.cache, "no-store");
  assert.equal(calls[1].init.method, "GET");
  assert.equal(calls[1].init.body, undefined);
});

test("생성·재생성·메모는 Idempotency-Key와 JSON 본문을 보낸다", async () => {
  const { calls, fetchImpl } = recorder((url) => url.endsWith("/memos")
    ? reply({ output_id: OID, status: "completed", replayed: false })
    : reply({ output_id: OID, job_id: "svj-1", status: "queued" }));
  const created = await createStudioOutput("ws-1", { notebookId: "nb-1", typeId: "report", formatId: "briefing", settings: { focus: "핵심" }, sourceVersionIds: ["sv-1"], idempotencyKey: "key-0000000000001", fetchImpl });
  assert.equal(created.job_id, "svj-1");
  assert.deepEqual(JSON.parse(calls[0].init.body), { type_id: "report", format_id: "briefing", settings: { focus: "핵심" }, source_version_ids: ["sv-1"] });
  assert.equal(calls[0].init.headers["Idempotency-Key"], "key-0000000000001");
  await regenerateStudioOutput("ws-1", OID, { notebookId: "nb-1", settings: { focus: "x" }, fetchImpl });
  assert.match(calls[1].init.headers["Idempotency-Key"], /^studio-v2-/u);
  assert.equal(calls[1].url, `${BASE}/outputs/${OID}/regenerate`);
  await createStudioMemo("ws-1", { notebookId: "nb-1", fromRunResultId: "rr-1", fetchImpl });
  assert.deepEqual(JSON.parse(calls[2].init.body), { from_run_result_id: "rr-1" });
  await cancelStudioOutput("ws-1", OID, { notebookId: "nb-1", fetchImpl: async () => reply({ output_id: OID, cancel_requested: true }) });
});

test("이름 변경은 If-Match를, 삭제는 204만 성공으로 본다", async () => {
  const { calls, fetchImpl } = recorder((url, init) => init.method === "DELETE" ? new Response(null, { status: 204 })
    : reply({ output_id: OID, title: "새", updated_at: "2026-10-20T01:00:00Z" }));
  await renameStudioOutput("ws-1", OID, "새", { notebookId: "nb-1", etag: '"studio-v2:x:y"', fetchImpl });
  assert.equal(calls[0].init.headers["If-Match"], '"studio-v2:x:y"');
  await deleteStudioOutput("ws-1", OID, { notebookId: "nb-1", fetchImpl });
  assert.equal(calls[1].init.method, "DELETE");
  await assert.rejects(deleteStudioOutput("ws-1", OID, { notebookId: "nb-1", fetchImpl: async () => new Response("{}", { status: 200 }) }), StudioV2Error);
});

test("오류는 안전한 코드만 노출하고 모양이 다르면 거부한다", async () => {
  const conflict = async () => new Response(JSON.stringify({ error: { code: "STUDIO_NO_READY_SOURCE", message: "secret detail" } }), { status: 409 });
  await assert.rejects(createStudioOutput("ws-1", { notebookId: "nb-1", typeId: "report", fetchImpl: conflict }), (e) => e.code === "STUDIO_NO_READY_SOURCE" && e.status === 409 && !e.message.includes("secret"));
  const weird = async () => new Response("not json", { status: 500 });
  await assert.rejects(listStudioOutputs("ws-1", { notebookId: "nb-1", fetchImpl: weird }), (e) => e.code === "STUDIO_REQUEST_FAILED");
  const bad = async () => reply({ items: [{ ...ITEM, status: "weird" }], next_cursor: null });
  await assert.rejects(listStudioOutputs("ws-1", { notebookId: "nb-1", fetchImpl: bad }), (e) => e.code === "STUDIO_RESPONSE_INVALID");
  await assert.rejects(getStudioOutput("ws-1", "not-an-id", { notebookId: "nb-1", fetchImpl: bad }), (e) => e.code === "STUDIO_INPUT_INVALID");
  await assert.rejects(listStudioTypes("bad id", { notebookId: "nb-1", fetchImpl: bad }), StudioV2Error);
});

test("내보내기는 바이트와 헤더를 돌려주고 상한을 지킨다", async () => {
  const ok = async () => new Response(new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="a.pdf"' } });
  const result = await downloadStudioExport("ws-1", OID, "pdf", { notebookId: "nb-1", fetchImpl: ok });
  assert.deepEqual([...result.bytes], [1, 2, 3]);
  assert.equal(result.contentType, "application/pdf");
  await assert.rejects(downloadStudioExport("ws-1", OID, "pdf", { notebookId: "nb-1", fetchImpl: async () => new Response(new Uint8Array(0)) }), (e) => e.code === "STUDIO_RESPONSE_INVALID");
});

test("근거 보기는 JSON 발췌와 PDF 바이너리를 구분한다", async () => {
  const excerpt = async () => new Response(JSON.stringify({ filename: "a.txt", text: "본문", locator: { kind: "page", value: "1" } }), { headers: { "Content-Type": "application/json" } });
  assert.equal((await getStudioEvidenceContent("ws-1", OID, "S1", { notebookId: "nb-1", fetchImpl: excerpt })).kind, "excerpt");
  const pdf = async () => new Response(new Uint8Array([37, 80]), { headers: { "Content-Type": "application/pdf", "x-citation-page": "3" } });
  const binary = await getStudioEvidenceContent("ws-1", OID, "S1", { notebookId: "nb-1", revision: 2, fetchImpl: pdf });
  assert.equal(binary.kind, "binary");
  assert.equal(binary.page, "3");
});

test("맞춤설정은 ETag로 저장한다", async () => {
  const { calls, fetchImpl } = recorder((url, init) => reply({ instruction: init.method === "PUT" ? "존댓말" : "", version: init.method === "PUT" ? 1 : 0 },
    { headers: { ETag: '"studio-v2-customization:nb-1:0"' } }));
  const current = await getStudioCustomization("ws-1", { notebookId: "nb-1", fetchImpl });
  const saved = await saveStudioCustomization("ws-1", "존댓말", { notebookId: "nb-1", etag: current.etag, fetchImpl });
  assert.equal(calls[1].init.headers["If-Match"], '"studio-v2-customization:nb-1:0"');
  assert.equal(saved.version, 1);
});
