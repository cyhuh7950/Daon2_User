from __future__ import annotations

import hashlib
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from daon2_user_api.knowledge_package_import import (
    KnowledgePackageImport, KnowledgePackageImportError, PostgresKnowledgePackageImporter, split_chunks,
)
from daon2_user_api.studio_workspace import StudioContext

NOW = datetime(2026, 11, 9, 1, 0, tzinfo=UTC)
CONTENT = "# 개요\n읽기 전용 채널입니다.\n\n## 인증\nJWT를 씁니다.\n\n## 도구\n" + ("검색 도구 설명입니다.\n\n" * 200)


def request(**overrides):
    values = dict(package_id="daon2-mcp-spec", producer="daon2", producer_version="1.0", title="Daon2 MCP",
                  content=CONTENT, effective_at=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(days=30),
                  basis="설계 정본 §5.10")
    values.update(overrides)
    return KnowledgePackageImport(**values)


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Connection:
    def __init__(self, existing=None):
        self.existing = existing or []
        self.inserts: list[tuple[str, tuple]] = []
        self.transitions: list[tuple[str, str]] = []
        self.versions: dict[str, int] = {}

    def execute(self, query, parameters=()):
        if query.startswith("SELECT pg_advisory_xact_lock"):
            return _Result()
        if "FROM knowledge_registrations" in query:
            return _Result(self.existing)
        if "transition_canon_state" in query:
            entity, record, version, target = parameters[:4]
            self.transitions.append((entity, target))
            return _Result([(target, version + 1, "succeeded", None)])
        if query.startswith("INSERT INTO"):
            table = query.split()[2]
            self.inserts.append((table, parameters))
            return _Result()
        raise AssertionError(query)


class _Store:
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def _transaction(self, context):
        self.context = context
        yield self.connection


def context():
    return StudioContext("tenant-a", "workspace-a", "admin", "trace-import-1", "runtime-policy-v1")


class SplitChunksTests(unittest.TestCase):
    def test_splits_at_headings_and_keeps_every_character(self):
        chunks = split_chunks(CONTENT, limit=300)
        self.assertGreater(len(chunks), 3)
        self.assertTrue(all(len(chunk) <= 300 for chunk in chunks))
        self.assertTrue(chunks[0].startswith("# 개요"))
        self.assertEqual("".join(chunks).replace("\n", "").replace(" ", ""),
                         CONTENT.replace("\n", "").replace(" ", ""))

    def test_blank_content_has_no_chunks(self):
        self.assertEqual(split_chunks("\n\n  \n"), [])


class ValidationTests(unittest.TestCase):
    def test_rejects_unknown_producer_bad_id_and_bad_period(self):
        for overrides, code in (
            ({"producer": "other"}, "KNOWLEDGE_PACKAGE_PRODUCER_INVALID"),
            ({"package_id": "../x"}, "KNOWLEDGE_PACKAGE_ID_INVALID"),
            ({"expires_at": NOW - timedelta(days=1)}, "KNOWLEDGE_PACKAGE_PERIOD_INVALID"),
            ({"effective_at": datetime(2026, 1, 1)}, "KNOWLEDGE_PACKAGE_PERIOD_INVALID"),
            ({"content": "  "}, "KNOWLEDGE_PACKAGE_CONTENT_INVALID"),
            ({"content_type": "application/pdf"}, "KNOWLEDGE_PACKAGE_CONTENT_TYPE_INVALID"),
            ({"basis": ""}, "KNOWLEDGE_PACKAGE_TEXT_INVALID"),
        ):
            with self.subTest(code=code), self.assertRaises(KnowledgePackageImportError) as raised:
                PostgresKnowledgePackageImporter(_Store(_Connection()), clock=lambda: NOW).import_package(context(), request(**overrides))
            self.assertEqual(raised.exception.code, code)


class ImportTests(unittest.TestCase):
    def importer(self, connection):
        return PostgresKnowledgePackageImporter(_Store(connection), clock=lambda: NOW)

    def test_creates_the_full_approved_lineage_in_one_transaction(self):
        connection = _Connection()
        result = self.importer(connection).import_package(context(), request())
        digest = hashlib.sha256(CONTENT.encode()).hexdigest()
        self.assertEqual((result["package_digest"], result["byte_size"], result["replayed"]), (digest, len(CONTENT.encode()), False))
        tables = [table for table, _ in connection.inserts]
        for table in ("generation_settings_snapshots", "generation_requests", "studio_outputs", "output_versions", "sources",
                      "source_versions", "evidence_spans", "index_versions", "knowledge_registrations", "audit_events"):
            self.assertIn(table, tables)
        self.assertEqual(tables.count("evidence_spans"), result["chunks"])
        self.assertLess(tables.index("output_versions"), tables.index("knowledge_registrations"))
        self.assertEqual([t for e, t in connection.transitions if e == "OutputVersion"],
                         ["draft", "review_requested", "in_review", "approved"])
        self.assertEqual([t for e, t in connection.transitions if e == "Source"], ["security_check", "processing", "indexing", "ready"])
        self.assertEqual(connection.transitions[-1], ("KnowledgeRegistration", "registered"))

    def test_registration_record_carries_package_fields_and_import_origin(self):
        connection = _Connection()
        self.importer(connection).import_package(context(), request())
        params = next(p for table, p in connection.inserts if table == "knowledge_registrations")
        payload = next(value for value in params if hasattr(value, "obj")).obj
        self.assertEqual((payload["producer"], payload["authority"], payload["package_id"]), ("daon2", "approved", "daon2-mcp-spec"))
        self.assertEqual(payload["import"], {"origin": "admin_import", "imported_by": "admin", "basis": "설계 정본 §5.10"})
        self.assertEqual(payload["content_type"], "text/markdown")

    def test_same_package_and_content_is_a_replay_without_writes(self):
        digest = hashlib.sha256(CONTENT.encode()).hexdigest()
        connection = _Connection(existing=[(digest, "registered")])
        result = self.importer(connection).import_package(context(), request())
        self.assertTrue(result["replayed"])
        self.assertEqual(connection.inserts, [])

    def test_same_package_with_different_content_is_a_conflict(self):
        connection = _Connection(existing=[("0" * 64, "registered")])
        with self.assertRaises(KnowledgePackageImportError) as raised:
            self.importer(connection).import_package(context(), request())
        self.assertEqual((raised.exception.code, raised.exception.status), ("KNOWLEDGE_PACKAGE_CONFLICT", 409))
        self.assertEqual(connection.inserts, [])

    def test_runs_under_the_registration_capability(self):
        store = _Store(_Connection())
        PostgresKnowledgePackageImporter(store, clock=lambda: NOW).import_package(context(), request())
        self.assertEqual(store.context.capability, "studio.knowledge_registration")


if __name__ == "__main__":
    unittest.main()
