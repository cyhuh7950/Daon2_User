"""Studio 생성의 외부 전송 정책 판정(WO-F1 F1-14). 외부 Provider로 보내기 전에 실효 정책을 적용한다.

- 내부 Provider(local, server_internal, local_runtime)는 항상 허용한다.
- 외부(external_api)는 실효 정책이 allow_approved_external(필수 승인자 none = "추가 인증 없이 허용")이고 Provider 종류·목적지 호스트가 허용 목록에 있으며
  전송 바이트가 max_bytes 이하일 때만 허용한다. 하나라도 어긋나면 해당 후보를 건너뛰고 다음 후보(우선순위)로 간다.
- 정책의 masking/redaction 요구는 개인 식별 패턴(주민번호·전화·이메일·카드)을 마스킹한 프롬프트로 충족한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .egress_policy import EgressPolicyContext, EgressPolicyError
from .studio_workspace import StudioContext

INTERNAL_KINDS = frozenset({"local", "server_internal", "local_runtime"})
_PATTERNS = (
    (re.compile(r"\b\d{6}-?[1-4]\d{6}\b"), "[주민번호]"),
    (re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"), "[전화번호]"),
    (re.compile(r"\b0\d{1,2}-\d{3,4}-\d{4}\b"), "[전화번호]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[이메일]"),
    (re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b"), "[카드번호]"),
)


def mask_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


@dataclass(frozen=True, slots=True)
class EgressDecision:
    allowed: bool
    reason: str
    masked: bool = False


class StudioEgressGate:
    def __init__(self, policy_service) -> None:  # type: ignore[no-untyped-def]
        self._policy_service = policy_service

    def authorize(self, context: StudioContext, model, size_bytes: int) -> EgressDecision:  # type: ignore[no-untyped-def]
        kind = getattr(model, "provider_kind", "external_api")
        if kind in INTERNAL_KINDS:
            return EgressDecision(True, "internal")
        if kind != "external_api" or self._policy_service is None:
            return EgressDecision(False, "EGRESS_POLICY_UNAVAILABLE")
        try:
            effective = self._policy_service.get_effective(EgressPolicyContext(
                context.tenant_id, context.tenant_id, context.workspace_id, context.actor_id, context.trace_id, context.policy_version))
        except EgressPolicyError as error:
            return EgressDecision(False, error.code)
        except Exception:
            return EgressDecision(False, "EGRESS_POLICY_UNAVAILABLE")
        host = (urlsplit(model.base_url).hostname or "").lower()
        if effective.mode != "allow_approved_external":
            return EgressDecision(False, "EGRESS_POLICY_DENIED")
        if effective.required_approver != "none":
            # "추가 인증 후 허용": 백그라운드 생성에는 승인 절차가 없으므로 외부 전송하지 않는다(질문에서만 추가 인증).
            return EgressDecision(False, "EGRESS_APPROVAL_REQUIRED")
        if "external_api" not in effective.allowed_provider_kinds or host not in {d.lower() for d in effective.allowed_destinations}:
            return EgressDecision(False, "EGRESS_DESTINATION_DENIED")
        if size_bytes > effective.max_bytes:
            return EgressDecision(False, "EGRESS_MAX_BYTES_EXCEEDED")
        return EgressDecision(True, "policy_allowed", masked=bool(effective.masking_required or effective.redaction_required))
