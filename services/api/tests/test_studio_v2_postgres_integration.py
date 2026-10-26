"""Studio v2 저장소·큐·워커 실DB 시험. 다음 환경 변수가 있을 때만 실행한다.

DAON_STUDIO_V2_TEST_DSN       daon_app 멤버의 NOSUPERUSER NOBYPASSRLS 로그인 DSN(마이그레이션 0074 적용 DB)
DAON_STUDIO_V2_TEST_SEED_DSN  시험용 노트북 행을 만들 관리자 DSN
"""
from __future__ import annotations

import hashlib
import os
import unittest
import uuid

from daon2_user_api.cloud_storage import PostgresCloudStore
from daon2_user_api.studio_v2_generation import GeneratorRegistry
from daon2_user_api.studio_v2_postgres import PostgresStudioV2Repository
from daon2_user_api.studio_v2_queue import PostgresStudioV2Queue
from daon2_user_api.studio_v2_worker import StudioV2Worker
from daon2_user_api.studio_workspace import StudioContext, StudioError

DSN = os.environ.get("DAON_STUDIO_V2_TEST_DSN")
SEED = os.environ.get("DAON_STUDIO_V2_TEST_SEED_DSN")


class NoScopeRepository(PostgresStudioV2Repository):
    """원본 Source 바인딩은 이 시험의 대상이 아니다(기존 Studio 시험이 다룬다)."""

    def require_scope(self, connection, context, versions):
        return None

    def ready_source_versions(self, connection, context):
        return ["source-version-it-1"]


