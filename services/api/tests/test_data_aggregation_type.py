from pathlib import Path

import pytest

from daon2_user_api.studio_v2_types import STUDIO_V2_TYPES, available_types, validate_settings

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
EXISTING = ("report", "data_table", "mind_map", "flashcards", "quiz", "slides", "infographic",
            "audio_overview", "video_overview", "memo", "authored_document", "web_page")


def test_type_registered_with_formats_and_schema():
    t = STUDIO_V2_TYPES["data_aggregation"]
    assert t.export_formats == ("xlsx", "csv")
    props = t.settings_schema["properties"]
    assert props["aggregation_request"] == {"type": "string", "maxLength": 2000}
    assert props["table_source_version_id"] == {"type": "string", "maxLength": 120}
    assert props["sheet"] == {"type": "string", "maxLength": 120}
    assert props["header_row"] == {"type": "integer", "minimum": 1, "maximum": 50}
    from daon2_user_api.studio_v2_postgres import TYPE_LABELS
    assert TYPE_LABELS["data_aggregation"] == "데이터 집계"


def test_validate_requires_request_and_table_source():
    ok = {"aggregation_request": "지점별 합계", "table_source_version_id": "ver-1"}
    _, clean = validate_settings("data_aggregation", None, ok)
    assert clean["aggregation_request"] == "지점별 합계" and clean["table_source_version_id"] == "ver-1"
    _, clean = validate_settings("data_aggregation", None, {**ok, "sheet": "Sheet1", "header_row": 3})
    assert clean["header_row"] == 3 and clean["sheet"] == "Sheet1"
    for bad in ({}, {**ok, "aggregation_request": ""}, {**ok, "aggregation_request": "   "},
                {"aggregation_request": "합계"}, {"aggregation_request": "합계", "table_source_version_id": ""},
                {**ok, "header_row": 0}, {**ok, "header_row": 51}):
        with pytest.raises(ValueError, match="STUDIO_INPUT_INVALID"):
            validate_settings("data_aggregation", None, bad)


def test_migration_0089_adds_type_keeps_12_existing():
    sql = Path(MIGRATIONS, "0089_data_aggregation.sql").read_text(encoding="utf-8")
    py = Path(MIGRATIONS, "0089_data_aggregation.py").read_text(encoding="utf-8")
    assert "revision = '0089'" in py and "down_revision = '0088'" in py
    add = sql[sql.index("ADD CONSTRAINT studio_v2_outputs_type_id_check"):]
    for type_id in (*EXISTING, "data_aggregation"):
        assert f"'{type_id}'" in add
    down = py[py.index("def downgrade"):]
    assert "<>'0089'" in down and "rolsuper" in down
    assert "type_id='data_aggregation'" in down
    assert "DATA_AGGREGATION_FORWARD_RECOVERY_REQUIRED" in down
    assert "'data_aggregation'" not in down[down.index("ADD CONSTRAINT"):]
    for type_id in EXISTING:
        assert f"'{type_id}'" in down[down.index("ADD CONSTRAINT"):]


def test_readiness_accepts_0089():
    import re
    src = Path(__file__).resolve().parents[1] / "src" / "daon2_user_api"
    for name in ("cloud_storage.py", "runtime.py", "question_answering_postgres.py"):
        text = (src / name).read_text(encoding="utf-8")
        for m in re.finditer(r"\{[^{}]*['\"]0088['\"][^{}]*\}|\([^()]*['\"]0088['\"][^()]*\)", text):
            assert "0089" in m.group(0), (name, m.group(0)[-60:])


def test_available_types_lists_data_aggregation_last():
    ids = [t["type_id"] for t in available_types()]
    assert "data_aggregation" in ids
    assert ids.index("data_aggregation") == ids.index("web_page") + 1
    item = next(t for t in available_types() if t["type_id"] == "data_aggregation")
    assert item["available"] is True and item["export_formats"] == ["xlsx", "csv"]
