// 화면 확인용 시험 페이지(S7-07). 가짜 데이터로 Studio 패널·작성 마법사·노트북 도구를 띄운다. 계정·서버 연결이 없다.
import { createElement as h, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { StudioPanel } from "../../packages/ui/src/studio-panel.jsx";
import { AuthoringWizard } from "../../packages/ui/src/authoring-wizard.jsx";
import { NotebookTools } from "../../packages/ui/src/notebook-menu.jsx";
import { NotebookHome } from "../../packages/ui/src/notebook-home.jsx";
import { KnowledgeConnectorsPane } from "../../packages/ui/src/knowledge-connectors-pane.jsx";
import { TtsEnginesPane } from "../../packages/ui/src/tts-engines-pane.jsx";
import { OrganizationJoinForm } from "../../apps/web/components/organization-join-form.jsx";
import OrganizationAdminConsole from "../../apps/web/components/organization-admin-console.jsx";
import { AuthPane } from "../../apps/web/lib/auth-pane.jsx";
import { studioResearchOf } from "../../apps/web/lib/studio-v2-api.js";
import { AnswerProcess } from "../../packages/ui/src/answer-process.jsx";
import { ProductWorkspaceShell } from "../../packages/ui/src/product-workspace-shell.jsx";
import { QuestionToolsMenu } from "../../packages/ui/src/question-tools-menu.jsx";
import { ModelSelectionBar } from "../../packages/ui/src/model-selection-bar.jsx";
import { NotebookOverview } from "../../packages/ui/src/notebook-overview.jsx";
import { SettingsDialog } from "../../packages/ui/src/studio-dialogs.jsx";
import "../../packages/ui/src/answer-process.css";
import "./proposal.css";
import "@daon2-user/design-tokens/tokens.css";
import "../../apps/web/app/globals.css";
import "../../packages/ui/src/workspace.css";
import "../../packages/ui/src/workspace-polish.css";

const sid = (c) => `sv2-${c.repeat(32)}`;
const ev = (n) => ({ ref_id: `S${n}`, source_version_id: "sv-1", source_name: "보험약관.pdf", locator_kind: "page", locator_value: String(n), origin: "notebook_source", has_snapshot: false });
const item = (c, type_id, title, over = {}) => ({ output_id: sid(c), type_id, format_id: null, title, status: "completed", error_code: null, source_count: 3, current_revision: 1,
  created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:00:00Z", stale: false, ...over });
const OUTPUTS = [
  item("a", "report", "보험금 지급 요약 보고서"), item("b", "mind_map", "약관 개념 지도"), item("c", "quiz", "면책 기간 퀴즈"), item("d", "flashcards", "용어 카드"),
  item("e", "slides", "발표 자료"), item("f", "infographic", "보험금 지급 안내"), item("g", "data_table", "조항 비교표", { stale: true }), item("h", "memo", "메모"),
  item("k", "audio_overview", "보험금 지급 오디오 개요"), item("i", "report", "생성 중인 보고서", { status: "generating" }), item("j", "quiz", "실패한 퀴즈", { status: "failed", error_code: "STUDIO_GENERATION_FAILED" }),
  item("l", "audio_overview", "오디오 개요", { status: "failed", error_code: "EGRESS_DESTINATION_DENIED" }), item("m", "video_overview", "동영상 개요", { status: "failed", error_code: "EGRESS_DESTINATION_DENIED" }),
];
const BODIES = {
  report: { title: "보험금 지급 요약", summary: "청구서류 접수 후 3일 이내 지급합니다.", sections: [{ heading: "지급 기한", blocks: [{ type: "paragraph", text: "보험금은 청구서류를 접수한 날부터 3일 이내에 지급한다.", refs: ["S1"] }, { type: "bullets", items: ["한도 1,000,000원", "면책 기간 90일"], refs: ["S2"] }] }] },
  mind_map: { root: "r", nodes: [{ id: "r", parent: null, label: "보험약관", summary: "", refs: ["S1"] }, { id: "a", parent: "r", label: "지급", summary: "", refs: ["S1"] }, { id: "b", parent: "r", label: "면책", summary: "", refs: ["S2"] }, { id: "c", parent: "a", label: "한도", summary: "", refs: ["S1"] }] },
  quiz: { questions: [{ q: "지급 기한은?", options: ["3일", "5일", "7일", "10일"], answer_index: 0, explanation: "접수일부터 3일 이내", refs: ["S1"] }] },
  flashcards: { cards: [{ front: "면책 기간", back: "계약일부터 90일", refs: ["S2"] }, { front: "지급 한도", back: "사고당 1,000,000원", refs: ["S1"] }] },
  slides: { title: "발표", slides: [{ layout: "title", title: "보험금 지급", bullets: [], notes: "", refs: ["S1"] }, { layout: "bullets", title: "핵심", bullets: ["3일 이내 지급", "한도 1,000,000원"], notes: "발표자 노트", refs: ["S1"] }] },
  infographic: { title: "보험금 지급 안내", sections: [{ headline: "지급 기한", value: "3일", refs: ["S1"] }, { headline: "면책 기간", value: "90일", refs: ["S2"] }] },
  data_table: { title: "조항 비교", columns: [{ key: "a", label: "조항", type: "text" }, { key: "b", label: "기한", type: "text" }], rows: [{ cells: { a: { value: "지급", refs: ["S1"] }, b: { value: "3일", refs: ["S1"] } } }] },
  memo: { markdown: "# 메모\n본문입니다." },
  audio_overview: { title: "보험금 지급 이야기", duration_ms: 6000, engine: "supertonic", voices: { A: "F1", B: "M1" }, script: [
    { speaker: "A", text: "안녕하세요, 오늘은 보험금 지급 기한을 알아봅니다.", refs: ["S1"], start_ms: 0, end_ms: 1800 },
    { speaker: "B", text: "청구서류를 접수한 날부터 3일 이내에 지급합니다.", refs: ["S1"], start_ms: 2100, end_ms: 4000 },
    { speaker: "A", text: "면책 기간은 어떻게 되나요?", refs: ["S2"], start_ms: 4300, end_ms: 5000 },
    { speaker: "B", text: "계약일부터 90일입니다.", refs: ["S2"], start_ms: 5200, end_ms: 6000 }] },
};

function makeStudio() {
  const types = ["audio_overview", "slides", "video_overview", "mind_map", "report", "flashcards", "quiz", "infographic", "data_table", "memo"].map((type_id) => ({
    type_id, available: !["video_overview"].includes(type_id), formats: [], presets: type_id === "report" ? ["summary", "briefing"] : [], export_formats: type_id === "audio_overview" ? ["mp3"] : ["docx", "pdf"],
    default_format: null, settings_schema: { type: "object", properties: type_id === "audio_overview"
      ? { focus: { type: "string" }, length: { type: "string", enum: ["short", "normal", "long"] }, engine: { type: "string", enum: ["supertonic", "qwen3-tts"] },
          voice_a: { type: "string", enum: ["F1", "F2", "M1", "M2"] }, voice_b: { type: "string", enum: ["F1", "F2", "M1", "M2"] } }
      : { focus: { type: "string" } } } }));
  types.limits = { userConcurrency: 2 };
  const png = fetch("./info.png").then((r) => r.arrayBuffer());
  return {
    listTypes: async () => types,
    listOutputs: async () => ({ items: OUTPUTS, nextCursor: null }),
    getOutput: async (id) => { const base = OUTPUTS.find((o) => o.output_id === id); return { ...base, settings: {}, assets: [], evidence: [ev(1), ev(2)], revision: { content: { body: BODIES[base.type_id] ?? {}, warnings: [] } } }; },
    getProvenance: async () => ({ type_id: "report", format_id: "summary", instruction: { focus: null, customization_applied: true }, settings: {}, sources: [{ source_version_id: "sv-1", name: "보험약관.pdf", changed: false }], evidence: [ev(1)] }),
    getSharing: async () => ({ scope: "notebook", public_link: false, notebook_id: "nb-1" }),
    downloadExport: async () => ({ bytes: new Uint8Array(await png), contentType: "image/png", disposition: "" }),
    getAudio: async () => ({ bytes: new Uint8Array(await (await fetch("./audio.mp3")).arrayBuffer()), contentType: "audio/mpeg", durationMs: 6000 }),
    exportFormats: () => ["docx", "pdf"],
    createOutput: async () => ({ output_id: sid("k"), job_id: "j", status: "queued" }),
    createMemo: async () => ({ output_id: sid("m") }),
    getEvidenceContent: async () => ({ kind: "excerpt", text: "청구서류를 접수한 날부터 3일 이내에 보험금을 지급한다." }),
    recordLearningAttempt: async () => ({}), listLearningAttempts: async () => [],
    getCustomization: async () => ({ instruction: "존댓말로 짧게 답해 주세요.", version: 1, etag: '"e"' }), saveCustomization: async (i) => ({ instruction: i, version: 2, etag: '"e2"' }),
    copyNotebook: async () => ({ notebook_id: "nb-2", title: "사본", copied: {}, skipped: { sources: 0, memos: 0, outputs: 0 } }), clearChatHistory: async () => {},
  };
}

const review = { output_id: sid("w"), template_id: "rfp_response_proposal", state: "review", requirements: [{ id: "REQ-001", text: "다중 인증을 지원해야 한다", mandatory: true, category: "", refs: [] }, { id: "REQ-002", text: "저장 데이터는 암호화한다", mandatory: false, category: "", refs: [] }],
  plan: { sections: [{ key: "a", title: "1. 사업의 이해", purpose: "", knowledge_refs: [], requirement_ids: ["REQ-001"] }, { key: "b", title: "2. 수행 방안", purpose: "", knowledge_refs: [], requirement_ids: ["REQ-002"] }] },
  output_formats: ["docx"], pending_questions: [], requests: [], inputs: {}, assumptions: [], error_code: null, document: null, knowledge_count: 3, job_status: "completed", revision_no: 3 };

// 답변 과정(NB1-U1) 5상태: 정상·근거 부족·외부 전송 차단·일반 대화·기록 없음. 값은 answer_process.v1 예시다.
const processItem = (over = {}) => ({ title: "보험약관.pdf", page: 3, origin: "raw_source", source_id: "source-1", source_version_id: "sv-1", ...over });
const processNormal = { version: 1,
  scope: { source_count: 2, knowledge_packages: [{ name: "제안서 작업" }], tools: null },
  evidence: { searched: 24, selected: [processItem(), processItem({ page: 7 }), processItem({ title: "가입 안내.txt", page: null, source_id: "source-2", source_version_id: "sv-2" })] },
  egress: { decision: "allowed", masked: true, redacted: false, policy_ref: "3f2a9c1b0d4e" },
  model: { connection: "Media Bridge", model: "uss/solar-pro4", reasoning: "high" },
  verification: { citations: 3, valid: true, insufficient: false, retried: false } };
const PROCESS_STATES = {
  "process-normal": { label: "답변 과정: 정상", process: processNormal, answer: "보험금 청구는 사고일로부터 3년 안에 해야 합니다." },
  "process-insufficient": { label: "답변 과정: 근거 부족", process: { ...processNormal, evidence: { searched: 18, selected: [] }, verification: { citations: 0, valid: true, insufficient: true, retried: true } }, answer: "선택한 소스에서 질문에 답할 근거를 찾지 못했습니다." },
  "process-blocked": { label: "답변 과정: 외부 전송 차단", process: { ...processNormal, egress: { decision: "blocked", masked: false, redacted: false, policy_ref: "3f2a9c1b0d4e" }, model: null, verification: null }, error: "질문 실행에 실패했습니다. (EGRESS_POLICY_DENIED) 입력을 확인한 뒤 다시 제출해 주세요." },
  "process-general": { label: "답변 과정: 일반 대화", process: { ...processNormal, scope: { source_count: 0, knowledge_packages: [], tools: null }, evidence: null, egress: { decision: "not_needed", masked: false, redacted: false, policy_ref: null } }, answer: "안녕하세요. 무엇을 도와드릴까요?" },
  "process-none": { label: "답변 과정: 기록 없음", process: null, answer: "이전에 저장된 답변입니다." },
};
function ProcessHarness({ state }) {
  const view = PROCESS_STATES[state];
  const processView = h(AnswerProcess, { process: view.process, defaultExpanded: true, canOpenEvidence: (item) => item.source_id === "source-1", onOpenEvidence: () => {} });
  return h("div", { className: "conversation-transcript", "data-harness-state": state, style: { maxWidth: 640, background: "var(--daon-color-surface)", border: "1px solid var(--daon-color-border)", borderRadius: 12 } },
    h("article", { className: "user-message" }, h("div", null, h("span", { className: "message-author" }, "나"), h("p", null, "보험금 청구 기한을 알려 주세요"))),
    view.error ? h("div", { className: "inline-alert compact", role: "alert" }, view.error, h("div", { className: "answer-process-row" }, processView))
      : h("div", null,
        h("article", { className: "assistant-message" }, h("div", { className: "assistant-avatar", "aria-hidden": "true" }, "D"), h("div", null, h("span", { className: "message-author" }, "Daon"), h("p", null, view.answer))),
        h("div", { className: "answer-process-row" }, processView)));
}

// 메모를 소스로(NB1-U2) 상태: 버튼 3상태·진행 중·실패 문구는 Studio 메모 보기, 메모 표시·원본 메모 없음은 노트북 소스 목록.
// 진행 중·실패는 화면에서 버튼을 눌러 만든다(진행 중은 응답을 끝내지 않고, 실패는 MEMO_EMPTY로 답한다).
const MEMO_ID = sid("n");
const memoOutput = item("n", "memo", "회의 메모", { current_revision: 3 });
const linkOf = (outdated) => ({ source_id: "memo-source-1", reflected_revision_no: outdated ? 2 : 3, outdated });
const MEMO_STATES = {
  "memo-create": { label: "메모→소스: 소스로 사용", link: null },
  "memo-reflect": { label: "메모→소스: 소스에 반영", link: linkOf(true) },
  "memo-same": { label: "메모→소스: 소스와 같음", link: linkOf(false) },
  "memo-busy": { label: "메모→소스: 진행 중(버튼 누르기)", link: null, create: () => new Promise(() => {}) },
  "memo-error": { label: "메모→소스: 실패 문구(버튼 누르기)", link: null, create: async () => { throw Object.assign(new Error("MEMO_EMPTY"), { code: "MEMO_EMPTY", status: 422 }); } },
  "memo-origin": { label: "메모→소스: 소스 줄 메모 표시·원본 메모 없음", link: linkOf(false), shell: true },
};
function makeMemoStudio(view) {
  let link = view.link;
  return {
    listTypes: async () => [{ type_id: "memo", available: true, formats: [], presets: [], export_formats: [], default_format: null, settings_schema: null }],
    listOutputs: async () => ({ items: [memoOutput], nextCursor: null }),
    getOutput: async () => ({ ...memoOutput, settings: {}, assets: [], evidence: [], source_link: link, revision: { content: { body: { markdown: "# 6월 회의\n- 보험금 청구 서류는 3일 안에 검토한다.\n- 면책 기간 안내 문구를 고친다." }, warnings: [] } } }),
    createRevision: async () => ({ revision_no: 4 }),
    createMemoSource: view.create ?? (async () => { link = linkOf(false); return { source_id: "memo-source-1", source_version_id: "memo-version-1", state: "registered" }; }),
    reflectMemoSource: async () => { link = linkOf(false); return { source_id: "memo-source-1", source_version_id: "memo-version-2" }; },
    exportFormats: () => [],
  };
}
const memoSourceRow = (over) => ({ source_id: "source-1", source_version_id: "version-1", filename: "보험약관.pdf", source_state: "ready", processing_state: "completed", job_state: "completed", ...over });
const MEMO_SOURCES = [
  memoSourceRow(),
  memoSourceRow({ source_id: "memo-source-1", source_version_id: "memo-version-1", filename: "회의 메모.txt", memo_origin: { memo_output_id: MEMO_ID, memo_exists: true } }),
  memoSourceRow({ source_id: "memo-source-2", source_version_id: "memo-version-2", filename: "검토 메모.txt", source_state: "processing", processing_state: "running", job_state: "running", memo_origin: { memo_output_id: sid("o"), memo_exists: true } }),
  memoSourceRow({ source_id: "memo-source-3", source_version_id: "memo-version-3", filename: "지난 메모.txt", memo_origin: { memo_output_id: sid("p"), memo_exists: false } }),
];
function MemoSourceHarness({ state }) {
  const view = MEMO_STATES[state];
  const studio = useMemo(() => makeMemoStudio(view), [view]);
  const adapter = useMemo(() => ({ listSources: async () => MEMO_SOURCES, uploadPdf() {}, getProcessingStatus() {}, askQuestion() {}, citationUrl: () => null, createReport() {},
    listStudioOutputs: async () => [], listConnectors: async () => [], listKnowledgePackages: async () => [], studioV2: studio }), [studio]);
  if (view.shell) return h("div", { "data-harness-state": state }, h(ProductWorkspaceShell, { workspaceId: "workspace-1", notebookTitle: "보험약관 검토", adapter }));
  return h("div", { "data-harness-state": state, style: { maxWidth: 420 } },
    h(StudioPanel, { studio, sourceStats: { sourceCount: 1, checkedCount: 1, readySourceCount: 1, processingCount: 0 }, openOutputRequest: { outputId: MEMO_ID, nonce: 1 } }));
}

// 질문 도구(NB2-U1) 상태: 입력창 아래 모델 선택 옆 "도구" 버튼. 목록은 버튼을 눌러 연다. 저장 실패는 스위치를 눌러 만든다(503으로 답한다).
const QT_KNOWLEDGE = { id: "approved_knowledge", kind: "approved_knowledge", label: "승인 지식", available: true, enabled: true };
const QT_RAG = { id: "connector:kc-rag", kind: "connector", connector_kind: "daon2_rag", label: "Daon2-RAG 문서", available: true, enabled: true };
const QT_LAW = { id: "connector:kc-law", kind: "connector", connector_kind: "law", label: "법령 검색", available: true, enabled: true };
const QT_STATES = {
  "tools-loading": { label: "질문 도구: 불러오는 중", load: () => new Promise(() => {}) },
  "tools-ready": { label: "질문 도구: 정상 3개", tools: [QT_KNOWLEDGE, QT_RAG, QT_LAW] },
  "tools-unavailable": { label: "질문 도구: 사용 불가 포함", tools: [{ ...QT_KNOWLEDGE, available: false, enabled: false, reason: "NO_SCOPE_SELECTED" }, { ...QT_RAG, available: false, enabled: false, reason: "CONNECTOR_NOT_READY" }, QT_LAW, { id: "connector:kc-off", kind: "connector", connector_kind: "daon2", label: "Daon2 지식", available: false, enabled: false, reason: "CONNECTOR_DISABLED" }] },
  "tools-off": { label: "질문 도구: 모두 꺼짐", tools: [{ ...QT_KNOWLEDGE, enabled: false }, { ...QT_RAG, enabled: false }, { ...QT_LAW, enabled: false }] },
  "tools-save-failed": { label: "질문 도구: 저장 실패(스위치 누르기)", tools: [QT_KNOWLEDGE, QT_RAG, QT_LAW], save: async () => { throw Object.assign(new Error("QUESTION_TOOLS_UNAVAILABLE"), { code: "QUESTION_TOOLS_UNAVAILABLE", status: 503 }); } },
};
function makeToolsStudio(view) {
  let tools = (view.tools ?? []).map((tool) => ({ ...tool }));
  return {
    getQuestionTools: view.load ?? (async () => ({ tools })),
    saveQuestionTools: view.save ?? (async (enabled) => { tools = tools.map((tool) => (tool.id in enabled ? { ...tool, enabled: tool.available && enabled[tool.id] } : tool)); return { tools }; }),
    getModelSelection: async () => ({ available: [{ connection_id: "conn-1", display_name: "사내 모델", model_id: "gpt-4.1", reasoning_levels: [], reasoning_checked: true }], selection: null, levels: ["low", "medium", "high"], default: { connection_id: "conn-1", model_id: "gpt-4.1" } }),
    saveModelSelection: async () => ({}),
  };
}
function QuestionToolsHarness({ state }) {
  const view = QT_STATES[state];
  const studio = useMemo(() => makeToolsStudio(view), [view]);
  return h("div", { "data-harness-state": state, className: "adaptive-workspace", style: { maxWidth: 720, minHeight: 0, paddingTop: 300, overflow: "visible" } },
    h("form", { className: "conversation-composer", onSubmit: (event) => event.preventDefault() },
      h(QuestionToolsMenu, { studio }),
      h(ModelSelectionBar, { studio }),
      h("label", null, h("span", { className: "sr-only" }, "질문"), h("textarea", { rows: 1, placeholder: "작업 내용이나 궁금한 점을 질문하세요" })),
      h("button", { className: "composer-submit", type: "submit", "aria-label": "질문 실행", disabled: true }, "↑")));
}

// 노트북 개요(NB2-U2) 6상태: 대화 영역 위쪽. 추천 질문 칩을 누르면 아래 입력창에 채워지기만 한다(전송 버튼은 잠겨 있다).
const OV_EMPTY = { summary: null, questions: [], citations: [], stale: false, generated_at: null, error_code: null };
const OV_READY = {
  state: "ready", stale: false, generated_at: "2026-11-24T01:00:00Z", error_code: null,
  summary: "이 노트북은 보험금 지급 기준과 청구 절차를 다룹니다.[1] 면책 기간은 계약일부터 90일이며 이 기간의 질병 사고는 보장하지 않습니다.[2] 청구할 때는 진단서와 영수증 원본이 필요합니다.[1]",
  questions: ["보험금 지급 기준은 무엇인가요?", "면책 기간에 생긴 사고는 어떻게 되나요?", "청구에 필요한 서류를 정리해 줘"],
  citations: [{ label: "1", source_title: "보험약관.pdf", page: 3 }, { label: "2", source_title: "청구 안내.docx", page: null }],
};
const OV_STATES = {
  "overview-none": { label: "개요: 없음(소스 없음)", data: { state: "none", ...OV_EMPTY } },
  "overview-generating": { label: "개요: 만드는 중", data: { state: "working", ...OV_EMPTY } },
  "overview-ready": { label: "개요: 완료", data: OV_READY },
  "overview-stale": { label: "개요: 낡음", data: { ...OV_READY, stale: true } },
  "overview-failed": { label: "개요: 실패", data: { state: "failed", ...OV_EMPTY, error_code: "OVERVIEW_UNGROUNDED" } },
  "overview-blocked": { label: "개요: 차단", data: { state: "blocked", ...OV_EMPTY, error_code: "OVERVIEW_BLOCKED" } },
};
function OverviewHarness({ state }) {
  const view = OV_STATES[state];
  const studio = useMemo(() => ({ getNotebookOverview: async () => view.data, regenerateNotebookOverview: async () => ({ state: "queued", ...OV_EMPTY }) }), [view]);
  const [question, setQuestion] = useState("");
  const [opened, setOpened] = useState(null);
  return h("div", { "data-harness-state": state, className: "adaptive-workspace", style: { maxWidth: 720, minHeight: 0, overflow: "visible" } },
    h("div", { className: "conversation-transcript" },
      h(NotebookOverview, { studio, notebookId: `harness-${state}`, storage: null, pollIntervalMs: 600000, onAskQuestion: setQuestion, onOpenSource: (citation) => setOpened(citation) }),
      opened ? h("div", { className: "context-selection-status", role: "status" }, `소스 보기: ${opened.source_title}`) : null,
      h("div", { className: "conversation-empty" }, h("h3", null, state === "overview-none" ? "Source를 추가한 뒤 질문하세요." : "Source에 대해 무엇이든 물어보세요."), h("p", null, "선택한 Source의 근거와 Citation을 사용해 답합니다."))),
    h("form", { className: "conversation-composer", onSubmit: (event) => event.preventDefault() },
      h("label", null, h("span", { className: "sr-only" }, "질문"), h("textarea", { rows: 1, value: question, onChange: (event) => setQuestion(event.currentTarget.value), placeholder: "작업 내용이나 궁금한 점을 질문하세요" })),
      h("button", { className: "composer-submit", type: "submit", "aria-label": "질문 실행", disabled: true }, "↑")));
}

// 생성 전 구성 확인(NB3-U1): 슬라이드·동영상 설정 체크칸, 카드 "구성 확인 필요", 검토 화면, 입력 오류, 422, 확정 후 생성 중, 취소됨.
// 확정·422는 검토 화면에서 "이대로 만들기"를 눌러 만든다(확정하면 가짜 목록이 생성 중으로 바뀐다).
const OL_CONFIRM = { confirm_outline: { type: "string", enum: ["no", "yes"] }, confirmed_outline: { type: "string", maxLength: 40000, hidden: true } };
const OL_SLIDES = item("q", "slides", "보험금 지급 발표 자료");
const OL_VIDEO = item("r", "video_overview", "보험금 지급 동영상 개요");
const OL_CANCELLED = item("t", "slides", "취소한 발표 자료", { status: "cancelled", current_revision: 0 });
const OL_SLIDES_BODY = { title: "보험금 지급 안내", slides: [], outline_review: [
  { title: "보험금 지급 안내", points: [] },
  { title: "지급 기한", points: ["청구서류 접수 후 3일 이내 지급", "조사가 필요하면 지급 예정일을 안내"] },
  { title: "면책 기간", points: ["계약일부터 90일", "이 기간의 질병 사고는 보장하지 않음"] },
  { title: "청구 서류", points: ["진단서", "영수증 원본"] }] };
const OL_VIDEO_BODY = { title: "보험금 지급 한눈에 보기", scenes: [], outline_review: [
  { title: "들어가며", narration_summary: "오늘은 보험금이 언제, 어떻게 지급되는지 알아봅니다." },
  { title: "지급 기한", narration_summary: "청구서류를 접수한 날부터 3일 이내에 보험금을 지급합니다.", bullets: ["접수일부터 3일 이내"] },
  { title: "면책 기간", narration_summary: "계약일부터 90일 동안 생긴 질병 사고는 보장하지 않습니다.", bullets: ["계약일부터 90일"] }] };
const OL_ERROR_BODY = { ...OL_SLIDES_BODY, outline_review: [OL_SLIDES_BODY.outline_review[0], { title: "", points: ["청구서류 접수 후 3일 이내 지급"] }, { title: "면책 기간", points: ["가".repeat(130)] }] };
const OL_STATES = {
  "outline-settings-slides": { label: "구성 확인: 슬라이드 설정 체크칸", settings: "slides" },
  "outline-settings-video": { label: "구성 확인: 동영상 설정 체크칸", settings: "video_overview" },
  "outline-cards": { label: "구성 확인: 카드(확인 필요·취소됨)" },
  "outline-review-slides": { label: "구성 확인: 슬라이드 검토 중", open: OL_SLIDES.output_id },
  "outline-review-video": { label: "구성 확인: 동영상 검토 중", open: OL_VIDEO.output_id },
  "outline-error-slides": { label: "구성 확인: 입력 오류(빈 제목·글자 수)", open: OL_SLIDES.output_id, slidesBody: OL_ERROR_BODY },
  "outline-422-video": { label: "구성 확인: 서버 거부 422(확정 누르기)", open: OL_VIDEO.output_id, reject: true },
};
function makeOutlineStudio(view) {
  const outputs = [OL_SLIDES, OL_VIDEO, OL_CANCELLED].map((o) => ({ ...o }));
  const bodies = { slides: view.slidesBody ?? OL_SLIDES_BODY, video_overview: OL_VIDEO_BODY };
  const types = ["audio_overview", "slides", "video_overview", "mind_map", "report", "flashcards", "quiz", "infographic", "data_table", "memo"].map((type_id) => ({
    type_id, available: true, formats: [], presets: [], export_formats: [], default_format: null,
    settings_schema: { type: "object", properties: { focus: { type: "string" }, ...(["slides", "video_overview"].includes(type_id) ? { length: { type: "string", enum: ["short", "normal", "long"] }, ...OL_CONFIRM } : {}) } } }));
  return {
    types,
    listTypes: async () => types,
    listOutputs: async () => ({ items: outputs.map((o) => ({ ...o })), nextCursor: null }),
    getOutput: async (id) => { const base = outputs.find((o) => o.output_id === id); return { ...base, settings: { confirm_outline: "yes" }, assets: [], evidence: [], revision: { content: { body: bodies[base.type_id], warnings: [] } } }; },
    regenerateOutput: async (id) => {
      if (view.reject) throw Object.assign(new Error("OUTLINE_INVALID"), { code: "OUTLINE_INVALID", status: 422 });
      const target = outputs.find((o) => o.output_id === id); target.status = "generating"; target.progress_pct = 15;
      return { output_id: id, job_id: "svj-h", status: "queued" };
    },
    cancelOutput: async () => ({}), createOutput: async () => ({ output_id: sid("u"), job_id: "j", status: "queued" }), exportFormats: () => [],
  };
}
function OutlineHarness({ state }) {
  const view = OL_STATES[state];
  const studio = useMemo(() => makeOutlineStudio(view), [view]);
  if (view.settings) {
    const type = studio.types.find((t) => t.type_id === view.settings);
    return h("div", { "data-harness-state": state, className: "studio-panel", style: { maxWidth: 420, minHeight: 560 } },
      h(SettingsDialog, { type, typeLabel: view.settings === "slides" ? "슬라이드 자료" : "동영상 개요", initial: { confirm_outline: "yes" }, onSubmit: () => {}, onCancel: () => {} }));
  }
  return h("div", { "data-harness-state": state, style: { maxWidth: 420 } },
    h(StudioPanel, { studio, sourceStats: { sourceCount: 3, checkedCount: 3, readySourceCount: 3, processingCount: 0 }, checkedSourceVersionIds: ["sv-1"],
      openOutputRequest: view.open ? { outputId: view.open, nonce: 1 } : null }));
}

// 소스 묶음(NB3-U2): 실제 셸 소스 칸에 묶음을 띄운다. 일부·없음 체크 상태는 소스·묶음 체크칸을 눌러 만든다.
// 저장 실패·권한 없음·다른 곳에서 바뀜은 소스 줄 "묶음으로 이동"을 눌러 만든다(가짜 어댑터가 503·403·412로 답한다).
const sgId = (c) => `sg-${c.repeat(32)}`;
const sgSource = (n, filename, over = {}) => ({ source_id: `source-g${n}`, source_version_id: `version-g${n}`, filename, source_state: "ready", processing_state: "completed", job_state: "completed", ...over });
const SG_SOURCES = [sgSource(1, "보험약관.pdf"), sgSource(2, "특약 약관.pdf"), sgSource(3, "청구 안내.docx"), sgSource(4, "지급 기준표.xlsx"), sgSource(5, "회의 메모.txt"), sgSource(6, "상담 기록.txt", { source_state: "processing", processing_state: "running", job_state: "running" })];
const SG_GROUPS = [
  { group_id: sgId("a"), name: "약관", position: 0, source_ids: ["source-g1", "source-g2", "source-g4"] },
  { group_id: sgId("b"), name: "청구 서류", position: 1, source_ids: [] },
];
const SG_TEN = Array.from({ length: 10 }, (_, i) => sgSource(i + 1, `약관 ${i + 1}장.pdf`));
const SG_STATES = {
  "groups-default": { label: "소스 묶음: 기본(체크·접기·이동 눌러 보기)" },
  "groups-none": { label: "소스 묶음: 묶음 없음(묶음 만들기)", groups: [] },
  "groups-save-failed": { label: "소스 묶음: 저장 실패 되돌림(이동 누르기)", fail: () => Object.assign(new Error("STUDIO_UNAVAILABLE"), { code: "STUDIO_UNAVAILABLE", status: 503 }) },
  "groups-conflict": { label: "소스 묶음: 412 다시 조회(이동 누르기)", conflict: true },
  "groups-forbidden": { label: "소스 묶음: 보기 권한 403(이동 누르기)", fail: () => Object.assign(new Error("FORBIDDEN"), { code: "FORBIDDEN", status: 403 }) },
  "groups-limit8": { label: "소스 묶음: 묶음 체크 8개 초과 안내(질문하기)", sources: SG_TEN, groups: [{ group_id: sgId("c"), name: "약관 전체", position: 0, source_ids: SG_TEN.map((s) => s.source_id) }] },
};
function makeGroupStudio(view) {
  let groups = JSON.parse(JSON.stringify(view.groups ?? SG_GROUPS));
  let version = 1;
  let conflictPending = Boolean(view.conflict);
  const etag = () => `"source-groups:${version}"`;
  const result = () => ({ groups: JSON.parse(JSON.stringify(groups)), etag: etag() });
  const check = (given) => {
    if (view.fail) throw view.fail();
    if (conflictPending) { conflictPending = false; groups[0].name = "약관(다른 사용자가 수정)"; groups[1].source_ids = ["source-g5"]; version += 1; }
    if (given !== etag()) throw Object.assign(new Error("SOURCE_GROUP_ETAG_MISMATCH"), { code: "SOURCE_GROUP_ETAG_MISMATCH", status: 412 });
  };
  return {
    listTypes: async () => [], listOutputs: async () => ({ items: [], nextCursor: null }), exportFormats: () => [],
    listSourceGroups: async () => result(),
    createSourceGroup: async (name) => { groups.push({ group_id: sgId(String.fromCharCode(100 + groups.length)), name, position: groups.length, source_ids: [] }); version += 1; return { groupId: groups.at(-1).group_id, etag: etag(), replayed: false }; },
    updateSourceGroup: async (gid, { name, etag: given }) => { check(given); groups = groups.map((g) => (g.group_id === gid ? { ...g, name } : g)); version += 1; return result(); },
    deleteSourceGroup: async (gid, { etag: given }) => { check(given); groups = groups.filter((g) => g.group_id !== gid).map((g, i) => ({ ...g, position: i })); version += 1; return result(); },
    setSourceGroupMembers: async (gid, ids, { etag: given }) => { check(given); groups = groups.map((g) => ({ ...g, source_ids: g.group_id === gid ? [...ids] : g.source_ids.filter((id) => !ids.includes(id)) })); version += 1; return result(); },
  };
}
function SourceGroupsHarness({ state }) {
  const view = SG_STATES[state];
  const studio = useMemo(() => makeGroupStudio(view), [view]);
  const adapter = useMemo(() => ({ listSources: async () => view.sources ?? SG_SOURCES, uploadPdf() {}, getProcessingStatus() {}, citationUrl: () => null, createReport() {},
    askQuestion: async () => ({ run_id: "run-h", run_result_id: "result-h", answer: "약관 전체를 요약했습니다.", insufficient: false, citations: [] }),
    listStudioOutputs: async () => [], listConnectors: async () => [], listKnowledgePackages: async () => [], notebookContext: { notebook_id: `notebook-${state}`, sources: [] }, studioV2: studio }), [studio, view, state]);
  return h("div", { "data-harness-state": state }, h(ProductWorkspaceShell, { workspaceId: "workspace-1", notebookTitle: "보험약관 검토", adapter }));
}

// 빠른 찾기(NB4-U1): 실제 셸 소스 칸 위쪽에 띄운다. 검색창에 글자를 넣고 "찾기"를 누르면 상태별 가짜 응답이 온다.
// 문서 후보를 추가하면 소스 목록에 처리 중 소스가, 패키지 후보를 추가하면 승인 지식 칸에 패키지가 나타난다.
const sdRef = (i, kind) => (kind === "document" ? { kind, project_id: "project-1", work_package_id: "wp-1", document_id: `doc-${i}`, document_version: "v1" } : { kind, project_id: "project-1", work_package_id: `wp-${i}` });
const sdCandidate = (i, kind) => ({ candidate_id: `cand-${kind === "document" ? "d" : "k"}${i}`, kind,
  title: kind === "document" ? ["보험금 청구 절차 안내서.pdf", "특약 약관 해설서.docx", "지급 기준 개정 공지.txt"][i % 3] + (i > 2 ? ` (${i + 1})` : "") : ["보험 청구 업무", "약관 검토 업무", "고객 상담 업무"][i % 3] + (i > 2 ? ` ${i + 1}` : ""),
  origin_label: kind === "document" ? "Daon2-RAG 문서 · 보험 업무" : "Daon2 승인 지식 · 보험 프로젝트",
  reason: kind === "document" ? "본문에 '청구 절차'와 '서류'가 함께 나옵니다" : "업무 이름과 설명이 검색어와 맞습니다",
  preview: kind === "document" ? "보험금을 청구하려면 청구서, 신분증 사본, 진단서를 준비해 고객센터 또는 앱으로 제출합니다. 접수 후 3영업일 안에 심사 결과를 알려 드리며, 추가 서류가 필요하면 담당자가 연락합니다." : "청구 접수부터 심사·지급까지의 업무 기준과 승인된 규칙을 묶은 업무 패키지입니다.",
  action: kind === "document" ? "add_source" : "add_scope", ref: sdRef(i, kind) });
const SD_BASE = [sdCandidate(0, "knowledge_package"), sdCandidate(0, "document"), sdCandidate(1, "document"), sdCandidate(1, "knowledge_package")];
const SD_MANY = Array.from({ length: 20 }, (_, i) => sdCandidate(i, i % 2 ? "document" : "knowledge_package"));
const sdFail = (code, status) => Object.assign(new Error(code), { code, status });
const SD_STATES = {
  "discovery-default": { label: "빠른 찾기: 기본(찾기·추가 눌러 보기)" },
  "discovery-searching": { label: "빠른 찾기: 찾는 중", search: () => new Promise(() => {}) },
  "discovery-many": { label: "빠른 찾기: 후보 20개(목록 창 안 스크롤)", search: async () => ({ candidates: SD_MANY, unavailable: [] }) },
  "discovery-empty": { label: "빠른 찾기: 결과 없음", search: async () => ({ candidates: [], unavailable: [] }) },
  "discovery-unavailable": { label: "빠른 찾기: 문서 범위 사용 불가", search: async () => ({ candidates: SD_BASE.filter((c) => c.kind !== "document"), unavailable: [{ scope: "documents", reason: "CONNECTOR_NOT_CONFIGURED" }] }) },
  "discovery-partial": { label: "빠른 찾기: 일부 범위 실패", search: async () => ({ candidates: SD_BASE.filter((c) => c.kind !== "document"), unavailable: [{ scope: "documents", reason: "DISCOVERY_CONNECTOR_FAILED" }] }) },
  "discovery-all-unavailable": { label: "빠른 찾기: 모든 범위 사용 불가(422)", search: async () => { throw sdFail("DISCOVERY_SCOPE_UNAVAILABLE", 422); } },
  "discovery-adding": { label: "빠른 찾기: 추가 중", add: () => new Promise(() => {}) },
  "discovery-add-failed": { label: "빠른 찾기: 추가 실패(문서 너무 큼)", add: async (ref) => { if (ref.kind === "document") throw sdFail("DISCOVERY_DOCUMENT_TOO_LARGE", 413); return { added: "scope", sourceId: null }; } },
  "discovery-forbidden": { label: "빠른 찾기: 보기 권한(추가 403)", add: async () => { throw sdFail("FORBIDDEN", 403); } },
};
function DiscoveryHarness({ state }) {
  const view = SD_STATES[state];
  const store = useMemo(() => ({ sources: [sgSource(1, "보험약관.pdf"), sgSource(2, "청구 안내.docx")], scopes: [] }), [view]);
  const adapter = useMemo(() => {
    const studio = { listTypes: async () => [], listOutputs: async () => ({ items: [], nextCursor: null }), exportFormats: () => [],
      searchSourceDiscovery: async (query, scopes) => (view.search ? view.search(query, scopes) : { candidates: SD_BASE, unavailable: [] }),
      addSourceDiscovery: async (ref) => {
        if (view.add) return view.add(ref);
        if (ref.kind === "document") {
          const id = `source-${ref.document_id}`;
          store.sources = [...store.sources, { source_id: id, source_version_id: `version-${ref.document_id}`, filename: SD_BASE.find((c) => c.ref.document_id === ref.document_id)?.title ?? id, source_state: "processing", processing_state: "running", job_state: "running" }];
          return { added: "source", sourceId: id };
        }
        store.scopes = [...store.scopes, { project_id: ref.project_id, work_package_id: ref.work_package_id, project_name: "보험 프로젝트", work_package_name: SD_BASE.find((c) => c.ref.work_package_id === ref.work_package_id && c.kind === "knowledge_package")?.title ?? ref.work_package_id }];
        return { added: "scope", sourceId: null };
      } };
    return { listSources: async () => store.sources, uploadPdf() {}, getProcessingStatus() {}, citationUrl: () => null, createReport() {},
      askQuestion: async () => ({ run_id: "run-h", run_result_id: "result-h", answer: "응답", insufficient: false, citations: [] }),
      listStudioOutputs: async () => [], listConnectors: async () => [], listKnowledgePackages: async () => [],
      getNotebookKnowledgeScopes: async () => ({ items: store.scopes }), listDaonKnowledgeScopes: async () => ({ projects: [] }),
      notebookContext: { notebook_id: `notebook-${state}`, sources: [] }, studioV2: studio };
  }, [view, store, state]);
  return h("div", { "data-harness-state": state }, h(ProductWorkspaceShell, { workspaceId: "workspace-1", notebookTitle: "보험약관 검토", adapter }));
}

// 심층 조사(NB4-U2): 실제 셸에 띄운다. 소스 칸 자료 찾기에서 "심층 조사"로 바꿔 질문을 넣고 "조사 시작"을 누르면 스튜디오에 새 보고서 카드가 생겨
// 계획 → 찾기 1/3 → 2/3 → 3/3 → 작성 → 완료로 진행한다(가짜 시계). 완료 카드를 열면 보고서와 "사용한 자료"가 보이고, 골라서 소스로 추가할 수 있다.
const DR_OID = (c) => `sv2-${c.repeat(32)}`;
const drItem = (c, title, over = {}) => ({ output_id: DR_OID(c), type_id: "report", format_id: "briefing", title, status: "completed", error_code: null, source_count: 0, current_revision: 1,
  created_at: "2026-11-24T00:00:00Z", updated_at: "2026-11-24T00:00:00Z", stale: false, progress: null, ...over });
const drCandidates = (count) => Array.from({ length: count }, (_, i) => sdCandidate(i, i % 3 === 1 ? "knowledge_package" : "document"))
  .map((c, i) => ({ ...c, candidate_id: `${c.candidate_id}-${i}` }));
const drSections = (long) => {
  const base = [
    { heading: "청구에 필요한 서류", blocks: [{ type: "paragraph", text: "보험금을 청구하려면 청구서, 신분증 사본, 진단서를 준비합니다.", refs: ["S1"] },
      { type: "paragraph", text: "청구 접수는 고객센터나 앱으로 할 수 있습니다.", refs: ["S1", "S3"] },
      { type: "paragraph", text: "근거 부족: 서류가 갖춰지면 당일 지급됩니다.", refs: [] }] },
    { heading: "심사와 지급 기준", blocks: [{ type: "paragraph", text: "접수 후 3영업일 안에 심사 결과를 알려 드립니다.", refs: ["S1"] },
      { type: "paragraph", text: "지급 기준은 청구 업무 패키지의 승인 규칙을 따릅니다.", refs: ["S2"] }] },
  ];
  if (!long) return base;
  return [...base, ...Array.from({ length: 5 }, (_, s) => ({ heading: `추가 조사 항목 ${s + 1}`, blocks: Array.from({ length: 6 }, (_, b) => (b === 5
    ? { type: "paragraph", text: "근거 부족: 찾은 자료로 확인되지 않은 내용입니다.", refs: [] }
    : { type: "paragraph", text: `조사 항목 ${s + 1}의 ${b + 1}번째 문장입니다. 청구 절차와 지급 기준을 자료에 따라 정리했습니다.`, refs: [`S${(b % 6) + 1}`] })) }))];
};
const drContent = (long, unavailable = []) => ({ schema: "studio.report.v1", warnings: [], body: { title: "보험금 청구 절차 조사", summary: "", sections: drSections(long) },
  research: { query: "보험금 청구 서류와 심사 기준", sub_questions: ["청구 서류", "심사 기간", "지급 기준"], candidates: drCandidates(long ? 40 : 6), unavailable, tool_calls: long ? 12 : 6 } });
const drEvidence = (count) => Array.from({ length: Math.min(count, 6) }, (_, i) => ({ ref_id: `S${i + 1}`, source_version_id: null, source_name: `자료 ${i + 1}`, locator_kind: "research", locator_value: `cand-${i}`, origin: "connector:daon2_rag" }));
// 가짜 시계로 진행하는 조사: 시작 후 경과 시간에 따라 진행 메모가 바뀐다.
const DR_STEPS = [[0, 5, "계획"], [2500, 10, "찾기 1/3"], [5000, 28, "찾기 2/3"], [7500, 46, "찾기 3/3"], [10000, 70, "작성"]];
const DR_STATES = {
  "research-start": { label: "심층 조사: 시작(조사 시작 눌러 보기)", outputs: () => [drItem("a", "지난 조사 보고서")], live: true },
  "research-progress": { label: "심층 조사: 카드 진행 문구 3단계", outputs: () => [
    drItem("p", "조사: 계획", { status: "generating", current_revision: 0, progress: { pct: 5, note: "계획" } }),
    drItem("f", "조사: 찾기", { status: "generating", current_revision: 0, progress: { pct: 28, note: "찾기 2/3" } }),
    drItem("w", "조사: 작성", { status: "generating", current_revision: 0, progress: { pct: 70, note: "작성" } }),
    drItem("a", "보험금 청구 절차 조사")] },
  "research-failed": { label: "심층 조사: 시간 초과·실패·취소·범위 사용 불가", outputs: () => [
    drItem("t", "조사: 시간 초과", { status: "failed", error_code: "RESEARCH_TIMEOUT", current_revision: 0 }),
    drItem("u", "조사: 범위 사용 불가", { status: "failed", error_code: "DISCOVERY_SCOPE_UNAVAILABLE", current_revision: 0 }),
    drItem("n", "조사: 자료 없음", { status: "failed", error_code: "RESEARCH_NO_EVIDENCE", current_revision: 0 }),
    drItem("c", "조사: 연결 실패", { status: "failed", error_code: "DISCOVERY_CONNECTOR_FAILED", current_revision: 0 }),
    drItem("x", "조사: 취소함", { status: "cancelled", current_revision: 0 })] },
  "research-report": { label: "심층 조사: 보고서·사용한 자료(카드 열기)", outputs: () => [drItem("a", "보험금 청구 절차 조사")], content: () => drContent(false, [{ scope: "knowledge", reason: "CONNECTOR_NOT_READY" }]) },
  "research-long": { label: "심층 조사: 긴 보고서·사용한 자료 40개(창 안 스크롤)", outputs: () => [drItem("a", "보험금 청구 절차 조사")], content: () => drContent(true) },
};
function ResearchHarness({ state }) {
  const view = DR_STATES[state];
  const store = useMemo(() => ({ sources: [sgSource(1, "보험약관.pdf"), sgSource(2, "청구 안내.docx")], scopes: [], outputs: view.outputs(), startedAt: null }), [view]);
  const adapter = useMemo(() => {
    const live = () => {
      if (!store.startedAt) return;
      const elapsed = Date.now() - store.startedAt;
      const target = store.outputs.find((o) => o.output_id === DR_OID("r"));
      if (!target) return;
      if (elapsed >= 12500) Object.assign(target, { status: "completed", current_revision: 1, progress: null, updated_at: new Date().toISOString() });
      else { const [, pct, note] = [...DR_STEPS].reverse().find(([at]) => elapsed >= at); Object.assign(target, { status: elapsed < 1200 ? "queued" : "generating", progress: { pct, note } }); }
    };
    const studio = { ...makeStudio(), listTypes: async () => STUDIO_TYPES_FOR_RESEARCH, exportFormats: () => ["docx", "pdf", "md"],
      listOutputs: async () => { live(); return { items: store.outputs.map((o) => ({ ...o })), nextCursor: null }; },
      getOutput: async (id) => {
        const base = store.outputs.find((o) => o.output_id === id) ?? store.outputs[0];
        const content = view.content ? view.content() : drContent(false);
        return { ...base, settings: {}, assets: [], evidence: drEvidence(content.research.candidates.length), revision: { revision_no: 1, content } };
      },
      cancelOutput: async (id) => { const target = store.outputs.find((o) => o.output_id === id); if (target) Object.assign(target, { status: "cancelled", progress: null }); store.startedAt = null; return { output_id: id, cancel_requested: true }; },
      researchOf: studioResearchOf,
      createResearch: async () => {
        store.outputs = [drItem("r", "보험금 청구 서류와 심사 기준", { status: "queued", current_revision: 0, progress: { pct: 5, note: "계획" } }), ...store.outputs.filter((o) => o.output_id !== DR_OID("r"))];
        store.startedAt = Date.now();
        return { output_id: DR_OID("r"), job_id: "svj-r", status: "queued" };
      },
      searchSourceDiscovery: async () => ({ candidates: SD_BASE, unavailable: [] }),
      addSourceDiscovery: async (ref) => {
        if (ref.kind === "document") {
          const id = `source-${ref.document_id}`;
          store.sources = [...store.sources, { source_id: id, source_version_id: `version-${ref.document_id}`, filename: `${ref.document_id}.txt`, source_state: "processing", processing_state: "running", job_state: "running" }];
          return { added: "source", sourceId: id };
        }
        store.scopes = [...store.scopes, { project_id: ref.project_id, work_package_id: ref.work_package_id, project_name: "보험 프로젝트", work_package_name: ref.work_package_id }];
        return { added: "scope", sourceId: null };
      } };
    return { listSources: async () => store.sources, uploadPdf() {}, getProcessingStatus() {}, citationUrl: () => null, createReport() {},
      askQuestion: async () => ({ run_id: "run-h", run_result_id: "result-h", answer: "응답", insufficient: false, citations: [] }),
      listStudioOutputs: async () => [], listConnectors: async () => [], listKnowledgePackages: async () => [],
      getNotebookKnowledgeScopes: async () => ({ items: store.scopes }), listDaonKnowledgeScopes: async () => ({ projects: [] }),
      notebookContext: { notebook_id: `notebook-${state}`, sources: [] }, studioV2: studio };
  }, [view, store, state]);
  return h("div", { "data-harness-state": state }, h(ProductWorkspaceShell, { workspaceId: "workspace-1", notebookTitle: "보험약관 검토", adapter }));
}
const STUDIO_TYPES_FOR_RESEARCH = ["audio_overview", "slides", "video_overview", "mind_map", "report", "flashcards", "quiz", "infographic", "data_table", "memo"]
  .map((type_id) => ({ type_id, available: true, formats: [], presets: type_id === "report" ? ["summary", "briefing"] : [], export_formats: ["docx"], default_format: null, settings_schema: null }));

function App() {
  const params = new URLSearchParams(location.search);
  const bare = params.has("bare");
  const [theme, setTheme] = useState(params.get("theme") === "dark" ? "dark" : "light");
  const [proposal, setProposal] = useState(false);
  const [view, setView] = useState(location.hash.slice(1) || "studio");
  useEffect(() => { document.documentElement.dataset.design = proposal ? "proposal" : "current"; }, [proposal]);
  useEffect(() => { if (bare) document.documentElement.style.overflow = "hidden"; }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; document.body.style.background = theme === "dark" ? "#101114" : "#f6f7fb"; }, [theme]);
  useEffect(() => { location.hash = view; }, [view]);
  const studio = useMemo(makeStudio, []);
  const wizardStudio = useMemo(() => ({ ...studio, downloadExport: studio.downloadExport, authoring: { listTemplates: async () => [], createSession: async () => review, getSession: async () => review, answer: async () => ({}), review: async () => ({}), listConnectors: async () => [], listDocuments: async () => [] } }), [studio]);
  const tabs = [["studio", "Studio 패널"], ["wizard", "작성 마법사"], ["tools", "노트북 도구"], ["home", "노트북 홈"], ["settings", "설정(지식 연결)"], ["tts", "설정(TTS 엔진)"], ["orgjoin", "조직 가입"], ["orgadmin", "조직 관리"], ["login", "로그인"], ...Object.entries(PROCESS_STATES).map(([key, value]) => [key, value.label]), ...Object.entries(MEMO_STATES).map(([key, value]) => [key, value.label]), ...Object.entries(QT_STATES).map(([key, value]) => [key, value.label]), ...Object.entries(OV_STATES).map(([key, value]) => [key, value.label]), ...Object.entries(OL_STATES).map(([key, value]) => [key, value.label]), ...Object.entries(SG_STATES).map(([key, value]) => [key, value.label]), ...Object.entries(SD_STATES).map(([key, value]) => [key, value.label]), ...Object.entries(DR_STATES).map(([key, value]) => [key, value.label])];
  return h("div", { style: { padding: 12, color: theme === "dark" ? "#e8eaed" : "#1b2230" } },
    bare ? null : h("div", { style: { display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" } },
      ...tabs.map(([key, label]) => h("button", { key, type: "button", id: `tab-${key}`, onClick: () => setView(key), style: { fontWeight: view === key ? 700 : 400 } }, label)),
      h("button", { type: "button", id: "toggle-design", onClick: () => setProposal((v) => !v), style: { fontWeight: proposal ? 700 : 400 } }, proposal ? "시안 보는 중 → 현재로" : "현재 → 시안 보기"),
      h("button", { type: "button", id: "toggle-theme", onClick: () => setTheme((t) => (t === "dark" ? "light" : "dark")) }, theme === "dark" ? "라이트로" : "다크로")),
    view === "studio" ? h("div", { style: { maxWidth: 420 } }, h(StudioPanel, { studio, sourceStats: { sourceCount: 3, checkedCount: 3, readySourceCount: 3, processingCount: 0 }, checkedSourceVersionIds: ["sv-1"] })) : null,
    view === "wizard" ? h("div", { style: { maxWidth: 720 } }, h(AuthoringWizard, { studio: wizardStudio, sources: [{ sourceVersionId: "sv-1", filename: "rfp.txt", ready: true }], outputId: review.output_id, onClose: () => setView("studio") })) : null,
    view === "home" ? h(NotebookHome, { state: "ready", notebooks: [
      { notebook_id: "nb-1", title: "보험약관 검토", source_count: 3, output_count: 4, updated_at: "2026-10-26T01:00:00Z", status: "active", etag: '"notebook:1"' },
      { notebook_id: "nb-2", title: "RFP 대응 제안서", source_count: 1, output_count: 2, updated_at: "2026-10-25T09:00:00Z", status: "active", etag: '"notebook:2"' },
      { notebook_id: "nb-3", title: "빈 노트북", source_count: 0, output_count: 0, updated_at: "2026-10-24T09:00:00Z", status: "empty", etag: '"notebook:3"' }] }) : null,
    view === "settings" ? h("div", { style: { maxWidth: 900 } }, h(KnowledgeConnectorsPane, { api: { list: async () => [{ connector_id: "kc-" + "a".repeat(32), kind: "daon2_rag", name: "Daon2-RAG", status: "verified", virtual: false, last_checked_at: "2026-10-26T01:00:00+00:00", error_code: null, version: 1, limits: {} }], register: async () => ({}), verify: async () => ({ status: "verified" }), disconnect: async () => {}, updateLimits: async () => ({}) } })) : null,
    view === "tts" ? h("div", { style: { maxWidth: 1000 } }, h(TtsEnginesPane, { api: (() => {
      const base = { slug: "supertonic", label: "Supertonic", base_url: "https://tts.example.com", provider_kind: "external_api", language: "ko", timeout_seconds: 120,
        voices: { A: "F1", B: "M1" }, voice_choices: ["F1", "F2", "M1", "M2"], last_checked_at: "2026-10-26T01:00:00+00:00", error_code: null, has_credential: true };
      const engines = [{ ...base, engine_id: "te-" + "a".repeat(32), status: "verified", is_default: true, version: 2, source: "settings" },
        { ...base, engine_id: "te-" + "b".repeat(32), slug: "qwen", label: "Qwen3-TTS", base_url: "https://qwen.example.com", status: "failed", error_code: "TTS_ENGINE_AUTH_FAILED", is_default: false, version: 1, source: "settings", voices: { A: "sohee", B: "aiden" }, voice_choices: ["sohee", "aiden"] },
        { ...base, engine_id: null, slug: "deploy", label: "배포 설정 엔진", status: "deployment", is_default: false, version: 0, source: "deployment", last_checked_at: null }];
      return { list: async () => engines, register: async () => engines[0], verify: async () => ({ ...engines[0], status: "verified" }), update: async () => engines[0], disconnect: async () => {} };
    })() })) : null,
    view === "orgjoin" ? h(OrganizationJoinForm, { api: {
      getOrganizationSession: async () => ({ user_id: "js4choi", tenant_id: "personal-tenant", session_id: "session-1", device_id: "device", workspace_id: null, is_system_admin: false }),
      listOwnJoinRequests: async () => [{ request_id: "jr-1", tenant_id: "tenant-a", user_id: "js4choi", invitation_id: "inv-1", state: "pending", decision_reason: null, decided_by: null, version: 1, created_at: "2026-11-16T01:00:00+00:00", updated_at: "2026-11-16T01:00:00+00:00" }],
      submitJoinRequest: async () => ({}) } }) : null,
    view === "orgadmin" ? (() => {
      const now = "2026-11-16T01:00:00+00:00";
      const tenant = "tenant-a";
      const api = {
        getOrganizationSession: async () => ({ user_id: "admin", tenant_id: "admin", session_id: "s-1", device_id: "device", workspace_id: null, is_system_admin: true }),
        listManagedOrganizations: async () => [{ tenant_id: tenant, display_name: "예시 조직" }],
        listManagedWorkspaces: async () => [{ workspace_id: "workspace-a", display_name: "기본 작업공간" }],
        listJoinRequests: async () => [{ request_id: "jr-1", tenant_id: tenant, user_id: "js4choi", invitation_id: "inv-1", state: "pending", decision_reason: null, decided_by: null, version: 1, created_at: now, updated_at: now }],
        listMembers: async () => [{ tenant_id: tenant, user_id: "member-1", role: "member", state: "active", version: 1, updated_at: now, join_workspace_id: "workspace-a", access_role: "viewer", access_state: "active", access_version: 1 }],
        listInvitations: async () => [{ invitation_id: "inv-1", tenant_id: tenant, workspace_id: "workspace-a", created_by: "admin", expires_at: "2099-01-01T00:00:00+00:00", max_uses: 1, used_count: 0, state: "active", version: 1, created_at: now, updated_at: now }],
        decideJoinRequest: async () => ({}), changeMemberRole: async () => ({}), changeMemberState: async () => ({}), createInvitation: async () => ({}), revokeInvitation: async () => ({}),
      };
      return h("div", { style: { maxWidth: 1000 } }, h(OrganizationAdminConsole, { mode: "organization", api }));
    })() : null,
    view === "login" ? h(AuthPane, {}) : null,
    PROCESS_STATES[view] ? h(ProcessHarness, { key: view, state: view }) : null,
    MEMO_STATES[view] ? h(MemoSourceHarness, { key: view, state: view }) : null,
    QT_STATES[view] ? h(QuestionToolsHarness, { key: view, state: view }) : null,
    OV_STATES[view] ? h(OverviewHarness, { key: view, state: view }) : null,
    OL_STATES[view] ? h(OutlineHarness, { key: view, state: view }) : null,
    SG_STATES[view] ? h(SourceGroupsHarness, { key: view, state: view }) : null,
    SD_STATES[view] ? h(DiscoveryHarness, { key: view, state: view }) : null,
    DR_STATES[view] ? h(ResearchHarness, { key: view, state: view }) : null,
    view === "tools" ? h("div", { className: "workspace-app-actions" }, h(NotebookTools, { studio, title: "원본 노트북", counts: { sources: 3 }, onOpenChatSettings: () => {} })) : null);
}

createRoot(document.getElementById("root")).render(h(App));
