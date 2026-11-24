// NB3-U2 소스 묶음 화면(WO-N1 N1-5, 결정 D-11 노트북 공유, 정정 C-4 상한 8개).
// 조작: 묶음 만들기·접기/펴기·묶음 체크칸(전체·일부·없음)·소스 줄 "묶음으로 이동"(묶음 목록·묶음 밖으로)·이름 바꾸기·삭제.
// 상태: 빈 묶음 안내 / 8개 초과 안내는 기존 그대로 / 저장 실패는 되돌리고 알림 / 412는 다시 조회 / 보기 권한이면 변경 메뉴 숨김.
// 이동: 묶음 밖 소스는 "묶음 없음" 아래. 접힘 상태는 노트북별 브라우저 저장(저장소를 못 써도 동작).
// 질문 범위는 바뀌지 않는다: 묶음 체크 = 안의 소스를 하나씩 체크한 것(셸 시험으로 askQuestion 입력을 비교한다).
import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
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

const gid = (c) => `sg-${c.repeat(32)}`;
const G1 = gid("a");
const G2 = gid("b");
const G3 = gid("c");
const failure = (code, status) => Object.assign(new Error(code), { code, status });
const deferred = () => { let resolve; let reject; const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; }); return { promise, resolve, reject }; };
const flush = () => new Promise((resolve) => setTimeout(resolve, 5));
const clone = (value) => JSON.parse(JSON.stringify(value));
const props = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];

// 서버처럼 동작하는 가짜 묶음 어댑터: 변경마다 ETag가 바뀌고, 다른 ETag면 412, 구성원 저장은 다른 묶음에서 옮겨 온다.
function fakeGroups(initial, { fail = () => null } = {}) {
  let groups = clone(initial);
  let version = 1;
  const calls = [];
  const etag = () => `"source-groups:${version}"`;
  const sorted = () => clone([...groups].sort((a, b) => a.position - b.position).map((g, index) => ({ ...g, position: index })));
  const guard = async (op, given) => {
    const injected = fail(op, calls.length);
    if (injected instanceof Promise) await injected;
    else if (injected) throw injected;
    if (given !== etag()) throw failure("SOURCE_GROUP_ETAG_MISMATCH", 412);
  };
  const studio = {
    listSourceGroups: async () => { calls.push(["list"]); return { groups: sorted(), etag: etag() }; },
    createSourceGroup: async (name) => {
      calls.push(["create", name]);
      const injected = fail("create", calls.length);
      if (injected instanceof Promise) await injected; else if (injected) throw injected;
      const groupId = gid(String.fromCharCode(100 + groups.length));
      groups.push({ group_id: groupId, name, position: groups.length, source_ids: [] });
      version += 1;
      return { groupId, etag: etag(), replayed: false };
    },
    updateSourceGroup: async (groupId, { name, position, etag: given }) => {
      calls.push(["update", groupId, { name, position }, given]);
      await guard("update", given);
      const target = groups.find((g) => g.group_id === groupId);
      if (name !== undefined) target.name = name;
      if (position !== undefined) target.position = position;
      version += 1;
      return { groups: sorted(), etag: etag() };
    },
    deleteSourceGroup: async (groupId, { etag: given }) => {
      calls.push(["delete", groupId, given]);
      await guard("delete", given);
      groups = groups.filter((g) => g.group_id !== groupId);
      version += 1;
      return { groups: sorted(), etag: etag() };
    },
    setSourceGroupMembers: async (groupId, sourceIds, { etag: given }) => {
      calls.push(["members", groupId, [...sourceIds], given]);
      await guard("members", given);
      for (const g of groups) g.source_ids = g.source_ids.filter((id) => !sourceIds.includes(id));
      groups.find((g) => g.group_id === groupId).source_ids = [...sourceIds];
      version += 1;
      return { groups: sorted(), etag: etag() };
    },
  };
  return { studio, calls, current: () => sorted(), external: (mutate) => { mutate(groups); version += 1; } };
}

