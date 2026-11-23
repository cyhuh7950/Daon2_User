"""메모를 소스로 저장·조회 계약(WO-N1 NB1-F2, 결정 D-10)."""
from __future__ import annotations

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
    """메모·연결·소스 버전을 기억하는 작은 저장소. 서비스의 SQL 상수만 알아듣는다."""

    def __init__(self):
        self.outputs = {MEMO: {"type_id": "memo", "title": "회의 메모", "revision": 1, "markdown": "첫 메모", "deleted": False},
                        REPORT: {"type_id": "report", "title": "보고서", "revision": 1, "markdown": None, "deleted": False}}
        self.links: dict[str, dict] = {}
        self.source_versions: dict[str, list[tuple[str, int]]] = {}
        self.source_state: dict[str, str] = {}
        self.inactive: set[str] = set()
        self.output_sources: dict[str, str] = {}   # 산출물 -> 근거로 쓴 source_version_id
        self.after_read = None

    @contextmanager
    def _transaction(self, scope):
        yield FakeConnection(self)

    def stale(self, output_id: str) -> bool:
        """_STALE_SQL의 '같은 소스의 더 새 버전' 조건을 그대로 흉내 낸다."""
        used = self.output_sources[output_id]
        for versions in self.source_versions.values():
            numbers = {vid: number for vid, number in versions}
            if used in numbers and any(number > numbers[used] for number in numbers.values()):
                return True
        return False


class FakeConnection:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=()):
        db = self.db
        row, rows = None, []
        if sql == memo_source._MEMO_SQL:
            output = db.outputs.get(params[2])
            if output is not None and not output["deleted"] and params[3] == "notebook-1":
                content = None if output["markdown"] is None else {"schema": "studio.memo.v1", "body": {"markdown": output["markdown"], "refs": []}}
                row = (output["type_id"], output["title"], output["revision"], content)
            if db.after_read is not None:
                db.after_read()
                db.after_read = None
        elif sql == memo_source._LINK_SQL:
            link = db.links.get(params[2])
            if link is not None:
                row = (link["source_id"], link["reflected_revision_no"], link["source_id"] not in db.inactive)
        elif sql == memo_source._INSERT_LINK_SQL:
            if params[3] not in db.links:
                db.links[params[3]] = {"notebook_id": params[2], "source_id": params[4], "reflected_revision_no": params[5]}
                row = (params[4],)
        elif sql == memo_source._REPLACE_LINK_SQL:
            link = db.links.get(params[5])
            if link is not None and link["source_id"] == params[6]:
                link.update(source_id=params[0], reflected_revision_no=params[1])
                row = (1,)
        elif sql == memo_source._REFLECT_LINK_SQL:
            link = db.links.get(params[3])
            if link is not None and link["source_id"] == params[4] and link["reflected_revision_no"] == params[5]:
                link["reflected_revision_no"] = params[0]
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
    def __init__(self, db):
        self.db = db
        self.registered: list[dict] = []
        self.appended: list[dict] = []
        self.fail = None

    def register_text_source(self, context, notebook_id, *, title, text, origin, idempotency_key=None):
        if self.fail:
            raise self.fail
        self.registered.append({"notebook_id": notebook_id, "title": title, "text": text, "origin": origin, "key": idempotency_key})
        number = len(self.registered)
        source_id, version_id = f"src-memo-{number}", f"sv-memo-{number}-1"
        self.db.source_versions[source_id] = [(version_id, 1)]
        self.db.source_state[source_id] = "processing"
        return source_id, version_id

    def append_text_version(self, context, source_id, text, *, idempotency_key=None, within=None):
        if self.fail:
            raise self.fail
        versions = self.db.source_versions[source_id]
        number = max(n for _, n in versions) + 1
        version_id = f"{source_id}-v{number}"
        snapshot = list(versions)
        versions.append((version_id, number))
        self.appended.append({"source_id": source_id, "text": text, "key": idempotency_key})
        try:
            if within is not None:
                within(FakeConnection(self.db), version_id)
        except Exception:
            self.db.source_versions[source_id] = snapshot   # 같은 트랜잭션이므로 되돌린다
            self.appended.pop()
            raise
        return version_id


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

    def test_reflect_appends_a_version_and_marks_existing_outputs_stale(self):
        db, texts, service = make()
        service.create(CTX, MEMO)
        db.output_sources[REPORT] = "sv-memo-1-1"     # 메모 소스로 만든 기존 산출물
        self.assertFalse(db.stale(REPORT))
        db.outputs[MEMO].update(revision=2, markdown="고친 메모")
        result = service.reflect(CTX, MEMO)
        self.assertEqual(result, {"source_id": "src-memo-1", "source_version_id": "src-memo-1-v2", "revision_no": 2})
        self.assertEqual(texts.appended[0], {"source_id": "src-memo-1", "text": "고친 메모", "key": f"memo-reflect:{MEMO}:2"})
        self.assertEqual(db.links[MEMO]["reflected_revision_no"], 2)
        self.assertEqual([n for _, n in db.source_versions["src-memo-1"]], [1, 2])
        self.assertTrue(db.stale(REPORT))
        # 실제 판정 SQL도 같은 소스의 더 새 버전을 본다.
        self.assertIn("nv.source_id=sv.source_id AND nv.version>sv.version", _STALE_SQL)

    def test_unchanged_memo_is_conflict(self):
        _, texts, service = make()
        service.create(CTX, MEMO)
        self.assert_code("MEMO_SOURCE_UNCHANGED", 409, service.reflect, CTX, MEMO)
        self.assertEqual(texts.appended, [])

    def test_concurrent_reflect_rolls_back(self):
        db, texts, service = make()
        service.create(CTX, MEMO)
        db.outputs[MEMO].update(revision=2, markdown="고친 메모")
        db.after_read = lambda: db.links[MEMO].__setitem__("reflected_revision_no", 2)
        self.assert_code("MEMO_SOURCE_UNCHANGED", 409, service.reflect, CTX, MEMO)
        self.assertEqual([n for _, n in db.source_versions["src-memo-1"]], [1])

    def test_not_linked_and_removed_sources(self):
        db, _, service = make()
        self.assert_code("MEMO_SOURCE_NOT_LINKED", 404, service.reflect, CTX, MEMO)
        service.create(CTX, MEMO)
        db.outputs[MEMO]["revision"] = 2
        db.inactive.add("src-memo-1")
        self.assert_code("MEMO_SOURCE_NOT_LINKED", 404, service.reflect, CTX, MEMO)

    def test_reflect_after_memo_deleted_is_not_found(self):
        db, _, service = make()
        service.create(CTX, MEMO)
        db.outputs[MEMO]["deleted"] = True
        self.assert_code("STUDIO_OUTPUT_NOT_FOUND", 404, service.reflect, CTX, MEMO)

    def test_reflect_maps_text_source_errors(self):
        db, texts, service = make()
        service.create(CTX, MEMO)
        db.outputs[MEMO]["revision"] = 2
        for error, code, status in ((TextSourceError("TEXT_SOURCE_NOT_FOUND", 404), "MEMO_SOURCE_NOT_LINKED", 404),
                                    (TextSourceError("SOURCE_PROCESSING_ACTIVE", 409), "SOURCE_PROCESSING_ACTIVE", 409),
                                    (TextSourceError("TEXT_SOURCE_NOT_TEXT", 409), "MEMO_SOURCE_NOT_LINKED", 404)):
            texts.fail = error
            self.assert_code(code, status, service.reflect, CTX, MEMO)


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
