// 생성 전 구성 확인 화면(WO-N1 NB3-U1): 슬라이드·동영상 개요의 설정 체크칸, 검토 화면 편집, 확정 호출, 취소, 422 문구, 상한.
import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

async function bundle(output) {
  const root = path.resolve(import.meta.dirname, "../..");
  const { build } = await import("vite");
  await build({
    configFile: false,
    logLevel: "silent",
    root,
    build: {
      outDir: output,
      emptyOutDir: false,
      lib: { entry: path.join(root, "packages/ui/src/studio-panel.jsx"), formats: ["es"], fileName: "outline-review-react" },
      rollupOptions: { external: ["react", "react-dom", "react-dom/client"] },
    },
  });
  const built = (await readdir(output)).find((name) => name.startsWith("outline-review-react") && /\.m?js$/u.test(name));
  return import(`${pathToFileURL(path.join(output, built)).href}?v=${Date.now()}`);
}

const OID = (c) => `sv2-${c.repeat(32)}`;
const CONFIRM = { confirm_outline: { type: "string", enum: ["no", "yes"] }, confirmed_outline: { type: "string", maxLength: 40000, hidden: true } };
const TYPES = ["audio_overview", "slides", "video_overview", "mind_map", "report", "flashcards", "quiz", "infographic", "data_table", "memo"].map((type_id) => ({
  type_id, available: true, formats: [], presets: type_id === "report" ? ["summary"] : [], export_formats: ["pptx"], default_format: type_id === "report" ? "summary" : null,
  settings_schema: { type: "object", properties: { focus: { type: "string" }, ...(["slides", "video_overview", "report"].includes(type_id) ? CONFIRM : {}) } },
}));
const item = (over = {}) => ({ output_id: OID("s"), type_id: "slides", format_id: null, title: "발표 자료", status: "completed", error_code: null, source_count: 2,
  current_revision: 1, created_at: "2026-11-24T00:00:00Z", updated_at: "2026-11-24T00:00:00Z", stale: false, ...over });

const SLIDES_REVIEW = { title: "보험 안내", slides: [], outline_review: [
  { title: "표지", points: [] }, { title: "지급 기한", points: ["3일 이내 지급"] }, { title: "면책 기간", points: ["90일"] }] };
const VIDEO_REVIEW = { title: "보험 영상", scenes: [], outline_review: [
  { title: "소개", narration_summary: "오늘은 보험금 지급을 알아봅니다." }, { title: "지급 기한", narration_summary: "서류 접수 후 3일 이내 지급합니다.", bullets: ["3일"] }] };

function fakeStudio({ outputs = [item(), item({ output_id: OID("v"), type_id: "video_overview", title: "동영상 개요" })], bodies = { slides: SLIDES_REVIEW, video_overview: VIDEO_REVIEW } } = {}) {
  const calls = [];
  const list = [...outputs];
  return {
    calls, list,
    listTypes: async () => TYPES,
    listOutputs: async () => ({ items: list.slice(), nextCursor: null }),
    createOutput: async (args) => { calls.push(["create", args]); return { output_id: OID("n"), job_id: "svj-1", status: "queued" }; },
    regenerateOutput: async (id, opts) => { calls.push(["regenerate", id, opts]); return { output_id: id, job_id: "svj-2", status: "queued" }; },
    cancelOutput: async (id) => { calls.push(["cancel", id]); return { output_id: id, cancel_requested: true }; },
    getOutput: async (id) => {
      const base = list.find((o) => o.output_id === id) ?? item({ output_id: id });
      return { ...base, settings: base.settings ?? {}, evidence: [], assets: [], revision: { content: { body: bodies[base.type_id] ?? { title: "제목", sections: [] }, warnings: [] } } };
    },
    exportFormats: () => [],
  };
}

async function mount(studio) {
  const dom = installMinimalDom();
  const root = path.resolve(import.meta.dirname, "../..");
  const output = await mkdtemp(path.join(root, ".outline-review-react-"));
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { StudioPanel } = await bundle(output);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(StudioPanel, { studio, sourceStats: { sourceCount: 2, checkedCount: 2, readySourceCount: 2, processingCount: 0 }, checkedSourceVersionIds: ["sv-1", "sv-2"] })); });
  const settle = async () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  await settle();
  return { container, act, settle,
    click: async (node) => { assert.ok(node, "누를 요소가 있어야 한다"); await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await settle(); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await rm(output, { recursive: true, force: true }); } };
}

