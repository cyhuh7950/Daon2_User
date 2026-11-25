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


def test_migration_0088_sql_constraint_lists_all_types_and_downgrade_guards():
    sql = Path(MIGRATIONS, "0088_web_page.sql").read_text(encoding="utf-8")
    py = Path(MIGRATIONS, "0088_web_page.py").read_text(encoding="utf-8")
    add = sql[sql.index("ADD CONSTRAINT studio_v2_outputs_type_id_check"):]
    for type_id in ("report", "data_table", "mind_map", "flashcards", "quiz", "slides", "infographic",
                    "audio_overview", "video_overview", "memo", "authored_document", "web_page"):
        assert f"'{type_id}'" in add
    down = py[py.index("def downgrade"):]
    assert "<>'0088'" in down and "rolsuper" in down
    assert "type_id='web_page'" in down and "preview_json<>'{}'::jsonb" in down
    assert "WEB_PAGE_FORWARD_RECOVERY_REQUIRED" in down
    assert "DROP COLUMN preview_json" in down
    assert "'web_page'" not in down[down.index("ADD CONSTRAINT"):]


def test_type_labels_cover_web_page_and_default_title_pattern():
    # 최종 검토 I4: 기본 제목은 "웹 페이지 YYYY-MM-DD HH:MM"이고 자동 제목의 기본 제목 판정도 같은 이름을 쓴다.
    import re

    from daon2_user_api.studio_v2_postgres import TYPE_LABELS

    assert TYPE_LABELS["web_page"] == "웹 페이지"
    assert set(STUDIO_V2_TYPES) <= set(TYPE_LABELS)
    default = re.compile(re.escape(TYPE_LABELS["web_page"]) + r" \d{4}-\d{2}-\d{2} \d{2}:\d{2}")
    assert default.fullmatch("웹 페이지 2026-11-25 10:00")
