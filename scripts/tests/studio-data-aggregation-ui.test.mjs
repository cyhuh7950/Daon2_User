// 데이터 집계(WO-N9 작업 8) 화면·BFF·어댑터 시험.
import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
// vite build가 NODE_ENV를 production으로 바꾸기 전에 React(act 포함 개발판)를 먼저 읽는다.
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";

import { MinimalEvent, findElements, installMinimalDom } from "./product-studio-dom.mjs";
import { TILE_ORDER, needsSettingsDialog, progressNoteKey, tableSources } from "../../packages/ui/src/studio-panel-model.js";
import { STUDIO_ERRORS, STUDIO_MESSAGES, studioErrorMessage } from "../../packages/ui/src/studio-messages.ko.js";
import { STUDIO_ICONS, STUDIO_TILE_ORDER, STUDIO_TYPE_STYLE } from "../../packages/ui/src/studio-icon-data.js";
import { createBffProxy } from "../../apps/web/lib/bff-api-proxy.js";
import { getStudioOutput, getStudioTableProfile } from "../../apps/web/lib/studio-v2-api.js";
import { createStudioV2Adapter } from "../../apps/web/lib/studio-v2-adapter.js";

const root = path.resolve(import.meta.dirname, "../..");
const read = (file) => readFile(path.join(root, file), "utf8");
const OID = (c) => `sv2-${c.repeat(32)}`;
const reactProps = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];
const wait = (ms) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

// ---------------------------------------------------------------- 문구·타일·모델
test("data_aggregation 타일이 순서·아이콘·문구에 연결된다", () => {
  assert.equal(TILE_ORDER.at(-1), "data_aggregation");
  assert.equal(STUDIO_TILE_ORDER.at(-1), "data_aggregation");
  assert.equal(STUDIO_TYPE_STYLE.data_aggregation.labelKey, "studio.tile.data_aggregation");
  assert.ok(Object.hasOwn(STUDIO_ICONS, STUDIO_TYPE_STYLE.data_aggregation.icon));
  assert.ok(STUDIO_MESSAGES["studio.tile.hint.data_aggregation"]);
});

test("데이터 집계 문구 키가 정해진 글자 그대로 있다", () => {
  const expected = {
    "studio.tile.data_aggregation": "데이터 집계",
    "studio.aggregation.request": "요청 글",
    "studio.aggregation.source": "표 소스",
    "studio.aggregation.sheet": "시트",
    "studio.aggregation.header_row": "머리글 행",
    "studio.aggregation.computed": "계산값",
    "studio.aggregation.not_computable": "계산 불가",
    "studio.aggregation.conditions": "적용한 조건",
    "studio.aggregation.evidence": "계산 근거",
    "studio.aggregation.skipped": "하지 않은 요청",
    "studio.progress.aggregation.read": "표 읽는 중",
    "studio.progress.aggregation.spec": "집계 조건 만드는 중",
    "studio.progress.aggregation.compute": "계산 중",
    "source.aggregation_only": "집계 전용",
  };
  for (const [key, text] of Object.entries(expected)) assert.equal(STUDIO_MESSAGES[key], text, key);
});

test("작업 6 오류 코드마다 한국어 문구가 있다", () => {
  for (const code of ["STUDIO_SOURCE_UNAVAILABLE", "TABLE_TOO_LARGE", "TABLE_TIMEOUT", "TABLE_SHEET_NOT_FOUND", "TABLE_HEADER_INVALID",
    "TABLE_FORMAT_UNSUPPORTED", "TABLE_ENCODING_UNSUPPORTED", "AGGREGATION_UNSUPPORTED", "AGGREGATION_TOO_LARGE", "AGGREGATION_TOO_MANY_GROUPS",
    "AGGREGATION_FILTER_VALUE_NOT_FOUND", "STUDIO_SERVICE_UNAVAILABLE"]) {
    assert.ok(STUDIO_ERRORS[code], code);
    assert.equal(studioErrorMessage(code), STUDIO_ERRORS[code]);
  }
  assert.equal(STUDIO_ERRORS.AGGREGATION_UNSUPPORTED, "이 요청은 데이터 집계 1차 범위에서 할 수 없습니다");
  assert.equal(STUDIO_ERRORS.AGGREGATION_TOO_LARGE, "결과가 너무 큽니다. 조건을 좁혀 다시 생성해 주세요");
  assert.equal(STUDIO_ERRORS.AGGREGATION_FILTER_VALUE_NOT_FOUND, "필터 값이 표에 없습니다");
});

test("진행 메모 세 단계가 카드 문구 키로 바뀌고, 다른 메모·유형은 null이다", () => {
  const out = (note, type_id = "data_aggregation", status = "generating") => ({ type_id, status, progress: { pct: 30, note } });
  assert.equal(progressNoteKey(out("표 읽는 중")), "studio.progress.aggregation.read");
  assert.equal(progressNoteKey(out("집계 조건 만드는 중")), "studio.progress.aggregation.spec");
  assert.equal(progressNoteKey(out("계산 중")), "studio.progress.aggregation.compute");
  assert.equal(progressNoteKey(out("다른 메모")), null);
  assert.equal(progressNoteKey(out("계산 중", "data_aggregation", "completed")), null);
  assert.equal(progressNoteKey(out("계산 중", "report")), null);
  assert.equal(progressNoteKey(out("페이지 만드는 중", "web_page")), "studio.progress.web_page.html");
});

