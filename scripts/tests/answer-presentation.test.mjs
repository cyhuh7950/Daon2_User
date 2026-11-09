import assert from "node:assert/strict";
import test from "node:test";

import {
  approvedKnowledgeCitationLabel,
  parseAnswerBlocks,
  shouldSubmitOnEnter,
  usesApprovedKnowledge,
} from "../../packages/ui/src/answer-presentation.js";

const plain = (text) => [{ text, bold: false }];

test("답변의 줄바꿈은 문단으로 나뉘고 빈 줄은 사라진다", () => {
  assert.deepEqual(parseAnswerBlocks("첫 줄\n\n둘째 줄"), [
    { type: "paragraph", segments: plain("첫 줄") },
    { type: "paragraph", segments: plain("둘째 줄") },
  ]);
});

test("이어진 목록 줄은 하나의 목록이 된다", () => {
  assert.deepEqual(parseAnswerBlocks("안내\n- 하나\n* 둘\n끝"), [
    { type: "paragraph", segments: plain("안내") },
    { type: "list", items: [plain("하나"), plain("둘")] },
    { type: "paragraph", segments: plain("끝") },
  ]);
});

test("굵은 글씨 기호는 표시로 바뀌고 짝이 안 맞으면 글자로 남는다", () => {
  assert.deepEqual(parseAnswerBlocks("앞 **굵게** 뒤")[0].segments, [
    { text: "앞 ", bold: false }, { text: "굵게", bold: true }, { text: " 뒤", bold: false },
  ]);
  assert.deepEqual(parseAnswerBlocks("2**3 은 8")[0].segments, plain("2**3 은 8"));
});

test("목록 안의 굵은 글씨와 제목 기호를 처리한다", () => {
  assert.deepEqual(parseAnswerBlocks("- **항목**: 설명")[0].items[0], [{ text: "항목", bold: true }, { text: ": 설명", bold: false }]);
  assert.deepEqual(parseAnswerBlocks("### 제목")[0].segments, [{ text: "제목", bold: true }]);
});

test("승인 지식 인용은 문서명과 쪽수로 표시하고 문서명이 없으면 쪽수만 쓴다", () => {
  assert.equal(approvedKnowledgeCitationLabel({ document_name: "제안요청서.pdf", page: 12 }), "제안요청서.pdf 12쪽");
  assert.equal(approvedKnowledgeCitationLabel({ page: 3 }), "승인 지식 3쪽");
  assert.equal(approvedKnowledgeCitationLabel({ document_name: "온톨로지 · 보험금 지급", page: 1 }), "온톨로지 · 보험금 지급");
  assert.equal(approvedKnowledgeCitationLabel({ document_name: "규칙 · 제외기간", page: 1 }), "규칙 · 제외기간");
});

test("승인 지식 인용이 있는 답변만 승인 지식 사용으로 본다", () => {
  assert.equal(usesApprovedKnowledge({ citations: [{ origin: "mcp_daon_rag" }] }), true);
  assert.equal(usesApprovedKnowledge({ citations: [{ origin: "raw_source" }] }), false);
  assert.equal(usesApprovedKnowledge({ citations: [] }), false);
  assert.equal(usesApprovedKnowledge(null), false);
});

test("Enter만 전송하고 Shift+Enter와 한글 조합 중 Enter는 전송하지 않는다", () => {
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, nativeEvent: { isComposing: false, keyCode: 13 } }), true);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: true, nativeEvent: { isComposing: false, keyCode: 13 } }), false);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, nativeEvent: { isComposing: true, keyCode: 13 } }), false);
  assert.equal(shouldSubmitOnEnter({ key: "Enter", shiftKey: false, nativeEvent: { isComposing: false, keyCode: 229 } }), false);
  assert.equal(shouldSubmitOnEnter({ key: "a", shiftKey: false, nativeEvent: { isComposing: false, keyCode: 65 } }), false);
});
