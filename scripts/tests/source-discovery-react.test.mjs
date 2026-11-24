// NB4-U1 빠른 찾기 화면(WO-N1 N1-7, 결정 D-02 웹 제외 — 내부 승인 지식·지식 연결만).
// 조작: 소스 칸 위쪽 검색창("필요한 자료를 찾아보세요"), 범위 칩(승인 지식·문서), 방식 전환(빠른 찾기·심층 조사 — 심층 조사는 NB4-U2),
//       후보마다 체크칸, "선택한 자료 추가".
// 상태: 찾는 중 / 결과 없음 / 범위 사용 불가(칩 흐리게, 이유) / 일부 범위 실패(결과 위 한 줄) / 추가 중 / 추가됨 / 추가 실패 / 보기 권한(추가 숨김).
// 이동: 추가된 소스는 소스 목록에 처리 중으로, 승인 지식 패키지는 승인 지식 영역에 반영(셸이 목록을 다시 읽는다).
// 배치: 결과 목록이 길어도 목록 창 안에서만 스크롤하고 노트북 페이지 전체는 늘어나지 않는다(실제 브라우저로 잰다).
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
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

const bundles = new Map();
async function bundle(name, entry) {
  if (bundles.has(name)) return bundles.get(name).module;
  const output = await mkdtemp(path.join(root, `.${name}-`));
  try {
    const { build } = await import("vite");
    await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
      lib: { entry: path.join(root, entry), formats: ["es"], fileName: name },
      rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
    const file = (await readdir(output)).find((item) => item.startsWith(name) && /\.m?js$/u.test(item));
    const module = await import(`${pathToFileURL(path.join(output, file)).href}?v=${Date.now()}`);
    bundles.set(name, { module, output });
    return module;
  } catch (error) { await rm(output, { recursive: true, force: true }); throw error; }
}
test.after(async () => { for (const { output } of bundles.values()) await rm(output, { recursive: true, force: true }); });

const failure = (code, status) => Object.assign(new Error(code), { code, status });
const deferred = () => { let resolve; let reject; const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; }); return { promise, resolve, reject }; };
const flush = () => new Promise((resolve) => setTimeout(resolve, 5));
const props = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];

const pkgRef = (n) => ({ kind: "knowledge_package", project_id: "project-1", work_package_id: `wp-${n}` });
const docRef = (n) => ({ kind: "document", project_id: "project-1", work_package_id: "wp-1", document_id: `doc-${n}`, document_version: "v1" });
const pkg = (n, over = {}) => ({ candidate_id: `cand-k${n}`, kind: "knowledge_package", title: `보험 업무 패키지 ${n}`, origin_label: "Daon2 승인 지식",
  reason: "검색어와 업무 이름이 맞습니다", preview: `패키지 ${n} 설명`, action: "add_scope", ref: pkgRef(n), ...over });
const doc = (n, over = {}) => ({ candidate_id: `cand-d${n}`, kind: "document", title: `약관 해설서 ${n}.pdf`, origin_label: "Daon2-RAG 문서",
  reason: "본문에 검색어가 있습니다", preview: `해설서 ${n}의 앞부분 미리보기`, action: "add_source", ref: docRef(n), ...over });

// 서버처럼 동작하는 가짜 빠른 찾기 어댑터. search/add는 테스트가 바꿔 끼울 수 있다.
function fakeDiscovery({ search, add } = {}) {
  const calls = [];
  const studio = {
    searchSourceDiscovery: async (query, scopes, options) => {
      calls.push(["search", query, [...scopes], options]);
      return search ? search(query, scopes, calls.length) : { candidates: [pkg(1), doc(1)], unavailable: [] };
    },
    addSourceDiscovery: async (ref, options) => {
      calls.push(["add", ref, options]);
      if (add) return add(ref, calls.length);
      return ref.kind === "document" ? { added: "source", sourceId: `source-new-${ref.document_id}` } : { added: "scope", sourceId: null };
    },
  };
  return { studio, calls, searches: () => calls.filter((c) => c[0] === "search"), adds: () => calls.filter((c) => c[0] === "add") };
}

async function mountPanel(options) {
  const { SourceDiscoveryPanel } = await bundle("source-discovery", "packages/ui/src/source-discovery.jsx");
  const dom = installMinimalDom();
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  const added = [];
  let current = { notebookId: "notebook-1", onAdded: (event) => added.push(event), ...options };
  const render = async (next = {}) => { current = { ...current, ...next }; await act(async () => { reactRoot.render(createElement(SourceDiscoveryPanel, current)); await flush(); }); };
  await render();
  const find = (predicate) => findElements(container, predicate);
  const byLabel = (tag, label) => find((node) => node.tagName === tag && node.getAttribute("aria-label") === label)[0];
  const button = (text) => find((node) => node.tagName === "BUTTON" && node.textContent.trim() === text)[0];
  const click = async (node) => { assert.ok(node, "누를 대상이 있어야 한다"); await act(async () => { node.dispatchEvent(new MinimalEvent("click")); await flush(); }); };
  const type = async (text) => {
    const input = byLabel("INPUT", "찾을 자료");
    input.value = text;
    await act(async () => { props(input).onChange({ target: input, currentTarget: input }); });
  };
  const submit = async () => {
    const form = find((node) => node.tagName === "FORM" && node.getAttribute("aria-label") === "자료 찾기 검색")[0];
    await act(async () => { void props(form).onSubmit({ preventDefault() {} }); await flush(); });
  };
  const search = async (text = "보험 약관") => { await type(text); await submit(); };
  const row = (candidateId) => find((node) => node.tagName === "LI" && node.getAttribute("data-candidate-id") === candidateId)[0];
  const check = (title) => byLabel("INPUT", `${title} 선택`);
  const status = () => find((node) => node.getAttribute("role") === "status" && node.getAttribute("data-discovery-status") !== null)[0]?.textContent ?? "";
  return { container, act, render, find, byLabel, button, click, type, submit, search, row, check, status, added,
    text: () => container.textContent,
    cleanup: async () => { await act(async () => reactRoot.unmount()); dom.restore(); } };
}

