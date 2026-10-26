"""새 설치의 초기 외부 전송 정책(조직·Workspace). api 컨테이너 안에서 실행한다.

  python3 initial_policy.py <tenant_id> <workspace_id>...   (보통 apply-initial-policy.sh 가 DB에서 찾아 넘긴다)

시드된 차단 정책(egress-backfill-policy:)인 범위만 올린다. 누가 한 번이라도 저장한 정책은 건드리지 않는다(멱등).
값은 환경변수로 바꿀 수 있다: SEED_EGRESS_DESTINATIONS(쉼표), SEED_EGRESS_MAX_BYTES, SEED_EGRESS_KINDS(쉼표), SEED_EGRESS_CLASSIFICATION.
정책은 서비스 계층(create_and_activate)으로 적용해 불변 이력·바인딩·감사 구조를 그대로 따른다.
"""
import os
import sys
import uuid

from daon2_user_api.cloud_storage import PostgresCloudStore
from daon2_user_api.egress_policy import EgressPolicyContext, EgressPolicyPayload, EgressPolicyService
from daon2_user_api.egress_policy_postgres import PostgresEgressPolicyRepository

SEEDED = "egress-backfill-policy:"
split = lambda value: tuple(dict.fromkeys(item.strip().lower() for item in value.split(",") if item.strip()))


def initial_payload() -> EgressPolicyPayload:
    return EgressPolicyPayload(
        mode="allow_approved_external",
        allowed_provider_kinds=split(os.environ.get("SEED_EGRESS_KINDS", "external_api,server_internal,local_runtime")),
        allowed_destinations=split(os.environ.get(
            "SEED_EGRESS_DESTINATIONS", "media-bridge-gateway.sinsan.kr,api.upstage.ai,omniroute.sinsan.kr,tts.supertonic.sinsan.kr")),
        classification=os.environ.get("SEED_EGRESS_CLASSIFICATION", "restricted"),
        max_bytes=int(os.environ.get("SEED_EGRESS_MAX_BYTES", "1048576")),
        masking_required=True, redaction_required=True, required_approver="none")


def apply(service, tenant, workspaces, payload, seeded_prefix=SEEDED):
    """시드된 차단 정책인 범위만 올린다. 처리 결과를 (workspace, scope, 'applied'|'kept') 목록으로 돌려준다."""
    done = []
    for workspace in workspaces:
        context = EgressPolicyContext(tenant, tenant, workspace, "seed-initial-policy", "trace-seed-initial-policy", "policy-seed-initial")
        for scope in ("organization", "workspace"):
            current = service._repository.current(context, scope)
            if not current.policy_version_id.startswith(seeded_prefix):
                done.append((workspace, scope, "kept"))
                continue
            service.create_and_activate(context, scope_type=scope, payload=payload, expected_etag=current.etag,
                                        idempotency_key=f"seed-initial-{scope}-{uuid.uuid4().hex}")
            done.append((workspace, scope, "applied"))
    return done


if __name__ == "__main__":
    tenant, workspaces = sys.argv[1], sys.argv[2:]
    if not workspaces:
        print(f"조직 {tenant} 의 Workspace가 아직 없습니다(앱을 한 번 기동한 뒤 다시 실행).")
        os._exit(0)
    store = PostgresCloudStore(os.environ["DAON_CLOUD_DATABASE_DSN"])
    service = EgressPolicyService(PostgresEgressPolicyRepository(store), development_default=None)
    for workspace, scope, result in apply(service, tenant, workspaces, initial_payload()):
        print(workspace, scope, "초기 정책 적용" if result == "applied" else "이미 저장된 정책이 있어 건드리지 않음")
    context = EgressPolicyContext(tenant, tenant, workspaces[-1], "seed-initial-policy", "trace-seed-initial-policy", "policy-seed-initial")
    effective = service.get_effective(context)
    print("effective:", effective.mode, list(effective.allowed_destinations), effective.max_bytes)
    os._exit(0)  # 연결 풀 종료 시 잡음 방지
