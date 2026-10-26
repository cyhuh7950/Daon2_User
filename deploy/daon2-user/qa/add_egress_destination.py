"""QA Workspace 의 외부 전송 정책에 허용 목적지를 더한다(기존 목적지·나머지 항목은 그대로). api 컨테이너 안에서 실행한다.

  python3 add_egress_destination.py <tenant_id> <workspace_id> <host> [<host> ...]

WO-F7: 음성 엔진 서버(예: tts.supertonic.sinsan.kr)를 조직·Workspace 정책의 허용 목적지에 추가한다.
정책은 서비스 계층(create_and_activate)으로 적용해 불변 이력·바인딩·감사 구조를 그대로 따른다.
"""
import dataclasses
import os
import re
import sys
import uuid

from daon2_user_api.cloud_storage import PostgresCloudStore
from daon2_user_api.egress_policy import EgressPolicyContext, EgressPolicyService
from daon2_user_api.egress_policy_postgres import PostgresEgressPolicyRepository

tenant, workspace, *hosts = sys.argv[1:]
hosts = [h.lower() for h in hosts]
assert hosts and all(re.fullmatch(r"[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?", h) for h in hosts), "host 형식 오류"
store = PostgresCloudStore(os.environ["DAON_CLOUD_DATABASE_DSN"])
service = EgressPolicyService(PostgresEgressPolicyRepository(store))
context = EgressPolicyContext(tenant, tenant, workspace, "qa-egress-destination", "trace-qa-egress", "policy-qa-egress")
for scope in ("organization", "workspace"):
    current = service._repository.current(context, scope)
    if current.payload.mode != "allow_approved_external":
        print(scope, "mode is", current.payload.mode, "- skipped")
        continue
    merged = tuple(dict.fromkeys((*current.payload.allowed_destinations, *hosts)))
    if merged == tuple(current.payload.allowed_destinations):
        print(scope, "already allowed")
        continue
    payload = dataclasses.replace(current.payload, allowed_destinations=merged)
    service.create_and_activate(context, scope_type=scope, payload=payload, expected_etag=current.etag,
                                idempotency_key=f"qa-egress-{scope}-{uuid.uuid4().hex}")
    print(scope, "applied")
effective = service.get_effective(context)
print("effective mode:", effective.mode, "destinations:", list(effective.allowed_destinations))
store.close()
