"use client";

import { secureUuid } from "@daon2-user/ui/secure-uuid";
import { withAnswerProcess } from "./answer-process.js";

// Studio v2 BFF 클라이언트(WO-S1 T-S1-01). 경로: /bff/api/workspaces/{ws}/notebooks/{nb}/studio/...
// 규칙: 직접 fetch 호출 금지(fetchImpl 기본 인자), same-origin 쿠키, 쓰기는 Idempotency-Key, 응답은 모양을 검증한다.

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/u;
const OUTPUT_ID = /^sv2-[0-9a-f]{32}$/u;
const ERROR_CODE = /^[A-Z][A-Z0-9_]{2,63}$/u;
const STATUSES = new Set(["queued", "generating", "completed", "failed", "cancelled"]);
export const MAX_EXPORT_BYTES = 32 * 1024 * 1024;
const LIST_KEYS = ["output_id", "type_id", "format_id", "title", "status", "error_code", "source_count", "current_revision", "created_at", "updated_at", "stale"];

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const exact = (value, keys) => isObject(value) && Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key));

export class StudioV2Error extends Error {
  constructor(code, status) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

function base(workspaceId, notebookId) {
  if (!SAFE_ID.test(workspaceId ?? "") || !SAFE_ID.test(notebookId ?? "")) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  return `/bff/api/workspaces/${encodeURIComponent(workspaceId)}/notebooks/${encodeURIComponent(notebookId)}/studio`;
}

function outputPath(workspaceId, notebookId, outputId) {
  if (!OUTPUT_ID.test(outputId ?? "")) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  return `${base(workspaceId, notebookId)}/outputs/${outputId}`;
}

async function failure(response) {
  let code = "STUDIO_REQUEST_FAILED";
  try {
    const payload = await response.json();
    if (typeof payload?.error?.code === "string" && ERROR_CODE.test(payload.error.code)) code = payload.error.code;
  } catch {
    // 본문이 없거나 JSON이 아니면 일반 코드를 쓴다. 원문 오류 문자열은 노출하지 않는다.
  }
  return new StudioV2Error(code, response.status);
}

async function request(method, url, { body, headers = {}, signal, fetchImpl = fetch, idempotent = false, idempotencyKey } = {}) {
  const init = { method, credentials: "same-origin", cache: "no-store", signal, headers: { ...headers } };
  if (idempotent) init.headers["Idempotency-Key"] = idempotencyKey ?? `studio-v2-${secureUuid()}`;
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  } else if (method !== "GET") {
    init.headers["Content-Type"] = "application/json";
    init.body = "{}";
  }
  return fetchImpl(url, init);
}

async function json(response, validate) {
  if (!response.ok) throw await failure(response);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new StudioV2Error("STUDIO_RESPONSE_INVALID", response.status);
  }
  if (!exact(payload, ["data", "meta"]) || !validate(payload.data)) throw new StudioV2Error("STUDIO_RESPONSE_INVALID", response.status);
  return { data: payload.data, etag: response.headers.get("etag"), replayed: payload.meta?.replayed === true };
}

const validType = (t) => isObject(t) && typeof t.type_id === "string" && typeof t.available === "boolean"
  && Array.isArray(t.export_formats) && Array.isArray(t.presets);
// 진행 중인 생성 작업의 진행률·진행 문구(WO-N1 NB4-F2). 진행 중이 아니면 null. 이전 서버 응답(키 없음)도 받는다.
const validProgress = (p) => p === null || (exact(p, ["pct", "note"]) && Number.isSafeInteger(p.pct) && p.pct >= 0 && p.pct <= 100
  && (p.note === null || (typeof p.note === "string" && p.note.length <= 200)));
export const validOutput = (o) => (exact(o, LIST_KEYS) || (exact(o, [...LIST_KEYS, "progress"]) && validProgress(o.progress)))
  && OUTPUT_ID.test(o.output_id) && STATUSES.has(o.status)
  && typeof o.title === "string" && (o.error_code === null || ERROR_CODE.test(o.error_code))
  && Number.isSafeInteger(o.source_count) && Number.isSafeInteger(o.current_revision) && typeof o.stale === "boolean";
const validReceipt = (r) => exact(r, ["output_id", "job_id", "status"]) && OUTPUT_ID.test(r.output_id) && STATUSES.has(r.status);

export async function listStudioTypes(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("GET", `${base(workspaceId, notebookId)}/types`, { signal, fetchImpl }),
    (d) => exact(d, ["types", "limits"]) && Array.isArray(d.types) && d.types.every(validType)
      && exact(d.limits, ["user_concurrency"]) && Number.isSafeInteger(d.limits.user_concurrency) && d.limits.user_concurrency >= 1);
  // 배열에 한도를 붙여 돌려준다(기존 호출부는 배열 그대로 쓴다).
  return Object.assign([...data.types], { limits: { userConcurrency: data.limits.user_concurrency } });
}

export async function listStudioOutputs(workspaceId, { notebookId, cursor, limit = 25, signal, fetchImpl } = {}) {
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor) query.set("cursor", cursor);
  const { data, etag } = await json(await request("GET", `${base(workspaceId, notebookId)}/outputs?${query}`, { signal, fetchImpl }),
    (d) => exact(d, ["items", "next_cursor"]) && Array.isArray(d.items) && d.items.every(validOutput));
  return { items: data.items, nextCursor: data.next_cursor, etag };
}

// 메모를 소스로(WO-N1 NB1-F2): 메모 조회 응답의 source_link는 없거나(null 포함) 정확한 모양이다.
const validSourceLink = (l) => l === undefined || l === null || (exact(l, ["source_id", "reflected_revision_no", "outdated"])
  && SAFE_ID.test(l.source_id) && Number.isSafeInteger(l.reflected_revision_no) && l.reflected_revision_no >= 1 && typeof l.outdated === "boolean");

