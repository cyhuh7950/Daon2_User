"""질문 도구 저장·조회·적용 상태 계약(WO-N1 N1-2, NB2-F1, 결정 D-02: 웹 도구 없음)."""
from __future__ import annotations

import copy
import unittest
from contextlib import contextmanager

from daon2_user_api import question_tools
from daon2_user_api.cloud_storage import CloudDatabaseError
from daon2_user_api.question_tools import QuestionToolsContext, QuestionToolsError, QuestionToolsService

CTX = QuestionToolsContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1")
RAG = {"connector_id": "kc-rag", "kind": "daon2_rag", "name": "Daon2-RAG", "status": "verified", "virtual": False}
DAON2 = {"connector_id": "kc-daon2", "kind": "daon2", "name": "Daon2 지식", "status": "verified", "virtual": False}
LAW = {"connector_id": "kc-law", "kind": "law", "name": "법령 연결", "status": "unverified", "virtual": False}


class FakeDb:
    def __init__(self):
        self.notebooks = {"notebook-1", "notebook-2"}
        self.scopes = {"notebook-1"}          # 승인 지식 범위(notebook_knowledge_scopes)가 있는 노트북
        self.rows: dict[tuple[str, str], dict] = {}   # (notebook, actor) -> enabled_json
        self.executed: list[tuple[str, tuple]] = []
        self.scopes_seen: list[tuple] = []
        self.fail = False

    @contextmanager
    def _transaction(self, scope):
        if self.fail:
            raise CloudDatabaseError("DB_DOWN", retryable=True)
        self.scopes_seen.append((scope.tenant_id, scope.workspace_id, scope.actor_id, scope.capability))
        snapshot = copy.deepcopy(self.rows)
        try:
            yield FakeConnection(self, scope)
        except Exception:
            self.rows = snapshot
            raise


class _Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, db, scope):
        self.db, self.scope = db, scope

    def execute(self, sql, params=()):
        db = self.db
        db.executed.append((sql, tuple(params)))
        if sql == question_tools._NOTEBOOK_SQL:
            return _Result((1,) if params[2] in db.notebooks else None)
        if sql == question_tools._SCOPE_SQL:
            return _Result((1,) if params[2] in db.scopes else None)
        if sql == question_tools._STORED_SQL:
            row = db.rows.get((params[2], params[3]))
            return _Result(None if row is None else (copy.deepcopy(row),))
        if sql == question_tools._UPSERT_SQL:
            # RLS(actor 기준): 다른 사용자 행은 쓰지 못한다.
            assert params[3] == self.scope.actor_id
            merged = {**db.rows.get((params[2], params[3]), {}), **params[4].obj}
            db.rows[(params[2], params[3])] = merged
            return _Result((copy.deepcopy(merged),))
        raise AssertionError(f"unexpected SQL {sql}")


