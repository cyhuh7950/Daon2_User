"""내장 작성 템플릿 `insurance_terms_draft`(보험 약관 초안). 기준 약관 + 변경점 → 변경 표시가 붙은 약관 초안."""

TEMPLATE = {
    "template_id": "insurance_terms_draft",
    "title": "보험 약관 초안",
    "version": 1,
    "description": "기준 약관을 바탕으로 변경점을 반영한 약관 초안을 만들고, 기준 대비 유지·수정·신규·삭제 제안을 표시한다.",
    "keywords": ["약관", "보험 약관", "보험약관", "보험 상품"],
    "analysis": "base_document",
    "style": "terms",
    "inputs": [
        {"key": "product_type", "question": "상품 유형을 선택해 주세요.", "kind": "choice", "required": True,
         "choices": ["실손의료보험", "종신보험", "자동차보험", "기타"]},
        {"key": "base_terms", "question": "기준이 될 기존 약관을 선택해 주세요(지식 서버의 문서).", "kind": "knowledge_ref", "required": True, "document_type": "insurance_terms"},
        {"key": "changes", "question": "기준 약관에서 바꾸려는 점을 적어 주세요(없으면 건너뛰기).", "kind": "text", "required": False},
    ],
    "knowledge": [
        {"tool": "get_document_outline", "per": "base_terms", "required": True},
        {"tool": "read_document_section", "per": "base_terms", "required": True},
        {"tool": "ontology_search_concepts", "required": False},
        {"tool": "ruleset_get", "required": False},
    ],
    "sections": [
        {"key": "general", "title": "제1장 총칙", "guidance": "약관의 목적과 용어의 정의를 정리한다.", "knowledge_hints": ["총칙"]},
        {"key": "coverage", "title": "제2장 보장내용", "guidance": "보장 범위와 한도를 정리한다.", "knowledge_hints": ["보장"]},
        {"key": "payment", "title": "제3장 보험금의 지급", "guidance": "지급사유, 청구 절차, 지급 시기를 정리한다.", "knowledge_hints": ["지급"]},
        {"key": "exclusion", "title": "제4장 면책", "guidance": "보험금을 지급하지 않는 사유와 면책 기간을 정리한다.", "knowledge_hints": ["면책"]},
        {"key": "premium", "title": "제5장 보험료", "guidance": "보험료 납입과 연체 처리를 정리한다.", "knowledge_hints": ["보험료"]},
        {"key": "termination", "title": "제6장 계약의 해지", "guidance": "해지 사유와 해지환급금을 정리한다.", "knowledge_hints": ["해지"]},
        {"key": "dispute", "title": "제7장 분쟁의 해결", "guidance": "분쟁 해결 방법과 관할을 정리한다.", "knowledge_hints": ["분쟁"]},
    ],
    "checks": [
        {"id": "terms_required_clauses", "kind": "ruleset", "ruleset_id": "rs-terms-clauses", "tool": "ruleset_evaluate", "title": "약관 필수 조항 점검"},
    ],
    "output": {"formats": ["docx"], "default": ["docx"]},
}
