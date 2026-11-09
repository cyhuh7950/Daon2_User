"""대화 수정 턴의 저장과 반영 규칙(WO-K5 §6, §7)."""
from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from daon2_user_api.studio_v2_edit_turns import COLUMNS, StudioV2EditTurnsMixin
from daon2_user_api.studio_workspace import StudioContext, StudioError

CTX = StudioContext("t", "w", "a", "trace", "policy", "nb")
OID = "sv2-" + "a" * 32
KEY = "k" * 16
REPORT = {"body": {"title": "제목", "summary": "요약", "sections": [{"heading": "1장", "blocks": [{"type": "paragraph", "text": "가", "refs": ["S1"]}]}]}}
CHANGE = {"op": "replace", "id": "s1.b1", "content": {"type": "paragraph", "text": "고침", "refs": ["S1"]}, "reason": "요청", "before_text": "가", "after_text": "고침"}


def turn(**over):  # type: ignore[no-untyped-def]
    return {"turn_id": "svt-1", "output_id": OID, "job_id": "sve-1", "base_revision": 3, "instruction": "고쳐 줘", "state": "ready", "reply": "고쳤습니다",
            "changes_json": [CHANGE], "new_evidence_json": [], "error_code": None, "applied_revision": None, "created_at": datetime(2026, 11, 10, tzinfo=timezone.utc), **over}


class FakeConnection:
    def __init__(self, repo):  # type: ignore[no-untyped-def]
        self.repo = repo

    def execute(self, sql, params=()):  # type: ignore[no-untyped-def]
        repo = self.repo
        repo.sql.append((sql, params))
        row = None
        rows: list = []
        if sql.startswith("SELECT turn_id"):
            found = [t for t in repo.turns if ("idempotency_key_sha256" not in sql or t.get("key") == params[-1])]
            if "turn_id=%s" in sql:
                found = [t for t in repo.turns if t["turn_id"] == params[-1]]
            row = tuple(found[0][c] for c in COLUMNS) if found else None
            rows = [tuple(t[c] for c in COLUMNS) for t in found]
        elif sql.startswith("SELECT 1 FROM studio_v2_edit_turns"):
            row = (1,) if any(t["state"] in ("queued", "working") for t in repo.turns) else None
        elif sql.startswith("SELECT content_json"):
            row = (REPORT,)
        elif sql.startswith("SELECT ref_id"):
            rows = [("S1",)]
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: rows)


class Repo(StudioV2EditTurnsMixin):
    def __init__(self, *, type_id="report", status="completed", current=3, turns=()):  # type: ignore[no-untyped-def]
        self.row = (OID, type_id, None, "제목", status, None, {}, [], current)
        self.turns = list(turns)
        self.sql: list = []
        self.revisions: list = []
        self.jobs: list = []
        self.lineage: list = []
        self._cloud_store = self

    @contextmanager
    def _transaction(self, scope):  # type: ignore[no-untyped-def]
        yield FakeConnection(self)

    def _cloud(self, context, capability):  # type: ignore[no-untyped-def]
        return capability

    def _require_notebook(self, context):  # type: ignore[no-untyped-def]
        return context.notebook_id

    def _owned_output(self, connection, context, output_id, *, lock=False):  # type: ignore[no-untyped-def]
        return self.row

    def _insert_job(self, connection, context, output_id, job_id, mode, type_id, format_id, settings, versions, notebook_id):  # type: ignore[no-untyped-def]
        self.jobs.append((mode, type_id, settings, versions))

    def add_revision(self, context, output_id, revision_type, content, **kwargs):  # type: ignore[no-untyped-def]
        self.revisions.append((revision_type, content, kwargs))
        return self.row[8] + 1

    def _copy_lineage(self, connection, context, output_id, number, current):  # type: ignore[no-untyped-def]
        self.lineage.append((number, current))

    def updates(self, needle: str) -> list:
        return [s for s in self.sql if s[0].startswith("UPDATE studio_v2_edit_turns") and needle in s[0]]


