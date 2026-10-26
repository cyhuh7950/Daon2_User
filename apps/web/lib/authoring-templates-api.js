"use client";

// 조직 작성 템플릿 관리 BFF 클라이언트(WO-A3). 직접 fetch 금지: fetchImpl 기본 인자, same-origin 쿠키.
// 오류는 안전한 코드와(검증 오류일 때) 위치 사유만 노출한다.

const TEMPLATE_ID = /^org_[a-z0-9_]{1,60}$/u;
const ERROR_CODE = /^[A-Z][A-Z0-9_]{2,63}$/u;
const REASON = /^[A-Za-z0-9_.[\]]{1,80}$/u;

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

export class AuthoringTemplateError extends Error {
  constructor(code, status, reason = null) {
    super(code);
    this.code = code;
    this.status = status;
    this.reason = reason;
  }
}

async function failure(response) {
  let code = "AUTHORING_TEMPLATE_REQUEST_FAILED";
  let reason = null;
  try {
    const payload = await response.json();
    if (typeof payload?.error?.code === "string" && ERROR_CODE.test(payload.error.code)) code = payload.error.code;
    if (typeof payload?.error?.details?.reason === "string" && REASON.test(payload.error.details.reason)) reason = payload.error.details.reason;
  } catch {
    // 본문이 없으면 일반 코드를 쓴다.
  }
  return new AuthoringTemplateError(code, response.status, reason);
}

async function call(method, url, { body, headers = {}, signal, fetchImpl = fetch } = {}) {
  const init = { method, credentials: "same-origin", cache: "no-store", signal, headers: { ...headers } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  } else if (method !== "GET") {
    init.headers["Content-Type"] = "application/json";
    init.body = "{}";
  }
  const response = await fetchImpl(url, init);
  if (!response.ok) throw await failure(response);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new AuthoringTemplateError("AUTHORING_TEMPLATE_RESPONSE_INVALID", response.status);
  }
  if (!isObject(payload) || !isObject(payload.data)) throw new AuthoringTemplateError("AUTHORING_TEMPLATE_RESPONSE_INVALID", response.status);
  return payload.data;
}

const validSummary = (item) => isObject(item) && TEMPLATE_ID.test(item.template_id ?? "") && typeof item.title === "string"
  && Number.isSafeInteger(item.version) && (item.status === "active" || item.status === "disabled");

export async function listAuthoringTemplates({ signal, fetchImpl } = {}) {
  const data = await call("GET", "/bff/api/admin/authoring-templates", { signal, fetchImpl });
  if (!Array.isArray(data.templates) || !data.templates.every(validSummary)) throw new AuthoringTemplateError("AUTHORING_TEMPLATE_RESPONSE_INVALID", 200);
  return data.templates;
}

export async function registerAuthoringTemplate(definition, { signal, fetchImpl } = {}) {
  if (!isObject(definition)) throw new AuthoringTemplateError("AUTHORING_TEMPLATE_INPUT_INVALID", 0);
  const data = await call("POST", "/bff/api/admin/authoring-templates", { body: { definition }, signal, fetchImpl });
  if (!validSummary(data)) throw new AuthoringTemplateError("AUTHORING_TEMPLATE_RESPONSE_INVALID", 201);
  return data;
}

export async function exportAuthoringTemplate(templateId, { signal, fetchImpl } = {}) {
  if (!TEMPLATE_ID.test(templateId ?? "")) throw new AuthoringTemplateError("AUTHORING_TEMPLATE_INPUT_INVALID", 0);
  const data = await call("GET", `/bff/api/admin/authoring-templates/${templateId}`, { signal, fetchImpl });
  if (!isObject(data.definition)) throw new AuthoringTemplateError("AUTHORING_TEMPLATE_RESPONSE_INVALID", 200);
  return data.definition;
}

export async function updateAuthoringTemplate(templateId, version, definition, { signal, fetchImpl } = {}) {
  if (!TEMPLATE_ID.test(templateId ?? "") || !Number.isSafeInteger(version) || !isObject(definition)) throw new AuthoringTemplateError("AUTHORING_TEMPLATE_INPUT_INVALID", 0);
  const data = await call("PUT", `/bff/api/admin/authoring-templates/${templateId}`, {
    body: { definition }, headers: { "If-Match": `"authoring-template:${templateId}:${version}"` }, signal, fetchImpl });
  if (!validSummary(data)) throw new AuthoringTemplateError("AUTHORING_TEMPLATE_RESPONSE_INVALID", 200);
  return data;
}

export async function setAuthoringTemplateStatus(templateId, enabled, { signal, fetchImpl } = {}) {
  if (!TEMPLATE_ID.test(templateId ?? "")) throw new AuthoringTemplateError("AUTHORING_TEMPLATE_INPUT_INVALID", 0);
  const data = await call("POST", `/bff/api/admin/authoring-templates/${templateId}/${enabled ? "enable" : "disable"}`, { signal, fetchImpl });
  if (!validSummary(data)) throw new AuthoringTemplateError("AUTHORING_TEMPLATE_RESPONSE_INVALID", 200);
  return data;
}
