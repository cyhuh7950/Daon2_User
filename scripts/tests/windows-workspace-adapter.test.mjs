import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createWindowsWorkspaceAdapter } from "../../apps/desktop/src/windows-workspace-adapter.js";

const COMMANDS = [
  "workspace_list_sources",
  "workspace_upload_pdf",
  "workspace_processing_status",
  "workspace_ask_question",
  "workspace_citation_content",
  "workspace_create_report",
  "workspace_list_studio_outputs"
];

test("Windows Workspace Adapter는 정확한 7개 전용 Command만 호출한다", async () => {
  const calls = [];
  const invoke = async (command, args) => {
    calls.push({ command, args });
    if (command === "workspace_list_sources" || command === "workspace_list_studio_outputs") return [];
    if (command === "workspace_upload_pdf") return { source_id: "source-1", source_version_id: "version-1", object_id: "a".repeat(32), digest_sha256: "b".repeat(64), byte_size: 5, status: "accepted", replayed: false, processing_run_id: "run-1", processing_state: "queued", job_state: "queued" };
    if (command === "workspace_processing_status") return { processing_run_id: "run-1", source_id: "source-1", source_version_id: "version-1", processing_state: "completed", source_state: "ready", job_state: "completed", safe_error_code: null };
    if (command === "workspace_ask_question") return { run_id: "run-1", run_result_id: "result-1", answer: "answer", insufficient: false, citations: [] };
    if (command === "workspace_citation_content") return { content_type: "application/pdf", page: 1, bytes: [0x25, 0x50, 0x44, 0x46, 0x2d] };
    return { studio_output_id: "output-1", output_version_id: "version-1", output_type: "evidence_report", title: "title", purpose: "purpose", status: "draft", content: "content", run_id: "run-1", run_result_id: "result-1", citations: [{ citation_id: "citation-1", source_id: "source-1", source_version_id: "version-1", evidence_span_id: "span-1", page: 1, origin: "raw_source", context_item_id: "source-1", locator: { kind: "page", value: "1" } }] };
  };
  const adapter = createWindowsWorkspaceAdapter("workspace-1", { invoke, notebookId: "notebook-1" });
  assert.deepEqual(Object.keys(adapter).sort(), ["applyLicense", "askQuestion", "citationContent", "citationUrl", "createReport", "getLicense", "getProcessingStatus", "listSources", "listStudioOutputs", "uploadPdf"].sort());
  await adapter.listSources();
  await adapter.uploadPdf({ name: "guide.pdf", type: "application/pdf", size: 5, arrayBuffer: async () => Uint8Array.from([0x25, 0x50, 0x44, 0x46, 0x2d]).buffer });
  await adapter.getProcessingStatus("run-1");
  await adapter.askQuestion({ knowledgeContext: { mode: "raw_only", resources: [{ resourceKind: "source", resourceId: "source-1", versionId: "version-1" }] }, question: "question" });
  await adapter.citationContent({ citation_id: "citation-1", page: 1 });
  await adapter.createReport(
    { source_id: "source-1", source_version_id: "version-1", run_id: "run-1", run_result_id: "result-1", title: "title", purpose: "purpose" },
    { idempotencyKey: "report-000000000001" }
  );
  await adapter.listStudioOutputs();
  assert.deepEqual(calls.map(({ command }) => command), COMMANDS);
  assert.equal(calls.find(({ command }) => command === "workspace_create_report").args.input.request_idempotency_key, "report-000000000001");
  for (const { args } of calls) {
    assert.equal(args.input.notebook_id, "notebook-1");
    const wire = JSON.stringify(args).toLowerCase();
    assert.doesNotMatch(wire, /"method"|"path"|"url"|"gateway"|"authorization"|"credential"|"password"/u);
  }
});

