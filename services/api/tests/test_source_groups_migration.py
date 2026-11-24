"""소스 묶음 저장소 마이그레이션(WO-N1 N1-5, NB3-F2, 결정 D-11 노트북 공유)."""
import re
import unittest
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SQL = (VERSIONS / "0087_source_groups.sql").read_text(encoding="utf-8")
PY = (VERSIONS / "0087_source_groups.py").read_text(encoding="utf-8")


class SourceGroupsMigrationTests(unittest.TestCase):
    def test_revision_chain(self):
        self.assertIn("revision = '0087'", PY)
        self.assertIn("down_revision = '0086'", PY)

    def test_precondition_requires_superuser_previous_revision_and_app_role(self):
        self.assertIn("SOURCE_GROUPS_PRECONDITION", SQL)
        self.assertIn("rolsuper", SQL)
        self.assertIn("<>'0086'", SQL)
        self.assertIn("rolname='daon_app'", SQL)

    def test_source_groups_columns_and_keys(self):
        for column in ("tenant_id text NOT NULL", "workspace_id text NOT NULL", "notebook_id text NOT NULL",
                       "group_id text NOT NULL", "name text NOT NULL", "position integer NOT NULL",
                       "created_by text NOT NULL", "created_at timestamptz NOT NULL", "updated_at timestamptz NOT NULL"):
            self.assertIn(column, SQL)
        self.assertIn("CHECK (group_id ~ '^sg-[0-9a-f]{32}$')", SQL)
        self.assertIn("CHECK (char_length(name) BETWEEN 1 AND 80)", SQL)
        self.assertIn("PRIMARY KEY (tenant_id,workspace_id,group_id)", SQL)
        self.assertIn("UNIQUE (tenant_id,workspace_id,notebook_id,group_id)", SQL)

    def test_members_columns_and_one_group_per_source(self):
        table = re.search(r"CREATE TABLE public\.source_group_members \((.*?)\n\);", SQL, re.S)
        self.assertIsNotNone(table)
        body = table.group(1)
        for column in ("tenant_id text NOT NULL", "workspace_id text NOT NULL", "notebook_id text NOT NULL",
                       "group_id text NOT NULL", "source_id text NOT NULL", "position integer NOT NULL"):
            self.assertIn(column, body)
        self.assertIn("PRIMARY KEY (tenant_id,workspace_id,notebook_id,source_id)", body)

    def test_cascades(self):
        self.assertRegex(SQL, r"FOREIGN KEY \(tenant_id,workspace_id,notebook_id\) REFERENCES public\.notebooks\(tenant_id,workspace_id,notebook_id\) ON DELETE CASCADE")
        self.assertRegex(SQL, r"FOREIGN KEY \(tenant_id,workspace_id,notebook_id,group_id\) REFERENCES public\.source_groups\(tenant_id,workspace_id,notebook_id,group_id\) ON DELETE CASCADE")
        # 소스(정본 표)에는 FK를 걸지 않는다: 소스 삭제·떼기는 조회에서 숨길 뿐 정본 표 작업에 끼어들지 않는다.
        self.assertNotRegex(SQL, r"REFERENCES public\.(sources|source_versions|notebook_bindings)\b")

    def test_indexes(self):
        self.assertIn("CREATE INDEX source_groups_notebook_idx ON public.source_groups(tenant_id,workspace_id,notebook_id,position)", SQL)
        self.assertIn("CREATE INDEX source_group_members_group_idx ON public.source_group_members(tenant_id,workspace_id,notebook_id,group_id,position)", SQL)

    def test_tables_are_notebook_shared_rls_like_studio_v2(self):
        for table in ("source_groups", "source_group_members"):
            for text in (f"CREATE TABLE public.{table} (", f"ALTER TABLE public.{table} OWNER TO daon_notebook_delete",
                         f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY", f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY",
                         f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC"):
                self.assertIn(text, SQL)
            policy = re.search(rf"CREATE POLICY {table}_scope ON public\.{table}(.*?);", SQL, re.S)
            self.assertIsNotNone(policy, table)
            body = policy.group(1)
            self.assertEqual(body.count("tenant_id=nullif(current_setting('app.tenant_id',true),'')"), 2)
            self.assertEqual(body.count("workspace_id=nullif(current_setting('app.workspace_id',true),'')"), 2)
            self.assertNotIn("actor_id", body)  # 결정 D-11: 노트북 공유 저장(사용자 기준이 아니다)

    def test_app_role_gets_select_insert_update_delete(self):
        self.assertIn("GRANT SELECT,INSERT,UPDATE,DELETE ON public.source_groups, public.source_group_members TO daon_app", SQL)

    def test_no_functions_or_triggers_and_no_canon_changes(self):
        self.assertNotRegex(SQL, r"CREATE (OR REPLACE )?(FUNCTION|TRIGGER)")
        for canon in ("sources", "source_versions", "notebook_bindings", "notebook_source_unbindings"):
            self.assertNotRegex(SQL, rf"(ALTER|GRANT[^;]*ON)\s+(TABLE\s+)?public\.{canon}\b")

    def test_downgrade_refuses_when_rows_exist(self):
        self.assertIn("SOURCE_GROUPS_FORWARD_RECOVERY_REQUIRED", PY)
        self.assertIn("SOURCE_GROUPS_DOWN_PRECONDITION", PY)
        self.assertIsNotNone(re.search(r"<>'0087'", PY))
        self.assertIn("EXISTS(SELECT 1 FROM public.source_groups)", PY)
        self.assertIn("EXISTS(SELECT 1 FROM public.source_group_members)", PY)
        self.assertLess(PY.index("DROP TABLE public.source_group_members"), PY.index("DROP TABLE public.source_groups"))


if __name__ == "__main__":
    unittest.main()