test("표 소스는 처리 완료된 XLSX·CSV만 고를 수 있다", () => {
  const sources = [
    { sourceVersionId: "v1", filename: "청구.xlsx", ready: true },
    { sourceVersionId: "v2", filename: "목록.CSV", ready: true },
    { sourceVersionId: "v3", filename: "약관.pdf", ready: true },
    { sourceVersionId: "v4", filename: "대기.xlsx", ready: false },
    { sourceVersionId: "v5", filename: "xlsx", ready: true },
  ];
  assert.deepEqual(tableSources(sources).map((s) => s.sourceVersionId), ["v1", "v2"]);
  assert.equal(needsSettingsDialog({ settings_schema: { properties: { aggregation_request: {} } } }), true);
  assert.equal(needsSettingsDialog({ settings_schema: { properties: { page_request: {} } } }), true);
  assert.equal(needsSettingsDialog({ settings_schema: { properties: { focus: {} } } }), false);
});

// ---------------------------------------------------------------- 실제 렌더(vite 묶음 + 최소 DOM)
async function bundle(entry, name) {
  const output = await mkdtemp(path.join(root, `.${name}-`));
  const { build } = await import("vite");
  await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
    lib: { entry: path.join(root, entry), formats: ["es"], fileName: name },
    rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
  const built = (await readdir(output)).find((file) => file.startsWith(name) && /\.m?js$/u.test(file));
  const module = await import(`${pathToFileURL(path.join(output, built)).href}?v=${Date.now()}`);
  return { module, cleanup: () => rm(output, { recursive: true, force: true }) };
}

async function mount(Component, props) {
  const dom = installMinimalDom();
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(Component, props)); });
  await wait(15);
  return { dom, container, click: (node) => act(async () => { node.dispatchEvent(new MinimalEvent("click")); }),
    rerender: (next) => act(async () => { reactRoot.render(createElement(Component, next)); }),
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); } };
}

const AGG_SCHEMA = { type: "object", properties: { language: {}, focus: {}, aggregation_request: { type: "string", maxLength: 2000 },
  table_source_version_id: { type: "string" }, sheet: { type: "string" }, header_row: { type: "integer", minimum: 1, maximum: 50 } } };
const TYPES = [
  { type_id: "report", available: true, formats: [], presets: [], export_formats: ["docx"], default_format: null, settings_schema: { type: "object", properties: { focus: {} } } },
  { type_id: "data_aggregation", available: true, formats: [], presets: [], export_formats: ["xlsx", "csv"], default_format: null, settings_schema: AGG_SCHEMA },
];
const SOURCES = [
  { sourceVersionId: "ver-xlsx", filename: "청구.xlsx", ready: true },
  { sourceVersionId: "ver-csv", filename: "목록.csv", ready: true },
  { sourceVersionId: "ver-pdf", filename: "약관.pdf", ready: true },
];
const aggItem = (over = {}) => ({ output_id: OID("d"), type_id: "data_aggregation", format_id: null, title: "데이터 집계", status: "completed", error_code: null,
  source_count: 1, current_revision: 1, created_at: "2026-11-20T00:00:00Z", updated_at: "2026-11-20T00:00:00Z", stale: false, ...over });

function fakeStudio({ outputs = [], settings = {}, profile } = {}) {
  const calls = [];
  return {
    calls,
    listTypes: async () => TYPES,
    listOutputs: async () => ({ items: outputs.slice(), nextCursor: null }),
    exportFormats: (typeId) => (typeId === "data_aggregation" ? ["xlsx", "csv"] : ["docx"]),
    createOutput: async (args) => { calls.push(["create", args]); return { output_id: OID("e"), job_id: "svj-1", status: "queued" }; },
    regenerateOutput: async (id, opts) => { calls.push(["regenerate", id, opts]); return { output_id: id, job_id: "svj-2", status: "queued" }; },
    getOutput: async (id) => { calls.push(["getOutput", id]); return { ...aggItem({ output_id: id }), settings, evidence: [], assets: [], revision: null }; },
    getTableProfile: async (params) => {
      calls.push(["profile", params]);
      if (profile) return profile(params);
      return params.sourceVersionId === "ver-xlsx"
        ? { sheets: ["청구내역", "요약"], columns: [{ name: "상품", kind: "text" }, { name: "지급액", kind: "number" }], row_count: 120 }
        : { sheets: [], columns: [{ name: "상품", kind: "text" }], row_count: 10 };
    },
  };
}

const panelProps = (studio) => ({ studio, sources: SOURCES, sourceStats: { sourceCount: 3, checkedCount: 3, readySourceCount: 3, processingCount: 0 },
  checkedSourceVersionIds: ["ver-xlsx", "ver-csv", "ver-pdf"] });
const byId = (container, id) => findElements(container, (n) => n.getAttribute?.("id") === id)[0];
const submitButton = (container) => findElements(container, (n) => n.tagName === "BUTTON" && n.getAttribute("type") === "submit")[0];

