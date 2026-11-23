"""텍스트로 소스 등록 도우미(WO-N1 NB1-F2, 정정 C-1). NB4-F1도 이 도우미를 쓴다."""
from __future__ import annotations

import hashlib
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from daon2_user_api import text_source
from daon2_user_api.data_canon import canonical_json_bytes
from daon2_user_api.document_processing import (
    DocumentProcessingContext, DocumentProcessingService, StoredSourceDocument, text_source_format,
)
from daon2_user_api.document_understanding_adapter import (
    DocumentUnderstandingResult, ParserValidation, SemanticUnderstanding,
)
from daon2_user_api.source_upload import SourceUploadResult
from daon2_user_api.studio_workspace import StudioContext
from daon2_user_api.text_source import TextSourceError, TextSourceService
from daon2_user_api.workspace_model_defaults import ResolvedModel

CTX = StudioContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1", "notebook-1")
OBJECT = "b" * 32


def obj(value):
    return getattr(value, "obj", value)


class FakeUpload:
    def __init__(self):
        self.registered: list[dict] = []
        self.stored: list[dict] = []
        self.canon_store = FakeCanon()

    def register_source(self, **kwargs):
        self.registered.append(kwargs)
        oid = hashlib.sha256(kwargs["idempotency_key"].encode()).hexdigest()[:32]
        return SourceUploadResult(f"src-{oid}", f"sv-{oid}", oid, hashlib.sha256(kwargs["content"]).hexdigest(),
                                  len(kwargs["content"]), "accepted", False, kwargs["content_type"])

    def store_object(self, **kwargs):
        self.stored.append(kwargs)
        return OBJECT


class FakeCanon:
    def __init__(self):
        self.appended: list[dict] = []

    def append_source_version_in_transaction(self, connection, context, **kwargs):
        self.appended.append({"context": context, **kwargs})
        connection.db.versions.append((kwargs["source_version_id"], kwargs["version_number"]))


class FakeProcessing:
    def __init__(self):
        self.submitted: list[tuple] = []

    def submit(self, context, source_version_id, *, notebook_id):
        self.submitted.append((context, source_version_id, notebook_id))
        return SimpleNamespace(source_state="processing")


class FakeDb:
    def __init__(self, *, state="ready", filename="메모.txt", content_type="text/plain", bound=True, deleted=False, exists=True):
        self.state = state
        self.filename = filename
        self.content_type = content_type
        self.bound = bound
        self.deleted = deleted
        self.exists = exists
        self.versions = [("sv-old", 1)]
        self.statements: list[tuple[str, tuple]] = []
        self.transitions: list[str] = []
        self.within: list[str] = []

    @contextmanager
    def _transaction(self, scope):
        self.scope = scope
        yield FakeConnection(self)


class FakeConnection:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=()):
        db = self.db
        db.statements.append((sql, params))
        row = None
        if sql == text_source._LOCK_SOURCE_SQL:
            row = (db.state, 3) if db.exists else None
        elif sql == text_source._DELETED_SQL:
            row = (1,) if db.deleted else None
        elif sql == text_source._LATEST_VERSION_SQL:
            latest = max(db.versions, key=lambda v: v[1])
            row = (latest[0], latest[1], {"filename": db.filename, "content_type": db.content_type,
                                          "deletion_policy": "delete_with_notebook"})
        elif sql == text_source._BOUND_SQL:
            row = (1,) if db.bound else None
        elif sql == text_source._TRANSITION_SQL:
            db.transitions.append(params[3])
            db.state = params[3]
            row = (params[3], 4 + len(db.transitions), "succeeded", None)
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: [] if row is None else [row])


def service(db=None, upload=None, processing=None):
    return TextSourceService(upload_service=upload or FakeUpload(), processing_service=processing or FakeProcessing(),
                             cloud_store=db or FakeDb())


