"""노트북 복사·채팅 기록 비움 실DB 시험(WO-F3). DAON_STUDIO_V2_TEST_DSN(마이그레이션 0076 적용 DB)과 관리자 DSN이 있을 때만 실행한다."""
from __future__ import annotations

import os
import unittest
import uuid

from daon2_user_api.cloud_storage import CloudAccessContext, PostgresCloudStore
from daon2_user_api.notebook import NotebookContext, NotebookError
from daon2_user_api.notebook_copy import NotebookCopyService
from daon2_user_api.studio_v2_postgres import PostgresStudioV2Repository
from daon2_user_api.studio_workspace import StudioContext

DSN = os.environ.get("DAON_STUDIO_V2_TEST_DSN")
SEED = os.environ.get("DAON_STUDIO_V2_TEST_SEED_DSN")


@unittest.skipUnless(DSN and SEED, "DAON_STUDIO_V2_TEST_DSN / DAON_STUDIO_V2_TEST_SEED_DSN required")
class NotebookCopyIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.created = []
        with psycopg.connect(SEED, autocommit=True) as seed:
            cls.tenant, cls.workspace = seed.execute("SELECT tenant_id,workspace_id FROM workspaces LIMIT 1").fetchone()
            cls.notebook = "nb-copy-it-" + uuid.uuid4().hex[:12]
            seed.execute("INSERT INTO notebooks(tenant_id,workspace_id,notebook_id,created_by,created_at) VALUES (%s,%s,%s,'it',now())", (cls.tenant, cls.workspace, cls.notebook))
            seed.execute("INSERT INTO notebook_metadata_versions(tenant_id,workspace_id,notebook_id,version,title,description,is_current,updated_by,updated_at) "
                         "VALUES (%s,%s,%s,1,'원본 노트북','설명',true,'it',now())", (cls.tenant, cls.workspace, cls.notebook))
            cls.source = None  # Source 연결 복사는 노트북 삭제 규칙(공유 Source 차단)과 충돌해 결정 대기
        cls.store = PostgresCloudStore(DSN)
        cls.service = NotebookCopyService(cls.store)
        cls.studio = PostgresStudioV2Repository(cls.store)
        cls.ctx = NotebookContext(cls.tenant, cls.workspace, "it-actor", "trace-it", "policy-it")
        cls.studio_ctx = StudioContext(cls.tenant, cls.workspace, "it-actor", "trace-it", "policy-it", cls.notebook)
        cls.memo = cls.studio.create_memo(cls.studio_ctx, "메모", "본문입니다", "copy-it-memo-" + uuid.uuid4().hex)
        cls.studio.save_customization(cls.studio_ctx, "존댓말로 답해 주세요", 0)

    @classmethod
    def tearDownClass(cls):
        for notebook in [cls.notebook, *cls.created]:
            with cls.store._transaction(CloudAccessContext(cls.tenant, cls.workspace, "it-actor", "studio.v2.write")) as c:
                c.execute("SELECT count(*) FROM delete_notebook_scope(%s,%s,%s)", (cls.tenant, cls.workspace, notebook)).fetchall()
        cls.store.close()

    def key(self):
        return "copy-it-key-" + uuid.uuid4().hex

    def copy(self, include=None, key=None, title=None):
        result = self.service.copy(self.ctx, self.notebook, title=title, include=include or {}, idempotency_key=key or self.key())
        self.created.append(result["notebook_id"])
        return result

    def test_copy_clones_memo_customization_and_sources_with_new_owner_and_ids(self):
        result = self.copy()
        self.assertEqual(result["title"], "원본 노트북 사본")
        self.assertEqual(result["copied"]["memos"], 1)
        self.assertEqual(result["copied"]["customization"], 1)
        self.assertEqual(result["copied"]["sources"], 0)
        new_ctx = StudioContext(self.tenant, self.workspace, "it-actor", "trace-it", "policy-it", result["notebook_id"])
        listed = self.studio.list_outputs(new_ctx)["items"]
        self.assertEqual(len(listed), 1)
        self.assertNotEqual(listed[0]["output_id"], self.memo["output_id"])
        copied = self.studio.get_output(new_ctx, listed[0]["output_id"])
        original = self.studio.get_output(self.studio_ctx, self.memo["output_id"])
        self.assertEqual(copied["revision"]["content"], original["revision"]["content"])
        self.assertEqual(self.studio.get_customization(new_ctx)["instruction"], "존댓말로 답해 주세요")
        with self.store._transaction(CloudAccessContext(self.tenant, self.workspace, "it-actor", "notebook.read_or_write")) as c:
            owner = c.execute("SELECT created_by FROM notebooks WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s", (self.tenant, self.workspace, result["notebook_id"])).fetchone()[0]
            chat = c.execute("SELECT count(*) FROM notebook_bindings WHERE tenant_id=%s AND workspace_id=%s AND notebook_id=%s AND binding_kind='conversation_thread'",
                             (self.tenant, self.workspace, result["notebook_id"])).fetchone()[0]
        self.assertEqual(owner, "it-actor")
        self.assertEqual(chat, 0)

    def test_include_flags_and_idempotent_replay(self):
        key = self.key()
        none = {"sources": False, "memos": False, "outputs": False, "customization": False}
        first = self.copy(include=none, key=key)
        self.assertEqual(first["copied"], {"sources": 0, "memos": 0, "outputs": 0, "customization": 0})
        again = self.service.copy(self.ctx, self.notebook, title=None, include=none, idempotency_key=key)
        self.assertTrue(again["replayed"])
        self.assertEqual(again["notebook_id"], first["notebook_id"])
        with self.assertRaises(NotebookError) as raised:
            self.service.copy(self.ctx, self.notebook, title=None, include={}, idempotency_key=key)
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_KEY_REUSED")

    def test_missing_notebook_and_bad_key(self):
        with self.assertRaises(NotebookError) as raised:
            self.service.copy(self.ctx, "nb-does-not-exist", title=None, include={}, idempotency_key=self.key())
        self.assertEqual(raised.exception.status, 404)
        with self.assertRaises(NotebookError):
            self.service.copy(self.ctx, self.notebook, title=None, include={}, idempotency_key="short")

    def test_chat_clear_is_per_user_and_repeatable(self):
        other = NotebookContext(self.tenant, self.workspace, "it-actor-2", "trace-it", "policy-it")
        self.service.clear_chat_history(self.ctx, self.notebook)
        self.service.clear_chat_history(self.ctx, self.notebook)
        with self.assertRaises(NotebookError):
            self.service.clear_chat_history(self.ctx, "nb-does-not-exist")
        for context, expected in ((self.ctx, 1), (other, 0)):
            with self.store._transaction(CloudAccessContext(self.tenant, self.workspace, context.actor_id, "notebook.read_or_write")) as c:
                count = c.execute("SELECT count(*) FROM notebook_chat_clears WHERE notebook_id=%s", (self.notebook,)).fetchone()[0]
            self.assertEqual(count, expected)


if __name__ == "__main__":
    unittest.main()
