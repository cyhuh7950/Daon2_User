"""Daon 승인 지식 목록과 노트북별 업무 패키지 선택(WO-K2 T3, T4)."""
from __future__ import annotations

import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from daon2_user_api.knowledge_connector_service import ConnectorContext
from daon2_user_api.knowledge_scope_service import KnowledgeScopeContext, KnowledgeScopeError, KnowledgeScopeService

CTX = KnowledgeScopeContext("tenant-a", "ws-a", "user-a", "trace-a", "policy-a")


def scope(project="p1", package="w1", approved=1, **over):
    return {"tenant_id": "src-tenant", "project_id": project, "project_name": f"{project} 이름", "work_package_id": package,
            "work_package_name": f"{package} 이름", "updated_at": "2026-11-09T00:00:00Z", "approved_document_count": approved, **over}


class _Connectors:
    def __init__(self, pages, connectors=None):
        self.pages, self.calls = pages, []
        self.connectors = connectors if connectors is not None else [
            {"connector_id": "kc-law", "kind": "law", "status": "verified"},
            {"connector_id": "kc-off", "kind": "daon2_rag", "status": "failed"},
            {"connector_id": "kc-rag", "kind": "daon2_rag", "status": "verified"}]

    def list(self, _context):  # noqa: A003
        return self.connectors

    def call(self, context, connector_id, tool, arguments):
        self.calls.append((context, connector_id, tool, dict(arguments)))
        return SimpleNamespace(structured=self.pages[len(self.calls) - 1])


class _Connection:
    def __init__(self, store):
        self.store = store
        self.last = None

    def execute(self, sql, params=()):
        self.store.statements.append((sql, params))
        self.last = sql
        return self

    def fetchone(self):
        return None if "notebooks" in self.last and not self.store.notebook else (1,)

    def fetchall(self):
        return self.store.rows


class _Store:
    def __init__(self, rows=(), notebook=True):
        self.rows, self.notebook, self.statements = list(rows), notebook, []

    @contextmanager
    def _transaction(self, _scope):
        yield _Connection(self)