class RegisterTextSourceTests(unittest.TestCase):
    def test_register_uses_the_upload_storage_path_and_the_document_processing_queue(self):
        upload, processing = FakeUpload(), FakeProcessing()
        source_id, version_id = service(upload=upload, processing=processing).register_text_source(
            CTX, "notebook-1", title="회의 메모", text="첫 줄\n둘째 줄", origin="memo", idempotency_key="memo-source:x")
        call = upload.registered[0]
        self.assertEqual(call["content_type"], "text/plain")
        self.assertEqual(call["filename"], "회의 메모.txt")
        self.assertEqual(call["content"], "첫 줄\n둘째 줄".encode("utf-8"))
        self.assertEqual(call["notebook_id"], "notebook-1")
        self.assertEqual((call["tenant_id"], call["workspace_id"], call["actor_id"], call["trace_id"]),
                         ("tenant-1", "workspace-1", "actor-1", "trace-1"))
        self.assertIs(call["deduplicate"], False)  # 같은 글의 다른 소스에 붙지 않는다
        self.assertEqual(call["idempotency_key"], "memo-source:x")
        context, submitted, notebook = processing.submitted[0]
        self.assertIsInstance(context, DocumentProcessingContext)
        self.assertEqual((submitted, notebook), (version_id, "notebook-1"))
        self.assertTrue(source_id.startswith("src-") and version_id.startswith("sv-"))
        self.assertEqual(text_source_format(call["filename"], call["content_type"]), "txt")

    def test_registered_memo_text_is_processed_by_the_document_worker_as_txt(self):
        upload = FakeUpload()
        service(upload=upload).register_text_source(CTX, "notebook-1", title="메모", text="계약 기간은 3년이다.", origin="memo")
        stored = upload.registered[0]

        class Repository:
            def __init__(self):
                self.events = []

            def load_source_document(self, context, source_id, *, processing_run_id=None):
                self.events.append("load")
                return StoredSourceDocument(source_id, "sv-memo", stored["filename"], stored["content"], stored["content_type"])

            def complete(self, context, processing_run_id, result):
                self.events.append("complete")

            def fail(self, context, processing_run_id, code, *, retryable):
                self.events.append(("fail", code))

        class Resolver:
            def __init__(self):
                self.capabilities = []

            @contextmanager
            def resolve(self, context, capability):
                self.capabilities.append(capability)
                yield ResolvedModel("ollama-public", "OLLAMA", "llama3.2:3b", capability, "http://ollama.internal:11434",
                                    0, 1, 1, "local", "provider", True, None)

        class TextAdapter:
            def __init__(self):
                self.documents = []

            def understand(self, document, selection, context):
                self.documents.append(document)
                text = document.content.decode("utf-8")
                return DocumentUnderstandingResult(document.source_id, document.source_version_id, "ready", (),
                                                   SemanticUnderstanding("메모", text, (text,)),
                                                   ParserValidation(text, text, "", (1,), ((1, text),)),
                                                   {"provider_code": selection.provider_code, "source_format": "txt"})

        class NoPdf:
            def create(self, *args):
                raise AssertionError("memo text must not use the PDF path")

        repository, resolver, adapter = Repository(), Resolver(), TextAdapter()
        DocumentProcessingService(repository, resolver, NoPdf(), text_adapter=adapter).process_existing(
            DocumentProcessingContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1"),
            source_id="src-memo", processing_run_id="run-memo")
        self.assertEqual(resolver.capabilities, ["text_generation"])
        self.assertEqual(adapter.documents[0].filename, "메모.txt")
        self.assertEqual(repository.events, ["load", "complete"])

    def test_without_key_each_call_makes_a_new_source(self):
        upload = FakeUpload()
        sources = service(upload=upload)
        first = sources.register_text_source(CTX, "notebook-1", title="메모", text="같은 글", origin="memo")
        second = sources.register_text_source(CTX, "notebook-1", title="메모", text="같은 글", origin="memo")
        self.assertNotEqual(first, second)

    def test_title_is_made_into_a_safe_txt_filename(self):
        upload = FakeUpload()
        sources = service(upload=upload)
        for title, expected in (("a/b\\c\x01d", "abcd.txt"), ("   ", "텍스트 소스.txt"), ("가" * 300, "가" * 120 + ".txt"),
                                ("보고서.md", "보고서.md.txt")):
            sources.register_text_source(CTX, "notebook-1", title=title, text="본문", origin="memo")
            self.assertEqual(upload.registered[-1]["filename"], expected)

    def test_rejects_empty_too_large_null_and_unknown_origin(self):
        upload = FakeUpload()
        sources = service(upload=upload)
        cases = (("   \n", "memo", "TEXT_SOURCE_EMPTY", 422), ("가" * 11000, "memo", "TEXT_SOURCE_TOO_LARGE", 413),
                 ("a\x00b", "memo", "TEXT_SOURCE_INPUT_INVALID", 400), ("본문", "web", "TEXT_SOURCE_INPUT_INVALID", 400),
                 (None, "memo", "TEXT_SOURCE_INPUT_INVALID", 400))
        for text, origin, code, status in cases:
            with self.subTest(code=code, origin=origin):
                with self.assertRaises(TextSourceError) as caught:
                    sources.register_text_source(CTX, "notebook-1", title="메모", text=text, origin=origin)
                self.assertEqual((caught.exception.code, caught.exception.status), (code, status))
        self.assertEqual(upload.registered, [])

    def test_limit_matches_the_txt_understanding_limit(self):
        self.assertEqual(text_source.TEXT_SOURCE_MAX_BYTES, 32 * 1024)
        service().register_text_source(CTX, "notebook-1", title="메모", text="a" * (32 * 1024), origin="memo")


