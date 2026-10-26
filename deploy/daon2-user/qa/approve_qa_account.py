import os
from datetime import datetime, timezone
from daon2_user_api.identity import IdentityPrincipal, IdentityError
from daon2_user_api.identity_postgres import PostgresIdentityRepository
from daon2_user_api.audit import PostgresSecurityAuditStore
from daon2_user_api.admin_users import AdminUserService
dsn = os.environ["DAON_CLOUD_DATABASE_DSN"]
repo = PostgresIdentityRepository(dsn); audit = PostgresSecurityAuditStore(dsn)
svc = AdminUserService(repository=repo, audit_store=audit, system_admin_user_ids=frozenset({"admin"}),
                       clock=lambda: datetime.now(timezone.utc), password_reset_requester=None)
principal = IdentityPrincipal(user_id="admin", session_id="console-seed", device_id="console-seed", tenant_id="admin")
import psycopg
with psycopg.connect(dsn) as c:
    uid = c.execute("select user_id from identity_users where login_id='qa-e2e'").fetchone()[0]
try:
    r = svc.approve_user(principal, user_id=uid, idempotency_key="approve-qa-e2e-20261020-000001",
        trace_id="trace-console-approve-qa", policy_version=os.environ.get("DAON_POLICY_VERSION","runtime-policy-v1"))
    print("approved:", r.user.login_id, "state=", r.user.state, "replayed=", r.replayed)
except IdentityError as e:
    print("FAILED:", e.code)
