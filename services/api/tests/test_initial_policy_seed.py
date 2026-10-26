import importlib.util
from pathlib import Path

from daon2_user_api.egress_policy import (
    EgressPolicyContext, EgressPolicyPayload, EgressPolicyService, ReferenceEgressPolicyRepository,
)

SEED = Path(__file__).resolve().parents[3] / "deploy" / "daon2-user" / "seed" / "initial_policy.py"
spec = importlib.util.spec_from_file_location("initial_policy_seed", SEED)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def context(scope_workspace="ws-1"):
    return EgressPolicyContext("admin", "admin", scope_workspace, "seed", "trace", "policy")


def test_initial_policy_opens_only_seeded_deny_scopes_and_is_idempotent():
    repository = ReferenceEgressPolicyRepository()
    service = EgressPolicyService(repository, development_default=None)
    repository.seed(context(), scope_type="organization", payload=EgressPolicyPayload.deny_external())
    repository.seed(context(), scope_type="workspace", payload=EgressPolicyPayload.deny_external())
    payload = seed.initial_payload()
    assert payload.mode == "allow_approved_external" and payload.required_approver == "none"
    assert "api.upstage.ai" in payload.allowed_destinations and payload.max_bytes == 1048576

    first = seed.apply(service, "admin", ["ws-1"], payload, seeded_prefix="policy-")
    assert first == [("ws-1", "organization", "applied"), ("ws-1", "workspace", "applied")]
    effective = service.get_effective(context())
    assert effective.mode == "allow_approved_external" and effective.max_bytes == 1048576

    # 두 번째 실행은 이미 바뀐 정책을 건드리지 않는다(사용자가 저장한 정책 보호).
    second = seed.apply(service, "admin", ["ws-1"], payload, seeded_prefix="policy-organization-1")
    assert [item[2] for item in second] == ["kept", "kept"] or all(item[2] == "kept" for item in second)


def test_initial_screen_preference_is_applied_once_and_never_overwrites():
    from daon2_user_api.screen_preferences import ReferenceScreenPreferenceRepository, ScreenPreferenceContext, ScreenPreferenceService
    spec = importlib.util.spec_from_file_location("initial_screen_seed", SEED.with_name("initial_screen.py"))
    screen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(screen)
    service = ScreenPreferenceService(ReferenceScreenPreferenceRepository())
    assert screen.apply(service, "admin", "admin", "dark") == "applied"
    assert screen.apply(service, "admin", "admin", "light") == "kept"
    assert service.get(ScreenPreferenceContext("admin", "admin")) == {"theme": "dark"}
