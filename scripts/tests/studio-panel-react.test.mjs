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
      lib: { entry: path.join(root, "packages/ui/src/studio-panel.jsx"), formats: ["es"], fileName: "studio-panel-react" },
      rollupOptions: { external: ["react", "react-dom", "react-dom/client"] },
    },
  });
  const built = (await readdir(output)).find((name) => name.startsWith("studio-panel-react") && /\.m?js$/u.test(name));
  return import(`${pathToFileURL(path.join(output, built)).href}?v=${Date.now()}`);
}

const OID = (c) => `sv2-${c.repeat(32)}`;
const TYPES = ["audio_overview", "slides", "video_overview", "mind_map", "report", "flashcards", "quiz", "infographic", "data_table", "memo"].map((type_id) => ({
  type_id, available: !["audio_overview", "video_overview", "infographic"].includes(type_id), formats: [], presets: type_id === "report" ? ["summary", "custom"] : [],
  export_formats: ["docx"], default_format: type_id === "report" ? "summary" : null, settings_schema: { type: "object", properties: { focus: { type: "string" } } },
}));
const item = (over = {}) => ({ output_id: OID("a"), type_id: "report", format_id: "summary", title: "보고서 1", status: "completed", error_code: null, source_count: 2,
  current_revision: 1, created_at: "2026-10-20T00:00:00Z", updated_at: "2026-10-20T00:00:00Z", stale: false, ...over });

function fakeStudio(initial = [item()]) {
  const calls = [];
  const outputs = [...initial];
  return {
    calls, outputs,
    listTypes: async () => TYPES,
    listOutputs: async () => ({ items: outputs.slice(), nextCursor: null }),
    createOutput: async (args) => { calls.push(["create", args]); const created = item({ output_id: OID("b"), type_id: args.typeId, title: "새 산출물", status: "queued" }); outputs.unshift(created); return { output_id: created.output_id, job_id: "svj-1", status: "queued" }; },
    deleteOutput: async (id) => { calls.push(["delete", id]); const i = outputs.findIndex((o) => o.output_id === id); if (i >= 0) outputs.splice(i, 1); },
    renameOutput: async (id, title, opts) => { calls.push(["rename", id, title, opts.etag]); return { output_id: id, title, updated_at: "2026-10-21T00:00:00Z" }; },
    cancelOutput: async (id) => { calls.push(["cancel", id]); return { output_id: id, cancel_requested: true }; },
    regenerateOutput: async (id, opts) => { calls.push(["regenerate", id, opts]); return { output_id: id, job_id: "svj-2", status: "queued" }; },
    createMemo: async (args) => { calls.push(["memo", args]); return { output_id: OID("c"), status: "completed", replayed: false }; },
    getOutput: async (id) => ({ ...item({ output_id: id }), settings: {}, evidence: [], assets: [], revision: { content: { body: { title: "보고서 제목", sections: [] }, warnings: [] } } }),
    getProvenance: async () => ({ type_id: "report", format_id: "summary", instruction: { focus: null, customization_applied: false }, settings: {}, sources: [], evidence: [] }),
    getSharing: async () => ({ scope: "notebook", public_link: false, notebook_id: "nb-1" }),
    exportFormats: () => ["docx"],
  };
}

async function mount(studio, props = {}) {
  const dom = installMinimalDom();
  const root = path.resolve(import.meta.dirname, "../..");
  const output = await mkdtemp(path.join(root, ".studio-panel-react-"));
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { StudioPanel } = await bundle(output);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  let current = { studio, sourceStats: { sourceCount: 3, checkedCount: 2, readySourceCount: 2, processingCount: 0 }, checkedSourceVersionIds: ["sv-1", "sv-2"], ...props };
  await act(async () => { reactRoot.render(createElement(StudioPanel, current)); });
  const rerender = async (next = {}) => { current = { ...current, ...next }; await act(async () => { reactRoot.render(createElement(StudioPanel, current)); }); };
  return { container, act, rerender, click: async (node) => act(async () => { node.dispatchEvent(new MinimalEvent("click")); }),
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await rm(output, { recursive: true, force: true }); } };
}

const reactProps = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];
const byLabel = (container, label) => findElements(container, (n) => n.getAttribute?.("aria-label") === label)[0];
const text = (container) => container.textContent;

test("패널은 타일 10종과 산출물 카드를 렌더하고 비활성 타일은 aria-disabled로 표시한다", async () => {
  const studio = fakeStudio();
  const view = await mount(studio);
  try {
    const tiles = findElements(view.container, (n) => n.tagName === "BUTTON" && n.getAttribute("class")?.includes("studio-tile") && !n.getAttribute("class").includes("edit"));
    assert.equal(tiles.length, 10);
    assert.equal(byLabel(view.container, "보고서").getAttribute("aria-disabled"), "false");
    assert.equal(byLabel(view.container, "오디오 개요").getAttribute("aria-disabled"), "true");
    assert.ok(text(view.container).includes("보고서 1"));
    assert.ok(text(view.container).includes("요약 · 소스 2개"));
    assert.ok(findElements(view.container, (n) => n.getAttribute?.("role") === "tooltip").length >= 10);
  } finally { await view.close(); }
});

test("소스가 없으면 타일이 비활성이고 클릭해도 생성하지 않는다", async () => {
  const studio = fakeStudio([]);
  const view = await mount(studio, { sourceStats: { sourceCount: 0, checkedCount: 0, readySourceCount: 0, processingCount: 0 }, checkedSourceVersionIds: [] });
  try {
    const tile = byLabel(view.container, "보고서");
    assert.equal(tile.getAttribute("aria-disabled"), "true");
    await view.click(tile);
    assert.equal(studio.calls.length, 0);
    assert.ok(text(view.container).includes("소스를 추가하면 만들 수 있습니다"));
    assert.ok(text(view.container).includes("소스를 선택하고"));
  } finally { await view.close(); }
});

test("타일 클릭은 선택한 소스로 createOutput을 호출하고 생성 중 카드를 보여준다", async () => {
  const studio = fakeStudio([]);
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "보고서"));
    assert.deepEqual(studio.calls[0], ["create", { typeId: "report", formatId: undefined, settings: undefined, sourceVersionIds: ["sv-1", "sv-2"] }]);
    assert.ok(text(view.container).includes("생성 중…"));
    assert.ok(findElements(view.container, (n) => n.getAttribute?.("class") === "studio-card").length === 1);
  } finally { await view.close(); }
});

test("생성 오류는 안전한 문구의 경고 배너로 표시한다", async () => {
  const studio = fakeStudio([]);
  studio.createOutput = async () => { const error = new Error("x"); error.code = "STUDIO_NO_READY_SOURCE"; throw error; };
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "보고서"));
    const alert = findElements(view.container, (n) => n.getAttribute?.("role") === "alert")[0];
    assert.ok(alert.textContent.includes("사용할 수 있는 소스가 없습니다"));
    assert.equal(findElements(view.container, (n) => n.getAttribute?.("class") === "studio-card").length, 0);
  } finally { await view.close(); }
});