const uiSource = (n, over = {}) => ({ sourceId: `source-m${n}`, sourceVersionId: `version-m${n}`, filename: `m${n}.pdf`, ready: true, ...over });
const UI_SOURCES = [1, 2, 3, 4, 5].map((n) => uiSource(n));
const TWO_GROUPS = [
  { group_id: G1, name: "약관", position: 0, source_ids: ["source-m4", "source-m2"] },
  { group_id: G2, name: "청구", position: 1, source_ids: [] },
];

function memoryStorage(initial = {}) {
  const store = new Map(Object.entries(initial));
  return { store, getItem: (key) => store.get(key) ?? null, setItem: (key, value) => { store.set(key, String(value)); }, removeItem: (key) => { store.delete(key); } };
}
const brokenStorage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };

// 컴포넌트 단독 장착: 셸과 같은 방식으로 체크 상태(해제한 소스 버전 집합)를 위에서 관리한다.
async function mountGroups(options) {
  const { SourceGroupsList } = await bundle("source-groups", "packages/ui/src/source-groups.jsx");
  const dom = installMinimalDom();
  const { createElement, act, useState } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  const state = { unchecked: new Set() };
  function Harness(p) {
    const [unchecked, setUnchecked] = useState(() => new Set());
    state.unchecked = unchecked;
    state.setUnchecked = setUnchecked;
    return createElement(SourceGroupsList, {
      studio: p.studio, notebookId: p.notebookId ?? "notebook-1", sources: p.sources ?? UI_SOURCES, refreshKey: p.refreshKey ?? null,
      storage: p.storage, canEdit: p.canEdit,
      isChecked: (source) => source.ready && !unchecked.has(source.sourceVersionId),
      onSetChecked: (items, checked) => setUnchecked((current) => {
        const next = new Set(current);
        for (const item of items) { if (!item.ready) continue; if (checked) next.delete(item.sourceVersionId); else next.add(item.sourceVersionId); }
        return next;
      }),
      renderRow: (source, control) => createElement("li", { key: source.sourceId, className: "source-list-row", "data-source-id": source.sourceId },
        createElement("input", { type: "checkbox", "aria-label": `${source.filename} 사용`, checked: source.ready && !unchecked.has(source.sourceVersionId), disabled: !source.ready,
          onChange: () => setUnchecked((current) => { const next = new Set(current); if (next.has(source.sourceVersionId)) next.delete(source.sourceVersionId); else next.add(source.sourceVersionId); return next; }) }),
        createElement("span", null, source.filename), control),
    });
  }
  let currentProps = options;
  const render = async (next = {}) => { currentProps = { ...currentProps, ...next }; await act(async () => { reactRoot.render(createElement(Harness, currentProps)); await flush(); }); };
  await render();
  const find = (predicate) => findElements(container, predicate);
  const byLabel = (tag, label) => find((node) => node.tagName === tag && node.getAttribute("aria-label") === label)[0];
  const button = (text) => find((node) => node.tagName === "BUTTON" && node.textContent.trim() === text)[0];
  const menuItem = (text) => find((node) => node.getAttribute("role") === "menuitem" && node.textContent.trim() === text)[0];
  const click = async (node) => { assert.ok(node, "누를 대상이 있어야 한다"); await act(async () => { node.dispatchEvent(new MinimalEvent("click")); await flush(); }); };
  const type = async (node, text) => { node.value = text; await act(async () => { props(node).onChange({ target: node, currentTarget: node }); }); };
  // 목록별 소스 이름(화면 순서)
  const listed = (label) => {
    const list = byLabel("UL", label);
    return list ? findElements(list, (node) => node.tagName === "LI").map((li) => li.getAttribute("data-source-id")) : null;
  };
  return { container, act, render, find, byLabel, button, menuItem, click, type, listed, state,
    text: () => container.textContent,
    cleanup: async () => { await act(async () => reactRoot.unmount()); dom.restore(); } };
}

