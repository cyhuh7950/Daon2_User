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
import { AnswerProcess } from "../../packages/ui/src/answer-process.jsx";
import { ProductWorkspaceShell } from "../../packages/ui/src/product-workspace-shell.jsx";
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
  const tabs = [["studio", "Studio 패널"], ["wizard", "작성 마법사"], ["tools", "노트북 도구"], ["home", "노트북 홈"], ["settings", "설정(지식 연결)"], ["tts", "설정(TTS 엔진)"], ["orgjoin", "조직 가입"], ["orgadmin", "조직 관리"], ["login", "로그인"], ...Object.entries(PROCESS_STATES).map(([key, value]) => [key, value.label]), ...Object.entries(MEMO_STATES).map(([key, value]) => [key, value.label])];
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
    view === "tools" ? h("div", { className: "workspace-app-actions" }, h(NotebookTools, { studio, title: "원본 노트북", counts: { sources: 3 }, onOpenChatSettings: () => {} })) : null);
}

createRoot(document.getElementById("root")).render(h(App));