class AppendTextVersionTests(unittest.TestCase):
    def test_does_not_lock_append_only_canon_rows_for_update(self):
        """NB1-I2 실서버: 앱 역할에는 sources UPDATE 권한이 없어 SELECT ... FOR UPDATE가 DATABASE_ACCESS_DENIED로 실패했다."""
        db = FakeDb()
        service(db=db).append_text_version(CTX, "src-1", "고친 메모")
        sqls = [sql for sql, _ in db.statements]
        self.assertFalse([sql for sql in sqls if "FOR UPDATE" in sql.upper()])
        lock = [index for index, sql in enumerate(sqls) if "pg_advisory_xact_lock" in sql]
        read = [index for index, sql in enumerate(sqls) if sql == text_source._LOCK_SOURCE_SQL]
        self.assertTrue(lock and read and lock[0] < read[0])

    def test_appends_a_new_version_to_the_same_source_with_lineage(self):
        db, upload = FakeDb(), FakeUpload()
        version_id = service(db=db, upload=upload).append_text_version(CTX, "src-1", "고친 메모", idempotency_key="memo-reflect:x:2")
        self.assertEqual(version_id, f"sv-{OBJECT}")
        stored = upload.stored[0]
        self.assertEqual((stored["content"], stored["content_type"], stored["idempotency_key"]),
                         ("고친 메모".encode(), "text/plain", "memo-reflect:x:2"))
        appended = upload.canon_store.appended[0]
        self.assertEqual((appended["source_id"], appended["source_version_id"], appended["version_number"], appended["previous_version_id"]),
                         ("src-1", version_id, 2, "sv-old"))
        payload = appended["canonical_payload"]
        self.assertEqual(payload, {"filename": "메모.txt", "content_type": "text/plain", "byte_size": len("고친 메모".encode()),
                                   "object_id": OBJECT, "content_digest_sha256": hashlib.sha256("고친 메모".encode()).hexdigest(),
                                   "deletion_policy": "delete_with_notebook"})
        self.assertEqual(appended["digest_sha256"], hashlib.sha256(canonical_json_bytes(payload)).hexdigest())
        self.assertEqual(db.scope.capability, "source.write")

    def test_binds_the_new_version_and_indexes_it_verbatim(self):
        db = FakeDb()
        text = "가" * 1500
        version_id = service(db=db).append_text_version(CTX, "src-1", text)
        binds = [p for s, p in db.statements if s == text_source._BIND_SQL]
        self.assertEqual(binds[0][:5], ("tenant-1", "workspace-1", "notebook-1", "src-1", version_id))
        spans = [p for s, p in db.statements if s == text_source._EVIDENCE_SQL]
        index = [p for s, p in db.statements if s == text_source._INDEX_SQL]
        self.assertEqual(len(spans), 2)
        self.assertEqual(len(index), 1)
        chunks = obj(index[0][4])["chunks"]
        self.assertEqual("".join(c["text"] for c in chunks), text)
        self.assertTrue(all(c["evidence_kind"] == "text_source_verbatim_fact" and c["source_version_id"] == version_id
                            and c["source_id"] == "src-1" for c in chunks))
        self.assertEqual(obj(index[0][4])["strategy"], "text_source_version_snapshot")
        self.assertEqual({obj(s[4])["kind"] for s in spans}, {"text_source_verbatim_fact"})
        self.assertEqual(db.transitions, [])  # 준비된 소스는 상태를 바꾸지 않는다

    def test_failed_source_becomes_ready_through_allowed_transitions(self):
        db = FakeDb(state="failed")
        service(db=db).append_text_version(CTX, "src-1", "고친 메모")
        self.assertEqual(db.transitions, ["processing", "indexing", "ready"])

    def test_within_runs_in_the_same_transaction(self):
        db = FakeDb()
        seen = []
        service(db=db).append_text_version(CTX, "src-1", "고친 메모", within=lambda connection, version: seen.append((connection.db, version)))
        self.assertIs(seen[0][0], db)

    def test_replayed_key_does_not_insert_twice(self):
        db, upload = FakeDb(), FakeUpload()
        db.versions.append((f"sv-{OBJECT}", 2))
        version_id = service(db=db, upload=upload).append_text_version(CTX, "src-1", "고친 메모")
        self.assertEqual(version_id, f"sv-{OBJECT}")
        self.assertEqual(upload.canon_store.appended, [])
        self.assertFalse(any(s == text_source._BIND_SQL for s, _ in db.statements))

    def test_rejects_missing_unbound_deleted_busy_and_non_text_sources(self):
        cases = ((FakeDb(exists=False), "TEXT_SOURCE_NOT_FOUND", 404), (FakeDb(bound=False), "TEXT_SOURCE_NOT_FOUND", 404),
                 (FakeDb(deleted=True), "TEXT_SOURCE_NOT_FOUND", 404), (FakeDb(state="disabled"), "TEXT_SOURCE_NOT_FOUND", 404),
                 (FakeDb(state="processing"), "SOURCE_PROCESSING_ACTIVE", 409),
                 (FakeDb(filename="a.pdf", content_type="application/pdf"), "TEXT_SOURCE_NOT_TEXT", 409))
        for db, code, status in cases:
            with self.subTest(code=code, state=db.state, bound=db.bound):
                upload = FakeUpload()
                with self.assertRaises(TextSourceError) as caught:
                    service(db=db, upload=upload).append_text_version(CTX, "src-1", "고친 메모")
                self.assertEqual((caught.exception.code, caught.exception.status), (code, status))
                self.assertEqual(upload.canon_store.appended, [])

    def test_requires_notebook_scope_and_valid_text(self):
        with self.assertRaises(TextSourceError) as caught:
            service().append_text_version(StudioContext("t", "w", "a", "tr", "p", None), "src-1", "글")
        self.assertEqual(caught.exception.code, "TEXT_SOURCE_INPUT_INVALID")
        with self.assertRaises(TextSourceError) as caught:
            service().append_text_version(CTX, "src-1", " ")
        self.assertEqual(caught.exception.code, "TEXT_SOURCE_EMPTY")


if __name__ == "__main__":
    unittest.main()
