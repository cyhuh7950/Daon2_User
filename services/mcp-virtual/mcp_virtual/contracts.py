"""Contract v0 — 두 가상 서버의 도구 계약(입력·출력 JSON Schema). 요청 설계서 §4~§6과 같은 형식이다. WO-M0 T-M0-02."""

from __future__ import annotations

S = {"type": "string"}
ID = {"type": "string", "minLength": 1, "maxLength": 128}
PAIR = {"project_id": ID, "work_package_id": ID}
PAIR_REQ = ["project_id", "work_package_id"]
INT = {"type": "integer"}
NUM = {"type": "number"}

BLOCK = {"type": "object", "required": ["block_id", "page", "text", "resource_uri"],
         "properties": {"block_id": S, "page": INT, "text": {"type": "string", "maxLength": 8000}, "resource_uri": S}}
RESULT = {"type": "object", "required": ["document_id", "version_id", "run_id", "block_id", "page", "excerpt", "score", "score_kind", "resource_uri"],
          "properties": {"document_id": S, "version_id": S, "run_id": S, "block_id": S, "page": INT, "excerpt": {"type": "string", "maxLength": 8000},
                         "score": NUM, "score_kind": S, "resource_uri": S}}
NODE = {"type": "object", "required": ["node_id", "kind", "title", "level", "page_from", "page_to", "block_ids", "children"],
        "properties": {"node_id": S, "kind": S, "title": S, "level": INT, "page_from": INT, "page_to": INT,
                       "block_ids": {"type": "array", "items": S}, "children": {"type": "array"}}}


def tool(description: str, properties: dict, required: list, output: dict) -> dict:
    return {"description": description,
            "inputSchema": {"type": "object", "required": required, "properties": properties, "additionalProperties": False},
            "outputSchema": output}


