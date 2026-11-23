"""노트북 개요·추천 질문 저장소 마이그레이션(WO-N1 N1-4, NB2-F2)."""
import re
import unittest
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0086_notebook_overviews.sql").read_text(encoding="utf-8")
PY = (VERSIONS / "0086_notebook_overviews.py").read_text(encoding="utf-8")


class NotebookOverviewsMigrationTests(unittest.TestCase):
    def test_revision_chain(self):
        self.assertIn("revision = '0086'", PY)
        self.assertIn("down_revision = '0085'", PY)

    def test_precondition_requires_superuser_previous_revision_and_app_role(self):
        self.assertIn("NOTEBOOK_OVERVIEWS_PRECONDITION", SQL)
        self.assertIn("rolsuper", SQL)
        self.assertIn("<>'0085'", SQL)
        self.assertIn("rolname='daon_app'", SQL)

    def test_columns_states_and_primary_key(self):
        for column in ("tenant_id text NOT NULL", "workspace_id text NOT NULL", "notebook_id text NOT NULL",
                       "state text NOT NULL", "summary text", "questions jsonb NOT NULL", "citations jsonb NOT NULL",
                       "source_fingerprint text", "model_ref text", "safe_error_code text", "attempt integer NOT NULL",
                       "lease_until timestamptz", "requested_by text NOT NULL", "created_at timestamptz NOT NULL",
                       "updated_at timestamptz NOT NULL"):
            self.assertIn(column, SQL)
        self.assertIn("CHECK (state IN ('queued','working','ready','failed','blocked'))", SQL)
        self.assertIn("PRIMARY KEY (tenant_id,workspace_id,notebook_id)", SQL)
        self.assertIn("CHECK (jsonb_typeof(questions)='array')", SQL)
        self.assertIn("CHECK (jsonb_typeof(citations)='array')", SQL)
        self.assertIn("source_fingerprint ~ '^[0-9a-f]{64}$'", SQL)

    def test_notebook_cascades(self):
        self.assertRegex(SQL, r"FOREIGN KEY \(tenant_id,workspace_id,notebook_id\) REFERENCES public\.notebooks\(tenant_id,workspace_id,notebook_id\) ON DELETE CASCADE")

    def test_table_is_shared_by_workspace_rls_like_studio_v2(self):
        for text in ("CREATE TABLE public.notebook_overviews (", "ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY",
                     "OWNER TO daon_notebook_delete", "REVOKE ALL ON TABLE public.notebook_overviews FROM PUBLIC"):
            self.assertIn(text, SQL)
        policy = re.search(r"CREATE POLICY notebook_overviews_scope ON public\.notebook_overviews(.*?);", SQL, re.S)
        self.assertIsNotNone(policy)
        body = policy.group(1)
        self.assertEqual(body.count("tenant_id=nullif(current_setting('app.tenant_id',true),'')"), 2)
        self.assertEqual(body.count("workspace_id=nullif(current_setting('app.workspace_id',true),'')"), 2)
        self.assertNotIn("actor_id", body)  # 노트북 공유 저장: 사용자 기준이 아니다

    def test_worker_policy_opens_only_for_overview_worker_capability(self):
        policy = re.search(r"CREATE POLICY notebook_overviews_worker ON public\.notebook_overviews(.*?);", SQL, re.S)
        self.assertIsNotNone(policy)
        self.assertEqual(policy.group(1).count("current_setting('app.capability',true)='notebook_overview.worker'"), 2)

    def test_pending_index(self):
        self.assertIn("CREATE INDEX notebook_overviews_pending_idx ON public.notebook_overviews(updated_at) WHERE state IN ('queued','working')", SQL)

    def test_app_role_gets_only_select_insert_update(self):
        self.assertIn("GRANT SELECT,INSERT,UPDATE ON public.notebook_overviews TO daon_app", SQL)
        self.assertNotIn("DELETE ON public.notebook_overviews TO daon_app", SQL)

    def test_no_functions_or_triggers_and_no_canon_changes(self):
        self.assertNotRegex(SQL, r"CREATE (OR REPLACE )?(FUNCTION|TRIGGER)")
        for canon in ("sources", "source_versions", "notebook_bindings", "notebook_source_unbindings"):
            self.assertNotRegex(SQL, rf"(ALTER|GRANT[^;]*ON)\s+(TABLE\s+)?public\.{canon}\b")

    def test_downgrade_refuses_when_rows_exist(self):
        self.assertIn("NOTEBOOK_OVERVIEWS_FORWARD_RECOVERY_REQUIRED", PY)
        self.assertIn("NOTEBOOK_OVERVIEWS_DOWN_PRECONDITION", PY)
        self.assertIsNotNone(re.search(r"<>'0086'", PY))
        self.assertIn("DROP TABLE public.notebook_overviews", PY)


if __name__ == "__main__":
    unittest.main()
