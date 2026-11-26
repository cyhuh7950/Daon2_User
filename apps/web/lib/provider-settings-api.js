const JSON_HEADERS = Object.freeze({ "Content-Type": "application/json" });

async function request(fetchImpl, path, { method = "GET", body, headers = {} } = {}) {
  const response = await fetchImpl(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? headers : { ...JSON_HEADERS, ...headers },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const payload = await response.json().catch(() => ({
    error: { code: "RESOURCE_UNAVAILABLE", trace_id: response.headers.get("x-trace-id") }
  }));
  if (!response.ok) {
    const error = new Error(payload?.error?.code ?? "RESOURCE_UNAVAILABLE");
    error.code = payload?.error?.code ?? "RESOURCE_UNAVAILABLE";
    error.traceId = payload?.error?.trace_id ?? response.headers.get("x-trace-id");
    error.status = response.status;
    error.details = payload?.error?.details && typeof payload.error.details === "object" ? payload.error.details : null;
    throw error;
  }
  return { payload, etag: response.headers.get("etag") };
}

export function createProviderSettingsApi(fetchImpl = (...args) => fetch(...args)) {
  const call = (path, options) => request(fetchImpl, path, options);
  return Object.freeze({
  getSession() {
    return call("/bff/api/session");
  },
  listConnections() {
    return call("/bff/api/admin/provider-connections");
  },
  previewModels(input) {
    return call("/bff/api/admin/provider-connections/model-preview", {
      method: "POST", body: input,
    });
  },
  // 모델이 추론 수준 요청을 받아 주는지 시험하고 받아 준 수준을 확인으로 저장한다.
  probeReasoning(input) {
    return call("/bff/api/admin/model-reasoning/probe", { method: "POST", body: input });
  },
  // 연결 시험만 한다(저장하지 않는다).
  testConnection(input) {
    return call("/bff/api/admin/provider-connections/test", { method: "POST", body: input });
  },
  getHealthSettings() {
    return call("/bff/api/admin/provider-health-settings");
  },
  saveHealthSettings(input) {
    return call("/bff/api/admin/provider-health-settings", {
      method: "PATCH", body: input,
    });
  },
  listUserCredentials() {
    return call("/bff/api/provider-credentials");
  },
  replaceUserCredential(connectionId, input) {
    return call(`/bff/api/provider-credentials/${encodeURIComponent(connectionId)}`, {
      method: "PUT", body: input,
    });
  },
  deleteUserCredential(connectionId, input) {
    return call(`/bff/api/provider-credentials/${encodeURIComponent(connectionId)}`, {
      method: "DELETE", body: input,
    });
  },
  createConnection(input, idempotencyKey) {
    return call("/bff/api/admin/provider-connections", {
      method: "POST", body: input, headers: { "Idempotency-Key": idempotencyKey }
    });
  },
  updateConnection(connectionId, input, idempotencyKey) {
    return call(`/bff/api/admin/provider-connections/${encodeURIComponent(connectionId)}`, {
      method: "PUT", body: input, headers: { "Idempotency-Key": idempotencyKey }
    });
  },
  replaceCredential(connectionId, input, idempotencyKey) {
    return call(`/bff/api/admin/provider-connections/${encodeURIComponent(connectionId)}/credential`, {
      method: "POST", body: input, headers: { "Idempotency-Key": idempotencyKey }
    });
  },
  deleteCredential(connectionId, input, idempotencyKey) {
    return call(`/bff/api/admin/provider-connections/${encodeURIComponent(connectionId)}/credential`, {
      method: "DELETE", body: input, headers: { "Idempotency-Key": idempotencyKey }
    });
  },
  deleteConnection(connectionId, input, idempotencyKey) {
    return call(`/bff/api/admin/provider-connections/${encodeURIComponent(connectionId)}`, {
      method: "DELETE", body: input, headers: { "Idempotency-Key": idempotencyKey }
    });
  },
  refreshCatalog(connectionId, input, idempotencyKey) {
    return call(`/bff/api/admin/provider-catalog/${encodeURIComponent(connectionId)}/refresh`, {
      method: "POST", body: input, headers: { "Idempotency-Key": idempotencyKey }
    });
  },
  correctCapabilities(connectionId, modelId, input, idempotencyKey) {
    return call(`/bff/api/admin/provider-models/${encodeURIComponent(connectionId)}/${encodeURIComponent(modelId)}/capabilities`, {
      method: "PATCH", body: input, headers: { "Idempotency-Key": idempotencyKey }
    });
  },
  getModelDefaults(workspaceId) {
    return call(`/bff/api/workspaces/${encodeURIComponent(workspaceId)}/model-defaults`);
  },
  saveModelDefault(workspaceId, input, etag, idempotencyKey) {
    return call(`/bff/api/workspaces/${encodeURIComponent(workspaceId)}/model-defaults`, {
      method: "PATCH",
      body: input,
      headers: { "If-Match": etag, "Idempotency-Key": idempotencyKey }
    });
  }
});
}

export const providerSettingsApi = createProviderSettingsApi();
