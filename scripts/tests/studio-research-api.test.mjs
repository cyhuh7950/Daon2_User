import assert from "node:assert/strict";
import test from "node:test";

import { MAX_RESEARCH_QUERY, StudioV2Error, createStudioResearch, listStudioOutputs, studioResearchOf } from "../../apps/web/lib/studio-v2-api.js";
import { createStudioV2Adapter } from "../../apps/web/lib/studio-v2-adapter.js";

// 심층 조사 웹 API 클라이언트(WO-N1 NB4-F2): 보고서 산출물 생성 요청, 목록의 진행 문구, 결과의 research 블록 검증.
const OID = `sv2-${"b".repeat(32)}`;
const BASE = "/bff/api/workspaces/ws-1/notebooks/nb-1/studio";
const ITEM = { output_id: OID, type_id: "report", format_id: "briefing", title: "보고서", status: "generating", error_code: null, source_count: 0, current_revision: 0, created_at: "2026-11-24T00:00:00Z", updated_at: "2026-11-24T00:00:00Z", stale: false };
const reply = (data, status = 202) => new Response(JSON.stringify({ data, meta: { trace_id: "t" } }), { status, headers: { "Content-Type": "application/json" } });
const DOC = { candidate_id: "doc-1", kind: "document", title: "평가 기준서", origin_label: "문서 근거 · 제안서", reason: "2쪽 내용이 검색어와 관련 있습니다", preview: "기술 70점", action: "add_source",
  ref: { kind: "document", project_id: "p", work_package_id: "w", document_id: "d", document_version: "v" } };
const KP = { candidate_id: "kp-1", kind: "knowledge_package", title: "p / w", origin_label: "승인 지식", reason: "업무 패키지 이름이 검색어와 일치합니다", preview: "p / w · 승인 문서 3건", action: "add_scope",
  ref: { kind: "knowledge_package", project_id: "p", work_package_id: "w" } };
const RESEARCH = { query: "평가 기준", sub_questions: ["평가 기준", "제출 서류"], candidates: [DOC, KP], unavailable: [{ scope: "knowledge", reason: "TOOL_NOT_ALLOWED" }], tool_calls: 6 };

function recorder(handler) {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push({ url, init }); return handler(url, init); };
  return { calls, fetchImpl };
}

test("createStudioResearch는 보고서 산출물을 research 설정으로 만들고 소스는 보내지 않는다", async () => {
  const { calls, fetchImpl } = recorder(() => reply({ output_id: OID, job_id: "svj-1", status: "queued" }));
  const receipt = await createStudioResearch("ws-1", { notebookId: "nb-1", query: "평가 기준", scopes: ["documents", "knowledge"], formatId: "briefing", focus: "점수", fetchImpl });
  assert.equal(receipt.output_id, OID);
  assert.equal(calls[0].url, `${BASE}/outputs`);
  assert.equal(calls[0].init.method, "POST");
  assert.ok(calls[0].init.headers["Idempotency-Key"]);
  assert.deepEqual(JSON.parse(calls[0].init.body), { type_id: "report", format_id: "briefing", settings: { research_query: "평가 기준", research_scopes: ["documents", "knowledge"], focus: "점수" } });
});

test("createStudioResearch는 잘못된 질문·범위를 보내지 않는다", async () => {
  const { calls, fetchImpl } = recorder(() => reply({ output_id: OID, job_id: "svj-1", status: "queued" }));
  for (const [query, scopes] of [["", ["documents"]], ["  ", ["documents"]], ["가".repeat(MAX_RESEARCH_QUERY + 1), ["documents"]], ["q", []], ["q", ["web"]], ["q", ["documents", "documents"]], ["q", "documents"]]) {
    await assert.rejects(createStudioResearch("ws-1", { notebookId: "nb-1", query, scopes, fetchImpl }), (e) => e instanceof StudioV2Error && e.code === "STUDIO_INPUT_INVALID");
  }
  assert.equal(calls.length, 0);
});

test("목록 항목의 progress는 진행 문구를 담고, 없거나 null이어도 받으며, 모양이 틀리면 거부한다", async () => {
  const page = (items) => recorder(() => reply({ items, next_cursor: null }, 200)).fetchImpl;
  const withProgress = { ...ITEM, progress: { pct: 40, note: "찾기 2/5" } };
  const result = await listStudioOutputs("ws-1", { notebookId: "nb-1", fetchImpl: page([withProgress, { ...ITEM, output_id: `sv2-${"c".repeat(32)}`, progress: null }, { ...ITEM, output_id: `sv2-${"d".repeat(32)}` }]) });
  assert.deepEqual(result.items[0].progress, { pct: 40, note: "찾기 2/5" });
  assert.equal(result.items[1].progress, null);
  for (const progress of [{ pct: 101, note: null }, { pct: 10 }, { pct: 10, note: "x".repeat(201) }, { pct: "10", note: null }, "작성"]) {
    await assert.rejects(listStudioOutputs("ws-1", { notebookId: "nb-1", fetchImpl: page([{ ...ITEM, progress }]) }), (e) => e.code === "STUDIO_RESPONSE_INVALID");
  }
});

test("studioResearchOf는 research 블록을 검사해 꺼내고 틀리면 null이다", () => {
  const output = (research) => ({ output_id: OID, revision: { content: { schema: "studio.report.v1", body: {}, research } } });
  assert.deepEqual(studioResearchOf(output(RESEARCH)), { query: "평가 기준", subQuestions: ["평가 기준", "제출 서류"], candidates: [DOC, KP], unavailable: RESEARCH.unavailable, toolCalls: 6 });
  assert.equal(studioResearchOf({ output_id: OID, revision: { content: { body: {} } } }), null);
  assert.equal(studioResearchOf({ output_id: OID, revision: null }), null);
  for (const bad of [{ ...RESEARCH, extra: 1 }, { ...RESEARCH, tool_calls: 13 }, { ...RESEARCH, sub_questions: [] }, { ...RESEARCH, sub_questions: ["1", "2", "3", "4", "5", "6"] },
    { ...RESEARCH, candidates: [DOC, DOC] }, { ...RESEARCH, candidates: [{ ...DOC, action: "add_scope" }] }, { ...RESEARCH, unavailable: [{ scope: "web", reason: "X_Y" }] }]) {
    assert.equal(studioResearchOf(output(bad)), null);
  }
});

test("노트북 어댑터는 심층 조사 생성을 노트북 범위로 묶는다", async () => {
  const { calls, fetchImpl } = recorder(() => reply({ output_id: OID, job_id: "svj-1", status: "queued" }));
  const adapter = createStudioV2Adapter("ws-1", "nb-1", { fetchImpl });
  await adapter.createResearch("평가 기준", ["documents"], { formatId: "summary" });
  assert.equal(calls[0].url, `${BASE}/outputs`);
  assert.deepEqual(JSON.parse(calls[0].init.body).settings, { research_query: "평가 기준", research_scopes: ["documents"] });
});