export async function getStudioOutput(workspaceId, outputId, { notebookId, revision, signal, fetchImpl } = {}) {
  const suffix = revision ? `?revision=${encodeURIComponent(revision)}` : "";
  const { data, etag } = await json(await request("GET", `${outputPath(workspaceId, notebookId, outputId)}${suffix}`, { signal, fetchImpl }),
    (d) => isObject(d) && OUTPUT_ID.test(d.output_id) && Array.isArray(d.evidence) && Array.isArray(d.assets) && validSourceLink(d.source_link));
  return { ...data, etag };
}

export async function createStudioOutput(workspaceId, { notebookId, typeId, formatId, settings, sourceVersionIds, idempotencyKey, signal, fetchImpl } = {}) {
  const body = { type_id: typeId };
  if (formatId) body.format_id = formatId;
  if (settings && Object.keys(settings).length) body.settings = settings;
  if (Array.isArray(sourceVersionIds)) body.source_version_ids = sourceVersionIds;
  const { data, replayed } = await json(await request("POST", `${base(workspaceId, notebookId)}/outputs`,
    { body, idempotent: true, idempotencyKey, signal, fetchImpl }), validReceipt);
  return { ...data, replayed };
}

// 심층 조사(WO-N1 NB4-F2, 결정 D-02 내부만): 스튜디오 보고서 산출물로 만든다(정정 C-5). 노트북 소스는 보내지 않는다(보내면 400).
// 진행 문구는 목록·조회의 progress.note: "계획" → "찾기 n/m" → "작성". 실패 error_code: RESEARCH_TIMEOUT(10분 초과),
// DISCOVERY_SCOPE_UNAVAILABLE(모든 범위 사용 불가), DISCOVERY_CONNECTOR_FAILED(모든 범위 연결 실패), RESEARCH_NO_EVIDENCE(찾은 자료 없음),
// STUDIO_VALIDATION_FAILED(근거 있는 문장 없음). 완료 후 revision.content.research = {query, sub_questions, candidates, unavailable, tool_calls}.
export const MAX_RESEARCH_QUERY = 500;
export async function createStudioResearch(workspaceId, { notebookId, query, scopes, formatId, focus, idempotencyKey, signal, fetchImpl } = {}) {
  if (typeof query !== "string" || !query.trim() || query.length > MAX_RESEARCH_QUERY || !Array.isArray(scopes) || scopes.length < 1
    || new Set(scopes).size !== scopes.length || !scopes.every((scope) => DISCOVERY_SCOPES.has(scope))) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  const settings = { research_query: query, research_scopes: [...scopes] };
  if (typeof focus === "string" && focus.trim()) settings.focus = focus;
  return createStudioOutput(workspaceId, { notebookId, typeId: "report", formatId, settings, idempotencyKey, signal, fetchImpl });
}

/** 보고서 조회 결과(getStudioOutput)에서 심층 조사 정보를 꺼낸다. 심층 조사가 아니거나 모양이 틀리면 null.
 * candidates는 빠른 찾기 후보와 같은 모양이며 candidates[i]가 보고서 근거 라벨 S{i+1}이다. 추가는 addSourceDiscovery(ref)로 한다. */
export function studioResearchOf(output) {
  const research = output?.revision?.content?.research;
  if (!exact(research, ["query", "sub_questions", "candidates", "unavailable", "tool_calls"])) return null;
  const ok = typeof research.query === "string" && Array.isArray(research.sub_questions) && research.sub_questions.length >= 1
    && research.sub_questions.length <= 5 && research.sub_questions.every((q) => typeof q === "string")
    && Array.isArray(research.candidates) && research.candidates.length <= 40 && research.candidates.every(validDiscoveryCandidate)
    && new Set(research.candidates.map((c) => c.candidate_id)).size === research.candidates.length
    && Array.isArray(research.unavailable) && research.unavailable.every((u) => exact(u, ["scope", "reason"]) && DISCOVERY_SCOPES.has(u.scope) && ERROR_CODE.test(u.reason))
    && Number.isSafeInteger(research.tool_calls) && research.tool_calls >= 0 && research.tool_calls <= 12;
  return ok ? { query: research.query, subQuestions: [...research.sub_questions], candidates: research.candidates, unavailable: research.unavailable, toolCalls: research.tool_calls } : null;
}

export async function renameStudioOutput(workspaceId, outputId, title, { notebookId, etag, signal, fetchImpl } = {}) {
  const headers = etag ? { "If-Match": etag } : {};
  const { data } = await json(await request("PATCH", outputPath(workspaceId, notebookId, outputId), { body: { title }, headers, signal, fetchImpl }),
    (d) => exact(d, ["output_id", "title", "updated_at"]));
  return data;
}

export async function deleteStudioOutput(workspaceId, outputId, { notebookId, signal, fetchImpl } = {}) {
  const response = await request("DELETE", outputPath(workspaceId, notebookId, outputId), { signal, fetchImpl });
  if (response.status !== 204) throw await failure(response);
}

export async function cancelStudioOutput(workspaceId, outputId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("POST", `${outputPath(workspaceId, notebookId, outputId)}/cancel`, { signal, fetchImpl }),
    (d) => exact(d, ["output_id", "cancel_requested"]));
  return data;
}

export async function regenerateStudioOutput(workspaceId, outputId, { notebookId, settings, formatId, idempotencyKey, signal, fetchImpl } = {}) {
  const body = settings ? { settings } : {};
  if (formatId) body.format_id = formatId;
  const { data } = await json(await request("POST", `${outputPath(workspaceId, notebookId, outputId)}/regenerate`,
    { body, idempotent: true, idempotencyKey, signal, fetchImpl }), validReceipt);
  return data;
}

export async function createStudioRevision(workspaceId, outputId, { notebookId, content, changeReason, idempotencyKey, signal, fetchImpl } = {}) {
  const body = { content };
  if (changeReason) body.change_reason = changeReason;
  const { data } = await json(await request("POST", `${outputPath(workspaceId, notebookId, outputId)}/revisions`,
    { body, idempotent: true, idempotencyKey, signal, fetchImpl }), (d) => exact(d, ["output_id", "revision_no"]));
  return data;
}