const groupCheck = (view, name) => view.byLabel("INPUT", `${name} 묶음 사용`);

test("묶음 기능이 없는 어댑터는 기존 평면 목록 그대로이고 묶음 만들기 버튼도 없다", async () => {
  const view = await mountGroups({ studio: { listOutputs: async () => ({ items: [] }) } });
  try {
    assert.deepEqual(view.listed("Raw Source 목록"), UI_SOURCES.map((s) => s.sourceId));
    assert.equal(view.button("묶음 만들기"), undefined);
    assert.doesNotMatch(view.text(), /묶음 없음/u);
  } finally { await view.cleanup(); }
});

test("묶음이 없으면 평면 목록 위에 '묶음 만들기'만 보이고, 묶음이 있으면 순서대로 묶음 → '묶음 없음' 아래 나머지 소스", async () => {
  const none = fakeGroups([]);
  let view = await mountGroups({ studio: none.studio });
  try {
    assert.deepEqual(view.listed("Raw Source 목록"), UI_SOURCES.map((s) => s.sourceId));
    assert.ok(view.button("묶음 만들기"));
    assert.doesNotMatch(view.text(), /묶음 없음/u);
  } finally { await view.cleanup(); }
  const fake = fakeGroups([TWO_GROUPS[1], TWO_GROUPS[0]].map((g, i) => ({ ...g, position: i === 0 ? 1 : 0 })));
  view = await mountGroups({ studio: fake.studio });
  try {
    const headers = view.find((node) => node.getAttribute("data-source-group-id")).map((node) => node.getAttribute("data-source-group-id"));
    assert.deepEqual(headers, [G1, G2], "position 순서");
    assert.deepEqual(view.listed("약관 묶음 소스"), ["source-m4", "source-m2"], "묶음 안은 저장된 순서");
    assert.equal(view.listed("청구 묶음 소스"), null, "빈 묶음은 목록 대신 안내");
    assert.match(view.text(), /소스를 이 묶음으로 옮기세요/u);
    assert.match(view.text(), /묶음 없음/u);
    assert.deepEqual(view.listed("Raw Source 목록"), ["source-m1", "source-m3", "source-m5"]);
  } finally { await view.cleanup(); }
});

test("묶음 체크칸은 전체·일부·없음 세 상태이고, 누르면 안의 소스 전체를 체크·해제한다(일부면 전체 체크)", async () => {
  const fake = fakeGroups(TWO_GROUPS);
  const view = await mountGroups({ studio: fake.studio });
  try {
    const box = () => groupCheck(view, "약관");
    assert.equal(box().getAttribute("aria-checked"), "true");
    assert.equal(box().checked, true);
    await view.click(view.byLabel("INPUT", "m2.pdf 사용"));
    assert.equal(box().getAttribute("aria-checked"), "mixed");
    assert.equal(box().indeterminate, true);
    assert.equal(box().checked, false);
    await view.click(view.byLabel("INPUT", "m4.pdf 사용"));
    assert.equal(box().getAttribute("aria-checked"), "false");
    assert.equal(box().indeterminate, false);
    await view.click(box());
    assert.equal(box().getAttribute("aria-checked"), "true");
    assert.deepEqual([...view.state.unchecked], []);
    await view.click(box());
    assert.equal(box().getAttribute("aria-checked"), "false");
    assert.deepEqual([...view.state.unchecked].sort(), ["version-m2", "version-m4"], "묶음 해제 = 안의 소스를 하나씩 해제한 것");
    await view.click(view.byLabel("INPUT", "m2.pdf 사용"));
    assert.equal(box().getAttribute("aria-checked"), "mixed");
    await view.click(box());
    assert.equal(box().getAttribute("aria-checked"), "true", "일부 상태에서 누르면 전체 체크");
    assert.equal(groupCheck(view, "청구").disabled, true, "빈 묶음 체크칸은 쓸 수 없다");
  } finally { await view.cleanup(); }
});

