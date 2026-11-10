from __future__ import annotations

import io
import json
import unittest
from contextlib import contextmanager
from pathlib import Path

from reportlab.pdfgen import canvas

from daon2_user_api.document_processing import (
    DocumentProcessingContext, DocumentProcessingService, StoredSourceDocument,
)
from daon2_user_api.document_understanding_adapter import DocumentUnderstandingError
from daon2_user_api.pdf_text_understanding import PdfTextDocumentAdapter, read_pdf_text
from daon2_user_api.workspace_model_defaults import ResolvedModel, WorkspaceModelUnavailable

try:
    from tests.test_document_processing import Adapter, AdapterFactory, FixtureOutboundGuard, ModelResolver, RecordingRepository
except ModuleNotFoundError:
    from test_document_processing import Adapter, AdapterFactory, FixtureOutboundGuard, ModelResolver, RecordingRepository


CONTEXT = DocumentProcessingContext("tenant-a", "workspace-a", "actor-a", "trace-a", "policy-a")
SERVICE_CONTEXT = DocumentProcessingContext("tenant-cp3", "workspace-cp3", "actor-cp3", "trace-cp3", "policy-v1")
FIRST = "The project budget is 500 million won in total."
SECOND = "Proposals must be submitted by the deadline in writing."


def pdf(*pages: str, password: str | None = None) -> bytes:
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer, encrypt=password)
    for text in pages:
        for index, line in enumerate(text.splitlines()):
            page.drawString(72, 760 - 14 * index, line)
        page.showPage()
    page.save()
    return buffer.getvalue()


def stored(content: bytes) -> StoredSourceDocument:
    return StoredSourceDocument("source-a", "version-a", "rfp.pdf", content, "application/pdf")


def model(kind: str = "external_api", provider: str = "UPSTAGE", capability: str = "text_generation") -> ResolvedModel:
    return ResolvedModel("selected-connection", provider, "synthetic-model", capability,
        "https://api.example.test/v1", 1, 1, 1, kind, "provider", True, bytearray(b"synthetic-key"))


def reply(title: str = "Benchmark RFP", summary: str = "A summary without figures.", facts=(FIRST,)) -> str:
    return json.dumps({"title": title, "summary": summary, "key_facts": list(facts)})


class Transport:
    def __init__(self, *contents: str) -> None:
        self.contents, self.calls = list(contents), []

    def post_json(self, *, url, api_key, payload, timeout_seconds):
        self.calls.append((url, payload))
        return {"model": "synthetic-model", "choices": [{"message": {"content": self.contents.pop(0)}}]}

    def post_json_no_auth(self, *, url, payload, timeout_seconds):
        self.calls.append((url, payload))
        return {"model": "synthetic-model", "message": {"content": self.contents.pop(0)}}


class ReadPdfTextTests(unittest.TestCase):
    def test_keeps_real_page_numbers_and_skips_blank_pages(self):
        result = read_pdf_text(pdf(FIRST, "", SECOND))
        self.assertEqual([number for number, _ in result.page_texts], [1, 3])
        self.assertIn("500 million", result.page_texts[0][1])
        self.assertEqual(result.pages_without_text, 1)

    def test_scanned_pdf_is_reported_as_having_no_text(self):
        with self.assertRaises(DocumentUnderstandingError) as caught:
            read_pdf_text(pdf("", ""))
        self.assertEqual((caught.exception.code, caught.exception.status, caught.exception.retryable), ("PDF_TEXT_NOT_FOUND", 409, False))

    def test_password_protected_pdf_is_rejected(self):
        with self.assertRaises(DocumentUnderstandingError) as caught:
            read_pdf_text(pdf(FIRST, password="secret"))
        self.assertEqual(caught.exception.code, "PDF_TEXT_ENCRYPTED")

    def test_broken_pdf_is_rejected_without_leaking_the_parser_error(self):
        with self.assertRaises(DocumentUnderstandingError) as caught:
            read_pdf_text(b"%PDF-1.4\nnot really a pdf")
        self.assertEqual(caught.exception.code, "PDF_TEXT_UNREADABLE")

    def test_control_characters_that_postgres_cannot_store_are_removed(self):
        from daon2_user_api import pdf_text_understanding as module
        self.assertEqual(module._clean("a\x00b\x07c\r\nd\te\ud800"), "abc\nd\te")


