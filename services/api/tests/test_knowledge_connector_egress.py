"""Connector 호출 직전 외부 전송 판정(F4-03)과 허용 도구 재확인."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from daon2_user_api.knowledge_connector_egress import ConnectorEgressGate
from daon2_user_api.knowledge_connector_service import ConnectorContext, ConnectorError, KnowledgeConnectorService


def effective(**over):
    base = dict(mode="allow_approved_external", required_approver="none", allowed_provider_kinds=("external_api",),
                allowed_destinations=("kg.example.com",), max_bytes=10_000, masking_required=False, redaction_required=False)
    return SimpleNamespace(**{**base, **over})


class FakePolicy:
    def __init__(self, policy):
        self.policy = policy

    def get_effective(self, context):
        return self.policy


def service(policy=None):
    instance = KnowledgeConnectorService.__new__(KnowledgeConnectorService)
    instance._egress_gate = None if policy is None else ConnectorEgressGate(FakePolicy(policy))
    return instance


CTX = ConnectorContext("tenant-1", "actor-1", "trace-1", "workspace-1", "policy-1")
PUBLIC = {"virtual": False, "endpoint_url": "https://kg.example.com/mcp"}


class ConnectorEgressTests(unittest.TestCase):
    def test_no_gate_virtual_and_private_endpoints_are_not_checked(self):
        service(None)._authorize_egress(CTX, PUBLIC, {"q": "x"})
        gate_deny = service(effective(mode="deny_external"))
        gate_deny._authorize_egress(ConnectorContext("t", "a"), {"virtual": True, "endpoint_url": "https://kg.example.com/mcp"}, {})
        gate_deny._authorize_egress(ConnectorContext("t", "a"), {"virtual": False, "endpoint_url": "http://127.0.0.1:8641/mcp"}, {})

    def test_public_endpoint_needs_allowing_policy_destination_and_size(self):
        service(effective())._authorize_egress(CTX, PUBLIC, {"q": "x"})
        denied = [effective(mode="deny_external"), effective(required_approver="step_up"), effective(allowed_destinations=("other.example.com",)),
                  effective(max_bytes=5)]
        for policy in denied:
            with self.subTest(policy=policy), self.assertRaises(ConnectorError) as raised:
                service(policy)._authorize_egress(CTX, PUBLIC, {"q": "긴 질의 내용"})
            self.assertEqual((raised.exception.code, raised.exception.status), ("CONNECTOR_EGRESS_DENIED", 403))

    def test_public_endpoint_without_workspace_context_is_denied(self):
        with self.assertRaises(ConnectorError) as raised:
            service(effective())._authorize_egress(ConnectorContext("tenant-1", "actor-1"), PUBLIC, {})
        self.assertEqual(raised.exception.code, "CONNECTOR_EGRESS_DENIED")


if __name__ == "__main__":
    unittest.main()