test("묶음 체크는 준비 안 된 소스를 건드리지 않고, 준비된 소스만으로 상태를 정한다", async () => {
  const sources = [uiSource(1), uiSource(2, { ready: false }), uiSource(3), uiSource(4)];
  const fake = fakeGroups([{ group_id: G1, name: "약관", position: 0, source_ids: ["source-m2", "source-m4"] }]);
  const view = await mountGroups({ studio: fake.studio, sources });
  try {
    assert.equal(groupCheck(view, "약관").getAttribute("aria-checked"), "true");
    await view.click(groupCheck(view, "약관"));
    assert.deepEqual([...view.state.unchecked], ["version-m4"]);
    assert.equal(groupCheck(view, "약관").getAttribute("aria-checked"), "false");
  } finally { await view.cleanup(); }
});

test("접기/펴기는 노트북별로 브라우저에 저장되고, 저장소를 못 써도 동작한다", async () => {
  const fake = fakeGroups(TWO_GROUPS);
  const storage = memoryStorage();
  let view = await mountGroups({ studio: fake.studio, storage });
  try {
    const toggle = () => view.byLabel("BUTTON", "약관 묶음 접기") ?? view.byLabel("BUTTON", "약관 묶음 펴기");
    assert.equal(toggle().getAttribute("aria-expanded"), "true");
    await view.click(toggle());
    assert.equal(toggle().getAttribute("aria-label"), "약관 묶음 펴기");
    assert.equal(toggle().getAttribute("aria-expanded"), "false");
    assert.equal(view.listed("약관 묶음 소스"), null, "접으면 안의 소스를 숨긴다");
    assert.deepEqual(JSON.parse(storage.store.get("daon.source-groups.collapsed.notebook-1")), [G1]);
    await view.render({ notebookId: "notebook-2" });
    assert.ok(view.byLabel("BUTTON", "약관 묶음 접기"), "다른 노트북은 따로 기억한다");
  } finally { await view.cleanup(); }
  view = await mountGroups({ studio: fake.studio, storage });
  try {
    assert.ok(view.byLabel("BUTTON", "약관 묶음 펴기"), "다시 열어도 접힌 상태");
    await view.click(view.byLabel("BUTTON", "약관 묶음 펴기"));
    assert.equal(storage.store.has("daon.source-groups.collapsed.notebook-1"), false);
  } finally { await view.cleanup(); }
  view = await mountGroups({ studio: fake.studio, storage: brokenStorage });
  try {
    await view.click(view.byLabel("BUTTON", "약관 묶음 접기"));
    assert.ok(view.byLabel("BUTTON", "약관 묶음 펴기"), "저장소가 막혀도 이번 화면에서는 접힌다");
  } finally { await view.cleanup(); }
});

test("소스 줄 '묶음으로 이동': 대상 묶음에 PUT 한 번(다른 묶음에서 옮겨 옴), '묶음 밖으로'는 원래 묶음에서 뺀 목록으로 PUT", async () => {
  const fake = fakeGroups(TWO_GROUPS);
  const view = await mountGroups({ studio: fake.studio });
  try {
    await view.click(view.byLabel("BUTTON", "m3.pdf 묶음으로 이동"));
    assert.equal(view.menuItem("묶음 밖으로"), undefined, "묶음 밖 소스에는 '묶음 밖으로'가 없다");
    await view.click(view.menuItem("약관"));
    assert.deepEqual(fake.calls.at(-1), ["members", G1, ["source-m4", "source-m2", "source-m3"], '"source-groups:1"']);
    assert.deepEqual(view.listed("약관 묶음 소스"), ["source-m4", "source-m2", "source-m3"]);
    assert.deepEqual(view.listed("Raw Source 목록"), ["source-m1", "source-m5"]);

    await view.click(view.byLabel("BUTTON", "m2.pdf 묶음으로 이동"));
    assert.equal(view.menuItem("약관"), undefined, "지금 묶음은 목록에 없다");
    await view.click(view.menuItem("청구"));
    assert.deepEqual(fake.calls.at(-1), ["members", G2, ["source-m2"], '"source-groups:2"'], "대상 묶음 PUT 한 번, 새 ETag");
    assert.equal(fake.calls.filter((c) => c[0] === "members").length, 2);
    assert.deepEqual(view.listed("약관 묶음 소스"), ["source-m4", "source-m3"]);
    assert.deepEqual(view.listed("청구 묶음 소스"), ["source-m2"]);

    await view.click(view.byLabel("BUTTON", "m4.pdf 묶음으로 이동"));
    await view.click(view.menuItem("묶음 밖으로"));
    assert.deepEqual(fake.calls.at(-1), ["members", G1, ["source-m3"], '"source-groups:3"']);
    assert.deepEqual(view.listed("Raw Source 목록"), ["source-m1", "source-m4", "source-m5"], "묶음 밖 소스는 원래 순서");
  } finally { await view.cleanup(); }
});