class PdfTextAdapterTests(unittest.TestCase):
    def understand(self, transport, content=None, selection=None, authorize=lambda size: None):
        return PdfTextDocumentAdapter(transport).understand(
            stored(content if content is not None else pdf(FIRST, SECOND)), selection or model(), CONTEXT, authorize_egress=authorize)

    def test_ready_result_keeps_every_page_as_parser_text(self):
        result = self.understand(Transport(reply()))
        self.assertEqual(result.status, "ready")
        self.assertIsNone(result.conflict)
        self.assertEqual(result.parser.pages, (1, 2))
        self.assertEqual([number for number, _ in result.parser.page_texts], [1, 2])
        self.assertIn(SECOND, result.parser.text)
        self.assertEqual(result.parser.markdown, result.parser.text)
        self.assertEqual(result.semantic.key_facts, (FIRST,))
        self.assertEqual(result.lineage["source_format"], "pdf_text")
        self.assertEqual(result.lineage["summary_source"], "model")
        self.assertEqual(result.lineage["trace_id"], "trace-a")

    def test_paraphrased_facts_are_dropped_and_copied_facts_kept(self):
        result = self.understand(Transport(reply(facts=("Budget is about half a billion.", FIRST))))
        self.assertEqual(result.semantic.key_facts, (FIRST,))

    def test_fact_copied_across_a_line_break_still_matches(self):
        content = pdf("The project budget is\n500 million won in total.")
        result = self.understand(Transport(reply(facts=(FIRST,))), content)
        self.assertEqual(result.semantic.key_facts, (FIRST,))

    def test_more_than_five_facts_are_capped_instead_of_failing(self):
        content = pdf("\n".join(f"Requirement number {n} is stated here." for n in range(8)))
        facts = [f"Requirement number {n} is stated here." for n in range(8)]
        self.assertEqual(len(self.understand(Transport(reply(facts=facts)), content).semantic.key_facts), 5)

    def test_when_no_fact_is_grounded_original_lines_are_used(self):
        result = self.understand(Transport(reply(facts=("Entirely invented statement.",))))
        self.assertTrue(result.semantic.key_facts)
        self.assertTrue(all(fact in result.parser.text for fact in result.semantic.key_facts))

    def test_summary_with_a_number_not_in_the_pdf_is_replaced_by_grounded_facts(self):
        result = self.understand(Transport(reply(summary="The budget is 999 million won.")))
        self.assertNotIn("999", result.semantic.summary)
        self.assertIn(FIRST, result.semantic.summary)
        self.assertEqual(result.lineage["summary_source"], "grounded_facts")

    def test_invalid_response_is_retried_once(self):
        transport = Transport("not json", reply())
        self.assertEqual(self.understand(transport).semantic.title, "Benchmark RFP")
        self.assertEqual(len(transport.calls), 2)

    def test_invalid_response_twice_still_leaves_a_usable_document(self):
        transport = Transport("not json", "still not json")
        result = self.understand(transport)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.semantic.title, "rfp")
        self.assertTrue(all(fact in result.parser.text for fact in result.semantic.key_facts))
        self.assertEqual((result.lineage["title_source"], result.lineage["summary_source"]), ("filename", "grounded_facts"))
        self.assertEqual(len(transport.calls), 2)

    def test_provider_outage_is_not_hidden_by_the_fallback(self):
        class Down(Transport):
            def post_json(self, **kwargs):
                raise DocumentUnderstandingError("UNDERSTANDING_PROVIDER_UNAVAILABLE", status=503, retryable=True)
        with self.assertRaises(DocumentUnderstandingError) as caught:
            self.understand(Down())
        self.assertEqual(caught.exception.code, "UNDERSTANDING_PROVIDER_UNAVAILABLE")

    def test_only_a_bounded_head_is_sent_but_all_text_is_kept(self):
        pages = [f"Page {n} " + "lorem ipsum dolor sit amet " * 3 for n in range(1, 41)] * 40
        transport = Transport(reply(facts=("Page 1",)))
        sizes = []
        result = self.understand(transport, pdf(*pages), authorize=sizes.append)
        sent = transport.calls[0][1]["messages"][1]["content"]
        self.assertLessEqual(len(sent.encode()), 32 * 1024)
        self.assertEqual(sizes, [len(sent.encode())])
        self.assertEqual(len(result.parser.page_texts), len(pages))
        self.assertGreater(len(result.parser.text.encode()), 32 * 1024)

    def test_external_provider_receives_masked_text(self):
        transport = Transport(reply(facts=("Contact the office.",)))
        self.understand(transport, pdf("Contact the office.\nCall 010-1234-5678 for details."))
        self.assertNotIn("1234-5678", transport.calls[0][1]["messages"][1]["content"])

    def test_internal_provider_uses_the_chat_endpoint_without_masking(self):
        transport = Transport(reply(facts=("Contact the office.",)))
        selection = model(kind="server_internal", provider="OLLAMA")
        self.understand(transport, pdf("Contact the office.\nCall 010-1234-5678 for details."), selection)
        url, payload = transport.calls[0]
        self.assertTrue(url.endswith("/api/chat"))
        self.assertIn("010-1234-5678", payload["messages"][1]["content"])

    def test_egress_denial_stops_before_anything_is_sent(self):
        transport = Transport(reply())

        def deny(size):
            raise DocumentUnderstandingError("EGRESS_POLICY_DENIED", status=403)
        with self.assertRaises(DocumentUnderstandingError) as caught:
            self.understand(transport, authorize=deny)
        self.assertEqual(caught.exception.code, "EGRESS_POLICY_DENIED")
        self.assertEqual(transport.calls, [])

    def test_scanned_pdf_never_reaches_the_model(self):
        transport = Transport(reply())
        with self.assertRaises(DocumentUnderstandingError):
            self.understand(transport, pdf("", ""))
        self.assertEqual(transport.calls, [])

    def test_wrong_capability_is_refused(self):
        with self.assertRaises(DocumentUnderstandingError) as caught:
            self.understand(Transport(reply()), selection=model(capability="image_understanding"))
        self.assertEqual(caught.exception.code, "DOCUMENT_PROVIDER_ADAPTER_UNAVAILABLE")


