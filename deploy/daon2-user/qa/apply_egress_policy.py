"""QA Workspace 의 외부 전송 정책을 daon-user 운영 정책(v34)과 같게 맞춘다. api 컨테이너 안에서 실행한다.

  python3 apply_egress_policy.py <tenant_id> <workspace_id>

허용 대상은 원본과 같은 media-bridge-gateway.sinsan.kr(external_api, 최대 64 KiB, 마스킹·삭제 필수)만이다.
필수 승인자는 기본 none("추가 인증 없이 허용", 개발 단계 기본). 추가 인증 후 허용으로 하려면 EGRESS_REQUIRED_APPROVER=organization_admin.
정책은 서비스 계층(create_and_activate)으로 적용해 불변 이력·바인딩·감사 구조를 그대로 따른다.
"""
import os
import sys
import uuid

from daon2_user_api.cloud_storage import PostgresCloudStore
from daon2_user_api.egress_policy import EgressPolicyContext, EgressPolicyPayload, EgressPolicyService
from daon2_user_api.egress_policy_postgres import PostgresEgressPolicyRepository

tenant, workspace = sys.argv[1], sys.argv[2]
payload = EgressPolicyPayload(
    mode="allow_approved_external", allowed_provider_kinds=("external_api",),
    allowed_destinations=("media-bridge-gateway.sinsan.kr",), classification="internal", max_bytes=65536,
    masking_required=True, redaction_required=True, required_approver=os.environ.get("EGRESS_REQUIRED_APPROVER", "none"))
store = PostgresCloudStore(os.environ["DAON_CLOUD_DATABASE_DSN"])
service = EgressPolicyService(PostgresEgressPolicyRepository(store))
context = EgressPolicyContext(tenant, tenant, workspace, "provider-import", "trace-provider-import", "policy-provider-import")
for scope in ("organization", "workspace"):
    current = service._repository.current(context, scope)
    if current.payload == payload:
        print(scope, "already applied")
        continue
    view = service.create_and_activate(context, scope_type=scope, payload=payload, expected_etag=current.etag,
                                       idempotency_key=f"provider-import-{scope}-{uuid.uuid4().hex}")
    print(scope, "applied version", view.policy_version if hasattr(view, "policy_version") else "?")
effective = service.get_effective(context)
print("effective mode:", effective.mode, "destinations:", list(effective.allowed_destinations))
store.close()
