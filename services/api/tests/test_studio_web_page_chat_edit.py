"""WO-N8 작업 6: 웹 페이지 대화로 고치기(고친 안을 만들 때 HTML도 함께 만들고, 적용은 모델 없이)."""
from __future__ import annotations

import copy
import unittest
from contextlib import contextmanager

from daon2_user_api.studio_chat_edit import CHAT_EDIT_TYPES, flatten
from daon2_user_api.studio_chat_edit_runner import ChatEditRunner
from daon2_user_api.studio_v2_generation import GeneratorRegistry
from daon2_user_api.studio_v2_queue import StudioV2Job
from daon2_user_api.studio_v2_worker import StudioV2Worker
from daon2_user_api.studio_web_page import BRIDGE_SCRIPT, mark_edited_blocks
from daon2_user_api.studio_workspace import StudioError
from test_studio_chat_edit_runner import CTX, OID, FakeLlm, FakeQueue, FakeRepo
from test_studio_v2_edit_turns import REPORT, FakeConnection, Repo, turn

WEB = {"schema": "studio.web_page.v1", "body": {
    "title": "행사 안내", "title_insufficient": False, "request": "행사 안내 페이지를 만들어 주세요",
    "sections": [{"heading": "개요", "blocks": [
        {"type": "paragraph", "text": "예산은 500만 원이다.", "refs": ["S1"], "insufficient": False},
        {"type": "paragraph", "text": "장소는 본관 강당이다.", "refs": ["S1"], "insufficient": False},
        {"type": "metric", "label": "참가 인원", "value": "30명", "refs": ["S1"], "insufficient": False},
        {"type": "paragraph", "text": "확인 안 된 문장", "refs": [], "insufficient": True},
    ]}],
    "html": "<html><body>옛 페이지</body></html>"}}
EDIT = {"reply": "고쳤습니다", "changes": [{"op": "replace", "id": "s1.b2", "content": {"type": "paragraph", "text": "장소는 본관 대강당이다.", "refs": ["S1"]}, "reason": "요청"}]}
NUMBER_EDIT = {"reply": "고쳤습니다", "changes": [{"op": "replace", "id": "s1.b1", "content": {"type": "paragraph", "text": "예산은 900만 원이다.", "refs": ["S1"]}, "reason": "요청"}]}
PAGE = "<!DOCTYPE html><html><head></head><body><h1>행사 안내</h1><h2>개요</h2><p data-ref=\"S1\">장소는 본관 대강당이다.</p></body></html>"
BAD_PAGE = PAGE.replace("</body>", "<p>추가 4,500명</p></body>")


class WebRepo(FakeRepo):
    def __init__(self, content=WEB):  # type: ignore[no-untyped-def]
        super().__init__(content=content)

    def chat_material_scope(self, context, output_id):  # type: ignore[no-untyped-def]
        return {"versions": [], "refs": {"S1"}}

    def save_edit_turn_result(self, context, turn_id, *, reply, changes, new_evidence, preview=None):  # type: ignore[no-untyped-def]
        self.saved.append({"reply": reply, "changes": changes, "new_evidence": new_evidence, "preview": preview})


def run_web(llm, repo):  # type: ignore[no-untyped-def]
    ChatEditRunner(llm, repo).run(CTX, OID, "svt-1", "web_page", cancel_check=lambda: None)


class WebConnection(FakeConnection):
    def execute(self, sql, params=()):  # type: ignore[no-untyped-def]
        result = super().execute(sql, params)
        if sql.startswith("SELECT content_json"):
            content = self.repo.content
            result.fetchone = lambda: (content,)
        return result