class ServicePathTests(unittest.TestCase):
    def run_service(self, missing, code="WORKSPACE_MODEL_DEFAULT_UNAVAILABLE"):
        calls, used = [], []

        class Repository(RecordingRepository):
            def load_source_document(inner, context, source_id, *, processing_run_id=None):
                return stored(pdf(FIRST))

        class Resolver(ModelResolver):
            @contextmanager
            def resolve(inner, context, capability):
                calls.append(capability)
                if capability in missing:
                    raise WorkspaceModelUnavailable(code)
                if capability == "text_generation":
                    selected = model()
                    try:
                        yield selected
                    finally:
                        selected.release()
                    return
                with super().resolve(context, capability) as selected:
                    yield selected

        class TextAdapter:
            def understand(inner, document, selection, context, *, authorize_egress):
                used.append((document.filename, selection.capability))
                return PdfTextDocumentAdapter(Transport(reply())).understand(document, selection, context, authorize_egress=authorize_egress)

        repository = Repository()
        document_adapter = Adapter()
        service = DocumentProcessingService(repository, Resolver(), AdapterFactory(document_adapter),
            egress_guard=FixtureOutboundGuard(), pdf_text_adapter=TextAdapter())
        return service, repository, calls, used, document_adapter

    def test_pdf_uses_text_extraction_when_document_models_are_not_set(self):
        for missing, expected in ((("image_understanding",), ["image_understanding", "text_generation"]),
                                  (("document_parsing",), ["image_understanding", "document_parsing", "text_generation"])):
            with self.subTest(missing=missing):
                service, repository, calls, used, document_adapter = self.run_service(missing)
                result = service.process_existing(SERVICE_CONTEXT, source_id="source-a", processing_run_id="run-a")
                self.assertEqual(result.lineage["source_format"], "pdf_text")
                self.assertEqual(calls, expected)
                self.assertEqual(used, [("rfp.pdf", "text_generation")])
                self.assertEqual(document_adapter.calls, 0)
                self.assertIn("complete", [event[0] for event in repository.events])
                self.assertNotIn("fail", [event[0] for event in repository.events])

    def test_document_models_are_still_preferred_when_set(self):
        service, _, calls, used, document_adapter = self.run_service(())
        service.process_existing(SERVICE_CONTEXT, source_id="source-a", processing_run_id="run-a")
        self.assertEqual(calls, ["image_understanding", "document_parsing"])
        self.assertEqual(used, [])
        self.assertEqual(document_adapter.calls, 1)

    def test_a_broken_model_connection_does_not_silently_switch_path(self):
        service, repository, calls, used, _ = self.run_service(("image_understanding",), code="PROVIDER_CONNECTION_UNAVAILABLE")
        with self.assertRaises(DocumentUnderstandingError) as caught:
            service.process_existing(SERVICE_CONTEXT, source_id="source-a", processing_run_id="run-a")
        self.assertEqual(caught.exception.code, "PROVIDER_CONNECTION_UNAVAILABLE")
        self.assertEqual(calls, ["image_understanding"])
        self.assertEqual(used, [])

    def test_text_model_missing_too_reports_the_missing_default(self):
        service, repository, _, used, _ = self.run_service(("image_understanding", "text_generation"))
        with self.assertRaises(DocumentUnderstandingError) as caught:
            service.process_existing(SERVICE_CONTEXT, source_id="source-a", processing_run_id="run-a")
        self.assertEqual(caught.exception.code, "WORKSPACE_MODEL_DEFAULT_UNAVAILABLE")
        self.assertEqual(used, [])
        self.assertEqual(repository.events[-1][0], "fail")


class PackagingTests(unittest.TestCase):
    def test_runtime_image_installs_the_pdf_reader(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn("pypdf==6.21.2", (root / "Dockerfile").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
