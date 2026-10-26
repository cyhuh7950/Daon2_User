"""합성 코퍼스(실제 문서 금지). 결정적으로 생성한다 — 같은 입력이면 항상 같은 문서·블록 ID가 나온다. WO-M0 T-M0-03."""

from __future__ import annotations

import hashlib
from typing import Any

COLLECTIONS = (
    {"project_id": "proj-alpha", "work_package_id": "wp-terms"},
    {"project_id": "proj-alpha", "work_package_id": "wp-proposals"},
    {"project_id": "proj-beta", "work_package_id": "wp-contracts"},
)
FORBIDDEN_COLLECTION = {"project_id": "proj-secret", "work_package_id": "wp-hidden"}


def _id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{hashlib.sha256('|'.join(parts).encode()).hexdigest()[:12]}"


def _doc(kind: str, slug: str, title: str, sections: list[tuple[str, list[str]]], collection: dict[str, str]) -> dict[str, Any]:
    document_id = _id("doc", kind, slug)
    version_id = _id("ver", document_id, "1")
    run_id = _id("run", version_id)
    blocks: list[dict[str, Any]] = []
    outline: list[dict[str, Any]] = []
    page = 1
    for index, (heading, paragraphs) in enumerate(sections, 1):
        node_blocks = []
        head_id = _id("blk", document_id, str(index), "h")
        blocks.append({"block_id": head_id, "page": page, "text": heading})
        node_blocks.append(head_id)
        for p_index, text in enumerate(paragraphs, 1):
            block_id = _id("blk", document_id, str(index), str(p_index))
            blocks.append({"block_id": block_id, "page": page, "text": text})
            node_blocks.append(block_id)
        outline.append({"node_id": _id("node", document_id, str(index)), "kind": "section", "title": heading, "level": 1,
                        "page_from": page, "page_to": page, "block_ids": node_blocks, "children": []})
        if index % 2 == 0:
            page += 1
    return {"document_id": document_id, "title": title, "document_type": kind, "version_id": version_id, "run_id": run_id,
            "blocks": blocks, "outline": outline, **collection}


def _terms() -> list[dict[str, Any]]:
    c = COLLECTIONS[0]
    kinds = (("실손의료보험", "의료비", "입원·통원 의료비"), ("종신보험", "사망보험금", "피보험자의 사망"), ("자동차보험", "대인배상", "자동차 사고"))
    docs = []
    for slug, (name, coverage, event) in zip(("indemnity", "whole-life", "auto"), kinds):
        sections = [
            ("제1장 총칙", [f"제1조(목적) 이 약관은 {name}의 계약 체결과 이행에 필요한 사항을 정한다.", "제2조(용어의 정의) 이 약관에서 계약자는 보험료를 납입하는 자를 말한다."]),
            ("제2장 보장내용", [f"제3조(보장 범위) 회사는 {event}으로 {coverage}가 발생한 경우 이 약관에 따라 보상한다.", f"제4조(보장 한도) {coverage}의 지급 한도는 사고당 100,000,000원이다."]),
            ("제3장 보험금의 지급", ["제5조(지급사유) 보험금 지급사유가 발생하면 계약자는 즉시 회사에 통지해야 한다.", "제6조(지급 시기) 회사는 청구서류를 접수한 날부터 3일 이내에 보험금을 지급한다."]),
            ("제4장 면책", ["제7조(면책사유) 계약자의 고의로 생긴 사고에 대하여 회사는 보험금을 지급하지 않는다.", "제8조(면책 기간) 계약일부터 90일 이내에 발생한 사고는 보장하지 않는다."]),
            ("제5장 보험료", ["제9조(보험료의 납입) 계약자는 매월 말일까지 보험료를 납입해야 한다.", "제10조(납입 연체) 보험료 납입이 30일 이상 연체되면 회사는 계약을 해지할 수 있다."]),
            ("제6장 계약의 해지", ["제11조(계약자의 해지) 계약자는 언제든지 계약을 해지할 수 있다.", "제12조(해지환급금) 회사는 해지일부터 7일 이내에 해지환급금을 지급한다."]),
            ("제7장 분쟁의 해결", ["제13조(관할) 이 계약에 관한 분쟁은 계약자의 주소지 관할 법원에서 해결한다."]),
        ]
        docs.append(_doc("insurance_terms", slug, f"합성 {name} 약관", sections, c))
    return docs


