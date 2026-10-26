"use client";

import { secureUuid } from "@daon2-user/ui/secure-uuid";

// TTS 엔진 관리 BFF 클라이언트(WO-F7T). 직접 fetch 금지: fetchImpl 기본 인자, same-origin 쿠키, 쓰기는 Idempotency-Key.
// 응답 오류는 안전한 코드만 노출한다. API 키는 요청 본문에만 실리고 응답·화면에는 남지 않는다(has_credential만 받는다).

const ENGINE_ID = /^te-[0-9a-f]{32}$/u;
const ERROR_CODE = /^[A-Z][A-Z0-9_]{2,63}$/u;
export const TTS_PROVIDER_KINDS = Object.freeze({ external_api: "외부 API(외부 전송 정책 적용)", server_internal: "서버 내부" });

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

export class TtsEngineError extends Error {
  constructor(code, status) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

async function failure(response) {
  let code = "TTS_ENGINE_REQUEST_FAILED";
  try {
    const payload = await response.json();
    if (typeof payload?.error?.code === "string" && ERROR_CODE.test(payload.error.code)) code = payload.error.code;
  } catch {
    // 본문이 없으면 일반 코드를 쓴다.
  }
  return new TtsEngineError(code, response.status);
}

async function call(method, url, { body, headers = {}, signal, fetchImpl = fetch, idempotent = false } = {}) {
  const init = { method, credentials: "same-origin", cache: "no-store", signal, headers: { ...headers } };
  if (idempotent) init.headers["Idempotency-Key"] = `tts-engine-${secureUuid()}`;
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetchImpl(url, init);
  if (!response.ok) throw await failure(response);
  if (response.status === 204) return { data: null };
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new TtsEngineError("TTS_ENGINE_RESPONSE_INVALID", response.status);
  }
  if (!isObject(payload) || !isObject(payload.data)) throw new TtsEngineError("TTS_ENGINE_RESPONSE_INVALID", response.status);
  return { data: payload.data };
}

const validView = (item) => isObject(item) && typeof item.slug === "string" && typeof item.label === "string" && typeof item.status === "string"
  && (item.source === "deployment" ? item.engine_id === null : ENGINE_ID.test(item.engine_id ?? ""));
const validId = (engineId) => ENGINE_ID.test(engineId ?? "");

export async function listTtsEngines({ signal, fetchImpl } = {}) {
  const { data } = await call("GET", "/bff/api/admin/tts-engines", { signal, fetchImpl });
  if (!Array.isArray(data.engines) || !data.engines.every(validView)) throw new TtsEngineError("TTS_ENGINE_RESPONSE_INVALID", 200);
  return data.engines;
}

export async function registerTtsEngine({ slug, label, baseUrl, apiKey, providerKind, language, timeoutSeconds, voiceA, voiceB, voiceChoices, signal, fetchImpl }) {
  if (!String(slug ?? "").trim() || !String(label ?? "").trim() || !String(baseUrl ?? "").trim() || !String(voiceA ?? "").trim() || !String(voiceB ?? "").trim()) {
    throw new TtsEngineError("TTS_ENGINE_INPUT_INVALID", 0);
  }
  const body = { slug: String(slug).trim(), label: String(label).trim(), base_url: String(baseUrl).trim(), voices: { A: String(voiceA).trim(), B: String(voiceB).trim() } };
  if (apiKey) body.api_key = apiKey;
  if (providerKind) body.provider_kind = providerKind;
  if (language) body.language = language;
  if (timeoutSeconds !== undefined && timeoutSeconds !== "") body.timeout_seconds = Number(timeoutSeconds);
  if (Array.isArray(voiceChoices) && voiceChoices.length) body.voice_choices = voiceChoices;
  const { data } = await call("POST", "/bff/api/admin/tts-engines", { body, idempotent: true, signal, fetchImpl });
  if (!validView(data)) throw new TtsEngineError("TTS_ENGINE_RESPONSE_INVALID", 201);
  return data;
}

export async function verifyTtsEngine(engineId, { signal, fetchImpl } = {}) {
  if (!validId(engineId)) throw new TtsEngineError("TTS_ENGINE_INPUT_INVALID", 0);
  const { data } = await call("POST", `/bff/api/admin/tts-engines/${engineId}/verify`, { body: {}, signal, fetchImpl });
  if (!validView(data)) throw new TtsEngineError("TTS_ENGINE_RESPONSE_INVALID", 200);
  return data;
}

/** 부분 수정. patch 키: label, baseUrl, apiKey, providerKind, timeoutSeconds, voiceA+voiceB, voiceChoices, isDefault, enabled. */
export async function updateTtsEngine(engineId, version, patch, { signal, fetchImpl } = {}) {
  if (!validId(engineId) || !Number.isSafeInteger(version) || !isObject(patch)) throw new TtsEngineError("TTS_ENGINE_INPUT_INVALID", 0);
  const body = {};
  if (patch.label !== undefined) body.label = String(patch.label).trim();
  if (patch.baseUrl !== undefined) body.base_url = String(patch.baseUrl).trim();
  if (patch.apiKey) body.api_key = patch.apiKey;
  if (patch.providerKind !== undefined) body.provider_kind = patch.providerKind;
  if (patch.timeoutSeconds !== undefined) body.timeout_seconds = Number(patch.timeoutSeconds);
  if (patch.voiceA !== undefined && patch.voiceB !== undefined) body.voices = { A: String(patch.voiceA).trim(), B: String(patch.voiceB).trim() };
  if (Array.isArray(patch.voiceChoices)) body.voice_choices = patch.voiceChoices;
  if (typeof patch.isDefault === "boolean") body.is_default = patch.isDefault;
  if (typeof patch.enabled === "boolean") body.enabled = patch.enabled;
  if (Object.keys(body).length === 0) throw new TtsEngineError("TTS_ENGINE_INPUT_INVALID", 0);
  const { data } = await call("PATCH", `/bff/api/admin/tts-engines/${engineId}`, {
    body, headers: { "If-Match": `"tts-engine:${engineId}:${version}"` }, signal, fetchImpl });
  if (!validView(data)) throw new TtsEngineError("TTS_ENGINE_RESPONSE_INVALID", 200);
  return data;
}

export async function disconnectTtsEngine(engineId, { signal, fetchImpl } = {}) {
  if (!validId(engineId)) throw new TtsEngineError("TTS_ENGINE_INPUT_INVALID", 0);
  await call("DELETE", `/bff/api/admin/tts-engines/${engineId}`, { signal, fetchImpl });
}