const scopeChip = (view, label) => view.find((node) => node.tagName === "BUTTON" && node.getAttribute("data-scope") !== null && node.textContent.includes(label))[0];

test("빠른 찾기 기능이 없는 어댑터에서는 아무것도 그리지 않는다", async () => {
  const view = await mountPanel({ studio: { listOutputs: async () => ({ items: [] }) } });
  try {
    assert.equal(view.container.childNodes.length, 0);
  } finally { await view.cleanup(); }
});

test("처음 화면: 검색창 안내 문구, 범위 칩 둘 다 켬, 방식은 빠른 찾기(심층 조사는 준비 중으로 누를 수 없음)", async () => {
  const fake = fakeDiscovery();
  const view = await mountPanel({ studio: fake.studio });
  try {
    const input = view.byLabel("INPUT", "찾을 자료");
    assert.ok(input);
    assert.equal(input.getAttribute("placeholder"), "필요한 자료를 찾아보세요");
    assert.equal(input.getAttribute("maxLength") ?? input.getAttribute("maxlength"), "500");
    assert.equal(scopeChip(view, "승인 지식").getAttribute("aria-pressed"), "true");
    assert.equal(scopeChip(view, "문서").getAttribute("aria-pressed"), "true");
    assert.equal(view.button("빠른 찾기").getAttribute("aria-pressed"), "true");
    assert.equal(view.button("심층 조사").disabled, true, "심층 조사는 NB4-U2에서 연결");
    assert.equal(view.button("찾기").disabled, true, "검색어가 없으면 찾기 버튼을 누를 수 없다");
    assert.equal(view.byLabel("UL", "찾은 자료 목록"), undefined, "검색 전에는 결과 목록이 없다");
    assert.equal(view.button("선택한 자료 추가"), undefined);
  } finally { await view.cleanup(); }
});

test("찾는 중 → 결과: 고른 범위로 찾고, 후보마다 제목·출처·관련 이유·미리보기·체크칸이 보인다", async () => {
  const gate = deferred();
  const fake = fakeDiscovery({ search: async () => { await gate.promise; return { candidates: [pkg(1), doc(1), doc(2)], unavailable: [] }; } });
  const view = await mountPanel({ studio: fake.studio });
  try {
    await view.click(scopeChip(view, "문서"));
    assert.equal(scopeChip(view, "문서").getAttribute("aria-pressed"), "false");
    await view.click(scopeChip(view, "문서"));
    await view.search("  보험 약관  ");
    assert.match(view.status(), /찾는 중/u);
    assert.equal(view.button("찾는 중").disabled, true, "찾는 동안 다시 찾기를 막는다");
    assert.deepEqual(fake.searches().map((c) => [c[1], c[2]]), [["보험 약관", ["knowledge", "documents"]]], "앞뒤 공백을 빼고 두 범위로 찾는다");
    await view.act(async () => { gate.resolve(); await flush(); });
    assert.match(view.status(), /자료 3개를 찾았습니다/u);
    const list = view.byLabel("UL", "찾은 자료 목록");
    assert.ok(list);
    assert.deepEqual(findElements(list, (n) => n.tagName === "LI").map((li) => li.getAttribute("data-candidate-id")), ["cand-k1", "cand-d1", "cand-d2"]);
    const first = view.row("cand-k1").textContent;
    for (const part of ["보험 업무 패키지 1", "Daon2 승인 지식", "검색어와 업무 이름이 맞습니다", "패키지 1 설명", "업무 패키지", "승인 지식 범위에 추가"]) assert.ok(first.includes(part), part);
    const second = view.row("cand-d1").textContent;
    for (const part of ["약관 해설서 1.pdf", "Daon2-RAG 문서", "해설서 1의 앞부분 미리보기", "텍스트 소스로 추가"]) assert.ok(second.includes(part), part);
    assert.ok(view.check("보험 업무 패키지 1"));
    assert.equal(view.button("선택한 자료 추가").disabled, true, "아무것도 고르지 않으면 추가할 수 없다");
    await view.click(view.check("약관 해설서 2.pdf"));
    assert.equal(view.button("선택한 자료 추가").disabled, false);
    assert.match(view.text(), /1개 선택/u);
  } finally { await view.cleanup(); }
});

test("범위 칩을 끄면 남은 범위로만 찾고, 모두 끄면 찾을 수 없다는 안내", async () => {
  const fake = fakeDiscovery();
  const view = await mountPanel({ studio: fake.studio });
  try {
    await view.click(scopeChip(view, "승인 지식"));
    await view.search("청구 절차");
    assert.deepEqual(fake.searches().at(-1)[2], ["documents"]);
    await view.click(scopeChip(view, "문서"));
    await view.type("청구 절차");
    assert.equal(view.button("찾기").disabled, true);
    assert.match(view.text(), /찾을 범위를 하나 이상 고르세요/u);
  } finally { await view.cleanup(); }
});

test("결과 없음: 찾은 자료가 없다는 안내만 보이고 추가 버튼은 없다", async () => {
  const fake = fakeDiscovery({ search: async () => ({ candidates: [], unavailable: [] }) });
  const view = await mountPanel({ studio: fake.studio });
  try {
    await view.search();
    assert.match(view.status(), /찾은 자료가 없습니다/u);
    assert.equal(view.byLabel("UL", "찾은 자료 목록"), undefined);
    assert.equal(view.button("선택한 자료 추가"), undefined);
  } finally { await view.cleanup(); }
});

