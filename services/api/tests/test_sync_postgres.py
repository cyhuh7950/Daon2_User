from __future__ import annotations

import hashlib
import os
import secrets
import unittest
from datetime import UTC, datetime
from unittest.mock import Mock

from daon2_user_api.cloud_storage import CloudAccessContext, PostgresCloudStore
from daon2_user_api.data_canon import CanonicalContext, PostgresDataCanonStore, canonical_json_bytes
from daon2_user_api.document_index_postgres import PostgresDocumentIndex
from daon2_user_api.document_processing import DocumentProcessingContext
from daon2_user_api.notebook import NotebookContext, NotebookService
from daon2_user_api.notebook_postgres import PostgresNotebookRepository
from daon2_user_api.question_answering_postgres import PostgresQuestionAnsweringRepository, QuestionContext
from daon2_user_api.studio_report import StudioReportContext
from daon2_user_api.studio_report_postgres import PostgresStudioReportRepository
from daon2_user_api.sync_source_index import SyncSourceIndexer
from daon2_user_api.object_queue import (
    ObjectQueueCoordinator, ObjectStorageError, ObjectSubmission, PostgresObjectQueueStore,
    StagedObject, StoredObject,
)
from daon2_user_api.sync import SyncContext, SyncError, SyncItemInput, SyncItemKind, TargetVersion, TransferPayload
from daon2_user_api.sync_postgres import ObjectQueueSyncTransferPort, PostgresSyncService


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, str]] = {}

    def health(self) -> bool:
        return True

    def put_staged(self, key: str, content: bytes, content_type: str,
                   digest: str) -> StagedObject:
        if hashlib.sha256(content).hexdigest() != digest:
            raise ObjectStorageError("OBJECT_CHECKSUM_MISMATCH")
        self.objects[key] = (content, content_type, digest)
        return StagedObject(key, digest, len(content), content_type, "etag-stage", "stage-v1")

    def promote(self, staged: StagedObject, final_key: str, *, expected_digest: str,
                expected_size: int, content_type: str) -> StoredObject:
        content, actual_type, digest = self.objects[staged.key]
        if digest != expected_digest or len(content) != expected_size or actual_type != content_type:
            raise ObjectStorageError("OBJECT_CHECKSUM_MISMATCH")
        self.objects[final_key] = (content, content_type, digest)
        return StoredObject(final_key, digest, len(content), content_type, "etag-final", "final-v1")

    def get(self, key: str) -> bytes:
        return self.objects[key][0]


class _NoSourceCoordinator:
    def submit(self, *_args, **_kwargs):
        raise AssertionError("output import must not use source submission")


class _OutputImporter:
    def __init__(self) -> None:
        self.calls = 0

    def import_bundle(self, context, item, content, idempotency_key, *, relation):
        self.calls += 1
        return TargetVersion(
            "cloud-output-version", "cloud-output-object", item.item_id,
            item.digest_sha256, None, relation,
        )