const TURN_ID = /^svt-[0-9a-f]{32}$/u;
const TURN_STATES = new Set(["queued", "working", "ready", "no_change", "failed", "applied", "discarded"]);
const CHANGE_OPS = new Set(["replace", "insert_after", "delete"]);
const TURN_KEYS = ["turn_id", "output_id", "base_revision", "instruction", "state", "reply", "changes", "error_code", "applied_revision", "created_at"];
const CHANGE_KEYS = ["op", "id", "before_text", "after_text", "reason", "anchor_text"];
const validChange = (c) => exact(c, CHANGE_KEYS) && CHANGE_OPS.has(c.op) && typeof c.id === "string" && typeof c.before_text === "string"
  && typeof c.after_text === "string" && typeof c.reason === "string" && typeof c.anchor_text === "string";
const validTurn = (t) => exact(t, TURN_KEYS) && TURN_ID.test(t.turn_id) && TURN_STATES.has(t.state) && typeof t.instruction === "string"
  && (t.reply === null || typeof t.reply === "string") && Array.isArray(t.changes) && t.changes.every(validChange)
  && (t.error_code === null || ERROR_CODE.test(t.error_code));

function turnPath(workspaceId, notebookId, outputId, turnId) {
  if (!TURN_ID.test(turnId ?? "")) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  return `${outputPath(workspaceId, notebookId, outputId)}/edit-turns/${turnId}`;
}

export async function createStudioEditTurn(workspaceId, outputId, { notebookId, instruction, idempotencyKey, signal, fetchImpl } = {}) {
  const { data } = await json(await request("POST", `${outputPath(workspaceId, notebookId, outputId)}/edit-turns`,
    { body: { instruction }, idempotent: true, idempotencyKey, signal, fetchImpl }),
  (d) => exact(d, ["turn_id", "job_id", "state"]) && TURN_ID.test(d.turn_id) && TURN_STATES.has(d.state));
  return data;
}

export async function listStudioEditTurns(workspaceId, outputId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("GET", `${outputPath(workspaceId, notebookId, outputId)}/edit-turns`, { signal, fetchImpl }),
    (d) => exact(d, ["turns"]) && Array.isArray(d.turns) && d.turns.every(validTurn));
  return data.turns;
}

export async function applyStudioEditTurn(workspaceId, outputId, turnId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("POST", `${turnPath(workspaceId, notebookId, outputId, turnId)}/apply`, { signal, fetchImpl }),
    (d) => exact(d, ["output_id", "turn_id", "revision_no"]) && Number.isSafeInteger(d.revision_no));
  return data;
}

export async function discardStudioEditTurn(workspaceId, outputId, turnId, { notebookId, signal, fetchImpl = fetch } = {}) {
  const response = await request("POST", `${turnPath(workspaceId, notebookId, outputId, turnId)}/discard`, { signal, fetchImpl });
  if (!response.ok) throw await failure(response);
}

export async function getStudioProvenance(workspaceId, outputId, { notebookId, revision, signal, fetchImpl } = {}) {
  const suffix = revision ? `?revision=${encodeURIComponent(revision)}` : "";
  const { data } = await json(await request("GET", `${outputPath(workspaceId, notebookId, outputId)}/provenance${suffix}`, { signal, fetchImpl }),
    (d) => isObject(d) && Array.isArray(d.sources) && Array.isArray(d.evidence));
  return data;
}

export const EXPORT_STEP_UP_GROUP = "studio_export_download";

/** 조직이 내보내기 추가 인증을 켠 경우: 비밀번호로 한 번 쓰는 승인 토큰을 받는다(대상 = 산출물 ID). */
export async function issueExportStepUp(outputId, password, { signal, fetchImpl = fetch, idempotencyKey } = {}) {
  if (!OUTPUT_ID.test(outputId ?? "") || typeof password !== "string" || !password) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  const response = await fetchImpl("/bff/api/session/step-up", {
    method: "POST", credentials: "same-origin", cache: "no-store", signal,
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey ?? `studio-v2-${secureUuid()}` },
    body: JSON.stringify({ action_group: EXPORT_STEP_UP_GROUP, target_id: outputId, ttl_seconds: 300, password }),
  });
  if (!response.ok) throw await failure(response);
  let payload;
  try { payload = await response.json(); } catch { throw new StudioV2Error("STUDIO_RESPONSE_INVALID", response.status); }
  if (typeof payload?.data?.step_up_authorization !== "string") throw new StudioV2Error("STUDIO_RESPONSE_INVALID", response.status);
  return payload.data.step_up_authorization;
}

export async function downloadStudioExport(workspaceId, outputId, format, { notebookId, revision, includeSources, stepUp, signal, fetchImpl } = {}) {
  const query = new URLSearchParams();
  if (revision) query.set("revision", String(revision));
  // 웹 페이지 HTML 내려받기(WO-N8): 출처 목록을 넣을지(1) 뺄지(0).
  if (typeof includeSources === "boolean") query.set("include_sources", includeSources ? "1" : "0");
  const suffix = query.toString() ? `?${query}` : "";
  const response = await request("GET", `${outputPath(workspaceId, notebookId, outputId)}/exports/${encodeURIComponent(format)}${suffix}`,
    { headers: stepUp ? { "x-daon-step-up-authorization": stepUp } : {}, signal, fetchImpl });
  if (!response.ok) throw await failure(response);
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength === 0 || bytes.byteLength > MAX_EXPORT_BYTES) throw new StudioV2Error("STUDIO_RESPONSE_INVALID", response.status);
  return { bytes, contentType: response.headers.get("content-type") ?? "application/octet-stream", disposition: response.headers.get("content-disposition") ?? "" };
}

export async function getStudioAudio(workspaceId, outputId, { notebookId, signal, fetchImpl } = {}) {
  const response = await request("GET", `${outputPath(workspaceId, notebookId, outputId)}/audio`, { signal, fetchImpl });
  if (!response.ok) throw await failure(response);
  const bytes = new Uint8Array(await response.arrayBuffer());
  const contentType = (response.headers.get("content-type") ?? "").split(";")[0].trim();
  if (bytes.byteLength === 0 || bytes.byteLength > MAX_EXPORT_BYTES || contentType !== "audio/mpeg") throw new StudioV2Error("STUDIO_RESPONSE_INVALID", response.status);
  return { bytes, contentType, durationMs: Number(response.headers.get("x-media-duration-ms")) || 0 };
}