test("범위 사용 불가: 연결 설정이 안 된 범위 칩은 흐려지고 이유가 보인다(다른 범위 결과는 그대로)", async () => {
  const fake = fakeDiscovery({ search: async () => ({ candidates: [pkg(1)], unavailable: [{ scope: "documents", reason: "CONNECTOR_NOT_CONFIGURED" }] }) });
  const view = await mountPanel({ studio: fake.studio });
  try {
    await view.search();
    const chip = scopeChip(view, "문서");
    assert.equal(chip.getAttribute("data-unavailable"), "true");
    assert.match(chip.getAttribute("class"), /is-unavailable/u);
    assert.equal(scopeChip(view, "승인 지식").getAttribute("data-unavailable"), null);
    assert.match(view.text(), /문서: 지식 연결이 설정되지 않았습니다/u);
    assert.ok(view.row("cand-k1"), "다른 범위 결과는 그대로");
    assert.doesNotMatch(view.text(), /나머지 결과만/u, "설정 문제는 결과 위 실패 안내가 아니라 칩 이유로 보인다");
  } finally { await view.cleanup(); }
  for (const [reason, text] of [["CONNECTOR_NOT_READY", "지식 연결이 아직 준비되지 않았습니다"], ["CONNECTOR_DISABLED", "지식 연결이 꺼져 있습니다"], ["TOOL_NOT_ALLOWED", "이 범위의 찾기 도구가 허용되지 않았습니다"]]) {
    const other = fakeDiscovery({ search: async () => ({ candidates: [], unavailable: [{ scope: "knowledge", reason }] }) });
    const v = await mountPanel({ studio: other.studio });
    try {
      await v.search();
      assert.equal(scopeChip(v, "승인 지식").getAttribute("data-unavailable"), "true", reason);
      assert.match(v.text(), new RegExp(`승인 지식: ${text}`, "u"), reason);
    } finally { await v.cleanup(); }
  }
});

test("요청한 범위를 모두 쓸 수 없으면(422) 두 칩 모두 흐려지고 안내 문구가 보인다", async () => {
  const fake = fakeDiscovery({ search: async () => { throw failure("DISCOVERY_SCOPE_UNAVAILABLE", 422); } });
  const view = await mountPanel({ studio: fake.studio });
  try {
    await view.search();
    assert.equal(scopeChip(view, "승인 지식").getAttribute("data-unavailable"), "true");
    assert.equal(scopeChip(view, "문서").getAttribute("data-unavailable"), "true");
    assert.match(view.text(), /고른 범위를 지금 쓸 수 없습니다/u);
    assert.equal(view.byLabel("UL", "찾은 자료 목록"), undefined);
  } finally { await view.cleanup(); }
});

test("일부 범위 실패: 연결 실패한 범위는 결과 위 한 줄로 알리고 나머지 결과를 보인다", async () => {
  const fake = fakeDiscovery({ search: async () => ({ candidates: [pkg(1), pkg(2)], unavailable: [{ scope: "documents", reason: "DISCOVERY_CONNECTOR_FAILED" }] }) });
  const view = await mountPanel({ studio: fake.studio });
  try {
    await view.search();
    const notice = view.find((node) => node.getAttribute("data-discovery-partial") !== null)[0];
    assert.ok(notice, "결과 위 안내가 있어야 한다");
    assert.match(notice.textContent, /문서 범위에서 찾지 못해 나머지 결과만 보여 드립니다/u);
    const list = view.byLabel("UL", "찾은 자료 목록");
    const siblings = notice.parentNode.childNodes;
    assert.ok(siblings.indexOf(notice) < siblings.indexOf(list), "안내는 결과 목록 위에 있다");
    assert.equal(scopeChip(view, "문서").getAttribute("data-unavailable"), null, "일시 실패는 칩을 흐리게 하지 않는다");
    assert.ok(view.row("cand-k2"));
  } finally { await view.cleanup(); }
});

test("찾기 오류 문구: 모두 실패(502)·찾기 사용 불가(503)·그 밖의 오류", async () => {
  for (const [error, text] of [
    [failure("DISCOVERY_CONNECTOR_FAILED", 502), /지식 연결이 응답하지 않아 자료를 찾지 못했습니다/u],
    [failure("DISCOVERY_UNAVAILABLE", 503), /자료 찾기를 지금 쓸 수 없습니다/u],
    [failure("STUDIO_REQUEST_FAILED", 500), /자료를 찾지 못했습니다\. 잠시 후 다시 시도해 주세요/u],
  ]) {
    const fake = fakeDiscovery({ search: async () => { throw error; } });
    const view = await mountPanel({ studio: fake.studio });
    try {
      await view.search();
      const alert = view.find((node) => node.getAttribute("role") === "alert")[0];
      assert.ok(alert, error.code);
      assert.match(alert.textContent, text);
      assert.doesNotMatch(alert.textContent, /DISCOVERY_|STUDIO_/u, "오류 코드 원문을 보이지 않는다");
      assert.equal(view.button("찾기").disabled, false, "다시 찾을 수 있다");
    } finally { await view.cleanup(); }
  }
});

