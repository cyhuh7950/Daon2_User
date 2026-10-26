import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import {
  TtsEngineError, disconnectTtsEngine, listTtsEngines, registerTtsEngine, updateTtsEngine, verifyTtsEngine,
} from "../../apps/web/lib/tts-engines-api.js";
import { MinimalEvent, buttonByText, findElements, installMinimalDom } from "./product-studio-dom.mjs";

const root = path.resolve(import.meta.dirname, "../..");
const ID = `te-${"a".repeat(32)}`;
const ID2 = `te-${"b".repeat(32)}`;
const engine = (patch = {}) => ({ engine_id: ID, slug: "supertonic", label: "Supertonic", base_url: "https://tts.example.com", provider_kind: "external_api", language: "ko",
  timeout_seconds: 120, voices: { A: "F1", B: "M1" }, voice_choices: ["F1", "F2", "M1"], status: "verified", last_checked_at: "2026-10-26T08:15:00+00:00", error_code: null,
  is_default: true, version: 3, has_credential: true, source: "settings", ...patch });
const deployment = () => engine({ engine_id: null, slug: "deploy", label: "배포 엔진", status: "deployment", is_default: false, version: 0, source: "deployment", last_checked_at: null });

async function mount(api) {
  const output = await mkdtemp(path.join(root, ".tts-engines-ui-"));
  const dom = installMinimalDom();
  const { build } = await import("vite");
  const { createElement, act } = await import("react");
  const { createRoot } = await import("react-dom/client");
  await build({ configFile: false, logLevel: "silent", root, build: { outDir: output, emptyOutDir: false,
    lib: { entry: path.join(root, "packages/ui/src/tts-engines-pane.jsx"), formats: ["es"], fileName: "tts-pane" },
    rollupOptions: { external: ["react", "react-dom", "react-dom/client"] } } });
  const entry = (await readdir(output)).find((name) => name.startsWith("tts-pane") && /\.m?js$/u.test(name));
  const { TtsEnginesPane } = await import(`${pathToFileURL(path.join(output, entry)).href}?v=${Date.now()}`);
  const container = dom.document.createElement("div");
  dom.document.body.appendChild(container);
  const reactRoot = createRoot(container);
  await act(async () => { reactRoot.render(createElement(TtsEnginesPane, { api })); await Promise.resolve(); });
  const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 15)); });
  const props = (node) => node[Object.keys(node).find((key) => key.startsWith("__reactProps$"))];
  const byLabel = (label) => findElements(container, (node) => node.getAttribute?.("aria-label") === label)[0];
  return { container, flush, act, byLabel,
    click: async (node) => { await act(async () => { node.dispatchEvent(new MinimalEvent("click")); }); await flush(); },
    type: async (label, value) => { const input = byLabel(label); input.value = value; await act(async () => props(input).onChange({ target: input, currentTarget: input })); },
    close: async () => { await act(async () => reactRoot.unmount()); dom.restore(); await rm(output, { recursive: true, force: true }); } };
}

const text = (view) => view.container.textContent;
const failure = (code, status = 400) => Object.assign(new Error(code), { code, status });

test("목록: 기본 배지·상태·목소리·키 유무를 보이고 배포 설정 엔진은 읽기 전용이며 키 값은 어디에도 없다", async () => {
  const view = await mount({ list: async () => [engine(), deployment()] });
  try {
    await view.flush();
    assert.ok(text(view).includes("Supertonic"));
    assert.ok(text(view).includes("기본"));
    assert.ok(text(view).includes("연결됨"));
    assert.ok(text(view).includes("F1 / M1"));
    assert.ok(text(view).includes("2026-10-26 08:15"));
    assert.ok(text(view).includes("키 있음"));
    assert.ok(text(view).includes("배포 엔진"));
    assert.ok(text(view).includes("배포 설정(수정 불가)"));
    assert.equal(view.byLabel("배포 엔진 연결 확인"), undefined);                 // 배포 엔진에는 작업 버튼이 없다
    assert.equal(view.byLabel("Supertonic 기본으로 지정"), undefined);            // 이미 기본이면 버튼이 없다
    assert.ok(view.byLabel("Supertonic 연결 확인"));
  } finally { await view.close(); }
});

test("외부 API 엔진은 외부 전송 정책에 넣을 호스트 이름을 보이고 서버 내부 엔진은 보이지 않는다", async () => {
  const view = await mount({ list: async () => [engine(), engine({ engine_id: ID2, slug: "local", label: "내부", base_url: "http://voice.internal:8201", provider_kind: "server_internal", is_default: false })] });
  try {
    await view.flush();
    assert.ok(text(view).includes("허용 목적지 필요: tts.example.com"));
    assert.ok(!text(view).includes("허용 목적지 필요: voice.internal"));
  } finally { await view.close(); }
});

