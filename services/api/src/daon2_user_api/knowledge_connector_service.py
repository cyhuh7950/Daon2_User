"""지식 Connector(MCP) 등록·확인·호출 서비스. WO-M0 T-M0-07.

토큰은 ProviderCredentialCipher로 암호화해 저장하고 호출 직전에만 복호화한다. 응답은 신뢰하지 않는 데이터다.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import secrets
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from psycopg.types.json import Jsonb

from .cloud_storage import CloudAccessContext
from .mcp_client import HttpJsonRpcTransport, McpClient, McpError, McpToolResult
from .provider_credentials import EncryptedCredential, ProviderCredentialCipher

KINDS = {"daon2_rag": "knowledge-rag", "daon2": "knowledge-ops", "law": "law"}
# Connector 종류별로 호출을 허용하는 도구의 상한(등록 시 허용 목록은 이 안에서만 고른다).
KIND_TOOLS: Mapping[str, frozenset[str]] = {
    "daon2_rag": frozenset({"search_document_evidence", "get_document_evidence", "list_documents", "get_document_outline", "read_document_section",
                            "get_document_version_status"}),
    "daon2": frozenset({"ontology_search_concepts", "ontology_get_concept", "ruleset_list", "ruleset_get", "ruleset_evaluate", "approved_knowledge_search"}),
    "law": frozenset({"search_law", "get_law_text"}),
}
_PROVIDER_CODE = "CUSTOM"


# Connector별 호출 한도(F4-02). 비어 있으면 서버 기본값(시간 초과 25초, 동시 4건, 응답 1 MiB, 분당 30회)을 쓴다.
LIMIT_RANGES = {"max_concurrent": (1, 8), "timeout_seconds": (1, 60), "max_response_bytes": (4096, 4 * 1024 * 1024), "calls_per_minute": (1, 600)}


def validate_limits(limits: Any) -> dict[str, int]:
    if not isinstance(limits, Mapping):
        raise ConnectorError("CONNECTOR_LIMITS_INVALID")
    cleaned: dict[str, int] = {}
    for key, value in limits.items():
        low_high = LIMIT_RANGES.get(key)
        if low_high is None or type(value) is not int or not low_high[0] <= value <= low_high[1]:
            raise ConnectorError("CONNECTOR_LIMITS_INVALID")
        cleaned[key] = value
    return cleaned


class ConnectorError(RuntimeError):
    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True, slots=True)
class ConnectorContext:
    tenant_id: str
    actor_id: str
    trace_id: str = "connector"
    workspace_id: str | None = None  # 호출 직전 외부 전송 판정에 쓴다(없으면 공용 주소 호출은 거부된다)
    policy_version: str | None = None


def _is_private_host(host: str) -> bool:
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)}
        except OSError:
            return False
    return any(a.is_private or a.is_loopback or a.is_link_local or a.is_reserved for a in addresses)


def validate_endpoint(url: str, *, allow_private: bool) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or len(url) > 2048:
        raise ConnectorError("CONNECTOR_ENDPOINT_INVALID")
    if not allow_private and _is_private_host(parsed.hostname):
        raise ConnectorError("CONNECTOR_ENDPOINT_PRIVATE_DENIED", 403)
    return url


def _view(row: Sequence[Any]) -> dict[str, Any]:
    return {"connector_id": row[0], "kind": row[1], "name": row[2], "endpoint_url": row[3], "protocol_version": row[4], "allowed_tools": list(row[5] or []),
            "allowed_scopes": row[6], "virtual": bool(row[7]), "status": row[8], "last_checked_at": row[9].isoformat() if isinstance(row[9], datetime) else None,
            "error_code": row[10], "version": int(row[11]), "has_credential": bool(row[12]),
            "limits": dict(row[13]) if len(row) > 13 and isinstance(row[13], Mapping) else {}}


_COLUMNS = ("connector_id,kind,name,endpoint_url,protocol_version,allowed_tools,allowed_scopes,is_virtual,status,last_checked_at,error_code,version,"
            "credential_ciphertext IS NOT NULL,call_limits")


class KnowledgeConnectorService:
    def __init__(self, cloud_store, cipher: ProviderCredentialCipher, *, production: bool = False, allow_private: bool = False,
                 call_timeout_seconds: float = 25.0, clock=None, egress_gate=None) -> None:  # type: ignore[no-untyped-def]
        self._store = cloud_store
        self._cipher = cipher
        self._production = production
        self._allow_private = allow_private
        self._timeout = call_timeout_seconds
        self._egress_gate = egress_gate
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._clients: dict[tuple[str, str, int], McpClient] = {}

    @staticmethod
    def _scope(context: ConnectorContext, capability: str) -> CloudAccessContext:
        return CloudAccessContext(context.tenant_id, "connectors", context.actor_id, capability)

    # ------------------------------------------------------------ 관리
    def register(self, context: ConnectorContext, spec: Mapping[str, Any]) -> dict[str, Any]:
        kind = spec.get("kind")
        if kind not in KINDS:
            raise ConnectorError("CONNECTOR_KIND_INVALID")
        name = str(spec.get("name", "")).strip()
        if not 1 <= len(name) <= 120:
            raise ConnectorError("CONNECTOR_NAME_INVALID")
        virtual = bool(spec.get("virtual", False))
        if virtual and self._production:
            raise ConnectorError("VIRTUAL_CONNECTOR_FORBIDDEN_IN_PRODUCTION", 403)
        endpoint = validate_endpoint(str(spec.get("endpoint_url", "")), allow_private=self._allow_private or virtual)
        tools = list(dict.fromkeys(spec.get("allowed_tools") or sorted(KIND_TOOLS[kind])))
        if not set(tools) <= KIND_TOOLS[kind]:
            raise ConnectorError("CONNECTOR_TOOL_NOT_ALLOWED")
        scopes = spec.get("allowed_scopes") or []
        if not isinstance(scopes, list) or any(not isinstance(s, dict) for s in scopes):
            raise ConnectorError("CONNECTOR_SCOPE_INVALID")
        token = spec.get("token")
        connector_id = "kc-" + secrets.token_hex(16)
        sealed = None
        if token:
            if not isinstance(token, str) or not 8 <= len(token) <= 8192:
                raise ConnectorError("CONNECTOR_CREDENTIAL_INVALID")
            sealed = self._cipher.encrypt(connector_id, _PROVIDER_CODE, 1, token.encode("utf-8"))
        with self._store._transaction(self._scope(context, "connector.write")) as connection:
            row = connection.execute(
                "INSERT INTO knowledge_connectors(tenant_id,connector_id,kind,name,endpoint_url,auth_kind,credential_ciphertext,credential_nonce,credential_version,"
                "encryption_key_version,allowed_tools,allowed_scopes,is_virtual,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                f"RETURNING {_COLUMNS}",
                (context.tenant_id, connector_id, kind, name, endpoint, "bearer" if sealed else "none", None if sealed is None else sealed.ciphertext,
                 None if sealed is None else sealed.nonce, 1 if sealed else 0, None if sealed is None else sealed.encryption_key_version, tools,
                 Jsonb(scopes), virtual, context.actor_id)).fetchone()
        return _view(row)

    def list(self, context: ConnectorContext) -> list[dict[str, Any]]:
        with self._store._transaction(self._scope(context, "connector.read")) as connection:
            rows = connection.execute(f"SELECT {_COLUMNS} FROM knowledge_connectors WHERE tenant_id=%s ORDER BY created_at,connector_id", (context.tenant_id,)).fetchall()
        return [_view(r) for r in rows]

    def get(self, context: ConnectorContext, connector_id: str) -> dict[str, Any]:
        with self._store._transaction(self._scope(context, "connector.read")) as connection:
            row = connection.execute(f"SELECT {_COLUMNS} FROM knowledge_connectors WHERE tenant_id=%s AND connector_id=%s", (context.tenant_id, connector_id)).fetchone()
        if row is None:
            raise ConnectorError("CONNECTOR_NOT_FOUND", 404)
        return _view(row)

    def set_allowed_tools(self, context: ConnectorContext, connector_id: str, tools: Sequence[str], expected_version: int) -> dict[str, Any]:
        current = self.get(context, connector_id)
        if not set(tools) <= KIND_TOOLS[current["kind"]]:
            raise ConnectorError("CONNECTOR_TOOL_NOT_ALLOWED")
        with self._store._transaction(self._scope(context, "connector.write")) as connection:
            row = connection.execute(
                f"UPDATE knowledge_connectors SET allowed_tools=%s,version=version+1,updated_at=now() WHERE tenant_id=%s AND connector_id=%s AND version=%s RETURNING {_COLUMNS}",
                (list(dict.fromkeys(tools)), context.tenant_id, connector_id, expected_version)).fetchone()
        if row is None:
            raise ConnectorError("CONNECTOR_VERSION_CONFLICT", 409)
        self._clients = {k: v for k, v in self._clients.items() if k[:2] != (context.tenant_id, connector_id)}
        return _view(row)

    def set_limits(self, context: ConnectorContext, connector_id: str, limits: Any, expected_version: int) -> dict[str, Any]:
        cleaned = validate_limits(limits)
        with self._store._transaction(self._scope(context, "connector.write")) as connection:
            row = connection.execute(
                f"UPDATE knowledge_connectors SET call_limits=%s,version=version+1,updated_at=now() WHERE tenant_id=%s AND connector_id=%s AND version=%s RETURNING {_COLUMNS}",
                (Jsonb(cleaned), context.tenant_id, connector_id, expected_version)).fetchone()
        if row is None:
            raise ConnectorError("CONNECTOR_VERSION_CONFLICT", 409)
        self._clients = {k: v for k, v in self._clients.items() if k[:2] != (context.tenant_id, connector_id)}
        return _view(row)

    def disconnect(self, context: ConnectorContext, connector_id: str) -> None:
        with self._store._transaction(self._scope(context, "connector.write")) as connection:
            row = connection.execute("DELETE FROM knowledge_connectors WHERE tenant_id=%s AND connector_id=%s RETURNING connector_id", (context.tenant_id, connector_id)).fetchone()
        if row is None:
            raise ConnectorError("CONNECTOR_NOT_FOUND", 404)
        self._clients = {k: v for k, v in self._clients.items() if k[:2] != (context.tenant_id, connector_id)}

    # ------------------------------------------------------------ 연결 확인·호출
    def _client(self, context: ConnectorContext, connector_id: str) -> tuple[McpClient, dict[str, Any]]:
        with self._store._transaction(self._scope(context, "connector.read")) as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS},credential_ciphertext,credential_nonce,credential_version,encryption_key_version FROM knowledge_connectors WHERE tenant_id=%s AND connector_id=%s",
                (context.tenant_id, connector_id)).fetchone()
        if row is None:
            raise ConnectorError("CONNECTOR_NOT_FOUND", 404)
        view = _view(row[:14])
        if view["virtual"] and self._production:
            raise ConnectorError("VIRTUAL_CONNECTOR_FORBIDDEN_IN_PRODUCTION", 403)
        key = (context.tenant_id, connector_id, view["version"])
        client = self._clients.get(key)
        if client is None:
            token = None
            if row[14] is not None:
                sealed = EncryptedCredential(bytes(row[14]), bytes(row[15]), int(row[17]), int(row[16]), 1)
                try:
                    token = self._cipher.decrypt(connector_id, _PROVIDER_CODE, int(row[16]), sealed).decode("utf-8")
                except Exception:
                    raise ConnectorError("CONNECTOR_CREDENTIAL_UNAVAILABLE", 503) from None
            validate_endpoint(view["endpoint_url"], allow_private=self._allow_private or view["virtual"])
            limits = view["limits"]
            transport_options = {"timeout_seconds": float(limits.get("timeout_seconds", self._timeout))}
            if "max_response_bytes" in limits:
                transport_options["max_response_bytes"] = int(limits["max_response_bytes"])
            client_options = {}
            if "max_concurrent" in limits:
                client_options["max_concurrent"] = int(limits["max_concurrent"])
            if "calls_per_minute" in limits:
                client_options["per_minute"] = int(limits["calls_per_minute"])
            client = McpClient(HttpJsonRpcTransport(view["endpoint_url"], token=token, **transport_options), allowed_tools=view["allowed_tools"], **client_options)
            self._clients[key] = client
        return client, view

    def verify(self, context: ConnectorContext, connector_id: str) -> dict[str, Any]:
        """연결 → 도구 목록 → 허용 도구가 서버에 있는지 대조. 결과를 저장한다."""
        status, error, protocol = "verified", None, None
        try:
            client, view = self._client(context, connector_id)
            protocol = client.connect().protocol_version
            names = {t["name"] for t in client.list_tools()}
            if not set(view["allowed_tools"]) <= names:
                status, error = "failed", "CONNECTOR_TOOLS_MISSING"
        except McpError as exc:
            status, error = "failed", exc.code
        with self._store._transaction(self._scope(context, "connector.write")) as connection:
            row = connection.execute(
                f"UPDATE knowledge_connectors SET status=%s,error_code=%s,protocol_version=COALESCE(%s,protocol_version),last_checked_at=now(),updated_at=now() "
                f"WHERE tenant_id=%s AND connector_id=%s RETURNING {_COLUMNS}", (status, error, protocol, context.tenant_id, connector_id)).fetchone()
        if row is None:
            raise ConnectorError("CONNECTOR_NOT_FOUND", 404)
        return _view(row)

    def call(self, context: ConnectorContext, connector_id: str, tool: str, arguments: Mapping[str, Any]) -> McpToolResult:
        client, view = self._client(context, connector_id)
        if view["status"] == "disabled":
            raise ConnectorError("CONNECTOR_DISABLED", 409)
        # 허용 도구는 호출마다 DB에서 읽은 판본으로 만든 클라이언트가 확인한다(판본이 바뀌면 클라이언트를 다시 만든다).
        self._authorize_egress(context, view, arguments)
        scopes = view["allowed_scopes"] or []
        pair = {k: arguments[k] for k in ("project_id", "work_package_id") if k in arguments}
        if pair and scopes and pair not in scopes:
            raise ConnectorError("CONNECTOR_SCOPE_DENIED", 403)
        if client._connection is None:  # noqa: SLF001
            client.connect()
        return client.call_tool(tool, arguments)

    def _authorize_egress(self, context: ConnectorContext, view: Mapping[str, Any], arguments: Mapping[str, Any]) -> None:
        if self._egress_gate is None or view["virtual"]:
            return
        host = urlsplit(view["endpoint_url"]).hostname or ""
        if _is_private_host(host):
            return
        import json
        allowed, reason = self._egress_gate.authorize(context, view, len(json.dumps(arguments, ensure_ascii=False).encode("utf-8")))
        if not allowed:
            raise ConnectorError("CONNECTOR_EGRESS_DENIED", 403)

    @staticmethod
    def arguments_fingerprint(arguments: Mapping[str, Any]) -> str:
        import json
        return hashlib.sha256(json.dumps(arguments, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def settings_from_env() -> dict[str, Any]:
    # 가상 서버 허용 스위치는 WSL 시험 스택에서만 켠다(기본 false). 운영 Compose는 설정하지 않는다.
    production = (os.environ.get("DAON_RUNTIME_PROFILE") == "production" or os.environ.get("ENV") == "production") and \
        os.environ.get("DAON_MCP_ALLOW_VIRTUAL_QA", "false") != "true"
    return {"production": production,
            "allow_private": os.environ.get("DAON_MCP_ALLOW_PRIVATE_ENDPOINTS", "false") == "true",
            "call_timeout_seconds": float(os.environ.get("DAON_MCP_CALL_TIMEOUT_SECONDS", "25"))}