test("추가 중 → 추가됨: 고른 것만 하나씩 추가하고(매번 새 요청), 끝나면 셸에 소스·범위 추가를 알린다", async () => {
  const gates = [deferred(), deferred()];
  let index = 0;
  const fake = fakeDiscovery({
    search: async () => ({ candidates: [pkg(1), doc(1), doc(2)], unavailable: [] }),
    add: async (ref) => { await gates[index++].promise; return ref.kind === "document" ? { added: "source", sourceId: "source-new-1" } : { added: "scope", sourceId: null }; },
  });
  const view = await mountPanel({ studio: fake.studio });
  try {
    await view.search();
    await view.click(view.check("보험 업무 패키지 1"));
    await view.click(view.check("약관 해설서 1.pdf"));
    await view.click(view.button("선택한 자료 추가"));
    assert.equal(fake.adds().length, 1, "한 번에 하나씩 보낸다");
    assert.deepEqual(fake.adds()[0][1], pkgRef(1));
    assert.match(view.row("cand-k1").textContent, /추가 중/u);
    assert.match(view.row("cand-d1").textContent, /추가 중/u);
    assert.doesNotMatch(view.row("cand-d2").textContent, /추가 중/u, "고르지 않은 후보는 그대로");
    assert.equal(view.button("선택한 자료 추가").disabled, true, "추가하는 동안 다시 누를 수 없다");
    await view.act(async () => { gates[0].resolve(); await flush(); });
    assert.match(view.row("cand-k1").textContent, /추가됨/u);
    assert.equal(fake.adds().length, 2);
    assert.deepEqual(fake.adds()[1][1], docRef(1));
    assert.deepEqual(view.added, [], "끝나기 전에는 알리지 않는다");
    await view.act(async () => { gates[1].resolve(); await flush(); });
    assert.match(view.row("cand-d1").textContent, /추가됨/u);
    assert.equal(view.check("보험 업무 패키지 1"), undefined, "추가된 후보는 다시 고를 수 없다");
    assert.equal(view.check("약관 해설서 1.pdf"), undefined);
    assert.ok(view.check("약관 해설서 2.pdf"));
    assert.match(view.row("cand-k1").textContent, /승인 지식 범위에 추가했습니다/u);
    assert.match(view.row("cand-d1").textContent, /소스 목록에 처리 중으로 추가했습니다/u);
    assert.deepEqual(view.added, [{ sourceIds: ["source-new-1"], scopeAdded: true }]);
    for (const call of fake.adds()) assert.equal(call[2]?.idempotencyKey, undefined, "Idempotency-Key는 어댑터가 매번 새로 만든다");
  } finally { await view.cleanup(); }
});

test("추가 실패: 문구는 후보 줄에 보이고 다음 후보는 계속 추가된다(크기 초과 문구에 숫자 없음)", async () => {
  const fake = fakeDiscovery({
    search: async () => ({ candidates: [doc(1), doc(2)], unavailable: [] }),
    add: async (ref) => { if (ref.document_id === "doc-1") throw failure("DISCOVERY_DOCUMENT_TOO_LARGE", 413); return { added: "source", sourceId: "source-new-2" }; },
  });
  const view = await mountPanel({ studio: fake.studio });
  try {
    await view.search();
    await view.click(view.check("약관 해설서 1.pdf"));
    await view.click(view.check("약관 해설서 2.pdf"));
    await view.click(view.button("선택한 자료 추가"));
    const failed = view.row("cand-d1").textContent;
    assert.match(failed, /문서가 너무 커서 소스로 추가할 수 없습니다/u);
    const message = view.find((node) => node.getAttribute("data-discovery-row-error") !== null)[0].textContent;
    assert.doesNotMatch(message, /\d/u, "상한은 NB4-F1b에서 바뀌므로 숫자를 박지 않는다");
    assert.match(view.row("cand-d2").textContent, /추가됨/u);
    assert.ok(view.check("약관 해설서 1.pdf"), "실패한 후보는 다시 고를 수 있다");
    assert.equal(view.check("약관 해설서 1.pdf").checked, false);
    assert.deepEqual(view.added, [{ sourceIds: ["source-new-2"], scopeAdded: false }]);
  } finally { await view.cleanup(); }
});

test("추가 오류 문구: 코드마다 안전한 문구, 원문 코드는 보이지 않는다", async () => {
  const cases = [
    [failure("DISCOVERY_REF_NOT_FOUND", 404), /자료를 더 이상 찾을 수 없습니다/u],
    [failure("DISCOVERY_SCOPE_LIMIT", 409), /승인 지식 범위가 가득 찼습니다/u],
    [failure("DISCOVERY_DOCUMENT_CHANGED", 409), /문서가 그사이 바뀌었습니다/u],
    [failure("DISCOVERY_DOCUMENT_EMPTY", 422), /문서에 추가할 내용이 없습니다/u],
    [failure("DISCOVERY_DOCUMENT_INVALID", 422), /문서를 텍스트로 읽을 수 없어/u],
    [failure("DISCOVERY_SCOPE_UNAVAILABLE", 422), /이 자료의 범위를 지금 쓸 수 없어/u],
    [failure("DISCOVERY_UNAVAILABLE", 503), /자료를 지금 추가할 수 없습니다/u],
    [failure("STUDIO_REQUEST_FAILED", 500), /추가하지 못했습니다\. 잠시 후 다시 시도해 주세요/u],
  ];
  for (const [error, text] of cases) {
    const fake = fakeDiscovery({ search: async () => ({ candidates: [pkg(1)], unavailable: [] }), add: async () => { throw error; } });
    const view = await mountPanel({ studio: fake.studio });
    try {
      await view.search();
      await view.click(view.check("보험 업무 패키지 1"));
      await view.click(view.button("선택한 자료 추가"));
      const line = view.row("cand-k1").textContent;
      assert.match(line, text, error.code);
      assert.doesNotMatch(line, /DISCOVERY_|STUDIO_/u);
      assert.deepEqual(view.added, [], "아무것도 추가되지 않으면 셸에 알리지 않는다");
    } finally { await view.cleanup(); }
  }
});