test("메뉴는 항목 순서를 지키고 삭제는 확인 대화상자를 거친다", async () => {
  const studio = fakeStudio();
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "더보기: 보고서 1"));
    const menu = findElements(view.container, (n) => n.getAttribute?.("role") === "menu")[0];
    const items = findElements(menu, (n) => n.getAttribute?.("role") === "menuitem").map((n) => n.textContent.trim());
    assert.deepEqual(items, ["공유", "이름 바꾸기", "다운로드", "프롬프트 및 소스 보기", "다시 생성", "설정 변경 후 다시 생성", "삭제"]);
    await view.click(findElements(menu, (n) => n.getAttribute?.("role") === "menuitem" && n.textContent.trim() === "삭제")[0]);
    const dialog = findElements(view.container, (n) => n.getAttribute?.("role") === "dialog")[0];
    assert.ok(dialog.textContent.includes("산출물을 삭제할까요?"));
    assert.equal(studio.calls.length, 0);
    await view.click(findElements(dialog, (n) => n.tagName === "BUTTON" && n.textContent.trim() === "삭제")[0]);
    assert.deepEqual(studio.calls[0], ["delete", OID("a")]);
    assert.ok(!text(view.container).includes("보고서 1"));
  } finally { await view.close(); }
});

test("프롬프트 및 소스 보기와 다시 생성 메뉴는 대화상자·API를 연결한다", async () => {
  const studio = fakeStudio();
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "더보기: 보고서 1"));
    const menuitem = (name) => findElements(view.container, (n) => n.getAttribute?.("role") === "menuitem" && n.textContent.trim() === name)[0];
    await view.click(menuitem("프롬프트 및 소스 보기"));
    const dialog = findElements(view.container, (n) => n.getAttribute?.("role") === "dialog")[0];
    assert.ok(dialog.textContent.includes("프롬프트 및 소스"));
    assert.ok(dialog.textContent.includes("포커스 없음"));
    await view.click(findElements(dialog, (n) => n.tagName === "BUTTON" && n.textContent.trim() === "닫기")[0]);
    await view.click(byLabel(view.container, "더보기: 보고서 1"));
    await view.click(menuitem("다시 생성"));
    assert.deepEqual(studio.calls.at(-1), ["regenerate", OID("a"), { settings: undefined }]);
  } finally { await view.close(); }
});

test("카드를 열면 상세 뷰어가 보이고 목록으로 돌아올 수 있다", async () => {
  const studio = fakeStudio();
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 보고서 1"));
    assert.ok(text(view.container).includes("보고서 제목"));
    await view.click(byLabel(view.container, "목록으로"));
    assert.ok(text(view.container).includes("보고서 1"));
  } finally { await view.close(); }
});

test("인포그래픽 상세는 서버가 그린 PNG를 이미지로 보이고 확대·축소하며 섹션 근거를 잇는다(F7-01)", async () => {
  const info = item({ output_id: OID("d"), type_id: "infographic", title: "인포그래픽 1" });
  const studio = fakeStudio([info]);
  studio.getOutput = async (id) => ({ ...info, output_id: id, settings: {}, assets: [], evidence: [{ ref_id: "S1", source_version_id: "sv-1", locator_kind: "page", locator_value: "1", origin: "notebook_source", has_snapshot: false }],
    revision: { content: { body: { title: "보험금 안내", sections: [{ headline: "지급 기한", value: "3일", refs: ["S1"] }, { headline: "지급 한도", refs: ["S1"] }] }, warnings: [] } } });
  const downloads = [];
  studio.downloadExport = async (id, format) => { downloads.push([id, format]); return { bytes: new Uint8Array([137, 80, 78, 71]), contentType: "image/png", disposition: "" }; };
  const urls = [];
  const priorCreate = globalThis.URL.createObjectURL; const priorRevoke = globalThis.URL.revokeObjectURL;
  globalThis.URL.createObjectURL = (blob) => { urls.push(blob.type); return "blob:fake-infographic"; };
  globalThis.URL.revokeObjectURL = () => {};
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 인포그래픽 1"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.deepEqual(downloads[0], [OID("d"), "png"]);
    assert.deepEqual(urls, ["image/png"]);
    const image = findElements(view.container, (n) => n.tagName === "IMG")[0];
    assert.equal(image.getAttribute("src"), "blob:fake-infographic");
    assert.equal(image.getAttribute("alt"), "인포그래픽: 보험금 안내");
    assert.equal(image.style.width, "100%");
    await view.click(byLabel(view.container, "확대"));
    assert.equal(findElements(view.container, (n) => n.tagName === "IMG")[0].style.width, "125%");
    await view.click(buttonByText(view.container, "맞춤"));
    assert.equal(findElements(view.container, (n) => n.tagName === "IMG")[0].style.width, "100%");
    assert.ok(text(view.container).includes("지급 기한"));
    assert.ok(findElements(view.container, (n) => n.tagName === "BUTTON" && n.getAttribute?.("aria-label")?.includes("S1") === false && n.textContent === "[1]").length >= 1);
  } finally {
    globalThis.URL.createObjectURL = priorCreate; globalThis.URL.revokeObjectURL = priorRevoke;
    await view.close();
  }
});

test("오디오 개요 상세는 mp3를 불러 재생기를 보이고 스크립트 줄을 누르면 그 위치로 이동하며 줄별 근거를 잇는다(F7-03·S2-13)", async () => {
  const audioItem = item({ output_id: OID("e"), type_id: "audio_overview", title: "오디오 1" });
  const studio = fakeStudio([audioItem]);
  studio.getOutput = async (id) => ({ ...audioItem, output_id: id, settings: {}, assets: [], evidence: [{ ref_id: "S1", source_version_id: "sv-1", locator_kind: "page", locator_value: "1", origin: "notebook_source", has_snapshot: false }],
    revision: { content: { body: { title: "보험금 이야기", duration_ms: 65000, script: [
      { speaker: "A", text: "안녕하세요.", refs: ["S1"], start_ms: 0, end_ms: 1500 },
      { speaker: "B", text: "보험금은 3일 이내에 지급합니다.", refs: ["S1"], start_ms: 1850, end_ms: 4200 }] }, warnings: [] } } });
  const loads = [];
  studio.getAudio = async (id) => { loads.push(id); return { bytes: new Uint8Array([0xff, 0xfb, 0x90]), contentType: "audio/mpeg", durationMs: 65000 }; };
  const types = [];
  const priorCreate = globalThis.URL.createObjectURL; const priorRevoke = globalThis.URL.revokeObjectURL;
  globalThis.URL.createObjectURL = (blob) => { types.push(blob.type); return "blob:fake-audio"; };
  globalThis.URL.revokeObjectURL = () => {};
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 오디오 1"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.deepEqual(loads, [OID("e")]);
    assert.deepEqual(types, ["audio/mpeg"]);
    const player = findElements(view.container, (n) => n.tagName === "AUDIO")[0];
    assert.equal(player.getAttribute("src"), "blob:fake-audio");
    assert.equal(player.getAttribute("aria-label"), "오디오 개요 재생기");
    assert.ok(text(view.container).includes("길이 1분 5초"));
    assert.ok(text(view.container).includes("A(진행자)") && text(view.container).includes("B(설명자)"));
    const second = byLabel(view.container, "이 줄부터 재생: 보험금은 3일 이내에 지급합니다.");
    player.play = () => Promise.resolve();
    await view.click(second);
    assert.equal(player.currentTime, 1.85);
    assert.ok(findElements(view.container, (n) => n.tagName === "OPTION" && n.textContent === "1.5×").length >= 1);
    assert.ok(findElements(view.container, (n) => n.tagName === "BUTTON" && n.textContent === "[1]").length >= 1);
  } finally {
    globalThis.URL.createObjectURL = priorCreate; globalThis.URL.revokeObjectURL = priorRevoke;
    await view.close();
  }
});

