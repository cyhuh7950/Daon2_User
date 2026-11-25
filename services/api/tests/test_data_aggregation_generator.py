"""WO-N9 작업 6: 원본 읽기·데이터 집계 생성기·표 정보 API(가짜 LLM, 가짜 저장소)."""

from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from daon2_user_api.studio_generators import DataAggregationGenerator, build_registry
from daon2_user_api.studio_original_reader import StudioOriginalReader
from daon2_user_api.studio_text_generation import StudioTextGenerator
from daon2_user_api.studio_v2_generation import GenerationContext
from daon2_user_api.studio_workspace import StudioContext, StudioError
from test_studio_v2_generation import CTX, FakeCatalog, FakeReader, FakeResolver, FakeTransport, ScriptedLLM, model, openai_reply

SECRET_CITY = "비밀마을"
SECRET_AMOUNT = "987654"
CSV = ("지역,금액,날짜\n"
       f"서울,1000,2026-01-05\n"
       f"부산,2500,2026-01-20\n"
       f"서울,300,2026-02-03\n"
       f"{SECRET_CITY},{SECRET_AMOUNT},2026-02-10\n").encode("utf-8")
SVID = "sv-table-1"
OBJECT_ID = "a" * 32
OBJECT_KEY = f"{CTX.tenant_id}/{CTX.workspace_id}/source/{OBJECT_ID}"
REQUEST = "지역별 금액 합계를 보여 줘"
SETTINGS = {"aggregation_request": REQUEST, "table_source_version_id": SVID}
GOOD_SPEC = {"filters": [], "group_by": [{"column": "지역", "month": False}],
             "measures": [{"id": "m1", "func": "sum", "column": "금액"}], "growth": [], "sort": None, "limit": None,
             "unsupported": []}
BAD_SPEC = {**GOOD_SPEC, "measures": [{"id": "m1", "func": "sum", "column": "없는열"}]}


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class FakeConnection:
    def __init__(self, row, bound_notebook):
        self.row = row
        self.bound_notebook = bound_notebook
        self.queries = []

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        row = self.row if (CTX.tenant_id in params and SVID in params and self.bound_notebook in params) else None
        return SimpleNamespace(fetchone=lambda: row, fetchall=lambda: [row] if row else [])


class FakeStore:
    def __init__(self, row, bound_notebook="notebook-1"):
        self.connection = FakeConnection(row, bound_notebook)
        self.scopes = []

    @contextmanager
    def _transaction(self, scope):
        self.scopes.append(scope)
        yield self.connection


class FakeScope:
    """노트북 범위 검사 자리(실제는 PostgresStudioWorkspaceRepository._require_generation_scope)."""

    def __init__(self, bound_notebook="notebook-1"):
        self.bound_notebook = bound_notebook
        self.calls = []

    def _require_generation_scope(self, connection, context, versions, *, action=None):
        self.calls.append((context.notebook_id, tuple(versions), action))
        if context.notebook_id != self.bound_notebook:
            raise StudioError("NOTEBOOK_SCOPE_MISMATCH", 409)


class FakeStorage:
    def __init__(self, content):
        self.content = content
        self.gets = []

    def get(self, key):
        self.gets.append(key)
        return self.content


class FakeAudit:
    def __init__(self):
        self.drafts = []

    def append(self, draft):
        self.drafts.append(draft)
        return draft


def make_reader(content=CSV, *, digest=None, size=None, file_name="sales.csv", content_type="text/csv",
                bound_notebook="notebook-1", scope_notebook="notebook-1"):
    row = (file_name, OBJECT_KEY, digest or sha(content), len(content) if size is None else size, content_type)
    store = FakeStore(row, bound_notebook)
    storage = FakeStorage(content)
    scope = FakeScope(scope_notebook)
    return StudioOriginalReader(store, storage, scope=scope), store, storage, scope


def agg_ctx(settings=None, context=CTX):
    progress = []
    ctx = GenerationContext(context, "sv2-agg", "data_aggregation", None, SETTINGS if settings is None else settings,
                            (SVID,), "", "ko", "create", lambda pct, note: progress.append((pct, note)), lambda: None)
    return ctx, progress


def run(*responses, settings=None, reader=None, audit=None):
    llm = ScriptedLLM(*responses)
    reader = reader or make_reader()[0]
    ctx, progress = agg_ctx(settings)
    result = DataAggregationGenerator(reader, llm, audit_store=audit).generate(ctx)
    return result, llm, progress