test("보기 권한: canEdit이 거짓이면 찾기는 되고 체크칸·추가 버튼은 숨기며 안내가 보인다", async () => {
  const fake = fakeDiscovery();
  const view = await mountPanel({ studio: fake.studio, canEdit: false });
  try {
    await view.search();
    assert.ok(view.row("cand-k1"));
    assert.equal(view.check("보험 업무 패키지 1"), undefined);
    assert.equal(view.button("선택한 자료 추가"), undefined);
    assert.match(view.text(), /보기 권한으로는 자료를 찾을 수만 있고 추가할 수 없습니다/u);
  } finally { await view.cleanup(); }
});

test("보기 권한: 추가가 403이면 남은 추가를 멈추고 체크칸·추가 버튼을 숨긴다", async () => {
  const fake = fakeDiscovery({ add: async () => { throw failure("FORBIDDEN", 403); } });
  const view = await mountPanel({ studio: fake.studio });
  try {
    await view.search();
    await view.click(view.check("보험 업무 패키지 1"));
    await view.click(view.check("약관 해설서 1.pdf"));
    await view.click(view.button("선택한 자료 추가"));
    assert.equal(fake.adds().length, 1, "403 뒤에는 더 보내지 않는다");
    assert.equal(view.button("선택한 자료 추가"), undefined);
    assert.equal(view.check("약관 해설서 1.pdf"), undefined);
    assert.match(view.text(), /보기 권한으로는 자료를 찾을 수만 있고 추가할 수 없습니다/u);
    assert.doesNotMatch(view.row("cand-d1").textContent, /추가 중/u, "멈춘 후보는 추가 중으로 남지 않는다");
    assert.deepEqual(view.added, []);
  } finally { await view.cleanup(); }
});

test("새로 찾으면 이전 결과·추가 표시를 버리고, 결과 닫기는 목록을 닫는다. 노트북이 바뀌면 처음 상태로", async () => {
  let round = 0;
  const fake = fakeDiscovery({ search: async () => (++round === 1 ? { candidates: [pkg(1)], unavailable: [{ scope: "documents", reason: "CONNECTOR_NOT_READY" }] } : { candidates: [doc(3)], unavailable: [] }) });
  const view = await mountPanel({ studio: fake.studio });
  try {
    await view.search("처음");
    await view.click(view.check("보험 업무 패키지 1"));
    await view.click(view.button("선택한 자료 추가"));
    assert.match(view.row("cand-k1").textContent, /추가됨/u);
    await view.search("다시");
    assert.equal(view.row("cand-k1"), undefined);
    assert.ok(view.row("cand-d3"));
    assert.equal(scopeChip(view, "문서").getAttribute("data-unavailable"), null, "새 결과에 없으면 칩 흐림도 풀린다");
    await view.click(view.button("결과 닫기"));
    assert.equal(view.byLabel("UL", "찾은 자료 목록"), undefined);
    await view.search("셋째");
    assert.ok(view.byLabel("UL", "찾은 자료 목록"));
    await view.render({ notebookId: "notebook-2" });
    assert.equal(view.byLabel("UL", "찾은 자료 목록"), undefined);
    assert.equal(view.byLabel("INPUT", "찾을 자료").value, "");
  } finally { await view.cleanup(); }
});

test("늦게 온 이전 검색 응답은 버린다", async () => {
  const first = deferred();
  let round = 0;
  const fake = fakeDiscovery({ search: async () => (++round === 1 ? first.promise : { candidates: [doc(9)], unavailable: [] }) });
  const view = await mountPanel({ studio: fake.studio });
  try {
    await view.search("하나");
    await view.render({ notebookId: "notebook-2" });
    await view.search("둘");
    assert.ok(view.row("cand-d9"));
    await view.act(async () => { first.resolve({ candidates: [pkg(7)], unavailable: [] }); await flush(); });
    assert.equal(view.row("cand-k7"), undefined);
    assert.ok(view.row("cand-d9"));
  } finally { await view.cleanup(); }
});

