import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

async function bundle(output) {
  const root = path.resolve(import.meta.dirname, "../..");
  const { build } = await import("vite");
  await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
    lib: { entry: path.join(root, "packages/ui/src/authoring-wizard.jsx"), formats: ["es"], fileName: "authoring-wizard-react" },
    rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
  const built = (await readdir(output)).find((name) => name.startsWith("authoring-wizard-react") && /\.m?js$/u.test(name));
  return import(`${pathToFileURL(path.join(output, built)).href}?v=${Date.now()}`);
}

const OID = `sv2-${"c".repeat(32)}`;
const base = { output_id: OID, template_id: "rfp_response_proposal", request_text: "", inputs: {}, assumptions: [], requirements: [], plan: null, output_formats: ["docx"],
  error_code: null, document: null, knowledge_count: 0, job_status: "completed", revision_no: 1 };
const REQUIRED = [{ key: "rfp_document", question: "제안요청서(RFP)로 사용할 소스를 선택해 주세요.", kind: "source_ref", required: true, choices: [] }];
const DOCUMENT = { notice: "AI 작성 초안, 전문가 검토 필요", sections: [{ key: "a", title: "1. 사업의 이해", paragraphs: [{ text: "근거 있는 문장. 가격은 [작성 필요]", refs: ["S1"], origin: "sourced" }, { text: "새 문장", refs: [], origin: "new" }], open_items: [] }],
  coverage: [{ requirement_id: "REQ-001", text: "다중 인증 지원", status: "covered" }, { requirement_id: "REQ-002", text: "암호화", status: "missing" }],
  checks: [{ id: "rfp_requirement_coverage", title: "요구사항 대응표", status: "done", summary: { covered: 1, partial: 0, missing: 1 } },
    { id: "proposal_required_sections", title: "제안서 필수 섹션 점검", status: "done", results: [{ rule_id: "r1", status: "pass", message: "확인" }] }], open_items: ["price_schedule: [작성 필요]"] };

function fakeStudio(sessions) {
  const calls = [];
  const queue = [...sessions];
  return { calls, downloadExport: async (id, format) => { calls.push(["download", id, format]); return { bytes: new Uint8Array([1]), contentType: "application/zip", disposition: "" }; },
    authoring: {
      listTemplates: async () => [{ template_id: "rfp_response_proposal", title: "RFP 대응 제안서", description: "설명", version: 1 }],
      createSession: async (input) => { calls.push(["create", input]); return { created: true, ...queue[0] }; },
      getSession: async () => queue.length > 1 ? queue.shift() : queue[0],
      answer: async (id, input) => { calls.push(["answer", input]); queue.shift(); return { output_id: id, revision_no: 2, state: "analyzing", queued: true }; },
      review: async (id, input) => { calls.push(["review", input]); queue.shift(); return { output_id: id, revision_no: 4, state: "generating", queued: true }; },
      listConnectors: async () => [], listDocuments: async () => [],
    } };
}

async function mount(studio, props = {}) {
  const dom = installMinimalDom();
  const root = path.resolve(import.meta.dirname, "../..");
  const output = await mkdtemp(path.join(root, ".authoring-wizard-react-"));
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const { AuthoringWizard } = await bundle(output);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(AuthoringWizard, { studio, sources: [{ sourceVersionId: "sv-rfp", filename: "rfp.txt", ready: true }], ...props })); });
  const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  return { container, act, flush, click: async (node) => { await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await flush(); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await rm(output, { recursive: true, force: true }); } };
}

const text = (v) => v.container.textContent;

test("템플릿 선택 → 세션 생성 → 필수 질문(소스 선택)이 보인다", async () => {
  const studio = fakeStudio([{ ...base, state: "collecting", pending_questions: REQUIRED, requests: [{ request: "select_source", key: "rfp_document" }] }]);
  const view = await mount(studio);
  try {
    await view.flush();
    assert.ok(text(view).includes("RFP 대응 제안서"));
    await view.click(buttonByText(view.container, "시작"));
    assert.deepEqual(studio.calls[0], ["create", { templateId: "rfp_response_proposal" }]);
    assert.ok(text(view).includes("제안요청서(RFP)로 사용할 소스를 선택해 주세요."));
    assert.ok(text(view).includes("rfp.txt"));
    assert.ok(text(view).includes("1. 입력"));
  } finally { await view.close(); }
});