const reactProps = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];
const byLabel = (container, label) => findElements(container, (n) => n.getAttribute?.("aria-label") === label)[0];
const alerts = (container) => findElements(container, (n) => n.getAttribute?.("role") === "alert").map((n) => n.textContent).join(" ");
const text = (container) => container.textContent;
async function type(view, label, value) {
  const input = byLabel(view.container, label);
  assert.ok(input, `${label} 입력칸이 있어야 한다`);
  await view.act(async () => reactProps(input).onChange({ target: { value }, currentTarget: { value } }));
}
const lastRegenerate = (studio) => studio.calls.filter((c) => c[0] === "regenerate").at(-1);

// ---- 설정 창 체크칸 ----
for (const [typeId, typeLabel] of [["slides", "슬라이드 자료"], ["video_overview", "동영상 개요"]]) {
  test(`${typeLabel} 설정 창에 '만들기 전에 구성 확인' 체크칸이 있고, 켜면 confirm_outline=yes와 지난 확정 목록 지우기를 함께 보낸다`, async () => {
    const studio = fakeStudio({ outputs: [] });
    const view = await mount(studio);
    try {
      await view.click(byLabel(view.container, `${typeLabel} 설정 변경 후 만들기`));
      const checkbox = findElements(view.container, (n) => n.tagName === "INPUT" && reactProps(n)?.type === "checkbox")[0];
      assert.ok(checkbox.parentNode.textContent.includes("만들기 전에 구성 확인"));
      assert.ok(!text(view.container).includes("작성 전에 구성 확인"));
      await view.act(async () => reactProps(checkbox).onChange({ target: { checked: true } }));
      const form = findElements(view.container, (n) => n.tagName === "FORM")[0];
      await view.act(async () => reactProps(form).onSubmit({ preventDefault() {} }));
      await view.settle();
      const [, args] = studio.calls.find((c) => c[0] === "create");
      assert.equal(args.typeId, typeId);
      assert.deepEqual(args.settings, { confirm_outline: "yes", confirmed_outline: "" });
    } finally { await view.close(); }
  });
}

test("체크칸을 켜지 않으면 구성 확인 설정을 보내지 않는다(기본은 바로 만들기)", async () => {
  const studio = fakeStudio({ outputs: [] });
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "슬라이드 자료 설정 변경 후 만들기"));
    const form = findElements(view.container, (n) => n.tagName === "FORM")[0];
    await view.act(async () => reactProps(form).onSubmit({ preventDefault() {} }));
    await view.settle();
    const [, args] = studio.calls.find((c) => c[0] === "create");
    assert.deepEqual(args.settings, {});
  } finally { await view.close(); }
});

test("보고서 설정 창의 체크칸 문구는 기존대로 '작성 전에 구성 확인'이다", async () => {
  const view = await mount(fakeStudio({ outputs: [] }));
  try {
    await view.click(byLabel(view.container, "보고서 설정 변경 후 만들기"));
    assert.ok(text(view.container).includes("작성 전에 구성 확인"));
  } finally { await view.close(); }
});

// ---- 카드 상태 ----
test("구성에서 멈춘 슬라이드·동영상 카드는 '구성 확인 필요'를 보이고, 일반 완료 카드는 보이지 않는다", async () => {
  const done = item({ output_id: OID("d"), title: "완성된 발표", type_id: "slides" });
  const studio = fakeStudio({ outputs: [item(), item({ output_id: OID("v"), type_id: "video_overview", title: "동영상 개요" }), done] });
  const base = studio.getOutput;
  studio.getOutput = async (id) => (id === done.output_id
    ? { ...done, settings: {}, evidence: [], assets: [], revision: { content: { body: { title: "발표", slides: [{ layout: "title", title: "표지", bullets: [], notes: "", refs: [] }] } } } }
    : base(id));
  const view = await mount(studio);
  try {
    const card = (title) => findElements(view.container, (n) => n.getAttribute?.("class") === "studio-card" && n.textContent.includes(title))[0];
    assert.ok(card("발표 자료").textContent.includes("구성 확인 필요"));
    assert.ok(card("동영상 개요").textContent.includes("구성 확인 필요"));
    assert.ok(!card("완성된 발표").textContent.includes("구성 확인 필요"));
  } finally { await view.close(); }
});

