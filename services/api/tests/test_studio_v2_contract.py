"""Studio v2 OpenAPI 계약(studio-v2.openapi.json)과 실제 라우트의 일치 검사."""
import json
import tempfile
import unittest
from pathlib import Path

from daon2_user_api.audit import AuditEventStore
from daon2_user_api.authorization import AuthorizationService, SqliteAuthorizationRepository
from daon2_user_api.runtime import RuntimeDependencies, RuntimeSettings, create_app
from test_identity_support import POLICY_VERSION, create_service

CONTRACT = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi" / "v1" / "studio-v2.openapi.json"


class StudioV2ContractTests(unittest.TestCase):
    def test_contract_matches_registered_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "runtime.sqlite3"
            audit = AuditEventStore()
            identity, identity_repository, _, clock = create_service(db, audit_store=audit)
            repository = SqliteAuthorizationRepository(db)
            authorization = AuthorizationService(repository=repository, audit_store=audit, clock=clock, identity_service=identity)
            dependencies = RuntimeDependencies(
                settings=RuntimeSettings.for_test(database_path=db, policy_version=POLICY_VERSION), identity_service=identity,
                authorization_service=authorization, audit_store=audit, identity_repository=identity_repository,
                authorization_repository=repository, studio_v2_service=object(), knowledge_connector_service=object())
            app = create_app(dependencies)
            actual = set()
            for route in app.routes:
                path = getattr(route, "path", "")
                if "/notebooks/{notebook_id}/studio" in path:
                    for method in getattr(route, "methods", ()):
                        if method not in {"HEAD", "OPTIONS"}:
                            actual.add((method.lower(), path))
            dependencies.close()
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        declared = {(method, path) for path, item in contract["paths"].items() for method in item}
        self.assertEqual(actual, declared)


if __name__ == "__main__":
    unittest.main()
