"""대화 수정 턴 저장소 마이그레이션(WO-K5)."""
import re
import unittest
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0083_studio_v2_edit_turns.sql").read_text(encoding="utf-8")
PY = (VERSIONS / "0083_studio_v2_edit_turns.py").read_text(encoding="utf-8")


class EditTurnsMigrationTests(unittest.TestCase):
    def test_revision_chain(self):
        self.assertIn("revision = '0083'", PY)
        self.assertIn("down_revision = '0082'", PY)

    def test_precondition(self):
        self.assertIn("STUDIO_V2_EDIT_TURNS_PRECONDITION", SQL)
        self.assertIn("<>'0082'", SQL)

    def test_table_is_protected(self):
        for text in ("CREATE TABLE public.studio_v2_edit_turns (", "FORCE ROW LEVEL SECURITY", "OWNER TO daon_notebook_delete",
                     "ON DELETE CASCADE", "app.tenant_id", "app.workspace_id"):
            self.assertIn(text, SQL)

    def test_states_and_instruction_limit(self):
        for state in ("queued", "working", "ready", "no_change", "failed", "applied", "discarded"):
            self.assertIn(f"'{state}'", SQL)
        self.assertIn("char_length(instruction) BETWEEN 1 AND 2000", SQL)

    def test_one_active_turn_per_output(self):
        self.assertRegex(SQL, r"CREATE UNIQUE INDEX \w+ ON public\.studio_v2_edit_turns\(tenant_id,workspace_id,output_id\) WHERE state IN \('queued','working'\)")

    def test_app_role_can_update(self):
        self.assertIn("GRANT SELECT,INSERT,UPDATE ON public.studio_v2_edit_turns TO daon_app", SQL)

    def test_downgrade_refuses_when_rows_exist(self):
        self.assertIn("STUDIO_V2_EDIT_TURNS_FORWARD_RECOVERY_REQUIRED", PY)
        self.assertIsNotNone(re.search(r"<>'0083'", PY))


if __name__ == "__main__":
    unittest.main()
