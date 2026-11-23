"""메모를 소스로 저장·조회 계약(WO-N1 NB1-F2, 결정 D-10)."""
from __future__ import annotations

import copy
import re
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from daon2_user_api import memo_source
from daon2_user_api.memo_source import MemoSourceService
from daon2_user_api.studio_v2_postgres import _STALE_SQL
from daon2_user_api.studio_workspace import StudioContext, StudioError
from daon2_user_api.text_source import TextSourceError

CTX = StudioContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1", "notebook-1")
MEMO = "sv2-" + "a" * 32
REPORT = "sv2-" + "c" * 32


class FakeDb:
    """메모·연결·소스 버전·노트북 연결을 기억하는 작은 저장소. 서비스의 SQL 상수만 알아듣는다."""

    def __init__(self):
        self.outputs = {MEMO: {"type_id": "memo", "title": "회의 메모", "revision": 1, "markdown": "첫 메모", "deleted": False},
                        REPORT: {"type_id": "report", "title": "보고서", "revision": 1, "markdown": None, "deleted": False}}
        self.links: dict[str, dict] = {}
        self.source_versions: dict[str, list[tuple[str, int]]] = {}
        self.source_state: dict[str, str] = {}
        self.inactive: set[str] = set()                  # 삭제 요청된 소스(deletion_requests)
        self.bindings: dict[tuple[str, str], str] = {}   # (notebook, source) -> version. notebook_bindings는 소스당 한 줄
        self.unbindings: list[dict] = []                 # notebook_source_unbindings
        self.activities: list[dict] = []                 # notebook_activities
        self.audits: list[dict] = []                     # audit_events
        self.locks: list[str] = []
        self.executed: list[str] = []
        self.output_sources: dict[str, str] = {}   # 산출물 -> 근거로 쓴 source_version_id
        self.after_read = None

    @contextmanager
    def _transaction(self, scope):
        # 트랜잭션이 예외로 끝나면 그 안에서 쓴 것을 되돌린다.
        snapshot = (copy.deepcopy(self.links), list(self.unbindings), list(self.activities), list(self.audits))
        try:
            yield FakeConnection(self)
        except Exception:
            self.links, self.unbindings, self.activities, self.audits = snapshot
            raise

    def unbound(self, notebook_id: str, source_id: str, version_id: str) -> bool:
        return any(u["notebook_id"] == notebook_id and u["source_id"] == source_id and u["source_version_id"] == version_id
                   for u in self.unbindings)

    def active(self, notebook_id: str, source_id: str) -> bool:
        """_ACTIVE_SQL 흉내: 최신 버전이 연결돼 있고, 떼지 않았고, 삭제되지 않았다."""
        versions = self.source_versions.get(source_id, [])
        if not versions or source_id in self.inactive:
            return False
        latest = max(versions, key=lambda item: item[1])[0]
        bound = self.bindings.get((notebook_id, source_id))
        return bound == latest and not self.unbound(notebook_id, source_id, bound)

    def stale(self, output_id: str, notebook_id: str = "notebook-1") -> bool:
        """_STALE_SQL의 '같은 소스의 더 새 버전'과 '노트북에서 뗌' 조건을 그대로 흉내 낸다."""
        used = self.output_sources[output_id]
        for versions in self.source_versions.values():
            numbers = {vid: number for vid, number in versions}
            if used in numbers and any(number > numbers[used] for number in numbers.values()):
                return True
        return any(u["notebook_id"] == notebook_id and u["source_version_id"] == used for u in self.unbindings)


