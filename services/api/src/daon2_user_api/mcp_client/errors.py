from __future__ import annotations


class McpError(RuntimeError):
    """안전한 코드만 담는다. 토큰·질문·본문은 오류에 포함하지 않는다."""

    def __init__(self, code: str, *, retryable: bool = False, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.status = status
