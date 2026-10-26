"""지식 Connector 호출 직전 외부 전송 판정(F4-03).

- 내부(가상 서버·사설 주소) 엔드포인트는 항상 허용한다.
- 공용 주소 엔드포인트는 Workspace의 실효 외부 전송 정책이 "추가 인증 없이 허용"이고 목적지 호스트가 허용 목록에 있으며
  전송 바이트가 한도 이하일 때만 허용한다. Workspace·정책 버전을 모르면(문맥 없음) 닫는다.
Studio 생성의 판정(`StudioEgressGate`)과 같은 규칙을 쓴다.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping

from .studio_egress import StudioEgressGate
from .studio_workspace import StudioContext


class ConnectorEgressGate:
    def __init__(self, policy_service: Any) -> None:
        self._gate = StudioEgressGate(policy_service)

    def authorize(self, context: Any, connector: Mapping[str, Any], size_bytes: int) -> tuple[bool, str]:
        workspace_id = getattr(context, "workspace_id", None)
        policy_version = getattr(context, "policy_version", None)
        if not workspace_id or not policy_version:
            return False, "EGRESS_CONTEXT_MISSING"
        try:
            studio_context = StudioContext(context.tenant_id, workspace_id, context.actor_id, context.trace_id, policy_version, None)
        except ValueError:
            return False, "EGRESS_CONTEXT_MISSING"
        model = SimpleNamespace(provider_kind="external_api", base_url=str(connector["endpoint_url"]))
        decision = self._gate.authorize(studio_context, model, size_bytes)
        return decision.allowed, decision.reason
