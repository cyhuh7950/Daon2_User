// NB2-U2 노트북 개요 화면(WO-N1 N1-4, 결정 D-06 자동 1회 + "다시 만들기"): 대화 영역 위쪽 개요.
// 상태: 없음(숨김) / 만드는 중(자리 표시) / 완료(요약 + 인용 칩 + 추천 질문 3개) / 낡음(안내 + 다시 만들기) / 실패(코드별 문구 + 다시 시도) / 차단(정책 문구 + 시작 제안 3개).
// 조작: 추천 질문 칩은 입력창에 채우기만 한다(전송 안 함). 인용 칩은 소스 보기를 연다. 접기는 노트북별로 기억한다.
// 이동: queued·working이면 짧은 간격으로 다시 읽고 none·ready·failed·blocked에서 멈춘다.
import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { MinimalEvent, findElements, installMinimalDom } from "./product-studio-dom.mjs";

const root = path.resolve(import.meta.dirname, "../..");

{
  const dom = installMinimalDom();
  await import("react");
  await import("react-dom/client");
  dom.restore();
}

let built = null;
async function bundle() {
  if (built) return built.module;
  const name = "notebook-overview";
  const output = await mkdtemp(path.join(root, `.${name}-`));
  try {
    const { build } = await import("vite");
    await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
      lib: { entry: path.join(root, "packages/ui/src/notebook-overview.jsx"), formats: ["es"], fileName: name },
      rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
    const file = (await readdir(output)).find((item) => item.startsWith(name) && /\.m?js$/u.test(item));
    const module = await import(`${pathToFileURL(path.join(output, file)).href}?v=${Date.now()}`);
    built = { module, output };
    return module;
  } catch (error) { await rm(output, { recursive: true, force: true }); throw error; }
}
test.after(async () => { if (built) await rm(built.output, { recursive: true, force: true }); });

const failure = (code, status) => Object.assign(new Error(code), { code, status });
const empty = (state, over = {}) => ({ state, summary: null, questions: [], citations: [], stale: false, generated_at: null, error_code: null, ...over });
const READY = {
  state: "ready",
  summary: "이 노트북은 보험금 지급 기준을 다룹니다.[1] 면책 기간은 계약일부터 90일입니다.[2]",
  questions: ["보험금 지급 기준은 무엇인가요?", "면책 기간은 언제까지인가요?", "청구에 필요한 서류는 무엇인가요?"],
  citations: [{ label: "1", source_title: "보험약관.pdf", page: 3 }, { label: "2", source_title: "청구 안내.docx", page: null }],
  stale: false, generated_at: "2026-11-24T01:00:00Z", error_code: null,
};

// 응답 순서를 정해 둔 가짜 어댑터. 마지막 응답은 계속 되풀이한다.
// 다시 만들기가 성공하면 서버처럼 다음 조회는 queued를 돌려준다(그 뒤로는 정해 둔 순서를 잇는다).
function fakeStudio(input, { regenerate } = {}) {
  const responses = [...input];
  const calls = { get: 0, regenerate: 0 };
  let index = 0;
  const studio = {
    getNotebookOverview: async () => {
      calls.get += 1;
      const value = responses[Math.min(index, responses.length - 1)];
      index += 1;
      if (value instanceof Error) throw value;
      return value;
    },
    regenerateNotebookOverview: async () => {
      calls.regenerate += 1;
      if (regenerate) return regenerate();
      responses.splice(Math.min(index, responses.length), 0, empty("queued"));
      return empty("queued");
    },
  };
  return { studio, calls };
}

function memoryStorage() {
  const data = new Map();
  return { data, getItem: (key) => (data.has(key) ? data.get(key) : null), setItem: (key, value) => { data.set(key, String(value)); }, removeItem: (key) => { data.delete(key); } };
}