class ObjectQueueSyncTransferPortUnitTests(unittest.TestCase):
    def test_local_file_is_finalized_before_returning_a_target(self) -> None:
        coordinator = Mock()
        submission = ObjectSubmission("0" * 32, "job-a", "event-a", False)
        coordinator.submit.return_value = submission
        context = SyncContext("tenant-a", "workspace-a", "actor-a", "trace-a", "policy-a")
        item = SyncItemInput(
            "item-a", None, "local-a", hashlib.sha256(b"txt").hexdigest(),
            3, "text/plain", None, None, item_kind=SyncItemKind.LOCAL_FILE,
        )
        target = ObjectQueueSyncTransferPort(coordinator).transmit(
            context, item, b"txt", "transfer-key", relation="copy",
        )
        coordinator.finalize.assert_called_once_with(
            CloudAccessContext("tenant-a", "workspace-a", "actor-a", "object.write"), submission,
        )
        self.assertEqual(target.target_object_id, submission.object_id)

    def test_notebook_transfer_indexes_after_final_storage(self) -> None:
        coordinator, indexer = Mock(), Mock()
        submission = ObjectSubmission("0" * 32, "job-a", "event-a", False)
        coordinator.submit.return_value = submission
        parent = Mock()
        parent.attach_mock(coordinator.finalize, "finalize")
        parent.attach_mock(indexer, "index")
        ctx = SyncContext("tenant-a", "workspace-a", "actor-a", "trace-a", "policy-a")
        item = SyncItemInput("item-a", None, "local-a", hashlib.sha256(b"txt").hexdigest(),
                             3, "text/plain", None, None, item_kind=SyncItemKind.LOCAL_FILE)
        ObjectQueueSyncTransferPort(coordinator, source_indexer=indexer).transmit(
            ctx, item, b"txt", "transfer-key", relation="copy", notebook_id="notebook-a",
        )
        self.assertEqual([c[0] for c in parent.mock_calls], ["finalize", "index"])
        indexer.assert_called_once_with(ctx, "notebook-a", item, coordinator.finalize.return_value)

    def test_output_item_is_dispatched_to_output_importer(self) -> None:
        content = b"{}"
        importer = _OutputImporter()
        port = ObjectQueueSyncTransferPort(_NoSourceCoordinator(), output_importer=importer)
        item = SyncItemInput(
            "output-item", None, "local-output-object", hashlib.sha256(content).hexdigest(),
            len(content), "application/vnd.daon.offline-studio-output+json", None, None,
            item_kind=SyncItemKind.OUTPUT_VERSION, output_version_id="local-output-version",
            dependency_item_ids=("source-item",),
        )
        target = port.transmit(
            SyncContext("tenant", "workspace", "actor", "trace", "policy"),
            item, content, "output-import-idem", relation="copy",
        )
        self.assertEqual(target.target_version_id, "cloud-output-version")
        self.assertEqual(importer.calls, 1)