test("타일을 누르면 설정 창이 열리고(바로 만들지 않음) 표 소스는 XLSX·CSV만, 시트는 표 정보에서 불러오며 요청 글은 필수 2000자다", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-panel.jsx", "studio-panel-aggregation");
  const studio = fakeStudio();
  const view = await mount(module.StudioPanel, panelProps(studio));
  try {
    const tile = findElements(view.container, (n) => n.getAttribute?.("aria-label") === "데이터 집계")[0];
    assert.ok(tile);
    await view.click(tile);
    assert.equal(studio.calls.filter(([kind]) => kind === "create").length, 0, "타일만 눌러서는 만들지 않는다");
    const dialog = findElements(view.container, (n) => n.getAttribute?.("role") === "dialog")[0];
    assert.ok(dialog, "설정 창이 열린다");
    const select = byId(dialog, "studio-aggregation-source");
    const options = findElements(select, (n) => n.tagName === "OPTION").map((n) => n.getAttribute("value"));
    assert.deepEqual(options, ["ver-xlsx", "ver-csv"]);
    const request = byId(dialog, "studio-aggregation-request");
    assert.equal(reactProps(request).maxLength, 2000);
    assert.equal(reactProps(request).required, true);
    assert.equal(reactProps(submitButton(dialog)).disabled, true, "표 정보를 읽는 동안·요청 글이 비면 꺼진다");
    await wait(400);
    const profileCalls = studio.calls.filter(([kind]) => kind === "profile");
    assert.deepEqual(profileCalls[0][1], { sourceVersionId: "ver-xlsx", sheet: undefined, headerRow: 1 });
    await wait(400);
    assert.equal(studio.calls.filter(([kind]) => kind === "profile").length, 1, "첫 시트를 고른 것으로 보여도 다시 읽지 않는다");
    const sheet = byId(dialog, "studio-aggregation-sheet");
    assert.deepEqual(findElements(sheet, (n) => n.tagName === "OPTION").map((n) => n.getAttribute("value")), ["청구내역", "요약"]);
    assert.ok(dialog.textContent.includes("열 2개 · 행 120개"));
    assert.equal(reactProps(submitButton(dialog)).disabled, true, "요청 글이 비면 꺼진다");
    await act(async () => { reactProps(request).onChange({ target: { value: "   " } }); });
    assert.equal(reactProps(submitButton(dialog)).disabled, true);
    await act(async () => { reactProps(request).onChange({ target: { value: " 상품별 지급액 합계 " } }); });
    await act(async () => { reactProps(byId(dialog, "studio-aggregation-sheet")).onChange({ target: { value: "요약" } }); });
    await wait(400);
    assert.deepEqual(studio.calls.filter(([kind]) => kind === "profile").at(-1)[1], { sourceVersionId: "ver-xlsx", sheet: "요약", headerRow: 1 });
    await act(async () => { reactProps(byId(dialog, "studio-aggregation-header-row")).onChange({ target: { value: "3" } }); });
    await wait(400);
    assert.equal(reactProps(submitButton(dialog)).disabled, false);
    const form = findElements(dialog, (n) => n.tagName === "FORM")[0];
    await act(async () => { reactProps(form).onSubmit({ preventDefault() {} }); });
    await wait(15);
    const create = studio.calls.find(([kind]) => kind === "create");
    assert.deepEqual(create[1], { typeId: "data_aggregation", formatId: undefined,
      settings: { aggregation_request: "상품별 지급액 합계", table_source_version_id: "ver-xlsx", sheet: "요약", header_row: 3 },
      sourceVersionIds: ["ver-xlsx"] });
  } finally { await view.close(); await cleanup(); }
});

test("CSV는 시트 칸이 없고, 표 정보 오류는 오류 표 문구와 다시 읽기를 보인다", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-panel.jsx", "studio-panel-aggregation-csv");
  let busy = true;
  const studio = fakeStudio({ profile: () => { if (busy) { const error = new Error("busy"); error.code = "STUDIO_SERVICE_UNAVAILABLE"; throw error; } return { sheets: [], columns: [], row_count: 0 }; } });
  const view = await mount(module.StudioPanel, panelProps(studio));
  try {
    await view.click(findElements(view.container, (n) => n.getAttribute?.("aria-label") === "데이터 집계")[0]);
    const dialog = findElements(view.container, (n) => n.getAttribute?.("role") === "dialog")[0];
    await act(async () => { reactProps(byId(dialog, "studio-aggregation-source")).onChange({ target: { value: "ver-csv" } }); });
    await wait(400);
    assert.equal(byId(dialog, "studio-aggregation-sheet"), undefined);
    const alert = findElements(dialog, (n) => n.getAttribute?.("role") === "alert")[0];
    assert.ok(alert.textContent.includes(STUDIO_ERRORS.STUDIO_SERVICE_UNAVAILABLE));
    busy = false;
    await view.click(findElements(alert, (n) => n.tagName === "BUTTON")[0]);
    await wait(400);
    assert.equal(findElements(dialog, (n) => n.getAttribute?.("role") === "alert").length, 0);
    await act(async () => { reactProps(byId(dialog, "studio-aggregation-request")).onChange({ target: { value: "건수" } }); });
    await act(async () => { reactProps(findElements(dialog, (n) => n.tagName === "FORM")[0]).onSubmit({ preventDefault() {} }); });
    await wait(15);
    const create = studio.calls.find(([kind]) => kind === "create");
    assert.deepEqual(create[1].settings, { aggregation_request: "건수", table_source_version_id: "ver-csv", sheet: "", header_row: 1 });
  } finally { await view.close(); await cleanup(); }
});