class DataAggregationGeneratorTests(unittest.TestCase):
    def test_end_to_end_body_shape(self):
        result, llm, _ = run(GOOD_SPEC)
        content = result.content
        self.assertEqual(content["schema"], "studio.data_aggregation.v1")
        body = content["body"]
        self.assertEqual(set(body), {"request", "source", "spec", "spec_raw", "conditions_text", "columns", "rows", "evidence",
                                     "chart", "summary", "warnings", "stats"})
        self.assertEqual(body["request"], REQUEST)
        self.assertEqual(body["source"], {"source_version_id": SVID, "sha256": sha(CSV), "file_name": "sales.csv",
                                          "sheet": None, "header_row": 1})
        self.assertEqual(body["spec_raw"], GOOD_SPEC)
        self.assertEqual(body["spec"]["measures"], [{"id": "m1", "func": "sum", "column": "금액"}])
        self.assertTrue(body["conditions_text"])
        self.assertEqual(len(body["rows"]), 3)
        self.assertTrue(body["evidence"])
        self.assertEqual(body["chart"]["kind"], "bar")
        self.assertEqual(set(body["stats"]), {"rows_read", "elapsed_ms"})
        self.assertEqual(body["stats"]["rows_read"], 4)
        self.assertIsInstance(body["stats"]["elapsed_ms"], int)
        self.assertEqual(result.sources, [{"source_version_id": SVID}])
        self.assertEqual(len(llm.prompts), 1)
        self.assertEqual(llm.prompts[0].json_schema["required"],
                         ["filters", "group_by", "measures", "growth", "sort", "limit", "unsupported"])
        self.assertEqual(result.generated_with["model"], "m")

    def test_prompt_has_no_cell_values(self):
        _, llm, _ = run(GOOD_SPEC)
        text = llm.prompts[0].system + llm.prompts[0].user
        for value in (SECRET_CITY, SECRET_AMOUNT, "서울", "부산", "2500", "2026-01-05"):
            self.assertNotIn(value, text)
        self.assertIn(REQUEST, text)
        self.assertIn("지역", text)
        self.assertIn("금액", text)
        self.assertIn('"row_count": 4', text)

    def test_spec_invalid_retries_once_then_fails(self):
        result, llm, _ = run(BAD_SPEC, GOOD_SPEC)
        self.assertEqual(len(llm.prompts), 2)
        self.assertIn("없는 열: 없는열", llm.prompts[1].user)
        self.assertEqual(result.content["body"]["spec_raw"], GOOD_SPEC)
        with self.assertRaises(StudioError) as caught:
            run(BAD_SPEC, BAD_SPEC)
        self.assertEqual((caught.exception.code, caught.exception.status), ("STUDIO_VALIDATION_FAILED", 502))

    def test_filter_value_missing_message(self):
        spec = {**GOOD_SPEC, "filters": [{"column": "지역", "op": "eq", "value": "대전"}]}
        with self.assertRaises(StudioError) as caught:
            run(spec)
        self.assertEqual((caught.exception.code, caught.exception.status), ("AGGREGATION_FILTER_VALUE_NOT_FOUND", 422))
        self.assertEqual(caught.exception.detail, "대전(지역)")

    def test_partial_unsupported_completes_with_warning(self):
        spec = {**GOOD_SPEC, "unsupported": ["중앙값 계산"]}
        result, _, _ = run(spec)
        self.assertIn("하지 않은 요청: 중앙값 계산", result.content["body"]["warnings"])
        self.assertTrue(result.warnings)

    def test_all_unsupported_fails(self):
        spec = {**GOOD_SPEC, "group_by": [], "measures": [], "unsupported": ["회귀 분석"]}
        with self.assertRaises(StudioError) as caught:
            run(spec)
        self.assertEqual((caught.exception.code, caught.exception.status), ("AGGREGATION_UNSUPPORTED", 422))

    def test_checksum_mismatch_rejected(self):
        reader, _, storage, _ = make_reader(digest="0" * 64)
        with self.assertRaises(StudioError) as caught:
            reader.read(CTX, SVID)
        self.assertEqual((caught.exception.code, caught.exception.status), ("STUDIO_SOURCE_UNAVAILABLE", 409))
        reader, _, _, _ = make_reader(size=len(CSV) + 1)
        with self.assertRaisesRegex(StudioError, "STUDIO_SOURCE_UNAVAILABLE"):
            reader.read(CTX, SVID)
        # 생성기도 같은 오류로 끝나고 모델을 부르지 않는다.
        llm = ScriptedLLM(GOOD_SPEC)
        with self.assertRaisesRegex(StudioError, "STUDIO_SOURCE_UNAVAILABLE"):
            DataAggregationGenerator(make_reader(digest="0" * 64)[0], llm).generate(agg_ctx()[0])
        self.assertEqual(llm.prompts, [])
        # 원본 형식은 XLSX·CSV만
        reader, _, storage, _ = make_reader(file_name="a.pdf", content_type="application/pdf")
        with self.assertRaises(StudioError) as caught:
            reader.read(CTX, SVID)
        self.assertEqual((caught.exception.code, caught.exception.status), ("STUDIO_INPUT_INVALID", 400))
        self.assertEqual(storage.gets, [])

    def test_other_notebook_source_rejected(self):
        other = StudioContext(CTX.tenant_id, CTX.workspace_id, CTX.actor_id, CTX.trace_id, CTX.policy_version, "notebook-2")
        # 범위 검사(노트북 연결·권한·삭제)가 먼저 거부한다.
        reader, store, storage, scope = make_reader()
        with self.assertRaises(StudioError) as caught:
            reader.read(other, SVID)
        self.assertEqual(caught.exception.code, "NOTEBOOK_SCOPE_MISMATCH")
        self.assertEqual(scope.calls[0][:2], ("notebook-2", (SVID,)))
        self.assertEqual(storage.gets, [])
        # 원본 조회도 작업의 노트북으로 묶여 있다(범위 검사를 지나도 다른 노트북 판은 읽지 않는다).
        reader, store, storage, _ = make_reader(scope_notebook="notebook-2", bound_notebook="notebook-1")
        with self.assertRaises(StudioError) as caught:
            reader.read(other, SVID)
        self.assertEqual(caught.exception.code, "STUDIO_SOURCE_UNAVAILABLE")
        sql, params = store.connection.queries[-1]
        self.assertIn("notebook_bindings", sql)
        self.assertIn("deletion_requests", sql)
        self.assertIn("notebook-2", params)
        self.assertEqual(storage.gets, [])
        # 노트북 없는 문맥은 거부
        no_notebook = StudioContext(CTX.tenant_id, CTX.workspace_id, CTX.actor_id, CTX.trace_id, CTX.policy_version, None)
        with self.assertRaisesRegex(StudioError, "NOTEBOOK_SCOPE_REQUIRED"):
            make_reader()[0].read(no_notebook, SVID)

    def test_progress_notes_order(self):
        _, _, progress = run(GOOD_SPEC)
        notes = [note for _, note in progress]
        self.assertEqual(notes, ["표 읽는 중", "집계 조건 만드는 중", "계산 중"])
        pcts = [pct for pct, _ in progress]
        self.assertEqual(pcts, sorted(pcts))

    def test_egress_decisions_equal_model_calls(self):
        from daon2_user_api.studio_egress import EgressDecision
        decisions = []

        class Allow:
            def authorize(self, context, model_, size):
                decisions.append(size)
                return EgressDecision(True, "policy_allowed")

        for responses in ([GOOD_SPEC], [BAD_SPEC, GOOD_SPEC]):
            decisions.clear()
            resolver = FakeResolver({"ms": model("CUSTOM", "https://media.example/v1", kind="external_api")})
            transport = FakeTransport([openai_reply(r) for r in responses])
            llm = StudioTextGenerator(resolver, FakeCatalog([("ms", "m", "MS")]), transport=transport, egress_gate=Allow())
            DataAggregationGenerator(make_reader()[0], llm).generate(agg_ctx()[0])
            self.assertEqual(len(decisions), len(transport.calls))
            self.assertEqual(len(transport.calls), len(responses))
            for _, _, payload in transport.calls:
                sent = json.dumps(payload, ensure_ascii=False)
                self.assertNotIn(SECRET_CITY, sent)
                self.assertNotIn(SECRET_AMOUNT, sent)

    def test_audit_records_run(self):
        audit = FakeAudit()
        run(GOOD_SPEC, audit=audit)
        self.assertEqual(len(audit.drafts), 1)
        draft = audit.drafts[0]
        self.assertEqual(draft.action, "studio_v2.aggregation.run")
        self.assertEqual(set(draft.metadata), {"rows_read", "elapsed_ms", "source_sha256"})
        self.assertEqual(draft.metadata["rows_read"], 4)
        self.assertEqual(draft.metadata["source_sha256"], sha(CSV))
        self.assertEqual((draft.tenant_id, draft.workspace_id, draft.actor_id, draft.target_id),
                         (CTX.tenant_id, CTX.workspace_id, CTX.actor_id, "sv2-agg"))
        # 실제 감사 저장소의 검사(금지 키 등)도 통과한다.
        from daon2_user_api.audit import AuditEventStore
        store = AuditEventStore()
        run(GOOD_SPEC, audit=store)
        events = store.list(tenant_id=CTX.tenant_id, action="studio_v2.aggregation.run").items
        self.assertEqual(len(events), 1)
        self.assertEqual(dict(events[0].metadata)["source_sha256"], sha(CSV))

    def test_result_too_large_message(self):
        with patch("daon2_user_api.studio_generators.content_size_ok", return_value=False):
            with self.assertRaises(StudioError) as caught:
                run(GOOD_SPEC)
        self.assertEqual((caught.exception.code, caught.exception.status), ("AGGREGATION_TOO_LARGE", 422))

    def test_table_errors_and_too_many_groups_map_to_codes(self):
        with self.assertRaises(StudioError) as caught:
            run(GOOD_SPEC, settings={**SETTINGS, "header_row": 9})
        self.assertEqual((caught.exception.code, caught.exception.status), ("TABLE_HEADER_INVALID", 422))
        with patch("daon2_user_api.studio_generators.aggregation_run", side_effect=ValueError("AGGREGATION_TOO_MANY_GROUPS")):
            with self.assertRaisesRegex(StudioError, "AGGREGATION_TOO_MANY_GROUPS"):
                run(GOOD_SPEC)
        from daon2_user_api.aggregation_engine import AggregationTimeout
        with patch("daon2_user_api.studio_generators.aggregation_run", side_effect=AggregationTimeout("AGGREGATION_TIMEOUT")):
            with self.assertRaisesRegex(StudioError, "TABLE_TIMEOUT"):
                run(GOOD_SPEC)

    def test_one_aggregation_at_a_time(self):
        active = []
        peak = []

        class SlowReader:
            def read(self, context, source_version_id, **kw):
                active.append(1)
                peak.append(len(active))
                time.sleep(0.05)
                active.pop()
                return CSV, "sales.csv", "csv", sha(CSV)

        errors = []

        def work():
            try:
                DataAggregationGenerator(SlowReader(), ScriptedLLM(GOOD_SPEC)).generate(agg_ctx()[0])
            except Exception as error:  # pragma: no cover - 실패 보고용
                errors.append(error)

        threads = [threading.Thread(target=work) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(max(peak), 1)

    def test_registry_registers_only_with_original_reader(self):
        llm = ScriptedLLM()
        with self.assertRaisesRegex(StudioError, "STUDIO_TYPE_UNAVAILABLE"):
            build_registry(FakeReader(), llm).get("data_aggregation")
        registry = build_registry(FakeReader(), llm, original_reader=make_reader()[0])
        self.assertIsInstance(registry.get("data_aggregation"), DataAggregationGenerator)


NEW_PUBLIC_CODES = (("STUDIO_SOURCE_UNAVAILABLE", 409), ("TABLE_TOO_LARGE", 422), ("TABLE_TIMEOUT", 422),
                    ("TABLE_SHEET_NOT_FOUND", 422), ("TABLE_HEADER_INVALID", 422), ("TABLE_FORMAT_UNSUPPORTED", 422),
                    ("TABLE_ENCODING_UNSUPPORTED", 422), ("AGGREGATION_UNSUPPORTED", 422), ("AGGREGATION_TOO_LARGE", 422),
                    ("AGGREGATION_TOO_MANY_GROUPS", 422), ("AGGREGATION_FILTER_VALUE_NOT_FOUND", 422),
                    ("STUDIO_SERVICE_UNAVAILABLE", 503))


class ReviewFixTests(unittest.TestCase):
    def test_new_codes_are_public(self):
        from daon2_user_api.studio_v2_routes import STUDIO_V2_PUBLIC_CODES
        for code, _ in NEW_PUBLIC_CODES[:-1]:  # STUDIO_SERVICE_UNAVAILABLE은 runtime 기본 공개 코드
            self.assertIn(code, STUDIO_V2_PUBLIC_CODES)

    def test_table_profile_busy_returns_503(self):
        from daon2_user_api import studio_v2_service
        service = studio_v2_service.StudioV2Service(None, object_storage=object())
        self.assertTrue(studio_v2_service._TABLE_PROFILE_SLOTS.acquire(timeout=1))
        try:
            with patch.object(studio_v2_service, "TABLE_PROFILE_WAIT_SECONDS", 0.01):
                with self.assertRaises(StudioError) as caught:
                    service.table_profile(CTX, SVID, None, 1)
        finally:
            studio_v2_service._TABLE_PROFILE_SLOTS.release()
        self.assertEqual((caught.exception.code, caught.exception.status), ("STUDIO_SERVICE_UNAVAILABLE", 503))

    def test_table_profile_slot_released_after_read(self):
        from daon2_user_api import studio_v2_service
        service = studio_v2_service.StudioV2Service(None, object_storage=object())
        reader = make_reader()[0]
        with patch("daon2_user_api.studio_original_reader.StudioOriginalReader", return_value=reader):
            for _ in range(2):  # 두 번째 호출이 막히지 않으면 자리가 돌아온 것
                with patch.object(studio_v2_service, "TABLE_PROFILE_WAIT_SECONDS", 0.01):
                    data = service.table_profile(CTX, SVID, None, 1)
        self.assertEqual(data["row_count"], 4)

    def test_generator_keeps_no_shared_generation_state(self):
        generator = DataAggregationGenerator(make_reader()[0], ScriptedLLM(GOOD_SPEC))
        result = generator.generate(agg_ctx()[0])
        self.assertNotIn("_last", vars(generator))
        self.assertEqual(result.generated_with["model"], "m")

    def test_list_sheets_uses_profile_deadline(self):
        from daon2_user_api.table_reader import TableReadError, list_sheets
        from test_table_reader import sheet_xml, workbook
        content = workbook([("Sheet1", sheet_xml([["지역", "금액"], ["서울", 1]]))])
        self.assertEqual(list_sheets(content), ["Sheet1"])
        with self.assertRaises(TableReadError) as caught:
            list_sheets(content, deadline=time.monotonic() - 1)
        self.assertEqual(caught.exception.code, "TABLE_TIMEOUT")
        from daon2_user_api import studio_v2_service
        seen = []
        real = studio_v2_service.list_sheets if hasattr(studio_v2_service, "list_sheets") else None
        with patch("daon2_user_api.table_reader.list_sheets", side_effect=lambda c, **kw: seen.append(kw) or ["Sheet1"]):
            studio_v2_service.table_profile_from_original(content, "a.xlsx", "xlsx", None, 1)
        self.assertIsNone(real)
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0].get("deadline"), float)


