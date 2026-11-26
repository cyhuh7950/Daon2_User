"""기존 제안서와 새 작성 목적을 받는 내장 템플릿."""

from .rfp_response_proposal import TEMPLATE as RFP_TEMPLATE

TEMPLATE = {
    **RFP_TEMPLATE,
    "template_id": "reference_proposal_draft",
    "title": "기존 제안서를 바탕으로 작성",
    "description": "노트북의 기존 제안서와 새 작성 목적을 바탕으로 제안서 초안을 만듭니다.",
    "keywords": [],
    "analysis": "base_document",
    "inputs": [
        {"key": "reference_proposals", "question": "기준이 될 기존 제안서를 선택해 주세요.", "kind": "source_ref", "required": True},
        {"key": "purpose", "question": "새 제안서의 대상과 작성 목적을 적어 주세요.", "kind": "text", "required": True},
        *[item for item in RFP_TEMPLATE["inputs"] if item["key"] in {"proposer_profile", "price_schedule"}],
    ],
    "knowledge": [{"tool": "ontology_search_concepts", "required": False}],
    "checks": [check for check in RFP_TEMPLATE["checks"] if check["kind"] != "derived"],
    "sections": [
        {**section, "guidance": "새 작성 목적에 맞춰 사업 배경과 범위를 정리한다."} if section["key"] == "understanding"
        else {**section, "guidance": "새 사업에 적용할 수행 방법과 단계, 산출물을 설명한다."} if section["key"] == "approach"
        else section
        for section in RFP_TEMPLATE["sections"]
    ],
}
