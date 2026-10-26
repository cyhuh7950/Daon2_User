"""내장 작성 템플릿 `contract_draft`(계약서 초안). 기준 계약서 + 당사자·기간·금액 → 계약서 초안과 법령 대조표."""

TEMPLATE = {
    "template_id": "contract_draft",
    "title": "계약서 초안",
    "version": 1,
    "description": "기준 계약서를 바탕으로 당사자·기간·금액을 반영한 계약서 초안을 만들고, 조항별 관련 법령 조문을 대조한다(법률 자문이 아닙니다).",
    "keywords": ["계약서", "계약", "용역계약", "공급계약"],
    "analysis": "base_document",
    "style": "contract",
    "inputs": [
        {"key": "contract_type", "question": "계약 유형을 선택해 주세요.", "kind": "choice", "required": True,
         "choices": ["용역계약", "물품공급계약", "라이선스계약", "기타"]},
        {"key": "base_contract", "question": "기준이 될 기존 계약서를 선택해 주세요(지식 서버의 문서).", "kind": "knowledge_ref", "required": True, "document_type": "contract"},
        {"key": "parties", "question": "당사자(갑·을)와 대표자를 적어 주세요(없으면 건너뛰기).", "kind": "text", "required": False},
        {"key": "period_amount", "question": "계약 기간과 금액을 적어 주세요(없으면 건너뛰기).", "kind": "text", "required": False},
    ],
    "knowledge": [
        {"tool": "get_document_outline", "per": "base_contract", "required": True},
        {"tool": "read_document_section", "per": "base_contract", "required": True},
        {"tool": "search_law", "required": False},
        {"tool": "get_law_text", "required": False},
        {"tool": "ruleset_get", "required": False},
    ],
    "sections": [
        {"key": "purpose", "title": "제1조(목적)", "guidance": "계약의 목적과 대상을 정리한다.", "knowledge_hints": ["목적"]},
        {"key": "period", "title": "제2조(계약기간)", "guidance": "계약 기간을 정리한다. 입력이 없으면 [작성 필요]로 표시한다.", "knowledge_hints": ["계약기간", "기간"]},
        {"key": "price", "title": "제3조(대금)", "guidance": "계약 대금을 정리한다. 금액 입력이 없으면 [작성 필요]로 표시한다.", "knowledge_hints": ["대금"]},
        {"key": "confidentiality", "title": "제4조(비밀유지)", "guidance": "비밀유지 의무를 정리한다.", "knowledge_hints": ["비밀"]},
        {"key": "liability", "title": "제5조(손해배상)", "guidance": "손해배상 책임을 정리한다.", "knowledge_hints": ["손해배상"]},
        {"key": "termination", "title": "제6조(계약의 해지)", "guidance": "해지 사유와 절차를 정리한다.", "knowledge_hints": ["해지"]},
        {"key": "dispute", "title": "제7조(분쟁의 해결)", "guidance": "분쟁 해결 방법과 관할을 정리한다.", "knowledge_hints": ["분쟁"]},
    ],
    "checks": [
        {"id": "contract_required_clauses", "kind": "ruleset", "ruleset_id": "rs-contract-clauses", "tool": "ruleset_evaluate", "title": "계약서 필수 조항 점검"},
        {"id": "law_crosscheck", "kind": "law", "title": "법령 대조표"},
    ],
    "output": {"formats": ["docx"], "default": ["docx"]},
}
