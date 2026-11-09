// 문서명은 승인 지식 인용에만 온다. packages/ui/src/answer-presentation.js와 같은 규칙이다.
const CITATION_KEYS = Object.freeze(["citation_id", "source_id", "source_version_id", "evidence_span_id", "page", "origin", "context_item_id", "locator"]);

export function citationKeys(value) {
  const named = value && typeof value === "object" && value.origin === "mcp_daon_rag" && "document_name" in value;
  return named ? [...CITATION_KEYS, "document_name"] : CITATION_KEYS;
}

export function validCitationDocumentName(value) {
  return !("document_name" in value) || (typeof value.document_name === "string" && value.document_name.length >= 1 && value.document_name.length <= 1024);
}
