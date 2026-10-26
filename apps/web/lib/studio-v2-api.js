"use client";

import { secureUuid } from "@daon2-user/ui/secure-uuid";

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
export const validOutput = (o) => exact(o, LIST_KEYS) && OUTPUT_ID.test(o.output_id) && STATUSES.has(o.status)
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

export async function getStudioOutput(workspaceId, outputId, { notebookId, revision, signal, fetchImpl } = {}) {
  const suffix = revision ? `?revision=${encodeURIComponent(revision)}` : "";
  const { data, etag } = await json(await request("GET", `${outputPath(workspaceId, notebookId, outputId)}${suffix}`, { signal, fetchImpl }),
    (d) => isObject(d) && OUTPUT_ID.test(d.output_id) && Array.isArray(d.evidence) && Array.isArray(d.assets));
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

export async function regenerateStudioOutput(workspaceId, outputId, { notebookId, settings, idempotencyKey, signal, fetchImpl } = {}) {
  const { data } = await json(await request("POST", `${outputPath(workspaceId, notebookId, outputId)}/regenerate`,
    { body: settings ? { settings } : {}, idempotent: true, idempotencyKey, signal, fetchImpl }), validReceipt);
  return data;
}

export async function createStudioRevision(workspaceId, outputId, { notebookId, content, changeReason, idempotencyKey, signal, fetchImpl } = {}) {
  const body = { content };
  if (changeReason) body.change_reason = changeReason;
  const { data } = await json(await request("POST", `${outputPath(workspaceId, notebookId, outputId)}/revisions`,
    { body, idempotent: true, idempotencyKey, signal, fetchImpl }), (d) => exact(d, ["output_id", "revision_no"]));
  return data;
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

export async function downloadStudioExport(workspaceId, outputId, format, { notebookId, revision, stepUp, signal, fetchImpl } = {}) {
  const suffix = revision ? `?revision=${encodeURIComponent(revision)}` : "";
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

/** 내 대화 기록(질문·답변·실패)을 시간순으로 읽는다. 새로 고침·재로그인 뒤 대화창을 복원한다. */
export async function listChatTurns(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("GET", `${notebookBase(workspaceId, notebookId)}/chat-history`, { signal, fetchImpl }),
    (d) => exact(d, ["turns"]) && Array.isArray(d.turns));
  return data.turns;
}

// ---- 작성(Authoring)과 지식 Connector -----------------------------------------------------------
const validSession = (d) => isObject(d) && typeof d.state === "string" && Number.isSafeInteger(d.revision_no);

export async function listAuthoringTemplates(workspaceId, { notebookId, signal, fetchImpl } = {}) {
  const { data } = await json(await request("GET", `${base(workspaceId, notebookId)}/authoring/templates`, { signal, fetchImpl }),
    (d) => exact(d, ["templates"]) && Array.isArray(d.templates));
  return data.templates;
}

export async function createAuthoringSession(workspaceId, { notebookId, templateId, requestText, idempotencyKey, signal, fetchImpl } = {}) {
  const body = {};
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
