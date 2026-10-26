"""설정된 기본 모델이 OpenAI 호환 Provider일 때의 Source 처리: Egress 정책 가드와 외부 텍스트 어댑터."""
from __future__ import annotations

import json

import pytest

from daon2_user_api.document_processing import DocumentProcessingContext, OriginalDocumentEgressGuard, StoredSourceDocument
from daon2_user_api.document_understanding_adapter import DocumentUnderstandingError
from daon2_user_api.egress_policy import EgressPolicyContext, EgressPolicyPayload, EgressPolicyService, ReferenceEgressPolicyRepository
from daon2_user_api.text_document_understanding import OpenAICompatibleTextDocumentAdapter
from daon2_user_api.workspace_model_defaults import ResolvedModel

HOST = "media-bridge-gateway.sinsan.kr"
BASE = f"https://{HOST}/v1"
TEXT = "제3조(면책 기간) 계약일부터 30일 이내 발생한 질병은 보장하지 않습니다.\n연락처는 010-1234-5678 입니다.\n"


def _context():
    return DocumentProcessingContext("tenant-t", "workspace-t", "actor-t", "trace-t", "policy-v1")


def _model(kind="external_api", provider="CUSTOM", base_url=BASE, key=b"synthetic-key"):
    return ResolvedModel("provider-mb", provider, "uss/solar-pro4", "text_generation", base_url, 1, 1, 1, kind, "provider", True, bytearray(key))


def _guard(payload):
    repository = ReferenceEgressPolicyRepository()
    policy_context = EgressPolicyContext("tenant-t", "tenant-t", "workspace-t", "actor-t", "trace-t", "policy-v1")
    for scope in ("organization", "workspace"):
        repository.seed(policy_context, scope_type=scope, payload=payload)
    return OriginalDocumentEgressGuard(EgressPolicyService(repository))


def _allow(**overrides):
    values = dict(mode="allow_approved_external", allowed_provider_kinds=("external_api",), allowed_destinations=(HOST,), classification="internal",
                  max_bytes=65536, masking_required=True, redaction_required=True, required_approver="none")
    values.update(overrides)
    return EgressPolicyPayload(**values)


def test_guard_allows_external_only_under_policy_destination_and_size():
    _guard(_allow()).authorize(_context(), (_model(),), 100)
    cases = (
        (_allow(), None, "EGRESS_POLICY_DENIED"),                          # 전송 바이트를 모르면 거부
        (EgressPolicyPayload.deny_external(), 100, "EGRESS_POLICY_DENIED"),  # 정책이 외부 전송을 막음
        (_allow(allowed_destinations=("other.example",)), 100, "EGRESS_POLICY_DENIED"),
        (_allow(max_bytes=50), 100, "EGRESS_MAX_BYTES_EXCEEDED"),
        (_allow(required_approver="organization_admin"), 100, "EGRESS_POLICY_DENIED"),  # 추가 인증 후 허용 모드: 문서 처리는 외부 전송 안 함
    )
    for payload, size, code in cases:
        with pytest.raises(DocumentUnderstandingError, match=code):
            _guard(payload).authorize(_context(), (_model(),), size)


def test_guard_without_policy_service_never_allows_external_and_internal_stays_allowed():
    with pytest.raises(DocumentUnderstandingError, match="EGRESS_POLICY_UNAVAILABLE"):
        OriginalDocumentEgressGuard().authorize(_context(), (_model(),), 10)
    OriginalDocumentEgressGuard().authorize(_context(), (_model(kind="local", provider="OLLAMA", base_url="https://ollama.internal"),), None)


class Transport:
    def __init__(self, content):
        self.content, self.calls = content, []

    def post_json(self, **kwargs):
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": self.content}}], "model": "uss/solar-pro4"}


def _document(text=TEXT):
    return StoredSourceDocument("source-txt", "version-txt", "약관.txt", text.encode("utf-8"), "text/plain")


def _answer(fact):
    return json.dumps({"title": "약관", "summary": "면책 기간을 설명한다.", "key_facts": [fact]}, ensure_ascii=False)


def test_external_adapter_uses_openai_chat_with_key_masks_pii_and_returns_grounded_result():
    transport = Transport(_answer("제3조(면책 기간) 계약일부터 30일 이내 발생한 질병은 보장하지 않습니다."))
    result = OpenAICompatibleTextDocumentAdapter(transport).understand(_document(), _model(), _context())
    call = transport.calls[0]
    assert call["url"] == f"{BASE}/chat/completions" and call["api_key"] == "synthetic-key"
    sent = json.dumps(call["payload"], ensure_ascii=False)
    assert "010-1234-5678" not in sent and "[전화번호]" in sent
    assert "temperature" not in call["payload"]
    assert result.status == "ready" and result.lineage["provider_code"] == "CUSTOM" and result.lineage["semantic_model_id"] == "uss/solar-pro4"
    assert result.parser.page_texts[0][1].startswith("제3조")


def test_external_adapter_accepts_fenced_json_and_rejects_ungrounded_or_invalid_answers():
    fenced = "```json\n" + _answer("제3조(면책 기간) 계약일부터 30일 이내 발생한 질병은 보장하지 않습니다.") + "\n```"
    assert OpenAICompatibleTextDocumentAdapter(Transport(fenced)).understand(_document(), _model(), _context()).status == "ready"
    with pytest.raises(DocumentUnderstandingError, match="TEXT_UNDERSTANDING_UNGROUNDED"):
        OpenAICompatibleTextDocumentAdapter(Transport(_answer("원문에 없는 사실"))).understand(_document(), _model(), _context())
    for bad in ("not json", json.dumps({"title": "x"})):
        with pytest.raises(DocumentUnderstandingError, match="TEXT_UNDERSTANDING_RESPONSE_INVALID"):
            OpenAICompatibleTextDocumentAdapter(Transport(bad)).understand(_document(), _model(), _context())


def test_external_adapter_refuses_ollama_models_and_bad_input():
    with pytest.raises(DocumentUnderstandingError, match="DOCUMENT_PROVIDER_ADAPTER_UNAVAILABLE"):
        OpenAICompatibleTextDocumentAdapter(Transport("{}")).understand(_document(), _model(kind="local", provider="OLLAMA"), _context())
    with pytest.raises(DocumentUnderstandingError, match="TEXT_UNDERSTANDING_ENCODING_INVALID"):
        OpenAICompatibleTextDocumentAdapter(Transport("{}")).understand(
            StoredSourceDocument("s", "v", "a.txt", b"\xff\xfe", "text/plain"), _model(), _context())