class FakeConnection:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=()):
        db = self.db
        db.executed.append(sql)
        row, rows = None, []
        if sql == memo_source._MEMO_SQL:
            output = db.outputs.get(params[2])
            if output is not None and not output["deleted"] and params[3] == "notebook-1":
                content = None if output["markdown"] is None else {"schema": "studio.memo.v1", "body": {"markdown": output["markdown"], "refs": []}}
                row = (output["type_id"], output["title"], output["revision"], content)
            if db.after_read is not None:
                hook, db.after_read = db.after_read, None
                hook()
        elif sql == memo_source._LINK_SQL:
            link = db.links.get(params[2])
            if link is not None:
                row = (link["source_id"], link["reflected_revision_no"], db.active(link["notebook_id"], link["source_id"]))
        elif sql == memo_source._INSERT_LINK_SQL:
            if params[3] not in db.links:
                db.links[params[3]] = {"notebook_id": params[2], "source_id": params[4], "reflected_revision_no": params[5]}
                row = (params[4],)
        elif sql == memo_source._REPLACE_LINK_SQL:
            link = db.links.get(params[5])
            if link is not None and link["source_id"] == params[6]:
                link.update(source_id=params[0], reflected_revision_no=params[1])
                row = (1,)
        elif sql == memo_source._UNBIND_LOCK_SQL:
            db.locks.append(params[0])
        elif sql == memo_source._LINK_ROW_SQL:
            link = db.links.get(params[2])
            if link is not None:
                row = (link["source_id"], link["reflected_revision_no"])
        elif sql == memo_source._CURRENT_BINDING_SQL:
            version = db.bindings.get((params[2], params[3]))
            if version is not None and not db.unbound(params[2], params[3], version):
                row = (version,)
        elif sql == memo_source._UNBINDING_COUNT_SQL:
            row = (sum(1 for u in db.unbindings if u["notebook_id"] == params[2]),)
        elif sql == memo_source._INSERT_UNBINDING_SQL:
            db.unbindings.append({"notebook_id": params[2], "source_id": params[3], "source_version_id": params[4],
                                  "binding_version": params[5], "actor_id": params[6]})
        elif sql == memo_source._NEXT_ACTIVITY_SQL:
            row = (1 + max([a["sequence"] for a in db.activities if a["notebook_id"] == params[2]], default=0),)
        elif sql == memo_source._INSERT_ACTIVITY_SQL:
            db.activities.append({"notebook_id": params[2], "sequence": params[3], "actor_id": params[4]})
        elif sql == memo_source._INSERT_AUDIT_SQL:
            if any(a["event_id"] == params[0] for a in db.audits):
                raise AssertionError("duplicate audit event_id")
            db.audits.append({"event_id": params[0], "tenant_id": params[1], "workspace_id": params[2], "actor_id": params[3],
                              "target_id": params[4], "after_value": getattr(params[7], "obj", params[7]),
                              "metadata": getattr(params[8], "obj", params[8])})
        elif sql == memo_source._REFLECT_LINK_SQL:
            link = db.links.get(params[4])
            if link is not None and link["source_id"] == params[5] and link["reflected_revision_no"] == params[6]:
                link.update(source_id=params[0], reflected_revision_no=params[1])
                row = (1,)
        elif sql == memo_source._SOURCE_STATE_SQL:
            row = (db.source_state.get(params[2], "registered"),)
        elif sql == memo_source._ORIGINS_SQL:
            rows = [(link["source_id"], output_id, output_id in db.outputs and not db.outputs[output_id]["deleted"])
                    for output_id, link in db.links.items() if link["notebook_id"] == params[2]]
        else:
            raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: rows)


class FakeTextSources:
    """register_text_source만 흉내 낸다. 같은 키면 같은 소스를 돌려준다(업로드 멱등)."""

    def __init__(self, db):
        self.db = db
        self.registered: list[dict] = []
        self.by_key: dict[str, tuple[str, str]] = {}
        self.fail = None

    def register_text_source(self, context, notebook_id, *, title, text, origin, idempotency_key=None):
        if self.fail:
            raise self.fail
        self.registered.append({"notebook_id": notebook_id, "title": title, "text": text, "origin": origin, "key": idempotency_key})
        if idempotency_key in self.by_key:
            return self.by_key[idempotency_key]
        number = len(self.by_key) + 1
        source_id, version_id = f"src-memo-{number}", f"sv-memo-{number}-1"
        self.db.source_versions[source_id] = [(version_id, 1)]
        self.db.source_state[source_id] = "processing"
        self.db.bindings[(notebook_id, source_id)] = version_id
        self.by_key[idempotency_key] = (source_id, version_id)
        return source_id, version_id

    def append_text_version(self, *args, **kwargs):
        raise AssertionError("반영은 같은 source_id에 새 버전을 붙이지 않는다")


def make():
    db = FakeDb()
    texts = FakeTextSources(db)
    return db, texts, MemoSourceService(db, texts)