test("검토 단계: 요구사항 수정·삭제·섹션 순서 후 확정하면 review API가 확정으로 호출된다", async () => {
  const review = { ...base, state: "review", pending_questions: [], requests: [], revision_no: 3, requirements: [
    { id: "REQ-001", text: "다중 인증", mandatory: true, category: "", refs: [] }, { id: "REQ-002", text: "암호화", mandatory: true, category: "", refs: [] }],
    plan: { sections: [{ key: "a", title: "1. 사업의 이해", purpose: "", knowledge_refs: [], requirement_ids: ["REQ-001"] }, { key: "b", title: "2. 수행 방안", purpose: "", knowledge_refs: [], requirement_ids: ["REQ-002"] }] } };
  const studio = fakeStudio([review]);
  const view = await mount(studio, { outputId: OID });
  try {
    await view.flush();
    assert.ok(text(view).includes("요구사항 확인 (2건)"));
    await view.click(findElements(view.container, (n) => n.getAttribute?.("aria-label") === "REQ-002 삭제")[0]);
    await view.click(findElements(view.container, (n) => n.getAttribute?.("aria-label") === "2. 수행 방안 위로")[0]);
    await view.click(buttonByText(view.container, "확정하고 초안 만들기"));
    const [, input] = studio.calls.find((c) => c[0] === "review");
    assert.equal(input.confirm, true);
    assert.equal(input.expectedRevision, 3);
    assert.deepEqual(input.requirements.map((r) => r.id), ["REQ-001"]);
    assert.deepEqual(input.planSections.map((s) => s.key), ["b", "a"]);
    assert.deepEqual(input.outputFormats, ["docx"]);
  } finally { await view.close(); }
});

test("완료 화면은 고지 문구·탭·[작성 필요] 강조·다운로드를 제공한다", async () => {
  const done = { ...base, state: "completed", pending_questions: [], requests: [], revision_no: 5, document: DOCUMENT };
  const studio = fakeStudio([done]);
  const view = await mount(studio, { outputId: OID });
  try {
    await view.flush();
    assert.ok(text(view).includes("AI 작성 초안, 전문가 검토 필요"));
    assert.ok(text(view).includes("신규 문장"));
    assert.ok(findElements(view.container, (n) => n.tagName === "MARK" && n.textContent === "[작성 필요]").length === 1);
    await view.click(buttonByText(view.container, "요구사항 대응표"));
    assert.ok(text(view).includes("누락"));
    await view.click(buttonByText(view.container, "점검"));
    assert.ok(text(view).includes("통과 — 확인"));
    await view.click(buttonByText(view.container, "가정·미결"));
    assert.ok(text(view).includes("price_schedule"));
    await view.click(buttonByText(view.container, "DOCX 다운로드"));
    assert.deepEqual(studio.calls.at(-1), ["download", OID, "docx"]);
  } finally { await view.close(); }
});

test("점검 탭: 근거 무결성과 용어 일관성 결과를 보인다(F6-13)", async () => {
  const checks = [...DOCUMENT.checks,
    { id: "evidence_integrity", title: "근거 무결성", status: "done", summary: { verified: 3, unverified: 1 }, items: [{ section_title: "1. 사업의 이해", text: "근거 없는 문장", reason: "no_ref" }] },
    { id: "term_consistency", title: "용어·일관성", status: "done", summary: { mixed: 1, synonym_only: 0 }, items: [{ kind: "mixed", found: "보상금", count: 2, preferred: "보험금" }] }];
  const done = { ...base, state: "completed", pending_questions: [], requests: [], revision_no: 5, document: { ...DOCUMENT, checks } };
  const view = await mount(fakeStudio([done]), { outputId: OID });
  try {
    await view.flush();
    await view.click(buttonByText(view.container, "점검"));
    assert.ok(text(view).includes("근거 확인 3 · 근거 미확인 1"));
    assert.ok(text(view).includes("근거 없는 문장"));
    assert.ok(text(view).includes("혼용 1"));
    assert.ok(text(view).includes('"보상금"(2회) → 기준 용어 "보험금"'));
  } finally { await view.close(); }
});