test("문구는 메시지 파일에서만 온다: 컴포넌트 코드(주석 제외)에 한글 문자열이 없다", async () => {
  const sourceCode = await readFile(path.join(root, "packages/ui/src/source-discovery.jsx"), "utf8");
  const code = sourceCode.replace(/\/\*[\s\S]*?\*\//gu, "").replace(/(^|[^:])\/\/.*$/gmu, "$1");
  assert.doesNotMatch(code, /[\uac00-\ud7a3]/u);
  const { NOTEBOOK_MESSAGES } = await import(`${pathToFileURL(path.join(root, "packages/ui/src/notebook-messages.ko.js")).href}?v=${Date.now()}`);
  const keys = Object.keys(NOTEBOOK_MESSAGES).filter((key) => key.startsWith("notebook.source_discovery."));
  assert.ok(keys.length >= 30, `빠른 찾기 문구 키: ${keys.length}`);
  for (const key of keys) assert.doesNotMatch(NOTEBOOK_MESSAGES[key], /KiB|MiB|\d+\s*(KB|MB)/u, `${key}에 크기 상한 숫자를 박지 않는다`);
  const used = [...sourceCode.matchAll(/"(notebook\.source_discovery\.[a-z_.A-Z]+)"/gu)].map((m) => m[1]);
  for (const key of used) assert.ok(Object.hasOwn(NOTEBOOK_MESSAGES, key), `${key} 키가 있어야 한다`);
});

// ---- 셸 연결: 소스 칸 위쪽에 놓이고, 추가 뒤 소스 목록·승인 지식 칸을 다시 읽는다 ----
const baseAdapter = Object.freeze({ listSources() {}, uploadPdf() {}, getProcessingStatus() {}, askQuestion() {}, citationUrl() {}, createReport() {}, listStudioOutputs() {} });
const apiSource = (id, state = "ready") => ({ source_id: id, source_version_id: `version-${id}`, filename: `${id}.txt`, source_state: state,
  processing_state: state === "ready" ? "completed" : "running", job_state: state === "ready" ? "completed" : "running" });
function shellAdapter({ calls, withScopes = true }) {
  let sources = [apiSource("source-a")];
  let scopes = [];
  const fake = fakeDiscovery({
    search: async () => ({ candidates: [pkg(1), doc(1)], unavailable: [] }),
    add: async (ref) => {
      if (ref.kind === "document") { sources = [...sources, apiSource("source-new-1", "processing")]; return { added: "source", sourceId: "source-new-1" }; }
      scopes = [...scopes, { project_id: "project-1", work_package_id: "wp-1", project_name: "보험", work_package_name: "보험 업무 패키지 1" }];
      return { added: "scope", sourceId: null };
    },
  });
  const studioV2 = { listTypes: async () => [], listOutputs: async () => ({ items: [], nextCursor: null }), ...fake.studio };
  const adapter = { ...baseAdapter, notebookContext: { notebook_id: "notebook-d", sources: [] },
    listSources: async () => { calls.push("listSources"); return sources; }, listConnectors: async () => [], listStudioOutputs: async () => [],
    listKnowledgePackages: async () => [], askQuestion: async () => ({ run_id: "r", run_result_id: "rr", answer: "응답", insufficient: false, citations: [] }), studioV2 };
  if (withScopes) {
    adapter.getNotebookKnowledgeScopes = async () => { calls.push("getNotebookKnowledgeScopes"); return { items: scopes }; };
    adapter.listDaonKnowledgeScopes = async () => ({ projects: [] });
  }
  return { adapter, fake };
}
async function mountShell(adapter) {
  const { ProductWorkspaceShell } = await bundle("source-discovery-shell", "packages/ui/src/product-workspace-shell.jsx");
  const dom = installMinimalDom();
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(ProductWorkspaceShell, { workspaceId: "workspace-1", adapter, memoSourcePollMs: 60000 })); await flush(); });
  await act(async () => { await flush(); });
  const find = (predicate) => findElements(container, predicate);
  const byLabel = (tag, label) => find((node) => node.tagName === tag && node.getAttribute("aria-label") === label)[0];
  const click = async (node) => { assert.ok(node); await act(async () => { node.dispatchEvent(new MinimalEvent("click")); await flush(); }); await act(async () => { await flush(); }); };
  const search = async (text) => {
    const input = byLabel("INPUT", "찾을 자료");
    input.value = text;
    await act(async () => { props(input).onChange({ target: input, currentTarget: input }); });
    const form = find((node) => node.tagName === "FORM" && node.getAttribute("aria-label") === "자료 찾기 검색")[0];
    await act(async () => { void props(form).onSubmit({ preventDefault() {} }); await flush(); });
  };
  return { container, find, byLabel, click, search, cleanup: async () => { await act(async () => reactRoot.unmount()); dom.restore(); } };
}

test("셸: 빠른 찾기는 소스 칸 안 Raw Source 목록보다 위에 있고, 기존 소스 줄·조작은 그대로다", async () => {
  const calls = [];
  const { adapter } = shellAdapter({ calls });
  const view = await mountShell(adapter);
  try {
    const pane = view.find((node) => node.getAttribute("id") === "product-pane-sources")[0];
    const panel = findElements(pane, (node) => node.getAttribute("aria-label") === "자료 찾기")[0];
    assert.ok(panel, "소스 칸 안에 빠른 찾기가 있다");
    const order = findElements(pane, (node) => node === panel || node.getAttribute("aria-labelledby") === "raw-source-title");
    assert.equal(order[0], panel, "Raw Source 목록보다 위");
    assert.ok(view.byLabel("INPUT", "source-a.txt 사용"), "기존 소스 줄 체크칸 그대로");
    assert.ok(view.byLabel("BUTTON", "source-a.txt 작업"), "기존 소스 줄 작업 메뉴 그대로");
  } finally { await view.cleanup(); }
});

test("셸: 문서를 추가하면 소스 목록을 다시 읽어 새 소스가 처리 중으로 보이고, 패키지를 추가하면 승인 지식 칸을 다시 읽는다", async () => {
  const calls = [];
  const { adapter, fake } = shellAdapter({ calls });
  const view = await mountShell(adapter);
  try {
    await view.search("보험");
    const listBefore = calls.filter((c) => c === "listSources").length;
    const scopesBefore = calls.filter((c) => c === "getNotebookKnowledgeScopes").length;
    await view.click(view.byLabel("INPUT", "약관 해설서 1.pdf 선택"));
    await view.click(view.byLabel("INPUT", "보험 업무 패키지 1 선택"));
    await view.click(findElements(view.container, (node) => node.tagName === "BUTTON" && node.textContent.trim() === "선택한 자료 추가")[0]);
    assert.equal(fake.adds().length, 2);
    assert.ok(calls.filter((c) => c === "listSources").length > listBefore, "소스 목록을 다시 읽는다");
    assert.ok(calls.filter((c) => c === "getNotebookKnowledgeScopes").length > scopesBefore, "승인 지식 칸을 다시 읽는다");
    const newRow = view.find((node) => node.tagName === "LI" && node.getAttribute("data-source-id") === "source-new-1")[0];
    assert.ok(newRow, "새 소스 줄이 목록에 나타난다");
    assert.match(newRow.textContent, /처리 중/u);
    assert.match(view.container.textContent, /보험 업무 패키지 1/u, "승인 지식 칸에 추가한 패키지가 보인다");
  } finally { await view.cleanup(); }
});