// ---- 슬라이드 검토·편집·확정 ----
test("슬라이드 검토: 카드를 누르면 검토 화면이 열리고 제목·요지 수정, 위/아래, 지우기, 추가 뒤 '이대로 만들기'가 그 목록으로 확정 호출하고 카드가 생성 중이 된다", async () => {
  const studio = fakeStudio();
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 발표 자료"));
    assert.ok(text(view.container).includes("구성 검토 중"));
    assert.equal(byLabel(view.container, "1번 장 제목").value, "표지");
    assert.equal(buttonByText(view.container, "편집"), undefined, "검토 중에는 본문 편집 버튼이 없다");
    await type(view, "문서 제목", "보험 안내 자료");
    await type(view, "2번 장 제목", "지급 기한 안내");
    await type(view, "2번 장 요지 1", "청구 후 3일 이내 지급");
    await view.click(byLabel(view.container, "2번 장 요지 추가"));
    await type(view, "2번 장 요지 2", "한도 1,000,000원");
    await view.click(byLabel(view.container, "3번 장 위로"));          // 면책 기간 ↔ 지급 기한 안내
    assert.equal(byLabel(view.container, "2번 장 제목").value, "면책 기간");
    await view.click(byLabel(view.container, "1번 장 지우기"));         // 표지 삭제
    await view.click(buttonByText(view.container, "장 추가"));
    await type(view, "3번 장 제목", "정리");
    await view.click(byLabel(view.container, "1번 장 아래로"));        // 면책 기간 ↔ 지급 기한 안내
    await view.click(buttonByText(view.container, "이대로 만들기"));
    const [, id, opts] = lastRegenerate(studio);
    assert.equal(id, OID("s"));
    assert.equal(opts.settings.confirm_outline, "no");
    assert.deepEqual(JSON.parse(opts.settings.confirmed_outline), { title: "보험 안내 자료", slides: [
      { title: "지급 기한 안내", points: ["청구 후 3일 이내 지급", "한도 1,000,000원"] },
      { title: "면책 기간", points: ["90일"] },
      { title: "정리", points: [] }] });
    assert.ok(!text(view.container).includes("구성 검토 중"), "확정하면 목록으로 돌아간다");
    const card = findElements(view.container, (n) => n.getAttribute?.("class") === "studio-card" && n.textContent.includes("발표 자료"))[0];
    assert.equal(card.getAttribute("data-state"), "generating");
    assert.ok(card.textContent.includes("확정한 구성으로 생성 중"));
  } finally { await view.close(); }
});

test("슬라이드 검토: 빈 요지는 확정 목록에서 빠지고 요지 지우기가 동작한다", async () => {
  const studio = fakeStudio();
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 발표 자료"));
    await view.click(byLabel(view.container, "2번 장 요지 추가"));
    await view.click(byLabel(view.container, "3번 장 요지 1 지우기"));
    await view.click(buttonByText(view.container, "이대로 만들기"));
    const [, , opts] = lastRegenerate(studio);
    assert.deepEqual(JSON.parse(opts.settings.confirmed_outline).slides.map((s) => s.points), [[], ["3일 이내 지급"], []]);
  } finally { await view.close(); }
});

