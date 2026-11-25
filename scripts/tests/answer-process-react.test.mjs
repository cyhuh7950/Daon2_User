// NB1-U1 답변 과정 화면(WO-N1 N1-1): 5상태 렌더, 펼침/접힘, 근거 클릭이 Citation과 같은 소스 보기로 이어짐.
import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { citationContentUrl } from "../../apps/web/lib/question-answering-api.js";
import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

const root = path.resolve(import.meta.dirname, "../..");

// react·react-dom은 묶기(vite build가 NODE_ENV를 production으로 바꿈) 전에, DOM이 있는 상태로 한 번 읽어 둔다(다른 React 시험과 같은 순서).
{
  const dom = installMinimalDom();
  await import("react");
  await import("react-dom/client");
  dom.restore();
}

async function bundle(entry, name) {
  const output = await mkdtemp(path.join(root, `.${name}-`));
  const cleanup = () => rm(output, { recursive: true, force: true });
  try {
    const { build } = await import("vite");
    await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
      lib: { entry: path.join(root, entry), formats: ["es"], fileName: name },
      rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
    const built = (await readdir(output)).find((file) => file.startsWith(name) && /\.m?js$/u.test(file));
    const module = await import(`${pathToFileURL(path.join(output, built)).href}?v=${Date.now()}`);
    return { module, cleanup };
  } catch (error) { await cleanup(); throw error; }
}

const evidenceItem = (over = {}) => ({ title: "약관.txt", page: 3, origin: "raw_source", source_id: "source-1", source_version_id: "version-1", ...over });
const normal = () => ({ version: 1,
  scope: { source_count: 2, knowledge_packages: [{ name: "제안서 작업" }], tools: null },
  evidence: { searched: 24, selected: [evidenceItem(), evidenceItem({ title: "규정.pdf", page: null, source_id: "source-2", source_version_id: "version-2" })] },
  egress: { decision: "allowed", masked: true, redacted: false, policy_ref: "3f2a9c1b0d4e" },
  model: { connection: "Media Bridge", model: "uss/solar-pro4", reasoning: "high" },
  verification: { citations: 3, valid: true, insufficient: false, retried: false } });
const insufficient = () => ({ ...normal(), verification: { citations: 0, valid: true, insufficient: true, retried: true } });
const blocked = () => ({ ...normal(), egress: { decision: "blocked", masked: false, redacted: false, policy_ref: "3f2a9c1b0d4e" }, model: null, verification: null });
const general = () => ({ ...normal(), scope: { source_count: 0, knowledge_packages: [], tools: null }, evidence: null,
  egress: { decision: "not_needed", masked: false, redacted: false, policy_ref: null } });

async function mountProcess(props) {
  const dom = installMinimalDom();
  const { module, cleanup } = await bundle("packages/ui/src/answer-process.jsx", "answer-process-react");
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(module.AnswerProcess, props)); });
  const toggle = () => findElements(container, (node) => node.tagName === "BUTTON" && node.getAttribute("aria-expanded") !== null)[0];
  return { container, act, toggle,
    open: async () => act(async () => { toggle().dispatchEvent(new MinimalEvent("click")); }),
    steps: () => findElements(container, (node) => node.tagName === "LI" && node.getAttribute("data-step") !== null),
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await cleanup(); } };
}

test("답변 과정은 기본 접힘이고 버튼으로 펼침/접힘하며 aria-expanded·aria-controls를 맞춘다", async () => {
  const view = await mountProcess({ process: normal() });
  try {
    const toggle = view.toggle();
    assert.equal(toggle.tagName, "BUTTON");
    assert.equal(toggle.getAttribute("type"), "button");
    assert.equal(toggle.textContent.trim(), "답변 과정");
    assert.equal(toggle.getAttribute("aria-expanded"), "false");
    assert.equal(view.steps().length, 0);
    await view.open();
    assert.equal(view.toggle().getAttribute("aria-expanded"), "true");
    const panelId = view.toggle().getAttribute("aria-controls");
    assert.ok(panelId);
    assert.equal(findElements(view.container, (node) => node.getAttribute?.("id") === panelId).length, 1);
    await view.open();
    assert.equal(view.toggle().getAttribute("aria-expanded"), "false");
    assert.equal(view.steps().length, 0);
  } finally { await view.close(); }
});

