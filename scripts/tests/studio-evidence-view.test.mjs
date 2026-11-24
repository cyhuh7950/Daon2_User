import assert from "node:assert/strict";
import test from "node:test";

import { evidenceExcerptView } from "../../packages/ui/src/studio-evidence-view.js";

// N1-B09 실서버: 심층 조사 보고서의 근거를 열면 snapshot JSON이 그대로 보였다.
test("조사 근거 snapshot은 문서 이름·출처 표시·발췌만 보여 준다", () => {
  const view = evidenceExcerptView({ kind: "excerpt", origin: "mcp_daon_rag", snapshot: {
    kind: "document", name: "정성제안서.pdf", tool: "search_document_evidence", excerpt: "제안서 평가 항목",
    project_id: "p-1", document_id: "d-1", candidate_id: "doc-1", origin_label: "문서 근거 · 제안서 작업" } });
  assert.deepEqual(view, { title: "정성제안서.pdf", label: "문서 근거 · 제안서 작업", text: "제안서 평가 항목" });
});

test("발췌가 없는 snapshot은 내부 식별자를 노출하지 않는다", () => {
  const view = evidenceExcerptView({ kind: "excerpt", snapshot: { name: "승인 지식 묶음", project_id: "p-1" } });
  assert.deepEqual(view, { title: "승인 지식 묶음", label: "", text: "" });
});

test("원문 발췌(text)가 있으면 파일 이름과 함께 그대로 쓴다", () => {
  assert.deepEqual(evidenceExcerptView({ kind: "excerpt", filename: "a.txt", text: "본문" }), { title: "a.txt", label: "", text: "본문" });
});
