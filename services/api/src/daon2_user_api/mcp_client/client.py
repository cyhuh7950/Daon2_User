"""McpClient: connect / list_tools / call_tool / read_resource. 선언된 도구만 호출하고 결과는 신뢰하지 않는 데이터로 다룬다."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .errors import McpError
from .lifecycle import Connection, connect
from .schemas import validate
from .transport import HttpJsonRpcTransport


@dataclass(frozen=True, slots=True)
class McpToolResult:
    structured: Mapping[str, Any]
    is_error: bool
    protocol_version: str


class McpClient:
    def __init__(self, transport: HttpJsonRpcTransport, *, allowed_tools: Sequence[str] | None = None, max_concurrent: int = 4,
                 per_minute: int = 30, clock=time.monotonic) -> None:  # type: ignore[no-untyped-def]
        self._transport = transport
        self._allowed = frozenset(allowed_tools) if allowed_tools is not None else None
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._per_minute = per_minute
        self._calls: deque[float] = deque()
        self._clock = clock
        self._lock = threading.Lock()
        self._connection: Connection | None = None
        self._tools: dict[str, Mapping[str, Any]] = {}

    @property
    def connection(self) -> Connection:
        if self._connection is None:
            raise McpError("MCP_NOT_CONNECTED")
        return self._connection

    def connect(self) -> Connection:
        self._connection = connect(self._transport)
        return self._connection

    def list_tools(self) -> list[Mapping[str, Any]]:
        conn = self.connection
        result, _ = self._transport.request("tools/list", {}, protocol_version=conn.protocol_version, session_id=conn.session_id)
        tools = result.get("tools")
        if not isinstance(tools, list) or any(not isinstance(t, dict) or not isinstance(t.get("name"), str) for t in tools):
            raise McpError("MCP_RESPONSE_INVALID")
        self._tools = {t["name"]: t for t in tools}
        return list(tools)

    def _throttle(self) -> None:
        now = self._clock()
        with self._lock:
            while self._calls and now - self._calls[0] > 60:
                self._calls.popleft()
            if len(self._calls) >= self._per_minute:
                raise McpError("LIMIT_EXCEEDED", retryable=True)
            self._calls.append(now)

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> McpToolResult:
        """선언된(허용된) 도구만 호출한다. 입력·출력은 서버가 알린 스키마로 검증한다."""
        if self._allowed is not None and name not in self._allowed:
            raise McpError("MCP_TOOL_NOT_ALLOWED")
        if not self._tools:
            self.list_tools()
        tool = self._tools.get(name)
        if tool is None:
            raise McpError("MCP_TOOL_UNKNOWN")
        input_schema = tool.get("inputSchema")
        if isinstance(input_schema, dict) and validate(dict(arguments), input_schema):
            raise McpError("MCP_ARGUMENTS_INVALID")
        self._throttle()
        if not self._slots.acquire(blocking=False):
            raise McpError("LIMIT_EXCEEDED", retryable=True)
        try:
            conn = self.connection
            result, _ = self._transport.request("tools/call", {"name": name, "arguments": dict(arguments)},
                                                protocol_version=conn.protocol_version, session_id=conn.session_id)
        finally:
            self._slots.release()
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise McpError("MCP_RESPONSE_INVALID")
        output_schema = tool.get("outputSchema")
        if not result.get("isError") and isinstance(output_schema, dict) and validate(structured, output_schema):
            raise McpError("MCP_RESPONSE_INVALID")
        return McpToolResult(structured, bool(result.get("isError")), conn.protocol_version)

    def read_resource(self, uri: str) -> Mapping[str, Any]:
        conn = self.connection
        result, _ = self._transport.request("resources/read", {"uri": uri}, protocol_version=conn.protocol_version, session_id=conn.session_id)
        if not isinstance(result.get("contents"), list):
            raise McpError("MCP_RESPONSE_INVALID")
        return result