test("Windows Adapter source에는 WebView network와 내부주소가 없다", async () => {
  const source = await readFile(new URL("../../apps/desktop/src/windows-workspace-adapter.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /fetch\s*\(|XMLHttpRequest|WebSocket|https?:\/\/|localhost|127\.0\.0\.1|NEXT_PUBLIC_|authorization|credential/i);
});

test("Windows Adapter는 unknown 응답과 잘못된 PDF를 fail-close한다", async () => {
  const adapter = createWindowsWorkspaceAdapter("workspace-1", { notebookId: "notebook-1", invoke: async () => ({ sources: [], unknown: true }) });
  await assert.rejects(adapter.listSources(), /SOURCE_LIST_RESPONSE_INVALID/);
  await assert.rejects(
    adapter.uploadPdf({ name: "bad.txt", type: "text/plain", size: 4, arrayBuffer: async () => new ArrayBuffer(4) }),
    /PDF_UPLOAD_INPUT_INVALID/
  );
  const safeError = createWindowsWorkspaceAdapter("workspace-1", { notebookId: "notebook-1", invoke: async () => Promise.reject({ code: "FORBIDDEN", retryable: false }) });
  await assert.rejects(safeError.listSources(), /FORBIDDEN/);
  const unsafeError = createWindowsWorkspaceAdapter("workspace-1", { notebookId: "notebook-1", invoke: async () => Promise.reject({ code: "FORBIDDEN", retryable: false, credential: "secret" }) });
  await assert.rejects(unsafeError.listSources(), /WORKSPACE_RESPONSE_REJECTED/);
  assert.throws(() => createWindowsWorkspaceAdapter("workspace-1", { invoke: async () => [] }), /WORKSPACE_ADAPTER_UNAVAILABLE/);
});

test("Rust Workspace Bridge는 exact 7 Command와 deny-unknown DTO만 등록한다", async () => {
  const [bridge, library, session] = await Promise.all([
    readFile(new URL("../../apps/desktop/src-tauri/src/workspace_bridge.rs", import.meta.url), "utf8"),
    readFile(new URL("../../apps/desktop/src-tauri/src/lib.rs", import.meta.url), "utf8"),
    readFile(new URL("../../apps/desktop/src-tauri/src/native_session.rs", import.meta.url), "utf8"),
  ]);
  for (const command of COMMANDS) {
    assert.match(bridge, new RegExp(`pub async fn ${command}\\b`, "u"));
    assert.match(library, new RegExp(`\\b${command},`, "u"));
  }
  assert.equal((bridge.match(/#\[serde\(deny_unknown_fields\)\]/gu) ?? []).length >= 16, true);
  assert.match(session, /redirect\(reqwest::redirect::Policy::none\(\)\)/u);
  assert.match(session, /MAX_WORKSPACE_PDF_BYTES/u);
  assert.doesNotMatch(bridge, /pub\s+fn\s+.*credential|pub\s+fn\s+.*access|pub\s+fn\s+.*gateway/iu);
});

test("Windows Adapter 소스 목록은 선택 키 aggregation_only·memo_origin·safe_error_code를 형식 검사 후 받는다", async () => {
  const base = { source_id: "source-1", source_version_id: "version-1", filename: "a.xlsx", source_state: "ready", processing_state: "completed", job_state: "completed" };
  const list = (sources) => createWindowsWorkspaceAdapter("workspace-1", { notebookId: "notebook-1", invoke: async () => sources }).listSources();
  const good = [
    base,
    { ...base, aggregation_only: true },
    { ...base, memo_origin: { memo_output_id: `sv2-${"a".repeat(32)}`, memo_exists: false } },
    { ...base, safe_error_code: "SOURCE_PROCESSING_FAILED" },
    { ...base, safe_error_code: null },
    { ...base, aggregation_only: true, memo_origin: { memo_output_id: `sv2-${"b".repeat(32)}`, memo_exists: true }, safe_error_code: "XLSX_LIMIT" },
  ];
  assert.deepEqual(await list(good), good);
  const bad = [
    { ...base, aggregation_only: false },
    { ...base, aggregation_only: "true" },
    { ...base, memo_origin: { memo_output_id: "memo-1", memo_exists: true } },
    { ...base, memo_origin: { memo_output_id: `sv2-${"a".repeat(32)}`, memo_exists: "yes" } },
    { ...base, memo_origin: { memo_output_id: `sv2-${"a".repeat(32)}`, memo_exists: true, extra: 1 } },
    { ...base, memo_origin: null },
    { ...base, safe_error_code: "lower_case" },
    { ...base, safe_error_code: 5 },
    { ...base, website: {} },
  ];
  for (const source of bad) await assert.rejects(list([source]), /SOURCE_LIST_RESPONSE_INVALID/, JSON.stringify(source));
});

test("Rust Workspace Bridge 소스 DTO는 선택 키를 serde(default) Option으로 받고 deny_unknown_fields를 유지한다", async () => {
  const bridge = await readFile(new URL("../../apps/desktop/src-tauri/src/workspace_bridge.rs", import.meta.url), "utf8");
  const block = bridge.slice(bridge.indexOf("pub struct WorkspaceSource {"), bridge.indexOf("impl WorkspaceSource"));
  const before = bridge.slice(0, bridge.indexOf("pub struct WorkspaceSource {")).split("\n").slice(-3).join("\n");
  assert.match(before, /#\[serde\(deny_unknown_fields\)\]/u);
  assert.match(block, /#\[serde\(default, skip_serializing_if = "Option::is_none"\)\]\s*pub aggregation_only: Option<bool>/u);
  assert.match(block, /#\[serde\(default, skip_serializing_if = "Option::is_none"\)\]\s*pub memo_origin: Option<WorkspaceMemoOrigin>/u);
  assert.match(block, /#\[serde\(default, skip_serializing_if = "Option::is_none"\)\]\s*pub safe_error_code: Option<String>/u);
});
