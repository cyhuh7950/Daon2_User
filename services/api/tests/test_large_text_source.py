"""큰 텍스트 소스(WO-N1 NB4-F1b): 상한 2 MiB, 모델에는 앞부분(32 KiB 이하)만, 색인·근거 구간은 본문 전체."""
from __future__ import annotations

import json
import time
import unittest
from contextlib import contextmanager

from daon2_user_api import text_document_understanding as tdu
from daon2_user_api import text_source
from daon2_user_api.document_index_postgres import PostgresDocumentIndex
from daon2_user_api.document_processing import DocumentProcessingContext, DocumentProcessingService, StoredSourceDocument
from daon2_user_api.document_understanding_adapter import DocumentUnderstandingError
from daon2_user_api.text_document_understanding import (
    OllamaTextDocumentAdapter, OpenAICompatibleTextDocumentAdapter, text_understanding_head,
)
from daon2_user_api.text_source import TEXT_SOURCE_MAX_BYTES, TextSourceError
from daon2_user_api.workspace_model_defaults import ResolvedModel

MIB2 = 2 * 1024 * 1024
KIB32 = 32 * 1024
FIRST = "제1조(목적) 이 문서는 큰 텍스트 소스 시험을 위한 합성 약관입니다."
TAIL = "부칙 끝 표식 ZEBRA-TAIL-77 은 문서 맨 뒤에만 있는 문장입니다."
CTX = DocumentProcessingContext("tenant-t", "workspace-t", "actor-t", "trace-t", "policy-v1")


def big_text(target_bytes: int = 200 * 1024, *, tail: str = TAIL) -> str:
    lines = [FIRST]
    size = len(FIRST.encode())
    number = 2
    while size < target_bytes:
        line = f"제{number}조 계약 당사자는 합성 조항 {number}번을 성실히 지킨다. 가나다라마바사 아자차카타파하."
        lines.append(line)
        size += len(line.encode()) + 1
        number += 1
    lines.append(tail)
    return "\n".join(lines)


def document(text: str, filename: str = "large.txt") -> StoredSourceDocument:
    return StoredSourceDocument("source-big", "source-version-big", filename, text.encode("utf-8"), "text/plain")


def local_model() -> ResolvedModel:
    return ResolvedModel("ollama-1", "OLLAMA", "llama3.2:3b", "text_generation", "http://ollama.internal:11434",
                         0, 1, 1, "local", "provider", True, None)


def external_model() -> ResolvedModel:
    return ResolvedModel("provider-mb", "CUSTOM", "uss/solar-pro4", "text_generation", "https://gateway.example/v1",
                         1, 1, 1, "external_api", "provider", True, bytearray(b"synthetic-key"))


def answer(facts, summary="합성 약관의 목적을 설명한다."):
    return json.dumps({"title": "큰 약관", "summary": summary, "key_facts": list(facts)}, ensure_ascii=False)


class OllamaTransport:
    def __init__(self, facts=(FIRST,), summary="합성 약관의 목적을 설명한다."):
        self.facts, self.summary, self.calls = facts, summary, []

    def post_json_no_auth(self, **kwargs):
        self.calls.append(kwargs)
        return {"message": {"content": answer(self.facts, self.summary)}, "model": "llama3.2:3b"}

    def sent(self) -> str:
        return self.calls[0]["payload"]["messages"][1]["content"]


class OpenAITransport:
    def __init__(self, facts=(FIRST,), summary="합성 약관의 목적을 설명한다."):
        self.facts, self.summary, self.calls = facts, summary, []

    def post_json(self, **kwargs):
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": answer(self.facts, self.summary)}}], "model": "uss/solar-pro4"}

    post_json_no_auth = post_json

    def sent(self) -> str:
        return self.calls[0]["payload"]["messages"][1]["content"]


