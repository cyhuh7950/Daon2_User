"""Studio v2 생성 워커(별도 컨테이너 studio-v2-worker). WO-F1 T1-08."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from dataclasses import dataclass

from .cloud_storage import CloudAccessContext, PostgresCloudStore
from .studio_v2_generation import GenerationContext, GeneratorRegistry, StudioCancelled
from .studio_v2_postgres import PostgresStudioV2Repository
from .studio_v2_queue import PostgresStudioV2Queue, StudioV2Job, StudioV2QueueError
from .studio_title import derive_title
from .studio_workspace import StudioContext, StudioError

_LOGGER = logging.getLogger(__name__)
RETRYABLE = frozenset({"STUDIO_DATABASE_UNAVAILABLE", "OBJECT_STORAGE_UNAVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE", "TTS_TIMEOUT", "TTS_ENGINE_UNREACHABLE", "TTS_ENGINE_UNAVAILABLE"})
_SWEEP_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class StudioV2WorkerSettings:
    database_dsn: str
    worker_id: str
    lease_seconds: int
    poll_seconds: float
    user_concurrency: int
    global_concurrency: int
    enabled: bool

    @classmethod
    def from_env(cls) -> "StudioV2WorkerSettings":
        flag = os.environ.get("DAON_STUDIO_V2_ENABLED", "false")
        if flag not in {"true", "false"}:
            raise ValueError("DAON_STUDIO_V2_ENABLED_FLAG_INVALID")
        dsn = os.environ.get("DAON_CLOUD_DATABASE_DSN", "").strip()
        if flag == "true" and not dsn:
            raise ValueError("STUDIO_V2_WORKER_DATABASE_REQUIRED")
        return cls(dsn, os.environ.get("DAON_STUDIO_V2_WORKER_ID", "studio-v2-worker-1"),
                   int(os.environ.get("DAON_STUDIO_V2_LEASE_SECONDS", "900")),
                   float(os.environ.get("DAON_STUDIO_V2_POLL_SECONDS", "0.5")),
                   int(os.environ.get("DAON_STUDIO_V2_USER_CONCURRENCY", "2")),
                   int(os.environ.get("DAON_STUDIO_V2_GLOBAL_CONCURRENCY", "4")), flag == "true")


class StudioV2Worker:
    def __init__(self, queue: PostgresStudioV2Queue, repository: PostgresStudioV2Repository, registry: GeneratorRegistry,
                 cloud_store, *, worker_id: str, lease_seconds: int = 900, clock=time.monotonic) -> None:  # type: ignore[no-untyped-def]
        self._queue = queue
        self._repository = repository
        self._registry = registry
        self._cloud_store = cloud_store
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._clock = clock
        self._last_sweep = float("-inf")

    def _context(self, job: StudioV2Job) -> StudioContext:
        request = job.request_json
        return StudioContext(job.tenant_id, job.workspace_id, job.actor_id, str(request.get("trace_id") or "studio-v2-worker"),
                             str(request.get("policy_version") or "studio-v2"), str(request.get("notebook_id")))

    def _customization(self, context: StudioContext) -> str:
        try:
            return str(self._repository.get_customization(context)["instruction"])
        except Exception:  # 맞춤설정 조회 실패가 생성을 막지 않는다.
            return ""

    def run_once(self) -> bool:
        self._sweep_if_due()
        job = self._queue.claim(self._worker_id, lease_seconds=self._lease_seconds)
        if job is None:
            return False
        try:
            self._process(job)
        except StudioV2QueueError as error:
            if error.code != "STUDIO_JOB_LEASE_LOST":
                raise
            _LOGGER.warning("STUDIO_V2_LEASE_LOST")
        return True

    def _sweep_if_due(self) -> None:
        now = self._clock()
        if now - self._last_sweep < _SWEEP_SECONDS:
            return
        self._last_sweep = now
        try:
            self._queue.sweep()
        except Exception:
            _LOGGER.warning("STUDIO_V2_SWEEP_FAILED")

    def _process(self, job: StudioV2Job) -> None:
        worker = self._worker_id
        try:
            job = self._queue.start(job, worker)
            request = job.request_json
            context = self._context(job)
            versions = tuple(str(v) for v in request.get("source_version_ids", ()))
            with self._cloud_store._transaction(CloudAccessContext(job.tenant_id, job.workspace_id, job.actor_id, "studio.v2.read")) as connection:
                if versions:
                    self._repository.require_scope(connection, context, versions)
            generator = self._registry.get(str(request.get("type_id")))

            def cancel_check() -> None:
                if self._queue.heartbeat(job, worker, extend_seconds=self._lease_seconds):
                    raise StudioCancelled()

            def progress(pct: int, note: str) -> None:
                if self._queue.heartbeat(job, worker, extend_seconds=self._lease_seconds,
                                         progress_pct=max(0, min(int(pct), 99)), note=note):
                    raise StudioCancelled()

            settings = dict(request.get("settings") or {})
            result = generator.generate(GenerationContext(
                context=context, output_id=job.output_id, type_id=str(request.get("type_id")),
                format_id=request.get("format_id") if isinstance(request.get("format_id"), str) else None,
                settings=settings, source_version_ids=versions, customization=self._customization(context),
                language=str(settings.get("language", "ko")), mode=str(request.get("mode", "create")),
                progress=progress, cancel_check=cancel_check))
            cancel_check()
            self._repository.add_revision(
                context, job.output_id, "regenerated" if request.get("mode") == "regenerate" else "generated",
                result.content, warnings=list(result.warnings), generated_with=result.generated_with,
                sources=result.sources, evidence=result.evidence, assets=result.assets)
            if request.get("mode", "create") == "create":
                try:
                    title = derive_title(result.content)
                    if title:
                        self._repository.apply_generated_title(context, job.output_id, title)
                except Exception:
                    _LOGGER.warning("STUDIO_V2_TITLE_FAILED")  # 제목은 부가 기능이다. 실패해도 산출물은 완료한다.
            self._queue.finish(job, worker, state="completed")
        except StudioCancelled:
            self._queue.finish(job, worker, state="cancelled")
        except StudioV2QueueError:
            raise
        except StudioError as error:
            self._fail(job, error.code, retryable=error.code in RETRYABLE)
        except Exception:
            self._fail(job, "STUDIO_JOB_PROCESSING_FAILED", retryable=True)

    def _fail(self, job: StudioV2Job, code: str, *, retryable: bool) -> None:
        if retryable and self._queue.retry(job, self._worker_id, error_code=code):
            return
        self._queue.finish(job, self._worker_id, state="failed", error_code="STUDIO_DEAD_LETTER" if retryable else code)

    def run_forever(self, stop: threading.Event, *, poll_seconds: float = 0.5) -> None:
        if not 0 < poll_seconds <= 60:
            raise ValueError("STUDIO_V2_WORKER_POLL_INVALID")
        while not stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                _LOGGER.warning("STUDIO_V2_POLL_FAILED")
                worked = False
            if not worked:
                stop.wait(poll_seconds)


def _registry(cloud_store) -> GeneratorRegistry:  # type: ignore[no-untyped-def]
    """Provider 키 파일이 있으면 실제 생성기, 없으면 스텁(시험용)."""
    key_file = os.environ.get("DAON_PROVIDER_CREDENTIAL_KEY_FILE", "").strip()
    if not key_file:
        _LOGGER.warning("STUDIO_V2_STUB_GENERATORS")
        return GeneratorRegistry.with_stubs()
    from pathlib import Path
    from .provider_credentials import ProviderCredentialCipher
    from .studio_generators import build_registry
    from .studio_source_reader import StudioSourceReader
    from .studio_text_generation import StudioModelCatalog, StudioTextGenerator
    from .user_provider_credentials import PostgresUserProviderCredentialService
    from .workspace_model_defaults import PostgresWorkspaceModelResolver
    cipher = ProviderCredentialCipher(Path(key_file).read_bytes(), encryption_key_version=1)
    resolver = PostgresWorkspaceModelResolver(cloud_store, cipher, PostgresUserProviderCredentialService(cloud_store, cipher))
    from .egress_policy import EgressPolicyService
    from .egress_policy_postgres import PostgresEgressPolicyRepository
    from .studio_egress import StudioEgressGate
    gate = StudioEgressGate(EgressPolicyService(PostgresEgressPolicyRepository(cloud_store)))
    llm = StudioTextGenerator(resolver, StudioModelCatalog(cloud_store), egress_gate=gate)
    reader = StudioSourceReader(cloud_store)
    context_chars = int(os.environ.get("DAON_STUDIO_V2_CONTEXT_CHARS", "16000"))
    registry = build_registry(reader, llm, context_chars=context_chars)
    from .tts_engines import configured_from_env as tts_file_config
    from .tts_engine_service import TtsEngineService
    from .knowledge_connector_service import settings_from_env as _tts_env
    tts_engines = TtsEngineService(cloud_store, cipher, file_config=tts_file_config(), allow_private=_tts_env()["allow_private"])
    from .studio_audio import AudioOverviewGenerator
    registry.register(AudioOverviewGenerator(reader, llm, tts_engines.for_tenant, egress_gate=gate, context_chars=context_chars))
    from .studio_video import VideoOverviewGenerator, ffmpeg_path
    if ffmpeg_path() is not None:
        registry.register(VideoOverviewGenerator(reader, llm, tts_engines.for_tenant, egress_gate=gate, context_chars=context_chars))
    from .authoring.pipeline import AuthoringPipeline
    from .authoring.service import AuthoringGenerator
    from .authoring.templates import TemplateRegistry
    from .authoring.org_templates import OrgTemplateProvider, OrgTemplateStore
    from .knowledge_connector_service import KnowledgeConnectorService, settings_from_env
    from .knowledge_connector_egress import ConnectorEgressGate
    connectors = KnowledgeConnectorService(cloud_store, cipher, egress_gate=ConnectorEgressGate(EgressPolicyService(PostgresEgressPolicyRepository(cloud_store))), **settings_from_env())
    repository = PostgresStudioV2Repository(cloud_store)
    registry.register(AuthoringGenerator(AuthoringPipeline(TemplateRegistry(org_provider=OrgTemplateProvider(OrgTemplateStore(cloud_store))), reader, llm, connectors, repository.latest_content, context_chars=context_chars)))
    return registry


def main() -> None:
    settings = StudioV2WorkerSettings.from_env()
    if not settings.enabled:
        return
    cloud_store = PostgresCloudStore(settings.database_dsn)
    queue = PostgresStudioV2Queue(cloud_store, user_concurrency=settings.user_concurrency,
                                  global_concurrency=settings.global_concurrency)
    repository = PostgresStudioV2Repository(cloud_store)
    worker = StudioV2Worker(queue, repository, _registry(cloud_store), cloud_store,
                            worker_id=settings.worker_id, lease_seconds=settings.lease_seconds)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_a: stop.set())
    signal.signal(signal.SIGINT, lambda *_a: stop.set())
    try:
        worker.run_forever(stop, poll_seconds=settings.poll_seconds)
    finally:
        cloud_store.close()


if __name__ == "__main__":
    main()
