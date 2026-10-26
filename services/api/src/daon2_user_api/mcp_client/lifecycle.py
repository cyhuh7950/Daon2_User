"""판본 어댑터: 서버가 알리는 판본으로 협상한다(설계서 §7A.3.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .errors import McpError
from .transport import HttpJsonRpcTransport

SUPPORTED = ("2026-07-28", "2025-11-25", "2025-06-18")
CLIENT_INFO = {"name": "daon2-user", "version": "0.1.0"}


@dataclass(frozen=True, slots=True)
class Connection:
    protocol_version: str
    session_id: str | None
    server_info: Mapping[str, object] = field(default_factory=dict)
    capabilities: Mapping[str, object] = field(default_factory=dict)


def _negotiate(version: object) -> str:
    if version not in SUPPORTED:
        raise McpError("MCP_VERSION_UNSUPPORTED")
    return str(version)


class DiscoverAdapter:
    """2026-07-28: 세션 없는 server/discover."""

    def connect(self, transport: HttpJsonRpcTransport) -> Connection:
        result, _ = transport.request("server/discover", {"supportedVersions": list(SUPPORTED), "clientInfo": CLIENT_INFO})
        offered = result.get("supportedVersions")
        versions = [v for v in offered if v in SUPPORTED] if isinstance(offered, list) else []
        version = _negotiate(versions[0] if versions else result.get("protocolVersion"))
        return Connection(version, None, result.get("serverInfo") or {}, result.get("capabilities") or {})


class InitializeAdapter:
    """2025-06-18 / 2025-11-25: initialize + notifications/initialized."""

    def connect(self, transport: HttpJsonRpcTransport) -> Connection:
        result, headers = transport.request("initialize", {"protocolVersion": SUPPORTED[1], "capabilities": {}, "clientInfo": CLIENT_INFO})
        version = _negotiate(result.get("protocolVersion"))
        session = headers.get("mcp-session-id")
        transport.notify("notifications/initialized", protocol_version=version, session_id=session)
        return Connection(version, session, result.get("serverInfo") or {}, result.get("capabilities") or {})


def connect(transport: HttpJsonRpcTransport) -> Connection:
    """discover를 먼저 시도하고, 서버가 모르면 initialize로 되돌아간다."""
    try:
        return DiscoverAdapter().connect(transport)
    except McpError as error:
        if error.code in {"MCP_METHOD_NOT_FOUND", "MCP_RPC_ERROR", "MCP_NOT_FOUND", "MCP_RESPONSE_INVALID"}:
            return InitializeAdapter().connect(transport)
        raise