class WorkerWiringTests(unittest.TestCase):
    def test_object_storage_absent_or_present(self):
        from daon2_user_api import studio_v2_worker
        keys = ("DAON_OBJECT_STORAGE_ENDPOINT", "DAON_OBJECT_STORAGE_BUCKET", "DAON_OBJECT_ACCESS_KEY_FILE", "DAON_OBJECT_SECRET_KEY_FILE")
        with patch.dict("os.environ", {k: "" for k in keys}):
            self.assertIsNone(studio_v2_worker._object_storage_from_env())
        with tempfile.TemporaryDirectory() as folder:
            access, secret = Path(folder, "a"), Path(folder, "s")
            access.write_text("access-value\n", encoding="utf-8")
            secret.write_text("secret-value\n", encoding="utf-8")
            env = {"DAON_OBJECT_STORAGE_ENDPOINT": "object-storage:9000", "DAON_OBJECT_STORAGE_BUCKET": "daon-bucket",
                   "DAON_OBJECT_ACCESS_KEY_FILE": str(access), "DAON_OBJECT_SECRET_KEY_FILE": str(secret),
                   "DAON_OBJECT_STORAGE_SECURE": "false"}
            with patch.dict("os.environ", env):
                from daon2_user_api.object_queue import MinioObjectStorageAdapter
                self.assertIsInstance(studio_v2_worker._object_storage_from_env(), MinioObjectStorageAdapter)
            with patch.dict("os.environ", {**env, "DAON_OBJECT_ACCESS_KEY_FILE": str(Path(folder, "missing"))}):
                self.assertIsNone(studio_v2_worker._object_storage_from_env())

    def test_table_profile_helper_maps_table_errors(self):
        from daon2_user_api.studio_v2_service import table_profile_from_original
        with self.assertRaises(StudioError) as caught:
            table_profile_from_original(CSV, "sales.csv", "csv", None, 9)
        self.assertEqual((caught.exception.code, caught.exception.status), ("TABLE_HEADER_INVALID", 422))


class TableProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import httpx
        from daon2_user_api.audit import AuditEventStore
        from daon2_user_api.authorization import AuthorizationService, Role, SqliteAuthorizationRepository
        from daon2_user_api.identity import IdentityPrincipal
        from daon2_user_api.runtime import WEB_SESSION_COOKIE, RuntimeDependencies, RuntimeSettings, create_app
        from daon2_user_api.studio_v2_service import table_profile_from_original
        from test_identity_support import POLICY_VERSION, create_service

        self.directory = tempfile.TemporaryDirectory()
        db_path = Path(self.directory.name) / "runtime.sqlite3"
        audit = AuditEventStore()
        identity, identity_repository, _, clock = create_service(db_path, audit_store=audit)
        repository = SqliteAuthorizationRepository(db_path)
        self.principal = IdentityPrincipal("user-001", "session-001", "device-001", "tenant-001")
        repository.bootstrap_workspace(
            tenant_id="tenant-001", workspace_id="workspace-001", owner_user_id="user-001", owner_role=Role.PERSONAL_OWNER,
            workspace_kind="personal", data_area="cloud_sync", cost_limit_cents=1000, now=clock())
        authorization = AuthorizationService(repository=repository, audit_store=audit, clock=clock, identity_service=identity)
        self.identity = identity
        calls = self.calls = []

        class FakeService:
            def table_profile(self, ctx, source_version_id, sheet, header_row):
                calls.append((ctx.notebook_id, source_version_id, sheet, header_row))
                return table_profile_from_original(CSV, "sales.csv", "csv", sheet, header_row)

        settings = RuntimeSettings.for_test(database_path=db_path, policy_version=POLICY_VERSION)
        self.dependencies = RuntimeDependencies(
            settings=settings, identity_service=identity, authorization_service=authorization, audit_store=audit,
            identity_repository=identity_repository, authorization_repository=repository, studio_v2_service=FakeService())
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.dependencies)), base_url="http://127.0.0.1")
        self.cookies = {WEB_SESSION_COOKIE: "opaque"}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.dependencies.close()
        self.directory.cleanup()

    async def test_table_profile_route_no_values(self):
        from test_identity_support import identity_session_view
        base = "/api/v1/workspaces/workspace-001/notebooks/notebook-001/studio/table-profile"
        with patch.object(self.identity, "describe_access", return_value=identity_session_view(self.principal)):
            response = await self.client.get(base, params={"source_version_id": SVID}, cookies=self.cookies)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()["data"]
            self.assertEqual(data, {"sheets": [], "columns": [{"name": "지역", "kind": "text"}, {"name": "금액", "kind": "number"},
                                                              {"name": "날짜", "kind": "date"}], "row_count": 4})
            for value in (SECRET_CITY, SECRET_AMOUNT, "서울", "부산"):
                self.assertNotIn(value, response.text)
            self.assertEqual(self.calls[-1], ("notebook-001", SVID, None, 1))
            self.assertEqual(response.headers.get("cache-control"), "no-store")
            bad = await self.client.get(base, params={"source_version_id": SVID, "header_row": "0"}, cookies=self.cookies)
            self.assertEqual(bad.status_code, 400)
            bad = await self.client.get(base, params={"source_version_id": "../x"}, cookies=self.cookies)
            self.assertEqual(bad.status_code, 400)
            bad = await self.client.get(base, params={"source_version_id": SVID, "extra": "1"}, cookies=self.cookies)
            self.assertEqual(bad.status_code, 400)
            ok = await self.client.get(base, params={"source_version_id": SVID, "header_row": "2", "sheet": "Sheet1"}, cookies=self.cookies)
            self.assertEqual(ok.status_code, 200, ok.text)
            self.assertEqual(self.calls[-1], ("notebook-001", SVID, "Sheet1", 2))
        unauthenticated = await self.client.get(base, params={"source_version_id": SVID})
        self.assertEqual(unauthenticated.status_code, 401)

    async def test_table_profile_route_preserves_public_codes(self):
        from test_identity_support import identity_session_view
        base = "/api/v1/workspaces/workspace-001/notebooks/notebook-001/studio/table-profile"
        service = self.dependencies.studio_v2_service
        for code, status in NEW_PUBLIC_CODES:
            def fail(*_a, code=code, status=status):
                raise StudioError(code, status)
            with patch.object(type(service), "table_profile", fail), \
                    patch.object(self.identity, "describe_access", return_value=identity_session_view(self.principal)):
                response = await self.client.get(base, params={"source_version_id": SVID}, cookies=self.cookies)
            self.assertEqual((response.status_code, response.json()["error"]["code"]), (status, code))


if __name__ == "__main__":
    unittest.main()