export async function getStudioVideo(workspaceId, outputId, { notebookId, signal, fetchImpl } = {}) {
  const response = await request("GET", `${outputPath(workspaceId, notebookId, outputId)}/video`, { signal, fetchImpl });
  if (!response.ok) throw await failure(response);
  const bytes = new Uint8Array(await response.arrayBuffer());
  const contentType = (response.headers.get("content-type") ?? "").split(";")[0].trim();
  if (bytes.byteLength === 0 || bytes.byteLength > MAX_EXPORT_BYTES || contentType !== "video/mp4") throw new StudioV2Error("STUDIO_RESPONSE_INVALID", response.status);
  return { bytes, contentType, durationMs: Number(response.headers.get("x-media-duration-ms")) || 0 };
}

export async function getStudioEvidenceContent(workspaceId, outputId, refId, { notebookId, revision, signal, fetchImpl } = {}) {
  if (!SAFE_ID.test(refId ?? "")) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  const suffix = revision ? `?revision=${encodeURIComponent(revision)}` : "";
  const response = await request("GET", `${outputPath(workspaceId, notebookId, outputId)}/evidence/${encodeURIComponent(refId)}/content${suffix}`, { signal, fetchImpl });
  if (!response.ok) throw await failure(response);
  const contentType = (response.headers.get("content-type") ?? "").split(";")[0].trim();
  if (contentType === "application/json") return { kind: "excerpt", ...(await response.json()) };
  return { kind: "binary", contentType, bytes: new Uint8Array(await response.arrayBuffer()), page: response.headers.get("x-citation-page") };
}

export async function recordLearningAttempt(workspaceId, outputId, { notebookId, revisionNo, kind, payload, idempotencyKey, signal, fetchImpl } = {}) {
  const { data } = await json(await request("POST", `${outputPath(workspaceId, notebookId, outputId)}/learning-attempts`,
    { body: { revision_no: revisionNo, kind, payload }, idempotent: true, idempotencyKey, signal, fetchImpl }), (d) => exact(d, ["attempt_id"]));
  return data;
}

export async function listLearningAttempts(workspaceId, outputId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("GET", `${outputPath(workspaceId, notebookId, outputId)}/learning-attempts`, { signal, fetchImpl }),
    (d) => exact(d, ["items"]) && Array.isArray(d.items));
  return data.items;
}

export async function getStudioSharing(workspaceId, outputId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("GET", `${outputPath(workspaceId, notebookId, outputId)}/sharing`, { signal, fetchImpl }),
    (d) => exact(d, ["scope", "public_link", "notebook_id"]));
  return data;
}

export async function createStudioMemo(workspaceId, { notebookId, title, markdown, fromRunResultId, idempotencyKey, signal, fetchImpl } = {}) {
  const body = {};
  if (title) body.title = title;
  if (markdown !== undefined) body.markdown = markdown;
  if (fromRunResultId) body.from_run_result_id = fromRunResultId;
  const { data } = await json(await request("POST", `${base(workspaceId, notebookId)}/memos`,
    { body, idempotent: true, idempotencyKey, signal, fetchImpl }), (d) => exact(d, ["output_id", "status", "replayed"]));
  return data;
}

// 메모를 소스로 사용: 메모 본문을 텍스트 소스로 등록한다(201). 응답 {source_id, source_version_id, state}.
// 오류 코드: STUDIO_OUTPUT_NOT_FOUND, OUTPUT_NOT_MEMO, MEMO_SOURCE_EXISTS, MEMO_EMPTY, MEMO_TOO_LARGE, FORBIDDEN.
export async function createMemoSource(workspaceId, outputId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("POST", `${outputPath(workspaceId, notebookId, outputId)}/source`, { signal, fetchImpl }),
    (d) => exact(d, ["source_id", "source_version_id", "state"]) && SAFE_ID.test(d.source_id) && SAFE_ID.test(d.source_version_id)
      && typeof d.state === "string");
  return data;
}

// 소스에 반영: 메모의 현재 리비전을 같은 소스의 새 버전으로 붙인다(200). 응답 {source_id, source_version_id}.
// 오류 코드: MEMO_SOURCE_NOT_LINKED, MEMO_SOURCE_UNCHANGED, MEMO_EMPTY, MEMO_TOO_LARGE, SOURCE_PROCESSING_ACTIVE, FORBIDDEN.
export async function reflectMemoSource(workspaceId, outputId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("POST", `${outputPath(workspaceId, notebookId, outputId)}/source/reflect`, { signal, fetchImpl }),
    (d) => exact(d, ["source_id", "source_version_id"]) && SAFE_ID.test(d.source_id) && SAFE_ID.test(d.source_version_id));
  return data;
}

export async function getStudioCustomization(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const { data, etag } = await json(await request("GET", `${base(workspaceId, notebookId)}/customization`, { signal, fetchImpl }),
    (d) => exact(d, ["instruction", "version"]));
  return { ...data, etag };
}

export async function saveStudioCustomization(workspaceId, instruction, { notebookId, etag, signal, fetchImpl } = {}) {
  const headers = etag ? { "If-Match": etag } : {};
  const { data, etag: next } = await json(await request("PUT", `${base(workspaceId, notebookId)}/customization`,
    { body: { instruction }, headers, signal, fetchImpl }), (d) => exact(d, ["instruction", "version"]));
  return { ...data, etag: next };
}

// ---- Notebook 수준 동작(WO-F3): 복사와 채팅 기록 비움 -------------------------------------------------
function notebookBase(workspaceId, notebookId) {
  if (!SAFE_ID.test(workspaceId ?? "") || !SAFE_ID.test(notebookId ?? "")) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  return `/bff/api/workspaces/${encodeURIComponent(workspaceId)}/notebooks/${encodeURIComponent(notebookId)}`;
}

