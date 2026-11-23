"""노트북 개요·추천 질문 저장·조회·생성 계약(WO-N1 N1-4, NB2-F2, 결정 D-06, 정정 C-5)."""
from __future__ import annotations

import copy
import hashlib
import json
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from daon2_user_api import notebook_overview as nov
from daon2_user_api.cloud_storage import CloudDatabaseError
from daon2_user_api.notebook_overview import (
    NotebookOverviewContext, NotebookOverviewError, NotebookOverviewGenerator, NotebookOverviewService,
    NotebookOverviewWorker, OverviewFailure, source_fingerprint,
)
from daon2_user_api.studio_source_reader import SourceSection, SourceText
from daon2_user_api.studio_text_generation import StudioTextGenerator
from daon2_user_api.studio_v2_postgres import READY_SOURCE_VERSIONS_SQL
from daon2_user_api.studio_workspace import StudioContext, StudioError

CTX = NotebookOverviewContext("tenant-1", "workspace-1", "actor-1", "trace-1", "policy-1")
TEXT_A = "보험금은 청구서류 접수일부터 3일 이내에 지급한다. 지급 한도는 1,000,000원이다."
TEXT_B = "면책 기간은 계약일부터 90일이다. 사고 발생 시 즉시 통지해야 한다."
QUESTIONS = ["보험금은 언제 지급되나요?", "면책 기간은 얼마인가요?", "사고가 나면 무엇을 해야 하나요?"]


# -- 가짜 DB ------------------------------------------------------------------

class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeDb:
    """SQL 상수로 나눠 처리하는 메모리 DB. 시간은 self.now(초)로 흉내 낸다."""

    def __init__(self):
        self.notebooks = {"notebook-1", "notebook-2"}
        self.ready = {"notebook-1": ["sv-2", "sv-1"], "notebook-2": []}
        self.rows: dict[tuple, dict] = {}
        self.audit: list[tuple] = []
        self.executed: list[tuple[str, tuple, str]] = []
        self.now = 1000.0
        self.fail = False

    def close(self):
        return None

    def ts(self, offset=0.0):
        return datetime(2026, 11, 24, tzinfo=timezone.utc) + timedelta(seconds=self.now + offset)

    @contextmanager
    def _transaction(self, scope):
        if self.fail:
            raise CloudDatabaseError("DB_DOWN", retryable=True)
        snapshot = copy.deepcopy(self.rows), list(self.audit)
        try:
            yield FakeConnection(self, scope)
        except Exception:
            self.rows, self.audit = snapshot
            raise


ROW_KEYS = ("state", "summary", "questions", "citations", "source_fingerprint", "safe_error_code", "updated_at")