class CreateMemoSourceTests(unittest.TestCase):
    def assert_code(self, code, status, fn, *args):
        with self.assertRaises(StudioError) as caught:
            fn(*args)
        self.assertEqual((caught.exception.code, caught.exception.status), (code, status))

    def test_create_registers_memo_text_and_links_it(self):
        db, texts, service = make()
        result = service.create(CTX, MEMO)
        self.assertEqual(result, {"source_id": "src-memo-1", "source_version_id": "sv-memo-1-1", "state": "processing", "revision_no": 1})
        self.assertEqual(texts.registered[0], {"notebook_id": "notebook-1", "title": "회의 메모", "text": "첫 메모", "origin": "memo",
                                               "key": f"memo-source:{MEMO}:new"})
        self.assertEqual(db.links[MEMO], {"notebook_id": "notebook-1", "source_id": "src-memo-1", "reflected_revision_no": 1})

    def test_duplicate_create_is_conflict(self):
        _, texts, service = make()
        service.create(CTX, MEMO)
        self.assert_code("MEMO_SOURCE_EXISTS", 409, service.create, CTX, MEMO)
        self.assertEqual(len(texts.registered), 1)

    def test_concurrent_create_of_another_source_is_conflict_but_same_source_replays(self):
        db, _, service = make()
        db.after_read = lambda: db.links.__setitem__(MEMO, {"notebook_id": "notebook-1", "source_id": "src-other", "reflected_revision_no": 1})
        self.assert_code("MEMO_SOURCE_EXISTS", 409, service.create, CTX, MEMO)
        db2, _, service2 = make()
        db2.after_read = lambda: db2.links.__setitem__(MEMO, {"notebook_id": "notebook-1", "source_id": "src-memo-1", "reflected_revision_no": 1})
        self.assertEqual(service2.create(CTX, MEMO)["source_id"], "src-memo-1")

    def test_missing_deleted_non_memo_and_empty_memos(self):
        db, texts, service = make()
        self.assert_code("STUDIO_OUTPUT_NOT_FOUND", 404, service.create, CTX, "sv2-" + "f" * 32)
        self.assert_code("OUTPUT_NOT_MEMO", 422, service.create, CTX, REPORT)
        db.outputs[MEMO]["markdown"] = "  \n "
        self.assert_code("MEMO_EMPTY", 422, service.create, CTX, MEMO)
        db.outputs[MEMO]["deleted"] = True
        self.assert_code("STUDIO_OUTPUT_NOT_FOUND", 404, service.create, CTX, MEMO)
        self.assertEqual(texts.registered, [])

    def test_text_source_errors_become_memo_codes(self):
        _, texts, service = make()
        for error, code, status in ((TextSourceError("TEXT_SOURCE_EMPTY", 422), "MEMO_EMPTY", 422),
                                    (TextSourceError("TEXT_SOURCE_TOO_LARGE", 413), "MEMO_TOO_LARGE", 413),
                                    (TextSourceError("TEXT_SOURCE_INPUT_INVALID", 400), "STUDIO_INPUT_INVALID", 400)):
            texts.fail = error
            self.assert_code(code, status, service.create, CTX, MEMO)

    def test_source_removed_from_notebook_can_be_made_again_with_a_new_key(self):
        db, texts, service = make()
        service.create(CTX, MEMO)
        db.inactive.add("src-memo-1")
        result = service.create(CTX, MEMO)
        self.assertEqual(result["source_id"], "src-memo-2")
        self.assertEqual(texts.registered[1]["key"], f"memo-source:{MEMO}:src-memo-1")
        self.assertEqual(db.links[MEMO]["source_id"], "src-memo-2")