const COPY_KEYS = ["sources", "memos", "outputs", "customization"];
const validCopy = (d) => isObject(d) && SAFE_ID.test(d.notebook_id ?? "") && typeof d.title === "string" && isObject(d.copied) && isObject(d.skipped);

/** 노트북 복사. 같은 대화상자에서 다시 시도해도 같은 결과가 되도록 호출자가 idempotencyKey를 한 번 만들어 넘긴다. */
export async function copyNotebook(workspaceId, { notebookId, title, include, idempotencyKey, signal, fetchImpl } = {}) {
  const body = {};
  if (typeof title === "string" && title.trim()) body.title = title.trim();
  if (include !== undefined) {
    if (!isObject(include) || Object.keys(include).some((key) => !COPY_KEYS.includes(key) || typeof include[key] !== "boolean")) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
    body.include = include;
  }
  const { data } = await json(await request("POST", `${notebookBase(workspaceId, notebookId)}/copies`, { body, signal, fetchImpl, idempotent: true, idempotencyKey }), validCopy);
  return data;
}

/** 내 채팅 기록 비우기(다른 사용자·메모·산출물은 그대로). */
export async function clearChatHistory(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const response = await request("DELETE", `${notebookBase(workspaceId, notebookId)}/chat-history`, { signal, fetchImpl, idempotent: true });
  if (response.status !== 204) throw await failure(response);
}

const validSelection = (d) => isObject(d) && Array.isArray(d.available) && Array.isArray(d.levels)
  && (d.selection === null || (isObject(d.selection) && typeof d.selection.connection_id === "string" && typeof d.selection.model_id === "string"));

/** 이 노트북에서 내가 고른 모델·추론 수준과 고를 수 있는 승인 모델 목록. */
export async function getModelSelection(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("GET", `${notebookBase(workspaceId, notebookId)}/model-selection`, { signal, fetchImpl }), validSelection);
  return data;
}

/** connectionId·modelId가 null이면 작업공간 기본 모델로 되돌린다. 추론 수준은 모델이 지원을 확인받은 것만 보낼 수 있다. */
export async function saveModelSelection(workspaceId, { notebookId, connectionId = null, modelId = null, reasoningLevel = null, signal, fetchImpl } = {}) {
  const body = { connection_id: connectionId, model_id: modelId, reasoning_level: reasoningLevel };
  const { data } = await json(await request("PUT", `${notebookBase(workspaceId, notebookId)}/model-selection`, { body, signal, fetchImpl }), validSelection);
  return data;
}

// 질문 도구(WO-N1 NB2-F1, 결정 D-02: 웹 도구 없음). 응답 항목은 정확한 키만 받는다.
const TOOL_REASONS = new Set(["NO_SCOPE_SELECTED", "CONNECTOR_NOT_READY", "CONNECTOR_DISABLED"]);
const CONNECTOR_KINDS = new Set(["daon2_rag", "daon2", "law"]);
const TOOL_ID = /^(?:approved_knowledge|connector:[A-Za-z0-9][A-Za-z0-9._:-]{0,245})$/u;

function validTool(item) {
  if (!isObject(item) || typeof item.id !== "string" || !TOOL_ID.test(item.id)) return false;
  const connector = item.kind === "connector";
  if (!connector && !(item.kind === "approved_knowledge" && item.id === "approved_knowledge")) return false;
  if (connector && (!item.id.startsWith("connector:") || !CONNECTOR_KINDS.has(item.connector_kind))) return false;
  const keys = ["id", "kind", ...(connector ? ["connector_kind"] : []), "label", "available", "enabled", ...(item.available === false ? ["reason"] : [])];
  return exact(item, keys) && typeof item.label === "string" && item.label.length >= 1 && item.label.length <= 120
    && typeof item.available === "boolean" && typeof item.enabled === "boolean"
    && (item.available || (TOOL_REASONS.has(item.reason) && item.enabled === false));
}

const validQuestionTools = (d) => exact(d, ["tools"]) && Array.isArray(d.tools) && d.tools.length <= 65 && d.tools.every(validTool);

/** 이 노트북에서 내가 켜고 끈 질문 도구. 사용할 수 없는 도구(available=false)는 reason과 함께 꺼짐으로 온다. */
export async function getQuestionTools(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("GET", `${notebookBase(workspaceId, notebookId)}/question-tools`, { signal, fetchImpl }), validQuestionTools);
  return data;
}

/** enabled: {"<도구 id>": true|false}. 바꾼 도구만 보내면 서버가 이전 선택과 합친다. 모르는 id는 422 QUESTION_TOOL_UNKNOWN. */
export async function saveQuestionTools(workspaceId, { notebookId, enabled, signal, fetchImpl } = {}) {
  if (!isObject(enabled) || Object.entries(enabled).some(([key, value]) => !TOOL_ID.test(key) || typeof value !== "boolean")) {
    throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  }
  const { data } = await json(await request("PUT", `${notebookBase(workspaceId, notebookId)}/question-tools`, { body: { enabled }, signal, fetchImpl }), validQuestionTools);
  return data;
}

// 노트북 개요·추천 질문(WO-N1 NB2-F2, 결정 D-06). none: 준비된 소스 없음. ready일 때만 summary·questions(3개)·citations·generated_at이 있다.
// 폴링 권장: queued·working이면 3초 간격으로 다시 읽고 none·ready·failed·blocked에서 멈춘다.
const OVERVIEW_STATES = new Set(["none", "queued", "working", "ready", "failed", "blocked"]);
const OVERVIEW_ERRORS = new Set(["OVERVIEW_UNGROUNDED", "OVERVIEW_BLOCKED", "OVERVIEW_NO_READY_SOURCE", "OVERVIEW_PROVIDER_UNAVAILABLE", "OVERVIEW_GENERATION_FAILED"]);
const OVERVIEW_KEYS = ["state", "summary", "questions", "citations", "stale", "generated_at", "error_code"];
const validCitation = (c) => exact(c, ["label", "source_title", "page"]) && typeof c.label === "string" && /^[1-9][0-9]{0,2}$/u.test(c.label)
  && typeof c.source_title === "string" && c.source_title.length <= 300 && (c.page === null || (Number.isSafeInteger(c.page) && c.page >= 1));