const settle = async (act) => act(async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); });
const wait = async (act, ms) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });
// 폴링 결과를 기다린다. 전체 시험을 함께 돌려 타이머가 늦어져도 조건이 맞을 때까지(최대 3초) 기다린다.
async function until(act, predicate, timeoutMs = 3000) {
  const end = Date.now() + timeoutMs;
  while (!predicate() && Date.now() < end) await wait(act, 10);
  assert.ok(predicate(), "기다린 상태가 되지 않았다");
}
const stateOf = (container) => region(container)?.getAttribute("data-overview-state");

async function mount(props) {
  const dom = installMinimalDom();
  const module = await bundle();
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  const render = async (next) => { await act(async () => { reactRoot.render(createElement(module.NotebookOverview, { pollIntervalMs: 5, storage: memoryStorage(), ...next })); }); await settle(act); };
  await render(props);
  return { container, act, render,
    click: async (node) => { await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await settle(act); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); } };
}

const region = (container) => findElements(container, (node) => node.getAttribute?.("data-notebook-overview") !== null)[0];
const button = (container, text) => findElements(container, (node) => node.tagName === "BUTTON" && node.textContent.trim() === text)[0];
const questionChips = (container) => findElements(container, (node) => node.tagName === "BUTTON" && node.getAttribute("data-overview-question") !== null);
const citationChips = (container) => findElements(container, (node) => node.getAttribute?.("data-overview-citation") !== null);
const collapseButton = (container) => findElements(container, (node) => node.tagName === "BUTTON" && node.getAttribute("aria-expanded") !== null)[0];

test("없음(none): 개요를 그리지 않아 기존 빈 화면이 그대로 보이고 폴링하지 않는다", async () => {
  const { studio, calls } = fakeStudio([empty("none")]);
  const view = await mount({ studio, notebookId: "nb-1" });
  try {
    assert.equal(region(view.container), undefined);
    assert.equal(view.container.textContent, "");
    await wait(view.act, 40);
    assert.equal(calls.get, 1, "none은 끝 상태라 다시 읽지 않는다");
  } finally { await view.close(); }
});

test("만드는 중(queued→working→ready): 자리 표시를 보이고 짧은 간격으로 다시 읽다가 ready에서 멈춘다", async () => {
  const { studio, calls } = fakeStudio([empty("queued"), empty("working"), READY]);
  const view = await mount({ studio, notebookId: "nb-1" });
  try {
    assert.ok(region(view.container), "개요 영역이 보인다");
    assert.match(view.container.textContent, /개요를 만드는 중/u);
    assert.equal(region(view.container).getAttribute("data-overview-state"), "generating");
    assert.equal(region(view.container).getAttribute("aria-busy"), "true");
    await until(view.act, () => stateOf(view.container) === "ready");
    assert.equal(calls.get, 3);
    await wait(view.act, 40);
    assert.equal(calls.get, 3, "ready에서 폴링이 멈춘다");
  } finally { await view.close(); }
});

test("완료(ready): 요약 문단·인용 칩·추천 질문 칩 3개. 질문 칩은 입력창 채우기만 하고 전송하지 않는다", async () => {
  const { studio, calls } = fakeStudio([READY]);
  const asked = [];
  const opened = [];
  const view = await mount({ studio, notebookId: "nb-1", onAskQuestion: (text) => asked.push(text), onOpenSource: (citation) => opened.push(citation) });
  try {
    assert.match(view.container.textContent, /노트북 개요/u);
    assert.match(view.container.textContent, /보험금 지급 기준을 다룹니다/u);
    assert.match(view.container.textContent, /면책 기간은 계약일부터 90일입니다/u);
    assert.doesNotMatch(view.container.textContent, /\[1\]|\[2\]/u, "[n] 표시는 인용 칩으로 바뀐다");
    const chips = citationChips(view.container);
    assert.equal(chips.length, 2);
    assert.equal(chips[0].textContent.trim(), "1");
    assert.match(chips[0].getAttribute("aria-label"), /보험약관\.pdf/u);
    assert.match(chips[0].getAttribute("aria-label"), /3쪽/u);
    const questions = questionChips(view.container);
    assert.equal(questions.length, 3);
    assert.deepEqual(questions.map((node) => node.textContent.trim()), READY.questions);
    assert.ok(questions.every((node) => node.getAttribute("type") === "button"), "칩은 폼을 제출하지 않는다");
    await view.click(questions[1]);
    assert.deepEqual(asked, [READY.questions[1]]);
    assert.equal(calls.regenerate, 0);
    await view.click(chips[0]);
    assert.deepEqual(opened, [{ label: "1", source_title: "보험약관.pdf", page: 3 }]);
    assert.doesNotMatch(view.container.textContent, /소스가 바뀌었습니다/u);
    assert.ok(button(view.container, "다시 만들기"), "편집 권한을 모를 때는 다시 만들기를 보인다");
  } finally { await view.close(); }
});