test("설정 변경 후 다시 생성은 출력 상세의 지난 요청·소스·시트·머리글 행을 채운다", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-panel.jsx", "studio-panel-aggregation-regen");
  const studio = fakeStudio({ outputs: [aggItem()], settings: { aggregation_request: "지난 요청", table_source_version_id: "ver-xlsx", sheet: "요약", header_row: 2 } });
  const view = await mount(module.StudioPanel, panelProps(studio));
  try {
    await view.click(findElements(view.container, (n) => n.getAttribute?.("aria-label") === "더보기: 데이터 집계")[0]);
    const menu = findElements(view.container, (n) => n.getAttribute?.("role") === "menu")[0];
    await view.click(findElements(menu, (n) => n.getAttribute?.("role") === "menuitem" && n.textContent.trim() === "설정 변경 후 다시 생성")[0]);
    await wait(450);
    assert.ok(studio.calls.some(([kind, id]) => kind === "getOutput" && id === OID("d")));
    const dialog = findElements(view.container, (n) => n.getAttribute?.("role") === "dialog")[0];
    assert.equal(reactProps(byId(dialog, "studio-aggregation-request")).value, "지난 요청");
    assert.equal(reactProps(byId(dialog, "studio-aggregation-source")).value, "ver-xlsx");
    assert.equal(reactProps(byId(dialog, "studio-aggregation-sheet")).value, "요약");
    assert.equal(reactProps(byId(dialog, "studio-aggregation-header-row")).value, "2");
    assert.deepEqual(studio.calls.filter(([kind]) => kind === "profile").at(-1)[1], { sourceVersionId: "ver-xlsx", sheet: "요약", headerRow: 2 });
    await act(async () => { reactProps(findElements(dialog, (n) => n.tagName === "FORM")[0]).onSubmit({ preventDefault() {} }); });
    await wait(15);
    const regen = studio.calls.find(([kind]) => kind === "regenerate");
    assert.deepEqual(regen[2], { settings: { aggregation_request: "지난 요청", table_source_version_id: "ver-xlsx", sheet: "요약", header_row: 2 } });
  } finally { await view.close(); await cleanup(); }
});

// ---------------------------------------------------------------- 보기
const cell = (value, display, extra = {}) => ({ value, display, computed: false, status: "ok", reason: null, evidence_id: null, ...extra });
const comp = (value, display, evidence_id, extra = {}) => cell(value, display, { computed: true, evidence_id, ...extra });
const MANY = Array.from({ length: 6 }, (_, i) => `청구내역!F${i * 10 + 2}:F${i * 10 + 5}`);
const BODY = {
  request: "월별 지급액", source: { source_version_id: "ver-xlsx", sha256: "a".repeat(64), file_name: "청구.xlsx", sheet: "청구내역", header_row: 1 },
  spec: {}, spec_raw: {}, conditions_text: "묶기: 상품 · 집계: 합계(지급액)",
  columns: [{ key: "상품", label: "상품", role: "group" }, { key: "m1", label: "지급액 합계", role: "measure" }],
  rows: [
    [cell("암보험", "암보험"), comp("1234.50", "1,234.50", "e1")],
    [cell("실손", "실손"), comp(null, "계산 불가", "e2", { status: "not_computable", reason: "숫자 값 없음" })],
    [cell("종신", "종신"), comp("-20", "-20", "e3")],
  ],
  evidence: {
    e1: { ranges: MANY, filter_text: "상품 = 암보험", formula: "지급액 합계 = 숫자 46개의 합", row_count: 46, excluded: { not_number: 2, blank: 1 } },
    e2: { ranges: [], filter_text: "상품 = 실손", formula: "지급액 합계 = 숫자 0개의 합", row_count: 0, excluded: { not_number: 3, blank: 0 } },
    e3: { ranges: ["청구내역!F7"], filter_text: "상품 = 종신", formula: "지급액 합계 = 숫자 1개의 합", row_count: 1, excluded: { not_number: 0, blank: 0 } },
  },
  chart: { kind: "bar", x_key: "상품", x_label: "상품", series: [{ key: "m1", label: "지급액 합계", points: [{ x: "암보험", value: "1234.50" }, { x: "실손", value: null }, { x: "종신", value: "-20" }] }] },
  summary: ["지급액 합계 가장 큰 묶음: 암보험 (1,234.50)"],
  warnings: ["하지 않은 요청: 다른 파일과 비교", "지급액 합계: 빈칸 1행 제외"],
  stats: { rows_read: 120, elapsed_ms: 10 },
};