class LimitTests(unittest.TestCase):
    def test_text_source_and_txt_understanding_share_the_2_mib_limit(self):
        self.assertEqual(TEXT_SOURCE_MAX_BYTES, MIB2)
        self.assertEqual(tdu.TEXT_UNDERSTANDING_MAX_BYTES, MIB2)
        self.assertEqual(tdu.TEXT_SENT_MAX_BYTES, KIB32)

    def test_encode_accepts_up_to_2_mib_and_rejects_beyond(self):
        self.assertEqual(len(text_source._encode("a" * MIB2)), MIB2)
        self.assertEqual(len(text_source._encode(big_text())), len(big_text().encode()))
        with self.assertRaises(TextSourceError) as caught:
            text_source._encode("a" * (MIB2 + 1))
        self.assertEqual((caught.exception.code, caught.exception.status), ("TEXT_SOURCE_TOO_LARGE", 413))


class HeadTests(unittest.TestCase):
    def test_short_text_is_sent_whole(self):
        self.assertEqual(text_understanding_head("짧은 글\n둘째 줄"), "짧은 글\n둘째 줄")

    def test_head_is_a_prefix_within_32_kib_on_a_utf8_character_boundary(self):
        text = "가" * 20000  # 3바이트 글자: 32768은 글자 중간
        head = text_understanding_head(text)
        self.assertLessEqual(len(head.encode("utf-8")), KIB32)
        self.assertEqual(head, "가" * (KIB32 // 3))

    def test_head_drops_the_word_cut_by_the_boundary(self):
        text = big_text()
        head = text_understanding_head(text)
        self.assertLessEqual(len(head.encode("utf-8")), KIB32)
        self.assertTrue(text.startswith(head))
        self.assertTrue(head[-1].isspace())  # 경계에 걸친 낱말은 보내지 않는다


class OllamaLargeTextTests(unittest.TestCase):
    def test_only_head_is_sent_but_the_whole_text_is_kept_for_evidence(self):
        text = big_text()
        transport = OllamaTransport(facts=(FIRST, TAIL))
        result = OllamaTextDocumentAdapter(transport).understand(document(text), local_model(), CTX)
        sent = transport.sent()
        self.assertLessEqual(len(sent.encode("utf-8")), KIB32)
        self.assertTrue(text.startswith(sent))
        self.assertNotIn("ZEBRA-TAIL-77", sent)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.parser.page_texts, ((1, text),))
        self.assertEqual(result.parser.text, text)
        self.assertEqual(result.semantic.key_facts, (FIRST,))  # 보내지 않은 뒷부분 문장은 핵심 사실이 아니다
        self.assertEqual(result.lineage["sent_bytes"], str(len(sent.encode("utf-8"))))

    def test_fallback_fact_and_summary_check_use_the_sent_part(self):
        text = big_text(tail="부칙 끝 표식 ZEBRA-TAIL-77 의 기한은 9876일이다.")
        transport = OllamaTransport(facts=("부칙 끝 표식 ZEBRA-TAIL-77 의 기한은 9876일이다.",), summary="기한은 9876일이다.")
        result = OllamaTextDocumentAdapter(transport).understand(document(text), local_model(), CTX)
        self.assertEqual(result.semantic.key_facts, (FIRST,))
        self.assertEqual(result.semantic.summary, FIRST)  # 보낸 부분에 없는 숫자가 든 요약은 쓰지 않는다

    def test_exactly_2_mib_is_processed_and_beyond_is_never_sent(self):
        transport = OllamaTransport(facts=("a",))
        exact = ("a " * (MIB2 // 2))
        self.assertEqual(len(exact.encode()), MIB2)
        result = OllamaTextDocumentAdapter(transport).understand(document(exact), local_model(), CTX)
        self.assertEqual(result.status, "ready")
        self.assertLessEqual(len(transport.sent().encode()), KIB32)
        over = OllamaTransport()
        with self.assertRaises(DocumentUnderstandingError) as caught:
            OllamaTextDocumentAdapter(over).understand(document("a" * (MIB2 + 1)), local_model(), CTX)
        self.assertEqual(caught.exception.code, "TEXT_UNDERSTANDING_SIZE_UNSUPPORTED")
        self.assertEqual(over.calls, [])


class ExternalLargeTextTests(unittest.TestCase):
    def test_external_receives_a_masked_head_within_32_kib(self):
        # 앞부분 안의 전화번호와, 32 KiB 경계에 걸치는 전화번호를 둔다.
        prefix = big_text(target_bytes=KIB32 - 2000, tail="연락처 010-1234-5678 입니다.") + "\n"
        filler = "x" * (KIB32 - 5 - len(prefix.encode()) - len(" 경계번호 ".encode()))
        text = prefix + filler + " 경계번호 010-9999-8888 끝\n" + TAIL
        self.assertLess(text.encode().index(b"010-9999"), KIB32)
        self.assertGreater(text.encode().index(b"8888"), KIB32 - 4)
        transport = OpenAITransport(facts=(FIRST, TAIL, "연락처 [전화번호] 입니다."))
        result = OpenAICompatibleTextDocumentAdapter(transport).understand(document(text), external_model(), CTX)
        sent = transport.sent()
        self.assertLessEqual(len(sent.encode("utf-8")), KIB32)
        self.assertIn("[전화번호]", sent)
        for leaked in ("1234-5678", "010-9999", "9999-8888", "ZEBRA-TAIL-77"):
            self.assertNotIn(leaked, sent)
        self.assertEqual(result.semantic.key_facts, (FIRST,))  # 뒷부분·가려진 문장은 원문 근거가 아니다
        self.assertEqual(result.parser.page_texts, ((1, text),))
        self.assertEqual(result.lineage["sent_bytes"], str(len(sent.encode("utf-8"))))

    def test_external_rejects_over_2_mib_without_sending(self):
        transport = OpenAITransport()
        with self.assertRaises(DocumentUnderstandingError) as caught:
            OpenAICompatibleTextDocumentAdapter(transport).understand(document("a" * (MIB2 + 1)), external_model(), CTX)
        self.assertEqual(caught.exception.code, "TEXT_UNDERSTANDING_SIZE_UNSUPPORTED")
        self.assertEqual(transport.calls, [])


class EgressSizeTests(unittest.TestCase):
    """외부 전송 판정에는 원문 전체가 아니라 실제로 보내는 바이트 수가 들어간다."""

    def process(self, model, adapter_kwargs):
        sizes: list = []

        class Guard:
            def authorize(self, context, selections, size_bytes=None):
                sizes.append(size_bytes)

        text = big_text()

        class Repository:
            def load_source_document(self, context, source_id, *, processing_run_id=None):
                return document(text)

            def complete(self, context, processing_run_id, result):
                self.result = result

            def fail(self, context, processing_run_id, code, *, retryable):
                raise AssertionError(code)

        class Resolver:
            @contextmanager
            def resolve(self, context, capability):
                yield model

        class NoPdf:
            def create(self, *args):
                raise AssertionError("TXT must not use the PDF path")

        repository = Repository()
        DocumentProcessingService(repository, Resolver(), NoPdf(), egress_guard=Guard(), **adapter_kwargs).process_existing(
            CTX, source_id="source-big", processing_run_id="run-big")
        return sizes, text, repository.result

    def test_internal_text_model_is_judged_on_the_sent_head(self):
        transport = OllamaTransport()
        sizes, text, result = self.process(local_model(), {"text_adapter": OllamaTextDocumentAdapter(transport)})
        self.assertEqual(sizes, [len(transport.sent().encode("utf-8"))])
        self.assertLess(sizes[0], len(text.encode()))
        self.assertEqual(result.parser.text, text)

    def test_external_text_model_is_judged_on_the_masked_bytes_actually_sent(self):
        transport = OpenAITransport()
        sizes, text, _ = self.process(external_model(), {"external_text_adapter": OpenAICompatibleTextDocumentAdapter(transport)})
        self.assertEqual(sizes, [len(transport.sent().encode("utf-8"))])
        self.assertLessEqual(sizes[0], KIB32)


class FakeIndexConnection:
    def __init__(self, key_facts):
        self.key_facts, self.index_payload, self.evidence = key_facts, None, 0
        self.state, self.version = "processing", 3

    def execute(self, sql, params=()):
        class Cursor:
            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        if sql.startswith("SELECT NOT EXISTS (SELECT 1 FROM identity_auth_source_access"):
            return Cursor((True,))
        if sql.startswith("SELECT record_id,canonical_json FROM understanding_results"):
            return Cursor(("understanding-big", {"source_id": "source-big", "status": "ready",
                                                 "semantic": {"key_facts": list(self.key_facts)}}))
        if sql.startswith("SELECT s.state,s.version,sv.source_id"):
            return Cursor((self.state, self.version, "source-big"))
        if sql.startswith("SELECT state,version,outcome,error_code FROM transition_canon_state"):
            self.state, self.version = params[3], self.version + 1
            return Cursor((self.state, self.version, "succeeded", None))
        if sql.startswith("INSERT INTO evidence_spans"):
            self.evidence += 1
            return Cursor()
        if sql.startswith("INSERT INTO index_versions"):
            self.index_payload = params[4].obj
            return Cursor()
        if sql.startswith("SELECT canonical_json FROM index_versions"):
            return Cursor((self.index_payload,))
        raise AssertionError(sql)


class FakeIndexStore:
    def __init__(self, key_facts):
        self.connection = FakeIndexConnection(key_facts)

    @contextmanager
    def _transaction(self, context):
        yield self.connection


class IndexWholeTextTests(unittest.TestCase):
    def test_tail_sentence_is_indexed_and_found_as_question_evidence(self):
        text = big_text(target_bytes=MIB2 - 4096)
        self.assertGreater(len(text.encode()), KIB32)
        self.assertLessEqual(len(text.encode()), MIB2)
        result = OllamaTextDocumentAdapter(OllamaTransport()).understand(document(text), local_model(), CTX)
        store = FakeIndexStore(result.semantic.key_facts)
        index = PostgresDocumentIndex(store)
        started = time.monotonic()
        index.index_result(CTX, result)
        found = index.search(CTX, source_id="source-big", source_version_id="source-version-big", query="ZEBRA 표식은 무엇인가요?")
        elapsed = time.monotonic() - started
        self.assertIn("ZEBRA-TAIL-77", "".join(chunk["text"] for chunk in store.connection.index_payload["chunks"]))
        self.assertTrue(any("ZEBRA" in chunk.text for chunk in found))
        self.assertTrue(all(chunk.locator_kind == "section" for chunk in found))
        self.assertGreater(store.connection.evidence, len(text) // 1024)  # 본문 전체가 근거 구간이다
        self.assertLess(elapsed, 10.0)


if __name__ == "__main__":
    unittest.main()


class InvalidResponseReasonTests(unittest.TestCase):
    """TXT 이해 응답이 검증을 통과하지 못하면 이유만(본문 없이) 경고 로그로 남긴다(NB4-I1 실서버 원인 조사)."""

    def run_with(self, choice, model="uss/solar-pro4"):
        class Transport:
            def post_json(self, **kwargs):
                return {"choices": [choice], "model": model}
            post_json_no_auth = post_json
        with self.assertLogs("daon2_user_api.text_document_understanding", level="WARNING") as logs:
            with self.assertRaises(DocumentUnderstandingError) as caught:
                OpenAICompatibleTextDocumentAdapter(Transport()).understand(document(big_text()), external_model(), CTX)
        self.assertEqual(caught.exception.code, "TEXT_UNDERSTANDING_RESPONSE_INVALID")
        return "\n".join(logs.output)

    def test_truncated_response_is_logged_as_truncated(self):
        out = self.run_with({"message": {"content": '{"title": "큰 약관", "summary": "중간에 잘린'}, "finish_reason": "length"})
        self.assertIn("reason=truncated", out)
        self.assertIn("finish=length", out)
        self.assertNotIn("중간에 잘린", out)

    def test_wrong_shape_is_logged_as_shape(self):
        out = self.run_with({"message": {"content": json.dumps({"title": "t", "summary": "s"})}, "finish_reason": "stop"})
        self.assertIn("reason=shape", out)

    def test_too_many_facts_is_logged_as_limits(self):
        out = self.run_with({"message": {"content": answer([FIRST] * 6)}, "finish_reason": "stop"})
        self.assertIn("reason=limits", out)

    def test_non_json_is_logged_as_not_json(self):
        out = self.run_with({"message": {"content": "요약할 수 없습니다"}, "finish_reason": "stop"})
        self.assertIn("reason=not_json", out)
        self.assertNotIn("요약할 수 없습니다", out)
