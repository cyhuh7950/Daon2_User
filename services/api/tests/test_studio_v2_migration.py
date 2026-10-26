import re
import unittest
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0074_studio_v2.sql").read_text(encoding="utf-8")
PY = (VERSIONS / "0074_studio_v2.py").read_text(encoding="utf-8")
TABLES = (
    "studio_v2_outputs", "studio_v2_revisions", "studio_v2_sources", "studio_v2_evidence",
    "studio_v2_assets", "studio_v2_jobs", "studio_v2_learning_attempts", "workspace_studio_v2_customization",
)


class StudioV2MigrationTests(unittest.TestCase):
    def test_revision_chain(self):
        self.assertIn("revision = '0074'", PY)
        self.assertIn("down_revision = '0073'", PY)

    def test_precondition_pins_previous_revision_and_roles(self):
        self.assertIn("STUDIO_V2_PRECONDITION", SQL)
        self.assertIn("<>'0073'", SQL)
        self.assertIn("daon_notebook_delete", SQL)

    def test_every_table_is_created_and_protected_by_rls(self):
        for table in TABLES:
            self.assertRegex(SQL, rf"CREATE TABLE public\.{table} \(")
            self.assertIn(f"'{table}'", SQL)
        self.assertIn("FORCE ROW LEVEL SECURITY", SQL)
        self.assertIn("OWNER TO daon_notebook_delete", SQL)
        self.assertIn("app.tenant_id", SQL)
        self.assertIn("app.workspace_id", SQL)

    def test_learning_attempts_are_scoped_to_the_user(self):
        self.assertIn("user_id=nullif(current_setting('app.actor_id',true),'')", SQL)

    def test_immutable_tables_have_no_update_grant(self):
        grant = re.search(r"GRANT SELECT,INSERT ON ([^;]+) TO daon_app;", SQL)
        self.assertIsNotNone(grant)
        for table in ("studio_v2_revisions", "studio_v2_sources", "studio_v2_evidence", "studio_v2_learning_attempts"):
            self.assertIn(table, grant.group(1))
        self.assertNotRegex(SQL, r"GRANT [^;]*DELETE[^;]*TO daon_app")

    def test_no_functions_or_triggers(self):
        self.assertNotRegex(SQL, r"CREATE (OR REPLACE )?(FUNCTION|TRIGGER)")

    def test_notebook_delete_cascades(self):
        self.assertGreaterEqual(SQL.count("REFERENCES public.notebooks(tenant_id,workspace_id,notebook_id) ON DELETE CASCADE"), 2)

    def test_job_lease_invariant_and_types(self):
        self.assertIn("(state IN ('leased','generating')) = (lease_owner IS NOT NULL AND lease_until IS NOT NULL)", SQL)
        for type_id in ("report", "data_table", "mind_map", "flashcards", "quiz", "slides", "infographic",
                        "audio_overview", "video_overview", "memo", "authored_document"):
            self.assertIn(f"'{type_id}'", SQL)

    def test_downgrade_refuses_when_rows_exist(self):
        self.assertIn("STUDIO_V2_FORWARD_RECOVERY_REQUIRED", PY)
        self.assertIn("'0074'", PY)
        for table in TABLES:
            self.assertIn(table, PY)


if __name__ == "__main__":
    unittest.main()