test("보기: 계산값 칸에 계산값 표지, 계산 불가는 이유, 칸을 누르면 근거 칸에 범위·필터·식·행 수", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-data-aggregation-viewer.jsx", "studio-aggregation-viewer");
  const view = await mount(module.DataAggregationViewer, { content: { body: BODY } });
  try {
    const text = view.container.textContent;
    assert.ok(text.includes("적용한 조건") && text.includes("묶기: 상품 · 집계: 합계(지급액)"));
    assert.ok(text.includes("하지 않은 요청") && text.includes("다른 파일과 비교"));
    assert.ok(text.includes("빈칸 1행 제외"));
    assert.ok(text.includes("지급액 합계 가장 큰 묶음: 암보험 (1,234.50)"));
    const computed = findElements(view.container, (n) => n.tagName === "TD" && n.getAttribute("data-computed") === "true");
    assert.equal(computed.length, 3);
    for (const td of computed) assert.ok(td.textContent.includes("계산값"), td.textContent);
    assert.ok(computed[0].textContent.includes("1,234.50"));
    assert.ok(computed[1].textContent.includes("계산 불가") && computed[1].textContent.includes("숫자 값 없음"));
    const originals = findElements(view.container, (n) => n.tagName === "TD" && n.getAttribute("data-computed") === "false");
    for (const td of originals) assert.ok(!td.textContent.includes("계산값"));
    const pane = findElements(view.container, (n) => n.tagName === "ASIDE")[0];
    assert.ok(pane.textContent.includes("계산값 칸을 누르면"));

    await view.click(findElements(computed[0], (n) => n.tagName === "BUTTON")[0]);
    let evidence = findElements(pane, (n) => n.getAttribute?.("data-evidence-cell") !== null && n.getAttribute?.("data-evidence-cell") !== undefined)[0];
    assert.equal(evidence.getAttribute("data-evidence-id"), "e1");
    assert.ok(pane.textContent.includes("상품 = 암보험"));
    assert.ok(pane.textContent.includes("지급액 합계 = 숫자 46개의 합"));
    assert.equal(findElements(pane, (n) => n.getAttribute?.("data-row-count") === "")[0].textContent, "46");
    assert.ok(pane.textContent.includes("숫자 아님 2개, 빈칸 1개"));
    assert.ok(pane.textContent.includes("청구.xlsx"));
    // 범위가 길면 묶음 수만 보이고 펼쳐서 전체를 본다.
    assert.ok(pane.textContent.includes("범위 6묶음"));
    assert.ok(!pane.textContent.includes(MANY[5]));
    await view.click(findElements(pane, (n) => n.tagName === "BUTTON" && n.textContent === "펼치기")[0]);
    for (const range of MANY) assert.ok(pane.textContent.includes(range), range);

    await view.click(findElements(computed[1], (n) => n.tagName === "BUTTON")[0]);
    evidence = findElements(pane, (n) => n.getAttribute?.("data-evidence-id") === "e2")[0];
    assert.ok(evidence.textContent.includes("계산 불가") && evidence.textContent.includes("숫자 값 없음"));
    assert.ok(evidence.textContent.includes("상품 = 실손"));

    await view.click(findElements(originals[0], (n) => n.tagName === "BUTTON")[0]);
    assert.ok(pane.textContent.includes("원본값"));
  } finally { await view.close(); await cleanup(); }
});

test("차트 SVG가 chart.series 값과 같다(막대·선), 계산 불가는 빈 막대·끊긴 점과 범례 문구", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-data-aggregation-viewer.jsx", "studio-aggregation-chart");
  try {
    const view = await mount(module.DataAggregationViewer, { content: { body: BODY } });
    try {
      const svg = findElements(view.container, (n) => n.tagName === "svg" || n.tagName === "SVG")[0];
      assert.ok(svg, "SVG 차트가 있다");
      const marks = findElements(svg, (n) => (n.tagName === "rect" || n.tagName === "RECT") && n.getAttribute("data-series") !== null);
      const points = BODY.chart.series[0].points;
      assert.equal(marks.length, points.length);
      assert.deepEqual(marks.map((n) => n.getAttribute("data-x")), points.map((p) => p.x));
      assert.deepEqual(marks.filter((n) => n.getAttribute("data-empty") !== "true").map((n) => n.getAttribute("data-value")), points.filter((p) => p.value !== null).map((p) => p.value));
      assert.equal(marks[1].getAttribute("data-empty"), "true");
      // 말풍선 글자는 집계표의 표시 문자열을 쓴다(화면이 숫자를 새로 만들지 않는다).
      assert.ok(marks[0].textContent.includes("1,234.50"), marks[0].textContent);
      assert.ok(view.container.textContent.includes("계산 불가"));
      assert.ok(findElements(view.container, (n) => n.getAttribute?.("data-gap") === "true").length === 1);
      assert.equal(findElements(view.container, (n) => n.tagName === "IMG" || n.tagName === "IFRAME" || n.tagName === "SCRIPT").length, 0);
    } finally { await view.close(); }

    const line = { ...BODY, columns: [{ key: "월", label: "월", role: "group" }, { key: "상품", label: "상품", role: "group" }, { key: "m1", label: "건수", role: "measure" }],
      rows: [[cell("2026-01", "2026-01"), cell("암", "암"), comp("3", "3", "e1")], [cell("2026-02", "2026-02"), cell("암", "암"), comp("5", "5", "e1")],
        [cell("2026-01", "2026-01"), cell("실손", "실손"), comp("7", "7", "e1")]],
      chart: { kind: "line", x_key: "월", x_label: "월", series: [
        { key: "암", label: "암", points: [{ x: "2026-01", value: "3" }, { x: "2026-02", value: "5" }] },
        { key: "실손", label: "실손", points: [{ x: "2026-01", value: "7" }, { x: "2026-02", value: null }] }] } };
    const model = module.chartModel(line.chart);
    assert.deepEqual(model.marks.filter((m) => !m.empty).map((m) => m.value), ["3", "5", "7"]);
    assert.equal(model.gap, true);
    const lineView = await mount(module.DataAggregationViewer, { content: { body: line } });
    try {
      const circles = findElements(lineView.container, (n) => (n.tagName === "circle" || n.tagName === "CIRCLE"));
      assert.deepEqual(circles.map((n) => n.getAttribute("data-value")), ["3", "5", "7"]);
      assert.ok(circles[2].textContent.includes("실손") && circles[2].textContent.includes("7"));
      assert.equal(findElements(lineView.container, (n) => (n.tagName === "polyline" || n.tagName === "POLYLINE")).length, 2);
    } finally { await lineView.close(); }
  } finally { await cleanup(); }
});

