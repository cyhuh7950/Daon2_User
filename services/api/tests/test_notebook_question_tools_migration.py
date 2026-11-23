"""노트북·사용자별 질문 도구 선택 저장소 마이그레이션(WO-N1 N1-2, NB2-F1)."""
import re
import unittest
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0085_notebook_question_tools.sql").read_text(encoding="utf-8")
PY = (VERSIONS / "0085_notebook_question_tools.py").read_text(encoding="utf-8")


class NotebookQuestionToolsMigrationTests(unittest.TestCase):
    def test_revision_chain(self):
        self.assertIn("revision = '0085'", PY)
        self.assertIn("down_revision = '0084'", PY)

    def test_precondition_requires_superuser_previous_revision_and_app_role(self):
        self.assertIn("NOTEBOOK_QUESTION_TOOLS_PRECONDITION", SQL)
        self.assertIn("rolsuper", SQL)
        self.assertIn("<>'0084'", SQL)
        self.assertIn("rolname='daon_app'", SQL)

    def test_columns_and_primary_key(self):
        for column in ("tenant_id text NOT NULL", "workspace_id text NOT NULL", "notebook_id text NOT NULL",
                       "actor_id text NOT NULL", "enabled_json jsonb NOT NULL", "updated_at timestamptz NOT NULL"):
            self.assertIn(column, SQL)
        self.assertIn("PRIMARY KEY (tenant_id,workspace_id,notebook_id,actor_id)", SQL)
        self.assertIn("CHECK (jsonb_typeof(enabled_json)='object')", SQL)

    def test_notebook_cascades(self):
        self.assertRegex(SQL, r"FOREIGN KEY \(tenant_id,workspace_id,notebook_id\) REFERENCES public\.notebooks\(tenant_id,workspace_id,notebook_id\) ON DELETE CASCADE")

    def test_table_is_protected_by_actor_rls_like_model_selection(self):
        for text in ("CREATE TABLE public.notebook_question_tools (", "ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY",
                     "OWNER TO daon_notebook_delete", "REVOKE ALL ON TABLE public.notebook_question_tools FROM PUBLIC"):
            self.assertIn(text, SQL)
        policy = re.search(r"CREATE POLICY notebook_question_tools_scope ON public\.notebook_question_tools(.*?);", SQL, re.S)
        self.assertIsNotNone(policy)
        for clause in ("USING", "WITH CHECK"):
            self.assertIn(clause, policy.group(1))
        # USING과 WITH CHECK 모두 tenant·workspace·actor 세 조건
        self.assertEqual(policy.group(1).count("actor_id=nullif(current_setting('app.actor_id',true),'')"), 2)
        self.assertEqual(policy.group(1).count("tenant_id=nullif(current_setting('app.tenant_id',true),'')"), 2)
        self.assertEqual(policy.group(1).count("workspace_id=nullif(current_setting('app.workspace_id',true),'')"), 2)

    def test_app_role_gets_only_select_insert_update(self):
        self.assertIn("GRANT SELECT,INSERT,UPDATE ON public.notebook_question_tools TO daon_app", SQL)
        self.assertNotIn("DELETE ON public.notebook_question_tools TO daon_app", SQL)

    def test_no_functions_or_triggers(self):
        self.assertNotRegex(SQL, r"CREATE (OR REPLACE )?(FUNCTION|TRIGGER)")

    def test_downgrade_refuses_when_rows_exist(self):
        self.assertIn("NOTEBOOK_QUESTION_TOOLS_FORWARD_RECOVERY_REQUIRED", PY)
        self.assertIn("NOTEBOOK_QUESTION_TOOLS_DOWN_PRECONDITION", PY)
        self.assertIsNotNone(re.search(r"<>'0085'", PY))
        self.assertIn("DROP TABLE public.notebook_question_tools", PY)


if __name__ == "__main__":
    unittest.main()