test("저장 실패는 화면을 되돌리고 알린다(이동 중에는 먼저 옮겨 보인다)", async () => {
  const gate = deferred();
  const fake = fakeGroups(TWO_GROUPS, { fail: (op) => (op === "members" ? gate.promise.then(() => { throw failure("STUDIO_UNAVAILABLE", 503); }) : null) });
  const view = await mountGroups({ studio: fake.studio });
  try {
    await view.click(view.byLabel("BUTTON", "m1.pdf 묶음으로 이동"));
    await view.click(view.menuItem("청구"));
    assert.deepEqual(view.listed("청구 묶음 소스"), ["source-m1"], "저장 중에도 옮겨 보인다");
    await view.act(async () => { gate.resolve(); await flush(); });
    assert.equal(view.listed("청구 묶음 소스"), null);
    assert.deepEqual(view.listed("Raw Source 목록"), ["source-m1", "source-m3", "source-m5"]);
    const alert = view.find((node) => node.getAttribute("role") === "alert")[0];
    assert.match(alert.textContent, /저장하지 못해 되돌렸습니다/u);
    assert.doesNotMatch(view.text(), /STUDIO_UNAVAILABLE/u);
  } finally { await view.cleanup(); }
});

test("412(다른 곳에서 바뀜)는 다시 조회해 최신 묶음을 보이고 안내한다", async () => {
  const fake = fakeGroups(TWO_GROUPS);
  const view = await mountGroups({ studio: fake.studio });
  try {
    fake.external((groups) => { groups[0].name = "약관(수정)"; groups[1].source_ids = ["source-m5"]; });
    await view.click(view.byLabel("BUTTON", "m1.pdf 묶음으로 이동"));
    await view.click(view.menuItem("청구"));
    assert.deepEqual(fake.calls.slice(-2).map((c) => c[0]), ["members", "list"]);
    assert.deepEqual(view.listed("청구 묶음 소스"), ["source-m5"], "서버 최신 상태");
    assert.ok(groupCheck(view, "약관(수정)"));
    assert.match(view.text(), /최신 상태를 다시 불러왔습니다/u);
    // 다시 조회한 ETag로 다음 변경이 된다.
    await view.click(view.byLabel("BUTTON", "m1.pdf 묶음으로 이동"));
    await view.click(view.menuItem("청구"));
    assert.deepEqual(fake.calls.at(-1), ["members", G2, ["source-m5", "source-m1"], '"source-groups:2"']);
    assert.deepEqual(view.listed("청구 묶음 소스"), ["source-m5", "source-m1"]);
  } finally { await view.cleanup(); }
});