test("보기 칸은 각자 min-height:0; overflow:auto이고 820px 이하에서는 위아래로 놓인다", async () => {
  const css = await read("packages/ui/src/studio-panel.css");
  assert.match(css, /\.studio-aggregation__main, \.studio-aggregation__evidence \{ min-height: 0; overflow: auto; \}/u);
  assert.match(css, /\.studio-aggregation__table \{[^}]*min-height: 0; overflow: auto;/u);
  const narrow = css.slice(css.indexOf("@media (max-width: 820px)"));
  assert.match(narrow.slice(0, narrow.indexOf("@container")), /\.studio-aggregation \{ grid-template-columns: minmax\(0, 1fr\); grid-template-rows:/u);
  assert.match(css, /\.studio-detail__body--aggregation \{ display: flex; flex-direction: column; gap: 12px; overflow: hidden; \}/u);
  const panel = await read("packages/ui/src/studio-panel.jsx");
  assert.match(panel, /studio-detail__body--aggregation/u);
  assert.match(await read("packages/ui/src/studio-viewers.jsx"), /case "data_aggregation": return <DataAggregationViewer/u);
  assert.doesNotMatch(await read("packages/ui/src/studio-data-aggregation-viewer.jsx"), /dangerouslySetInnerHTML|https?:\/\//u);
});

test("소스 목록에 집계 전용 표지를 보인다", async () => {
  const shell = await read("packages/ui/src/product-workspace-shell.jsx");
  assert.match(shell, /\{source\.aggregationOnly && <AggregationOnlyBadge \/>\}/u);
  const { module, cleanup } = await bundle("packages/ui/src/studio-data-aggregation-viewer.jsx", "studio-aggregation-badge");
  try {
    const view = await mount(module.AggregationOnlyBadge, {});
    try { assert.equal(view.container.textContent, "집계 전용"); } finally { await view.close(); }
  } finally { await cleanup(); }
});

// ---------------------------------------------------------------- BFF·어댑터
const COOKIE = "__Host-daon_session=opaque-session";
const ORIGIN = "https://app.example.com";
const BASE = ["workspaces", "workspace-1", "notebooks", "notebook-1", "studio"];
const URL_BASE = `${ORIGIN}/bff/api/workspaces/workspace-1/notebooks/notebook-1/studio`;

test("BFF는 table-profile에 허용한 쿼리 3개 외에는 400", async () => {
  const captured = [];
  const proxy = createBffProxy({ baseUrl: new URL("https://api.example.com"), publicOrigin: new URL(ORIGIN),
    fetchImpl: async (url, init) => { captured.push({ url: String(url), method: init.method }); return Response.json({ data: {}, meta: {} }); } });
  const get = (query, method = "GET") => proxy(new Request(`${URL_BASE}/table-profile${query}`, { method, headers: { Cookie: COOKIE } }), [...BASE, "table-profile"]);
  const sheet = encodeURIComponent("청구내역");
  for (const query of ["?source_version_id=ver-1", `?source_version_id=ver-1&sheet=${sheet}&header_row=3`, "?source_version_id=ver-1&header_row=50"]) {
    const response = await get(query);
    assert.equal(response.status, 200, query);
    assert.equal(captured.at(-1).url, `https://api.example.com/api/v1/workspaces/workspace-1/notebooks/notebook-1/studio/table-profile${query}`);
  }
  const count = captured.length;
  for (const query of ["", "?sheet=a", "?source_version_id=ver-1&limit=1", "?source_version_id=ver-1&source_version_id=ver-2",
    "?source_version_id=ver-1&header_row=0", "?source_version_id=ver-1&header_row=51", "?source_version_id=ver-1&header_row=01", "?source_version_id=ver-1&header_row=x",
    `?source_version_id=ver-1&sheet=${"a".repeat(121)}`, "?source_version_id=ver-1&sheet=", "?source_version_id=bad%20id",
    "?source_version_id=ver-1&header_row=1&header_row=2", "?source_version_id=ver-1&sheet=a&sheet=b"]) {
    assert.equal((await get(query)).status, 400, query);
  }
  assert.equal(captured.length, count);
  assert.notEqual((await get("?source_version_id=ver-1", "DELETE")).status, 200);
  assert.equal(captured.length, count);
});

const okFetch = (data, calls = []) => async (url, init) => { calls.push({ url: String(url), init }); return Response.json({ data, meta: { trace_id: "t" } }); };

test("어댑터 표 정보 조회는 쿼리를 만들고 응답 모양을 정확한 키로 검사한다", async () => {
  const calls = [];
  const good = { sheets: ["청구내역"], columns: [{ name: "상품", kind: "text" }, { name: "지급일", kind: "date" }], row_count: 3 };
  const data = await getStudioTableProfile("ws-1", { notebookId: "nb-1", sourceVersionId: "ver-1", sheet: "청구내역", headerRow: 2, fetchImpl: okFetch(good, calls) });
  assert.deepEqual(data, good);
  assert.equal(calls[0].url, `/bff/api/workspaces/ws-1/notebooks/nb-1/studio/table-profile?source_version_id=ver-1&sheet=${encodeURIComponent("청구내역")}&header_row=2`);
  assert.equal(calls[0].init.method, "GET");
  const noSheet = [];
  await getStudioTableProfile("ws-1", { notebookId: "nb-1", sourceVersionId: "ver-1", fetchImpl: okFetch(good, noSheet) });
  assert.equal(noSheet[0].url, "/bff/api/workspaces/ws-1/notebooks/nb-1/studio/table-profile?source_version_id=ver-1&header_row=1");
  for (const bad of [{ ...good, extra: 1 }, { sheets: [], columns: [{ name: "a", kind: "money" }], row_count: 1 }, { sheets: [], columns: [{ name: "a", kind: "text", sample: "값" }], row_count: 1 },
    { sheets: [], columns: [], row_count: -1 }, { sheets: [1], columns: [], row_count: 0 }, { columns: [], row_count: 0 }]) {
    await assert.rejects(getStudioTableProfile("ws-1", { notebookId: "nb-1", sourceVersionId: "ver-1", fetchImpl: okFetch(bad) }), (e) => e.code === "STUDIO_RESPONSE_INVALID", JSON.stringify(bad));
  }
  for (const input of [{ sourceVersionId: "bad id" }, { sourceVersionId: "ver-1", headerRow: 0 }, { sourceVersionId: "ver-1", headerRow: 51 }, { sourceVersionId: "ver-1", sheet: "a".repeat(121) }]) {
    await assert.rejects(getStudioTableProfile("ws-1", { notebookId: "nb-1", fetchImpl: okFetch(good), ...input }), (e) => e.code === "STUDIO_INPUT_INVALID", JSON.stringify(input));
  }
  const busy = async () => Response.json({ error: { code: "STUDIO_SERVICE_UNAVAILABLE" } }, { status: 503 });
  await assert.rejects(getStudioTableProfile("ws-1", { notebookId: "nb-1", sourceVersionId: "ver-1", fetchImpl: busy }), (e) => e.code === "STUDIO_SERVICE_UNAVAILABLE" && e.status === 503);
  const adapter = createStudioV2Adapter("ws-1", "nb-1", { fetchImpl: okFetch(good) });
  assert.deepEqual(await adapter.getTableProfile({ sourceVersionId: "ver-1" }), good);
});

test("데이터 집계 출력 상세는 웹 어댑터 검사를 통과한다", async () => {
  const detail = { ...aggItem(), progress: null, settings: { aggregation_request: "요청", table_source_version_id: "ver-1", header_row: 1 },
    revision: { revision_no: 1, content: { schema: "studio.data_aggregation.v1", language: "ko", body: BODY, warnings: [] } }, evidence: [], assets: [] };
  const data = await getStudioOutput("ws-1", OID("d"), { notebookId: "nb-1", fetchImpl: okFetch(detail) });
  assert.equal(data.revision.content.body.chart.kind, "bar");
});

// ---------------------------------------------------------------- 검토 보강 1차
const openAggregationDialog = async (view) => {
  await view.click(findElements(view.container, (n) => n.getAttribute?.("aria-label") === "데이터 집계")[0]);
  return findElements(view.container, (n) => n.getAttribute?.("role") === "dialog")[0];
};

test("고른 시트가 표가 아니면(TABLE_* error_code) 시트 목록은 남고 다른 시트로 바꿀 수 있으며, 그동안 만들기가 꺼진다", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-panel.jsx", "studio-panel-aggregation-sheet-error");
  const studio = fakeStudio({ profile: ({ sheet }) => (!sheet || sheet === "표지"
    ? { sheets: ["표지", "청구"], columns: [], row_count: 0, error_code: "TABLE_HEADER_INVALID" }
    : { sheets: ["표지", "청구"], columns: [{ name: "상품", kind: "text" }], row_count: 5 }) });
  const view = await mount(module.StudioPanel, panelProps(studio));
  try {
    const dialog = await openAggregationDialog(view);
    await act(async () => { reactProps(byId(dialog, "studio-aggregation-request")).onChange({ target: { value: "건수" } }); });
    await wait(400);
    await wait(400);
    const alert = findElements(dialog, (n) => n.getAttribute?.("role") === "alert")[0];
    assert.ok(alert && alert.textContent.includes(STUDIO_ERRORS.TABLE_HEADER_INVALID), alert?.textContent);
    const sheet = byId(dialog, "studio-aggregation-sheet");
    assert.equal(reactProps(sheet).disabled, false, "시트 목록이 있으면 시트 칸은 켜져 있다");
    assert.deepEqual(findElements(sheet, (n) => n.tagName === "OPTION").map((n) => n.getAttribute("value")), ["표지", "청구"]);
    assert.equal(reactProps(submitButton(dialog)).disabled, true, "TABLE_* 오류가 있으면 만들기가 꺼진다");
    await act(async () => { reactProps(sheet).onChange({ target: { value: "청구" } }); });
    await wait(400);
    assert.equal(findElements(dialog, (n) => n.getAttribute?.("role") === "alert").length, 0);
    assert.ok(dialog.textContent.includes("열 1개 · 행 5개"));
    assert.equal(reactProps(submitButton(dialog)).disabled, false);
    assert.deepEqual(studio.calls.filter(([kind]) => kind === "profile").at(-1)[1], { sourceVersionId: "ver-xlsx", sheet: "청구", headerRow: 1 });
  } finally { await view.close(); await cleanup(); }
});

test("표 정보 503(바쁨)은 다시 읽기만 보이고 만들기는 끄지 않는다, 오류 응답 뒤에도 시트 목록은 남는다", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-panel.jsx", "studio-panel-aggregation-busy");
  let busy = false;
  const studio = fakeStudio({ profile: () => {
    if (busy) { const error = new Error("busy"); error.code = "STUDIO_SERVICE_UNAVAILABLE"; throw error; }
    return { sheets: ["청구내역", "요약"], columns: [{ name: "상품", kind: "text" }], row_count: 3 };
  } });
  const view = await mount(module.StudioPanel, panelProps(studio));
  try {
    const dialog = await openAggregationDialog(view);
    await act(async () => { reactProps(byId(dialog, "studio-aggregation-request")).onChange({ target: { value: "건수" } }); });
    await wait(400);
    busy = true;
    await act(async () => { reactProps(byId(dialog, "studio-aggregation-sheet")).onChange({ target: { value: "요약" } }); });
    await wait(400);
    const alert = findElements(dialog, (n) => n.getAttribute?.("role") === "alert")[0];
    assert.ok(alert.textContent.includes(STUDIO_ERRORS.STUDIO_SERVICE_UNAVAILABLE));
    assert.ok(findElements(alert, (n) => n.tagName === "BUTTON").length === 1);
    const sheet = byId(dialog, "studio-aggregation-sheet");
    assert.deepEqual(findElements(sheet, (n) => n.tagName === "OPTION").map((n) => n.getAttribute("value")), ["청구내역", "요약"]);
    assert.equal(reactProps(sheet).disabled, false);
    assert.equal(reactProps(submitButton(dialog)).disabled, false, "바쁨(503)은 만들기를 끄지 않는다");
  } finally { await view.close(); await cleanup(); }
});

