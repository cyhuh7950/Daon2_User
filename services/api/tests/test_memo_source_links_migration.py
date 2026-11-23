"""메모를 소스로 쓰는 연결 저장소 마이그레이션(WO-N1 N1-3, NB1-F2)."""
import re
import unittest
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0084_memo_source_links.sql").read_text(encoding="utf-8")
PY = (VERSIONS / "0084_memo_source_links.py").read_text(encoding="utf-8")


class MemoSourceLinksMigrationTests(unittest.TestCase):
    def test_revision_chain(self):
        self.assertIn("revision = '0084'", PY)
        self.assertIn("down_revision = '0083'", PY)

    def test_precondition_requires_superuser_previous_revision_and_app_role(self):
        self.assertIn("MEMO_SOURCE_LINKS_PRECONDITION", SQL)
        self.assertIn("rolsuper", SQL)
        self.assertIn("<>'0083'", SQL)
        self.assertIn("rolname='daon_app'", SQL)

    def test_columns_and_keys(self):
        for column in ("tenant_id text NOT NULL", "workspace_id text NOT NULL", "notebook_id text NOT NULL",
                       "memo_output_id text NOT NULL", "source_id text NOT NULL", "reflected_revision_no integer NOT NULL",
                       "created_by text NOT NULL", "created_at timestamptz NOT NULL", "updated_at timestamptz NOT NULL"):
            self.assertIn(column, SQL)
        self.assertIn("PRIMARY KEY (tenant_id,workspace_id,memo_output_id)", SQL)
        self.assertIn("UNIQUE (tenant_id,workspace_id,source_id)", SQL)

    def test_memo_has_no_foreign_key_but_notebook_cascades(self):
        # 메모를 지워도 연결을 남긴다(D-10). 노트북을 지우면 함께 지운다.
        self.assertNotIn("REFERENCES public.studio_v2_outputs", SQL)
        self.assertRegex(SQL, r"FOREIGN KEY \(tenant_id,workspace_id,notebook_id\) REFERENCES public\.notebooks\(tenant_id,workspace_id,notebook_id\) ON DELETE CASCADE")

    def test_table_is_protected_by_workspace_rls(self):
        for text in ("CREATE TABLE public.memo_source_links (", "ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY",
                     "OWNER TO daon_notebook_delete", "app.tenant_id", "app.workspace_id", "REVOKE ALL ON TABLE public.memo_source_links FROM PUBLIC"):
            self.assertIn(text, SQL)
        self.assertNotIn("app.actor_id", SQL)

    def test_notebook_index_and_grants(self):
        self.assertRegex(SQL, r"CREATE INDEX \w+ ON public\.memo_source_links\(tenant_id,workspace_id,notebook_id\)")
        self.assertIn("GRANT SELECT,INSERT,UPDATE ON public.memo_source_links TO daon_app", SQL)
        self.assertNotIn("DELETE ON public.memo_source_links TO daon_app", SQL)

    def test_reflected_revision_is_positive(self):
        self.assertIn("CHECK (reflected_revision_no>=1)", SQL)

    def test_downgrade_refuses_when_rows_exist(self):
        self.assertIn("MEMO_SOURCE_LINKS_FORWARD_RECOVERY_REQUIRED", PY)
        self.assertIn("MEMO_SOURCE_LINKS_DOWN_PRECONDITION", PY)
        self.assertIsNotNone(re.search(r"<>'0084'", PY))
        self.assertIn("DROP TABLE public.memo_source_links", PY)


if __name__ == "__main__":
    unittest.main()
