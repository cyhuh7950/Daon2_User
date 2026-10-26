"use client";

// 내려받기 추가 인증 정책 BFF 클라이언트(관리자). 직접 fetch 금지: fetchImpl 기본 인자, same-origin 쿠키.

export class ExportPolicyError extends Error {
  constructor(code, status) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

async function call(method, body, { signal, fetchImpl = fetch } = {}) {
  const init = { method, credentials: "same-origin", cache: "no-store", signal, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetchImpl("/bff/api/admin/export-policy", init);
  if (!response.ok) throw new ExportPolicyError("EXPORT_POLICY_REQUEST_FAILED", response.status);
  let payload;
  try { payload = await response.json(); } catch { throw new ExportPolicyError("EXPORT_POLICY_RESPONSE_INVALID", response.status); }
  if (typeof payload?.data?.require_step_up !== "boolean") throw new ExportPolicyError("EXPORT_POLICY_RESPONSE_INVALID", response.status);
  return payload.data;
}

export const getExportPolicy = (options) => call("GET", undefined, options);
export const setExportPolicy = (requireStepUp, options) => call("PUT", { require_step_up: requireStepUp === true }, options);