// ---- 동영상 검토·편집·확정 ----
test("동영상 검토: 장면 제목·내레이션·글머리를 고치고 순서를 바꾸고 추가·삭제한 뒤 확정하면 scenes 목록으로 확정 호출한다", async () => {
  const studio = fakeStudio();
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 동영상 개요"));
    assert.ok(text(view.container).includes("구성 검토 중"));
    assert.equal(reactProps(byLabel(view.container, "2번 장면 내레이션")).value, "서류 접수 후 3일 이내 지급합니다.");
    await type(view, "1번 장면 제목", "들어가며");
    await type(view, "1번 장면 내레이션", "보험금 지급 기준을 살펴봅니다.");
    await type(view, "2번 장면 글머리 1", "3일 이내");
    await view.click(byLabel(view.container, "2번 장면 글머리 추가"));
    await type(view, "2번 장면 글머리 2", "서류 접수일 기준");
    await view.click(buttonByText(view.container, "장면 추가"));
    await type(view, "3번 장면 제목", "정리");
    await type(view, "3번 장면 내레이션", "오늘 내용을 정리합니다.");
    await view.click(byLabel(view.container, "3번 장면 위로"));
    await view.click(buttonByText(view.container, "장면 추가"));
    await view.click(byLabel(view.container, "4번 장면 지우기"));
    await view.click(buttonByText(view.container, "이대로 만들기"));
    const [, id, opts] = lastRegenerate(studio);
    assert.equal(id, OID("v"));
    assert.equal(opts.settings.confirm_outline, "no");
    assert.deepEqual(JSON.parse(opts.settings.confirmed_outline), { title: "보험 영상", scenes: [
      { title: "들어가며", narration_summary: "보험금 지급 기준을 살펴봅니다." },
      { title: "정리", narration_summary: "오늘 내용을 정리합니다." },
      { title: "지급 기한", narration_summary: "서류 접수 후 3일 이내 지급합니다.", bullets: ["3일 이내", "서류 접수일 기준"] }] });
    const card = findElements(view.container, (n) => n.getAttribute?.("class") === "studio-card" && n.textContent.includes("동영상 개요"))[0];
    assert.ok(card.textContent.includes("확정한 구성으로 생성 중"));
  } finally { await view.close(); }
});

// ---- 취소 ----
for (const [title, unit] of [["발표 자료", "장"], ["동영상 개요", "장면"]]) {
  test(`${title} 검토에서 '취소'를 누르면 확정 호출 없이 목록으로 돌아가고 카드는 다시 '구성 확인 필요'다`, async () => {
    const studio = fakeStudio();
    const view = await mount(studio);
    try {
      await view.click(byLabel(view.container, `열기: ${title}`));
      await type(view, `1번 ${unit} 제목`, "고쳤지만 버림");
      await view.click(buttonByText(view.container, "취소"));
      assert.equal(lastRegenerate(studio), undefined);
      assert.ok(!text(view.container).includes("구성 검토 중"));
      const card = findElements(view.container, (n) => n.getAttribute?.("class") === "studio-card" && n.textContent.includes(title))[0];
      assert.ok(card.textContent.includes("구성 확인 필요"));
    } finally { await view.close(); }
  });
}

test("확정 후 생성 중 카드의 '취소'는 기존 취소 경로(cancelOutput)를 부른다", async () => {
  const studio = fakeStudio();
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 발표 자료"));
    await view.click(buttonByText(view.container, "이대로 만들기"));
    const card = findElements(view.container, (n) => n.getAttribute?.("class") === "studio-card" && n.textContent.includes("발표 자료"))[0];
    await view.click(findElements(card, (n) => n.tagName === "BUTTON" && n.textContent.trim() === "취소")[0]);
    assert.deepEqual(studio.calls.at(-1), ["cancel", OID("s")]);
  } finally { await view.close(); }
});

test("취소된 슬라이드·동영상 카드는 '취소됨'으로 보인다", async () => {
  const studio = fakeStudio({ outputs: [item({ status: "cancelled", current_revision: 0 }), item({ output_id: OID("v"), type_id: "video_overview", title: "동영상 개요", status: "cancelled", current_revision: 0 })] });
  const view = await mount(studio);
  try {
    const cards = findElements(view.container, (n) => n.getAttribute?.("class") === "studio-card");
    assert.equal(cards.length, 2);
    for (const card of cards) { assert.equal(card.getAttribute("data-state"), "cancelled"); assert.ok(card.textContent.includes("취소됨")); assert.ok(!card.textContent.includes("구성 확인 필요")); }
  } finally { await view.close(); }
});

// ---- 422 문구 ----
for (const [title] of [["발표 자료"], ["동영상 개요"]]) {
  test(`${title} 확정이 422 OUTLINE_INVALID로 거부되면 입력 오류 문구를 보이고 검토 화면과 고친 내용을 유지한다`, async () => {
    const studio = fakeStudio();
    studio.regenerateOutput = async (id, opts) => { studio.calls.push(["regenerate", id, opts]); throw Object.assign(new Error("x"), { code: "OUTLINE_INVALID", status: 422 }); };
    const view = await mount(studio);
    try {
      await view.click(byLabel(view.container, `열기: ${title}`));
      await view.click(buttonByText(view.container, "이대로 만들기"));
      assert.ok(alerts(view.container).includes("구성 목록이 올바르지 않습니다"));
      assert.ok(text(view.container).includes("구성 검토 중"));
    } finally { await view.close(); }
  });
}

