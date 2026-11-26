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


# ------------------------------------------------------------------ 최종 검토 I3: 출력 소스 == 표 소스

class _Rows:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return []


class _Connection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        return _Rows(self.rows.pop(0) if self.rows else None)


class _Store:
    def __init__(self, rows=()):
        self.connection = _Connection(rows)

    from contextlib import contextmanager

    @contextmanager
    def _transaction(self, context):
        yield self.connection


def _repo(rows=(), ready=("ver-1", "ver-2")):
    from types import SimpleNamespace

    from daon2_user_api.studio_v2_postgres import PostgresStudioV2Repository

    class Repo(PostgresStudioV2Repository):
        scoped = []

        def require_scope(self, connection, context, versions, **kwargs):
            self.scoped.append(list(versions))

        def _has_selected_knowledge(self, connection, context, notebook_id):
            return False

        def ready_source_versions(self, connection, context):
            return list(ready)

    store = _Store(rows)
    repo = Repo(store)
    repo.scoped = []
    repo.tts_resolver = SimpleNamespace(for_tenant=lambda tenant: None)
    return repo, store


AGG = {"aggregation_request": "상품별 합계", "table_source_version_id": "ver-1"}


def _writes(store):
    return [sql for sql in store.connection.statements if sql.startswith(("INSERT", "UPDATE"))]


def test_create_requires_output_sources_equal_table_source():
    from test_studio_v2_generation import CTX

    from daon2_user_api.studio_workspace import StudioError
    for requested in (None, [], ["ver-2"], ["ver-1", "ver-2"]):
        repo, store = _repo()
        request = {"type_id": "data_aggregation", "settings": AGG}
        if requested is not None:
            request["source_version_ids"] = requested
        with pytest.raises(StudioError) as caught:
            repo.enqueue(CTX, request, "agg-create-key-0001")
        assert (caught.value.code, caught.value.status) in {("STUDIO_INPUT_INVALID", 400), ("STUDIO_NO_READY_SOURCE", 409)}, requested
        assert _writes(store) == [], requested
    repo, store = _repo()
    receipt = repo.enqueue(CTX, {"type_id": "data_aggregation", "settings": AGG, "source_version_ids": ["ver-1"]}, "agg-create-key-0002")
    assert receipt["status"] == "queued"
    assert repo.scoped == [["ver-1"]]  # 표 소스도 노트북 범위 검사를 거친다
    # 다른 유형은 바뀌지 않는다.
    repo, store = _repo()
    assert repo.enqueue(CTX, {"type_id": "report", "settings": {}, "source_version_ids": ["ver-1", "ver-2"]}, "agg-create-key-0003")["status"] == "queued"


def test_regenerate_rejects_table_source_different_from_output_sources():
    from datetime import datetime, timezone

    from test_studio_v2_generation import CTX

    from daon2_user_api.studio_workspace import StudioError
    now = datetime(2026, 11, 26, tzinfo=timezone.utc)

    def row(versions):
        return ("sv2-" + "a" * 32, "data_aggregation", None, "데이터 집계", "completed", None, dict(AGG), versions, 1, CTX.actor_id, now, now)
    repo, store = _repo([row(["ver-1"]), None])
    with pytest.raises(StudioError) as caught:
        repo.regenerate(CTX, "sv2-" + "a" * 32, {"table_source_version_id": "ver-2"}, "agg-regen-key-00001")
    assert (caught.value.code, caught.value.status) == ("STUDIO_INPUT_INVALID", 400)
    assert _writes(store) == []
    repo, store = _repo([row(["ver-1", "ver-2"]), None])
    with pytest.raises(StudioError):
        repo.regenerate(CTX, "sv2-" + "a" * 32, {"aggregation_request": "다시"}, "agg-regen-key-00002")
    repo, store = _repo([row(["ver-1"]), None])
    receipt = repo.regenerate(CTX, "sv2-" + "a" * 32, {"aggregation_request": "다시"}, "agg-regen-key-00003")
    assert receipt["status"] == "queued"
    assert repo.scoped == [["ver-1"]]