test("분석 중에는 진행 안내를, 오류는 안전한 문구를 보인다", async () => {
  const analyzing = { ...base, state: "analyzing", pending_questions: [], requests: [], job_status: "generating" };
  const view = await mount(fakeStudio([analyzing]), { outputId: OID });
  try {
    await view.flush();
    assert.ok(text(view).includes("RFP를 분석하고"));
  } finally { await view.close(); }
  const studio = fakeStudio([analyzing]);
  studio.authoring.getSession = async () => { const error = new Error("x"); error.code = "RESOURCE_UNAVAILABLE"; throw error; };
  const failing = await mount(studio, { outputId: OID });
  try {
    await failing.flush();
    assert.ok(findElements(failing.container, (n) => n.getAttribute?.("role") === "alert")[0].textContent.includes("찾을 수 없는 항목"));
  } finally { await failing.close(); }
});

// ---- 약관·계약서 템플릿(WO-A1 A2) ----
const TERMS_DOC = { notice: "AI 작성 초안, 전문가 검토 필요", style: "terms", coverage: [], requirements: [], assumptions: [], open_items: [],
  sections: [{ key: "premium", title: "제5장 보험료", delete_suggested: ["기준에만 있던 문장입니다."], paragraphs: [
    { text: "보험료를 납입한다. 연체 이자를 정한다.", refs: ["K1"], origin: "sourced", diff: { tag: "modified", sentences: [
      { text: "보험료를 납입한다.", tag: "unchanged", base: "보험료를 납입한다." }, { text: "연체 이자를 정한다.", tag: "modified", base: "연체 시 해지할 수 있다." }] } },
    { text: "자동이체 할인을 둔다.", refs: [], origin: "new", diff: { tag: "new", sentences: [{ text: "자동이체 할인을 둔다.", tag: "new", base: null }] } }], open_items: [] }],
  checks: [{ id: "terms_change_summary", title: "기준 약관 대비 변경 요약", status: "done", summary: { unchanged: 1, modified: 1, new: 1, delete_suggested: 1 } }] };
const CONTRACT_DOC = { notice: "AI 작성 초안, 전문가 검토 필요 · 법률 자문이 아닌 근거 대조입니다", style: "contract", coverage: [], requirements: [], assumptions: [], open_items: [],
  sections: [{ key: "price", title: "제3조(대금)", paragraphs: [{ text: "계약 대금은 [작성 필요]원으로 한다.", refs: ["L1"], origin: "sourced" }], open_items: [] }],
  checks: [{ id: "law_crosscheck", title: "법령 대조표", status: "done", notice: "법률 자문이 아닌 근거 대조입니다. 최종 판단은 전문가가 합니다.", summary: { related: 0, possible_conflict: 1 },
    rows: [{ section_key: "price", section_title: "제3조(대금)", law_ref: "L1", law: "가상 보험업법 제3조(조문 3)", article_excerpt: "…", relation: "possible_conflict", note: "한도가 다를 수 있다." }] }] };
const BASE_ONLY = { ...base, analysis: "base_document", style: "terms", output_choices: ["docx"], output_formats: ["docx"], requirements: [], knowledge_count: 6 };

test("약관 결과: 변경 표시 탭이 유지·수정·신규와 삭제 제안을 보이고, 요구사항 대응표 탭과 PPTX 다운로드는 없다", async () => {
  const studio = fakeStudio([{ ...BASE_ONLY, state: "completed", pending_questions: [], requests: [], revision_no: 5, document: TERMS_DOC }]);
  const view = await mount(studio, { outputId: OID });
  try {
    await view.flush();
    assert.equal(buttonByText(view.container, "요구사항 대응표"), undefined);
    assert.equal(buttonByText(view.container, "PPTX 다운로드"), undefined);
    assert.ok(buttonByText(view.container, "DOCX 다운로드") && buttonByText(view.container, "PDF 다운로드"));
    await view.click(buttonByText(view.container, "변경 표시"));
    for (const needle of ["유지", "수정", "신규", "삭제 제안", "기준에만 있던 문장입니다."]) assert.ok(text(view).includes(needle), needle);
    assert.equal(findElements(view.container, (n) => n.getAttribute?.("data-diff") === "modified")[0].getAttribute("title"), "기준: 연체 시 해지할 수 있다.");
    await view.click(buttonByText(view.container, "점검"));
    assert.ok(text(view).includes("유지 1 · 수정 1 · 신규 1 · 삭제 제안 1"));
  } finally { await view.close(); }
});