test("설정 변경 후 다시 생성에서는 표 소스를 바꿀 수 없다(지금 소스를 보이고 잠근다)", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-panel.jsx", "studio-panel-aggregation-lock");
  const studio = fakeStudio({ outputs: [aggItem()], settings: { aggregation_request: "지난 요청", table_source_version_id: "ver-csv", header_row: 1 } });
  const view = await mount(module.StudioPanel, panelProps(studio));
  try {
    await view.click(findElements(view.container, (n) => n.getAttribute?.("aria-label") === "더보기: 데이터 집계")[0]);
    const menu = findElements(view.container, (n) => n.getAttribute?.("role") === "menu")[0];
    await view.click(findElements(menu, (n) => n.getAttribute?.("role") === "menuitem" && n.textContent.trim() === "설정 변경 후 다시 생성")[0]);
    await wait(450);
    const dialog = findElements(view.container, (n) => n.getAttribute?.("role") === "dialog")[0];
    const select = byId(dialog, "studio-aggregation-source");
    assert.equal(reactProps(select).disabled, true);
    assert.equal(reactProps(select).value, "ver-csv");
  } finally { await view.close(); }
  // 새로 만들 때는 바꿀 수 있다.
  const fresh = await mount(module.StudioPanel, panelProps(fakeStudio()));
  try {
    const dialog = await openAggregationDialog(fresh);
    assert.notEqual(reactProps(byId(dialog, "studio-aggregation-source")).disabled, true);
  } finally { await fresh.close(); await cleanup(); }
});