class ReflectMemoSourceTests(unittest.TestCase):
    def assert_code(self, code, status, fn, *args):
        with self.assertRaises(StudioError) as caught:
            fn(*args)
        self.assertEqual((caught.exception.code, caught.exception.status), (code, status))

    def edited(self):
        db, texts, service = make()
        service.create(CTX, MEMO)
        db.output_sources[REPORT] = "sv-memo-1-1"     # 메모 소스로 만든 기존 산출물
        db.outputs[MEMO].update(revision=2, markdown="고친 메모")
        return db, texts, service

    def test_reflect_registers_a_new_source_with_the_reflect_key(self):
        db, texts, service = self.edited()
        result = service.reflect(CTX, MEMO)
        self.assertEqual(result, {"source_id": "src-memo-2", "source_version_id": "sv-memo-2-1", "revision_no": 2})
        self.assertEqual(texts.registered[1], {"notebook_id": "notebook-1", "title": "회의 메모", "text": "고친 메모",
                                               "origin": "memo", "key": f"memo-reflect:{MEMO}:2"})
        # 이전 소스에 새 버전을 붙이지 않는다.
        self.assertEqual(db.source_versions["src-memo-1"], [("sv-memo-1-1", 1)])

    def test_reflect_unbinds_the_previous_source_with_activity_and_audit(self):
        db, _, service = self.edited()
        service.reflect(CTX, MEMO)
        self.assertEqual(db.locks, ["unbind-notebook|tenant-1|workspace-1|notebook-1"])
        self.assertEqual(db.unbindings, [{"notebook_id": "notebook-1", "source_id": "src-memo-1", "source_version_id": "sv-memo-1-1",
                                          "binding_version": 2, "actor_id": "actor-1"}])
        self.assertEqual(db.activities, [{"notebook_id": "notebook-1", "sequence": 1, "actor_id": "actor-1"}])
        self.assertIn("'context_unbound'", memo_source._INSERT_ACTIVITY_SQL)
        self.assertIn("'notebook.source_unbound'", memo_source._INSERT_AUDIT_SQL)
        self.assertEqual(len(db.audits), 1)
        audit = db.audits[0]
        self.assertEqual((audit["target_id"], audit["actor_id"], audit["after_value"], audit["metadata"]),
                         ("notebook-1", "actor-1", {"binding_version": 2}, {"reason_code": "MEMO_SOURCE_REFLECTED"}))
        self.assertRegex(audit["event_id"], r"^notebook-audit-[0-9a-f]{24}$")
        self.assertNotIn("고친 메모", repr(audit))      # 메모 본문은 감사 기록에 남지 않는다

    def test_binding_version_follows_existing_unbindings(self):
        db, _, service = self.edited()
        db.unbindings.append({"notebook_id": "notebook-1", "source_id": "src-x", "source_version_id": "sv-x",
                              "binding_version": 2, "actor_id": "actor-1"})
        db.activities.append({"notebook_id": "notebook-1", "sequence": 4, "actor_id": "actor-1"})
        service.reflect(CTX, MEMO)
        self.assertEqual(db.unbindings[-1]["binding_version"], 3)
        self.assertEqual(db.activities[-1]["sequence"], 5)

    def test_reflect_moves_the_link_and_keeps_the_new_source_active(self):
        db, _, service = self.edited()
        service.reflect(CTX, MEMO)
        self.assertEqual(db.links[MEMO], {"notebook_id": "notebook-1", "source_id": "src-memo-2", "reflected_revision_no": 2})
        self.assertTrue(db.active("notebook-1", "src-memo-2"))
        self.assertFalse(db.active("notebook-1", "src-memo-1"))
        self.assertEqual(service.source_link(CTX, MEMO, 2), {"source_id": "src-memo-2", "reflected_revision_no": 2, "outdated": False})
        self.assertEqual(service.memo_origins(CTX), {"src-memo-2": {"memo_output_id": MEMO, "memo_exists": True}})

    def test_outputs_using_the_previous_source_become_stale(self):
        db, _, service = self.edited()
        self.assertFalse(db.stale(REPORT))
        service.reflect(CTX, MEMO)
        self.assertTrue(db.stale(REPORT))
        # 실제 판정 SQL도 '노트북에서 뗀 소스 버전'을 본다.
        self.assertIn("FROM notebook_source_unbindings u WHERE u.tenant_id=o.tenant_id AND u.workspace_id=o.workspace_id\n"
                      "        AND u.notebook_id=o.notebook_id AND u.source_version_id=s.source_version_id", _STALE_SQL)

    def test_reflect_again_after_another_edit_moves_on_from_the_second_source(self):
        db, _, service = self.edited()
        service.reflect(CTX, MEMO)
        db.outputs[MEMO].update(revision=3, markdown="또 고친 메모")
        self.assertEqual(service.reflect(CTX, MEMO)["source_id"], "src-memo-3")
        self.assertEqual([u["source_id"] for u in db.unbindings], ["src-memo-1", "src-memo-2"])
        self.assertEqual([u["binding_version"] for u in db.unbindings], [2, 3])
        self.assertEqual(len({a["event_id"] for a in db.audits}), 2)

    def test_unchanged_memo_is_conflict(self):
        db, texts, service = make()
        service.create(CTX, MEMO)
        self.assert_code("MEMO_SOURCE_UNCHANGED", 409, service.reflect, CTX, MEMO)
        self.assertEqual(len(texts.registered), 1)
        self.assertEqual(db.unbindings, [])

    def test_concurrent_reflect_of_another_revision_is_conflict_and_rolls_back(self):
        db, _, service = self.edited()
        # 읽은 뒤 다른 요청이 3번 리비전을 먼저 반영했다.
        db.after_read = lambda: db.links[MEMO].update(source_id="src-other", reflected_revision_no=3)
        self.assert_code("MEMO_SOURCE_UNCHANGED", 409, service.reflect, CTX, MEMO)
        self.assertEqual(db.links[MEMO]["source_id"], "src-other")
        self.assertEqual((db.unbindings, db.activities, db.audits), ([], [], []))

    def test_guarded_link_update_failure_rolls_back_the_unbinding(self):
        db, _, service = self.edited()
        original = FakeConnection.execute

        def execute(connection, sql, params=()):
            if sql == memo_source._REFLECT_LINK_SQL:      # 조건부 갱신이 아무 행도 못 바꿈
                connection.db.executed.append(sql)
                return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])
            return original(connection, sql, params)

        FakeConnection.execute = execute
        try:
            self.assert_code("MEMO_SOURCE_UNCHANGED", 409, service.reflect, CTX, MEMO)
        finally:
            FakeConnection.execute = original
        self.assertEqual(db.links[MEMO]["source_id"], "src-memo-1")
        self.assertEqual((db.unbindings, db.activities, db.audits), ([], [], []))

    def test_same_key_request_racing_a_finished_one_returns_the_same_result(self):
        db, texts, service = self.edited()
        first = {}
        # 두 요청이 같은 리비전을 함께 읽고, 앞 요청이 먼저 끝났다.
        db.after_read = lambda: first.update(service.reflect(CTX, MEMO))
        second = service.reflect(CTX, MEMO)
        self.assertEqual(second, first)
        self.assertEqual(second, {"source_id": "src-memo-2", "source_version_id": "sv-memo-2-1", "revision_no": 2})
        self.assertEqual([r["key"] for r in texts.registered[1:]], [f"memo-reflect:{MEMO}:2"] * 2)
        self.assertEqual((len(db.unbindings), len(db.activities), len(db.audits)), (1, 1, 1))
        self.assertTrue(db.active("notebook-1", "src-memo-2"))

    def test_previous_source_already_removed_still_moves_the_link_without_unbinding_twice(self):
        db, _, service = self.edited()
        # 읽은 뒤 사용자가 이전 소스를 노트북에서 직접 뗐다.
        db.after_read = lambda: db.unbindings.append({"notebook_id": "notebook-1", "source_id": "src-memo-1",
                                                      "source_version_id": "sv-memo-1-1", "binding_version": 2,
                                                      "actor_id": "actor-1"})
        self.assertEqual(service.reflect(CTX, MEMO)["source_id"], "src-memo-2")
        self.assertEqual(len(db.unbindings), 1)
        self.assertEqual((db.activities, db.audits), ([], []))
        self.assertEqual(db.links[MEMO]["source_id"], "src-memo-2")

    def test_not_linked_and_removed_sources(self):
        db, texts, service = make()
        self.assert_code("MEMO_SOURCE_NOT_LINKED", 404, service.reflect, CTX, MEMO)
        service.create(CTX, MEMO)
        db.outputs[MEMO]["revision"] = 2
        db.inactive.add("src-memo-1")
        self.assert_code("MEMO_SOURCE_NOT_LINKED", 404, service.reflect, CTX, MEMO)
        self.assertEqual(len(texts.registered), 1)

    def test_reflect_after_memo_deleted_is_not_found(self):
        db, _, service = make()
        service.create(CTX, MEMO)
        db.outputs[MEMO]["deleted"] = True
        self.assert_code("STUDIO_OUTPUT_NOT_FOUND", 404, service.reflect, CTX, MEMO)

    def test_empty_memo_is_rejected_before_registering(self):
        db, texts, service = make()
        service.create(CTX, MEMO)
        db.outputs[MEMO].update(revision=2, markdown=" \n")
        self.assert_code("MEMO_EMPTY", 422, service.reflect, CTX, MEMO)
        self.assertEqual(len(texts.registered), 1)

    def test_reflect_maps_text_source_errors_and_leaves_the_link(self):
        db, texts, service = self.edited()
        for error, code, status in ((TextSourceError("TEXT_SOURCE_EMPTY", 422), "MEMO_EMPTY", 422),
                                    (TextSourceError("TEXT_SOURCE_TOO_LARGE", 413), "MEMO_TOO_LARGE", 413),
                                    (TextSourceError("TEXT_SOURCE_INPUT_INVALID", 400), "STUDIO_INPUT_INVALID", 400)):
            texts.fail = error
            self.assert_code(code, status, service.reflect, CTX, MEMO)
        self.assertEqual(db.links[MEMO]["source_id"], "src-memo-1")
        self.assertEqual(db.unbindings, [])

    def test_reflect_never_updates_or_locks_append_only_tables(self):
        """앱 역할(daon_app)은 이 표들에 UPDATE가 없다. UPDATE도 SELECT … FOR UPDATE도 쓰면 안 된다."""
        db, _, service = self.edited()
        db.executed.clear()
        service.reflect(CTX, MEMO)
        self.assertTrue(db.executed)
        protected = r"(sources|source_versions|notebook_bindings|notebook_source_unbindings)"
        for sql in db.executed:
            self.assertNotRegex(sql, r"(?i)\bFOR\s+UPDATE\b")
            self.assertNotRegex(sql, r"(?i)\bUPDATE\s+" + protected + r"\b")
        updated = [re.search(r"(?i)\bUPDATE\s+(\w+)", sql).group(1) for sql in db.executed if re.search(r"(?i)\bUPDATE\s+\w+", sql)]
        self.assertEqual(updated, ["memo_source_links"])