test("묶음 만들기(이름 입력)·이름 바꾸기·삭제(소스는 묶음 없음으로)", async () => {
  const fake = fakeGroups(TWO_GROUPS);
  const view = await mountGroups({ studio: fake.studio });
  try {
    await view.click(view.button("묶음 만들기"));
    const name = () => view.byLabel("INPUT", "묶음 이름");
    await view.type(name(), "   ");
    await view.click(view.button("만들기"));
    assert.equal(fake.calls.filter((c) => c[0] === "create").length, 0, "빈 이름은 보내지 않는다");
    assert.match(view.text(), /1~80자/u);
    await view.type(name(), "부속 서류");
    await view.click(view.button("만들기"));
    assert.deepEqual(fake.calls.find((c) => c[0] === "create"), ["create", "부속 서류"]);
    assert.ok(groupCheck(view, "부속 서류"), "만든 묶음이 보인다(다시 조회)");
    assert.equal(name(), undefined, "입력칸은 닫힌다");

    await view.click(view.byLabel("BUTTON", "약관 묶음 메뉴"));
    await view.click(view.menuItem("이름 바꾸기"));
    await view.type(name(), "보험 약관");
    await view.click(view.button("저장"));
    const update = fake.calls.find((c) => c[0] === "update");
    assert.deepEqual(update.slice(0, 3), ["update", G1, { name: "보험 약관", position: undefined }]);
    assert.ok(groupCheck(view, "보험 약관"));

    await view.click(view.byLabel("BUTTON", "보험 약관 묶음 메뉴"));
    await view.click(view.menuItem("묶음 삭제"));
    assert.match(view.text(), /소스 자체는 그대로 남습니다/u);
    await view.click(view.button("삭제"));
    assert.equal(fake.calls.at(-1)[0], "delete");
    assert.equal(groupCheck(view, "보험 약관"), undefined);
    assert.deepEqual(view.listed("Raw Source 목록"), UI_SOURCES.map((s) => s.sourceId), "안의 소스는 묶음 없음으로");
  } finally { await view.cleanup(); }
});

test("묶음 상한(409 SOURCE_GROUP_LIMIT)은 상한 안내를 보인다", async () => {
  const fake = fakeGroups(TWO_GROUPS, { fail: (op) => (op === "create" ? failure("SOURCE_GROUP_LIMIT", 409) : null) });
  const view = await mountGroups({ studio: fake.studio });
  try {
    await view.click(view.button("묶음 만들기"));
    await view.type(view.byLabel("INPUT", "묶음 이름"), "새 묶음");
    await view.click(view.button("만들기"));
    assert.match(view.text(), /50개까지/u);
  } finally { await view.cleanup(); }
});

test("보기 권한이면 변경 메뉴(만들기·묶음 메뉴·이동)를 숨기고 묶음 보기·체크·접기는 된다", async () => {
  const fake = fakeGroups(TWO_GROUPS);
  const view = await mountGroups({ studio: fake.studio, canEdit: false });
  try {
    assert.ok(groupCheck(view, "약관"));
    assert.equal(view.button("묶음 만들기"), undefined);
    assert.equal(view.byLabel("BUTTON", "약관 묶음 메뉴"), undefined);
    assert.equal(view.byLabel("BUTTON", "m1.pdf 묶음으로 이동"), undefined);
    await view.click(groupCheck(view, "약관"));
    assert.equal(groupCheck(view, "약관").getAttribute("aria-checked"), "false");
    await view.click(view.byLabel("BUTTON", "약관 묶음 접기"));
    assert.ok(view.byLabel("BUTTON", "약관 묶음 펴기"));
  } finally { await view.cleanup(); }
});

test("변경이 403이면 되돌리고 권한 안내 후 변경 메뉴를 숨긴다", async () => {
  const fake = fakeGroups(TWO_GROUPS, { fail: (op) => (op === "members" ? failure("FORBIDDEN", 403) : null) });
  const view = await mountGroups({ studio: fake.studio });
  try {
    await view.click(view.byLabel("BUTTON", "m1.pdf 묶음으로 이동"));
    await view.click(view.menuItem("약관"));
    assert.deepEqual(view.listed("약관 묶음 소스"), ["source-m4", "source-m2"]);
    assert.match(view.text(), /편집할 권한이 없어/u);
    assert.equal(view.button("묶음 만들기"), undefined);
    assert.equal(view.byLabel("BUTTON", "약관 묶음 메뉴"), undefined);
    assert.equal(view.byLabel("BUTTON", "m3.pdf 묶음으로 이동"), undefined);
  } finally { await view.cleanup(); }
});