class CatalogTests(unittest.TestCase):
    def service(self, pages, **kw):
        self.connectors = _Connectors(pages, **kw)
        return KnowledgeScopeService(_Store(), self.connectors)

    def test_reads_every_page_through_first_verified_rag_connector(self):
        service = self.service([{"scopes": [scope("p1", "w1")], "next_cursor": "next"}, {"scopes": [scope("p1", "w2")], "next_cursor": None}])
        result = service.catalog(CTX)
        self.assertEqual([c[1:] for c in self.connectors.calls], [
            ("kc-rag", "list_knowledge_scopes", {"limit": 50}), ("kc-rag", "list_knowledge_scopes", {"limit": 50, "cursor": "next"})])
        self.assertEqual(result, {"projects": [{"project_id": "p1", "project_name": "p1 이름", "work_packages": [
            {"work_package_id": "w1", "work_package_name": "w1 이름", "updated_at": "2026-11-09T00:00:00Z"},
            {"work_package_id": "w2", "work_package_name": "w2 이름", "updated_at": "2026-11-09T00:00:00Z"}]}]})

    def test_shared_connection_is_looked_up_at_its_owner_but_egress_stays_with_the_caller(self):
        self.connectors = _Connectors([{"scopes": [scope()], "next_cursor": None}])
        KnowledgeScopeService(_Store(), self.connectors, shared_connector_tenant="admin").catalog(CTX)
        context = self.connectors.calls[0][0]
        self.assertEqual((context.tenant_id, context.owner_tenant_id, context.workspace_id), ("tenant-a", "admin", "ws-a"))

    def test_without_shared_tenant_the_organization_uses_its_own_connection(self):
        self.service([{"scopes": [scope()], "next_cursor": None}]).catalog(CTX)
        self.assertIsNone(self.connectors.calls[0][0].owner_tenant_id)

    def test_daon2_connection_is_found_when_verified(self):
        connectors = _Connectors([], connectors=[{"connector_id": "kc-d", "kind": "daon2", "status": "verified"}])
        context, connector_id = KnowledgeScopeService(_Store(), connectors).daon2_target(CTX)
        self.assertEqual((connector_id, context.workspace_id), ("kc-d", "ws-a"))

    def test_daon2_connection_is_optional_and_virtual_is_ignored(self):
        connectors = _Connectors([], connectors=[{"connector_id": "kc-v", "kind": "daon2", "status": "verified", "virtual": True}])
        self.assertIsNone(KnowledgeScopeService(_Store(), connectors).daon2_target(CTX))

    def test_call_carries_workspace_for_egress_decision(self):
        self.service([{"scopes": [], "next_cursor": None}]).catalog(CTX)
        context = self.connectors.calls[0][0]
        self.assertIsInstance(context, ConnectorContext)
        self.assertEqual((context.tenant_id, context.workspace_id, context.policy_version), ("tenant-a", "ws-a", "policy-a"))

    def test_only_packages_with_approved_documents_are_returned(self):
        page = {"scopes": [scope("p1", "ok", 7), scope("p1", "none", 0), scope("p2", "missing", approved=None), scope("p3", "text", "3"), scope("p4", "flag", True)],
                "next_cursor": None}
        result = self.service([page]).catalog(CTX)
        self.assertEqual([p["project_id"] for p in result["projects"]], ["p1"])
        self.assertEqual([w["work_package_id"] for w in result["projects"][0]["work_packages"]], ["ok"])

    def test_status_alone_does_not_approve(self):
        row = scope(status="active")
        del row["approved_document_count"]
        self.assertEqual(self.service([{"scopes": [row], "next_cursor": None}]).catalog(CTX), {"projects": []})

    def test_missing_verified_connector_is_distinct_error(self):
        with self.assertRaises(KnowledgeScopeError) as caught:
            self.service([], connectors=[{"connector_id": "kc-off", "kind": "daon2_rag", "status": "failed"}]).catalog(CTX)
        self.assertEqual((caught.exception.code, caught.exception.status), ("KNOWLEDGE_CONNECTOR_NOT_CONFIGURED", 409))

    def test_virtual_connector_is_never_used(self):
        fake = {"connector_id": "kc-fake", "kind": "daon2_rag", "status": "verified", "virtual": True}
        real = {"connector_id": "kc-real", "kind": "daon2_rag", "status": "verified", "virtual": False}
        self.service([{"scopes": [], "next_cursor": None}], connectors=[fake, real]).catalog(CTX)
        self.assertEqual(self.connectors.calls[0][1], "kc-real")
        with self.assertRaises(KnowledgeScopeError) as caught:
            self.service([], connectors=[fake]).catalog(CTX)
        self.assertEqual(caught.exception.code, "KNOWLEDGE_CONNECTOR_NOT_CONFIGURED")

    def test_malformed_or_looping_response_fails_closed(self):
        # 필수 항목이 빠진 행 하나는 이제 그 행만 건너뛴다(ScopeRowToleranceTests). 응답 형식 자체가 틀리면 여전히 실패한다.
        bad = [[{"next_cursor": None}], [{"scopes": "x", "next_cursor": None}], [{"scopes": [], "next_cursor": 3}],
               [{"scopes": [], "next_cursor": "same"}, {"scopes": [], "next_cursor": "same"}]]
        for pages in bad:
            with self.subTest(pages=pages), self.assertRaises(KnowledgeScopeError) as caught:
                self.service(pages).catalog(CTX)
            self.assertEqual(caught.exception.code, "KNOWLEDGE_SCOPE_RESPONSE_INVALID")