RAG_TOOLS = {
    "search_document_evidence": tool("질문과 관련된 문서 근거 블록을 검색한다.",
        {**PAIR, "question": {"type": "string", "minLength": 1, "maxLength": 2000}, "document_id": ID, "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
        [*PAIR_REQ, "question"], {"type": "object", "required": ["results"], "properties": {"results": {"type": "array", "items": RESULT, "maxItems": 20}, "model_mismatch": {"type": "boolean"}}}),
    "get_document_evidence": tool("블록 하나의 원문 근거를 읽는다.", {**PAIR, "document_id": ID, "block_id": ID}, [*PAIR_REQ, "document_id", "block_id"],
        {"type": "object", "required": ["evidence"], "properties": {"evidence": RESULT}}),
    "list_documents": tool("컬렉션의 문서 목록.", {**PAIR, "document_type": S}, PAIR_REQ,
        {"type": "object", "required": ["documents"], "properties": {"documents": {"type": "array", "items": {"type": "object", "required": ["document_id", "title", "document_type", "version_id"],
            "properties": {"document_id": S, "title": S, "document_type": S, "version_id": S}}}}}),
    "get_document_outline": tool("문서의 개요(목차 트리).", {**PAIR, "document_id": ID}, [*PAIR_REQ, "document_id"],
        {"type": "object", "required": ["document_id", "version_id", "nodes"], "properties": {"document_id": S, "version_id": S, "nodes": {"type": "array", "items": NODE}}}),
    "read_document_section": tool("개요 노드의 본문 블록을 읽는다.", {**PAIR, "document_id": ID, "node_id": ID, "cursor": S}, [*PAIR_REQ, "document_id", "node_id"],
        {"type": "object", "required": ["node_id", "blocks", "next_cursor"], "properties": {"node_id": S, "blocks": {"type": "array", "items": BLOCK}, "next_cursor": {"type": ["string", "null"]}}}),
    "get_document_version_status": tool("문서 버전이 아직 최신인지 확인한다(stale 판정).", {**PAIR, "document_id": ID, "version_id": ID}, [*PAIR_REQ, "document_id", "version_id"],
        {"type": "object", "required": ["document_id", "current_version_id", "changed"], "properties": {"document_id": S, "current_version_id": S, "changed": {"type": "boolean"}}}),
}

CONCEPT = {"type": "object", "required": ["concept_id", "label", "kind", "version"], "properties": {"concept_id": S, "label": S, "kind": S, "version": INT,
           "synonyms": {"type": "array", "items": S}, "relations": {"type": "array"}}}
OPS_TOOLS = {
    "ontology_search_concepts": tool("온톨로지 개념 검색.", {"query": {"type": "string", "minLength": 1, "maxLength": 200}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"],
        {"type": "object", "required": ["concepts"], "properties": {"concepts": {"type": "array", "items": CONCEPT}}}),
    "ontology_get_concept": tool("개념 하나와 관계.", {"concept_id": ID}, ["concept_id"], {"type": "object", "required": ["concept"], "properties": {"concept": CONCEPT}}),
    "ruleset_list": tool("RuleSet 목록.", {"applies_to": S}, [],
        {"type": "object", "required": ["rulesets"], "properties": {"rulesets": {"type": "array", "items": {"type": "object", "required": ["ruleset_id", "title", "version", "applies_to"],
            "properties": {"ruleset_id": S, "title": S, "version": INT, "applies_to": S}}}}}),
    "ruleset_get": tool("RuleSet 규칙 목록.", {"ruleset_id": ID}, ["ruleset_id"], {"type": "object", "required": ["ruleset"], "properties": {"ruleset": {"type": "object"}}}),
    "ruleset_evaluate": tool("초안을 RuleSet으로 점검한다.", {"ruleset_id": ID, "draft": {"type": "object", "required": ["sections"], "properties": {"sections": {"type": "array", "maxItems": 100,
        "items": {"type": "object", "required": ["id", "title", "text"], "properties": {"id": S, "title": S, "text": {"type": "string", "maxLength": 100000}}}}}}}, ["ruleset_id", "draft"],
        {"type": "object", "required": ["results"], "properties": {"results": {"type": "array", "items": {"type": "object", "required": ["rule_id", "status", "message"],
            "properties": {"rule_id": S, "status": {"type": "string", "enum": ["pass", "fail", "needs_review"]}, "section_id": S, "evidence_refs": {"type": "array"}, "message": S}}}}}),
    "approved_knowledge_search": tool("승인된 지식 검색(약관·제안서).", {"query": {"type": "string", "minLength": 1, "maxLength": 500}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"],
        {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {"type": "object", "required": ["knowledge_id", "title", "excerpt", "score"],
            "properties": {"knowledge_id": S, "title": S, "excerpt": S, "score": NUM}}}}}),
    "search_law": tool("법령 조문 검색(가상 법령).", {"query": {"type": "string", "minLength": 1, "maxLength": 500}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"],
        {"type": "object", "required": ["articles"], "properties": {"articles": {"type": "array", "items": {"type": "object", "required": ["law_id", "law_title", "article", "excerpt", "score"],
            "properties": {"law_id": S, "law_title": S, "article": S, "excerpt": S, "score": NUM}}}}}),
    "get_law_text": tool("법령 조문 원문.", {"law_id": ID, "article": {"type": "string", "minLength": 1, "maxLength": 200}}, ["law_id", "article"],
        {"type": "object", "required": ["law_id", "law_title", "article", "text"], "properties": {"law_id": S, "law_title": S, "article": S, "text": S}}),
}

ERROR_CODES = ["NOT_FOUND", "SCOPE_FORBIDDEN", "NOT_READY", "MODEL_MISMATCH", "INVALID_ARGUMENT", "LIMIT_EXCEEDED", "UNAVAILABLE", "VERSION_CHANGED"]
SERVERS = {"rag": RAG_TOOLS, "ops": OPS_TOOLS}
AUDIENCES = {"rag": "knowledge-rag-virtual", "ops": "knowledge-ops-virtual"}