// ---- 상한(화면에서 막기) ----
test("슬라이드 상한: 빈 제목은 확정을 막고 문구를 보이며, 제목 100자·요지 120자·문서 제목 160자 입력 제한과 요지 5개·장 30개 추가 제한이 있다", async () => {
  const studio = fakeStudio({ bodies: { slides: { title: "t", slides: [], outline_review: [
    { title: "하나", points: ["1", "2", "3", "4", "5"] }, ...Array.from({ length: 29 }, (_, i) => ({ title: `장 ${i + 2}`, points: [] }))] } } });
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 발표 자료"));
    assert.equal(reactProps(byLabel(view.container, "1번 장 제목")).maxLength, 100);
    assert.equal(reactProps(byLabel(view.container, "1번 장 요지 1")).maxLength, 120);
    assert.equal(reactProps(byLabel(view.container, "문서 제목")).maxLength, 160);
    assert.equal(byLabel(view.container, "1번 장 요지 추가").disabled, true, "요지는 5개까지");
    assert.equal(buttonByText(view.container, "장 추가").disabled, true, "장은 30개까지");
    assert.ok(text(view.container).includes("30 / 30"));
    await type(view, "2번 장 제목", "   ");
    assert.ok(alerts(view.container).includes("2번 장 제목을 입력하세요"));
    assert.equal(buttonByText(view.container, "이대로 만들기").disabled, true);
    await view.click(buttonByText(view.container, "이대로 만들기"));
    assert.equal(lastRegenerate(studio), undefined);
  } finally { await view.close(); }
});

test("슬라이드 상한: 서버가 준 목록이 30장을 넘거나 글자 수를 넘으면 확정을 막고 문구를 보인다", async () => {
  const studio = fakeStudio({ bodies: { slides: { title: "t", slides: [], outline_review: [
    { title: "가".repeat(101), points: ["나".repeat(121)] }, ...Array.from({ length: 30 }, (_, i) => ({ title: `장 ${i + 2}`, points: [] }))] } } });
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 발표 자료"));
    const message = alerts(view.container);
    assert.ok(message.includes("장은 최대 30개"));
    assert.ok(message.includes("1번 장 제목은 최대 100자"));
    assert.ok(message.includes("1번 장 요지는 최대 120자"));
    assert.equal(buttonByText(view.container, "이대로 만들기").disabled, true);
  } finally { await view.close(); }
});

test("빈 목록은 확정할 수 없다: 마지막 장을 지우면 문구를 보이고 '이대로 만들기'가 잠긴다", async () => {
  const studio = fakeStudio({ bodies: { slides: { title: "t", slides: [], outline_review: [{ title: "하나", points: [] }] } } });
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 발표 자료"));
    await view.click(byLabel(view.container, "1번 장 지우기"));
    assert.ok(alerts(view.container).includes("장을 하나 이상 남겨 두세요"));
    assert.equal(buttonByText(view.container, "이대로 만들기").disabled, true);
  } finally { await view.close(); }
});

test("동영상 상한: 내레이션 600자·글머리 120자 입력 제한, 글머리 5개·장면 20개 추가 제한, 빈 장면 제목과 초과 내레이션 문구", async () => {
  const studio = fakeStudio({ bodies: { video_overview: { title: "t", scenes: [], outline_review: [
    { title: "하나", narration_summary: "가".repeat(601), bullets: ["1", "2", "3", "4", "5"] }, ...Array.from({ length: 19 }, (_, i) => ({ title: `장면 ${i + 2}`, narration_summary: "말" }))] } } });
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 동영상 개요"));
    assert.equal(reactProps(byLabel(view.container, "1번 장면 내레이션")).maxLength, 600);
    assert.equal(reactProps(byLabel(view.container, "1번 장면 글머리 1")).maxLength, 120);
    assert.equal(byLabel(view.container, "1번 장면 글머리 추가").disabled, true);
    assert.equal(buttonByText(view.container, "장면 추가").disabled, true);
    assert.ok(alerts(view.container).includes("1번 장면 내레이션은 최대 600자"));
    await type(view, "1번 장면 내레이션", "짧게");
    await type(view, "3번 장면 제목", "");
    assert.ok(alerts(view.container).includes("3번 장면 제목을 입력하세요"));
    assert.ok(!alerts(view.container).includes("내레이션은 최대 600자"));
    assert.equal(buttonByText(view.container, "이대로 만들기").disabled, true);
  } finally { await view.close(); }
});