@unittest.skipUnless(DSN and SEED, "DAON_STUDIO_V2_TEST_DSN / DAON_STUDIO_V2_TEST_SEED_DSN required")
class StudioV2PostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        with psycopg.connect(SEED, autocommit=True) as seed:
            row = seed.execute("SELECT tenant_id,workspace_id FROM workspaces LIMIT 1").fetchone()
            cls.tenant, cls.workspace = row
            cls.notebook = "nb-v2-it-" + uuid.uuid4().hex[:12]
            seed.execute("INSERT INTO notebooks(tenant_id,workspace_id,notebook_id,created_by,created_at) VALUES (%s,%s,%s,'it',now())",
                         (cls.tenant, cls.workspace, cls.notebook))
        cls.store = PostgresCloudStore(DSN)
        cls.repo = NoScopeRepository(cls.store)
        cls.queue = PostgresStudioV2Queue(cls.store, user_concurrency=2, global_concurrency=50)
        cls.ctx = StudioContext(cls.tenant, cls.workspace, "it-actor", "trace-it", "policy-it", cls.notebook)
        cls.other = StudioContext(cls.tenant, cls.workspace, "it-actor-2", "trace-it", "policy-it", cls.notebook)

    @classmethod
    def tearDownClass(cls):
        from daon2_user_api.cloud_storage import CloudAccessContext
        with cls.store._transaction(CloudAccessContext(cls.tenant, cls.workspace, "it-actor", "studio.v2.write")) as c:
            c.execute("SELECT count(*) FROM delete_notebook_scope(%s,%s,%s)", (cls.tenant, cls.workspace, cls.notebook)).fetchall()
            left = c.execute("SELECT count(*) FROM studio_v2_outputs WHERE notebook_id=%s", (cls.notebook,)).fetchone()[0]
        cls.store.close()
        assert left == 0, "notebook delete must cascade to studio_v2_outputs"

    def key(self):
        return "it-key-" + uuid.uuid4().hex

    def drain(self):
        """남은 큐를 모두 처리해 시험 간 간섭을 없앤다."""
        worker = StudioV2Worker(self.queue, self.repo, GeneratorRegistry.with_stubs(), self.store, worker_id="it-worker")
        while worker.run_once():
            pass

    def test_create_replay_conflict_and_worker_completion(self):
        key = self.key()
        first = self.repo.enqueue(self.ctx, {"type_id": "report"}, key)
        self.assertEqual(first["status"], "queued")
        again = self.repo.enqueue(self.ctx, {"type_id": "report"}, key)
        self.assertTrue(again["replayed"])
        self.assertEqual(again["output_id"], first["output_id"])
        with self.assertRaisesRegex(StudioError, "IDEMPOTENCY_CONFLICT"):
            self.repo.enqueue(self.ctx, {"type_id": "report", "format_id": "briefing"}, key)
        self.drain()
        detail = self.repo.get_output(self.ctx, first["output_id"])
        self.assertEqual(detail["status"], "completed")
        self.assertEqual(detail["current_revision"], 1)
        self.assertEqual(detail["revision"]["content"]["schema"], "studio.report.v1")
        self.assertEqual(detail["source_count"], 1)
        listed = self.repo.list_outputs(self.ctx, limit=50)
        self.assertIn(first["output_id"], [i["output_id"] for i in listed["items"]])

    def test_user_edit_saves_a_validated_revision_and_carries_evidence_and_sources(self):
        created = self.repo.enqueue(self.ctx, {"type_id": "report"}, self.key())
        self.drain()
        oid = created["output_id"]
        before = self.repo.get_output(self.ctx, oid)
        known = [e["ref_id"] for e in before["evidence"]]
        body = {"title": "사용자 편집", "summary": "요약", "sections": [{"heading": "1장", "blocks": [
            {"type": "paragraph", "text": "사용자가 고친 문장", "refs": known[:1] + ["S99"]}]}]}
        number = self.repo.save_user_edit(self.ctx, oid, {"body": body}, "문장 수정")
        self.assertEqual(number, before["current_revision"] + 1)
        after = self.repo.get_output(self.ctx, oid)
        self.assertEqual(after["revision"]["content"]["body"]["sections"][0]["blocks"][0]["text"], "사용자가 고친 문장")
        self.assertEqual(after["revision"]["content"]["body"]["sections"][0]["blocks"][0]["refs"], known[:1])  # 알 수 없는 근거 라벨은 제거
        self.assertEqual([e["ref_id"] for e in after["evidence"]], known)  # 근거 연결을 이어 받는다
        self.assertEqual(after["source_count"], before["source_count"])
        self.assertFalse(after["stale"])
        with self.assertRaisesRegex(StudioError, "STUDIO_INPUT_INVALID"):
            self.repo.save_user_edit(self.ctx, oid, {"body": {"sections": []}})

    def test_generated_title_replaces_default_title_only(self):
        created = self.repo.enqueue(self.ctx, {"type_id": "report"}, self.key())
        oid = created["output_id"]
        self.assertTrue(self.repo.apply_generated_title(self.ctx, oid, "자동 제목"))
        self.assertEqual(self.repo.get_output(self.ctx, oid)["title"], "자동 제목")
        self.assertFalse(self.repo.apply_generated_title(self.ctx, oid, "다른 제목"))  # 이미 기본 제목이 아니다
        self.assertFalse(self.repo.apply_generated_title(self.ctx, oid, "가" * 41))
        renamed = self.repo.enqueue(self.ctx, {"type_id": "quiz"}, self.key())
        self.repo.rename(self.ctx, renamed["output_id"], "내가 정한 이름", None)
        self.assertFalse(self.repo.apply_generated_title(self.ctx, renamed["output_id"], "자동"))

    def test_unavailable_invalid_and_no_source(self):
        with self.assertRaisesRegex(StudioError, "STUDIO_TYPE_UNAVAILABLE"):
            self.repo.enqueue(self.ctx, {"type_id": "video_overview"}, self.key())
        with self.assertRaisesRegex(StudioError, "STUDIO_INPUT_INVALID"):
            self.repo.enqueue(self.ctx, {"type_id": "quiz", "settings": {"count": 999}}, self.key())

    def test_rename_edit_regenerate_delete(self):
        created = self.repo.enqueue(self.ctx, {"type_id": "mind_map"}, self.key())
        self.drain()
        oid = created["output_id"]
        head = self.repo.get_output(self.ctx, oid)
        with self.assertRaisesRegex(StudioError, "STUDIO_VERSION_CONFLICT"):
            self.repo.rename(self.ctx, oid, "x", "2000-01-01T00:00:00+00:00")
        renamed = self.repo.rename(self.ctx, oid, "내 마인드맵", head["updated_at"])
        self.assertEqual(renamed["title"], "내 마인드맵")
        number = self.repo.add_revision(self.ctx, oid, "user_edit", {"schema": "studio.mind_map.v1", "body": {"edited": True}})
        self.assertEqual(number, 2)
        regen = self.repo.regenerate(self.ctx, oid, {"focus": "핵심"}, self.key())
        self.assertEqual(regen["status"], "queued")
        with self.assertRaisesRegex(StudioError, "STUDIO_VERSION_CONFLICT"):
            self.repo.regenerate(self.ctx, oid, {}, self.key())
        self.drain()
        self.assertEqual(self.repo.get_output(self.ctx, oid)["current_revision"], 3)
        prov = self.repo.provenance(self.ctx, oid)
        self.assertEqual(prov["settings"], {"focus": "핵심"})
        self.assertNotIn("generated_with", prov)
        self.repo.soft_delete(self.ctx, oid)
        with self.assertRaisesRegex(StudioError, "RESOURCE_UNAVAILABLE"):
            self.repo.get_output(self.ctx, oid)

    def test_cancel_queued_job(self):
        created = self.repo.enqueue(self.ctx, {"type_id": "quiz"}, self.key())
        self.repo.request_cancel(self.ctx, created["output_id"])
        self.assertEqual(self.repo.get_output(self.ctx, created["output_id"])["status"], "cancelled")
        self.assertIsNone(self.queue.claim("it-worker-cancel"))

    def test_per_user_concurrency_limit_and_other_user(self):
        self.drain()
        ids = [self.repo.enqueue(self.other, {"type_id": "slides"}, self.key())["job_id"] for _ in range(3)]
        claimed = [self.queue.claim("it-w", lease_seconds=60) for _ in range(3)]
        self.assertEqual(sum(1 for j in claimed if j is not None), 2)
        for job in [j for j in claimed if j is not None]:
            self.queue.finish(job, "it-w", state="failed", error_code="IT_DONE")
        self.drain()
        self.assertEqual(len(ids), 3)

    def test_sweeper_dead_letters_exhausted_lease(self):
        import psycopg
        created = self.repo.enqueue(self.ctx, {"type_id": "flashcards"}, self.key())
        job = self.queue.claim("it-w2", lease_seconds=60)
        self.assertEqual(job.output_id, created["output_id"])
        with psycopg.connect(SEED, autocommit=True) as seed:
            seed.execute("UPDATE studio_v2_jobs SET lease_until=now()-interval '1 minute',attempt=max_attempts WHERE job_id=%s", (job.job_id,))
        self.assertGreaterEqual(self.queue.sweep(), 1)
        detail = self.repo.get_output(self.ctx, created["output_id"])
        self.assertEqual((detail["status"], detail["error_code"]), ("failed", "STUDIO_DEAD_LETTER"))

    def test_learning_attempts_are_private_and_customization_is_versioned(self):
        created = self.repo.enqueue(self.ctx, {"type_id": "quiz"}, self.key())
        self.drain()
        oid = created["output_id"]
        self.repo.record_learning_attempt(self.ctx, oid, 1, "quiz", {"score": 3, "total": 5}, self.key())
        self.assertEqual(len(self.repo.list_learning_attempts(self.ctx, oid)), 1)
        self.assertEqual(self.repo.list_learning_attempts(self.other, oid), [])
        self.assertEqual(self.repo.get_customization(self.ctx)["version"], 0)
        saved = self.repo.save_customization(self.ctx, "존댓말로", 0)
        self.assertEqual(saved["version"], 1)
        with self.assertRaisesRegex(StudioError, "STUDIO_VERSION_CONFLICT"):
            self.repo.save_customization(self.ctx, "x", 0)
        self.assertEqual(self.repo.save_customization(self.ctx, "x", 1)["version"], 2)

    def test_output_of_an_older_source_version_is_stale_and_of_the_latest_is_not(self):
        """ST-T09: 생성에 쓴 Source에 더 새 버전이 있으면 산출물이 stale이다. 실제 source_versions 행으로 확인한다.

        소스 행은 DB 가드(SOURCE_CLEANUP_DELETE_DENIED)로 지울 수 없으므로 고정 ID 한 벌(v1·v2)을 한 번만 만들고 재사용한다.
        """
        import psycopg
        source_id, v1, v2 = "src-it-stale", "sv-it-stale-1", "sv-it-stale-2"
        digest = hashlib.sha256(b"{}").hexdigest()  # canonical_text 기본값 '{}'의 해시(트리거가 검증한다)
        scope = (self.tenant, self.workspace)
        with psycopg.connect(SEED, autocommit=True) as seed:
            seed.execute("INSERT INTO sources(tenant_id,workspace_id,record_id,aggregate_id,digest_sha256,created_by,trace_id) VALUES (%s,%s,%s,%s,%s,'it','t') ON CONFLICT DO NOTHING",
                         (*scope, source_id, source_id, digest))
            seed.execute("INSERT INTO source_versions(tenant_id,workspace_id,record_id,aggregate_id,version,digest_sha256,created_by,trace_id,source_id) "
                         "VALUES (%s,%s,%s,%s,1,%s,'it','t',%s) ON CONFLICT DO NOTHING", (*scope, v1, source_id, digest, source_id))
            seed.execute("INSERT INTO source_versions(tenant_id,workspace_id,record_id,aggregate_id,version,previous_version_id,digest_sha256,created_by,trace_id,source_id) "
                         "VALUES (%s,%s,%s,%s,2,%s,%s,'it','t',%s) ON CONFLICT DO NOTHING", (*scope, v2, source_id, v1, digest, source_id))

        def output_with(version: str) -> str:
            class Repo(NoScopeRepository):
                def ready_source_versions(self, connection, context):
                    return [version]
            repo = Repo(self.store)
            created = repo.enqueue(self.ctx, {"type_id": "report"}, self.key())
            worker = StudioV2Worker(self.queue, repo, GeneratorRegistry.with_stubs(), self.store, worker_id="it-worker-stale")
            while worker.run_once():
                pass
            return created["output_id"]
        old_id, new_id = output_with(v1), output_with(v2)
        old, new = self.repo.get_output(self.ctx, old_id), self.repo.get_output(self.ctx, new_id)
        self.assertEqual((old["status"], new["status"]), ("completed", "completed"))
        self.assertTrue(old["stale"])
        self.assertFalse(new["stale"])
        listed = {i["output_id"]: i for i in self.repo.list_outputs(self.ctx, limit=50)["items"]}
        self.assertTrue(listed[old_id]["stale"])
        self.assertFalse(listed[new_id]["stale"])

    def test_memo_is_completed_and_idempotent(self):
        key = self.key()
        memo = self.repo.create_memo(self.ctx, None, "# 메모\n내용", key)
        self.assertFalse(memo["replayed"])
        self.assertTrue(self.repo.create_memo(self.ctx, None, "# 메모\n내용", key)["replayed"])
        detail = self.repo.get_output(self.ctx, memo["output_id"])
        self.assertEqual((detail["type_id"], detail["status"]), ("memo", "completed"))
        self.assertEqual(detail["revision"]["content"]["body"]["markdown"], "# 메모\n내용")

    def test_mcp_evidence_snapshot_is_returned_and_missing_ref_is_404(self):
        from daon2_user_api.studio_v2_service import StudioV2Service
        service = StudioV2Service(self.store)
        memo = self.repo.create_memo(self.ctx, "근거 메모", "본문", self.key())
        number = self.repo.add_revision(
            self.ctx, memo["output_id"], "user_edit", {"schema": "studio.memo.v1", "body": {"markdown": "본문"}},
            evidence=[{"ref_id": "K1", "origin": "mcp_daon_rag", "locator_kind": "page", "locator_value": "3",
                       "external_ref": {"tool": "search_document_evidence", "result": {"excerpt": "발췌"}}}])
        content = service.evidence_content(self.ctx, memo["output_id"], "K1", number)
        self.assertEqual(content.media_type, "application/json")
        self.assertIn("발췌", content.body.decode())
        with self.assertRaisesRegex(StudioError, "RESOURCE_UNAVAILABLE"):
            service.evidence_content(self.ctx, memo["output_id"], "nope", number)
        detail = self.repo.get_output(self.ctx, memo["output_id"], number)
        self.assertEqual([e["origin"] for e in detail["evidence"]], ["mcp_daon_rag"])
        self.assertTrue(detail["evidence"][0]["has_snapshot"])


if __name__ == "__main__":
    unittest.main()
