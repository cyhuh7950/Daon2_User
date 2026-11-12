"""WO-K6: Daon 승인 지식의 온톨로지·GraphRAG·RuleSet·승인 자산을 모두 쓴다(신산님 지시 2026-11-12)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mcp-virtual"))

from daon2_user_api.knowledge_connector_service import KIND_TOOLS, SLOW_TOOL_TIMEOUTS, ConnectorContext, KnowledgeConnectorService  # noqa: E402
from daon2_user_api.mcp_client import HttpJsonRpcTransport  # noqa: E402


class ToolDefaultsTests(unittest.TestCase):
    def test_daon2_and_rag_defaults_include_every_tool_the_servers_offer(self):
        # ysna tools/list(2026-11-12): Daon2에는 있는데 Daon2-User 기본 허용에 빠져 있던 도구들.
        self.assertTrue({"graphrag_query", "ontology_traverse", "approved_knowledge_read"} <= KIND_TOOLS["daon2"])
        self.assertTrue({"get_document_text", "list_approved_documents"} <= KIND_TOOLS["daon2_rag"])


class SlowToolTimeoutTests(unittest.TestCase):
    def test_graphrag_waits_long_enough_for_the_server(self):
        # Daon2 안내: graphrag_query는 최대 약 2분, 클라이언트 대기 130초 이상 권장. 기본 25초(최대 60초)로는 끊겼다.
        self.assertGreaterEqual(SLOW_TOOL_TIMEOUTS["graphrag_query"], 130)

    def test_service_passes_the_longer_timeout_only_for_slow_tools(self):
        calls = []
        client = SimpleNamespace(_connection=object(), call_tool=lambda name, arguments, **kw: calls.append((name, kw)) or "ok")
        view = {"status": "verified", "allowed_scopes": [], "virtual": True, "limits": {}}
        service = KnowledgeConnectorService.__new__(KnowledgeConnectorService)
        service._egress_gate = None
        with patch.object(KnowledgeConnectorService, "_client", return_value=(client, view)):
            ctx = ConnectorContext("t", "a")
            service.call(ctx, "kc", "graphrag_query", {"scope": {}, "mode": "local", "query": "q"})
            service.call(ctx, "kc", "ruleset_list", {"scope": {}, "limit": 1})
        self.assertEqual(calls, [("graphrag_query", {"timeout_seconds": SLOW_TOOL_TIMEOUTS["graphrag_query"]}), ("ruleset_list", {})])

    def test_transport_uses_the_per_request_timeout(self):
        seen = []

        class Opener:
            def open(self, request, timeout):  # noqa: A003
                seen.append(timeout)
                raise OSError("stop")

        transport = HttpJsonRpcTransport("https://example.test/mcp", token="t", timeout_seconds=25)
        transport._opener = Opener()
        for timeout in (None, 130):
            try:
                transport.request("tools/call", {"name": "x"}, timeout_seconds=timeout)
            except Exception:  # noqa: BLE001  연결 실패 자체는 이 시험의 관심사가 아니다.
                pass
        self.assertEqual(seen, [25, 130])


import json  # noqa: E402

from daon2_user_api.mcp_client import McpError  # noqa: E402
from daon2_user_api.question_external_evidence import NotebookKnowledgeEvidence, build_plan_prompt, parse_plan  # noqa: E402
from test_question_external_evidence import CONCEPT, _Scopes, _ToolConnectors, daon2_target  # noqa: E402

APPROVED = "EXPERT_APPROVED"
SEARCH = {"concepts": [{"concept_id": "c1", "snapshot_id": "s1", "score": 0.8, "provenance": APPROVED}]}
TRAVERSE = {"nodes": [{"concept_id": "c1", "label": "보험금 지급"}, {"concept_id": "c2", "label": "지급기준표"}],
            "edges": [{"source": "c1", "target": "c2", "relation_type": "근거"}], "truncated": False, "snapshot_id": "s1", "provenance": APPROVED}
RULE_WITH_CONDITION = {"ruleset_id": "r1", "revision": 6, "name": "입찰무효_규칙", "purpose": "제안서가 없으면 무효", "published": True, "provenance": APPROVED,
                       "formal": {"if": [{"condition_id": "k1", "subject": "s-doc", "operator": "EXISTS", "value": None, "datatype": "boolean"}], "then": []}}


class KnowledgeKindsTests(unittest.TestCase):
    def test_plan_offers_every_daon2_kind(self):
        prompt = build_plan_prompt("질문", (), daon2_target("A"))
        for kind in ("rag", "ontology", "ruleset", "graphrag", "approved", "judgment"):
            self.assertIn(f"- {kind}:", prompt)

    def test_plan_keeps_new_kinds(self):
        raw = json.dumps({"requests": [{"knowledge": "graphrag", "package": "P1", "query": "제출 조건"},
                                       {"knowledge": "judgment", "package": "P1", "query": "제안서 미제출"}]}, ensure_ascii=False)
        self.assertEqual(parse_plan(raw, daon2_target("A")), (("P1", "제출 조건", "graphrag"), ("P1", "제안서 미제출", "judgment")))


class Daon2KindEvidenceTests(unittest.TestCase):
    def finder(self, **responses):
        self.connectors = _ToolConnectors(**responses)
        return NotebookKnowledgeEvidence(_Scopes([]), self.connectors)

    def calls(self):
        return [c[2] for c in self.connectors.calls]

    def test_graphrag_answer_and_evidence_become_one_cited_item(self):
        finder = self.finder(graphrag_query={"mode": "local", "answer": "제안서는 기한 내 제출해야 한다.", "evidence": [{"label": "제출 기한", "text": "마감일까지"}],
                                             "evidence_truncated": False, "warnings": [], "snapshot_id": "g1", "provenance": APPROVED})
        found = finder.run(daon2_target("A"), (("P1", "제출 조건", "graphrag"),))
        self.assertEqual(self.calls(), ["graphrag_query"])
        self.assertEqual({k: self.connectors.calls[0][3][k] for k in ("mode", "query")}, {"mode": "local", "query": "제출 조건"})
        self.assertEqual(found[0].document_name, "GraphRAG · 제출 조건")
        self.assertIn("제안서는 기한 내 제출해야 한다.", found[0].text)
        self.assertIn("마감일까지", found[0].text)

    def test_unapproved_graphrag_is_not_used(self):
        finder = self.finder(graphrag_query={"answer": "x", "evidence": [], "provenance": "AUTO"})
        self.assertEqual(finder.run(daon2_target("A"), (("P1", "q", "graphrag"),)), ())

    def test_graphrag_failures_skip_only_that_request(self):
        for code in ("NOT_READY", "SCOPE_FORBIDDEN", "UPSTREAM_UNAVAILABLE", "MCP_UNAVAILABLE"):
            with self.subTest(code=code):
                self.assertEqual(self.finder(graphrag_query=McpError(code)).run(daon2_target("A"), (("P1", "q", "graphrag"),)), ())

    def test_scope_forbidden_package_is_skipped_like_not_ready(self):
        # Daon2 배포(2026-11-12) 뒤 없는 (tenant, 패키지) 조합은 NOT_READY 대신 SCOPE_FORBIDDEN이다. 질문 전체를 실패시키지 않는다.
        self.assertEqual(self.finder(ontology_search_concepts=McpError("SCOPE_FORBIDDEN")).run(daon2_target("A"), (("P1", "보험금", "ontology"),)), ())
        self.assertEqual(self.finder(ruleset_list=McpError("SCOPE_FORBIDDEN")).run(daon2_target("A"), (("P1", "규칙", "ruleset"),)), ())

    def test_ontology_adds_related_concepts_from_traverse(self):
        finder = self.finder(ontology_search_concepts=SEARCH, ontology_get_concept=CONCEPT, ontology_traverse=TRAVERSE)
        found = finder.run(daon2_target("A"), (("P1", "보험금", "ontology"),))
        self.assertEqual(self.calls(), ["ontology_search_concepts", "ontology_get_concept", "ontology_traverse"])
        self.assertIn("관련 개념: 지급기준표(근거)", found[0].text)

    def test_ontology_still_works_when_traverse_is_not_available(self):
        finder = self.finder(ontology_search_concepts=SEARCH, ontology_get_concept=CONCEPT, ontology_traverse=McpError("MCP_TOOL_NOT_ALLOWED"))
        self.assertEqual(len(finder.run(daon2_target("A"), (("P1", "보험금", "ontology"),))), 1)

    def test_approved_asset_is_read_and_cited(self):
        finder = self.finder(approved_knowledge_search={"assets": [{"asset_id": "a1", "version_id": "v1", "title": "지급 안내", "provenance": APPROVED}], "provenance": APPROVED},
                             approved_knowledge_read={"asset_id": "a1", "version_id": "v1", "approval_status": "APPROVED", "version": "1", "content": {"body": "지급은 7일 안에 한다."},
                                                      "evidence": [], "expires_at": None, "revoked_at": None, "provenance": APPROVED})
        found = finder.run(daon2_target("A"), (("P1", "지급", "approved"),))
        self.assertEqual(self.calls(), ["approved_knowledge_search", "approved_knowledge_read"])
        self.assertEqual(found[0].document_name, "승인 자산 · 지급 안내")
        self.assertIn("지급은 7일 안에 한다.", found[0].text)

    def test_revoked_asset_is_not_used(self):
        finder = self.finder(approved_knowledge_search={"assets": [{"asset_id": "a1", "version_id": "v1", "title": "t", "provenance": APPROVED}], "provenance": APPROVED},
                             approved_knowledge_read={"asset_id": "a1", "version_id": "v1", "content": {"body": "x"}, "revoked_at": "2026-11-01T00:00:00Z", "provenance": APPROVED})
        self.assertEqual(finder.run(daon2_target("A"), (("P1", "지급", "approved"),)), ())


class JudgmentTests(unittest.TestCase):
    def finder(self, **responses):
        self.connectors = _ToolConnectors(ruleset_list={"rulesets": [{"ruleset_id": "r1", "published": True}], "provenance": APPROVED}, ruleset_get=RULE_WITH_CONDITION,
                                          ontology_traverse={"nodes": [{"concept_id": "s-doc", "label": "제안서 제출"}], "edges": [], "provenance": APPROVED}, **responses)
        return NotebookKnowledgeEvidence(_Scopes([]), self.connectors)

    def test_facts_are_extracted_by_label_and_evaluated_by_subject_id(self):
        seen = []

        def extract(query, conditions):
            seen.append((query, conditions))
            return {conditions[0]["id"]: False}

        finder = self.finder(ruleset_evaluate={"results": [{"ruleset_id": "r1", "revision": 6, "result": "satisfied", "actual_action_ids": [], "applied_exception_ids": [],
                                                            "resolution_trace": [], "evidence_refs": [], "published": True}], "provenance": APPROVED})
        found = finder.run(daon2_target("A"), (("P1", "제안서 미제출", "judgment"),), extract_facts=extract)
        self.assertEqual(seen[0][1][0]["label"], "제안서 제출")
        evaluate = next(c for c in self.connectors.calls if c[2] == "ruleset_evaluate")[3]
        self.assertEqual((evaluate["ruleset_ids"], evaluate["facts"]), (["r1"], [{"key": "s-doc", "value": False}]))
        self.assertEqual(found[0].document_name, "규칙 판정 · 입찰무효_규칙")
        for part in ("충족", "제안서 제출 = 아니오", "참고 판정"):
            self.assertIn(part, found[0].text)

    def test_missing_facts_are_reported_as_needs_review(self):
        finder = self.finder(ruleset_evaluate={"results": [{"ruleset_id": "r1", "revision": 6, "result": "needs_review", "actual_action_ids": [], "applied_exception_ids": [],
                                                            "resolution_trace": ["missing_fact:s-doc"], "evidence_refs": [], "published": True}], "provenance": APPROVED})
        found = finder.run(daon2_target("A"), (("P1", "제안서", "judgment"),), extract_facts=lambda query, conditions: {})
        self.assertIn("확인 필요", found[0].text)
        self.assertIn("부족한 사실: 제안서 제출", found[0].text)

    def test_without_a_fact_extractor_rules_are_returned_as_text(self):
        found = self.finder().run(daon2_target("A"), (("P1", "제안서", "judgment"),))
        self.assertNotIn("ruleset_evaluate", [c[2] for c in self.connectors.calls])
        self.assertEqual(found[0].document_name, "규칙 · 입찰무효_규칙")


if __name__ == "__main__":
    unittest.main()


class FactParsingTests(unittest.TestCase):
    CONDITIONS = [{"id": "F1", "label": "제안서 제출", "datatype": "boolean", "operator": "eq", "value": True}]

    def test_prompt_lists_conditions_by_label_without_concept_ids(self):
        from daon2_user_api.question_external_evidence import build_facts_prompt
        text = build_facts_prompt("제출 안 했는데 괜찮나요?", self.CONDITIONS)
        for part in ("제출 안 했는데 괜찮나요?", "F1", "제안서 제출", "boolean"):
            self.assertIn(part, text)

    def test_only_known_conditions_are_kept(self):
        from daon2_user_api.question_external_evidence import parse_facts
        raw = '{"facts":[{"id":"F1","value":false},{"id":"F9","value":true},{"id":"F1"}]}'
        self.assertEqual(parse_facts(raw, self.CONDITIONS), {"F1": False})

    def test_unreadable_answer_gives_no_facts(self):
        from daon2_user_api.question_external_evidence import parse_facts
        self.assertEqual(parse_facts("모르겠습니다", self.CONDITIONS), {})


class FactServiceTests(unittest.TestCase):
    """규칙 판정을 고른 질문이면 서비스가 사실 추출 함수를 넘긴다. 그 호출도 전송 승인을 따로 받는다."""

    def setUp(self):
        import json as _json
        from test_question_external_evidence import CTX, FakeCredential, FakeIndex, FakeProviderSettings, _PlanEgress, _PlanTransport, _Repository, daon2_target as d2, external
        from daon2_user_api.question_answering_service import QuestionAnsweringService
        plan = _json.dumps({"requests": [{"knowledge": "judgment", "package": "P1", "query": "제안서 미제출"}]}, ensure_ascii=False)

        class Transport(_PlanTransport):
            def post_json(self, **kwargs):
                if "fact extractor" in _json.dumps(kwargs["payload"], ensure_ascii=False):
                    self.calls += 1
                    self.payloads.append(kwargs["payload"])
                    return {"choices": [{"message": {"content": _json.dumps({"answer": '{"facts":[{"id":"F1","value":false}]}'})}}]}
                return super().post_json(**kwargs)

        test = self

        class Planner:
            def prepare(self, context):
                return d2("제안서 작업")

            def run(self, tgt, requests, extract_facts=None):
                test.extract = extract_facts
                test.facts = extract_facts("제안서 미제출", FactParsingTests.CONDITIONS) if extract_facts else None
                return (external(),)

        self.egress, self.transport = _PlanEgress(), Transport(plan, ["ext-b1"])
        self.make = lambda costs=None: QuestionAnsweringService(FakeProviderSettings(), _Repository(), FakeIndex(()), FakeCredential(), self.transport, self.egress, run_cost_sessions=costs)
        self.Planner, self.ctx = Planner, CTX

    def evidence(self, costs=None):
        service = self.make(costs)
        planner = self.Planner()
        service.set_external_evidence(planner.run, planner=planner)
        return service._external_evidence(self.ctx, "제안서를 안 냈는데 입찰이 무효인가요?")  # noqa: SLF001

    def test_llm_reads_facts_for_the_rule_conditions(self):
        self.evidence()
        self.assertEqual(self.facts, {"F1": False})
        self.assertEqual(len(self.egress.plan_checks), 2)
        self.assertIn("제안서 제출", str(self.transport.payloads[-1]))

    def test_charged_runs_skip_fact_reading(self):
        from test_question_external_evidence import _Costs
        self.evidence(_Costs())
        self.assertEqual(self.facts, {})
        self.assertFalse(any("fact extractor" in str(p) for p in self.transport.payloads))