class MemoSourceViewTests(unittest.TestCase):
    def test_source_link_reports_outdated_and_null(self):
        db, _, service = make()
        self.assertIsNone(service.source_link(CTX, MEMO, 1))
        service.create(CTX, MEMO)
        self.assertEqual(service.source_link(CTX, MEMO, 1), {"source_id": "src-memo-1", "reflected_revision_no": 1, "outdated": False})
        self.assertEqual(service.source_link(CTX, MEMO, 2), {"source_id": "src-memo-1", "reflected_revision_no": 1, "outdated": True})
        db.inactive.add("src-memo-1")
        self.assertIsNone(service.source_link(CTX, MEMO, 2))

    def test_deleted_memo_keeps_source_and_link_with_memo_exists_false(self):
        db, _, service = make()
        service.create(CTX, MEMO)
        self.assertEqual(service.memo_origins(CTX), {"src-memo-1": {"memo_output_id": MEMO, "memo_exists": True}})
        db.outputs[MEMO]["deleted"] = True       # soft_delete
        self.assertIn(MEMO, db.links)
        self.assertEqual(db.source_versions["src-memo-1"], [("sv-memo-1-1", 1)])
        self.assertEqual(service.memo_origins(CTX), {"src-memo-1": {"memo_output_id": MEMO, "memo_exists": False}})

    def test_origins_are_scoped_to_the_notebook(self):
        _, _, service = make()
        service.create(CTX, MEMO)
        other = StudioContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1", "notebook-2")
        self.assertEqual(service.memo_origins(other), {})

    def test_sql_never_selects_memo_body_into_links_and_link_sql_checks_latest_binding(self):
        for name in ("_LINK_SQL", "_ORIGINS_SQL"):
            self.assertNotIn("content_json", getattr(memo_source, name))
        self.assertIn("notebook_source_unbindings", memo_source._ACTIVE_SQL)
        self.assertIn("deletion_requests", memo_source._ACTIVE_SQL)
        self.assertIn("nv.version>sv.version", memo_source._ACTIVE_SQL)


class ReadySourceVersionTests(unittest.TestCase):
    def test_default_studio_scope_uses_only_the_latest_version_of_a_source(self):
        """반영 뒤 기본 생성 범위에 옛 메모 버전과 새 버전이 함께 들어가지 않는다."""
        from daon2_user_api.studio_v2_postgres import PostgresStudioV2Repository
        seen = []

        class Connection:
            def execute(self, sql, params=()):
                seen.append(sql)
                return SimpleNamespace(fetchall=lambda: [("sv-2",)])

        repo = PostgresStudioV2Repository(None)
        self.assertEqual(repo.ready_source_versions(Connection(), CTX), ["sv-2"])
        self.assertIn("NOT EXISTS(SELECT 1 FROM source_versions nv WHERE nv.tenant_id=sv.tenant_id AND nv.workspace_id=sv.workspace_id "
                      "AND nv.source_id=sv.source_id AND nv.version>sv.version)", seen[0])


if __name__ == "__main__":
    unittest.main()