class FakeConnectors:
    def __init__(self, items=(RAG, DAON2, LAW)):
        self.items = [dict(item) for item in items]
        self.contexts = []
        self.calls = 0  # 지식 연결 호출(call)은 도구 목록을 만들 때 쓰지 않는다

    def list(self, context):
        self.contexts.append(context)
        return [dict(item) for item in self.items]

    def call(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("tool list must not call connectors")


def by_id(data):
    return {item["id"]: item for item in data["tools"]}


class QuestionToolsListTests(unittest.TestCase):
    def setUp(self):
        self.db, self.connectors = FakeDb(), FakeConnectors()
        self.service = QuestionToolsService(self.db, self.connectors, shared_connector_tenant="shared-tenant")

    def test_default_without_row_matches_current_behavior(self):
        data = self.service.get(CTX, "notebook-1")
        self.assertEqual([item["id"] for item in data["tools"]], ["approved_knowledge", "connector:kc-rag", "connector:kc-daon2", "connector:kc-law"])
        tools = by_id(data)
        self.assertEqual(tools["approved_knowledge"], {"id": "approved_knowledge", "kind": "approved_knowledge", "label": "승인 지식",
                                                       "available": True, "enabled": True})
        self.assertEqual(tools["connector:kc-rag"], {"id": "connector:kc-rag", "kind": "connector", "connector_kind": "daon2_rag",
                                                     "label": "Daon2-RAG", "available": True, "enabled": True})
        self.assertTrue(tools["connector:kc-daon2"]["enabled"])
        self.assertEqual(tools["connector:kc-law"], {"id": "connector:kc-law", "kind": "connector", "connector_kind": "law", "label": "법령 연결",
                                                     "available": False, "enabled": False, "reason": "CONNECTOR_NOT_READY"})
        self.assertEqual(self.db.rows, {})
        self.assertEqual(self.connectors.calls, 0)

    def test_no_web_tool_is_offered(self):
        ids = [item["id"] for item in self.service.get(CTX, "notebook-1")["tools"]]
        self.assertFalse(any("web" in item for item in ids))

    def test_no_scope_makes_approved_knowledge_unavailable(self):
        tool = by_id(self.service.get(CTX, "notebook-2"))["approved_knowledge"]
        self.assertEqual((tool["available"], tool["enabled"], tool["reason"]), (False, False, "NO_SCOPE_SELECTED"))

    def test_disabled_connector_reason(self):
        self.connectors.items[1]["status"] = "disabled"
        tool = by_id(self.service.get(CTX, "notebook-1"))["connector:kc-daon2"]
        self.assertEqual((tool["available"], tool["enabled"], tool["reason"]), (False, False, "CONNECTOR_DISABLED"))

    def test_failed_connector_is_not_ready(self):
        self.connectors.items[0]["status"] = "failed"
        tool = by_id(self.service.get(CTX, "notebook-1"))["connector:kc-rag"]
        self.assertEqual((tool["available"], tool["reason"]), (False, "CONNECTOR_NOT_READY"))

    def test_virtual_and_unknown_kind_connectors_are_not_tools(self):
        self.connectors.items.append({"connector_id": "kc-virtual", "kind": "daon2_rag", "name": "가상", "status": "verified", "virtual": True})
        self.connectors.items.append({"connector_id": "kc-other", "kind": "other", "name": "기타", "status": "verified", "virtual": False})
        ids = [item["id"] for item in self.service.get(CTX, "notebook-1")["tools"]]
        self.assertNotIn("connector:kc-virtual", ids)
        self.assertNotIn("connector:kc-other", ids)

    def test_unsafe_connector_name_falls_back_to_kind_label(self):
        self.connectors.items[0]["name"] = "rag.example.com 연결"
        self.assertEqual(by_id(self.service.get(CTX, "notebook-1"))["connector:kc-rag"]["label"], "문서 근거")

    def test_connectors_are_read_with_the_shared_connector_tenant(self):
        self.service.get(CTX, "notebook-1")
        context = self.connectors.contexts[-1]
        self.assertEqual((context.tenant_id, context.workspace_id, context.owner_tenant_id), ("tenant-1", "workspace-1", "shared-tenant"))

    def test_without_connector_service_only_approved_knowledge(self):
        data = QuestionToolsService(self.db, None).get(CTX, "notebook-1")
        self.assertEqual([item["id"] for item in data["tools"]], ["approved_knowledge"])

    def test_unknown_notebook(self):
        with self.assertRaises(QuestionToolsError) as caught:
            self.service.get(CTX, "notebook-x")
        self.assertEqual((caught.exception.code, caught.exception.status), ("NOTEBOOK_NOT_FOUND", 404))

    def test_database_failure(self):
        self.db.fail = True
        with self.assertRaises(QuestionToolsError) as caught:
            self.service.get(CTX, "notebook-1")
        self.assertEqual((caught.exception.code, caught.exception.status), ("QUESTION_TOOLS_UNAVAILABLE", 503))


class QuestionToolsSaveTests(unittest.TestCase):
    def setUp(self):
        self.db, self.connectors = FakeDb(), FakeConnectors()
        self.service = QuestionToolsService(self.db, self.connectors)

    def test_save_and_read_back(self):
        data = self.service.put(CTX, "notebook-1", {"connector:kc-rag": False})
        self.assertFalse(by_id(data)["connector:kc-rag"]["enabled"])
        self.assertTrue(by_id(data)["approved_knowledge"]["enabled"])
        self.assertEqual(self.db.rows[("notebook-1", "actor-1")], {"connector:kc-rag": False})
        self.assertFalse(by_id(self.service.get(CTX, "notebook-1"))["connector:kc-rag"]["enabled"])

    def test_save_merges_with_earlier_choices(self):
        self.service.put(CTX, "notebook-1", {"connector:kc-rag": False})
        data = self.service.put(CTX, "notebook-1", {"approved_knowledge": False})
        self.assertEqual(self.db.rows[("notebook-1", "actor-1")], {"connector:kc-rag": False, "approved_knowledge": False})
        self.assertFalse(by_id(data)["connector:kc-rag"]["enabled"])
        self.assertFalse(by_id(data)["approved_knowledge"]["enabled"])

    def test_choices_are_per_notebook_and_per_actor(self):
        self.service.put(CTX, "notebook-1", {"connector:kc-rag": False})
        self.assertTrue(by_id(self.service.get(CTX, "notebook-2"))["connector:kc-rag"]["enabled"])
        other = QuestionToolsContext("tenant-1", "workspace-1", "actor-2", "trace-1", "policy-1")
        self.assertTrue(by_id(self.service.get(other, "notebook-1"))["connector:kc-rag"]["enabled"])

    def test_unknown_tool_is_rejected_without_saving(self):
        for tool in ("web", "connector:kc-missing", "connector:", "APPROVED_KNOWLEDGE"):
            with self.subTest(tool=tool), self.assertRaises(QuestionToolsError) as caught:
                self.service.put(CTX, "notebook-1", {tool: True})
            self.assertEqual((caught.exception.code, caught.exception.status), ("QUESTION_TOOL_UNKNOWN", 422))
        self.assertEqual(self.db.rows, {})

    def test_virtual_connector_cannot_be_saved(self):
        self.connectors.items.append({"connector_id": "kc-virtual", "kind": "daon2_rag", "name": "가상", "status": "verified", "virtual": True})
        with self.assertRaises(QuestionToolsError) as caught:
            self.service.put(CTX, "notebook-1", {"connector:kc-virtual": True})
        self.assertEqual(caught.exception.code, "QUESTION_TOOL_UNKNOWN")

    def test_turning_on_an_unavailable_tool_is_saved_but_reported_off(self):
        data = self.service.put(CTX, "notebook-1", {"connector:kc-law": True})
        self.assertEqual(self.db.rows[("notebook-1", "actor-1")], {"connector:kc-law": True})
        tool = by_id(data)["connector:kc-law"]
        self.assertEqual((tool["available"], tool["enabled"]), (False, False))
        # 연결이 준비되면 저장값(켬)이 그대로 보인다.
        self.connectors.items[2]["status"] = "verified"
        self.assertTrue(by_id(self.service.get(CTX, "notebook-1"))["connector:kc-law"]["enabled"])

    def test_non_boolean_values_are_rejected(self):
        for body in ({"approved_knowledge": 1}, {"approved_knowledge": None}, "x", {1: True}):
            with self.subTest(body=body), self.assertRaises(QuestionToolsError) as caught:
                self.service.put(CTX, "notebook-1", body)  # type: ignore[arg-type]
            self.assertEqual(caught.exception.code, "QUESTION_TOOLS_INVALID")

    def test_save_on_unknown_notebook(self):
        with self.assertRaises(QuestionToolsError) as caught:
            self.service.put(CTX, "notebook-x", {"approved_knowledge": False})
        self.assertEqual(caught.exception.code, "NOTEBOOK_NOT_FOUND")
        self.assertEqual(self.db.rows, {})

    def test_enabled_ids_for_audit(self):
        data = self.service.put(CTX, "notebook-1", {"connector:kc-rag": False})
        self.assertEqual(question_tools.enabled_ids(data), ["approved_knowledge", "connector:kc-daon2"])


class QuestionToolStateTests(unittest.TestCase):
    """질문 처리 경로가 쓰는 적용 상태. 화면이 보낸 값이 아니라 서버 저장값으로 정한다."""

    def setUp(self):
        self.db, self.connectors = FakeDb(), FakeConnectors()
        self.service = QuestionToolsService(self.db, self.connectors)

    def test_default_state_is_everything_on(self):
        state = self.service.read_state("tenant-1", "workspace-1", "notebook-1", "actor-1")
        self.assertTrue(state.approved_knowledge)
        self.assertEqual(state.disabled_connectors, frozenset())
        self.assertEqual(state.labels, ("승인 지식", "Daon2-RAG", "Daon2 지식"))

    def test_saved_choices_turn_tools_off(self):
        self.service.put(CTX, "notebook-1", {"approved_knowledge": False, "connector:kc-daon2": False})
        state = self.service.read_state("tenant-1", "workspace-1", "notebook-1", "actor-1")
        self.assertFalse(state.approved_knowledge)
        self.assertEqual(state.disabled_connectors, frozenset({"kc-daon2"}))
        self.assertEqual(state.labels, ("Daon2-RAG",))

    def test_approved_knowledge_without_scope_still_applies_daon_knowledge_by_default(self):
        # 범위가 없어 '사용할 수 없음'으로 보여도, 꺼 두지 않았다면 지식 패키지 입력은 지금처럼 쓴다(기본값 = 현재 동작).
        state = self.service.read_state("tenant-1", "workspace-1", "notebook-2", "actor-1")
        self.assertTrue(state.approved_knowledge)
        self.assertNotIn("승인 지식", state.labels)

    def test_state_read_is_bound_to_the_actor(self):
        self.service.read_state("tenant-1", "workspace-1", "notebook-1", "actor-1")
        self.assertIn(("tenant-1", "workspace-1", "actor-1", "question_tools.read"), self.db.scopes_seen)

    def test_state_read_failure_raises(self):
        self.db.fail = True
        with self.assertRaises(QuestionToolsError):
            self.service.read_state("tenant-1", "workspace-1", "notebook-1", "actor-1")


if __name__ == "__main__":
    unittest.main()