const validQuestion = (q) => typeof q === "string" && q.length >= 1 && q.length <= 200;

function validNotebookOverview(d) {
  if (!exact(d, OVERVIEW_KEYS) || !OVERVIEW_STATES.has(d.state) || typeof d.stale !== "boolean" || !Array.isArray(d.questions) || !Array.isArray(d.citations)) return false;
  const failed = d.state === "failed" || d.state === "blocked";
  if (!(d.error_code === null || (failed && OVERVIEW_ERRORS.has(d.error_code)))) return false;
  if (d.state !== "ready") return d.summary === null && d.generated_at === null && d.questions.length === 0 && d.citations.length === 0;
  return typeof d.summary === "string" && d.summary.length >= 1 && d.summary.length <= 4000
    && typeof d.generated_at === "string" && d.questions.length === 3 && d.questions.every(validQuestion)
    && d.citations.length >= 1 && d.citations.length <= 64 && d.citations.every(validCitation);
}

/** 노트북 개요. 행이 없고 준비된 소스가 있으면 서버가 첫 생성을 대기열에 넣고 queued를 돌려준다. stale=true면 소스가 바뀐 것이다(자동 재생성 없음). */
export async function getNotebookOverview(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("GET", `${notebookBase(workspaceId, notebookId)}/overview`, { signal, fetchImpl }), validNotebookOverview);
  return data;
}

/** 개요 다시 만들기(노트북 편집 권한). 202와 queued 개요. 진행 중이면 409 OVERVIEW_IN_PROGRESS, 준비된 소스가 없으면 409 OVERVIEW_NO_READY_SOURCE. */
export async function regenerateNotebookOverview(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("POST", `${notebookBase(workspaceId, notebookId)}/overview/regenerate`, { signal, fetchImpl }), validNotebookOverview);
  return data;
}

// 소스 묶음(WO-N1 NB3-F2, 결정 D-11 노트북 공유). 묶음은 화면 편의이고 질문 범위 상한(8개)은 그대로다(정정 C-4).
// 모든 응답은 ETag를 돌려준다. 수정·삭제·구성원 저장은 마지막으로 받은 ETag를 If-Match로 보내야 하고, 다르면 412 SOURCE_GROUP_ETAG_MISMATCH다.
const SOURCE_GROUP_ID = /^sg-[0-9a-f]{32}$/u;
const MAX_SOURCE_GROUPS = 50;
const MAX_GROUP_MEMBERS = 500;
const validGroupName = (name) => typeof name === "string" && name.trim().length >= 1 && name.trim().length <= 80 && !/[\u0000-\u001f\u007f]/u.test(name);
const validSourceGroup = (g) => exact(g, ["group_id", "name", "position", "source_ids"]) && SOURCE_GROUP_ID.test(g.group_id)
  && validGroupName(g.name) && Number.isSafeInteger(g.position) && g.position >= 0
  && Array.isArray(g.source_ids) && g.source_ids.length <= MAX_GROUP_MEMBERS && g.source_ids.every((id) => typeof id === "string" && SAFE_ID.test(id));

function validSourceGroups(d) {
  if (!exact(d, ["groups"]) || !Array.isArray(d.groups) || d.groups.length > MAX_SOURCE_GROUPS || !d.groups.every(validSourceGroup)) return false;
  const ids = d.groups.flatMap((g) => g.source_ids);
  return new Set(ids).size === ids.length && new Set(d.groups.map((g) => g.group_id)).size === d.groups.length;
}

function sourceGroupPath(workspaceId, notebookId, groupId) {
  if (groupId !== undefined && !SOURCE_GROUP_ID.test(groupId ?? "")) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  return `${notebookBase(workspaceId, notebookId)}/source-groups${groupId === undefined ? "" : `/${groupId}`}`;
}

function ifMatch(etag) {
  if (typeof etag !== "string" || etag.length < 1 || etag.length > 256) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  return { "If-Match": etag };
}

/** 노트북의 소스 묶음(순서대로). 노트북에서 떼었거나 삭제 요청된 소스, 내가 볼 수 없는 소스는 source_ids에서 빠진다. */
export async function listSourceGroups(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const { data, etag } = await json(await request("GET", sourceGroupPath(workspaceId, notebookId), { signal, fetchImpl }), validSourceGroups);
  return { groups: data.groups, etag };
}

/** 묶음 만들기(노트북 편집 권한). 이름 1~80자. 노트북당 50개(409 SOURCE_GROUP_LIMIT). 같은 Idempotency-Key 재시도는 같은 묶음(replayed). */
export async function createSourceGroup(workspaceId, { notebookId, name, idempotencyKey, signal, fetchImpl } = {}) {
  if (!validGroupName(name)) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  const path = sourceGroupPath(workspaceId, notebookId);
  const { data, etag, replayed } = await json(await request("POST", path, { body: { name }, idempotent: true, idempotencyKey, signal, fetchImpl }),
    (d) => exact(d, ["group_id"]) && SOURCE_GROUP_ID.test(d.group_id));
  return { groupId: data.group_id, etag, replayed };
}

/** 이름 바꾸기·순서 옮기기(position: 0부터, 끝을 넘으면 맨 끝). 둘 중 하나 이상. 바뀐 전체 묶음 목록과 새 ETag를 돌려준다. */
export async function updateSourceGroup(workspaceId, groupId, { notebookId, name, position, etag, signal, fetchImpl } = {}) {
  const body = {};
  if (name !== undefined) {
    if (!validGroupName(name)) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
    body.name = name;
  }
  if (position !== undefined) {
    if (!Number.isSafeInteger(position) || position < 0 || position >= MAX_SOURCE_GROUPS) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
    body.position = position;
  }
  if (Object.keys(body).length === 0) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  const path = sourceGroupPath(workspaceId, notebookId, groupId);
  const { data, etag: next } = await json(await request("PATCH", path, { body, headers: ifMatch(etag), signal, fetchImpl }), validSourceGroups);
  return { groups: data.groups, etag: next };
}