@unittest.skipUnless(os.environ.get("DAON_TEST_POSTGRES_DSN"), "isolated PostgreSQL DSN required")
class PostgresSyncIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        dsn = os.environ["DAON_TEST_POSTGRES_DSN"]
        self.cloud = PostgresCloudStore(dsn)
        self.queue = PostgresObjectQueueStore(dsn)
        suffix = secrets.token_hex(6)
        self.context = SyncContext(
            f"tenant-sync-{suffix}", f"workspace-sync-{suffix}",
            f"actor-sync-{suffix}", f"trace-sync-{suffix}", "policy-sync-v1",
        )
        self.cloud.seed_scope(CloudAccessContext(
            self.context.tenant_id, self.context.workspace_id,
            self.context.actor_id, "sync.write",
        ))
        self.storage = _Storage()
        self.coordinator = ObjectQueueCoordinator(
            self.queue, self.storage, id_factory=lambda: secrets.token_hex(16)
        )
        self.transfer = ObjectQueueSyncTransferPort(self.coordinator)
        self.service = PostgresSyncService(
            self.cloud, self.transfer,
            clock=lambda: datetime(2026, 7, 30, 15, 0, tzinfo=UTC),
        )

    def tearDown(self) -> None:
        self.queue.close()
        self.cloud.close()

    def test_persists_approval_manifest_batch_target_and_restart_projection(self) -> None:
        content = b"postgres-sync"
        cloud_context = CloudAccessContext(self.context.tenant_id, self.context.workspace_id,
                                           self.context.actor_id, "object.write")
        digest = hashlib.sha256(content).hexdigest()
        item = SyncItemInput(
            f"source-txt-{digest}", None, "local-object-postgres",
            digest, len(content), "text/plain", None, None,
            item_kind=SyncItemKind.LOCAL_FILE,
        )
        batch_key = f"sync-transfer-2-{item.item_id}"
        operation = self.service.create_operation(
            self.context, target_area="cloud_sync", items=(item,),
            idempotency_key="create-postgres-sync", if_match="*",
        )
        self.assertEqual(self.storage.objects, {})
        with self.assertRaisesRegex(SyncError, "SYNC_APPROVAL_REQUIRED"):
            self.service.transfer_batch(
                self.context, operation_id=operation.operation_id,
                expected_version=operation.version, idempotency_key="batch-before-approval",
                cursor=None, payloads=(TransferPayload(item.item_id, content, None, None),),
            )
        self.assertEqual(self.storage.objects, {})
        approved = self.service.approve(
            self.context, operation_id=operation.operation_id,
            approved_item_ids=(item.item_id,), step_up_authorization_id="step-postgres-sync",
            expected_version=operation.version, idempotency_key="approve-postgres-sync",
            approval_verified=True,
        )
        self.assertEqual(self.storage.objects, {})
        other_job = self.coordinator.submit(
            cloud_context, area="source", content=b"unrelated", content_type="text/plain",
            idempotency_key="unrelated-object", trace_id=self.context.trace_id,
        )
        batch = self.service.transfer_batch(
            self.context, operation_id=operation.operation_id,
            expected_version=approved.version, idempotency_key=batch_key,
            cursor=None, payloads=(TransferPayload(item.item_id, content, None, None),),
        )
        replay = self.service.transfer_batch(
            self.context, operation_id=operation.operation_id,
            expected_version=approved.version, idempotency_key=batch_key,
            cursor=None, payloads=(TransferPayload(item.item_id, content, None, None),),
        )
        self.assertEqual((batch.batch_id, replay.batch_id), (batch.batch_id, batch.batch_id))
        restarted = PostgresSyncService(
            self.cloud, self.transfer,
            clock=lambda: datetime(2026, 7, 30, 15, 1, tzinfo=UTC),
        )
        view = restarted.get_operation(self.context, operation.operation_id)
        self.assertEqual(view.state, "reindex_requested")
        listed = restarted.list_operations(self.context)
        self.assertEqual(tuple(item.operation_id for item in listed), (operation.operation_id,))
        self.assertEqual(listed[0].item_ids, (item.item_id,))
        self.assertEqual((view.source_mutations, view.overwrite_count), (0, 0))
        stored = self.queue.get_object(cloud_context, view.target_versions[0].target_object_id)
        self.assertEqual(stored.status, "completed")
        self.assertEqual(self.storage.get(stored.object_key), content)
        self.assertEqual(self.queue.get_job(cloud_context, other_job.job_id).attempt, 0)
        with self.cloud._transaction(CloudAccessContext(
            self.context.tenant_id, self.context.workspace_id,
            self.context.actor_id, "sync.read",
        )) as connection:
            counts = connection.execute(
                "SELECT (SELECT count(*) FROM sync_approval_snapshots WHERE operation_id=%s),"
                "(SELECT count(*) FROM sync_manifest_items WHERE operation_id=%s),"
                "(SELECT count(*) FROM sync_transfer_batches WHERE operation_id=%s),"
                "(SELECT count(*) FROM sync_target_versions WHERE operation_id=%s),"
                "(SELECT count(*) FROM sync_reindex_requests WHERE operation_id=%s)",
                (operation.operation_id,) * 5,
            ).fetchone()
        self.assertEqual(tuple(counts or ()), (1, 1, 1, 1, 1))

        separate = self.service.create_operation(
            self.context, target_area="cloud_sync", items=(item,),
            idempotency_key="create-separate-sync", if_match="*",
        )
        approved_separate = self.service.approve(
            self.context, operation_id=separate.operation_id,
            approved_item_ids=(item.item_id,), step_up_authorization_id="step-separate-sync",
            expected_version=separate.version, idempotency_key="approve-separate-sync",
            approval_verified=True,
        )
        other = self.service.transfer_batch(
            self.context, operation_id=separate.operation_id,
            expected_version=approved_separate.version, idempotency_key=batch_key,
            cursor=None, payloads=(TransferPayload(item.item_id, content, None, None),),
        )
        self.assertEqual(other.state, "transferred")
        self.assertNotEqual(batch.batch_id, other.batch_id)
        other_view = self.service.get_operation(self.context, separate.operation_id)
        self.assertNotEqual(view.target_versions[0].target_object_id, other_view.target_versions[0].target_object_id)

    def test_cloud_source_preview_still_requires_a_registered_version(self) -> None:
        content = b"registered"
        item = SyncItemInput(
            "cloud-item", "cloud-version", "local-object-cloud",
            hashlib.sha256(content).hexdigest(), len(content), "text/plain", None, None,
        )
        def preview():
            return self.service.create_operation(
                self.context, target_area="cloud_sync", items=(item,),
                idempotency_key="cloud-source-preview", if_match="*",
            )

        with self.assertRaisesRegex(SyncError, "DATABASE_CONSTRAINT_VIOLATION"):
            preview()
        self.assertEqual(self.service.list_operations(self.context), ())
        canon = PostgresDataCanonStore(os.environ["DAON_TEST_POSTGRES_DSN"])
        try:
            context = CanonicalContext(
                self.context.tenant_id, self.context.workspace_id, self.context.actor_id,
                "canon.write", self.context.trace_id,
            )
            canon.create_source(context, "registered-source")
            payload = {"object_id": None, "title": "Registered source"}
            canon.append_source_version(
                context, source_version_id="cloud-version", source_id="registered-source",
                version_number=1, previous_version_id=None, canonical_payload=payload,
                digest_sha256=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
                created_at=datetime.now(UTC),
            )
        finally:
            canon.close()
        self.assertEqual(preview().state, "awaiting_approval")
        self.assertEqual(self.storage.objects, {})

    def test_notebook_sync_builds_searchable_original_index_once_without_model(self) -> None:
        ctx = self.context
        args = (ctx.tenant_id, ctx.workspace_id, ctx.actor_id, ctx.trace_id, ctx.policy_version)
        clock = lambda: datetime.now(UTC)
        notebook, _ = NotebookService(PostgresNotebookRepository(self.cloud), clock=clock).create(
            NotebookContext(*args), title="Sync QA", description="", idempotency_key="sync-qa-notebook",
        )
        content = b"Internal test keyword txsyncoriginal"
        item = SyncItemInput("local-sync-index", None, "local-sync-index", hashlib.sha256(content).hexdigest(),
                             len(content), "text/plain", None, None, item_kind=SyncItemKind.LOCAL_FILE)
        canon = PostgresDataCanonStore(os.environ["DAON_TEST_POSTGRES_DSN"])
        self.addCleanup(canon.close)
        port = ObjectQueueSyncTransferPort(
            self.coordinator, source_indexer=SyncSourceIndexer(self.cloud, canon, self.storage),
        )
        service = PostgresSyncService(self.cloud, port, clock=clock)
        created = service.create_operation(ctx, target_area="cloud_sync", items=(item,), notebook_id=notebook.notebook_id,
                                           if_match="*", idempotency_key="notebook-sync-preview")
        with self.assertRaisesRegex(SyncError, "IDEMPOTENCY_KEY_REUSED"):
            service.create_operation(ctx, target_area="cloud_sync", items=(item,), notebook_id="different-notebook",
                                     if_match="*", idempotency_key="notebook-sync-preview")
        step = service.approve(ctx, operation_id=created.operation_id, approved_item_ids=(item.item_id,),
                               step_up_authorization_id="step-sync-index", expected_version=created.version,
                               idempotency_key="approve-sync-index", approval_verified=True)
        for _ in range(2):
            service.transfer_batch(ctx, operation_id=created.operation_id, expected_version=step.version,
                                   idempotency_key="transfer-sync-index", cursor=None,
                                   payloads=(TransferPayload(item.item_id, content, None, None),))
        saved = service.get_operation(ctx, created.operation_id)
        self.assertEqual(saved.reindex_state, "indexed")
        object_id = saved.target_versions[0].target_object_id
        hits = PostgresDocumentIndex(self.cloud).search(
            DocumentProcessingContext(*args), source_id=f"src-{object_id}", source_version_id=f"sv-{object_id}",
            query="txsyncoriginal",
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].text, content.decode())
        sources = PostgresStudioReportRepository(self.cloud).list_sources(
            StudioReportContext(*args, notebook_id=notebook.notebook_id),
        )
        self.assertEqual(len(sources), 1)
        self.assertEqual((sources[0].processing_state, sources[0].job_state), ("completed", "completed"))
        preview = PostgresQuestionAnsweringRepository(self.cloud, self.storage).read_notebook_source_preview(
            QuestionContext(*args, notebook_id=notebook.notebook_id), f"src-{object_id}", f"sv-{object_id}",
        )
        self.assertEqual(preview.content, content)


if __name__ == "__main__":
    unittest.main()
