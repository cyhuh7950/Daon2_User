import { createStudioV2Adapter } from "../../web/lib/studio-v2-adapter.js";
import { askGroundedQuestion, authorizeGroundedQuestion, citationContentUrl } from "../../web/lib/question-answering-api.js";
import { downloadManualAsset, getManualManifest, readManualDocument } from "../../web/lib/manual-api.js";

const MAX_IPC_BYTES = 32 * 1024 * 1024 + 16_388;

function unpackResponse(value) {
  // The CSP blocks Tauri's fetch-based IPC. Its postMessage fallback returns an array of bytes.
  const buffer = value instanceof ArrayBuffer ? value
    : Array.isArray(value) && value.length <= MAX_IPC_BYTES
      && value.every((byte) => Number.isInteger(byte) && byte >= 0 && byte <= 255)
      ? Uint8Array.from(value).buffer : null;
  if (!buffer || buffer.byteLength < 4 || buffer.byteLength > MAX_IPC_BYTES) throw new Error("WORKSPACE_RESPONSE_REJECTED");
  const metadataLength = new DataView(buffer).getUint32(0, true);
  const offset = 4 + metadataLength;
  if (metadataLength > 16_384 || offset > buffer.byteLength) throw new Error("WORKSPACE_RESPONSE_REJECTED");
  const [status, headers] = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(buffer, 4, metadataLength)));
  return new Response(status === 204 ? null : new Uint8Array(buffer, offset), { status, headers });
}

async function invokeResponse(invoke, command, parameters, signal) {
  signal?.throwIfAborted();
  try {
    const value = await invoke(command, parameters);
    signal?.throwIfAborted();
    return unpackResponse(value);
  } catch (error) {
    signal?.throwIfAborted();
    if (typeof error === "string" && /^[A-Z][A-Z0-9_]{2,63}$/u.test(error)) throw new Error(error);
    throw new Error("WORKSPACE_RESPONSE_REJECTED");
  }
}

export function createWindowsOnlineFeatures(workspaceId, notebookId, invoke) {
  function fetchImpl(url, { method = "GET", headers, body = null, signal } = {}) {
    if (typeof url !== "string" || !url.startsWith("/bff/api/")) throw new Error("INVALID_REQUEST");
    const requestHeaders = new Headers(headers);
    requestHeaders.delete("content-type");
    return invokeResponse(invoke, "native_notebook_request", {
      workspaceId, notebookId,
      request: { method, path: "/api/v1/" + url.slice("/bff/api/".length), headers: [...requestHeaders], body },
    }, signal);
  }

  const manualFetch = createWindowsManualFetch(invoke);
  const citationUrl = (citation) => citationContentUrl(workspaceId, citation, { notebookId });
  const citationResponse = (citation, { signal } = {}) => fetchImpl(citationUrl(citation).split("#", 1)[0], { signal });
  return {
    studioV2: createStudioV2Adapter(workspaceId, notebookId, { fetchImpl }),
    askQuestion: (input, options) => askGroundedQuestion(workspaceId, { ...input, notebookId }, { ...options, fetchImpl }),
    authorizeQuestion: (input, options) => authorizeGroundedQuestion(workspaceId, { ...input, notebookId }, { ...options, fetchImpl }),
    citationUrl,
    citationResponse,
    async citationContent(citation, options) {
      const response = await citationResponse(citation, options);
      const content_type = response.headers.get("content-type")?.split(";", 1)[0];
      if (!response.ok || !["application/pdf", "text/plain"].includes(content_type)) throw new Error("CITATION_CONTENT_UNAVAILABLE");
      return {
        content_type,
        page: Number(response.headers.get("x-citation-page")),
        bytes: [...new Uint8Array(await response.arrayBuffer())],
      };
    },
    getManualManifest: (options) => getManualManifest({ ...options, fetchImpl: manualFetch }),
    readManual: (id, manifest, options) => readManualDocument(id, { ...options, manifest, fetchImpl: manualFetch }),
    downloadManual: (id, format, manifest, options) => downloadManualAsset(id, format, { ...options, manifest, fetchImpl: manualFetch }),
  };
}

export function createWindowsManualFetch(invoke) {
  return function manualFetch(url, { signal } = {}) {
    if (typeof url !== "string" || !url.startsWith("/manual/")) throw new Error("MANUAL_DOCUMENT_NOT_FOUND");
    return invokeResponse(invoke, "native_read_manual", { asset: url.slice("/manual/".length) }, signal);
  };
}
