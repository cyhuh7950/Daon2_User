"""OpenAI(api.openai.com) chat/completions는 새 모델이 max_tokens를 거부하므로 max_completion_tokens로 보낸다.

다른 OpenAI 호환 서버(Media Bridge·Gemini 호환·Ollama 등)는 지금처럼 max_tokens를 그대로 보낸다.
"""
from __future__ import annotations

import pathlib

import pytest

from daon2_user_api.openai_chat import openai_chat_payload
from daon2_user_api.provider_connection_adapters import AdapterRegistry, TransportResponse
from test_provider_connection_adapters import FakeTransport, RequestRecord, TEST_CREDENTIAL, connection

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "daon2_user_api"


def test_openai_url_uses_max_completion_tokens() -> None:
    payload = {"model": "gpt-6.1-sol", "messages": [], "max_tokens": 512}
    assert openai_chat_payload("https://api.openai.com/v1/chat/completions", payload) == {
        "model": "gpt-6.1-sol", "messages": [], "max_completion_tokens": 512}
    assert payload["max_tokens"] == 512, "원래 요청 본문은 바꾸지 않는다"


def test_minimum_is_applied_only_for_openai() -> None:
    assert openai_chat_payload("https://api.openai.com/v1/chat/completions", {"max_tokens": 16},
                               min_completion_tokens=1024) == {"max_completion_tokens": 1024}
    assert openai_chat_payload("https://media-bridge.example/v1/chat/completions", {"max_tokens": 16},
                               min_completion_tokens=1024) == {"max_tokens": 16}


@pytest.mark.parametrize("url", [
    "https://media-bridge-gateway.sinsan.kr/v1/chat/completions",
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "https://api.openai.com.evil.example/v1/chat/completions",
    "http://localhost:11434/v1/chat/completions",
])
def test_other_servers_keep_max_tokens(url: str) -> None:
    assert openai_chat_payload(url, {"max_tokens": 512}) == {"max_tokens": 512}


def test_payload_without_max_tokens_is_unchanged() -> None:
    assert openai_chat_payload("https://api.openai.com/v1/chat/completions", {"model": "m"}) == {"model": "m"}


def test_connection_probe_to_openai_sends_max_completion_tokens() -> None:
    class Capture(FakeTransport):
        def request(self, method, url, headers, body, timeout_seconds, *, follow_redirects):
            self.requests.append(RequestRecord(method, url, dict(headers), dict(body) if body else None,
                                               timeout_seconds, follow_redirects))
            return TransportResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    transport = Capture()
    adapter = AdapterRegistry(transport).adapter("CUSTOM", "openai_compatible")
    adapter.verify_models(connection("CUSTOM", base_url="https://api.openai.com/v1"), TEST_CREDENTIAL, ("gpt-6.1-sol",))
    body = transport.requests[0].body
    assert "max_tokens" not in body
    assert body["max_completion_tokens"] >= 1024


@pytest.mark.parametrize("module", [
    "question_answering.py", "studio_text_generation.py", "text_document_understanding.py",
    "pdf_text_understanding.py", "model_selection.py", "provider_connection_adapters.py",
])
def test_every_openai_compatible_call_site_uses_the_helper(module: str) -> None:
    source = (SRC / module).read_text(encoding="utf-8")
    assert "openai_chat_payload(" in source, f"{module}이 OpenAI 출력 한도 변환을 거치지 않는다"
