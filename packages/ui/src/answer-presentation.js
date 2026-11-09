// 답변 표시 규칙. 문서명은 승인 지식 인용에만 온다.
export const CITATION_KEYS = Object.freeze(["citation_id", "source_id", "source_version_id", "evidence_span_id", "page", "origin", "context_item_id", "locator"]);
const APPROVED_KNOWLEDGE_ORIGIN = "mcp_daon_rag";

export function citationKeys(value) {
  const named = value && typeof value === "object" && value.origin === APPROVED_KNOWLEDGE_ORIGIN && "document_name" in value;
  return named ? [...CITATION_KEYS, "document_name"] : CITATION_KEYS;
}

export function validCitationDocumentName(value) {
  return !("document_name" in value) || (typeof value.document_name === "string" && value.document_name.length >= 1 && value.document_name.length <= 1024);
}

export function approvedKnowledgeCitationLabel(citation) {
  return `${citation.document_name ?? "승인 지식"} ${citation.page}쪽`;
}

export function usesApprovedKnowledge(answer) {
  return Boolean(answer?.citations?.some((citation) => citation.origin === APPROVED_KNOWLEDGE_ORIGIN));
}

// 한글 조합 중의 Enter는 글자 확정이므로 전송하지 않는다.
export function shouldSubmitOnEnter(event) {
  const native = event.nativeEvent ?? event;
  return event.key === "Enter" && !event.shiftKey && !native.isComposing && native.keyCode !== 229;
}

function segments(text) {
  return text.split(/\*\*(?=\S)(.+?)(?<=\S)\*\*/u)
    .map((part, index) => ({ text: part, bold: index % 2 === 1 }))
    .filter((part) => part.text.length > 0);
}

export function parseAnswerBlocks(text) {
  const blocks = [];
  for (const line of text.split(/\r?\n/u)) {
    const content = line.trim();
    if (!content) continue;
    const item = content.match(/^[-*•]\s+(.+)$/u);
    if (item) {
      const last = blocks[blocks.length - 1];
      if (last?.type === "list") last.items.push(segments(item[1]));
      else blocks.push({ type: "list", items: [segments(item[1])] });
      continue;
    }
    const heading = content.match(/^#{1,6}\s+(.+)$/u);
    blocks.push({ type: "paragraph", segments: heading ? [{ text: heading[1].replaceAll("**", ""), bold: true }] : segments(content) });
  }
  return blocks;
}