test("소스 목록이 바뀌면(refreshKey) 묶음을 다시 읽고, 조회 실패는 평면 목록 + 다시 시도", async () => {
  let failing = true;
  const fake = fakeGroups(TWO_GROUPS);
  const studio = { ...fake.studio, listSourceGroups: async (...args) => { if (failing) { fake.calls.push(["list-failed"]); throw failure("STUDIO_UNAVAILABLE", 503); } return fake.studio.listSourceGroups(...args); } };
  const view = await mountGroups({ studio, refreshKey: "a" });
  try {
    assert.deepEqual(view.listed("Raw Source 목록"), UI_SOURCES.map((s) => s.sourceId));
    assert.match(view.text(), /묶음을 불러오지 못했습니다/u);
    assert.equal(view.button("묶음 만들기"), undefined, "ETag가 없으면 바꾸지 않는다");
    failing = false;
    await view.click(view.button("다시 시도"));
    assert.ok(groupCheck(view, "약관"));
    const before = fake.calls.filter((c) => c[0] === "list").length;
    await view.render({ refreshKey: "b" });
    assert.equal(fake.calls.filter((c) => c[0] === "list").length, before + 1);
  } finally { await view.cleanup(); }
});

// ---- 셸 통합: 질문 범위는 바뀌지 않는다 ----
const baseAdapter = Object.freeze({ listSources() {}, uploadPdf() {}, getProcessingStatus() {}, askQuestion() {}, citationUrl() {}, createReport() {}, listStudioOutputs() {} });
const apiSource = (n) => ({ source_id: `source-m${n}`, source_version_id: `version-m${n}`, filename: `m${n}.pdf`, source_state: "ready", processing_state: "completed", job_state: "completed" });
const answer = () => ({ run_id: "run-g", run_result_id: "result-g", answer: "응답", insufficient: false, citations: [] });
function shellAdapter({ sources, groups, calls }) {
  const fake = groups ? fakeGroups(groups) : null;
  const studioV2 = { listTypes: async () => [], listOutputs: async () => ({ items: [], nextCursor: null }), ...(fake ? fake.studio : {}) };
  return { ...baseAdapter, notebookContext: { notebook_id: "notebook-g", sources: [] }, listSources: async () => sources, listConnectors: async () => [], listStudioOutputs: async () => [],
    listKnowledgePackages: async () => [], askQuestion: async (input) => { calls.push(input); return answer(); }, studioV2 };
}
async function mountShell(adapter) {
  const { ProductWorkspaceShell } = await bundle("source-groups-shell", "packages/ui/src/product-workspace-shell.jsx");
  const dom = installMinimalDom();
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(ProductWorkspaceShell, { workspaceId: "workspace-1", adapter })); await flush(); });
  await act(async () => { await flush(); });
  const byLabel = (tag, label) => findElements(container, (node) => node.tagName === tag && node.getAttribute("aria-label") === label)[0];
  const click = async (node) => { assert.ok(node); await act(async () => { node.dispatchEvent(new MinimalEvent("click")); await flush(); }); };
  const ask = async (text) => {
    const textarea = findElements(container, (node) => node.tagName === "TEXTAREA")[0];
    textarea.value = text;
    await act(async () => props(textarea).onChange({ currentTarget: textarea, target: textarea }));
    const form = findElements(container, (node) => node.tagName === "FORM" && node.getAttribute("class") === "conversation-composer")[0];
    await act(async () => { await props(form).onSubmit({ preventDefault() {} }); await flush(); });
  };
  return { container, byLabel, click, ask, cleanup: async () => { await act(async () => reactRoot.unmount()); dom.restore(); } };
}
const resourceIds = (input) => input.knowledgeContext?.resources.map((item) => item.resourceId) ?? null;