class EnqueueTests(unittest.TestCase):
    def assert_code(self, code, fn, *args):  # type: ignore[no-untyped-def]
        with self.assertRaises(StudioError) as caught:
            fn(*args)
        self.assertEqual(caught.exception.code, code)

    def test_enqueue_creates_turn_and_chat_edit_job(self):
        repo = Repo()
        result = repo.enqueue_edit_turn(CTX, OID, " 고쳐 줘 ", KEY)
        self.assertEqual((result["state"], result["replayed"]), ("queued", False))
        self.assertEqual(repo.jobs, [("chat_edit", "report", {"turn_id": result["turn_id"]}, [])])
        insert = next(s for s in repo.sql if s[0].startswith("INSERT INTO studio_v2_edit_turns"))
        self.assertIn("고쳐 줘", insert[1])
        self.assertNotIn(" 고쳐 줘 ", insert[1])
        self.assertIn(3, insert[1])

    def test_enqueue_rejects_unsupported_type(self):
        self.assert_code("CHAT_EDIT_UNSUPPORTED", Repo(type_id="memo").enqueue_edit_turn, CTX, OID, "고쳐", KEY)

    def test_enqueue_rejects_active_output(self):
        self.assert_code("STUDIO_VERSION_CONFLICT", Repo(status="generating").enqueue_edit_turn, CTX, OID, "고쳐", KEY)

    def test_enqueue_rejects_second_active_turn(self):
        self.assert_code("CHAT_EDIT_BUSY", Repo(turns=[turn(state="working", key="other")]).enqueue_edit_turn, CTX, OID, "고쳐", KEY)

    def test_enqueue_replays_same_key(self):
        from daon2_user_api.studio_v2_postgres import sha256_hex
        repo = Repo(turns=[turn(state="queued", key=sha256_hex(KEY), instruction="고쳐")])
        result = repo.enqueue_edit_turn(CTX, OID, "고쳐", KEY)
        self.assertEqual((result["turn_id"], result["replayed"]), ("svt-1", True))
        self.assertEqual(repo.jobs, [])

    def test_same_key_with_other_instruction_conflicts(self):
        from daon2_user_api.studio_v2_postgres import sha256_hex
        self.assert_code("IDEMPOTENCY_CONFLICT", Repo(turns=[turn(key=sha256_hex(KEY), instruction="앞 지시")]).enqueue_edit_turn, CTX, OID, "다른 지시", KEY)

    def test_instruction_length(self):
        for value in ("", "   ", "가" * 2001):
            with self.subTest(size=len(value)):
                self.assert_code("STUDIO_INPUT_INVALID", Repo().enqueue_edit_turn, CTX, OID, value, KEY)


class ResultTests(unittest.TestCase):
    def test_changes_mean_ready_and_empty_means_no_change(self):
        repo = Repo()
        repo.save_edit_turn_result(CTX, "svt-1", reply="답", changes=[CHANGE], new_evidence=[])
        repo.save_edit_turn_result(CTX, "svt-1", reply="못 합니다", changes=[], new_evidence=[])
        states = [s[1][0] for s in repo.sql if s[0].startswith("UPDATE")]
        self.assertEqual(states, ["ready", "no_change"])

    def test_list_hides_internal_content(self):
        rows = Repo(turns=[turn()]).list_edit_turns(CTX, OID)
        self.assertEqual(rows[0]["changes"], [{"op": "replace", "id": "s1.b1", "before_text": "가", "after_text": "고침", "reason": "요청"}])
        self.assertNotIn("new_evidence_json", rows[0])
        self.assertEqual(rows[0]["created_at"], "2026-11-10T00:00:00+00:00")