test("셸: 승인 지식 범위 조회가 없는(이전 방식) 어댑터에서도 패키지 추가 뒤 목록을 다시 읽는다", async () => {
  const calls = [];
  const { adapter } = shellAdapter({ calls, withScopes: false });
  const view = await mountShell(adapter);
  try {
    await view.search("보험");
    const before = calls.filter((c) => c === "listSources").length;
    await view.click(view.byLabel("INPUT", "보험 업무 패키지 1 선택"));
    await view.click(findElements(view.container, (node) => node.tagName === "BUTTON" && node.textContent.trim() === "선택한 자료 추가")[0]);
    assert.ok(calls.filter((c) => c === "listSources").length > before);
  } finally { await view.cleanup(); }
});

// ---- 실제 브라우저 배치: 결과 목록은 목록 창 안에서만 스크롤, 페이지 전체는 늘어나지 않는다 ----
const browserCandidates = process.platform === "win32"
  ? ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"]
  : ["/usr/bin/chromium", "/usr/bin/google-chrome"];
const browser = browserCandidates.find(existsSync);

async function withBrowserPage(fileUrl, sizes, measure) {
  const profile = mkdtempSync(path.join(tmpdir(), "daon-discovery-browser-"));
  const child = spawn(browser, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--allow-file-access-from-files",
    "--remote-debugging-port=0", `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore", windowsHide: true });
  let socket;
  let send;
  try {
    let port;
    for (let attempt = 0; attempt < 50 && !port; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 200));
      try { port = Number(readFileSync(path.join(profile, "DevToolsActivePort"), "utf8").split(/\r?\n/u)[0]); } catch { /* 아직 시작 중 */ }
    }
    assert.ok(port, "격리 브라우저의 CDP 포트가 열려야 합니다");
    const target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((entry) => entry.type === "page");
    socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
    let sequence = 0;
    const pending = new Map();
    socket.addEventListener("message", ({ data }) => {
      const message = JSON.parse(data);
      const request = pending.get(message.id);
      if (!request) return;
      pending.delete(message.id);
      if (message.error) request.reject(new Error(JSON.stringify(message.error))); else request.resolve(message.result);
    });
    send = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP 시간 초과: ${method}`)); }, 15_000);
      timer.unref();
      pending.set(id, { resolve: (v) => { clearTimeout(timer); resolve(v); }, reject: (e) => { clearTimeout(timer); reject(e); } });
      socket.send(JSON.stringify({ id, method, params }));
    });
    await send("Page.enable");
    await send("Runtime.enable");
    const results = [];
    for (const [width, height] of sizes) {
      await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 600 });
      await send("Page.navigate", { url: fileUrl });
      let value = "";
      for (let attempt = 0; attempt < 100 && !value; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        value = (await send("Runtime.evaluate", { expression: "document.querySelector('#result')?.textContent || ''", returnByValue: true })).result.value;
      }
      assert.ok(value, `${width}×${height}: 브라우저가 배치 크기를 출력해야 합니다`);
      results.push({ width, height, ...JSON.parse(value) });
    }
    return measure(results);
  } finally {
    if (send) await Promise.race([send("Browser.close").catch(() => {}), new Promise((resolve) => setTimeout(resolve, 1000))]);
    socket?.close();
    child.kill();
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      try { rmSync(profile, { recursive: true, force: true, maxRetries: 2, retryDelay: 100 }); break; } catch (error) { if (attempt === 19) throw error; }
    }
  }
}