test("정상 상태는 순서 목록에 다섯 단계를 서버 값만으로 보여 주고 tools가 null이면 도구 줄을 생략한다", async () => {
  const view = await mountProcess({ process: normal() });
  try {
    await view.open();
    const list = findElements(view.container, (node) => node.tagName === "OL");
    assert.equal(list.length, 1);
    assert.deepEqual(view.steps().map((node) => node.getAttribute("data-step")), ["scope", "evidence", "egress", "model", "verification"]);
    const text = view.container.textContent;
    for (const expected of ["질문 범위", "소스 2개", "제안서 작업", "근거 찾기", "찾은 구간 24개", "약관.txt", "3쪽", "규정.pdf",
      "외부 전송", "허용", "가림 적용", "삭제 없음", "모델", "Media Bridge", "uss/solar-pro4", "high", "검증", "인용 3개 확인", "재요청 없음"]) {
      assert.ok(text.includes(expected), `missing ${expected}`);
    }
    assert.doesNotMatch(text, /도구/u);
    assert.equal(view.steps().filter((node) => node.getAttribute("data-emphasis") === "true").length, 0);
  } finally { await view.close(); }
});

test("tools 배열이 있으면 도구 줄을 보인다", async () => {
  const view = await mountProcess({ process: { ...normal(), scope: { ...normal().scope, tools: ["법령 찾기"] } } });
  try {
    await view.open();
    assert.match(view.container.textContent, /도구: 법령 찾기/u);
  } finally { await view.close(); }
});

test("근거 부족 상태는 검증 단계를 색 말고 글자로도 강조한다", async () => {
  const view = await mountProcess({ process: insufficient() });
  try {
    await view.open();
    const verification = view.steps().find((node) => node.getAttribute("data-step") === "verification");
    assert.equal(verification.getAttribute("data-emphasis"), "true");
    assert.match(verification.textContent, /근거 부족/u);
    assert.match(verification.textContent, /확인 필요/u);
    assert.match(verification.textContent, /재요청함/u);
    assert.equal(view.steps().filter((node) => node.getAttribute("data-emphasis") === "true").length, 1);
  } finally { await view.close(); }
});

test("외부 전송 차단 상태는 외부 전송 단계를 강조하고 모델·검증은 하지 않았다고 표시한다", async () => {
  const view = await mountProcess({ process: blocked() });
  try {
    await view.open();
    const egress = view.steps().find((node) => node.getAttribute("data-step") === "egress");
    assert.equal(egress.getAttribute("data-emphasis"), "true");
    assert.match(egress.textContent, /차단/u);
    assert.match(egress.textContent, /확인 필요/u);
    assert.match(view.container.textContent, /모델을 호출하지 않았습니다/u);
    assert.match(view.container.textContent, /검증하지 않았습니다/u);
  } finally { await view.close(); }
});

test("일반 대화 상태는 근거 찾기 단계 없이 네 단계만 보인다", async () => {
  const view = await mountProcess({ process: general() });
  try {
    await view.open();
    assert.deepEqual(view.steps().map((node) => node.getAttribute("data-step")), ["scope", "egress", "model", "verification"]);
    assert.match(view.container.textContent, /소스 0개/u);
    assert.match(view.container.textContent, /필요 없음/u);
  } finally { await view.close(); }
});

test("기록 없음 상태는 버튼을 보이고 펼치면 '과정 기록 없음' 한 줄만 보인다", async () => {
  const view = await mountProcess({ process: null });
  try {
    assert.equal(view.toggle().textContent.trim(), "답변 과정");
    await view.open();
    assert.equal(view.steps().length, 0);
    assert.match(view.container.textContent, /과정 기록 없음/u);
  } finally { await view.close(); }
});

