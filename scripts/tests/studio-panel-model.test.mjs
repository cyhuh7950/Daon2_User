import assert from "node:assert/strict";
import test from "node:test";

import {
  TILE_ORDER, cardState, cardSubtitle, createStudioPanelState, formatRelativeTime, hasActiveJob, menuItems, optimisticOutput, pollInterval, reduce, tileState,
} from "../../packages/ui/src/studio-panel-model.js";
import { STUDIO_MESSAGES, msg, studioErrorMessage } from "../../packages/ui/src/studio-messages.ko.js";

const NOW = Date.parse("2026-10-20T12:00:00Z");
const out = (over = {}) => ({ output_id: `sv2-${"a".repeat(32)}`, type_id: "report", format_id: "summary", title: "보고서", status: "completed", error_code: null,
  source_count: 14, current_revision: 1, created_at: "2026-07-19T12:00:00Z", updated_at: "2026-07-19T12:00:00Z", stale: false, ...over });

test("타일 순서는 NotebookLM 배치(9종)와 같다", () => {
  assert.equal(TILE_ORDER.length, 9);
  assert.deepEqual(TILE_ORDER.slice(0, 3), ["audio_overview", "slides", "video_overview"]);
  for (const id of TILE_ORDER) assert.ok(STUDIO_MESSAGES[`studio.tile.${id}`], id);
});

test("타일 활성 규칙", () => {
  const report = { type_id: "report", available: true };
  assert.deepEqual(tileState({ type_id: "video_overview", available: false }, {}), { enabled: false, reason: "unavailable" });
  assert.equal(tileState(report, { sourceCount: 0 }).reason, "no_sources");
  assert.equal(tileState(report, { sourceCount: 3, checkedCount: 0 }).reason, "none_selected");
  assert.equal(tileState(report, { sourceCount: 3, checkedCount: 2, readySourceCount: 0, processingCount: 1 }).reason, "processing");
  assert.equal(tileState(report, { sourceCount: 3, checkedCount: 2, readySourceCount: 0 }).reason, "no_sources");
  assert.deepEqual(tileState(report, { sourceCount: 3, checkedCount: 2, readySourceCount: 2 }), { enabled: true, reason: null });
  assert.equal(tileState({ type_id: "memo", available: true }, { sourceCount: 0 }).enabled, true);
});

test("카드 부제와 상대 시간", () => {
  assert.equal(cardSubtitle(out(), { now: NOW }), "요약 · 소스 14개 · 93일 전");
  assert.equal(cardSubtitle(out({ type_id: "memo", format_id: null }), { now: NOW }), "93일 전");
  assert.equal(cardSubtitle(out({ format_id: null, updated_at: "2026-10-20T11:59:50Z" }), { now: NOW }), "소스 14개 · 방금");
  assert.equal(formatRelativeTime("2026-10-20T11:30:00Z", NOW), "30분 전");
  assert.equal(formatRelativeTime("2026-10-20T07:00:00Z", NOW), "5시간 전");
  assert.equal(formatRelativeTime("garbage", NOW), "");
});

test("폴링 판정: 활성 작업이 있을 때만, 숨김 탭은 느리게", () => {
  assert.equal(hasActiveJob([out()]), false);
  assert.equal(pollInterval([out()]), null);
  assert.equal(pollInterval([out({ status: "generating" })]), 1500);
  assert.equal(pollInterval([out({ status: "queued" })], true), 10000);
});

test("리듀서: 낙관적 카드 삽입·교체·폴링 병합·삭제", () => {
  let state = reduce(createStudioPanelState(), { type: "LOADED", types: [], outputs: [out()] });
  state = reduce(state, { type: "CREATE_STARTED", typeId: "quiz" });
  assert.deepEqual(state.pendingCreate, ["quiz"]);
  const pending = optimisticOutput("quiz", "퀴즈", NOW);
  state = reduce(state, { type: "OUTPUT_UPDATED", output: pending });
  assert.equal(state.outputs[0].optimistic, true);
  const real = out({ output_id: `sv2-${"b".repeat(32)}`, type_id: "quiz", status: "queued", title: "퀴즈" });
  state = reduce(state, { type: "OUTPUT_REMOVED", outputId: pending.output_id });
  state = reduce(state, { type: "OUTPUT_CREATED", typeId: "quiz", output: real });
  assert.equal(state.pendingCreate.length, 0);
  assert.equal(state.outputs[0].output_id, real.output_id);
  state = reduce(state, { type: "POLL_RESULT", outputs: [{ ...real, status: "completed" }, out()] });
  assert.equal(state.outputs.find((o) => o.output_id === real.output_id).status, "completed");
  assert.equal(state.outputs.length, 2);
  state = reduce(state, { type: "SELECT", outputId: real.output_id });
  state = reduce(state, { type: "OUTPUT_REMOVED", outputId: real.output_id });
  assert.equal(state.selectedOutputId, null);
  state = reduce(state, { type: "CREATE_FAILED", typeId: "quiz", code: "STUDIO_NO_READY_SOURCE" });
  assert.equal(state.error, "STUDIO_NO_READY_SOURCE");
  assert.equal(reduce(state, { type: "UNKNOWN" }), state);
});

test("카드 상태와 메뉴 항목 규칙", () => {
  assert.equal(cardState(out({ status: "generating" })), "generating");
  assert.equal(cardState(out({ stale: true })), "stale");
  const generating = menuItems(out({ status: "generating", current_revision: 0 }));
  assert.deepEqual(generating.map((i) => i.id), ["share", "rename", "download", "provenance", "regenerate", "regenerate_with_settings", "delete"]);
  assert.equal(generating.find((i) => i.id === "download").disabled, true);
  assert.equal(generating.find((i) => i.id === "delete").danger, true);
  assert.deepEqual(menuItems(out({ type_id: "memo" })).map((i) => i.id), ["share", "rename", "download", "provenance", "delete"]);
});

test("메시지는 키로만 찾고 오류 코드는 안전한 문구로 바꾼다", () => {
  assert.equal(msg("studio.card.count", { count: 3 }), "산출물 3개");
  assert.throws(() => msg("studio.nope"), /STUDIO_MESSAGE_MISSING/);
  assert.match(studioErrorMessage("STUDIO_NO_READY_SOURCE"), /소스/);
  assert.equal(studioErrorMessage("select * from secrets"), STUDIO_MESSAGES["studio.error.generic"]);
  assert.equal(studioErrorMessage("UNKNOWN_CODE_X"), STUDIO_MESSAGES["studio.error.generic"]);
});
