"""MCP 근거 스냅샷의 지식 버전 변경(stale) 판정 단위 시험(DB·MCP 대역)."""
from __future__ import annotations

import unittest
from contextlib import contextmanager

from daon2_user_api.studio_v2_service import StudioV2Service
from daon2_user_api.studio_workspace import StudioContext

CTX = StudioContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1", "notebook-1")
REF = {"connector_id": "kc-1", "document_id": "doc-1", "version_id": "v1", "project_id": "proj-alpha", "work_package_id": "wp-proposals"}


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append((sql, params))
        return _Result(self.rows)


class _Store:
    def __init__(self, rows):
        self.connection = _Connection(rows)

    @contextmanager
    def _transaction(self, _access):
        yield self.connection


class _Service(StudioV2Service):
    def _cloud(self, context, operation):  # type: ignore[no-untyped-def]
        return object()

    def _owned_output(self, connection, context, output_id):  # type: ignore[no-untyped-def]
        return (None,) * 8 + (3,)


class KnowledgeStaleTests(unittest.TestCase):
    def service(self, rows, checker):
        service = _Service(_Store(rows))
        service.set_knowledge_status(checker)
        return service

    def test_changed_document_marks_output_stale_and_card_cache(self):
        calls = []
        service = self.service([(REF,), (REF,)], lambda ctx, ref: calls.append(ref) or True)
        self.assertTrue(service.knowledge_changed(CTX, "sv2-a"))
        self.assertEqual(len(calls), 1, "같은 문서·버전은 한 번만 확인한다")
        items = [{"output_id": "sv2-a", "stale": False}, {"output_id": "sv2-b", "stale": False}]
        service.apply_knowledge_stale(CTX, items)
        self.assertEqual([item["stale"] for item in items], [True, False])

    def test_unchanged_unknown_and_failing_checks_do_not_mark_stale(self):
        for outcome in (False, None):
            with self.subTest(outcome=outcome):
                self.assertFalse(self.service([(REF,)], lambda ctx, ref, outcome=outcome: outcome).knowledge_changed(CTX, "sv2-a"))

        def broken(ctx, ref):
            raise RuntimeError("knowledge server down")
        self.assertFalse(self.service([(REF,)], broken).knowledge_changed(CTX, "sv2-a"))

    def test_without_checker_or_snapshot_fields_nothing_is_checked(self):
        service = _Service(_Store([(REF,)]))
        self.assertFalse(service.knowledge_changed(CTX, "sv2-a"))
        incomplete = self.service([({"connector_id": "kc-1"},)], lambda ctx, ref: True)
        self.assertFalse(incomplete.knowledge_changed(CTX, "sv2-a"))

    def test_query_is_scoped_to_mcp_origin_and_current_revision(self):
        service = self.service([], lambda ctx, ref: True)
        service.knowledge_changed(CTX, "sv2-a")
        sql, params = service._cloud_store.connection.sql[0]
        self.assertIn("left(origin,4)='mcp_'", sql)
        self.assertEqual(params, ("tenant-1", "workspace-1", "sv2-a", 3))


if __name__ == "__main__":
    unittest.main()
