"""가상 MCP 서버 2종을 QA 테넌트의 지식 Connector로 등록하고 연결을 확인한다. api 컨테이너 안에서 실행한다.

  docker exec -e MCP_VIRTUAL_JWT_KEY=<키> daon2_user-api-1 python /tmp/seed_connectors.py <tenant_id>

토큰은 가상 서버 키로 이 스크립트가 직접 서명해(시험용 HS256) DB에 암호화 저장한다. 값은 출력하지 않는다.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

from daon2_user_api.cloud_storage import PostgresCloudStore
from daon2_user_api.knowledge_connector_service import ConnectorContext, KnowledgeConnectorService
from daon2_user_api.provider_credentials import ProviderCredentialCipher

tenant = sys.argv[1]
key = os.environ["MCP_VIRTUAL_JWT_KEY"].strip().encode()
PAIRS = [{"project_id": "proj-alpha", "work_package_id": "wp-terms"}, {"project_id": "proj-alpha", "work_package_id": "wp-proposals"},
         {"project_id": "proj-beta", "work_package_id": "wp-contracts"}]


def token(aud: str, pairs: list) -> str:
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps({"aud": aud, "exp": int(time.time()) + 365 * 86400, "scope": ["read"], "pairs": pairs}, separators=(",", ":")).encode())
    return f"{head}.{body}.{b64(hmac.new(key, f'{head}.{body}'.encode(), hashlib.sha256).digest())}"


store = PostgresCloudStore(os.environ["DAON_CLOUD_DATABASE_DSN"])
store._ensure_pool_open()  # noqa: SLF001
cipher = ProviderCredentialCipher(Path(os.environ["DAON_PROVIDER_CREDENTIAL_KEY_FILE"]).read_bytes(), encryption_key_version=1)
service = KnowledgeConnectorService(store, cipher)
ctx = ConnectorContext(tenant, "seed-script")
existing = {c["name"]: c for c in service.list(ctx)}
for kind, name, url, aud, pairs in (("daon2_rag", "가상 Daon2-RAG", "http://knowledge-rag-virtual:8641/mcp", "knowledge-rag-virtual", PAIRS),
                                    ("daon2", "가상 Daon2", "http://knowledge-ops-virtual:8642/mcp", "knowledge-ops-virtual", []),
                                    ("law", "가상 법령", "http://knowledge-ops-virtual:8642/mcp", "knowledge-ops-virtual", [])):
    if name in existing:
        service.disconnect(ctx, existing[name]["connector_id"])
    created = service.register(ctx, {"kind": kind, "name": name, "endpoint_url": url, "token": token(aud, pairs), "virtual": True, "allowed_scopes": pairs})
    verified = service.verify(ctx, created["connector_id"])
    print(kind, verified["status"], verified["protocol_version"], verified["error_code"])
os._exit(0)