test("계약서 결과: 법령 대조 탭이 면책 문구와 충돌 가능 표시를 보인다", async () => {
  const studio = fakeStudio([{ ...BASE_ONLY, style: "contract", state: "completed", pending_questions: [], requests: [], revision_no: 5, document: CONTRACT_DOC }]);
  const view = await mount(studio, { outputId: OID });
  try {
    await view.flush();
    assert.ok(text(view).includes("법률 자문이 아닌"));
    await view.click(buttonByText(view.container, "법령 대조"));
    for (const needle of ["가상 보험업법 제3조(조문 3)", "충돌 가능(확인 필요)", "한도가 다를 수 있다.", "최종 판단은 전문가가 합니다."]) assert.ok(text(view).includes(needle), needle);
  } finally { await view.close(); }
});

test("기준 문서 템플릿의 확인 단계는 요구사항 없이 계획만 보이고, 확정하면 DOCX로 review를 호출한다", async () => {
  const review = { ...BASE_ONLY, state: "review", pending_questions: [], requests: [], revision_no: 3,
    plan: { sections: [{ key: "a", title: "제1장 총칙", purpose: "", knowledge_refs: ["K1"], requirement_ids: [] }, { key: "b", title: "제2장 보장내용", purpose: "", knowledge_refs: [], requirement_ids: [] }] } };
  const studio = fakeStudio([review]);
  const view = await mount(studio, { outputId: OID });
  try {
    await view.flush();
    assert.ok(!text(view).includes("요구사항 확인"));
    assert.ok(text(view).includes("제1장 총칙"));
    assert.equal(buttonByText(view.container, "요구사항 추가"), undefined);
    assert.ok(!text(view).includes("PPTX"));
    await view.click(buttonByText(view.container, "확정하고 초안 만들기"));
    const [, input] = studio.calls.find((c) => c[0] === "review");
    assert.deepEqual([input.confirm, input.outputFormats, input.planSections.map((s) => s.key)], [true, ["docx"], ["a", "b"]]);
  } finally { await view.close(); }
});

test("기준 문서 입력은 문서 종류를 지정해 조회하고, 비어 있는 컬렉션은 건너뛰어 처음 문서가 있는 컬렉션을 보여 준다", async () => {
  const asked = [];
  const studio = fakeStudio([{ ...BASE_ONLY, state: "collecting", requests: [{ request: "select_knowledge", key: "base_terms" }],
    pending_questions: [{ key: "base_terms", question: "기준이 될 기존 약관을 선택해 주세요.", kind: "knowledge_ref", required: true, choices: [], document_type: "insurance_terms" }] }]);
  studio.authoring.listConnectors = async () => [{ connector_id: `kc-${"a".repeat(32)}`, kind: "daon2_rag", name: "가상 Daon2-RAG", virtual: true,
    allowed_scopes: [{ project_id: "p1", work_package_id: "wp-empty" }, { project_id: "p1", work_package_id: "wp-terms" }] }];
  studio.authoring.listDocuments = async (_id, query) => { asked.push(query); return query.workPackageId === "wp-terms" ? [{ document_id: "doc-1", title: "합성 자동차 약관" }] : []; };
  const view = await mount(studio, { outputId: OID });
  try {
    await view.flush(); await view.flush();
    assert.ok(asked.every((q) => q.documentType === "insurance_terms"));
    assert.deepEqual(asked.map((q) => q.workPackageId), ["wp-empty", "wp-terms"]);
    assert.ok(text(view).includes("합성 자동차 약관"));
    assert.ok(findElements(view.container, (n) => n.getAttribute?.("aria-label") === "기준 약관").length === 1);
  } finally { await view.close(); }
});
