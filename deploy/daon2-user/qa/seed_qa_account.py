import os, secrets
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
password = secrets.token_urlsafe(24)
try:
    result = svc.create_user(principal, login_id="qa-e2e", email="qa-e2e@example.test", initial_password=password,
        idempotency_key="seed-qa-e2e-20261020-000001", trace_id="trace-console-seed-qa",
        policy_version=os.environ.get("DAON_POLICY_VERSION", "runtime-policy-v1"))
    with open("/tmp/qa_e2e_password", "w") as handle:
        os.fchmod(handle.fileno(), 0o600); handle.write(password)
    print("created:", result.user.login_id, "state=", result.user.state, "replayed=", result.replayed)
except IdentityError as error:
    print("FAILED:", error.code)
except Exception as error:
    print("FAILED:", type(error).__name__)