/** 묶음 삭제. 안의 소스는 묶음 밖으로 나가고 소스 자체는 그대로다. */
export async function deleteSourceGroup(workspaceId, groupId, { notebookId, etag, signal, fetchImpl } = {}) {
  const path = sourceGroupPath(workspaceId, notebookId, groupId);
  const { data, etag: next } = await json(await request("DELETE", path, { headers: ifMatch(etag), signal, fetchImpl }), validSourceGroups);
  return { groups: data.groups, etag: next };
}

/** 묶음 구성원을 이 순서 그대로 저장한다. 다른 묶음에 있던 소스는 옮겨 온다. 노트북에 없는 소스는 422 SOURCE_NOT_IN_NOTEBOOK. */
export async function setSourceGroupMembers(workspaceId, groupId, { notebookId, sourceIds, etag, signal, fetchImpl } = {}) {
  if (!Array.isArray(sourceIds) || sourceIds.length > MAX_GROUP_MEMBERS || new Set(sourceIds).size !== sourceIds.length
    || !sourceIds.every((id) => typeof id === "string" && SAFE_ID.test(id))) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  const path = `${sourceGroupPath(workspaceId, notebookId, groupId)}/members`;
  const { data, etag: next } = await json(await request("PUT", path, { body: { source_ids: sourceIds }, headers: ifMatch(etag), signal, fetchImpl }),
    validSourceGroups);
  return { groups: data.groups, etag: next };
}

// 자료 찾기·빠른 찾기(WO-N1 NB4-F1, 결정 D-02 웹 제외·내부만, 정정 C-6). 검색은 노트북 보기, 추가는 편집 권한.
// 범위: knowledge(Daon2 승인 지식 → 업무 패키지 후보, add_scope) · documents(Daon2-RAG 문서 → 문서 후보, add_source).
// 검색 한 번에 후보 최대 20개. 쓸 수 없거나 실패한 범위는 unavailable[{scope, reason}]로 오고 다른 범위 결과는 그대로다.
// 모든 범위를 쓸 수 없으면 422 DISCOVERY_SCOPE_UNAVAILABLE, 모두 실패하면 502 DISCOVERY_CONNECTOR_FAILED.
// 추가: 이미 있는 패키지는 200 그대로, 문서가 너무 크면 413 DISCOVERY_DOCUMENT_TOO_LARGE(텍스트 소스 상한 2 MiB와 같음).
const DISCOVERY_SCOPES = new Set(["knowledge", "documents"]);
const MAX_DISCOVERY_QUERY = 500;
const MAX_DISCOVERY_CANDIDATES = 20;
const DISCOVERY_KEYS = ["candidate_id", "kind", "title", "origin_label", "reason", "preview", "action", "ref"];
const DISCOVERY_ACTIONS = { knowledge_package: "add_scope", document: "add_source" };
const REF_KEYS = { knowledge_package: ["kind", "project_id", "work_package_id"], document: ["kind", "project_id", "work_package_id", "document_id", "document_version"] };
const refId = (value) => typeof value === "string" && value.length >= 1 && value.length <= 256 && !/[\u0000-\u001f\u007f]/u.test(value);
const shortText = (value, max) => typeof value === "string" && value.length <= max;
export const validDiscoveryRef = (r) => isObject(r) && Object.hasOwn(REF_KEYS, r.kind) && exact(r, REF_KEYS[r.kind]) && REF_KEYS[r.kind].slice(1).every((key) => refId(r[key]));
const validDiscoveryCandidate = (c) => exact(c, DISCOVERY_KEYS) && typeof c.candidate_id === "string" && SAFE_ID.test(c.candidate_id)
  && Object.hasOwn(DISCOVERY_ACTIONS, c.kind) && c.action === DISCOVERY_ACTIONS[c.kind] && validDiscoveryRef(c.ref) && c.ref.kind === c.kind
  && shortText(c.title, 200) && shortText(c.origin_label, 120) && shortText(c.reason, 200) && shortText(c.preview, 300);
const validDiscoveryResult = (d) => exact(d, ["candidates", "unavailable"]) && Array.isArray(d.candidates) && d.candidates.length <= MAX_DISCOVERY_CANDIDATES
  && d.candidates.every(validDiscoveryCandidate) && new Set(d.candidates.map((c) => c.candidate_id)).size === d.candidates.length
  && Array.isArray(d.unavailable) && d.unavailable.every((u) => exact(u, ["scope", "reason"]) && DISCOVERY_SCOPES.has(u.scope) && ERROR_CODE.test(u.reason));

/** 승인 지식·지식 연결에서 자료 후보를 찾는다. 자동으로 추가하지 않는다(사람이 고른 것만 addSourceDiscovery). */
export async function searchSourceDiscovery(workspaceId, { notebookId, query, scopes, signal, fetchImpl } = {}) {
  if (typeof query !== "string" || !query.trim() || query.length > MAX_DISCOVERY_QUERY || !Array.isArray(scopes) || scopes.length < 1
    || new Set(scopes).size !== scopes.length || !scopes.every((scope) => DISCOVERY_SCOPES.has(scope))) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  const { data } = await json(await request("POST", `${notebookBase(workspaceId, notebookId)}/source-discovery/search`,
    { body: { query, scopes }, signal, fetchImpl }), validDiscoveryResult);
  return data;
}

/** 후보의 ref 하나를 추가한다. add_scope는 승인 지식 범위에, add_source는 텍스트 소스(처리 중으로 나타남)로. 서버가 ref 접근을 다시 확인한다. */
export async function addSourceDiscovery(workspaceId, { notebookId, ref, idempotencyKey, signal, fetchImpl } = {}) {
  if (!validDiscoveryRef(ref)) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  const { data } = await json(await request("POST", `${notebookBase(workspaceId, notebookId)}/source-discovery/add`,
    { body: { ref }, idempotent: true, idempotencyKey, signal, fetchImpl }),
  (d) => (exact(d, ["added"]) && d.added === "scope") || (exact(d, ["added", "source_id"]) && d.added === "source" && SAFE_ID.test(d.source_id)));
  return { added: data.added, sourceId: data.added === "source" ? data.source_id : null };
}