test("동영상 개요 상세는 mp4와 자막을 불러 재생기·자막 트랙·챕터 목록을 보이고 챕터를 누르면 그 위치로 이동한다(F7-05·S2-14)", async () => {
  const videoItem = item({ output_id: OID("f"), type_id: "video_overview", title: "동영상 1" });
  const studio = fakeStudio([videoItem]);
  const chapters = [{ title: "보험금 지급 안내", start_ms: 0, end_ms: 4000 }, { title: "지급 기한", start_ms: 4000, end_ms: 9000 }];
  studio.getOutput = async (id) => ({ ...videoItem, output_id: id, settings: {}, assets: [], evidence: [{ ref_id: "S1", source_version_id: "sv-1", locator_kind: "page", locator_value: "1", origin: "notebook_source", has_snapshot: false }],
    revision: { content: { body: { title: "보험금", duration_ms: 125000, chapters, scenes: [
      { title: "보험금 지급 안내", refs: [], start_ms: 0, end_ms: 4000, cues: [] }, { title: "지급 기한", refs: ["S1"], start_ms: 4000, end_ms: 9000, cues: [] }] }, warnings: [] } } });
  const loads = [];
  studio.getVideo = async (id) => { loads.push(["video", id]); return { bytes: new Uint8Array([0, 0, 0, 24]), contentType: "video/mp4", durationMs: 125000 }; };
  studio.downloadExport = async (id, format) => { loads.push(["export", id, format]); return { bytes: new TextEncoder().encode("WEBVTT"), contentType: "text/vtt", disposition: "" }; };
  const types = [];
  const priorCreate = globalThis.URL.createObjectURL; const priorRevoke = globalThis.URL.revokeObjectURL;
  globalThis.URL.createObjectURL = (blob) => { types.push(blob.type); return `blob:fake-${types.length}`; };
  globalThis.URL.revokeObjectURL = () => {};
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 동영상 1"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.deepEqual(loads.sort(), [["export", OID("f"), "vtt"], ["video", OID("f")]].sort());
    assert.deepEqual(types.sort(), ["text/vtt", "video/mp4"]);
    const player = findElements(view.container, (n) => n.tagName === "VIDEO")[0];
    assert.equal(player.getAttribute("aria-label"), "동영상 개요 재생기");
    const track = findElements(view.container, (n) => n.tagName === "TRACK")[0];
    assert.equal(track.getAttribute("kind"), "captions");
    assert.equal(track.getAttribute("label"), "한국어 자막");
    assert.ok(text(view.container).includes("길이 2분 5초"));
    assert.ok(text(view.container).includes("챕터"));
    player.play = () => Promise.resolve();
    await view.click(byLabel(view.container, "이 챕터로 이동: 지급 기한"));
    assert.equal(player.currentTime, 4);
    assert.ok(findElements(view.container, (n) => n.tagName === "BUTTON" && n.textContent === "[1]").length >= 1);
  } finally {
    globalThis.URL.createObjectURL = priorCreate; globalThis.URL.revokeObjectURL = priorRevoke;
    await view.close();
  }
});

const EVIDENCE = [{ ref_id: "S1", source_version_id: "sv-1", source_name: "보험약관.pdf", locator_kind: "page", locator_value: "1", origin: "notebook_source", has_snapshot: false }];
function detailStudio(listItem, body, extra = {}) {
  const studio = fakeStudio([listItem]);
  studio.getOutput = async (id) => ({ ...listItem, output_id: id, settings: {}, assets: [], evidence: EVIDENCE, revision: { content: { body, warnings: [] } } });
  studio.attempts = [];
  studio.recordLearningAttempt = async (id, input) => { studio.attempts.push(input); return {}; };
  return Object.assign(studio, extra);
}

test("인용 번호를 누르면 그 근거의 소스 위치(발췌)가 열린다(ST-T05)", async () => {
  const report = item({ output_id: OID("r"), type_id: "report", title: "근거 보고서" });
  const studio = detailStudio(report, { title: "보험금", summary: "요약", sections: [{ heading: "지급", blocks: [{ type: "paragraph", text: "3일 이내에 지급한다.", refs: ["S1"] }] }] });
  const calls = [];
  studio.getEvidenceContent = async (id, ref, options) => { calls.push([id, ref, options?.revision ?? null]); return { kind: "excerpt", text: "청구서류 접수일부터 3일 이내에 지급한다." }; };
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 근거 보고서"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    const ref = findElements(view.container, (n) => n.tagName === "BUTTON" && n.textContent === "[1]")[0];
    assert.ok(ref, "인용 번호 버튼이 보인다");
    await view.click(ref);
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.deepEqual(calls[0].slice(0, 2), [OID("r"), "S1"]);
    assert.ok(text(view.container).includes("청구서류 접수일부터 3일 이내에 지급한다."));
  } finally { await view.close(); }
});

