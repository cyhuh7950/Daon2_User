"""HTTP JSON-RPC 전송. 응답 크기 상한, 연결·호출 타임아웃, 리다이렉트 금지, 토큰 비노출."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Mapping
from urllib.parse import urlsplit

from .errors import McpError

MAX_RESPONSE_BYTES = 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class HttpJsonRpcTransport:
    def __init__(self, endpoint: str, *, token: str | None = None, timeout_seconds: float = 25.0,
                 max_response_bytes: int = MAX_RESPONSE_BYTES, extra_headers: Mapping[str, str] | None = None) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise McpError("MCP_ENDPOINT_INVALID")
        self._endpoint = endpoint
        self._token = token
        self._timeout = timeout_seconds
        self._max = max_response_bytes
        self._extra = dict(extra_headers or {})
        self._opener = urllib.request.build_opener(_NoRedirect())
        self._counter = 0

    def __repr__(self) -> str:  # 토큰을 노출하지 않는다.
        return f"HttpJsonRpcTransport(endpoint={self._endpoint!r}, token={'set' if self._token else 'none'})"

    def request(self, method: str, params: Mapping[str, Any] | None = None, *, protocol_version: str | None = None,
                session_id: str | None = None) -> tuple[Mapping[str, Any], Mapping[str, str]]:
        self._counter += 1
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": self._counter, "method": method}
        if params is not None:
            body["params"] = dict(params)
        return self._post(body, protocol_version, session_id, expect_result=True)

    def notify(self, method: str, params: Mapping[str, Any] | None = None, *, protocol_version: str | None = None,
               session_id: str | None = None) -> None:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = dict(params)
        self._post(body, protocol_version, session_id, expect_result=False)

    def _post(self, body: Mapping[str, Any], protocol_version: str | None, session_id: str | None, *, expect_result: bool):  # type: ignore[no-untyped-def]
        headers = {"Content-Type": "application/json", "Accept": "application/json", **self._extra}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if protocol_version:
            headers["MCP-Protocol-Version"] = protocol_version
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        request = urllib.request.Request(self._endpoint, data=json.dumps(body, separators=(",", ":")).encode("utf-8"), headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                raw = response.read(self._max + 1)
                response_headers = {k.lower(): v for k, v in response.headers.items()}
                status = response.status
        except urllib.error.HTTPError as error:
            code = {401: "MCP_UNAUTHENTICATED", 403: "MCP_FORBIDDEN", 404: "MCP_NOT_FOUND", 429: "MCP_RATE_LIMITED"}.get(error.code, "MCP_HTTP_ERROR")
            try:  # 서버가 JSON-RPC 오류 본문을 함께 보냈다면 그 안전 코드를 우선한다(예: SCOPE_FORBIDDEN).
                detail = json.loads(error.read(65536).decode("utf-8")).get("error", {}).get("data", {}).get("code")
                if isinstance(detail, str) and detail.isupper() and len(detail) <= 64:
                    code = detail
            except (ValueError, AttributeError, OSError):
                pass
            raise McpError(code, retryable=error.code in {408, 429} or error.code >= 500, status=error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise McpError("MCP_UNAVAILABLE", retryable=True) from None
        if len(raw) > self._max:
            raise McpError("MCP_RESPONSE_TOO_LARGE")
        if not expect_result:
            return {}, response_headers
        if status == 202 or not raw:
            return {}, response_headers
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise McpError("MCP_RESPONSE_INVALID") from None
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            raise McpError("MCP_RESPONSE_INVALID")
        if "error" in payload:
            error = payload["error"] if isinstance(payload["error"], dict) else {}
            data = error.get("data") if isinstance(error.get("data"), dict) else {}
            code = data.get("code") if isinstance(data.get("code"), str) and data["code"].isupper() else "MCP_RPC_ERROR"
            if error.get("code") == -32601:
                code = "MCP_METHOD_NOT_FOUND"
            raise McpError(code, retryable=bool(data.get("retryable", False)))
        result = payload.get("result")
        if not isinstance(result, dict):
            raise McpError("MCP_RESPONSE_INVALID")
        return result, response_headers