test("연결 확인은 진행 뒤 결과를 알리고, 실패하면 원인 문구를 보인다", async () => {
  let result = { status: "verified" };
  const verified = [];
  const view = await mount({ list: async () => [engine({ status: "unverified" })], verify: async (id) => { verified.push(id); return result; } });
  try {
    await view.flush();
    await view.click(view.byLabel("Supertonic 연결 확인"));
    assert.deepEqual(verified, [ID]);
    assert.ok(text(view).includes("연결을 확인했습니다"));
    result = { status: "failed", error_code: "TTS_ENGINE_AUTH_FAILED" };
    await view.click(view.byLabel("Supertonic 연결 확인"));
    assert.ok(text(view).includes("연결을 확인하지 못했습니다"));
    assert.ok(text(view).includes("음성 서버가 키를 거부했습니다"));
  } finally { await view.close(); }
});

test("등록 대화상자: 필수값이 있어야 등록되고 키·전송 구분이 전달되며 오류는 안전한 문구만 보인다", async () => {
  const calls = [];
  let attempt = 0;
  const view = await mount({ list: async () => [],
    register: async (input) => { calls.push(input); attempt += 1; if (attempt === 1) throw failure("TTS_ENGINE_ENDPOINT_PRIVATE_DENIED", 403); return engine(); } });
  try {
    await view.flush();
    assert.ok(text(view).includes("등록된 TTS 엔진이 없습니다"));
    await view.click(buttonByText(view.container, "엔진 추가"));
    assert.equal(buttonByText(view.container, "등록").disabled, true);
    await view.type("식별자", "supertonic");
    await view.type("이름", "Supertonic");
    await view.type("서버 주소", "https://tts.example.com");
    await view.type("API 키", "secret-key-12345");
    await view.type("화자 A(진행자) 기본 목소리", "F1");
    await view.type("화자 B(설명자) 기본 목소리", "M1");
    assert.equal(buttonByText(view.container, "등록").disabled, false);
    await view.click(buttonByText(view.container, "등록"));
    assert.ok(text(view).includes("사설·내부 주소는 이 환경에서 연결할 수 없습니다"));
    assert.ok(!text(view).includes("secret-key-12345"));
    await view.click(buttonByText(view.container, "등록"));
    assert.equal(calls.length, 2);
    assert.deepEqual({ ...calls[1], apiKey: "(있음)" }, { slug: "supertonic", label: "Supertonic", baseUrl: "https://tts.example.com", apiKey: "(있음)",
      providerKind: "external_api", timeoutSeconds: "120", voiceA: "F1", voiceB: "M1" });
    assert.equal(calls[1].apiKey, "secret-key-12345");
    assert.ok(text(view).includes("TTS 엔진을 등록했습니다"));
    assert.equal(view.byLabel("API 키"), undefined);                              // 대화상자가 닫히며 키 입력칸이 사라진다
  } finally { await view.close(); }
});

test("기본으로 지정·사용 안 함·해제는 엔진 ID와 현재 버전으로 서버를 부른다", async () => {
  const calls = [];
  let engines = [engine({ is_default: true }), engine({ engine_id: ID2, slug: "qwen", label: "Qwen", is_default: false, version: 7, status: "unverified" })];
  const view = await mount({ list: async () => engines,
    update: async (id, version, patch) => { calls.push(["update", id, version, patch]); return engine(); },
    disconnect: async (id) => { calls.push(["disconnect", id]); engines = engines.filter((e) => e.engine_id !== id); } });
  try {
    await view.flush();
    await view.click(view.byLabel("Qwen 기본으로 지정"));
    await view.click(view.byLabel("Qwen 사용 안 함"));
    assert.deepEqual(calls, [["update", ID2, 7, { isDefault: true }], ["update", ID2, 7, { enabled: false }]]);
    assert.ok(text(view).includes("사용을 중지했습니다"));
    await view.click(view.byLabel("Qwen 해제"));
    assert.ok(text(view).includes("엔진을 해제할까요"));
    await view.click(buttonByText(view.container, "해제 확인"));
    assert.deepEqual(calls.at(-1), ["disconnect", ID2]);
    assert.ok(text(view).includes("Qwen 엔진을 해제했습니다"));
  } finally { await view.close(); }
});

test("수정: 목소리는 엔진이 알려 준 선택지에서 고르고, 바뀌지 않은 주소와 빈 키는 보내지 않는다", async () => {
  const calls = [];
  const view = await mount({ list: async () => [engine()], update: async (id, version, patch) => { calls.push([id, version, patch]); return engine(); } });
  try {
    await view.flush();
    await view.click(view.byLabel("Supertonic 수정"));
    const select = view.byLabel("화자 A(진행자) 기본 목소리");
    assert.equal(select.tagName, "SELECT");
    assert.deepEqual(findElements(select, (n) => n.tagName === "OPTION").map((o) => o.textContent), ["F1", "F2", "M1"]);
    await view.type("이름", "새 이름");
    await view.click(buttonByText(view.container, "저장"));
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].slice(0, 2), [ID, 3]);
    assert.equal(calls[0][2].label, "새 이름");
    assert.equal(Object.hasOwn(calls[0][2], "baseUrl"), false);
    assert.equal(Object.hasOwn(calls[0][2], "apiKey"), false);
    await view.click(view.byLabel("Supertonic 수정"));
    await view.type("API 키 교체", "another-secret-1");
    await view.click(buttonByText(view.container, "저장"));
    assert.equal(calls[1][2].apiKey, "another-secret-1");
    assert.ok(text(view).includes("다시 확인이 필요합니다"));
  } finally { await view.close(); }
});