def _proposals() -> list[dict[str, Any]]:
    c = COLLECTIONS[1]
    topics = (("hospital", "병원 정보시스템 구축", "의료정보"), ("city", "스마트시티 데이터 플랫폼", "도시데이터"), ("edu", "대학 학사 시스템 고도화", "학사행정"))
    docs = []
    for slug, title, domain in topics:
        sections = [
            ("1. 사업의 이해", [f"본 사업은 {domain} 업무의 통합과 이용자 편의 향상을 목표로 한다."]),
            ("2. 제안 개요", ["제안사는 15년간 유사 사업을 수행한 경험을 보유하고 있다.", "핵심 제안은 표준 데이터 모델, 단계별 이관, 무중단 전환이다."]),
            ("3. 수행 방안", ["수행은 분석, 설계, 구현, 시험, 이관의 5단계로 진행한다.", "각 단계 종료 시 발주처 검토 회의를 개최한다."]),
            ("4. 일정", ["총 사업 기간은 계약일로부터 10개월이다.", "착수 후 2개월 이내에 상세 설계를 완료한다."]),
            ("5. 투입 조직", ["프로젝트 관리자 1명, 설계자 3명, 개발자 8명, 시험 담당 2명으로 구성한다."]),
            ("6. 가격", ["총 사업비는 1,200,000,000원이며 부가세를 포함하지 않는다."]),
            ("7. 기대 효과", ["업무 처리 시간을 30% 단축하고 데이터 정합성 오류를 절반으로 줄인다."]),
        ]
        docs.append(_doc("proposal", slug, f"합성 제안서 - {title}", sections, c))
    return docs


def _rfps() -> list[dict[str, Any]]:
    c = COLLECTIONS[1]
    docs = []
    for slug, title, offset in (("rfp-a", "통합 고객관리시스템 구축 제안요청서", 0), ("rfp-b", "데이터 레이크 구축 제안요청서", 100)):
        reqs = [f"REQ-{offset + n:03d} {text}" for n, text in enumerate((
            "시스템은 사용자 인증을 위해 다중 인증 방식을 지원해야 한다.", "모든 개인정보는 암호화하여 저장해야 한다.",
            "시스템 가용성은 연 99.9% 이상이어야 한다.", "데이터 이관 계획을 제안서에 포함해야 한다.",
            "사업 수행 인력의 자격 요건을 명시해야 한다.", "하자보수 기간은 검수 후 12개월 이상이어야 한다.",
            "성능 시험 결과를 발주처에 제출해야 한다.", "사용자 교육을 2회 이상 실시해야 한다."), 1)]
        sections = [("1. 사업 개요", [f"{title}는 발주처의 업무 효율화를 위한 사업이다."]),
                    ("2. 요구사항", reqs),
                    ("3. 평가 기준", ["기술 평가 80점, 가격 평가 20점으로 평가한다.", "제안서는 요구사항별 대응표를 포함해야 한다."])]
        docs.append(_doc("rfp", slug, f"합성 {title}", sections, c))
    return docs