class FakeConnection:
    def __init__(self, db, scope):
        self.db, self.scope = db, scope

    def _visible(self, key):
        # RLS: 앱 범위는 tenant·workspace가 같아야 하고, 워커 capability는 교차 범위를 본다.
        if self.scope.capability == nov.WORKER_CAPABILITY:
            return True
        return key[0] == self.scope.tenant_id and key[1] == self.scope.workspace_id

    def execute(self, sql, params=()):
        db = self.db
        db.executed.append((sql, tuple(params), self.scope.capability))
        if sql == nov._NOTEBOOK_SQL:
            return _Result([(1,)] if params[2] in db.notebooks else [])
        if sql == READY_SOURCE_VERSIONS_SQL:
            return _Result([(v,) for v in sorted(db.ready.get(params[2], []))])
        if sql == nov._ROW_SQL:
            row = db.rows.get(tuple(params[:3]))
            if row is None or not self._visible(tuple(params[:3])):
                return _Result([])
            return _Result([tuple(copy.deepcopy(row[k]) for k in ROW_KEYS)])
        if sql == nov._INSERT_SQL:
            key = tuple(params[:3])
            if key in db.rows:
                return _Result([])
            db.rows[key] = {"state": "queued", "summary": None, "questions": [], "citations": [], "source_fingerprint": None,
                            "model_ref": None, "safe_error_code": None, "attempt": 0, "lease_until": None,
                            "requested_by": params[3], "updated_at": db.ts(), "created_at": db.ts()}
            return _Result([(1,)])
        if sql == nov._REQUEUE_SQL:
            requested_by, *key = params
            row = db.rows.get(tuple(key))
            if row is None or row["state"] not in {"ready", "failed", "blocked"}:
                return _Result([])
            row.update(state="queued", summary=None, questions=[], citations=[], source_fingerprint=None, model_ref=None,
                       safe_error_code=None, attempt=0, lease_until=None, requested_by=requested_by, updated_at=db.ts())
            return _Result([(1,)])
        if sql == nov._SWEEP_SQL:
            assert self.scope.capability == nov.WORKER_CAPABILITY
            (max_attempts,) = params
            for row in db.rows.values():
                if row["state"] == "working" and row["lease_until"] < db.now and row["attempt"] >= max_attempts:
                    row.update(state="failed", safe_error_code="OVERVIEW_GENERATION_FAILED", lease_until=None, updated_at=db.ts())
            return _Result([])
        if sql == nov._CLAIM_SQL:
            assert self.scope.capability == nov.WORKER_CAPABILITY
            max_attempts, lease = params
            candidates = sorted(
                (row["updated_at"], key) for key, row in db.rows.items()
                if row["attempt"] < max_attempts and (
                    (row["state"] == "queued" and (row["lease_until"] is None or row["lease_until"] <= db.now))
                    or (row["state"] == "working" and row["lease_until"] < db.now)))
            if not candidates:
                return _Result([])
            key = candidates[0][1]
            row = db.rows[key]
            row.update(state="working", attempt=row["attempt"] + 1, lease_until=db.now + lease, updated_at=db.ts())
            return _Result([(*key, row["attempt"], row["requested_by"])])
        if sql == nov._HEARTBEAT_SQL:
            lease, *key, attempt = params
            row = db.rows.get(tuple(key))
            if row is None or row["state"] != "working" or row["attempt"] != attempt:
                return _Result([])
            row["lease_until"] = db.now + lease
            return _Result([(1,)])
        if sql == nov._FINISH_SQL:
            state, summary, questions, citations, fingerprint, model_ref, code, *key, attempt = params
            row = db.rows.get(tuple(key))
            if row is None or row["state"] != "working" or row["attempt"] != attempt:
                return _Result([])
            row.update(state=state, summary=summary, questions=json.loads(questions), citations=json.loads(citations),
                       source_fingerprint=fingerprint, model_ref=model_ref, safe_error_code=code, lease_until=None, updated_at=db.ts())
            return _Result([(1,)])
        if sql == nov._RETRY_SQL:
            code, delay, *key, attempt = params
            row = db.rows.get(tuple(key))
            if row is None or row["state"] != "working" or row["attempt"] != attempt:
                return _Result([])
            row.update(state="queued", safe_error_code=code, lease_until=db.now + delay, updated_at=db.ts())
            return _Result([(1,)])
        if sql == nov._AUDIT_SQL:
            db.audit.append(tuple(params))
            return _Result([])
        raise AssertionError(f"unexpected SQL {sql}")


# -- 생성기 가짜 --------------------------------------------------------------

def source(name="약관.pdf", version="sv-1", texts=(TEXT_A, TEXT_B)):
    sections = tuple(SourceSection(version, None, "page", str(i), None, t) for i, t in enumerate(texts, 1))
    return SourceText("src-1", version, name, sections, False)


class FakeReader:
    def __init__(self, sources=None, error=None):
        self.sources = sources or (source(),)
        self.error = error
        self.calls = []

    def read(self, context, versions, **kw):
        self.calls.append((context, tuple(versions)))
        if self.error is not None:
            raise self.error
        return self.sources


class ScriptedLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []
        self.flags = []

    def generate(self, context, prompt, cancel_check=None, report_egress_block=False):
        self.prompts.append(prompt)
        self.flags.append(report_egress_block)
        if cancel_check is not None:
            cancel_check()
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(data=item, usage={}, model_id="m-1", provider_code="CUSTOM", connection_short_code="MS")


GOOD = {"sentences": [{"text": "보험금은 청구서류 접수일부터 3일 이내에 지급한다.", "refs": ["S1"]},
                      {"text": "면책 기간은 계약일부터 90일이다.", "refs": ["S2"]}],
        "questions": QUESTIONS}