test("관리자가 아니면 안내만 보이고 추가 버튼은 막힌다", async () => {
  const view = await mount({ list: async () => { throw failure("FORBIDDEN", 403); } });
  try {
    await view.flush();
    assert.ok(text(view).includes("관리자만 TTS 엔진을 관리할 수 있습니다"));
    assert.equal(buttonByText(view.container, "엔진 추가").disabled, true);
  } finally { await view.close(); }
});

// ---- BFF 클라이언트
const ok = (data, init = {}) => ({ ok: true, status: init.status ?? 200, json: async () => ({ data, meta: {} }), headers: { get: () => null } });
const fetchLog = (response) => { const calls = []; return { calls, fetchImpl: async (url, init) => { calls.push([url, init]); return response; } }; };

test("클라이언트: 경로·헤더·본문을 만들고 응답을 검증한다", async () => {
  let log = fetchLog(ok({ engines: [engine(), deployment()] }));
  assert.equal((await listTtsEngines({ fetchImpl: log.fetchImpl })).length, 2);
  assert.equal(log.calls[0][0], "/bff/api/admin/tts-engines");
  assert.equal(log.calls[0][1].credentials, "same-origin");

  log = fetchLog(ok(engine(), { status: 201 }));
  await registerTtsEngine({ slug: " supertonic ", label: "Supertonic", baseUrl: "https://tts.example.com", apiKey: "secret-key-12345", providerKind: "external_api",
    timeoutSeconds: "90", voiceA: "F1", voiceB: "M1", fetchImpl: log.fetchImpl });
  const [url, init] = log.calls[0];
  assert.equal(url, "/bff/api/admin/tts-engines");
  assert.match(init.headers["Idempotency-Key"], /^tts-engine-/u);
  assert.deepEqual(JSON.parse(init.body), { slug: "supertonic", label: "Supertonic", base_url: "https://tts.example.com", voices: { A: "F1", B: "M1" },
    api_key: "secret-key-12345", provider_kind: "external_api", timeout_seconds: 90 });

  log = fetchLog(ok(engine({ version: 4 })));
  await updateTtsEngine(ID, 3, { isDefault: true, voiceA: "F2", voiceB: "M1", label: " 이름 " }, { fetchImpl: log.fetchImpl });
  assert.equal(log.calls[0][1].headers["If-Match"], `"tts-engine:${ID}:3"`);
  assert.deepEqual(JSON.parse(log.calls[0][1].body), { label: "이름", voices: { A: "F2", B: "M1" }, is_default: true });

  log = fetchLog(ok(engine({ status: "verified" })));
  await verifyTtsEngine(ID, { fetchImpl: log.fetchImpl });
  assert.equal(log.calls[0][0], `/bff/api/admin/tts-engines/${ID}/verify`);

  log = fetchLog({ ok: true, status: 204, json: async () => ({}), headers: { get: () => null } });
  await disconnectTtsEngine(ID, { fetchImpl: log.fetchImpl });
  assert.equal(log.calls[0][1].method, "DELETE");
});

test("클라이언트: 잘못된 입력은 서버를 부르지 않고, 오류 응답은 안전한 코드만 노출한다", async () => {
  const never = { fetchImpl: async () => { throw new Error("호출되면 안 된다"); } };
  await assert.rejects(registerTtsEngine({ slug: "", label: "a", baseUrl: "https://x.example.com", voiceA: "F1", voiceB: "M1", ...never }), { code: "TTS_ENGINE_INPUT_INVALID" });
  await assert.rejects(verifyTtsEngine("not-an-id", never), { code: "TTS_ENGINE_INPUT_INVALID" });
  await assert.rejects(updateTtsEngine(ID, 1.5, { enabled: true }, never), { code: "TTS_ENGINE_INPUT_INVALID" });
  await assert.rejects(updateTtsEngine(ID, 1, {}, never), { code: "TTS_ENGINE_INPUT_INVALID" });
  await assert.rejects(disconnectTtsEngine("x", never), TtsEngineError);
  const body = { ok: false, status: 409, json: async () => ({ error: { code: "TTS_ENGINE_SLUG_EXISTS", message: "내부 상세 메시지 http://10.0.0.5" } }), headers: { get: () => null } };
  await assert.rejects(listTtsEngines({ fetchImpl: async () => body }), (error) => error.code === "TTS_ENGINE_SLUG_EXISTS" && !String(error.message).includes("10.0.0.5"));
  const garbled = { ok: false, status: 500, json: async () => { throw new Error("x"); }, headers: { get: () => null } };
  await assert.rejects(listTtsEngines({ fetchImpl: async () => garbled }), { code: "TTS_ENGINE_REQUEST_FAILED" });
  const wrong = ok({ engines: [{ slug: "x" }] });
  await assert.rejects(listTtsEngines({ fetchImpl: async () => wrong }), { code: "TTS_ENGINE_RESPONSE_INVALID" });
});