test("인용 칩: 소스 보기 연결이 없으면 칩은 표시만 한다(버튼이 아니다)", async () => {
  const { studio } = fakeStudio([READY]);
  const view = await mount({ studio, notebookId: "nb-1" });
  try {
    const chips = citationChips(view.container);
    assert.equal(chips.length, 2);
    assert.ok(chips.every((node) => node.tagName !== "BUTTON"));
  } finally { await view.close(); }
});

test("낡음(stale): '소스가 바뀌었습니다'와 다시 만들기. 누르면 이전 내용을 비우고 만드는 중으로 바뀌어 폴링한다", async () => {
  const { studio, calls } = fakeStudio([{ ...READY, stale: true }, empty("working"), READY]);
  const view = await mount({ studio, notebookId: "nb-1" });
  try {
    assert.match(view.container.textContent, /소스가 바뀌었습니다/u);
    assert.match(view.container.textContent, /보험금 지급 기준/u, "낡아도 이전 개요는 보인다");
    await view.click(button(view.container, "다시 만들기"));
    assert.equal(calls.regenerate, 1);
    assert.match(view.container.textContent, /개요를 만드는 중/u);
    assert.doesNotMatch(view.container.textContent, /보험금 지급 기준을 다룹니다/u, "만드는 동안 이전 개요는 보이지 않는다");
    await until(view.act, () => stateOf(view.container) === "ready");
    assert.doesNotMatch(view.container.textContent, /소스가 바뀌었습니다/u);
    const settled = calls.get;
    await wait(view.act, 40);
    assert.equal(calls.get, settled);
  } finally { await view.close(); }
});

test("실패(failed): 오류 코드별 문구와 다시 시도. 코드는 그대로 보이지 않고 폴링은 멈춘다", async () => {
  const cases = [
    ["OVERVIEW_UNGROUNDED", /근거/u],
    ["OVERVIEW_PROVIDER_UNAVAILABLE", /모델에 연결하지 못해/u],
    ["OVERVIEW_GENERATION_FAILED", /개요를 만들지 못했습니다/u],
    ["OVERVIEW_NO_READY_SOURCE", /준비된 소스가 없어/u],
    [null, /개요를 만들지 못했습니다/u],
  ];
  for (const [code, pattern] of cases) {
    const { studio, calls } = fakeStudio([empty("failed", { error_code: code })]);
    const view = await mount({ studio, notebookId: "nb-1" });
    try {
      assert.equal(region(view.container).getAttribute("data-overview-state"), "failed");
      assert.match(view.container.textContent, pattern, String(code));
      assert.doesNotMatch(view.container.textContent, /OVERVIEW_/u);
      await wait(view.act, 30);
      assert.equal(calls.get, 1, "failed에서 다시 읽지 않는다");
      await view.click(button(view.container, "다시 시도"));
      assert.equal(calls.regenerate, 1);
      assert.match(view.container.textContent, /개요를 만드는 중/u);
    } finally { await view.close(); }
  }
});