class ApplyTests(unittest.TestCase):
    def assert_code(self, code, repo):  # type: ignore[no-untyped-def]
        with self.assertRaises(StudioError) as caught:
            repo.apply_edit_turn(CTX, OID, "svt-1")
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(repo.revisions, [])

    def test_apply_saves_new_revision_and_marks_turn(self):
        repo = Repo(turns=[turn()])
        self.assertEqual(repo.apply_edit_turn(CTX, OID, "svt-1"), 4)
        self.assertEqual(repo.revisions[0][1]["body"]["sections"][0]["blocks"][0]["text"], "고침")
        self.assertEqual(repo.lineage, [(4, 3)])
        self.assertTrue(repo.updates("state='applied'"))

    def test_apply_records_origin(self):
        repo = Repo(turns=[turn(instruction="가" * 300)])
        repo.apply_edit_turn(CTX, OID, "svt-1")
        generated = repo.revisions[0][2]["generated_with"]
        self.assertEqual((generated["edited_by"], len(generated["change_reason"])), ("llm_chat", 200))

    def test_apply_adds_new_evidence(self):
        change = {**CHANGE, "content": {"type": "paragraph", "text": "고침", "refs": ["S7"]}}
        repo = Repo(turns=[turn(changes_json=[change], new_evidence_json=[{"ref_id": "S7"}])])
        repo.apply_edit_turn(CTX, OID, "svt-1")
        self.assertEqual(repo.revisions[0][1]["body"]["sections"][0]["blocks"][0]["refs"], ["S7"])
        self.assertEqual(repo.revisions[0][2]["evidence"], [{"ref_id": "S7"}])

    def test_apply_rejects_stale_base(self):
        self.assert_code("CHAT_EDIT_STALE", Repo(current=4, turns=[turn()]))

    def test_apply_rejects_active_output(self):
        self.assert_code("STUDIO_VERSION_CONFLICT", Repo(status="generating", turns=[turn()]))

    def test_apply_is_idempotent(self):
        repo = Repo(turns=[turn(state="applied", applied_revision=4)])
        self.assertEqual(repo.apply_edit_turn(CTX, OID, "svt-1"), 4)
        self.assertEqual(repo.revisions, [])

    def test_apply_invalid_changes_keeps_output(self):
        repo = Repo(turns=[turn(changes_json=[{"op": "delete", "id": "s9"}])])
        self.assert_code("CHAT_EDIT_INVALID", repo)
        self.assertFalse(repo.updates("state='applied'"))

    def test_apply_requires_ready(self):
        self.assert_code("CHAT_EDIT_STATE_INVALID", Repo(turns=[turn(state="no_change")]))

    def test_other_output_is_hidden(self):
        self.assert_code("RESOURCE_UNAVAILABLE", Repo(turns=[turn(output_id="sv2-other")]))

    def test_discard_only_ready(self):
        repo = Repo(turns=[turn()])
        repo.discard_edit_turn(CTX, OID, "svt-1")
        self.assertTrue(repo.updates("state='discarded'"))
        with self.assertRaises(StudioError) as caught:
            Repo(turns=[turn(state="applied")]).discard_edit_turn(CTX, OID, "svt-1")
        self.assertEqual(caught.exception.code, "CHAT_EDIT_STATE_INVALID")


class CancelTests(unittest.TestCase):
    def test_output_cancel_leaves_chat_edit_jobs_alone(self):
        import inspect
        from daon2_user_api.studio_v2_postgres import PostgresStudioV2Repository
        sql = []
        connection = SimpleNamespace(execute=lambda statement, params=(): (sql.append(statement), SimpleNamespace(fetchone=lambda: None, fetchall=lambda: []))[1])
        method = inspect.getattr_static(PostgresStudioV2Repository, "_cancel_jobs")
        (method.__func__ if isinstance(method, staticmethod) else method)(*([connection, CTX, OID] if isinstance(method, staticmethod) else [None, connection, CTX, OID]))
        self.assertTrue(sql)
        self.assertTrue(all("request_json->>'mode'" in statement and "chat_edit" in statement for statement in sql))


if __name__ == "__main__":
    unittest.main()