/** 내 대화 기록(질문·답변·실패)을 시간순으로 읽는다. 새로 고침·재로그인 뒤 대화창을 복원한다.
 * 각 답변의 process(답변 과정)는 질문 응답과 같은 규칙으로 검사해 열거되지 않는 `answer.process`로 붙인다(틀리면 null). */
export async function listChatTurns(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("GET", `${notebookBase(workspaceId, notebookId)}/chat-history`, { signal, fetchImpl }),
    (d) => exact(d, ["turns"]) && Array.isArray(d.turns));
  return data.turns.map((turn) => (isObject(turn) && isObject(turn.answer) ? { ...turn, answer: withAnswerProcess(turn.answer) } : turn));
}

// ---- 작성(Authoring)과 지식 Connector -----------------------------------------------------------
const validSession = (d) => isObject(d) && typeof d.state === "string" && Number.isSafeInteger(d.revision_no);

export async function listAuthoringTemplates(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("GET", `${base(workspaceId, notebookId)}/authoring/templates`, { signal, fetchImpl }),
    (d) => exact(d, ["templates"]) && Array.isArray(d.templates));
  return data.templates;
}

export async function createAuthoringSession(workspaceId, { notebookId, templateId, requestText, targetPages, confirmMaterial, idempotencyKey, signal, fetchImpl } = {}) {
  const body = {};
  if (confirmMaterial) body.confirm_material = true;
  if (targetPages) body.target_pages = targetPages;
  if (templateId) body.template_id = templateId;
  if (requestText) body.request_text = requestText;
  const { data } = await json(await request("POST", `${base(workspaceId, notebookId)}/authoring/sessions`, { body, idempotent: true, idempotencyKey, signal, fetchImpl }),
    (d) => isObject(d) && typeof d.created === "boolean");
  return data;
}

export async function getAuthoringSession(workspaceId, outputId, { notebookId, signal, fetchImpl } = {}) {
  if (!OUTPUT_ID.test(outputId ?? "")) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  const { data } = await json(await request("GET", `${base(workspaceId, notebookId)}/authoring/sessions/${outputId}`, { signal, fetchImpl }), validSession);
  return data;
}

export async function answerAuthoringSession(workspaceId, outputId, { notebookId, expectedRevision, answers, skipRemaining = false, idempotencyKey, signal, fetchImpl } = {}) {
  const { data } = await json(await request("POST", `${base(workspaceId, notebookId)}/authoring/sessions/${outputId}/answers`,
    { body: { expected_revision: expectedRevision, answers, skip_remaining: skipRemaining }, idempotent: true, idempotencyKey, signal, fetchImpl }),
    (d) => isObject(d) && Number.isSafeInteger(d.revision_no));
  return data;
}

export async function reviewAuthoringSession(workspaceId, outputId, { notebookId, expectedRevision, requirements, planSections, outputFormats, confirm = false, signal, fetchImpl } = {}) {
  const body = { expected_revision: expectedRevision, confirm };
  if (requirements) body.requirements = requirements;
  if (planSections) body.plan_sections = planSections;
  if (outputFormats) body.output_formats = outputFormats;
  const { data } = await json(await request("PUT", `${base(workspaceId, notebookId)}/authoring/sessions/${outputId}/review`, { body, signal, fetchImpl }),
    (d) => isObject(d) && Number.isSafeInteger(d.revision_no));
  return data;
}

export async function controlAuthoringSession(workspaceId, outputId, { notebookId, action, expectedRevision, unitKey, materialRefs, signal, fetchImpl } = {}) {
  const body = { action };
  if (materialRefs) body.material_refs = materialRefs;
  if (unitKey) body.unit_key = unitKey;
  if (expectedRevision) body.expected_revision = expectedRevision;
  const { data } = await json(await request("POST", `${base(workspaceId, notebookId)}/authoring/sessions/${outputId}/control`, { body, signal, fetchImpl }), isObject);
  return data;
}

export async function editAuthoringUnit(workspaceId, outputId, unitKey, { notebookId, expectedRevision, paragraphs, signal, fetchImpl } = {}) {
  const { data } = await json(await request("PUT", `${base(workspaceId, notebookId)}/authoring/sessions/${outputId}/units/${encodeURIComponent(unitKey)}`,
    { body: { expected_revision: expectedRevision, paragraphs }, signal, fetchImpl }), isObject);
  return data;
}

export async function updateAuthoringOutline(workspaceId, outputId, { notebookId, expectedRevision, units, confirm = false, signal, fetchImpl } = {}) {
  const { data } = await json(await request("PUT", `${base(workspaceId, notebookId)}/authoring/sessions/${outputId}/outline`,
    { body: { expected_revision: expectedRevision, units, confirm }, signal, fetchImpl }), isObject);
  return data;
}

export async function listKnowledgeConnectors({ signal, fetchImpl = fetch } = {}) {
  const { data } = await json(await request("GET", "/bff/api/knowledge-connectors", { signal, fetchImpl }), (d) => exact(d, ["connectors"]) && Array.isArray(d.connectors));
  return data.connectors;
}

export async function listConnectorDocuments(connectorId, { projectId, workPackageId, documentType, signal, fetchImpl = fetch } = {}) {
  if (!/^kc-[0-9a-f]{32}$/u.test(connectorId ?? "")) throw new StudioV2Error("STUDIO_INPUT_INVALID", 0);
  const query = new URLSearchParams({ project_id: projectId, work_package_id: workPackageId });
  if (documentType) query.set("document_type", documentType);
  const { data } = await json(await request("GET", `/bff/api/knowledge-connectors/${connectorId}/documents?${query}`, { signal, fetchImpl }),
    (d) => exact(d, ["documents"]) && Array.isArray(d.documents));
  return data.documents;
}