test("차단(blocked): 정책 문구와 시작 제안 3개만. 요약·추천 질문·다시 만들기는 없고 폴링은 멈춘다", async () => {
  const { studio, calls } = fakeStudio([empty("blocked", { error_code: "OVERVIEW_BLOCKED" })]);
  const view = await mount({ studio, notebookId: "nb-1", onAskQuestion: () => {} });
  try {
    assert.equal(region(view.container).getAttribute("data-overview-state"), "blocked");
    assert.match(view.container.textContent, /외부 전송 정책으로 개요를 만들 수 없습니다/u);
    const suggestions = findElements(view.container, (node) => node.getAttribute?.("data-overview-start") !== null);
    assert.equal(suggestions.length, 3);
    assert.deepEqual(suggestions.map((node) => node.textContent.trim()), ["새로운 주제에 관해 알아보기", "새로운 항목 만들기", "프로젝트 진행하기"]);
    assert.equal(questionChips(view.container).length, 0);
    assert.equal(button(view.container, "다시 만들기"), undefined);
    assert.equal(button(view.container, "다시 시도"), undefined);
    await wait(view.act, 30);
    assert.equal(calls.get, 1);
  } finally { await view.close(); }
});

test("다시 만들기 409 OVERVIEW_IN_PROGRESS: 안내를 보이고 다시 읽어 진행 상태를 따라간다", async () => {
  const { studio, calls } = fakeStudio([{ ...READY, stale: true }, empty("working"), READY], { regenerate: async () => { throw failure("OVERVIEW_IN_PROGRESS", 409); } });
  const view = await mount({ studio, notebookId: "nb-1" });
  try {
    await view.click(button(view.container, "다시 만들기"));
    assert.equal(calls.regenerate, 1);
    assert.match(view.container.textContent, /이미 개요를 만들고 있습니다/u);
    await until(view.act, () => stateOf(view.container) === "ready" && calls.get >= 3);
  } finally { await view.close(); }
});

test("다시 만들기 409 OVERVIEW_NO_READY_SOURCE: 준비된 소스가 없다는 안내", async () => {
  const { studio } = fakeStudio([{ ...READY, stale: true }], { regenerate: async () => { throw failure("OVERVIEW_NO_READY_SOURCE", 409); } });
  const view = await mount({ studio, notebookId: "nb-1" });
  try {
    await view.click(button(view.container, "다시 만들기"));
    assert.match(view.container.textContent, /준비된 소스가 없어/u);
    assert.doesNotMatch(view.container.textContent, /OVERVIEW_/u);
  } finally { await view.close(); }
});

test("다시 만들기 403: 편집 권한이 없다는 안내를 보이고 다시 만들기 버튼을 숨긴다", async () => {
  const { studio } = fakeStudio([{ ...READY, stale: true }], { regenerate: async () => { throw failure("FORBIDDEN", 403); } });
  const view = await mount({ studio, notebookId: "nb-1" });
  try {
    await view.click(button(view.container, "다시 만들기"));
    assert.equal(button(view.container, "다시 만들기"), undefined);
    assert.match(view.container.textContent, /편집할 권한이 없어/u);
    assert.match(view.container.textContent, /소스가 바뀌었습니다/u, "낡음 안내는 남는다");
  } finally { await view.close(); }
});