test("근거 항목은 열 수 있을 때만 버튼이며 누르면 onOpenEvidence에 그 항목을 넘긴다", async () => {
  const opened = [];
  const view = await mountProcess({ process: normal(), canOpenEvidence: (item) => item.source_id === "source-1",
    onOpenEvidence: (event, item) => opened.push({ item, hasEvent: typeof event?.preventDefault === "function" }) });
  try {
    await view.open();
    const evidenceButtons = findElements(view.container, (node) => node.tagName === "BUTTON" && node.getAttribute("data-evidence") !== null);
    assert.equal(evidenceButtons.length, 1);
    assert.match(evidenceButtons[0].textContent, /약관\.txt/u);
    assert.match(evidenceButtons[0].getAttribute("aria-label"), /약관\.txt/u);
    await view.act(async () => { evidenceButtons[0].dispatchEvent(new MinimalEvent("click")); });
    assert.equal(opened.length, 1);
    assert.equal(opened[0].item.source_id, "source-1");
    assert.equal(opened[0].item.source_version_id, "version-1");
    assert.equal(opened[0].hasEvent, true);
    assert.match(view.container.textContent, /규정\.pdf/u);
  } finally { await view.close(); }
});

test("새 컴포넌트 코드에는 한글 문구가 없고 문구는 notebook-messages.ko.js의 notebook.process.* 키에만 있다", async () => {
  const source = await readFile(path.join(root, "packages/ui/src/answer-process.jsx"), "utf8");
  const code = source.replace(/\/\*[\s\S]*?\*\//gu, "").replace(/(^|[^:])\/\/.*$/gmu, "$1");
  assert.doesNotMatch(code, /[가-힣]/u);
  const { NOTEBOOK_MESSAGES } = await import(pathToFileURL(path.join(root, "packages/ui/src/notebook-messages.ko.js")).href);
  const used = [...new Set([...code.matchAll(/["'`](notebook\.process\.[a-z0-9_.]+)["'`]/gu)].map((match) => match[1]))];
  assert.ok(used.length >= 10);
  for (const key of used) assert.equal(typeof NOTEBOOK_MESSAGES[key], "string", key);
  assert.doesNotMatch(code, /\bfetch\(/u);
});

// ---- 대화창 연결(product-workspace-shell) ----

const withHiddenProcess = (answer, process) => {
  Object.defineProperty(answer, "process", { value: process, enumerable: false, writable: false, configurable: false });
  return answer;
};
const citation = { citation_id: "citation-1", source_id: "source-1", source_version_id: "version-1", evidence_span_id: "span-1",
  page: 3, origin: "raw_source", context_item_id: "source-1", locator: { kind: "page", value: "3" } };
const storedAnswer = (process) => withHiddenProcess({ run_id: "run-1", run_result_id: "result-1", answer: "저장된 답변", insufficient: false, citations: [{ ...citation }] }, process);
const citationUrl = (value) => citationContentUrl("workspace-1", value, { notebookId: "notebook-1" });
const sources = [{ source_id: "source-1", source_version_id: "version-1", filename: "약관.txt", source_state: "ready", processing_state: "completed", job_state: "completed" }];

test("투영은 열거되지 않는 answer.process를 평범한 process 키로 옮기고 없으면 null로 둔다", async () => {
  const { module, cleanup } = await bundle("packages/ui/src/product-workspace-shell.jsx", "answer-process-projection");
  try {
    const selected = [{ sourceId: "source-1", sourceVersionId: "version-1" }];
    const projected = module.projectSafeQuestionAnswer(storedAnswer(normal()), "workspace-1", citationUrl, selected);
    assert.ok(Object.keys(projected).includes("process"));
    assert.deepEqual(projected.process, normal());
    const plain = { run_id: "run-1", run_result_id: "result-1", answer: "답", insufficient: false, citations: [{ ...citation }] };
    assert.equal(module.projectSafeQuestionAnswer(plain, "workspace-1", citationUrl, selected).process, null);
    const turns = module.projectChatTurns([{ run_id: "run-1", question: "질문", state: "completed", answer: storedAnswer(insufficient()) }], "workspace-1", citationUrl);
    assert.deepEqual(turns[0].answer.process, insufficient());
    assert.equal(module.projectChatTurns([{ run_id: "run-2", question: "질문", state: "completed", answer: storedAnswer(null) }], "workspace-1", citationUrl)[0].answer.process, null);
  } finally { await cleanup(); }
});

async function mountShell(effectAdapter) {
  const dom = installMinimalDom();
  const { module, cleanup } = await bundle("packages/ui/src/product-workspace-shell.jsx", "answer-process-shell");
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(module.ProductWorkspaceShell, { workspaceId: "workspace-1", adapter: effectAdapter })); await Promise.resolve(); await Promise.resolve(); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  return { container, act,
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await cleanup(); } };
}
const baseAdapter = (over = {}) => ({ listSources: async () => sources, uploadPdf() {}, getProcessingStatus() {}, askQuestion() {}, citationUrl,
  createReport() {}, listStudioOutputs: async () => [], listConnectors: async () => [], listKnowledgePackages: async () => [],
  notebookContext: { notebook_id: "notebook-1", sources: [] }, ...over });

test("노트북을 다시 열면 저장된 답변 아래 답변 과정이 보이고 근거 클릭은 Citation 클릭과 같은 소스 보기 함수로 간다", async () => {
  const opened = [];
  const view = await mountShell(baseAdapter({
    loadChatTurns: async () => [{ run_id: "run-1", question: "약관 내용", state: "completed", answer: storedAnswer(normal()) }],
    citationContent: async (value) => { opened.push(value); throw new Error("CITATION_CONTENT_UNAVAILABLE"); },
  }));
  try {
    assert.match(view.container.textContent, /저장된 답변/u);
    const toggle = buttonByText(view.container, "답변 과정");
    assert.ok(toggle, "답변 과정 버튼");
    assert.equal(toggle.getAttribute("aria-expanded"), "false");
    await view.act(async () => { toggle.dispatchEvent(new MinimalEvent("click")); });
    assert.match(view.container.textContent, /찾은 구간 24개/u);
    const evidenceButtons = findElements(view.container, (node) => node.tagName === "BUTTON" && node.getAttribute("data-evidence") !== null);
    assert.equal(evidenceButtons.length, 1, "Citation과 맞는 근거만 열 수 있다");
    await view.act(async () => { evidenceButtons[0].dispatchEvent(new MinimalEvent("click")); await Promise.resolve(); await Promise.resolve(); });
    const link = findElements(view.container, (node) => node.tagName === "A" && node.parentNode?.getAttribute?.("class") === "citation-row")[0];
    assert.ok(link);
    await view.act(async () => { link.dispatchEvent(new MinimalEvent("click")); await Promise.resolve(); await Promise.resolve(); });
    assert.equal(opened.length, 2);
    assert.equal(opened[0].citation_id, "citation-1");
    assert.deepEqual(opened[0], opened[1]);
  } finally { await view.close(); }
});

test("과정이 없는 과거 답변은 버튼을 보이고 펼치면 '과정 기록 없음'을 보인다", async () => {
  const view = await mountShell(baseAdapter({
    loadChatTurns: async () => [{ run_id: "run-1", question: "약관 내용", state: "completed", answer: storedAnswer(null) }],
  }));
  try {
    const toggle = buttonByText(view.container, "답변 과정");
    assert.ok(toggle);
    await view.act(async () => { toggle.dispatchEvent(new MinimalEvent("click")); });
    assert.match(view.container.textContent, /과정 기록 없음/u);
  } finally { await view.close(); }
});

const composer = (view) => findElements(view.container, (node) => node.tagName === "FORM" && node.getAttribute("class") === "conversation-composer")[0];
const reactProps = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];
async function ask(view, text = "약관 내용을 알려 주세요") {
  const textarea = findElements(view.container, (node) => node.tagName === "TEXTAREA")[0];
  textarea.value = text;
  await view.act(async () => reactProps(textarea).onChange({ currentTarget: textarea, target: textarea }));
  await view.act(async () => { await reactProps(composer(view)).onSubmit({ preventDefault() {} }); });
}

test("질문 직후 답변 아래에 답변 과정이 붙는다", async () => {
  const view = await mountShell(baseAdapter({ askQuestion: async () => storedAnswer(insufficient()) }));
  try {
    await ask(view);
    const toggle = buttonByText(view.container, "답변 과정");
    assert.ok(toggle);
    await view.act(async () => { toggle.dispatchEvent(new MinimalEvent("click")); });
    const verification = findElements(view.container, (node) => node.tagName === "LI" && node.getAttribute("data-step") === "verification")[0];
    assert.equal(verification.getAttribute("data-emphasis"), "true");
  } finally { await view.close(); }
});

test("외부 전송 차단 오류는 오류 카드 안에 외부 전송 단계를 강조한 답변 과정을 보인다", async () => {
  const view = await mountShell(baseAdapter({ askQuestion: async () => {
    const error = new Error("EGRESS_POLICY_DENIED"); error.process = blocked(); throw error;
  } }));
  try {
    await ask(view);
    const alert = findElements(view.container, (node) => node.getAttribute?.("role") === "alert" && node.textContent.includes("답변 과정"))[0];
    assert.ok(alert, "오류 카드 안의 답변 과정");
    const toggle = findElements(alert, (node) => node.tagName === "BUTTON" && node.getAttribute("aria-expanded") !== null)[0];
    await view.act(async () => { toggle.dispatchEvent(new MinimalEvent("click")); });
    const egress = findElements(alert, (node) => node.tagName === "LI" && node.getAttribute("data-step") === "egress")[0];
    assert.equal(egress.getAttribute("data-emphasis"), "true");
  } finally { await view.close(); }
});

test("과정이 없는 일반 실패 오류 카드에는 답변 과정을 붙이지 않는다", async () => {
  const view = await mountShell(baseAdapter({ askQuestion: async () => { throw new Error("QUESTION_FAILED"); } }));
  try {
    await ask(view);
    assert.equal(buttonByText(view.container, "답변 과정"), undefined);
  } finally { await view.close(); }
});

// 후속 A-4·A-5: 같은 소스의 근거가 똑같은 이름으로 두 번, 인용 0개인데 "인용이 근거 구간과 맞습니다"가 보였다.
test("근거 찾기 목록에서 이름이 같은 근거에는 순번을 붙인다", async () => {
  const same = evidenceItem({ title: "약관_보장범위.txt", page: null });
  const view = await mountProcess({ process: { ...normal(), evidence: { searched: 2, selected: [same, { ...same }] } } });
  try {
    await view.open();
    const evidence = view.steps().find((node) => node.getAttribute("data-step") === "evidence");
    assert.match(evidence.textContent, /약관_보장범위\.txt 1/u);
    assert.match(evidence.textContent, /약관_보장범위\.txt 2/u);
  } finally { await view.close(); }
});

test("인용이 0개면 검증 단계는 '인용 없음'만 보이고 '인용이 근거 구간과 맞습니다'를 보이지 않는다", async () => {
  const view = await mountProcess({ process: insufficient() });
  try {
    await view.open();
    const verification = view.steps().find((node) => node.getAttribute("data-step") === "verification");
    assert.match(verification.textContent, /인용 없음/u);
    assert.doesNotMatch(verification.textContent, /인용이 근거 구간과 맞습니다/u);
    assert.doesNotMatch(verification.textContent, /인용 0개 확인/u);
  } finally { await view.close(); }
});
