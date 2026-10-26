// 조직 템플릿 편집기의 "예시 채우기" 본문. 내장 템플릿과 같은 형식이며 필요한 부분만 고쳐 쓴다.
export const SAMPLE_TEMPLATE = Object.freeze({
  template_id: "org_sample_proposal",
  title: "조직 제안서 템플릿",
  version: 1,
  description: "제안요청서(RFP)를 읽고 조직 양식에 맞춘 제안서 초안을 만든다.",
  keywords: ["제안서"],
  analysis: "rfp_requirements",
  style: "proposal",
  inputs: [
    { key: "rfp_document", question: "제안요청서(RFP)로 사용할 소스를 선택해 주세요.", kind: "source_ref", required: true },
    { key: "company_notes", question: "회사 소개나 강조할 점을 적어 주세요(없으면 건너뛰기).", kind: "text", required: false },
  ],
  knowledge: [],
  sections: [
    { key: "understanding", title: "1. 사업의 이해", guidance: "제안요청서의 배경과 목적을 정리한다.", knowledge_hints: [] },
    { key: "approach", title: "2. 수행 방안", guidance: "요구사항별 수행 방법을 정리한다.", knowledge_hints: [] },
  ],
  checks: [],
  output: { formats: ["docx"], default: ["docx"] },
});