test("퀴즈를 풀고 제출하면 정오 표시·결과 점수·시도 기록이 남고 '틀린 문항만 다시'는 틀린 문항만 보인다(ST-T11·T24)", async () => {
  const quiz = item({ output_id: OID("q"), type_id: "quiz", title: "면책 퀴즈" });
  const studio = detailStudio(quiz, { questions: [
    { q: "지급 기한은?", options: ["3일", "5일", "7일", "10일"], answer_index: 0, explanation: "접수일부터 3일", refs: ["S1"] },
    { q: "면책 기간은?", options: ["30일", "60일", "90일", "120일"], answer_index: 2, explanation: "계약일부터 90일", refs: ["S1"] }] });
  const view = await mount(studio);
  const option = (label) => findElements(view.container, (n) => n.tagName === "BUTTON" && n.getAttribute("class")?.includes("studio-option") && n.textContent.includes(label))[0];
  const button = (label) => buttonByText(view.container, label);
  try {
    await view.click(byLabel(view.container, "열기: 면책 퀴즈"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    await view.click(option("3일"));            // 1번: 정답
    await view.click(button("제출"));
    assert.ok(text(view.container).includes("정답입니다."));
    await view.click(button("다음"));
    await view.click(option("30일"));           // 2번: 오답
    await view.click(button("제출"));
    assert.ok(text(view.container).includes("오답입니다."));
    await view.click(button("결과 보기"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.ok(text(view.container).includes("결과: 1 / 2"));
    assert.equal(studio.attempts.length, 1);
    assert.equal(studio.attempts[0].kind, "quiz");
    assert.equal(studio.attempts[0].payload.score, 1);
    assert.deepEqual(studio.attempts[0].payload.answers.map((a) => a.correct), [true, false]);
    await view.click(button("틀린 문항만 다시"));   // 학습 모드: 틀린 문항만
    assert.ok(text(view.container).includes("1 / 1."));
    assert.ok(text(view.container).includes("면책 기간은?"));
    assert.ok(!text(view.container).includes("지급 기한은?"));
  } finally { await view.close(); }
});

test("플래시카드는 알아요/모르겠어요를 기록하고 '모르는 카드만' 모드는 모르는 카드만 보인다(ST-T24)", async () => {
  const cards = item({ output_id: OID("c"), type_id: "flashcards", title: "용어 카드" });
  const studio = detailStudio(cards, { cards: [
    { front: "면책 기간", back: "계약일부터 90일", refs: ["S1"] }, { front: "지급 한도", back: "사고당 1,000,000원", refs: ["S1"] }, { front: "해지환급금", back: "7일 이내", refs: ["S1"] }] });
  const view = await mount(studio);
  const button = (label) => buttonByText(view.container, label);
  try {
    await view.click(byLabel(view.container, "열기: 용어 카드"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    await view.click(button("알아요"));         // 카드 1: 앎
    await view.click(button("모르겠어요"));      // 카드 2: 모름
    await view.click(button("알아요"));         // 카드 3: 앎
    assert.ok(studio.attempts.length >= 3);
    const last = studio.attempts.at(-1).payload;
    assert.deepEqual([last.known, last.unknown], [[0, 2], [1]]);
    const checkbox = findElements(view.container, (n) => n.tagName === "INPUT")[0];
    await view.act(async () => { reactProps(checkbox).onChange({ target: { checked: true } }); });
    assert.ok(text(view.container).includes("1 / 1"));
    const face = findElements(view.container, (n) => n.getAttribute?.("class")?.includes("studio-card-face"))[0];
    assert.ok(face.textContent.includes("지급 한도"));
  } finally { await view.close(); }
});

test("소스가 바뀐 산출물 카드는 '변경됨' 표시를 보이고 최신 카드는 보이지 않는다(ST-T09)", async () => {
  const studio = fakeStudio([item({ output_id: OID("s"), title: "오래된 보고서", stale: true }), item({ output_id: OID("t"), title: "최신 보고서", stale: false })]);
  const view = await mount(studio);
  try {
    const card = (title) => findElements(view.container, (n) => n.getAttribute?.("class") === "studio-card" && n.textContent.includes(title))[0];
    const chips = (node) => findElements(node, (n) => n.getAttribute?.("class")?.includes("studio-chip"));
    assert.equal(chips(card("오래된 보고서")).length, 1);
    assert.equal(chips(card("최신 보고서")).length, 0);
  } finally { await view.close(); }
});

test("조직이 내보내기 추가 인증을 켠 경우 비밀번호 확인 뒤 승인 토큰으로 다시 내려받는다(ST-T27)", async () => {
  const studio = fakeStudio();
  const downloads = [];
  const issued = [];
  studio.downloadExport = async (id, format, options) => {
    downloads.push([id, format, options?.stepUp ?? null]);
    if (!options?.stepUp) throw Object.assign(new Error("x"), { code: "STEP_UP_REQUIRED" });
    return { bytes: new Uint8Array([1, 2, 3]), contentType: "application/pdf", disposition: "" };
  };
  studio.issueExportStepUp = async (id, password) => { issued.push([id, password]); return "grant-token"; };
  const priorCreate = globalThis.URL.createObjectURL; const priorRevoke = globalThis.URL.revokeObjectURL;
  globalThis.URL.createObjectURL = () => "blob:fake"; globalThis.URL.revokeObjectURL = () => {};
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 보고서 1"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    await view.click(buttonByText(view.container, "다운로드"));
    await view.click(findElements(view.container, (n) => n.getAttribute?.("role") === "menuitem" && n.textContent === "DOCX")[0]);
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.ok(text(view.container).includes("내려받기 추가 인증"));
    const password = findElements(view.container, (n) => n.tagName === "INPUT" && n.getAttribute?.("id") === "studio-stepup-password")[0];
    password.value = "pw-for-test";
    await view.click(buttonByText(view.container, "인증 후 내려받기"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.deepEqual(issued, [[OID("a"), "pw-for-test"]]);
    assert.deepEqual(downloads, [[OID("a"), "docx", null], [OID("a"), "docx", "grant-token"]]);
    assert.ok(!text(view.container).includes("내려받기 추가 인증"));
  } finally {
    globalThis.URL.createObjectURL = priorCreate; globalThis.URL.revokeObjectURL = priorRevoke;
    await view.close();
  }
});

test("메모 추가 버튼은 빈 메모를 만든다", async () => {
  const studio = fakeStudio([]);
  const view = await mount(studio);
  try {
    await view.click(buttonByText(view.container, "메모 추가"));
    assert.deepEqual(studio.calls[0], ["memo", { markdown: "" }]);
  } finally { await view.close(); }
});

async function mountWith(component, props) {
  const dom = installMinimalDom();
  const root = path.resolve(import.meta.dirname, "../..");
  const output = await mkdtemp(path.join(root, ".studio-gate-react-"));
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const exports = await bundle(output);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(exports[component], props)); });
  return { container, act, close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await rm(output, { recursive: true, force: true }); } };
}

test("셸 진입점: studioV2가 없으면 기존 Studio(fallback)를 그대로 쓴다", async () => {
  const { createElement } = await import("react");
  const view = await mountWith("StudioFallbackGate", { adapter: {}, sources: [], fallback: createElement("p", null, "기존 Studio") });
  try { assert.ok(text(view.container).includes("기존 Studio")); } finally { await view.close(); }
});

test("셸 진입점: API가 v2를 제공하지 않으면(404) 기존 Studio로 되돌아간다", async () => {
  const { createElement } = await import("react");
  const studio = { ...fakeStudio(), listTypes: async () => { const error = new Error("x"); error.status = 404; error.code = "RESOURCE_UNAVAILABLE"; throw error; } };
  const view = await mountWith("StudioFallbackGate", { adapter: { studioV2: studio }, sources: [], fallback: createElement("p", null, "기존 Studio") });
  try { assert.ok(text(view.container).includes("기존 Studio")); assert.ok(!text(view.container).includes("산출물 만들기")); } finally { await view.close(); }
});

test("셸 진입점: 체크 해제한 소스는 생성에서 제외되고 처리 중인 소스는 타일 사유가 된다", async () => {
  const studio = fakeStudio([]);
  const sources = [
    { sourceId: "s1", sourceVersionId: "sv-1", ready: true, sourceState: "ready" },
    { sourceId: "s2", sourceVersionId: "sv-2", ready: true, sourceState: "ready" },
    { sourceId: "s3", sourceVersionId: "sv-3", ready: false, sourceState: "processing" },
  ];
  const view = await mountWith("StudioFallbackGate", { adapter: { studioV2: studio }, sources, unchecked: new Set(["sv-2"]) });
  try {
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    const tile = byLabel(view.container, "퀴즈");
    await view.act(async () => { tile.dispatchEvent(new MinimalEvent("click")); });
    assert.deepEqual(studio.calls.find((c) => c[0] === "create")[1].sourceVersionIds, ["sv-1"]);
  } finally { await view.close(); }
});

test("동시 한도(기본 2)를 넘은 접수 산출물만 '대기 중'으로 구분하고, 실행 중·낙관적 카드는 '생성 중'이다(ST-T26)", async () => {
  const studio = fakeStudio([
    item({ output_id: OID("1"), title: "실행1", status: "generating", created_at: "2026-10-20T00:00:01Z" }),
    item({ output_id: OID("2"), title: "실행2", status: "generating", created_at: "2026-10-20T00:00:02Z" }),
    item({ output_id: OID("3"), title: "대기3", status: "queued", created_at: "2026-10-20T00:00:03Z" })]);
  studio.listTypes = async () => Object.assign([...TYPES], { limits: { userConcurrency: 2 } });
  const view = await mount(studio);
  try {
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    const cards = findElements(view.container, (n) => n.tagName === "LI" && n.getAttribute?.("class") === "studio-card");
    const states = cards.map((c) => c.textContent);
    assert.equal(states.filter((t) => t.includes("대기 중…")).length, 1);
    assert.equal(states.filter((t) => t.includes("생성 중…")).length, 2);
    assert.ok(states.find((t) => t.includes("대기3")).includes("대기 중…"));
  } finally { await view.close(); }
});

test("실행 중이 한도 미만이면 접수된 산출물은 곧 시작되므로 '생성 중'으로 보인다", async () => {
  const studio = fakeStudio([item({ output_id: OID("4"), title: "방금 접수", status: "queued" })]);
  const view = await mount(studio);
  try {
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.ok(text(view.container).includes("생성 중…"));
    assert.ok(!text(view.container).includes("대기 중…"));
  } finally { await view.close(); }
});

// ---- 사용자 편집(S2-11) ----
const REPORT_CONTENT = { schema: "studio.report.v1", language: "ko", warnings: [], body: { title: "보고서 제목", summary: "요약", sections: [
  { heading: "1장", blocks: [{ type: "paragraph", text: "원래 문장", refs: ["S1"] }, { type: "bullets", items: ["가", "나"], refs: [] }, { type: "table", rows: [["a", "b"]], refs: [] }] }] } };

test("보고서 편집: 문단·목록을 고쳐 저장하면 전체 content(근거·스키마 유지)로 새 리비전을 만들고 편집본을 다시 읽어 보여 준다", async () => {
  const studio = fakeStudio();
  let stored = REPORT_CONTENT;
  studio.getOutput = async (id) => ({ ...item({ output_id: id }), settings: {}, evidence: [], assets: [], revision: { content: stored } });
  studio.createRevision = async (id, args) => { studio.calls.push(["revision", id, args]); stored = args.content; return { output_id: id, revision_no: 2 }; };
  const view = await mount(studio);
  try {
    await view.click(findElements(view.container, (n) => n.tagName === "BUTTON" && (n.getAttribute?.("aria-label") ?? "").includes("보고서 1"))[0]);
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    await view.click(buttonByText(view.container, "편집"));
    const paragraph = byLabel(view.container, "섹션 1 문단 1");
    paragraph.value = "고친 문장";
    await view.act(async () => reactProps(paragraph).onChange({ target: paragraph, currentTarget: paragraph }));
    const bullets = byLabel(view.container, "섹션 1 목록 2 (한 줄에 항목 하나)");
    bullets.value = "가\n\n다\n";
    await view.act(async () => reactProps(bullets).onChange({ target: bullets, currentTarget: bullets }));
    assert.ok(text(view.container).includes("표는 이 편집기에서 수정할 수 없습니다"));
    await view.click(buttonByText(view.container, "저장"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    const [, id, args] = studio.calls.find((c) => c[0] === "revision");
    assert.equal(id, OID("a"));
    assert.equal(args.changeReason, "사용자 편집");
    assert.equal(args.content.schema, "studio.report.v1");
    assert.deepEqual(args.content.body.sections[0].blocks.map((b) => b.type), ["paragraph", "bullets", "table"]);
    assert.deepEqual([args.content.body.sections[0].blocks[0].text, args.content.body.sections[0].blocks[0].refs], ["고친 문장", ["S1"]]);
    assert.deepEqual(args.content.body.sections[0].blocks[1].items, ["가", "다"]);
    assert.ok(text(view.container).includes("고친 문장"), "저장 뒤 뷰어가 편집본을 보여 준다");
    assert.equal(buttonByText(view.container, "저장"), undefined, "저장 뒤 편집기가 닫힌다");
  } finally { await view.close(); }
});

test("편집 저장이 거부되면 안전한 안내를 보이고 편집 내용을 잃지 않으며, 취소하면 그대로 닫는다. 지원하지 않는 유형은 편집 버튼이 없다", async () => {
  const studio = fakeStudio();
  studio.getOutput = async (id) => ({ ...item({ output_id: id }), settings: {}, evidence: [], assets: [], revision: { content: REPORT_CONTENT } });
  studio.createRevision = async () => { const error = new Error("x"); error.code = "STUDIO_INPUT_INVALID"; throw error; };
  const view = await mount(studio);
  try {
    await view.click(findElements(view.container, (n) => n.tagName === "BUTTON" && (n.getAttribute?.("aria-label") ?? "").includes("보고서 1"))[0]);
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    await view.click(buttonByText(view.container, "편집"));
    const paragraph = byLabel(view.container, "섹션 1 문단 1");
    paragraph.value = "고친 문장";
    await view.act(async () => reactProps(paragraph).onChange({ target: paragraph, currentTarget: paragraph }));
    await view.click(buttonByText(view.container, "저장"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.ok(findElements(view.container, (n) => n.getAttribute?.("role") === "alert")[0].textContent.includes("저장하지 못했습니다"));
    assert.equal(byLabel(view.container, "섹션 1 문단 1").value, "고친 문장");
    await view.click(buttonByText(view.container, "취소"));
    assert.equal(buttonByText(view.container, "저장"), undefined);
  } finally { await view.close(); }
});

test("표 유형 산출물에는 편집 버튼이 없다", async () => {
  const table = fakeStudio([item({ output_id: OID("t"), type_id: "data_table", title: "표 1" })]);
  table.getOutput = async (id) => ({ ...item({ output_id: id, type_id: "data_table", title: "표 1" }), settings: {}, evidence: [], assets: [], revision: { content: { body: { title: "표", columns: [{ key: "a", label: "A", type: "text" }], rows: [{ cells: { a: { value: "1", refs: [] } } }], notes: [] }, warnings: [] } } });
  const viewTable = await mount(table);
  try {
    await viewTable.click(findElements(viewTable.container, (n) => n.tagName === "BUTTON" && (n.getAttribute?.("aria-label") ?? "").includes("표 1"))[0]);
    await viewTable.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.equal(buttonByText(viewTable.container, "편집"), undefined);
  } finally { await viewTable.close(); }
});

// ---- 대화 수정(WO-K5) ----
const chatStudio = (over = {}) => {
  const studio = fakeStudio([item(over)]);
  studio.getOutput = async (id) => ({ ...item({ output_id: id, ...over }), settings: {}, evidence: [], assets: [], revision: { content: { body: { title: "제목", summary: "요약", sections: [] } } } });
  studio.listEditTurns = async () => [];
  return studio;
};
async function openFirst(view) {
  await view.click(findElements(view.container, (n) => n.tagName === "BUTTON" && (n.getAttribute?.("aria-label") ?? "").includes("보고서 1"))[0]);
  await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
}

test("panel shows chat for completed text outputs only", async () => {
  const view = await mount(chatStudio());
  try {
    await openFirst(view);
    assert.ok(byLabel(view.container, "대화로 수정 입력"));
    await view.click(buttonByText(view.container, "편집"));
    assert.equal(byLabel(view.container, "대화로 수정 입력"), undefined);
  } finally { await view.close(); }
});

test("panel hides chat for other types and without the adapter", async () => {
  for (const [over, drop] of [[{ type_id: "mind_map" }, false], [{}, true]]) {
    const studio = chatStudio(over);
    if (drop) delete studio.listEditTurns;
    const view = await mount(studio);
    try {
      await openFirst(view);
      assert.equal(byLabel(view.container, "대화로 수정 입력"), undefined);
    } finally { await view.close(); }
  }
});

test("설정 변경 후 다시 생성은 고른 형식을 함께 보내고 지금 형식으로 창을 연다", async () => {
  // 실제 화면: 형식을 바꿔도 regenerate에 formatId가 가지 않아 형식이 그대로였다.
  const studio = fakeStudio();
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "더보기: 보고서 1"));
    const menuitem = findElements(view.container, (n) => n.getAttribute?.("role") === "menuitem" && n.textContent.trim() === "설정 변경 후 다시 생성")[0];
    await view.click(menuitem);
    const select = findElements(view.container, (n) => n.getAttribute?.("id") === "studio-format")[0];
    assert.equal(reactProps(select).value, "summary");
    await view.act(async () => { reactProps(select).onChange({ target: { value: "custom" } }); });
    const custom = findElements(view.container, (n) => n.getAttribute?.("id") === "studio-custom")[0];
    await view.act(async () => { reactProps(custom).onChange({ target: { value: "세 줄로" } }); });
    const form = findElements(view.container, (n) => n.tagName === "FORM")[0];
    await view.act(async () => { reactProps(form).onSubmit({ preventDefault() {} }); });
    const [name, id, options] = studio.calls.at(-1);
    assert.deepEqual([name, id, options.formatId, options.settings.custom_instruction], ["regenerate", OID("a"), "custom", "세 줄로"]);
  } finally { await view.close(); }
});

test("메모를 고친 뒤 자동 저장 전에 목록으로 나가도 마지막 입력을 저장한다", async () => {
  // 실제 화면: 입력 후 1.5초 안에 나가면 타이머만 지워져 마지막 입력이 사라졌다.
  const memo = item({ output_id: OID("m"), type_id: "memo", format_id: null, title: "메모 1" });
  const studio = fakeStudio([memo]);
  studio.getOutput = async (id) => ({ ...memo, output_id: id, settings: {}, evidence: [], assets: [], revision: { content: { schema: "studio.memo.v1", body: { markdown: "처음" } } } });
  studio.createRevision = async (id, input) => { studio.calls.push(["revision", id, input.content.body.markdown]); return { output_id: id, revision_no: 2 }; };
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 메모 1"));
    const area = findElements(view.container, (n) => n.getAttribute?.("id") === "studio-memo-text")[0];
    await view.act(async () => { reactProps(area).onChange({ target: { value: "고친 메모" } }); });
    await view.click(byLabel(view.container, "목록으로"));
    assert.deepEqual(studio.calls.filter((call) => call[0] === "revision"), [["revision", OID("m"), "고친 메모"]]);
  } finally { await view.close(); }
});

test("보고서 구성 확인(NB3-U1 공통 경로): 멈춘 카드는 '구성 확인 필요'를 보이고, 확정하면 목록으로 돌아가 카드가 '확정한 구성으로 생성 중'이 된다", async () => {
  const studio = fakeStudio();
  const review = { title: "보고서 제목", summary: "요약", sections: [], outline_review: [{ heading: "배경", purpose: "왜" }, { heading: "결론", purpose: "무엇" }] };
  studio.getOutput = async (id) => ({ ...item({ output_id: id }), settings: {}, evidence: [], assets: [], revision: { content: { body: review, warnings: [] } } });
  const view = await mount(studio);
  try {
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    const card = () => findElements(view.container, (n) => n.getAttribute?.("class") === "studio-card")[0];
    assert.ok(card().textContent.includes("구성 확인 필요"));
    await view.click(byLabel(view.container, "열기: 보고서 1"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.equal(buttonByText(view.container, "편집"), undefined, "구성 검토 중에는 본문 편집 버튼이 없다");
    await view.click(buttonByText(view.container, "이 구성으로 작성"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    const [name, id, options] = studio.calls.at(-1);
    assert.deepEqual([name, id, options.settings.confirm_outline], ["regenerate", OID("a"), "no"]);
    assert.deepEqual(JSON.parse(options.settings.confirmed_outline).sections.map((s) => s.heading), ["배경", "결론"]);
    assert.equal(card().getAttribute("data-state"), "generating");
    assert.ok(card().textContent.includes("확정한 구성으로 생성 중"));
  } finally { await view.close(); }
});

// ---- 심층 조사(WO-N1 NB4-U2): 카드 진행 문구·실패·취소, 새 카드로 이동, 보고서의 근거 부족 문장·사용한 자료 ----
const wait = (view, ms = 20) => view.act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });
const cardOf = (container, title) => findElements(container, (n) => n.tagName === "LI" && n.getAttribute?.("class") === "studio-card" && n.textContent.includes(title))[0];
const bar = (card) => findElements(card, (n) => n.getAttribute?.("class") === "studio-progress")[0]?.childNodes[0];

test("심층 조사 카드 진행 문구 3단계: 계획 → 찾기 n/m → 작성, 진행 막대는 서버 진행률을 따른다", async () => {
  const studio = fakeStudio([
    item({ output_id: OID("1"), title: "조사 계획", status: "generating", progress: { pct: 5, note: "계획" } }),
    item({ output_id: OID("2"), title: "조사 찾기", status: "generating", progress: { pct: 37, note: "찾기 2/5" } }),
    item({ output_id: OID("3"), title: "조사 작성", status: "generating", progress: { pct: 70, note: "작성" } })]);
  const view = await mount(studio);
  try {
    await wait(view);
    const plan = cardOf(view.container, "조사 계획");
    const find = cardOf(view.container, "조사 찾기");
    const write = cardOf(view.container, "조사 작성");
    assert.match(plan.textContent, /조사 계획 세우는 중/u);
    assert.match(find.textContent, /자료 찾는 중 \(2\/5\)/u);
    assert.match(write.textContent, /보고서 작성 중/u);
    assert.equal(plan.getAttribute("data-research-step"), "plan");
    assert.equal(find.getAttribute("data-research-step"), "find");
    assert.equal(write.getAttribute("data-research-step"), "write");
    assert.equal(bar(find).style.width, "37%");
    assert.equal(bar(write).style.width, "70%");
    for (const card of [plan, find, write]) assert.ok(buttonByText(card, "취소"), "진행 중 조사는 취소할 수 있다");
  } finally { await view.close(); }
});

test("진행 문구가 없거나 조사 형식이 아니면 기존 문구를 그대로 쓰고, 폴링으로 단계가 바뀌면 문구도 바뀐다", async () => {
  const studio = fakeStudio([
    item({ output_id: OID("1"), title: "일반 보고서", status: "generating", progress: null }),
    item({ output_id: OID("2"), title: "다른 진행", status: "generating", progress: { pct: 40, note: "소목차 작성 1/3: 개요" } }),
    item({ output_id: OID("3"), title: "슬라이드", type_id: "slides", status: "generating", progress: { pct: 10, note: "계획" } })]);
  const view = await mount(studio);
  try {
    await wait(view);
    assert.match(cardOf(view.container, "일반 보고서").textContent, /생성 중…/u);
    assert.match(cardOf(view.container, "다른 진행").textContent, /생성 중…/u);
    assert.doesNotMatch(cardOf(view.container, "다른 진행").textContent, /소목차/u, "알 수 없는 진행 메모 원문은 보이지 않는다");
    assert.match(cardOf(view.container, "슬라이드").textContent, /생성 중…/u, "보고서가 아니면 조사 문구를 쓰지 않는다");
    assert.equal(cardOf(view.container, "일반 보고서").getAttribute("data-research-step"), null);
    studio.outputs[0] = { ...studio.outputs[0], progress: { pct: 21, note: "찾기 1/4" } };
    await wait(view, 1700);
    assert.match(cardOf(view.container, "일반 보고서").textContent, /자료 찾는 중 \(1\/4\)/u);
  } finally { await view.close(); }
});

test("심층 조사 실패 문구: 시간 초과·범위 사용 불가·연결 실패·찾기 불가·자료 없음·검증 실패·유형 불가, 코드 원문은 보이지 않는다", async () => {
  const cases = [["RESEARCH_TIMEOUT", /제한 시간 안에 끝나지 않아/u], ["DISCOVERY_SCOPE_UNAVAILABLE", /고른 범위를 지금 쓸 수 없어 조사하지 못했습니다/u],
    ["DISCOVERY_CONNECTOR_FAILED", /지식 연결이 응답하지 않아 조사하지 못했습니다/u], ["DISCOVERY_UNAVAILABLE", /자료 찾기를 지금 쓸 수 없어 조사하지 못했습니다/u],
    ["RESEARCH_NO_EVIDENCE", /조사에 쓸 자료를 찾지 못했습니다/u], ["STUDIO_VALIDATION_FAILED", /결과를 검증하지 못했습니다/u], ["STUDIO_TYPE_UNAVAILABLE", /아직 제공하지 않는 유형입니다/u]];
  const studio = fakeStudio(cases.map(([code], i) => item({ output_id: OID(String(i)), title: `조사 ${i}`, status: "failed", error_code: code })));
  const view = await mount(studio);
  try {
    await wait(view);
    cases.forEach(([code, pattern], i) => {
      const card = cardOf(view.container, `조사 ${i}`);
      assert.match(card.textContent, pattern, code);
      assert.doesNotMatch(card.textContent, new RegExp(code, "u"));
      assert.ok(buttonByText(card, "다시 시도"), "실패한 조사는 다시 시도할 수 있다");
    });
  } finally { await view.close(); }
});

test("심층 조사 취소: 취소를 누르면 기존 취소 경로를 부르고, 취소된 카드는 '취소됨'이다", async () => {
  const studio = fakeStudio([item({ output_id: OID("1"), title: "조사 중", status: "generating", progress: { pct: 37, note: "찾기 2/5" } }),
    item({ output_id: OID("2"), title: "취소한 조사", status: "cancelled" })]);
  const view = await mount(studio);
  try {
    await wait(view);
    await view.click(buttonByText(cardOf(view.container, "조사 중"), "취소"));
    assert.deepEqual(studio.calls.at(-1), ["cancel", OID("1")]);
    assert.match(cardOf(view.container, "취소한 조사").textContent, /취소됨/u);
  } finally { await view.close(); }
});

test("새 카드로 이동: focusOutputRequest를 받으면 보기를 닫고 목록을 다시 읽어 그 카드로 스크롤하고 강조한다", async () => {
  const studio = fakeStudio([item()]);
  const scrolled = [];
  const view = await mount(studio);
  const proto = Object.getPrototypeOf(view.container);
  proto.scrollIntoView = function scrollIntoView() { scrolled.push(this.getAttribute("data-output-id")); };
  try {
    await wait(view);
    await view.click(byLabel(view.container, "열기: 보고서 1"));
    await wait(view);
    assert.ok(findElements(view.container, (n) => n.getAttribute?.("class") === "studio-detail")[0], "보기가 열려 있다");
    studio.outputs.unshift(item({ output_id: OID("r"), title: "새 조사", status: "queued", current_revision: 0, progress: null }));
    await view.rerender({ focusOutputRequest: { outputId: OID("r"), nonce: 1 } });
    await wait(view);
    assert.equal(findElements(view.container, (n) => n.getAttribute?.("class") === "studio-detail")[0], undefined, "보기를 닫고 목록으로");
    const card = cardOf(view.container, "새 조사");
    assert.ok(card, "다시 읽은 목록에 새 카드가 있다");
    assert.equal(card.getAttribute("data-output-id"), OID("r"));
    assert.equal(card.getAttribute("data-focused"), "true");
    assert.equal(cardOf(view.container, "보고서 1").getAttribute("data-focused"), null);
    assert.deepEqual(scrolled.filter(Boolean), [OID("r")]);
  } finally { delete proto.scrollIntoView; await view.close(); }
});

test("조사 보고서 보기: 근거 있는 문장은 S 라벨 근거 번호로, 근거 부족 문장은 표시를 붙여 구분하고 그 아래 사용한 자료가 보인다", async () => {
  const candidate = (n, kind = "document") => ({ candidate_id: `cand-${n}`, kind, title: `자료 ${n}`, origin_label: "Daon2-RAG 문서", reason: "관련", preview: "미리보기",
    action: kind === "document" ? "add_source" : "add_scope", ref: kind === "document" ? { kind, project_id: "p", work_package_id: "w", document_id: `d${n}`, document_version: "v" } : { kind, project_id: "p", work_package_id: `w${n}` } });
  const research = { query: "청구", sub_questions: ["서류"], candidates: [candidate(1), candidate(2), candidate(3, "knowledge_package")], unavailable: [], tool_calls: 2 };
  const studio = fakeStudio();
  studio.getOutput = async (id) => ({ ...item({ output_id: id }), settings: {}, assets: [],
    evidence: [{ ref_id: "S1", source_version_id: null, source_name: "자료 1", locator_kind: "research", locator_value: "cand-1", origin: "connector:daon2_rag" },
      { ref_id: "S3", source_version_id: null, source_name: "자료 3", locator_kind: "research", locator_value: "cand-3", origin: "daon_knowledge" }],
    revision: { content: { schema: "studio.report.v1", warnings: [{ code: "UNSUPPORTED_CLAIM", path: "sections[0].blocks[1]" }],
      body: { title: "조사", summary: "", sections: [{ heading: "서류", blocks: [{ type: "paragraph", text: "청구서를 냅니다.", refs: ["S1", "S3"] },
        { type: "paragraph", text: "근거 부족: 바로 지급됩니다.", refs: [] }] }] }, research } } });
  studio.researchOf = (output) => { const r = output?.revision?.content?.research; return r ? { query: r.query, subQuestions: r.sub_questions, candidates: r.candidates, unavailable: r.unavailable, toolCalls: r.tool_calls } : null; };
  studio.addSourceDiscovery = async (ref) => { studio.calls.push(["add", ref]); return { added: "source", sourceId: "src-new" }; };
  const discovered = [];
  const view = await mount(studio, { onDiscoveryAdded: (event) => discovered.push(event) });
  try {
    await wait(view);
    await view.click(byLabel(view.container, "열기: 보고서 1"));
    await wait(view);
    const refs = findElements(view.container, (n) => n.tagName === "BUTTON" && n.getAttribute?.("class") === "studio-ref").map((n) => n.textContent);
    assert.deepEqual(refs, ["[S1]", "[S3]"], "조사 보고서 근거 번호는 사용한 자료 라벨과 같다");
    const unsupported = findElements(view.container, (n) => n.tagName === "P" && n.getAttribute?.("data-unsupported") === "true")[0];
    assert.ok(unsupported, "근거 부족 문장은 따로 표시된다");
    assert.match(unsupported.textContent, /근거 부족/u);
    assert.match(unsupported.textContent, /바로 지급됩니다/u);
    const grounded = findElements(view.container, (n) => n.tagName === "P" && n.textContent.includes("청구서를 냅니다."))[0];
    assert.equal(grounded.getAttribute("data-unsupported"), null);
    const section = findElements(view.container, (n) => n.tagName === "SECTION" && n.getAttribute?.("aria-label") === "사용한 자료")[0];
    assert.ok(section, "보고서 아래 사용한 자료");
    assert.match(section.textContent, /사용한 자료 3개/u);
    await view.click(findElements(section, (n) => n.tagName === "INPUT" && n.getAttribute?.("aria-label") === "자료 2 선택")[0]);
    await view.click(buttonByText(section, "선택한 자료 추가"));
    await wait(view);
    assert.deepEqual(studio.calls.filter((c) => c[0] === "add").map((c) => c[1].document_id), ["d2"]);
    assert.deepEqual(discovered, [{ sourceIds: ["src-new"], scopeAdded: false }]);
  } finally { await view.close(); }
});

test("조사 보고서가 아니면(research 없음) 사용한 자료를 그리지 않고 근거 번호는 기존처럼 순번이다", async () => {
  const studio = fakeStudio();
  studio.getOutput = async (id) => ({ ...item({ output_id: id }), settings: {}, assets: [], evidence: [{ ref_id: "S1", source_version_id: "sv-1", source_name: "a.pdf", locator_kind: "page", locator_value: "1" }],
    revision: { content: { ...REPORT_CONTENT } } });
  studio.researchOf = () => null;
  const view = await mount(studio);
  try {
    await wait(view);
    await view.click(byLabel(view.container, "열기: 보고서 1"));
    await wait(view);
    assert.equal(findElements(view.container, (n) => n.tagName === "SECTION" && n.getAttribute?.("aria-label") === "사용한 자료")[0], undefined);
    assert.deepEqual(findElements(view.container, (n) => n.getAttribute?.("class") === "studio-ref").map((n) => n.textContent), ["[1]"]);
  } finally { await view.close(); }
});

// 웹 페이지 보기(WO-N8): 상세 본문은 web_page일 때만 칸 배치 클래스를 받는다(다른 유형 배치는 그대로).
test("웹 페이지 상세만 본문에 web_page 칸 배치 클래스를 붙인다", async () => {
  const page = item({ output_id: OID("e"), type_id: "web_page", title: "웹 페이지 1" });
  const studio = fakeStudio([page, item()]);
  const base = studio.getOutput;
  studio.getOutput = async (id) => id === OID("e")
    ? { ...page, settings: {}, assets: [], evidence: [], revision: { content: { body: { title: "페이지", request: "r", sections: [], html: "<!DOCTYPE html><p>x</p>" }, warnings: [] } } }
    : base(id);
  const view = await mount(studio);
  const bodyClass = () => findElements(view.container, (n) => n.getAttribute?.("class")?.startsWith("studio-detail__body"))[0]?.getAttribute("class");
  try {
    await view.click(byLabel(view.container, "열기: 웹 페이지 1"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.equal(bodyClass(), "studio-detail__body studio-detail__body--web-page");
    await view.click(byLabel(view.container, "목록으로"));
    await view.click(byLabel(view.container, "열기: 보고서 1"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.equal(bodyClass(), "studio-detail__body");
  } finally { await view.close(); }
});

test("html 내려받기 메뉴의 '출처 목록 넣기'는 menuitemcheckbox이고 클릭·Enter·Space로 바뀌어 내려받기에 실린다", async () => {
  const page = item({ output_id: OID("e"), type_id: "web_page", title: "웹 페이지 1" });
  const studio = fakeStudio([page]);
  studio.exportFormats = () => ["html"];
  studio.getOutput = async () => ({ ...page, settings: {}, assets: [], evidence: [], revision: { content: { body: { title: "페이지", sections: [], html: "<p>x</p>" }, warnings: [] } } });
  const downloads = [];
  studio.downloadExport = async (id, format, options) => { downloads.push([id, format, options]); return { bytes: new Uint8Array([60]), contentType: "text/html", disposition: "" }; };
  const priorCreate = globalThis.URL.createObjectURL; const priorRevoke = globalThis.URL.revokeObjectURL;
  globalThis.URL.createObjectURL = () => "blob:fake"; globalThis.URL.revokeObjectURL = () => {};
  const view = await mount(studio);
  try {
    await view.click(byLabel(view.container, "열기: 웹 페이지 1"));
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    await view.click(buttonByText(view.container, "다운로드"));
    const check = () => findElements(view.container, (n) => n.getAttribute?.("role") === "menuitemcheckbox")[0];
    assert.ok(check(), "menuitemcheckbox가 있다");
    assert.ok(check().textContent.includes("출처 목록 넣기"));
    assert.equal(check().getAttribute("aria-checked"), "true");
    assert.equal(check().getAttribute("tabindex") ?? check().getAttribute("tabIndex"), "0");
    await view.click(check());
    assert.equal(check().getAttribute("aria-checked"), "false");
    const key = async (name) => { let prevented = false; await view.act(async () => reactProps(check()).onKeyDown({ key: name, preventDefault() { prevented = true; }, stopPropagation() {} })); return prevented; };
    assert.equal(await key("Enter"), true);
    assert.equal(check().getAttribute("aria-checked"), "true");
    assert.equal(await key(" "), true);
    assert.equal(check().getAttribute("aria-checked"), "false");
    assert.equal(await key("Tab"), false);
    assert.equal(check().getAttribute("aria-checked"), "false");
    await view.click(findElements(view.container, (n) => n.getAttribute?.("role") === "menuitem" && n.textContent === "HTML")[0]);
    await view.act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    assert.deepEqual(downloads, [[OID("e"), "html", { includeSources: false }]]);
    // Escape로 메뉴 닫기는 그대로 동작한다
    await view.click(buttonByText(view.container, "다운로드"));
    const menu = findElements(view.container, (n) => n.getAttribute?.("role") === "menu")[0];
    await view.act(async () => reactProps(menu).onKeyDown({ key: "Escape" }));
    assert.equal(findElements(view.container, (n) => n.getAttribute?.("role") === "menu").length, 0);
  } finally {
    globalThis.URL.createObjectURL = priorCreate; globalThis.URL.revokeObjectURL = priorRevoke;
    await view.close();
  }
});
