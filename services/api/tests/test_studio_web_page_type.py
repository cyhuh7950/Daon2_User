from pathlib import Path

from daon2_user_api.studio_v2_types import STUDIO_V2_TYPES

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def test_web_page_type_registered():
    t = STUDIO_V2_TYPES["web_page"]
    assert t.export_formats == ("html",)
    assert t.settings_schema["properties"]["page_request"]["maxLength"] == 2000


def test_migration_0088_allows_web_page_and_preview_column():
    sql = Path(MIGRATIONS, "0088_web_page.sql").read_text(encoding="utf-8")
    assert "'web_page'" in sql and "studio_v2_outputs_type_id_check" in sql
    assert "preview_json" in sql


def test_migration_0088_py_chain_and_downgrade_guards():
    py = Path(MIGRATIONS, "0088_web_page.py").read_text(encoding="utf-8")
    assert "revision = '0088'" in py and "down_revision = '0087'" in py
    assert "WEB_PAGE_FORWARD_RECOVERY_REQUIRED" in py
