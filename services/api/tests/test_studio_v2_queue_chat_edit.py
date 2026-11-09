"""대화 수정 작업은 큐를 쓰지만 자료 상태를 건드리지 않는다(WO-K5 §5.4)."""
from __future__ import annotations

import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from daon2_user_api.studio_v2_queue import CHAT_EDIT_MODE, PostgresStudioV2Queue, StudioV2Job


class FakeConnection:
    def __init__(self, sql: list[str], sweep_rows: list[tuple]) -> None:
        self._sql, self._sweep_rows = sql, sweep_rows

    def execute(self, statement, params=()):  # type: ignore[no-untyped-def]
        self._sql.append(statement)
        return SimpleNamespace(fetchone=lambda: (2,), fetchall=lambda: self._sweep_rows)


class FakeCloud:
    def __init__(self, sweep_rows: list[tuple]) -> None:
        self.sql: list[str] = []
        self._sweep_rows = sweep_rows

    @contextmanager
    def _transaction(self, scope):  # type: ignore[no-untyped-def]
        yield FakeConnection(self.sql, self._sweep_rows)


def make_queue(sweep_rows=()):  # type: ignore[no-untyped-def]
    cloud = FakeCloud(list(sweep_rows))
    return PostgresStudioV2Queue(cloud), cloud.sql


def make_job(request) -> StudioV2Job:  # type: ignore[no-untyped-def]
    return StudioV2Job("t", "w", "job-1", "o", "a", 1, 3, 1, request)


def output_updates(sql: list[str]) -> list[str]:
    return [statement for statement in sql if "UPDATE studio_v2_outputs" in statement]


class ChatEditQueueTests(unittest.TestCase):
    def test_mode_name(self):
        self.assertEqual(CHAT_EDIT_MODE, "chat_edit")

    def test_chat_edit_start_retry_finish_leave_output_alone(self):
        queue, sql = make_queue()
        job = make_job({"mode": CHAT_EDIT_MODE})
        queue.start(job, "w")
        queue.retry(job, "w", error_code="X")
        queue.finish(job, "w", state="completed")
        self.assertEqual(output_updates(sql), [])

    def test_other_modes_still_update_output(self):
        for action in ("start", "retry", "finish"):
            with self.subTest(action=action):
                queue, sql = make_queue()
                job = make_job({"mode": "create"})
                if action == "start":
                    queue.start(job, "w")
                elif action == "retry":
                    queue.retry(job, "w", error_code="X")
                else:
                    queue.finish(job, "w", state="completed")
                self.assertTrue(output_updates(sql))

    def test_sweep_fails_chat_turn_instead_of_output(self):
        queue, sql = make_queue([("t", "w", "o", "a", "failed", "STUDIO_DEAD_LETTER", CHAT_EDIT_MODE, "job-1")])
        self.assertEqual(queue.sweep(), 1)
        self.assertEqual(output_updates(sql), [])
        turns = [statement for statement in sql if "UPDATE studio_v2_edit_turns" in statement]
        self.assertEqual(len(turns), 1)
        self.assertIn("state='failed'", turns[0])
        self.assertIn("state IN ('queued','working')", turns[0])

    def test_sweep_still_syncs_other_outputs(self):
        queue, sql = make_queue([("t", "w", "o", "a", "failed", "STUDIO_DEAD_LETTER", "create", "job-1")])
        queue.sweep()
        self.assertTrue(output_updates(sql))


if __name__ == "__main__":
    unittest.main()