class WebEditRepo(Repo):
    def __init__(self, *, content=WEB, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(type_id="web_page", **kwargs)
        self.content = content

    @contextmanager
    def _transaction(self, scope):  # type: ignore[no-untyped-def]
        yield WebConnection(self)


class WebPageChatEditTests(unittest.TestCase):
    def test_web_page_in_chat_edit_types(self):
        self.assertIn("web_page", CHAT_EDIT_TYPES)

    def test_runner_saves_preview_html_with_turn(self):
        llm, repo = FakeLlm(EDIT, {"html": PAGE}), WebRepo()
        run_web(llm, repo)
        self.assertEqual(len(llm.prompts), 2)
        preview = repo.saved[0]["preview"]
        self.assertIn(BRIDGE_SCRIPT, preview["html"])
        self.assertIn("Content-Security-Policy", preview["html"])
        self.assertEqual(preview["body"]["sections"][0]["blocks"][1]["text"], "장소는 본관 대강당이다.")
        self.assertFalse(preview["body"]["sections"][0]["blocks"][1]["insufficient"])
        self.assertEqual(preview["body"]["request"], WEB["body"]["request"])
        self.assertTrue(preview["body"]["sections"][0]["blocks"][3]["insufficient"])
        self.assertIn(WEB["body"]["request"], llm.prompts[1].user)
        self.assertEqual(repo.saved[0]["changes"][0]["after_text"], "장소는 본관 대강당이다.")

    def test_html_failure_fails_turn(self):
        repo = WebRepo()
        registry = GeneratorRegistry()
        registry.attach_chat_editor(ChatEditRunner(FakeLlm(EDIT, {"html": BAD_PAGE}, {"html": BAD_PAGE}), repo))
        job = StudioV2Job("t", "w", "job-1", OID, "a", 1, 3, 1, {"mode": "chat_edit", "type_id": "web_page", "settings": {"turn_id": "svt-1"}, "notebook_id": "nb",
                                                                "trace_id": "trace", "policy_version": "policy"})
        queue = FakeQueue()
        StudioV2Worker(queue, repo, registry, None, worker_id="w")._process(job)  # noqa: SLF001
        self.assertEqual(repo.failed, ["STUDIO_VALIDATION_FAILED"])
        self.assertEqual(queue.finished, [("failed", "STUDIO_VALIDATION_FAILED")])
        self.assertEqual(repo.saved, [])

    def test_edited_block_with_new_number_becomes_insufficient(self):
        page = PAGE.replace("장소는 본관 대강당이다.", "장소는 본관 강당이다.")
        llm, repo = FakeLlm(NUMBER_EDIT, {"html": page}), WebRepo()
        run_web(llm, repo)
        preview = repo.saved[0]["preview"]
        block = preview["body"]["sections"][0]["blocks"][0]
        self.assertEqual((block["text"], block["insufficient"]), ("예산은 900만 원이다.", True))
        self.assertNotIn("900만", llm.prompts[1].user)
        self.assertNotIn("900만", preview["html"])

    def test_apply_uses_stored_preview(self):
        preview = {"html": "<html><body><h2>개요</h2>새 페이지</body></html>",
                   "body": {**copy.deepcopy(WEB["body"]), "html": ""}}
        preview["body"]["sections"][0]["blocks"][1] = {"type": "paragraph", "text": "장소는 본관 대강당이다.", "refs": ["S1"], "insufficient": False}
        change = {**EDIT["changes"][0], "before_text": "장소는 본관 강당이다.", "after_text": "장소는 본관 대강당이다."}
        repo = WebEditRepo(turns=[turn(changes_json=[change], preview_json=preview)])
        number = repo.apply_edit_turn(CTX, OID, "svt-1")
        self.assertEqual(number, 4)
        body = repo.revisions[0][1]["body"]
        self.assertEqual(body["html"], preview["html"])
        self.assertEqual(body["sections"], preview["body"]["sections"])
        self.assertEqual(body["request"], WEB["body"]["request"])
        self.assertEqual(repo.revisions[0][1]["schema"], "studio.web_page.v1")

    def test_apply_without_preview_is_invalid(self):
        change = {**EDIT["changes"][0], "before_text": "", "after_text": ""}
        repo = WebEditRepo(turns=[turn(changes_json=[change], preview_json={})])
        with self.assertRaises(StudioError) as caught:
            repo.apply_edit_turn(CTX, OID, "svt-1")
        self.assertEqual((caught.exception.code, caught.exception.status), ("CHAT_EDIT_INVALID", 422))
        self.assertEqual(repo.revisions, [])

    def test_other_types_unchanged(self):
        repo = FakeRepo()
        llm = FakeLlm({"reply": "고쳤습니다", "changes": [{"op": "replace", "id": "s1.b1", "content": {"type": "paragraph", "text": "고침", "refs": []}, "reason": "요청"}]})
        ChatEditRunner(llm, repo).run(CTX, OID, "svt-1", "report", cancel_check=lambda: None)
        self.assertEqual(len(llm.prompts), 1)
        self.assertEqual(len(repo.saved), 1)
        saving = Repo(turns=[turn(state="working")])
        saving.save_edit_turn_result(CTX, "svt-1", reply="r", changes=[{"op": "replace"}], new_evidence=[])
        update = saving.updates("preview_json")[0]
        self.assertEqual(update[1][4].obj, {})
        applied = Repo(turns=[turn()])
        applied.apply_edit_turn(CTX, OID, "svt-1")
        self.assertEqual(applied.revisions[0][1]["body"]["sections"][0]["blocks"][0]["text"], "고침")
        self.assertNotIn("html", applied.revisions[0][1]["body"])
        self.assertEqual(REPORT["body"]["sections"][0]["blocks"][0]["text"], "가")


class SaveAndListTests(unittest.TestCase):
    def test_save_stores_preview_json(self):
        repo = Repo(turns=[turn(state="working")])
        preview = {"html": "<html></html>", "body": {"sections": []}}
        repo.save_edit_turn_result(CTX, "svt-1", reply="r", changes=[{"op": "replace"}], new_evidence=[], preview=preview)
        update = repo.updates("preview_json")[0]
        self.assertEqual(update[1][4].obj, preview)

    def test_list_turns_has_preview_html(self):
        repo = Repo(type_id="web_page", turns=[turn(preview_json={"html": "<html>새</html>", "body": {}}), turn(turn_id="svt-2", preview_json={})])
        turns = {item["turn_id"]: item for item in repo.list_edit_turns(CTX, OID)}
        self.assertEqual(turns["svt-1"]["preview_html"], "<html>새</html>")
        self.assertIsNone(turns["svt-2"]["preview_html"])
        self.assertNotIn("preview_json", turns["svt-1"])
        self.assertNotIn("body", turns["svt-1"])


class FlattenTests(unittest.TestCase):
    def test_flatten_skips_table_metric_and_summary(self):
        ids = [piece.id for piece in flatten("web_page", WEB)]
        self.assertEqual(ids, ["title", "s1", "s1.heading", "s1.b1", "s1.b2", "s1.b4"])


def _body(*blocks, heading="개요", title="행사 안내", title_insufficient=False):  # type: ignore[no-untyped-def]
    return {"title": title, "title_insufficient": title_insufficient, "request": "요청", "html": "",
            "sections": [{"heading": heading, "blocks": [dict(b) for b in blocks]}]}


OK_A = {"type": "paragraph", "text": "예산은 500만 원이다.", "refs": ["S1"], "insufficient": False}
OK_B = {"type": "paragraph", "text": "장소는 본관이다.", "refs": ["S1"], "insufficient": False}
BAD_C = {"type": "paragraph", "text": "근거 없는 2026-01-05 일정", "refs": ["S1"], "insufficient": True}


class MarkEditedBlocksTests(unittest.TestCase):
    def test_unchanged_blocks_keep_flags(self):
        old = _body(OK_A, BAD_C)
        marked = mark_edited_blocks(copy.deepcopy(old), old, "")
        self.assertEqual([b["insufficient"] for b in marked["sections"][0]["blocks"]], [False, True])

    def test_changed_block_without_refs_is_insufficient(self):
        old = _body(OK_A, OK_B)
        new = _body(OK_A, {**OK_B, "text": "장소는 별관이다.", "refs": []})
        self.assertTrue(mark_edited_blocks(new, old, "")["sections"][0]["blocks"][1]["insufficient"])

    def test_changed_block_with_known_anchor_stays_verified(self):
        old = _body(OK_A, OK_B)
        new = _body(OK_A, {**OK_B, "text": "장소는 본관이고 예산은 500만 원이다.", "insufficient": True})
        self.assertFalse(mark_edited_blocks(new, old, "")["sections"][0]["blocks"][1]["insufficient"])

    def test_new_anchor_found_in_extra_text_is_verified(self):
        old = _body(OK_A)
        new = _body(OK_A, {"type": "paragraph", "text": "참가비는 3만 원이다.", "refs": ["S2"]})
        self.assertTrue(mark_edited_blocks(new, old, "")["sections"][0]["blocks"][1]["insufficient"])
        self.assertFalse(mark_edited_blocks(new, old, "[찾은 자료]\n참가비 3만 원")["sections"][0]["blocks"][1]["insufficient"])

    def test_anchor_of_insufficient_old_block_does_not_count(self):
        old = _body(OK_A, BAD_C)
        new = _body(OK_A, BAD_C, {"type": "paragraph", "text": "2026-01-05에 연다.", "refs": ["S1"]})
        self.assertTrue(mark_edited_blocks(new, old, "")["sections"][0]["blocks"][2]["insufficient"])

    def test_shifted_insufficient_block_is_not_promoted(self):
        weak = {"type": "paragraph", "text": "확인 안 된 설명", "refs": ["S1"], "insufficient": True}
        old = _body(OK_A, weak)
        new = _body(weak)  # 앞 블록을 지워 자리가 바뀌었다
        self.assertTrue(mark_edited_blocks(new, old, "")["sections"][0]["blocks"][0]["insufficient"])

    def test_changed_heading_with_unknown_anchor_marks_section(self):
        old = _body(OK_A, OK_B)
        new = _body(OK_A, OK_B, heading="2027년 개요")
        self.assertEqual([b["insufficient"] for b in mark_edited_blocks(new, old, "")["sections"][0]["blocks"]], [True, True])
        same = _body(OK_A, OK_B, heading="행사 개요")
        self.assertEqual([b["insufficient"] for b in mark_edited_blocks(same, old, "")["sections"][0]["blocks"]], [False, False])

    def test_edit_under_unsupported_old_heading_stays_insufficient(self):
        weak = {"type": "paragraph", "text": "설명", "refs": ["S1"], "insufficient": True}
        old = {**_body(OK_A), "sections": [*_body(OK_A)["sections"], {"heading": "2027년 계획", "blocks": [weak]}]}
        new = copy.deepcopy(old)
        new["sections"][1]["blocks"][0] = {"type": "paragraph", "text": "고친 설명", "refs": ["S1"]}
        marked = mark_edited_blocks(new, old, "")
        self.assertTrue(marked["sections"][1]["blocks"][0]["insufficient"])
        self.assertFalse(marked["sections"][0]["blocks"][0]["insufficient"])

    def test_changed_title_is_rechecked(self):
        old = _body(OK_A)
        self.assertTrue(mark_edited_blocks(_body(OK_A, title="2027 행사 안내"), old, "")["title_insufficient"])
        self.assertFalse(mark_edited_blocks(_body(OK_A, title="새 행사 안내"), old, "")["title_insufficient"])
        kept = mark_edited_blocks(_body(OK_A, title_insufficient=True), _body(OK_A, title_insufficient=True), "")
        self.assertTrue(kept["title_insufficient"])

    def test_preserves_other_fields_and_does_not_mutate(self):
        old = _body(OK_A)
        new = _body({**OK_A, "text": "예산은 900만 원이다."})
        snapshot = copy.deepcopy(new)
        marked = mark_edited_blocks(new, old, "")
        self.assertEqual(new, snapshot)
        self.assertEqual((marked["request"], marked["html"], marked["title"]), ("요청", "", "행사 안내"))


if __name__ == "__main__":
    unittest.main()
