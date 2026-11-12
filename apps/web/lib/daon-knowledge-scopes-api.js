"use client";

// Daon 승인 지식 목록과 노트북별 업무 패키지 선택 BFF 클라이언트(WO-K2). 오류는 안전한 코드만 전달한다.

const ERROR_CODE = /^[A-Z][A-Z0-9_]{2,63}$/u;
const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

export class DaonKnowledgeScopeError extends Error {
  constructor(code, status) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

async function call(method, url, { body, signal, fetchImpl = fetch } = {}) {
  const init = { method, credentials: "same-origin", cache: "no-store", signal, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetchImpl(url, init);
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // 본문이 없으면 아래에서 일반 코드로 처리한다.
  }
  if (!response.ok) {
    const code = payload?.error?.code;
    throw new DaonKnowledgeScopeError(typeof code === "string" && ERROR_CODE.test(code) ? code : "KNOWLEDGE_SCOPE_REQUEST_FAILED", response.status);
  }
  if (!isObject(payload) || !isObject(payload.data)) throw new DaonKnowledgeScopeError("KNOWLEDGE_SCOPE_RESPONSE_INVALID", response.status);
  return payload.data;
}

const workspacePath = (workspaceId) => `/bff/api/workspaces/${encodeURIComponent(workspaceId)}`;
const selectionPath = (workspaceId, notebookId) => `${workspacePath(workspaceId)}/notebooks/${encodeURIComponent(notebookId)}/knowledge-scopes`;

export async function listDaonKnowledgeScopes(workspaceId, options = {}) {
  const data = await call("GET", `${workspacePath(workspaceId)}/daon-knowledge-scopes`, options);
  if (!Array.isArray(data.projects)) throw new DaonKnowledgeScopeError("KNOWLEDGE_SCOPE_RESPONSE_INVALID", 200);
  return data;
}

const validSelection = (data) => {
  if (!Array.isArray(data.items)) throw new DaonKnowledgeScopeError("KNOWLEDGE_SCOPE_RESPONSE_INVALID", 200);
  return data;
};

export async function getNotebookKnowledgeScopes(workspaceId, notebookId, options = {}) {
  return validSelection(await call("GET", selectionPath(workspaceId, notebookId), options));
}

// WO-K6: 선택한 업무 패키지별로 쓸 수 있는 지식 종류(문서·온톨로지·규칙·승인 자산·GraphRAG).
export async function getNotebookKnowledgeStatus(workspaceId, notebookId, options = {}) {
  return validSelection(await call("GET", `${selectionPath(workspaceId, notebookId)}/status`, options));
}

export async function saveNotebookKnowledgeScopes(workspaceId, notebookId, items, options = {}) {
  return validSelection(await call("PUT", selectionPath(workspaceId, notebookId), { ...options, body: { items } }));
}