test("접기: 노트북별로 브라우저 저장에 기억하고, 다시 열면 같은 상태다. 저장이 막혀도 접기는 동작한다", async () => {
  const storage = memoryStorage();
  const { studio } = fakeStudio([READY]);
  let view = await mount({ studio, notebookId: "nb-1", storage });
  try {
    const toggle = collapseButton(view.container);
    assert.equal(toggle.getAttribute("aria-expanded"), "true");
    await view.click(toggle);
    assert.equal(collapseButton(view.container).getAttribute("aria-expanded"), "false");
    assert.doesNotMatch(view.container.textContent, /보험금 지급 기준을 다룹니다/u, "접으면 본문을 숨긴다");
    assert.equal(questionChips(view.container).length, 0);
    assert.ok([...storage.data.keys()].some((key) => key.includes("nb-1")), "노트북 ID로 저장한다");
  } finally { await view.close(); }

  view = await mount({ studio: fakeStudio([READY]).studio, notebookId: "nb-1", storage });
  try {
    assert.equal(collapseButton(view.container).getAttribute("aria-expanded"), "false", "다시 열어도 접힌 상태");
    await view.click(collapseButton(view.container));
    assert.equal(collapseButton(view.container).getAttribute("aria-expanded"), "true");
    assert.equal(questionChips(view.container).length, 3);
  } finally { await view.close(); }

  const other = memoryStorage();
  other.setItem("daon.notebook-overview.collapsed.nb-1", "1");
  view = await mount({ studio: fakeStudio([READY]).studio, notebookId: "nb-2", storage: other });
  try {
    assert.equal(collapseButton(view.container).getAttribute("aria-expanded"), "true", "다른 노트북은 따로");
  } finally { await view.close(); }

  const broken = { getItem: () => { throw new Error("SecurityError"); }, setItem: () => { throw new Error("QuotaExceeded"); }, removeItem: () => { throw new Error("SecurityError"); } };
  view = await mount({ studio: fakeStudio([READY]).studio, notebookId: "nb-1", storage: broken });
  try {
    assert.equal(collapseButton(view.container).getAttribute("aria-expanded"), "true");
    await view.click(collapseButton(view.container));
    assert.equal(collapseButton(view.container).getAttribute("aria-expanded"), "false");
  } finally { await view.close(); }
});

test("소스 목록이 바뀌면(refreshKey) 개요를 다시 읽는다: none → 자동 queued", async () => {
  const { studio, calls } = fakeStudio([empty("none"), empty("queued"), READY]);
  const view = await mount({ studio, notebookId: "nb-1", refreshKey: "" });
  try {
    assert.equal(region(view.container), undefined);
    await view.render({ studio, notebookId: "nb-1", refreshKey: "sv-1" });
    assert.match(view.container.textContent, /개요를 만드는 중/u);
    await until(view.act, () => stateOf(view.container) === "ready");
    assert.equal(calls.get, 3);
  } finally { await view.close(); }
});

test("불러오기 실패: 안내와 다시 시도. 누르면 다시 읽는다", async () => {
  const { studio, calls } = fakeStudio([failure("STUDIO_REQUEST_FAILED", 503), READY]);
  const view = await mount({ studio, notebookId: "nb-1" });
  try {
    assert.match(view.container.textContent, /개요를 불러오지 못했습니다/u);
    await wait(view.act, 30);
    assert.equal(calls.get, 1, "실패 뒤 자동으로 계속 읽지 않는다");
    await view.click(button(view.container, "다시 시도"));
    assert.equal(calls.get, 2);
    assert.equal(region(view.container).getAttribute("data-overview-state"), "ready");
  } finally { await view.close(); }
});

test("어댑터에 개요 함수가 없으면 그리지 않는다", async () => {
  const view = await mount({ studio: {}, notebookId: "nb-1" });
  try { assert.equal(view.container.textContent, ""); } finally { await view.close(); }
});

test("새 컴포넌트는 한글 문구를 직접 쓰지 않고 notebook.overview.* 키만 쓴다", async () => {
  const source = await readFile(path.join(root, "packages/ui/src/notebook-overview.jsx"), "utf8");
  const code = source.split("\n").filter((line) => !/^\s*(\/\/|\/\*|\*)/u.test(line)).join("\n").replace(/\/\/.*$/gmu, "");
  assert.doesNotMatch(code, /[가-힣]/u);
  const messages = await readFile(path.join(root, "packages/ui/src/notebook-messages.ko.js"), "utf8");
  for (const key of new Set([...source.matchAll(/"(notebook\.overview\.[a-z_.]+)"/gu)].map((match) => match[1]))) {
    assert.ok(messages.includes(`"${key}"`), key);
  }
});