test("실제 브라우저: 후보 20개 결과 목록은 목록 안에서 스크롤되고, 찾기 전후 노트북 페이지·소스 칸 높이는 그대로다(넓은 화면 셋·좁은 화면 하나)", { skip: !browser, timeout: 180_000 }, async () => {
  const work = await mkdtemp(path.join(root, ".source-discovery-layout-"));
  try {
    // 실제 셸을 가짜 어댑터로 띄우는 진입 파일. react까지 한 파일(iife)로 묶어 file://에서 바로 연다.
    const entry = path.join(work, "entry.jsx");
    const shellPath = path.join(root, "packages/ui/src/product-workspace-shell.jsx").replaceAll("\\", "/");
    const tokensPath = path.join(root, "packages/design-tokens/tokens.css").replaceAll("\\", "/");
    const globalsPath = path.join(root, "apps/web/app/globals.css").replaceAll("\\", "/");
    writeFileSync(entry, `
import { createElement as h } from "react";
import { createRoot } from "react-dom/client";
import { ProductWorkspaceShell } from "${shellPath}";
import "${tokensPath}";
import "${globalsPath}";
const candidates = Array.from({ length: 20 }, (_, i) => ({ candidate_id: "cand-" + i, kind: i % 2 ? "document" : "knowledge_package",
  title: "후보 자료 " + (i + 1) + " — 보험 약관과 청구 절차를 설명하는 긴 제목", origin_label: i % 2 ? "Daon2-RAG 문서" : "Daon2 승인 지식",
  reason: "검색어와 제목·본문이 맞습니다", preview: "미리보기 ".repeat(30), action: i % 2 ? "add_source" : "add_scope",
  ref: i % 2 ? { kind: "document", project_id: "p", work_package_id: "w", document_id: "d" + i, document_version: "v1" } : { kind: "knowledge_package", project_id: "p", work_package_id: "w" + i } }));
const sources = Array.from({ length: 3 }, (_, i) => ({ source_id: "s" + i, source_version_id: "v" + i, filename: "소스 " + i + ".txt", source_state: "ready", processing_state: "completed", job_state: "completed" }));
const studioV2 = { listTypes: async () => [], listOutputs: async () => ({ items: [], nextCursor: null }),
  searchSourceDiscovery: async () => ({ candidates, unavailable: [] }), addSourceDiscovery: async () => ({ added: "scope", sourceId: null }) };
const adapter = { listSources: async () => sources, uploadPdf() {}, getProcessingStatus() {}, askQuestion: async () => ({}), citationUrl: () => null, createReport() {},
  listStudioOutputs: async () => [], listConnectors: async () => [], listKnowledgePackages: async () => [], notebookContext: { notebook_id: "notebook-layout", sources: [] }, studioV2 };
const rootNode = document.getElementById("root");
createRoot(rootNode).render(h(ProductWorkspaceShell, { workspaceId: "workspace-1", notebookTitle: "배치 시험", adapter }));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const measure = () => {
  const pane = document.getElementById("product-pane-sources");
  const list = document.querySelector('[aria-label="찾은 자료 목록"]');
  return { pageHeight: document.documentElement.scrollHeight, pageWidth: document.documentElement.scrollWidth, viewportHeight: innerHeight, viewportWidth: innerWidth,
    paneHeight: pane ? pane.getBoundingClientRect().height : -1,
    listHeight: list ? list.clientHeight : -1, listContentHeight: list ? list.scrollHeight : -1, listScrollTop: list ? list.scrollTop : -1,
    listBottom: list ? list.getBoundingClientRect().bottom : -1, paneBottom: pane ? pane.getBoundingClientRect().bottom : -1 };
};
(async () => {
  for (let i = 0; i < 100 && !document.querySelector('[aria-label="찾을 자료"]'); i += 1) await wait(50);
  if (innerWidth < 821) document.querySelector('[aria-controls="product-pane-sources"]')?.click();
  await wait(200);
  const before = measure();
  const input = document.querySelector('[aria-label="찾을 자료"]');
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, "보험 약관");
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await wait(50);
  input.form.requestSubmit();
  for (let i = 0; i < 100 && !document.querySelector('[aria-label="찾은 자료 목록"]'); i += 1) await wait(50);
  await wait(200);
  const list = document.querySelector('[aria-label="찾은 자료 목록"]');
  if (list) { list.scrollIntoView({ block: "nearest" }); list.scrollTop = 200; }
  await wait(50);
  document.getElementById("result").textContent = JSON.stringify({ before, after: measure() });
})();
`);
    const { build } = await import("vite");
    const out = path.join(work, "out");
    await build({ configFile: false, logLevel: "silent", root, define: { "process.env.NODE_ENV": JSON.stringify("production") },
      build: { outDir: out, emptyOutDir: true, cssCodeSplit: false, lib: { entry, formats: ["iife"], name: "DiscoveryLayout", fileName: () => "app.js", cssFileName: "app" } } });
    const cssFile = (await readdir(out)).find((item) => item.endsWith(".css"));
    assert.ok(cssFile, "묶은 CSS가 있어야 한다");
    writeFileSync(path.join(out, "index.html"), `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="./${cssFile}"><style>html,body{margin:0}</style></head><body><div id="root"></div><output id="result" hidden></output><script src="./app.js"></script></body></html>`);
    await withBrowserPage(pathToFileURL(path.join(out, "index.html")).href, [[1920, 1080], [1440, 900], [1280, 720], [430, 844]], (results) => {
      for (const r of results) {
        const label = `${r.width}×${r.height} ${JSON.stringify(r)}`;
        assert.ok(r.after.listHeight > 0, `${label}: 결과 목록이 보여야 한다`);
        assert.ok(r.after.listContentHeight > r.after.listHeight, `${label}: 긴 결과 목록은 목록 안에 넘쳐야 한다`);
        assert.ok(r.after.listScrollTop > 0, `${label}: 결과 목록 자체가 스크롤되어야 한다`);
        assert.ok(r.after.listHeight <= r.after.viewportHeight * 0.6, `${label}: 결과 목록 창은 화면의 일부만 차지한다`);
        assert.ok(r.after.pageWidth <= r.after.viewportWidth, `${label}: 가로 스크롤이 생기지 않는다`);
        if (r.width >= 821) {
          // 세 창(소스·대화·스튜디오) 배치: 페이지 전체 스크롤이 없고, 찾은 뒤에도 페이지·소스 칸 높이가 그대로다.
          assert.equal(r.after.pageHeight, r.before.pageHeight, `${label}: 찾은 뒤에도 페이지 전체 높이가 그대로여야 한다`);
          assert.ok(r.after.pageHeight <= r.after.viewportHeight, `${label}: 넓은 화면에서 페이지 전체 스크롤이 없다`);
          assert.equal(Math.round(r.after.paneHeight), Math.round(r.before.paneHeight), `${label}: 소스 칸 높이가 그대로여야 한다`);
          assert.ok(r.after.listBottom <= r.after.paneBottom, `${label}: 결과 목록 창은 소스 칸 안에 있다`);
        } else {
          // 좁은 화면(820px 이하)은 기존 셸이 한 창씩 세로로 쌓는 배치라 찾기 전부터 페이지가 길다(이번 단위에서 바꾸지 않음).
          // 결과가 아무리 많아도 늘어나는 높이는 결과 목록 창 하나 크기(+안내·버튼 줄)를 넘지 않는다.
          assert.ok(r.after.pageHeight - r.before.pageHeight <= r.after.listHeight + 120, `${label}: 결과 수만큼 페이지가 늘어나지 않는다`);
        }
      }
    });
  } finally { await rm(work, { recursive: true, force: true }); }
});