class SelectionTests(unittest.TestCase):
    def service(self, *, rows=(), notebook=True, approved=()):
        self.store = _Store(rows, notebook)
        return KnowledgeScopeService(self.store, _Connectors([{"scopes": list(approved), "next_cursor": None}]))

    def test_get_returns_saved_items_without_remote_call(self):
        service = self.service(rows=[("p1", "프로젝트", "w1", "패키지")])
        self.assertEqual(service.selection(CTX, "nb-1"), {"items": [{"project_id": "p1", "project_name": "프로젝트", "work_package_id": "w1", "work_package_name": "패키지"}]})
        self.assertEqual(service._connectors.calls, [])  # noqa: SLF001

    def test_unknown_notebook_is_not_found(self):
        with self.assertRaises(KnowledgeScopeError) as caught:
            self.service(notebook=False).selection(CTX, "nb-x")
        self.assertEqual((caught.exception.code, caught.exception.status), ("NOTEBOOK_NOT_FOUND", 404))

    def test_put_replaces_selection_using_server_names(self):
        service = self.service(approved=[scope("p1", "w1"), scope("p1", "w2")])
        service.replace(CTX, "nb-1", [{"project_id": "p1", "work_package_id": "w2"}])
        sql = [s for s, _ in self.store.statements]
        self.assertTrue(any(s.startswith("DELETE FROM notebook_knowledge_scopes") for s in sql))
        insert = next(p for s, p in self.store.statements if s.startswith("INSERT INTO notebook_knowledge_scopes"))
        self.assertEqual(insert, ("tenant-a", "ws-a", "nb-1", "src-tenant", "p1", "p1 이름", "w2", "w2 이름", "user-a"))

    def test_put_rejects_package_outside_approved_list(self):
        service = self.service(approved=[scope("p1", "w1", 0)])
        with self.assertRaises(KnowledgeScopeError) as caught:
            service.replace(CTX, "nb-1", [{"project_id": "p1", "work_package_id": "w1"}])
        self.assertEqual((caught.exception.code, caught.exception.status), ("KNOWLEDGE_SCOPE_NOT_AVAILABLE", 409))
        self.assertFalse(any(s.startswith(("DELETE", "INSERT")) for s, _ in self.store.statements))

    def test_empty_selection_clears_without_remote_call(self):
        service = self.service(approved=[])
        service.replace(CTX, "nb-1", [])
        self.assertEqual(service._connectors.calls, [])  # noqa: SLF001
        self.assertTrue(any(s.startswith("DELETE FROM notebook_knowledge_scopes") for s, _ in self.store.statements))

    def test_more_than_eight_packages_are_rejected(self):
        items = [{"project_id": "p1", "work_package_id": f"w{i}"} for i in range(9)]
        with self.assertRaises(KnowledgeScopeError) as caught:
            self.service(approved=[]).replace(CTX, "nb-1", items)
        self.assertEqual(caught.exception.code, "KNOWLEDGE_SCOPE_SELECTION_INVALID")

    def test_duplicates_are_rejected(self):
        item = {"project_id": "p1", "work_package_id": "w1"}
        with self.assertRaises(KnowledgeScopeError) as caught:
            self.service(approved=[scope()]).replace(CTX, "nb-1", [item, dict(item)])
        self.assertEqual(caught.exception.code, "KNOWLEDGE_SCOPE_SELECTION_INVALID")


if __name__ == "__main__":
    unittest.main()


class ScopeRowToleranceTests(unittest.TestCase):
    """2026-11-16 ysna: Daon2가 재생성 중인 패키지 행을 tenant_id 없이 보내자 목록 전체가 실패했다."""

    def test_row_without_tenant_is_kept_and_a_broken_row_is_skipped(self):
        rows = [scope("p1", "w1"), scope("p1", "w2", tenant_id=None), {**scope("p1", "w3"), "work_package_name": ""}]
        service = KnowledgeScopeService(_Store(), _Connectors([{"scopes": rows, "next_cursor": None}]))
        names = [w["work_package_id"] for p in service.catalog(CTX)["projects"] for w in p["work_packages"]]
        self.assertEqual(names, ["w1", "w2"])

    def test_selecting_a_package_without_tenant_stores_a_marker(self):
        store = _Store()
        service = KnowledgeScopeService(store, _Connectors([{"scopes": [scope("p1", "w2", tenant_id=None)], "next_cursor": None}]))
        service.replace(CTX, "nb-1", [{"project_id": "p1", "work_package_id": "w2"}])
        insert = next(p for s, p in store.statements if s.startswith("INSERT INTO notebook_knowledge_scopes"))
        self.assertEqual(insert[3], "server")


class PageSizeFromServerTests(unittest.TestCase):
    """목록 한 번에 받을 개수는 서버 도구 설명(limit maximum)을 따른다. 모르면 50, 많아도 200."""

    def limits_sent(self, maximum):
        connectors = _Connectors([{"scopes": [scope()], "next_cursor": None}])
        if maximum != "absent":
            connectors.tool_limit = lambda context, connector_id, tool: maximum
        KnowledgeScopeService(_Store(), connectors).catalog(CTX)
        return connectors.calls[0][3]["limit"]

    def test_server_maximum_is_used(self):
        self.assertEqual(self.limits_sent(20), 20)

    def test_unknown_maximum_falls_back_to_50(self):
        self.assertEqual(self.limits_sent(None), 50)
        self.assertEqual(self.limits_sent("absent"), 50)

    def test_large_maximum_is_capped(self):
        self.assertEqual(self.limits_sent(500), 200)