// ---- 확정한 동영상의 근거 표시 ----
test("확정한 구성으로 만든 동영상은 장면별 근거가 없어도 오류가 아니라 안내 문구로 보인다", async () => {
  const done = item({ output_id: OID("v"), type_id: "video_overview", title: "동영상 개요", settings: { confirm_outline: "no", confirmed_outline: "{\"title\":\"t\",\"scenes\":[{\"title\":\"소개\",\"narration_summary\":\"말\"}]}" } });
  const studio = fakeStudio({ outputs: [done], bodies: { video_overview: { title: "t", scenes: [{ layout: "title", title: "소개", bullets: [], refs: [], narration: "말", start_ms: 0 }], duration_ms: 1000 } } });
  studio.getVideo = async () => ({ bytes: new Uint8Array([0]), contentType: "video/mp4" });
  studio.downloadExport = async () => ({ bytes: new Uint8Array([0]), contentType: "text/vtt", disposition: "" });
  globalThis.URL.createObjectURL ??= () => "blob:x";
  globalThis.URL.revokeObjectURL ??= () => {};
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 동영상 개요"));
    assert.ok(text(view.container).includes("확정한 구성으로 만든 동영상이라 장면별 근거 표시가 없습니다"));
    assert.ok(!alerts(view.container).includes("근거"), "근거 없음은 경고(alert)로 보이지 않는다");
  } finally { await view.close(); }
});

// ---- N1-B10·B11 (UAT-09) ----
test("검토 중에는 머리줄에 '다운로드'가 없고, 완성된 산출물에는 있다", async () => {
  const done = item({ output_id: OID("d"), title: "완성된 발표", type_id: "slides" });
  const studio = fakeStudio({ outputs: [item(), done] });
  studio.exportFormats = () => ["pptx"];
  const base = studio.getOutput;
  studio.getOutput = async (id) => (id === done.output_id
    ? { ...done, settings: {}, evidence: [], assets: [], revision: { content: { body: { title: "발표", slides: [{ layout: "title", title: "표지", bullets: [], notes: "", refs: [] }] } } } }
    : base(id));
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 발표 자료"));
    assert.ok(text(view.container).includes("구성 검토 중"));
    assert.ok(!buttonByText(view.container, "다운로드"), "검토 중에는 내려받을 본문이 없다");
    await view.click(byLabel(view.container, "목록으로"));
    await view.click(byLabel(view.container, "열기: 완성된 발표"));
    assert.ok(Boolean(buttonByText(view.container, "다운로드")), "완성된 산출물은 내려받을 수 있다");
  } finally { await view.close(); }
});

for (const [title, label] of [["발표 자료", "2번 장 요지 1"], ["동영상 개요", "2번 장면 글머리 1"]]) {
  test(`${title} 검토의 요지·글머리 칸은 긴 문장이 잘리지 않게 줄바꿈되는 입력칸이다`, async () => {
    const view = await mount(fakeStudio());
    try {
      await view.click(byLabel(view.container, `열기: ${title}`));
      const field = byLabel(view.container, label);
      assert.ok(field, `${label} 칸이 있어야 한다`);
      assert.equal(field.tagName, "TEXTAREA");
      await type(view, label, "첫 줄\n둘째 줄");
      assert.equal(byLabel(view.container, label).value, "첫 줄 둘째 줄", "요지·글머리는 한 줄 문장으로 저장한다");
    } finally { await view.close(); }
  });
}

test("서버가 문서 제목을 비워 보내면 문서 제목 칸을 첫 장 제목으로 채운다", async () => {
  const studio = fakeStudio({ bodies: { slides: { ...SLIDES_REVIEW, title: "" }, video_overview: VIDEO_REVIEW } });
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 발표 자료"));
    assert.equal(byLabel(view.container, "문서 제목").value, "표지");
  } finally { await view.close(); }
});