test("보기: 내용(판)이 바뀌면 고른 칸을 지운다", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/studio-data-aggregation-viewer.jsx", "studio-aggregation-reset");
  const view = await mount(module.DataAggregationViewer, { content: { body: BODY } });
  try {
    const td = findElements(view.container, (n) => n.tagName === "TD" && n.getAttribute("data-computed") === "true")[0];
    await view.click(findElements(td, (n) => n.tagName === "BUTTON")[0]);
    const pane = () => findElements(view.container, (n) => n.tagName === "ASIDE")[0];
    assert.ok(findElements(pane(), (n) => n.getAttribute?.("data-evidence-id") === "e1").length === 1);
    await view.rerender({ content: { body: { ...BODY, evidence: { ...BODY.evidence } } } });
    assert.ok(pane().textContent.includes("계산값 칸을 누르면"), pane().textContent);
    assert.equal(findElements(view.container, (n) => n.getAttribute?.("aria-pressed") === "true").length, 0);
  } finally { await view.close(); await cleanup(); }
});

test("어댑터 표 정보 검사는 선택 error_code(코드 문자열)를 받는다", async () => {
  const good = { sheets: ["표지", "청구"], columns: [], row_count: 0, error_code: "TABLE_HEADER_INVALID" };
  assert.deepEqual(await getStudioTableProfile("ws-1", { notebookId: "nb-1", sourceVersionId: "ver-1", fetchImpl: okFetch(good) }), good);
  for (const bad of [{ ...good, error_code: 3 }, { ...good, error_code: "table bad" }, { ...good, error_code: null }]) {
    await assert.rejects(getStudioTableProfile("ws-1", { notebookId: "nb-1", sourceVersionId: "ver-1", fetchImpl: okFetch(bad) }), (e) => e.code === "STUDIO_RESPONSE_INVALID", JSON.stringify(bad));
  }
});

test("OpenAPI 계약의 표 정보에 선택 error_code가 있다", async () => {
  const contract = JSON.parse(await read("packages/contracts/openapi/v1/studio-v2.openapi.json"));
  const schema = contract.components.schemas.StudioV2TableProfile;
  assert.ok(schema.properties.error_code, "error_code 속성");
  assert.ok(!schema.required.includes("error_code"), "error_code는 선택");
});
