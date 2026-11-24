"""OpenAI chat/completions 요청 본문 보정.

OpenAI(api.openai.com)의 새 세대 모델은 출력 한도 매개변수 max_tokens를 받지 않고(400 unsupported_parameter)
max_completion_tokens만 받는다. OpenAI는 기존 모델도 max_completion_tokens를 받으므로 주소로 구분한다.
다른 OpenAI 호환 서버(Media Bridge·Gemini 호환·Ollama 등)는 max_tokens를 그대로 보낸다.
"""
from __future__ import annotations

from typing import Mapping
from urllib.parse import urlsplit

OPENAI_API_HOST = "api.openai.com"


def is_openai_api(url: str) -> bool:
    try:
        return urlsplit(url).hostname == OPENAI_API_HOST
    except ValueError:
        return False


def openai_chat_payload(
    url: str, payload: Mapping[str, object], *, min_completion_tokens: int = 0,
) -> dict[str, object]:
    """api.openai.com이면 max_tokens를 max_completion_tokens로 바꾼 새 본문을 돌려준다(원본은 그대로).

    min_completion_tokens: 추론형 모델은 생각에도 출력 한도를 쓰므로, 아주 작은 한도(연결 확인 등)는 이 값까지 올린다.
    """
    if not is_openai_api(url) or "max_tokens" not in payload:
        return dict(payload)
    converted = {key: value for key, value in payload.items() if key != "max_tokens"}
    limit = payload["max_tokens"]
    converted["max_completion_tokens"] = max(limit, min_completion_tokens) if isinstance(limit, int) else limit
    return converted
