"""Studio 생성용 텍스트 생성 어댑터(JSON 스키마 응답, Provider 우선순위 폴백). WO-F2 T2-03.

사용 순서(사용자 지정): 1 Media Bridge(MS) → 2 Upstage(US) → 3 OmniRoute(AF) → 4 Ollama(OL).
설정·API Key는 daon-user 방식(관리자 Provider 설정, 키는 DB 암호 저장)을 그대로 쓴다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from .cloud_storage import CloudAccessContext
from .document_understanding_adapter import DocumentUnderstandingError, UrlLibDocumentUnderstandingTransport
from .studio_egress import INTERNAL_KINDS, mask_text
from .studio_workspace import StudioContext, StudioError
from .workspace_model_defaults import WorkspaceModelContext, WorkspaceModelUnavailable

DEFAULT_PRIORITY = ("MS", "US", "AF", "OL")
CAPABILITY = "text_generation"
_PROVIDER_DEADLINE = 600.0
_THINKING_MODEL = re.compile(r"qwen3|deepseek-r1|gpt-oss|magistral", re.I)


@dataclass(frozen=True, slots=True)
class StudioPrompt:
    system: str
    user: str
    json_schema: Mapping[str, object]
    max_output_tokens: int = 2048
    timeout_seconds: float | None = None
    prompt_version: str = "studio-v1"
    schema_name: str = "studio_output"


@dataclass(frozen=True, slots=True)
class StudioGeneration:
    data: Mapping[str, object]
    usage: Mapping[str, int]
    model_id: str
    provider_code: str
    connection_short_code: str


def provider_priority() -> tuple[str, ...]:
    raw = os.environ.get("DAON_STUDIO_PROVIDER_PRIORITY", "").strip()
    if not raw:
        return DEFAULT_PRIORITY
    order = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    if not order or any(len(code) != 2 for code in order):
        raise ValueError("STUDIO_PROVIDER_PRIORITY_INVALID")
    return order


class StudioModelCatalog:
    """Studio 생성에 쓸 (연결, 모델) 후보를 우선순위대로 찾는다."""

    def __init__(self, cloud_store, *, priority: Sequence[str] | None = None) -> None:  # type: ignore[no-untyped-def]
        self._store = cloud_store
        self._priority = tuple(priority) if priority is not None else provider_priority()

    def candidates(self, context: StudioContext) -> list[tuple[str, str, str]]:
        """[(connection_id, model_id, short_code)] — Workspace 기본 모델은 같은 연결의 모델 선택에 우선한다."""
        scope = CloudAccessContext(context.tenant_id, context.workspace_id, context.actor_id, "workspace_model.resolve")
        with self._store._transaction(scope) as connection:
            rows = connection.execute(
                "SELECT c.connection_id,c.short_code,c.auto_model_id,"
                "(SELECT d.model_id FROM workspace_model_defaults d WHERE d.tenant_id=%s AND d.workspace_id=%s "
                " AND d.capability=%s AND d.connection_id=c.connection_id),"
                "ARRAY(SELECT m.model_id FROM system_provider_models m JOIN system_provider_allowed_models a "
                " ON a.connection_id=m.connection_id AND a.model_id=m.model_id WHERE m.connection_id=c.connection_id "
                " AND %s=ANY(m.effective_capabilities) AND m.catalog_status='ready' ORDER BY m.model_id) "
                "FROM system_provider_connections c WHERE c.enabled",
                (context.tenant_id, context.workspace_id, CAPABILITY, CAPABILITY)).fetchall()
        by_code: dict[str, tuple[str, str]] = {}
        for connection_id, short_code, auto_model, default_model, models in rows:
            allowed = list(models or [])
            model = (default_model if default_model in allowed else None) or (auto_model if auto_model in allowed else None) \
                or (allowed[0] if allowed else None)
            if model is not None:
                by_code[str(short_code)] = (str(connection_id), str(model))
        ordered = [(by_code[code][0], by_code[code][1], code) for code in self._priority if code in by_code]
        return ordered


def _openai_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _ollama_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/api/chat"


def _json_from_text(raw: object) -> Mapping[str, object]:
    if isinstance(raw, Mapping):
        return raw
    if not isinstance(raw, str):
        raise ValueError("STUDIO_VALIDATION_FAILED")
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("STUDIO_VALIDATION_FAILED")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("STUDIO_VALIDATION_FAILED")
    return value


class StudioTextGenerator:
    def __init__(self, resolver, catalog: StudioModelCatalog, *, transport=None, egress_gate=None,
                 schema_validator: Callable[[Mapping[str, object], Mapping[str, object]], None] | None = None) -> None:  # type: ignore[no-untyped-def]
        self._resolver = resolver
        self._catalog = catalog
        self._egress = egress_gate  # None이면 외부 Provider는 쓰지 않는다(내부 Provider만).
        self._transport = transport or UrlLibDocumentUnderstandingTransport()
        self._validate = schema_validator

    def generate(self, context: StudioContext, prompt: StudioPrompt, *, cancel_check: Callable[[], None] | None = None) -> StudioGeneration:
        candidates = self._catalog.candidates(context)
        if not candidates:
            raise StudioError("PROVIDER_UNAVAILABLE", 503)
        model_context = WorkspaceModelContext(context.tenant_id, context.workspace_id, context.actor_id, "system")
        last: StudioError | None = None
        for connection_id, model_id, short_code in candidates:
            if cancel_check is not None:
                cancel_check()
            try:
                with self._resolver.resolve(model_context, CAPABILITY, connection_id=connection_id, model_id=model_id) as model:
                    prompt_to_send, masked = self._authorize(context, model, prompt)
                    result = self._call(model, short_code, prompt_to_send)
                    return result if not masked else StudioGeneration(result.data, {**result.usage, "masked": 1}, result.model_id,
                                                                    result.provider_code, result.connection_short_code)
            except WorkspaceModelUnavailable:
                last = StudioError("PROVIDER_UNAVAILABLE", 503)  # 키 없음(개인 Provider)·비활성 등은 다음 후보로
            except StudioError as error:
                if error.code not in {"PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT", "STUDIO_VALIDATION_FAILED"}:
                    raise
                last = error
        raise last or StudioError("PROVIDER_UNAVAILABLE", 503)

    def _authorize(self, context: StudioContext, model, prompt: StudioPrompt) -> tuple[StudioPrompt, bool]:  # type: ignore[no-untyped-def]
        """외부 전송 정책 판정. 허용이 아니면 이 후보를 건너뛴다(PROVIDER_UNAVAILABLE)."""
        kind = getattr(model, "provider_kind", "external_api")
        if kind in INTERNAL_KINDS:
            return prompt, False
        if self._egress is None:
            raise StudioError("PROVIDER_UNAVAILABLE", 503)
        masked_prompt = prompt
        size = len((prompt.system + prompt.user).encode("utf-8"))
        decision = self._egress.authorize(context, model, size)
        if not decision.allowed:
            raise StudioError("PROVIDER_UNAVAILABLE", 503)
        if decision.masked:
            from dataclasses import replace
            masked_prompt = replace(prompt, user=mask_text(prompt.user))
        return masked_prompt, decision.masked

    def _call(self, model, short_code: str, prompt: StudioPrompt) -> StudioGeneration:  # type: ignore[no-untyped-def]
        last_error = "STUDIO_VALIDATION_FAILED"
        user = prompt.user
        for attempt in range(2):
            try:
                response = self._post(model, prompt, user)
                data, usage = self._parse(model, response)
                if self._validate is not None:
                    self._validate(prompt.json_schema, data)
                return StudioGeneration(data, usage, model.model_id, model.provider_code, short_code)
            except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
                last_error = "STUDIO_VALIDATION_FAILED"
                user = prompt.user + "\n\n[이전 응답이 형식 오류였습니다. 지정한 JSON 스키마만 정확히 반환하세요.]"
                _ = error
        raise StudioError(last_error, 502)

    def _post(self, model, prompt: StudioPrompt, user: str) -> Mapping[str, object]:  # type: ignore[no-untyped-def]
        parsed = urlsplit(model.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise StudioError("PROVIDER_UNAVAILABLE", 503)
        timeout = prompt.timeout_seconds if prompt.timeout_seconds is not None else _PROVIDER_DEADLINE
        messages = [{"role": "system", "content": prompt.system}, {"role": "user", "content": user}]
        try:
            if model.provider_code == "OLLAMA":
                payload: dict[str, Any] = {"model": model.model_id, "messages": messages, "stream": False,
                                           "format": dict(prompt.json_schema),
                                           "options": {"temperature": 0.2, "num_predict": prompt.max_output_tokens}}
                if _THINKING_MODEL.search(model.model_id):
                    payload["think"] = False  # 사고 모델은 추론에 출력 토큰을 소모해 JSON이 비는 일을 막는다
                return self._transport.post_json_no_auth(url=_ollama_url(model.base_url), payload=payload, timeout_seconds=timeout)
            # Media Bridge 등 게이트웨이는 temperature를 거부한다(downstream_payload_invalid) — 기존 QA 어댑터와 같이 보내지 않는다.
            payload = {"model": model.model_id, "messages": messages, "max_tokens": prompt.max_output_tokens,
                       "response_format": {"type": "json_schema", "json_schema": {"name": prompt.schema_name, "strict": False,
                                                                                    "schema": dict(prompt.json_schema)}}}
            key = model.credential_text(required=False) if hasattr(model, "credential_text") else None
            if key:
                return self._transport.post_json(url=_openai_url(model.base_url), api_key=key, payload=payload, timeout_seconds=timeout)
            return self._transport.post_json_no_auth(url=_openai_url(model.base_url), payload=payload, timeout_seconds=timeout)
        except DocumentUnderstandingError as error:
            if error.retryable:
                raise StudioError("PROVIDER_UNAVAILABLE", 503) from None
            raise StudioError("PROVIDER_UNAVAILABLE", 502) from None

    @staticmethod
    def _parse(model, response: Mapping[str, object]) -> tuple[Mapping[str, object], Mapping[str, int]]:  # type: ignore[no-untyped-def]
        if model.provider_code == "OLLAMA":
            message = response["message"]
            data = _json_from_text(message["content"])  # type: ignore[index]
            usage = {"prompt_tokens": int(response.get("prompt_eval_count", 0) or 0),
                     "completion_tokens": int(response.get("eval_count", 0) or 0)}
            return data, usage
        choices = response["choices"]
        data = _json_from_text(choices[0]["message"]["content"])  # type: ignore[index]
        raw_usage = response.get("usage", {})
        usage = {k: int(v) for k, v in raw_usage.items() if isinstance(v, int)} if isinstance(raw_usage, Mapping) else {}
        return data, usage
