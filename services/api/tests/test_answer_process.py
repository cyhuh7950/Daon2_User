"""NB1-F1 답변 과정 블록(answer_process.v1): 허용 목록·금지 문자열·최대 개수·저장/조회 왕복."""
from __future__ import annotations

import copy
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone

from daon2_user_api.answer_process import (
    MAX_SELECTED_EVIDENCE, build_answer_process, validate_answer_process,
)


def sample() -> dict:
    return {
        "version": 1,
        "scope": {"source_count": 2, "knowledge_packages": [{"name": "제안서 작업"}], "tools": None},
        "evidence": {"searched": 24, "selected": [{
            "title": "약관.txt", "page": 3, "origin": "raw_source",
            "source_id": "source-cp3", "source_version_id": "source-version-cp3",
        }]},
        "egress": {"decision": "allowed", "masked": False, "redacted": False, "policy_ref": "3f2a9c1b0d4e"},
        "model": {"connection": "Media Bridge", "model": "uss/solar-pro4", "reasoning": None},
        "verification": {"citations": 3, "valid": True, "insufficient": False, "retried": False},
    }


class ValidateAnswerProcessTests(unittest.TestCase):
    def test_plan_example_shape_is_accepted_unchanged(self) -> None:
        value = sample()
        self.assertEqual(validate_answer_process(copy.deepcopy(value)), value)

    def test_general_conversation_and_not_called_model_shapes(self) -> None:
        value = sample()
        value["scope"] = {"source_count": 0, "knowledge_packages": [], "tools": None}
        value["evidence"] = None
        value["egress"]["decision"] = "not_needed"
        value["model"] = None
        self.assertEqual(validate_answer_process(copy.deepcopy(value)), value)
        value["scope"]["tools"] = ["승인 지식"]
        self.assertEqual(validate_answer_process(copy.deepcopy(value))["scope"]["tools"], ["승인 지식"])

    def test_keys_outside_allow_list_are_rejected_at_every_level(self) -> None:
        mutations = (
            lambda v: v.update(prompt="system prompt"),
            lambda v: v["scope"].update(question="질문 원문"),
            lambda v: v["evidence"].update(text="근거 본문"),
            lambda v: v["evidence"]["selected"][0].update(chunk_text="본문"),
            lambda v: v["egress"].update(destination="provider"),
            lambda v: v["model"].update(api_key="x"),
            lambda v: v["model"].update(thinking="모델 내부 추론"),
            lambda v: v["verification"].update(raw="x"),
            lambda v: v["scope"]["knowledge_packages"][0].update(project_id="p-1"),
            lambda v: v.pop("verification"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                value = sample()
                mutate(value)
                with self.assertRaises(ValueError):
                    validate_answer_process(value)

    def test_forbidden_strings_are_rejected(self) -> None:
        forbidden = (
            "http://10.0.0.1/v1", "https://media-bridge-gateway.sinsan.kr/v1", "10.0.0.1",
            "sk-proj-abcdef123456", "admin@example.com", "Bearer abcdefghijk",
            "provider.internal", "media-bridge-gateway.sinsan.kr", "fe80::1",
            "eyJhbGciOiJIUzI1NiJ9.payload", "A" * 48,
        )
        places = (
            lambda v, s: v["evidence"]["selected"][0].update(title=s),
            lambda v, s: v["model"].update(connection=s),
            lambda v, s: v["model"].update(model=s),
            lambda v, s: v["scope"]["knowledge_packages"][0].update(name=s),
            lambda v, s: v["scope"].update(tools=[s]),
        )
        for text in forbidden:
            for index, place in enumerate(places):
                with self.subTest(text=text, place=index):
                    value = sample()
                    place(value, text)
                    with self.assertRaises(ValueError):
                        validate_answer_process(value)

    def test_enums_types_and_limits(self) -> None:
        mutations = (
            lambda v: v.update(version=2),
            lambda v: v["egress"].update(decision="denied"),
            lambda v: v["egress"].update(policy_ref="sha256:3f2a9"),
            lambda v: v["egress"].update(masked="false"),
            lambda v: v["scope"].update(source_count=True),
            lambda v: v["scope"].update(source_count=-1),
            lambda v: v["evidence"].update(searched=1.5),
            lambda v: v["evidence"]["selected"][0].update(origin="web"),
            lambda v: v["evidence"]["selected"][0].update(page=0),
            lambda v: v["evidence"]["selected"][0].update(source_id="bad id/x"),
            lambda v: v["verification"].update(citations=-1),
            lambda v: v["evidence"].update(selected=[v["evidence"]["selected"][0]] * (MAX_SELECTED_EVIDENCE + 1)),
            lambda v: v["model"].update(reasoning="high effort please"),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                value = sample()
                mutate(value)
                with self.assertRaises(ValueError):
                    validate_answer_process(value)
        self.assertEqual(MAX_SELECTED_EVIDENCE, 20)
        for value in (None, [], "process", 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_answer_process(value)


class BuildAnswerProcessTests(unittest.TestCase):
    def test_build_returns_only_allow_listed_fields(self) -> None:
        value = sample()
        built = build_answer_process(scope=value["scope"], evidence=value["evidence"], egress=value["egress"],
                                     model=value["model"], verification=value["verification"])
        self.assertEqual(built, value)

    def test_build_caps_selected_evidence_at_twenty_and_keeps_searched(self) -> None:
        value = sample()
        item = value["evidence"]["selected"][0]
        built = build_answer_process(
            scope=value["scope"], evidence={"searched": 40, "selected": [dict(item, page=n) for n in range(1, 31)]},
            egress=value["egress"], model=value["model"], verification=value["verification"])
        self.assertEqual(len(built["evidence"]["selected"]), 20)
        self.assertEqual([entry["page"] for entry in built["evidence"]["selected"]], list(range(1, 21)))
        self.assertEqual(built["evidence"]["searched"], 40)

    def test_build_blanks_unsafe_display_text_instead_of_leaking_it(self) -> None:
        value = sample()
        built = build_answer_process(
            scope={"source_count": 1, "knowledge_packages": [{"name": "http://10.0.0.1"}, {"name": "업무 A"}], "tools": None},
            evidence={"searched": 1, "selected": [dict(value["evidence"]["selected"][0], title="admin@example.com 메모")]},
            egress={"decision": "allowed", "masked": True, "redacted": True, "policy_ref": "sha256:" + "ab" * 32},
            model={"connection": "https://gateway.example.com", "model": "uss/solar-pro4", "reasoning": "high"},
            verification=value["verification"])
        self.assertEqual(built["scope"]["knowledge_packages"], [{"name": "업무 A"}])
        self.assertIsNone(built["evidence"]["selected"][0]["title"])
        self.assertIsNone(built["model"]["connection"])
        self.assertEqual(built["model"]["reasoning"], "high")
        self.assertEqual(built["egress"]["policy_ref"], "abababababab")
        self.assertNotIn("10.0.0.1", repr(built))
        self.assertNotIn("example.com", repr(built))


class _HistoryConnection:
    def __init__(self, result_json: dict) -> None:
        self.result_json = result_json

    def execute(self, sql, params=()):  # type: ignore[no-untyped-def]
        class Cursor:
            def __init__(self, row=None, rows=None):  # type: ignore[no-untyped-def]
                self.row, self.rows = row, rows or []

            def fetchone(self):  # type: ignore[no-untyped-def]
                return self.row

            def fetchall(self):  # type: ignore[no-untyped-def]
                return self.rows
        if sql.startswith("SELECT 1 FROM notebooks"):
            return Cursor((1,))
        if sql.startswith("SELECT r.record_id,r.created_at"):
            return Cursor(rows=[(
                "run-history", datetime(2026, 11, 23, tzinfo=timezone.utc), "completed",
                {"question": "약관의 해지 조건은?", "context_mode": "raw_only"},
                "result-history", self.result_json, False,
            )])
        if sql.startswith("SELECT run_result_id,record_id,canonical_json FROM citations"):
            return Cursor(rows=[])
        if sql.startswith("SELECT run_result_id,citation_id,document_id"):
            return Cursor(rows=[])
        raise AssertionError(sql)


class _HistoryStore:
    def __init__(self, result_json: dict) -> None:
        self.connection = _HistoryConnection(result_json)

    @contextmanager
    def _transaction(self, context):  # type: ignore[no-untyped-def]
        yield self.connection


class ChatHistoryProcessTests(unittest.TestCase):
    def turns(self, result_json: dict):  # type: ignore[no-untyped-def]
        from daon2_user_api.notebook import NotebookContext
        from daon2_user_api.notebook_copy import NotebookCopyService
        service = NotebookCopyService(_HistoryStore(result_json))  # type: ignore[arg-type]
        context = NotebookContext("tenant-cp3", "workspace-cp3", "actor-cp3", "trace-cp3", "policy-v1")
        return service.list_chat_turns(context, "notebook-cp3")

    def test_stored_process_is_returned_with_the_answer(self) -> None:
        turns = self.turns({"answer": "해지는 30일 전 통지", "insufficient": False, "citation_ids": [], "process": sample()})
        self.assertEqual(turns[0]["answer"]["process"], sample())

    def test_past_answer_without_process_returns_null(self) -> None:
        turns = self.turns({"answer": "과거 답변", "insufficient": False, "citation_ids": []})
        self.assertIn("process", turns[0]["answer"])
        self.assertIsNone(turns[0]["answer"]["process"])

    def test_tampered_process_is_lowered_to_null(self) -> None:
        tampered = sample()
        tampered["model"]["connection"] = "http://10.0.0.1"
        turns = self.turns({"answer": "답변", "insufficient": False, "citation_ids": [], "process": tampered})
        self.assertIsNone(turns[0]["answer"]["process"])


if __name__ == "__main__":
    unittest.main()