test("셸: 묶음 체크로 바꾼 질문 범위는 같은 소스를 하나씩 체크한 결과와 정확히 같다(세 상태 포함)", async () => {
  const sources = [1, 2, 3, 4, 5].map(apiSource);
  const grouped = []; const single = [];
  const withGroups = await mountShell(shellAdapter({ sources, groups: TWO_GROUPS, calls: grouped }));
  try {
    const box = () => withGroups.byLabel("INPUT", "약관 묶음 사용");
    assert.ok(box(), "셸 소스 칸에 묶음이 보인다");
    // 묶음 안 소스 줄도 기존 조작(사용 체크칸·작업 메뉴)을 그대로 가진다.
    assert.ok(withGroups.byLabel("INPUT", "m4.pdf 사용"));
    assert.ok(withGroups.byLabel("BUTTON", "m4.pdf 작업"));
    assert.ok(withGroups.byLabel("BUTTON", "m4.pdf 묶음으로 이동"));
    assert.equal(box().getAttribute("aria-checked"), "true");
    await withGroups.click(box());
    assert.equal(box().getAttribute("aria-checked"), "false");
    await withGroups.ask("묶음 해제 후 질문");
    await withGroups.click(withGroups.byLabel("INPUT", "m2.pdf 사용"));
    assert.equal(box().getAttribute("aria-checked"), "mixed");
    await withGroups.ask("일부 체크 질문");
    await withGroups.click(box());
    assert.equal(box().getAttribute("aria-checked"), "true");
    await withGroups.ask("묶음 다시 체크 질문");
  } finally { await withGroups.cleanup(); }
  const flat = await mountShell(shellAdapter({ sources, groups: null, calls: single }));
  try {
    assert.equal(flat.byLabel("INPUT", "약관 묶음 사용"), undefined);
    await flat.click(flat.byLabel("INPUT", "m4.pdf 사용"));
    await flat.click(flat.byLabel("INPUT", "m2.pdf 사용"));
    await flat.ask("묶음 해제 후 질문");
    await flat.click(flat.byLabel("INPUT", "m2.pdf 사용"));
    await flat.ask("일부 체크 질문");
    await flat.click(flat.byLabel("INPUT", "m4.pdf 사용"));
    await flat.ask("묶음 다시 체크 질문");
  } finally { await flat.cleanup(); }
  assert.equal(grouped.length, 3);
  assert.deepEqual(resourceIds(grouped[0]), ["source-m1", "source-m3", "source-m5"]);
  assert.deepEqual(resourceIds(grouped[1]), ["source-m1", "source-m2", "source-m3", "source-m5"]);
  assert.deepEqual(resourceIds(grouped[2]), ["source-m1", "source-m2", "source-m3", "source-m4", "source-m5"]);
  assert.deepEqual(grouped, single, "askQuestion 입력 전체가 같아야 한다");
});

test("셸: 묶음 체크로 9개 이상이 되면 기존 8개 안내 그대로(앞의 8개 사용), 묶음 해제로 0개면 일반 상담", async () => {
  const sources = Array.from({ length: 10 }, (_, i) => apiSource(i + 1));
  const calls = [];
  const groups = [{ group_id: G3, name: "전체", position: 0, source_ids: sources.map((s) => s.source_id) }];
  const view = await mountShell(shellAdapter({ sources, groups, calls }));
  try {
    const box = () => view.byLabel("INPUT", "전체 묶음 사용");
    await view.click(box());
    assert.equal(box().getAttribute("aria-checked"), "false");
    await view.ask("일반 질문");
    assert.equal(calls[0].knowledgeContext, null);
    await view.click(box());
    await view.ask("전체 요약");
    assert.deepEqual(resourceIds(calls[1]), sources.slice(0, 8).map((s) => s.source_id));
    assert.match(view.container.textContent, /질문에는 최대 8개 소스를 쓸 수 있습니다\. 앞의 8개를 사용합니다\./u);
  } finally { await view.cleanup(); }
});