def _contracts() -> list[dict[str, Any]]:
    c = COLLECTIONS[2]
    docs = []
    for slug, title, subject in (("service", "용역계약서", "소프트웨어 개발 용역"), ("supply", "물품공급계약서", "서버 장비 공급"), ("license", "라이선스계약서", "소프트웨어 사용권")):
        sections = [
            ("제1조(목적)", [f"이 계약은 {subject}에 관한 갑과 을의 권리와 의무를 정한다."]),
            ("제2조(계약기간)", ["계약기간은 계약 체결일부터 12개월로 한다."]),
            ("제3조(대금)", ["계약 대금은 총 500,000,000원으로 한다."]),
            ("제4조(대금의 지급)", ["갑은 검수 완료 후 30일 이내에 대금을 지급한다."]),
            ("제5조(비밀유지)", ["양 당사자는 계약 이행 중 알게 된 상대방의 비밀을 제3자에게 누설하지 않는다."]),
            ("제6조(손해배상)", ["일방의 귀책사유로 손해가 발생한 경우 그 손해를 배상한다."]),
            ("제7조(계약의 해지)", ["상대방이 계약을 위반하고 14일 이내에 시정하지 않으면 계약을 해지할 수 있다."]),
            ("제8조(분쟁의 해결)", ["분쟁은 갑의 소재지 관할 법원에서 해결한다."]),
        ]
        docs.append(_doc("contract", slug, f"합성 {title}", sections, c))
    return docs


def _law() -> list[dict[str, Any]]:
    c = COLLECTIONS[0]
    articles = [(f"제{n}조(조문 {n})", [f"가상 보험업법 제{n}조는 보험계약 관련 사항 {n}을 규정한다. 위반 시 과태료 {n * 10}만원을 부과한다."]) for n in range(1, 21)]
    return [_doc("law", "virtual-insurance-act", "가상 보험업법", articles, c)]


def build_documents() -> list[dict[str, Any]]:
    return _terms() + _proposals() + _rfps() + _contracts() + _law()


_CONCEPTS = (
    ("보험계약", "contract", ("보험 계약", "계약")), ("보험금", "payment", ("보상금",)), ("보험료", "payment", ("납입금",)), ("면책", "exclusion", ("보장 제외",)),
    ("지급사유", "event", ("보험사고",)), ("해지", "termination", ("계약 해지",)), ("해지환급금", "payment", ("환급금",)), ("계약자", "party", ("보험계약자",)),
    ("피보험자", "party", ("보험 대상자",)), ("수익자", "party", ("수령인",)), ("제안요청서", "document", ("RFP",)), ("요구사항", "requirement", ("REQ",)),
    ("평가기준", "evaluation", ("평가 항목",)), ("사업기간", "schedule", ("수행기간",)), ("사업비", "price", ("총사업비", "가격")), ("투입인력", "resource", ("조직",)),
    ("수행방안", "method", ("추진 방안",)), ("하자보수", "warranty", ("유지보수",)), ("비밀유지", "obligation", ("기밀 보호",)), ("손해배상", "liability", ("배상책임",)),
)
CONCEPTS = [{"concept_id": f"con-{i:03d}", "label": label, "kind": kind, "synonyms": list(syn), "version": 1,
             "relations": [{"type": "related_to", "target": f"con-{(i + 1) % len(_CONCEPTS):03d}"}]} for i, (label, kind, syn) in enumerate(_CONCEPTS)]

RULESETS = [
    {"ruleset_id": "rs-proposal-sections", "title": "제안서 필수 섹션", "version": 1, "applies_to": "proposal",
     "rules": [{"rule_id": f"rule-p{i}", "description": f"제안서에 '{name}' 섹션이 있어야 한다.", "must_contain": name}
               for i, name in enumerate(("사업의 이해", "제안 개요", "수행 방안", "일정", "투입 조직", "가격", "기대 효과"), 1)]},
    {"ruleset_id": "rs-terms-clauses", "title": "약관 필수 조항", "version": 1, "applies_to": "insurance_terms",
     "rules": [{"rule_id": f"rule-t{i}", "description": f"약관에 '{name}' 조항이 있어야 한다.", "must_contain": name}
               for i, name in enumerate(("목적", "보장", "지급사유", "면책", "보험료", "해지", "분쟁"), 1)]},
    {"ruleset_id": "rs-contract-clauses", "title": "계약서 필수 조항", "version": 1, "applies_to": "contract",
     "rules": [{"rule_id": f"rule-c{i}", "description": f"계약서에 '{name}' 조항이 있어야 한다.", "must_contain": name}
               for i, name in enumerate(("목적", "계약기간", "대금", "비밀유지", "손해배상", "해지", "분쟁"), 1)]},
]
