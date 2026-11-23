from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from daon2_user_api.source_upload import PostgresSourceUploadService


class PostgresSourceUploadServiceTests(unittest.TestCase):
    def test_registration_uses_deterministic_ids_and_reconciles_canon_after_object_completion(self) -> None:
        service = object.__new__(PostgresSourceUploadService)
        service._queue_store = Mock()  # type: ignore[attr-defined]
        service._canon_store = Mock()  # type: ignore[attr-defined]
        service._coordinator = Mock()  # type: ignore[attr-defined]
        service._worker = Mock()  # type: ignore[attr-defined]
        service._coordinator.submit.side_effect = (  # type: ignore[attr-defined]
            lambda *_args, **kwargs: SimpleNamespace(
                object_id=kwargs["object_id"], replayed=False
            )
        )
        service._queue_store.get_object.return_value = SimpleNamespace(status="completed")  # type: ignore[attr-defined]

        result = service.register_pdf(
            tenant_id="tenant-001",
            workspace_id="workspace-001",
            notebook_id="notebook-001",
            actor_id="user-001",
            filename="fixture.pdf",
            content=b"%PDF-1.7\nfixture",
            idempotency_key="upload-001",
            trace_id="trace-upload-001",
        )

        submitted_id = service._coordinator.submit.call_args.kwargs["object_id"]  # type: ignore[attr-defined]
        self.assertRegex(submitted_id, r"^[0-9a-f]{32}$")
        self.assertEqual(result.object_id, submitted_id)
        self.assertEqual(result.source_id, f"src-{submitted_id}")
        self.assertEqual(result.source_version_id, f"sv-{submitted_id}")
        self.assertEqual(result.status, "accepted")
        service._canon_store.register_uploaded_source.assert_called_once()  # type: ignore[attr-defined]
        self.assertEqual(
            service._canon_store.register_uploaded_source.call_args.kwargs["digest_sha256"],  # type: ignore[attr-defined]
            result.digest_sha256,
        )
        self.assertEqual(
            service._canon_store.register_uploaded_source.call_args.kwargs["notebook_id"],  # type: ignore[attr-defined]
            "notebook-001",
        )


    @staticmethod
    def _service() -> PostgresSourceUploadService:
        service = object.__new__(PostgresSourceUploadService)
        service._queue_store = Mock()  # type: ignore[attr-defined]
        service._canon_store = Mock()  # type: ignore[attr-defined]
        service._coordinator = Mock()  # type: ignore[attr-defined]
        service._worker = Mock()  # type: ignore[attr-defined]
        service._coordinator.submit.side_effect = (  # type: ignore[attr-defined]
            lambda *_args, **kwargs: SimpleNamespace(object_id=kwargs["object_id"], replayed=False))
        service._queue_store.get_object.return_value = SimpleNamespace(status="completed")  # type: ignore[attr-defined]
        return service

    def test_text_sources_can_skip_digest_deduplication(self) -> None:
        service = self._service()
        service._canon_store.find_source_by_digest.return_value = ("src-old", "sv-old", "o" * 32)  # type: ignore[attr-defined]
        common = dict(tenant_id="tenant-001", workspace_id="workspace-001", notebook_id="notebook-001", actor_id="user-001",
                      filename="memo.txt", content=b"same text", trace_id="trace-001", content_type="text/plain")
        deduplicated = service.register_source(idempotency_key="upload-001", **common)
        fresh = service.register_source(idempotency_key="memo-001", deduplicate=False, **common)
        self.assertEqual(deduplicated.source_id, "src-old")
        self.assertNotEqual(fresh.source_id, "src-old")
        self.assertEqual(service._canon_store.find_source_by_digest.call_count, 1)  # type: ignore[attr-defined]
        self.assertEqual(service._canon_store.register_uploaded_source.call_args.kwargs["source_id"], fresh.source_id)  # type: ignore[attr-defined]

    def test_store_object_uses_the_upload_queue_without_canon_registration(self) -> None:
        service = self._service()
        object_id = service.store_object(tenant_id="tenant-001", workspace_id="workspace-001", actor_id="user-001",
                                         content=b"text", content_type="text/plain", idempotency_key="memo-reflect-1",
                                         trace_id="trace-001")
        self.assertRegex(object_id, r"^[0-9a-f]{32}$")
        submit = service._coordinator.submit.call_args.kwargs  # type: ignore[attr-defined]
        self.assertEqual((submit["area"], submit["content_type"], submit["object_id"]), ("source", "text/plain", object_id))
        service._canon_store.register_uploaded_source.assert_not_called()  # type: ignore[attr-defined]
        self.assertIs(service.canon_store, service._canon_store)  # type: ignore[attr-defined]
        same = service.store_object(tenant_id="tenant-001", workspace_id="workspace-001", actor_id="user-001",
                                    content=b"text", content_type="text/plain", idempotency_key="memo-reflect-1", trace_id="trace-002")
        self.assertEqual(same, object_id)


if __name__ == "__main__":
    unittest.main()
