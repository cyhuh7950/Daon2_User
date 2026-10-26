"use client";

import { secureUuid } from "@daon2-user/ui/secure-uuid";

// 지식 연결(MCP Connector) 관리 BFF 클라이언트(WO-M0 T-M0-09). 직접 fetch 금지: fetchImpl 기본 인자, same-origin 쿠키, 쓰기는 Idempotency-Key.
// 응답 오류는 안전한 코드만 노출한다(원문 메시지·서버 주소 오류는 쓰지 않는다).

const CONNECTOR_ID = /^kc-[0-9a-f]{32}$/u;
const ERROR_CODE = /^[A-Z][A-Z0-9_]{2,63}$/u;
export const CONNECTOR_KINDS = Object.freeze({
  daon2_rag: { label: "Daon2-RAG", tools: ["search_document_evidence", "get_document_evidence", "list_documents", "get_document_outline", "read_document_section", "get_document_version_status"] },
  daon2: { label: "Daon2", tools: ["ontology_search_concepts", "ontology_get_concept", "ruleset_list", "ruleset_get", "ruleset_evaluate", "approved_knowledge_search"] },
  law: { label: "법령", tools: ["search_law", "get_law_text"] },
});

const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

export class KnowledgeConnectorError extends Error {
  constructor(code, status) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

async function failure(response) {
  let code = "CONNECTOR_REQUEST_FAILED";
  try {
    const payload = await response.json();
    if (typeof payload?.error?.code === "string" && ERROR_CODE.test(payload.error.code)) code = payload.error.code;
  } catch {
    // 본문이 없으면 일반 코드를 쓴다.
  }
  return new KnowledgeConnectorError(code, response.status);
}

async function call(method, url, { body, headers = {}, signal, fetchImpl = fetch, idempotent = false } = {}) {
  const init = { method, credentials: "same-origin", cache: "no-store", signal, headers: { ...headers } };
  if (idempotent) init.headers["Idempotency-Key"] = `connector-${secureUuid()}`;
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetchImpl(url, init);
  if (!response.ok) throw await failure(response);
  if (response.status === 204) return { data: null, etag: null };
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new KnowledgeConnectorError("CONNECTOR_RESPONSE_INVALID", response.status);
  }
  if (!isObject(payload) || !isObject(payload.data)) throw new KnowledgeConnectorError("CONNECTOR_RESPONSE_INVALID", response.status);
  return { data: payload.data, etag: response.headers?.get?.("etag") ?? null };
}

const validView = (item) => isObject(item) && CONNECTOR_ID.test(item.connector_id ?? "") && typeof item.name === "string" && typeof item.kind === "string" && typeof item.status === "string";

export async function listKnowledgeConnectors({ signal, fetchImpl } = {}) {
  const { data } = await call("GET", "/bff/api/knowledge-connectors", { signal, fetchImpl });
  if (!Array.isArray(data.connectors) || !data.connectors.every(validView)) throw new KnowledgeConnectorError("CONNECTOR_RESPONSE_INVALID", 200);
  return data.connectors;
}

export async function registerKnowledgeConnector({ kind, name, endpointUrl, token, allowedTools, allowedScopes, signal, fetchImpl }) {
  if (!Object.hasOwn(CONNECTOR_KINDS, kind) || !String(name ?? "").trim() || !String(endpointUrl ?? "").trim()) throw new KnowledgeConnectorError("CONNECTOR_INPUT_INVALID", 0);
  const body = { kind, name: String(name).trim(), endpoint_url: String(endpointUrl).trim() };
  if (token) body.token = token;
  if (Array.isArray(allowedTools) && allowedTools.length) body.allowed_tools = allowedTools;
  if (Array.isArray(allowedScopes) && allowedScopes.length) body.allowed_scopes = allowedScopes.map((scope) => ({ project_id: scope.projectId, work_package_id: scope.workPackageId }));
  const { data } = await call("POST", "/bff/api/admin/knowledge-connectors", { body, idempotent: true, signal, fetchImpl });
  if (!validView(data)) throw new KnowledgeConnectorError("CONNECTOR_RESPONSE_INVALID", 201);
  return data;
}

export async function verifyKnowledgeConnector(connectorId, { signal, fetchImpl } = {}) {
  if (!CONNECTOR_ID.test(connectorId ?? "")) throw new KnowledgeConnectorError("CONNECTOR_INPUT_INVALID", 0);
  const { data } = await call("POST", `/bff/api/admin/knowledge-connectors/${connectorId}/verify`, { body: {}, signal, fetchImpl });
  if (!isObject(data) || typeof data.status !== "string") throw new KnowledgeConnectorError("CONNECTOR_RESPONSE_INVALID", 200);
  return data;
}

export async function updateKnowledgeConnectorTools(connectorId, version, allowedTools, { signal, fetchImpl } = {}) {
  if (!CONNECTOR_ID.test(connectorId ?? "") || !Number.isSafeInteger(version)) throw new KnowledgeConnectorError("CONNECTOR_INPUT_INVALID", 0);
  const { data } = await call("PATCH", `/bff/api/admin/knowledge-connectors/${connectorId}`, {
    body: { allowed_tools: allowedTools }, headers: { "If-Match": `"knowledge-connector:${connectorId}:${version}"` }, signal, fetchImpl });
  if (!validView(data)) throw new KnowledgeConnectorError("CONNECTOR_RESPONSE_INVALID", 200);
  return data;
}

const LIMIT_KEYS = ["max_concurrent", "timeout_seconds", "max_response_bytes", "calls_per_minute"];

/** Connector별 호출 한도 저장(F4-02). limits는 네 키 중 일부이며 빈 객체면 서버 기본값으로 돌아간다. */
export async function updateKnowledgeConnectorLimits(connectorId, version, limits, { signal, fetchImpl } = {}) {
  if (!CONNECTOR_ID.test(connectorId ?? "") || !Number.isSafeInteger(version) || !isObject(limits)
      || Object.entries(limits).some(([key, value]) => !LIMIT_KEYS.includes(key) || !Number.isSafeInteger(value))) throw new KnowledgeConnectorError("CONNECTOR_INPUT_INVALID", 0);
  const { data } = await call("PATCH", `/bff/api/admin/knowledge-connectors/${connectorId}`, {
    body: { limits }, headers: { "If-Match": `"knowledge-connector:${connectorId}:${version}"` }, signal, fetchImpl });
  if (!validView(data)) throw new KnowledgeConnectorError("CONNECTOR_RESPONSE_INVALID", 200);
  return data;
}

export async function disconnectKnowledgeConnector(connectorId, { signal, fetchImpl } = {}) {
  if (!CONNECTOR_ID.test(connectorId ?? "")) throw new KnowledgeConnectorError("CONNECTOR_INPUT_INVALID", 0);
  await call("DELETE", `/bff/api/admin/knowledge-connectors/${connectorId}`, { signal, fetchImpl });
}
