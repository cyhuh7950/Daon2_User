"""Studio v2 작업 큐(studio_v2_jobs). 하트비트·sweeper·취소·동시 한도 포함. WO-F1 T1-07."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from psycopg.types.json import Jsonb  # noqa: F401  (호출부가 request_json 재사용 시 사용)

from .cloud_storage import CloudAccessContext

WORKER_CAPABILITY = "studio_v2.worker"
_WORKER_SCOPE = CloudAccessContext("system", "system", "studio-v2-worker", WORKER_CAPABILITY)


class StudioV2QueueError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class StudioV2Job:
    tenant_id: str
    workspace_id: str
    job_id: str
    output_id: str
    actor_id: str
    attempt: int
    max_attempts: int
    version: int
    request_json: Mapping[str, object]


_RUNNING = "r.state IN ('leased','generating') AND r.lease_until>=now()"


class PostgresStudioV2Queue:
    def __init__(self, cloud_store, *, user_concurrency: int = 2, global_concurrency: int = 4) -> None:  # type: ignore[no-untyped-def]
        if user_concurrency < 1 or global_concurrency < 1:
            raise ValueError("STUDIO_V2_CONCURRENCY_INVALID")
        self._cloud_store = cloud_store
        self._user_limit = user_concurrency
        self._global_limit = global_concurrency

    @staticmethod
    def _scope(job: StudioV2Job) -> CloudAccessContext:
        return CloudAccessContext(job.tenant_id, job.workspace_id, job.actor_id, "studio.v2.write")

    def claim(self, worker_id: str, *, lease_seconds: int = 900) -> StudioV2Job | None:
        with self._cloud_store._transaction(_WORKER_SCOPE) as connection:
            row = connection.execute(
                "WITH cand AS (SELECT j.tenant_id,j.workspace_id,j.job_id FROM studio_v2_jobs j "
                "WHERE ((j.state='queued' AND j.next_attempt_at<=now()) "
                "OR (j.state IN ('leased','generating') AND j.lease_until<now() AND j.attempt<j.max_attempts)) "
                "AND j.cancel_requested=false "
                f"AND (SELECT count(*) FROM studio_v2_jobs r WHERE {_RUNNING} "
                "AND r.tenant_id=j.tenant_id AND r.owner_actor_id=j.owner_actor_id)<%s "
                f"AND (SELECT count(*) FROM studio_v2_jobs r WHERE {_RUNNING})<%s "
                "ORDER BY j.next_attempt_at,j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT 1) "
                "UPDATE studio_v2_jobs j SET state='leased',attempt=j.attempt+1,lease_owner=%s,"
                "lease_until=now()+make_interval(secs=>%s),version=j.version+1,updated_at=now() FROM cand "
                "WHERE j.tenant_id=cand.tenant_id AND j.workspace_id=cand.workspace_id AND j.job_id=cand.job_id "
                "RETURNING j.tenant_id,j.workspace_id,j.job_id,j.output_id,j.owner_actor_id,j.attempt,j.max_attempts,j.version,j.request_json",
                (self._user_limit, self._global_limit, worker_id, float(lease_seconds))).fetchone()
        if row is None:
            return None
        return StudioV2Job(*[str(v) for v in row[:5]], int(row[5]), int(row[6]), int(row[7]), dict(row[8]))  # type: ignore[arg-type]

    def start(self, job: StudioV2Job, worker_id: str) -> StudioV2Job:
        with self._cloud_store._transaction(self._scope(job)) as connection:
            row = connection.execute(
                "UPDATE studio_v2_jobs SET state='generating',version=version+1,updated_at=now() WHERE tenant_id=%s AND workspace_id=%s "
                "AND job_id=%s AND version=%s AND lease_owner=%s AND state='leased' RETURNING version",
                (job.tenant_id, job.workspace_id, job.job_id, job.version, worker_id)).fetchone()
            if row is None:
                raise StudioV2QueueError("STUDIO_JOB_LEASE_LOST")
            connection.execute(
                "UPDATE studio_v2_outputs SET status='generating',error_code=NULL,updated_at=now() "
                "WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s", (job.tenant_id, job.workspace_id, job.output_id))
        return StudioV2Job(job.tenant_id, job.workspace_id, job.job_id, job.output_id, job.actor_id, job.attempt,
                           job.max_attempts, int(row[0]), job.request_json)

    def heartbeat(self, job: StudioV2Job, worker_id: str, *, extend_seconds: int = 900, progress_pct: int | None = None,
                  note: str | None = None) -> bool:
        """lease 연장·진행률 갱신. 반환값은 취소 요청 여부. lease를 잃으면 오류."""
        with self._cloud_store._transaction(self._scope(job)) as connection:
            row = connection.execute(
                "UPDATE studio_v2_jobs SET lease_until=now()+make_interval(secs=>%s),progress_pct=COALESCE(%s,progress_pct),"
                "progress_note=COALESCE(%s,progress_note),updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND job_id=%s "
                "AND lease_owner=%s AND state IN ('leased','generating') RETURNING cancel_requested",
                (float(extend_seconds), progress_pct, None if note is None else note[:200],
                 job.tenant_id, job.workspace_id, job.job_id, worker_id)).fetchone()
        if row is None:
            raise StudioV2QueueError("STUDIO_JOB_LEASE_LOST")
        return bool(row[0])

    def retry(self, job: StudioV2Job, worker_id: str, *, error_code: str, delay_seconds: float | None = None) -> bool:
        """재시도 예약. 시도 횟수를 다 썼으면 False(호출부가 finish(failed))."""
        if job.attempt >= job.max_attempts:
            return False
        delay = delay_seconds if delay_seconds is not None else 5.0 * (2 ** max(job.attempt - 1, 0))
        with self._cloud_store._transaction(self._scope(job)) as connection:
            row = connection.execute(
                "UPDATE studio_v2_jobs SET state='queued',lease_owner=NULL,lease_until=NULL,safe_error_code=%s,"
                "next_attempt_at=now()+make_interval(secs=>%s),version=version+1,updated_at=now() WHERE tenant_id=%s AND workspace_id=%s "
                "AND job_id=%s AND lease_owner=%s AND state IN ('leased','generating') RETURNING job_id",
                (error_code, float(delay), job.tenant_id, job.workspace_id, job.job_id, worker_id)).fetchone()
            if row is None:
                raise StudioV2QueueError("STUDIO_JOB_LEASE_LOST")
            connection.execute(
                "UPDATE studio_v2_outputs SET status='queued',updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s",
                (job.tenant_id, job.workspace_id, job.output_id))
        return True

    def finish(self, job: StudioV2Job, worker_id: str, *, state: str, error_code: str | None = None) -> None:
        if state not in {"completed", "failed", "cancelled"}:
            raise ValueError("STUDIO_V2_JOB_STATE_INVALID")
        with self._cloud_store._transaction(self._scope(job)) as connection:
            row = connection.execute(
                "UPDATE studio_v2_jobs SET state=%s,lease_owner=NULL,lease_until=NULL,safe_error_code=%s,"
                "progress_pct=CASE WHEN %s='completed' THEN 100 ELSE progress_pct END,completed_at=now(),version=version+1,updated_at=now() "
                "WHERE tenant_id=%s AND workspace_id=%s AND job_id=%s AND lease_owner=%s AND state IN ('leased','generating') RETURNING job_id",
                (state, error_code, state, job.tenant_id, job.workspace_id, job.job_id, worker_id)).fetchone()
            if row is None:
                raise StudioV2QueueError("STUDIO_JOB_LEASE_LOST")
            self._sync_output(connection, job.tenant_id, job.workspace_id, job.output_id, state, error_code)

    @staticmethod
    def _sync_output(connection, tenant_id: str, workspace_id: str, output_id: str, state: str, error_code: str | None) -> None:
        status = {"completed": "completed", "failed": "failed", "cancelled": "cancelled"}[state]
        connection.execute(
            "UPDATE studio_v2_outputs SET status=CASE WHEN %s='cancelled' AND current_revision>0 THEN 'completed' ELSE %s END,"
            "error_code=%s,updated_at=now() WHERE tenant_id=%s AND workspace_id=%s AND output_id=%s",
            (status, status, error_code, tenant_id, workspace_id, output_id))

    def sweep(self) -> int:
        """lease가 끝났는데 더 시도할 수 없는 작업을 종결하고(기존 큐의 영구 고착 결함 방지) 출력 상태를 맞춘다."""
        with self._cloud_store._transaction(_WORKER_SCOPE) as connection:
            rows = connection.execute(
                "UPDATE studio_v2_jobs SET state=CASE WHEN cancel_requested THEN 'cancelled' ELSE 'failed' END,"
                "lease_owner=NULL,lease_until=NULL,safe_error_code=CASE WHEN cancel_requested THEN NULL ELSE 'STUDIO_DEAD_LETTER' END,"
                "completed_at=now(),version=version+1,updated_at=now() "
                "WHERE state IN ('leased','generating') AND lease_until<now() AND (attempt>=max_attempts OR cancel_requested) "
                "RETURNING tenant_id,workspace_id,output_id,owner_actor_id,state,safe_error_code").fetchall()
        for tenant, workspace, output, actor, state, code in rows:
            scope = CloudAccessContext(str(tenant), str(workspace), str(actor), "studio.v2.write")
            with self._cloud_store._transaction(scope) as connection:
                self._sync_output(connection, str(tenant), str(workspace), str(output), str(state), code)
        return len(rows)

    def close(self) -> None:  # 풀은 cloud_store가 소유한다.
        return None