def sha(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


class FingerprintTests(unittest.TestCase):
    def test_sorted_join_sha256(self):
        self.assertEqual(source_fingerprint(["sv-2", "sv-1"]), sha(["sv-1", "sv-2"]))
        self.assertEqual(source_fingerprint(["sv-1", "sv-2"]), source_fingerprint(["sv-2", "sv-1"]))
        self.assertNotEqual(source_fingerprint(["sv-1"]), source_fingerprint(["sv-1", "sv-2"]))
        self.assertRegex(source_fingerprint([]), r"^[0-9a-f]{64}$")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDb()
        self.service = NotebookOverviewService(self.db)

    def test_first_get_with_ready_sources_creates_one_queued_row(self):
        data = self.service.get(CTX, "notebook-1")
        self.assertEqual(data, {"state": "queued", "summary": None, "questions": [], "citations": [], "stale": False,
                                "generated_at": None, "error_code": None})
        self.assertEqual(list(self.db.rows), [("tenant-1", "workspace-1", "notebook-1")])
        self.assertEqual(self.db.rows[("tenant-1", "workspace-1", "notebook-1")]["requested_by"], "actor-1")
        again = self.service.get(CTX, "notebook-1")
        self.assertEqual(again["state"], "queued")
        self.assertEqual(sum(1 for sql, *_ in self.db.executed if sql == nov._INSERT_SQL), 1)

    def test_no_ready_source_returns_none_and_creates_no_row(self):
        data = self.service.get(CTX, "notebook-2")
        self.assertEqual(data, {"state": "none", "summary": None, "questions": [], "citations": [], "stale": False,
                                "generated_at": None, "error_code": None})
        self.assertEqual(self.db.rows, {})
        self.assertFalse(any(sql == nov._INSERT_SQL for sql, *_ in self.db.executed))

    def test_unknown_notebook_is_404(self):
        with self.assertRaises(NotebookOverviewError) as caught:
            self.service.get(CTX, "notebook-x")
        self.assertEqual((caught.exception.code, caught.exception.status), ("NOTEBOOK_NOT_FOUND", 404))
        with self.assertRaises(NotebookOverviewError) as caught:
            self.service.regenerate(CTX, "notebook-x")
        self.assertEqual(caught.exception.code, "NOTEBOOK_NOT_FOUND")

    def test_database_failure_is_503(self):
        self.db.fail = True
        with self.assertRaises(NotebookOverviewError) as caught:
            self.service.get(CTX, "notebook-1")
        self.assertEqual((caught.exception.code, caught.exception.status), ("OVERVIEW_UNAVAILABLE", 503))

    def _ready_row(self, fingerprint):
        self.db.rows[("tenant-1", "workspace-1", "notebook-1")] = {
            "state": "ready", "summary": "요약 [1]", "questions": list(QUESTIONS),
            "citations": [{"label": "1", "source_title": "약관.pdf", "page": 1}], "source_fingerprint": fingerprint,
            "model_ref": "MS:m", "safe_error_code": None, "attempt": 1, "lease_until": None, "requested_by": "actor-1",
            "updated_at": self.db.ts(), "created_at": self.db.ts()}

    def test_ready_row_is_returned_and_changed_sources_are_stale_without_regeneration(self):
        self._ready_row(sha(["sv-1", "sv-2"]))
        data = self.service.get(CTX, "notebook-1")
        self.assertEqual(data["state"], "ready")
        self.assertFalse(data["stale"])
        self.assertEqual(data["questions"], QUESTIONS)
        self.assertEqual(data["generated_at"], self.db.ts().isoformat())
        self.db.ready["notebook-1"].append("sv-3")
        before = copy.deepcopy(self.db.rows)
        data = self.service.get(CTX, "notebook-1")
        self.assertTrue(data["stale"])
        self.assertEqual(data["state"], "ready")  # 자동 재생성 없음(D-06)
        self.assertEqual(self.db.rows, before)
        self.assertFalse(any(sql in {nov._INSERT_SQL, nov._REQUEUE_SQL} for sql, *_ in self.db.executed))

    def test_regenerate_requeues_finished_row_and_clears_previous_content(self):
        self._ready_row(sha(["sv-1"]))
        data = self.service.regenerate(CTX, "notebook-1")
        self.assertEqual((data["state"], data["summary"], data["questions"], data["stale"]), ("queued", None, [], False))
        row = self.db.rows[("tenant-1", "workspace-1", "notebook-1")]
        self.assertEqual((row["attempt"], row["safe_error_code"], row["source_fingerprint"]), (0, None, None))

    def test_regenerate_while_queued_or_working_is_409(self):
        for state in ("queued", "working"):
            self._ready_row(None)
            self.db.rows[("tenant-1", "workspace-1", "notebook-1")]["state"] = state
            with self.assertRaises(NotebookOverviewError) as caught:
                self.service.regenerate(CTX, "notebook-1")
            self.assertEqual((caught.exception.code, caught.exception.status), ("OVERVIEW_IN_PROGRESS", 409))
            self.assertEqual(self.db.rows[("tenant-1", "workspace-1", "notebook-1")]["state"], state)

    def test_regenerate_without_row_creates_queued_or_rejects_without_ready_source(self):
        self.assertEqual(self.service.regenerate(CTX, "notebook-1")["state"], "queued")
        with self.assertRaises(NotebookOverviewError) as caught:
            self.service.regenerate(CTX, "notebook-2")
        self.assertEqual((caught.exception.code, caught.exception.status), ("OVERVIEW_NO_READY_SOURCE", 409))
        self.assertNotIn(("tenant-1", "workspace-1", "notebook-2"), self.db.rows)

    def test_failed_and_blocked_rows_expose_safe_error_code(self):
        self._ready_row(sha(["sv-1", "sv-2"]))
        self.db.rows[("tenant-1", "workspace-1", "notebook-1")].update(state="blocked", summary=None, questions=[], citations=[],
                                                                       safe_error_code="OVERVIEW_BLOCKED")
        data = self.service.get(CTX, "notebook-1")
        self.assertEqual((data["state"], data["error_code"], data["generated_at"]), ("blocked", "OVERVIEW_BLOCKED", None))

    def test_sql_never_updates_or_locks_canon_tables(self):
        canon = ("sources", "source_versions", "notebook_bindings", "notebook_source_unbindings", "notebooks",
                 "deletion_requests", "understanding_results", "evidence_spans")
        for name in dir(nov):
            value = getattr(nov, name)
            if not (name.startswith("_") and name.endswith("_SQL") and isinstance(value, str)):
                continue
            upper = value.upper()
            for table in canon:
                self.assertNotRegex(value, rf"(?i)UPDATE\s+{table}\b", name)
                self.assertNotRegex(value, rf"(?i)INSERT\s+INTO\s+{table}\b", name)
            if "FOR UPDATE" in upper:
                self.assertEqual(name, "_CLAIM_SQL")
                self.assertIn("FROM notebook_overviews", value)
                self.assertIn("FOR UPDATE SKIP LOCKED", value)


class GeneratorTests(unittest.TestCase):
    def run_gen(self, *responses, reader=None):
        llm = ScriptedLLM(*responses)
        generator = NotebookOverviewGenerator(reader or FakeReader(), llm)
        context = StudioContext("tenant-1", "workspace-1", "actor-1", "trace", "policy", "notebook-1")
        return generator, llm, generator.generate(context, ("sv-1",), cancel_check=lambda: None)

    def test_summary_cites_every_sentence_and_three_questions(self):
        _, llm, draft = self.run_gen(GOOD)
        self.assertEqual(draft.summary, "보험금은 청구서류 접수일부터 3일 이내에 지급한다. [1] 면책 기간은 계약일부터 90일이다. [2]")
        self.assertEqual(draft.citations, [{"label": "1", "source_title": "약관.pdf", "page": 1},
                                           {"label": "2", "source_title": "약관.pdf", "page": 2}])
        self.assertEqual(draft.questions, QUESTIONS)
        self.assertEqual(draft.model_ref, "MS:m-1")
        self.assertEqual(llm.flags, [True])  # 외부 전송 차단을 따로 알려 달라고 한다
        self.assertIn('<source id="S1"', llm.prompts[0].user)
        self.assertIn("구간에 없는 사실은 쓰지 않습니다", llm.prompts[0].system)

    def test_ungrounded_sentences_are_dropped(self):
        data = {"sentences": [{"text": "보험금은 청구서류 접수일부터 3일 이내에 지급한다.", "refs": ["S1"]},
                              {"text": "이 상품은 업계 최고입니다.", "refs": []},
                              {"text": "가입자는 99명이다.", "refs": ["S9"]},
                              {"text": "지급 한도는 5,000,000원이다.", "refs": ["S1"]}],  # 숫자가 근거와 다르다
                "questions": QUESTIONS}
        _, _, draft = self.run_gen(data)
        self.assertEqual(draft.summary, "보험금은 청구서류 접수일부터 3일 이내에 지급한다. [1]")
        self.assertNotIn("업계 최고", draft.summary)
        self.assertNotIn("99명", draft.summary)
        self.assertNotIn("5,000,000", draft.summary)
        self.assertEqual([c["label"] for c in draft.citations], ["1"])

    def test_all_sentences_ungrounded_is_final_failure(self):
        with self.assertRaises(OverviewFailure) as caught:
            self.run_gen({"sentences": [{"text": "근거 없는 말", "refs": []}], "questions": QUESTIONS})
        self.assertEqual((caught.exception.code, caught.exception.final), ("OVERVIEW_UNGROUNDED", True))

    def test_same_page_citations_share_one_label_and_model_markers_are_removed(self):
        data = {"sentences": [{"text": "보험금은 3일 이내에 지급한다 [S1].", "refs": ["S1"]},
                              {"text": "지급 한도는 1,000,000원이다.", "refs": ["S1", "S2"]}],
                "questions": QUESTIONS + ["네 번째 질문?"]}
        _, _, draft = self.run_gen(data)
        self.assertEqual(draft.summary, "보험금은 3일 이내에 지급한다. [1] 지급 한도는 1,000,000원이다. [1][2]")
        self.assertEqual(draft.questions, QUESTIONS)

    def test_fewer_than_three_questions_is_retryable_failure(self):
        with self.assertRaises(OverviewFailure) as caught:
            self.run_gen({"sentences": GOOD["sentences"], "questions": ["하나?", "하나?", " "]})
        self.assertEqual((caught.exception.code, caught.exception.final), ("OVERVIEW_GENERATION_FAILED", False))

    def test_egress_block_is_blocked_and_provider_failure_retryable(self):
        with self.assertRaises(OverviewFailure) as caught:
            self.run_gen(StudioError("STUDIO_EGRESS_BLOCKED", 403))
        self.assertEqual((caught.exception.code, caught.exception.final, caught.exception.state), ("OVERVIEW_BLOCKED", True, "blocked"))
        with self.assertRaises(OverviewFailure) as caught:
            self.run_gen(StudioError("PROVIDER_UNAVAILABLE", 503))
        self.assertEqual((caught.exception.code, caught.exception.final), ("OVERVIEW_PROVIDER_UNAVAILABLE", False))
        with self.assertRaises(OverviewFailure) as caught:
            self.run_gen(GOOD, reader=FakeReader(error=StudioError("STUDIO_NO_READY_SOURCE", 409)))
        self.assertEqual((caught.exception.code, caught.exception.final), ("OVERVIEW_NO_READY_SOURCE", True))

    def test_blocked_by_real_egress_gate_makes_zero_model_calls(self):
        from daon2_user_api.studio_egress import EgressDecision
        from test_studio_v2_generation import FakeCatalog, FakeResolver, FakeTransport, model

        class Deny:
            def authorize(self, context, model, size):
                return EgressDecision(False, "EGRESS_POLICY_DENIED")

        transport = FakeTransport([])
        llm = StudioTextGenerator(FakeResolver({"a": model("CUSTOM", "https://a.example/v1", kind="external_api")}),
                                  FakeCatalog([("a", "m", "MS")]), transport=transport, egress_gate=Deny())
        context = StudioContext("tenant-1", "workspace-1", "actor-1", "trace", "policy", "notebook-1")
        with self.assertRaises(OverviewFailure) as caught:
            NotebookOverviewGenerator(FakeReader(), llm).generate(context, ("sv-1",), cancel_check=lambda: None)
        self.assertEqual(caught.exception.state, "blocked")
        self.assertEqual(transport.calls, [])


class WorkerTests(unittest.TestCase):
    KEY = ("tenant-1", "workspace-1", "notebook-1")

    def setUp(self):
        self.db = FakeDb()
        NotebookOverviewService(self.db).get(CTX, "notebook-1")  # 첫 조회가 queued 행을 만든다

    def worker(self, *responses, reader=None):
        self.llm = ScriptedLLM(*responses)
        self.reader = reader or FakeReader()
        return NotebookOverviewWorker(self.db, NotebookOverviewGenerator(self.reader, self.llm), worker_id="w-1", lease_seconds=900)

    def test_queued_row_becomes_ready_with_fingerprint_and_audit(self):
        worker = self.worker(GOOD)
        self.assertTrue(worker.run_once())
        row = self.db.rows[self.KEY]
        self.assertEqual(row["state"], "ready")
        self.assertEqual(row["source_fingerprint"], sha(["sv-1", "sv-2"]))
        self.assertEqual(row["questions"], QUESTIONS)
        self.assertEqual(row["model_ref"], "MS:m-1")
        self.assertEqual(self.reader.calls[0][1], ("sv-1", "sv-2"))  # 준비된 소스 전체
        self.assertEqual(self.reader.calls[0][0].notebook_id, "notebook-1")
        self.assertFalse(worker.run_once())  # 더 할 일이 없다
        self.assertEqual(len(self.db.audit), 1)
        audit = self.db.audit[0]
        self.assertIn("notebook.overview.generate", audit)
        self.assertEqual(json.loads(audit[-1]), {"state": "ready", "source_count": 2})
        self.assertNotIn("보험금", json.dumps(audit, ensure_ascii=False))  # 본문·질문은 남기지 않는다
        claims = [cap for sql, _, cap in self.db.executed if sql in {nov._CLAIM_SQL, nov._SWEEP_SQL}]
        self.assertEqual(set(claims), {nov.WORKER_CAPABILITY})
        view = NotebookOverviewService(self.db).get(CTX, "notebook-1")
        self.assertEqual((view["state"], view["stale"]), ("ready", False))

    def test_blocked_is_terminal_without_retry(self):
        worker = self.worker(StudioError("STUDIO_EGRESS_BLOCKED", 403))
        worker.run_once()
        row = self.db.rows[self.KEY]
        self.assertEqual((row["state"], row["safe_error_code"], row["summary"]), ("blocked", "OVERVIEW_BLOCKED", None))
        self.db.now += 10_000
        self.assertFalse(worker.run_once())
        self.assertEqual(json.loads(self.db.audit[0][-1]), {"state": "blocked", "source_count": 2})

    def test_ungrounded_is_terminal_failed(self):
        worker = self.worker({"sentences": [{"text": "근거 없음", "refs": []}], "questions": QUESTIONS})
        worker.run_once()
        self.assertEqual((self.db.rows[self.KEY]["state"], self.db.rows[self.KEY]["safe_error_code"]), ("failed", "OVERVIEW_UNGROUNDED"))

    def test_retryable_failure_is_tried_three_times_then_failed(self):
        error = StudioError("PROVIDER_UNAVAILABLE", 503)
        worker = self.worker(error, error, error)
        worker.run_once()
        row = self.db.rows[self.KEY]
        self.assertEqual((row["state"], row["attempt"], row["safe_error_code"]), ("queued", 1, "OVERVIEW_PROVIDER_UNAVAILABLE"))
        self.assertFalse(worker.run_once())  # 대기 시간 전에는 다시 잡지 않는다
        for expected_attempt in (2, 3):
            self.db.now += 1000
            self.assertTrue(worker.run_once())
            self.assertEqual(self.db.rows[self.KEY]["attempt"], expected_attempt)
        row = self.db.rows[self.KEY]
        self.assertEqual((row["state"], row["safe_error_code"]), ("failed", "OVERVIEW_PROVIDER_UNAVAILABLE"))
        self.db.now += 10_000
        self.assertFalse(worker.run_once())
        self.assertEqual(len(self.llm.prompts), 3)
        self.assertEqual([json.loads(a[-1])["state"] for a in self.db.audit], ["failed"])

    def test_retry_then_success(self):
        worker = self.worker(StudioError("PROVIDER_TIMEOUT", 503), GOOD)
        worker.run_once()
        self.db.now += 1000
        worker.run_once()
        self.assertEqual(self.db.rows[self.KEY]["state"], "ready")

    def test_expired_lease_is_reclaimed_and_exhausted_lease_is_swept(self):
        row = self.db.rows[self.KEY]
        row.update(state="working", attempt=1, lease_until=self.db.now - 1)
        worker = self.worker(GOOD)
        self.assertTrue(worker.run_once())
        self.assertEqual((self.db.rows[self.KEY]["state"], self.db.rows[self.KEY]["attempt"]), ("ready", 2))
        self.db.rows[self.KEY].update(state="working", attempt=3, lease_until=self.db.now - 1)
        self.assertFalse(self.worker().run_once())
        self.assertEqual((self.db.rows[self.KEY]["state"], self.db.rows[self.KEY]["safe_error_code"]),
                         ("failed", "OVERVIEW_GENERATION_FAILED"))

    def test_lost_lease_does_not_overwrite_newer_work(self):
        db = self.db
        key = self.KEY

        class Stealing(ScriptedLLM):
            def generate(self, context, prompt, cancel_check=None, report_egress_block=False):
                db.rows[key]["attempt"] += 1  # 다른 워커가 lease 만료 뒤 다시 잡았다
                return super().generate(context, prompt, None, report_egress_block)

        worker = NotebookOverviewWorker(db, NotebookOverviewGenerator(FakeReader(), Stealing(GOOD)), worker_id="w-1")
        self.assertTrue(worker.run_once())
        self.assertEqual(db.rows[key]["state"], "working")
        self.assertEqual(db.audit, [])

    def test_heartbeat_extends_lease_during_generation(self):
        worker = self.worker(GOOD)
        worker.run_once()
        self.assertTrue(any(sql == nov._HEARTBEAT_SQL for sql, *_ in self.db.executed))

    def test_no_ready_source_at_generation_time_is_failed(self):
        self.db.ready["notebook-1"] = []
        worker = self.worker()
        worker.run_once()
        self.assertEqual((self.db.rows[self.KEY]["state"], self.db.rows[self.KEY]["safe_error_code"]), ("failed", "OVERVIEW_NO_READY_SOURCE"))
        self.assertEqual(self.llm.prompts, [])

    def test_unexpected_error_is_retryable(self):
        worker = self.worker(RuntimeError("boom"))
        worker.run_once()
        self.assertEqual((self.db.rows[self.KEY]["state"], self.db.rows[self.KEY]["safe_error_code"]), ("queued", "OVERVIEW_GENERATION_FAILED"))


class StudioWorkerIntegrationTests(unittest.TestCase):
    def test_studio_worker_runs_overview_work_in_the_same_loop(self):
        from daon2_user_api.studio_v2_worker import StudioV2Worker

        class EmptyQueue:
            def claim(self, worker_id, lease_seconds=900):
                return None

            def sweep(self):
                return 0

        class Overview:
            def __init__(self):
                self.calls = 0

            def run_once(self):
                self.calls += 1
                return self.calls == 1

        overview = Overview()
        worker = StudioV2Worker(EmptyQueue(), object(), object(), object(), worker_id="w", overview=overview)
        self.assertTrue(worker.run_once())
        self.assertFalse(worker.run_once())
        self.assertEqual(overview.calls, 2)
        # 개요 처리 실패가 스튜디오 작업 루프를 멈추지 않는다.
        class Broken:
            def run_once(self):
                raise RuntimeError("x")
        self.assertFalse(StudioV2Worker(EmptyQueue(), object(), object(), object(), worker_id="w", overview=Broken()).run_once())
        self.assertFalse(StudioV2Worker(EmptyQueue(), object(), object(), object(), worker_id="w").run_once())


if __name__ == "__main__":
    unittest.main()
