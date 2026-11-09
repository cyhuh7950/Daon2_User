"""OAuth client credentials 토큰 발급(WO-K2 T2). 값은 호출 직전에만 쓰고 repr·오류에 노출하지 않는다."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlencode

from .errors import McpError
from .transport import _NoRedirect

MAX_TOKEN_RESPONSE_BYTES = 64 * 1024
MAX_TOKEN_LIFETIME_SECONDS = 300
REFRESH_MARGIN_SECONDS = 30


class ClientCredentialsTokenSource:
    """호출 대상 하나(resource)와 그 scope에 대한 토큰을 받아 만료 직전까지 재사용한다."""

    def __init__(self, *, token_url: str, client_id: str, client_secret: str, resource: str, scope: str, timeout_seconds: float = 10.0,
                 opener: Any = None, clock: Callable[[], float] = time.monotonic) -> None:
        self._url = token_url
        self._form = urlencode({"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret,
                                "resource": resource, "scope": scope}).encode("ascii")
        self._timeout = timeout_seconds
        self._opener = opener or urllib.request.build_opener(_NoRedirect())
        self._clock = clock
        self._lock = threading.Lock()
        self._token: str | None = None
        self._refresh_at = 0.0

    def __repr__(self) -> str:
        return f"ClientCredentialsTokenSource(token_url={self._url!r})"

    def token(self) -> str:
        with self._lock:
            if self._token is None or self._clock() >= self._refresh_at:
                self._token, lifetime = self._issue()
                self._refresh_at = self._clock() + min(lifetime, MAX_TOKEN_LIFETIME_SECONDS) - REFRESH_MARGIN_SECONDS
            return self._token

    def _issue(self) -> tuple[str, int]:
        request = urllib.request.Request(self._url, data=self._form, method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                raw = response.read(MAX_TOKEN_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code in {400, 401, 403}:
                raise McpError("MCP_TOKEN_REJECTED", status=error.code) from None
            raise McpError("MCP_TOKEN_UNAVAILABLE", retryable=True, status=error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise McpError("MCP_TOKEN_UNAVAILABLE", retryable=True) from None
        try:
            payload = json.loads(raw.decode("utf-8")) if len(raw) <= MAX_TOKEN_RESPONSE_BYTES else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        token = payload.get("access_token") if isinstance(payload, dict) else None
        lifetime = payload.get("expires_in") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token or type(lifetime) is not int or lifetime <= 0:
            raise McpError("MCP_TOKEN_INVALID")
        return token, lifetime
