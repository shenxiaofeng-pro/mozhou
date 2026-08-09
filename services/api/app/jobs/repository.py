import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from sqlite3 import Connection, Row
from typing import Any
from uuid import uuid4

from app.database import Database
from app.jobs.models import (
    AttemptState,
    ChunkState,
    Job,
    JobArtifact,
    JobArtifactContent,
    JobAttempt,
    JobChunk,
    JobDetail,
    JobEvent,
    JobKind,
    JobState,
)
from app.jobs.state_machine import require_job_transition


class JobNotFoundError(LookupError):
    pass


class JobIdempotencyConflictError(ValueError):
    pass


class ArtifactConflictError(ValueError):
    pass


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    return current if current.tzinfo is not None else current.replace(tzinfo=UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class JobRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_job(
        self,
        *,
        project_id: str,
        kind: JobKind,
        idempotency_key: str,
        input_payload: dict[str, object],
        provider: str,
        model: str,
        chapter_id: str | None = None,
        parent_job_id: str | None = None,
        progress_total: int = 0,
        estimated_calls: int = 0,
        now: datetime | None = None,
    ) -> tuple[Job, bool]:
        timestamp = _now(now).isoformat()
        input_json = _canonical_json(input_payload)
        job_id = str(uuid4())
        with self.database.connect() as connection:
            result = connection.execute(
                """
                INSERT INTO jobs (
                    id, project_id, chapter_id, parent_job_id, kind, state,
                    idempotency_key, input_json, progress_total, estimated_calls,
                    provider, model, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, kind, idempotency_key) DO NOTHING
                """,
                (
                    job_id,
                    project_id,
                    chapter_id,
                    parent_job_id,
                    kind.value,
                    JobState.QUEUED.value,
                    idempotency_key,
                    input_json,
                    progress_total,
                    estimated_calls,
                    provider,
                    model,
                    timestamp,
                    timestamp,
                ),
            )
            created = result.rowcount == 1
            if created:
                self._append_event(
                    connection,
                    job_id,
                    "created",
                    None,
                    JobState.QUEUED,
                    {},
                    timestamp,
                )
                row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT * FROM jobs
                    WHERE project_id = ? AND kind = ? AND idempotency_key = ?
                    """,
                    (project_id, kind.value, idempotency_key),
                ).fetchone()
                if row is not None and row["input_json"] != input_json:
                    raise JobIdempotencyConflictError(
                        "同一任务幂等键对应了不同输入"
                    )
        if row is None:
            raise JobNotFoundError(job_id)
        return self._job(row), created

    def get_job(self, job_id: str) -> Job:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return self._job(row)

    def get_job_detail(self, job_id: str) -> JobDetail:
        job = self.get_job(job_id)
        with self.database.connect() as connection:
            chunks = connection.execute(
                "SELECT * FROM job_chunks WHERE job_id = ? ORDER BY ordinal, id",
                (job_id,),
            ).fetchall()
            attempts = connection.execute(
                "SELECT * FROM job_attempts WHERE job_id = ? ORDER BY ordinal, id",
                (job_id,),
            ).fetchall()
            artifacts = connection.execute(
                "SELECT * FROM job_artifacts WHERE job_id = ? ORDER BY created_at, id",
                (job_id,),
            ).fetchall()
            events = connection.execute(
                "SELECT * FROM job_events WHERE job_id = ? ORDER BY sequence",
                (job_id,),
            ).fetchall()
        return JobDetail.model_validate({
            **job.model_dump(mode="json"),
            "chunks": [self._chunk(row) for row in chunks],
            "attempts": [self._attempt(row) for row in attempts],
            "artifacts": [self._artifact(row) for row in artifacts],
            "events": [self._event(row) for row in events],
        })

    def list_jobs(self, project_id: str, *, limit: int = 100) -> list[Job]:
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT 1 FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise JobNotFoundError(project_id)
            rows = connection.execute(
                """
                SELECT * FROM jobs WHERE project_id = ?
                ORDER BY updated_at DESC, id DESC LIMIT ?
                """,
                (project_id, limit),
            ).fetchall()
        return [self._job(row) for row in rows]

    def load_input(self, job_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT input_json FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        loaded = json.loads(row["input_json"])
        if not isinstance(loaded, dict):
            raise TypeError("任务输入不是对象")
        return loaded

    def transition_job(
        self,
        job_id: str,
        target: JobState,
        *,
        event_type: str = "state_changed",
        detail: dict[str, object] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> Job:
        timestamp = _now(now).isoformat()
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise JobNotFoundError(job_id)
            current = JobState(row["state"])
            require_job_transition(current, target)
            terminal = target in {
                JobState.CANCELLED,
                JobState.SUCCEEDED,
                JobState.FAILED,
                JobState.INTERRUPTED,
            }
            clear_for_queue = target == JobState.QUEUED
            connection.execute(
                """
                UPDATE jobs
                SET state = ?, updated_at = ?,
                    started_at = CASE WHEN ? = 'running' THEN COALESCE(started_at, ?) ELSE started_at END,
                    completed_at = CASE WHEN ? THEN ? WHEN ? THEN NULL ELSE completed_at END,
                    lease_owner = CASE WHEN ? THEN NULL ELSE lease_owner END,
                    lease_expires_at = CASE WHEN ? THEN NULL ELSE lease_expires_at END,
                    heartbeat_at = CASE WHEN ? THEN NULL ELSE heartbeat_at END,
                    error_code = CASE WHEN ? THEN NULL ELSE ? END,
                    error_message = CASE WHEN ? THEN NULL ELSE ? END
                WHERE id = ? AND state = ?
                """,
                (
                    target.value,
                    timestamp,
                    target.value,
                    timestamp,
                    terminal,
                    timestamp,
                    clear_for_queue,
                    terminal or clear_for_queue,
                    terminal or clear_for_queue,
                    terminal or clear_for_queue,
                    clear_for_queue,
                    error_code,
                    clear_for_queue,
                    error_message,
                    job_id,
                    current.value,
                ),
            )
            if target == JobState.CANCELLED:
                connection.execute(
                    """
                    UPDATE job_chunks SET state = ?, error_code = NULL, error_message = NULL,
                        updated_at = ?
                    WHERE job_id = ? AND state != ?
                    """,
                    (
                        ChunkState.CANCELLED.value,
                        timestamp,
                        job_id,
                        ChunkState.SUCCEEDED.value,
                    ),
                )
            elif target == JobState.FAILED:
                connection.execute(
                    """
                    UPDATE job_chunks SET state = ?, error_code = ?, error_message = ?,
                        updated_at = ? WHERE job_id = ? AND state = ?
                    """,
                    (
                        ChunkState.FAILED.value,
                        error_code,
                        error_message,
                        timestamp,
                        job_id,
                        ChunkState.RUNNING.value,
                    ),
                )
            elif target == JobState.INTERRUPTED:
                connection.execute(
                    """
                    UPDATE job_chunks SET state = ?, error_code = ?, error_message = ?,
                        updated_at = ? WHERE job_id = ? AND state = ?
                    """,
                    (
                        ChunkState.INTERRUPTED.value,
                        error_code,
                        error_message,
                        timestamp,
                        job_id,
                        ChunkState.RUNNING.value,
                    ),
                )
            elif target == JobState.QUEUED:
                connection.execute(
                    """
                    UPDATE job_chunks SET state = ?, error_code = NULL, error_message = NULL,
                        updated_at = ? WHERE job_id = ? AND state IN (?, ?, ?)
                    """,
                    (
                        ChunkState.QUEUED.value,
                        timestamp,
                        job_id,
                        ChunkState.FAILED.value,
                        ChunkState.INTERRUPTED.value,
                        ChunkState.CANCELLED.value,
                    ),
                )
            self._append_event(
                connection,
                job_id,
                event_type,
                current,
                target,
                detail or {},
                timestamp,
            )
            updated = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if updated is None:
            raise JobNotFoundError(job_id)
        return self._job(updated)

    def request_cancel(self, job_id: str, *, now: datetime | None = None) -> Job:
        job = self.get_job(job_id)
        if job.state == JobState.QUEUED:
            return self.transition_job(job_id, JobState.CANCELLED, event_type="cancelled", now=now)
        if job.state == JobState.RUNNING:
            return self.transition_job(
                job_id,
                JobState.PAUSE_REQUESTED,
                event_type="cancel_requested",
                now=now,
            )
        if job.state in {JobState.FAILED, JobState.INTERRUPTED}:
            return self.transition_job(job_id, JobState.CANCELLED, event_type="cancelled", now=now)
        return job

    def retry_job(self, job_id: str, *, now: datetime | None = None) -> Job:
        job = self.get_job(job_id)
        if job.state not in {JobState.FAILED, JobState.INTERRUPTED, JobState.CANCELLED}:
            return job
        return self.transition_job(job_id, JobState.QUEUED, event_type="retried", now=now)

    def lease_next(
        self,
        owner: str,
        eligible_kinds: set[JobKind],
        *,
        lease_duration: timedelta,
        now: datetime | None = None,
    ) -> Job | None:
        if not eligible_kinds:
            return None
        current = _now(now)
        timestamp = current.isoformat()
        expires_at = (current + lease_duration).isoformat()
        placeholders = ",".join("?" for _ in eligible_kinds)
        values = [kind.value for kind in sorted(eligible_kinds, key=lambda item: item.value)]
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"""
                SELECT * FROM jobs
                WHERE state = ? AND kind IN ({placeholders})
                ORDER BY created_at, id LIMIT 1
                """,
                [JobState.QUEUED.value, *values],
            ).fetchone()
            if row is None:
                return None
            job_id = str(row["id"])
            result = connection.execute(
                """
                UPDATE jobs
                SET state = ?, lease_owner = ?, lease_expires_at = ?, heartbeat_at = ?,
                    started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE id = ? AND state = ?
                """,
                (
                    JobState.RUNNING.value,
                    owner,
                    expires_at,
                    timestamp,
                    timestamp,
                    timestamp,
                    job_id,
                    JobState.QUEUED.value,
                ),
            )
            if result.rowcount != 1:
                return None
            self._append_event(
                connection,
                job_id,
                "leased",
                JobState.QUEUED,
                JobState.RUNNING,
                {"owner": owner, "lease_expires_at": expires_at},
                timestamp,
            )
            leased = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(leased) if leased is not None else None

    def heartbeat(
        self,
        job_id: str,
        owner: str,
        *,
        lease_duration: timedelta,
        now: datetime | None = None,
    ) -> bool:
        current = _now(now)
        timestamp = current.isoformat()
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE jobs
                SET heartbeat_at = ?, lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND lease_owner = ? AND state IN (?, ?)
                """,
                (
                    timestamp,
                    (current + lease_duration).isoformat(),
                    timestamp,
                    job_id,
                    owner,
                    JobState.RUNNING.value,
                    JobState.PAUSE_REQUESTED.value,
                ),
            )
        return result.rowcount == 1

    def recover_expired(
        self,
        *,
        now: datetime | None = None,
        requeue: bool = True,
    ) -> list[Job]:
        timestamp = _now(now).isoformat()
        recovered_ids: list[str] = []
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT id, state FROM jobs
                WHERE state IN (?, ?)
                  AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                ORDER BY created_at, id
                """,
                (JobState.RUNNING.value, JobState.PAUSE_REQUESTED.value, timestamp),
            ).fetchall()
            for row in rows:
                job_id = str(row["id"])
                current = JobState(row["state"])
                connection.execute(
                    """
                    UPDATE jobs SET state = ?, lease_owner = NULL, lease_expires_at = NULL,
                        heartbeat_at = NULL, error_code = ?, error_message = ?, updated_at = ?,
                        completed_at = ? WHERE id = ?
                    """,
                    (
                        JobState.INTERRUPTED.value,
                        "lease_expired",
                        "任务进程中断，已保留完成结果",
                        timestamp,
                        timestamp,
                        job_id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE job_attempts SET state = ?, error_code = ?, error_message = ?,
                        completed_at = ? WHERE job_id = ? AND state = ?
                    """,
                    (
                        AttemptState.INTERRUPTED.value,
                        "lease_expired",
                        "任务进程中断",
                        timestamp,
                        job_id,
                        AttemptState.RUNNING.value,
                    ),
                )
                connection.execute(
                    """
                    UPDATE job_chunks SET state = ?, error_code = ?, error_message = ?,
                        updated_at = ? WHERE job_id = ? AND state = ?
                    """,
                    (
                        ChunkState.INTERRUPTED.value,
                        "lease_expired",
                        "任务进程中断",
                        timestamp,
                        job_id,
                        ChunkState.RUNNING.value,
                    ),
                )
                self._append_event(
                    connection,
                    job_id,
                    "lease_expired",
                    current,
                    JobState.INTERRUPTED,
                    {},
                    timestamp,
                )
                if requeue:
                    connection.execute(
                        """
                        UPDATE jobs SET state = ?, error_code = NULL, error_message = NULL,
                            completed_at = NULL, updated_at = ? WHERE id = ?
                        """,
                        (JobState.QUEUED.value, timestamp, job_id),
                    )
                    connection.execute(
                        """
                        UPDATE job_chunks SET state = ?, error_code = NULL, error_message = NULL,
                            updated_at = ? WHERE job_id = ? AND state = ?
                        """,
                        (
                            ChunkState.QUEUED.value,
                            timestamp,
                            job_id,
                            ChunkState.INTERRUPTED.value,
                        ),
                    )
                    self._append_event(
                        connection,
                        job_id,
                        "recovered",
                        JobState.INTERRUPTED,
                        JobState.QUEUED,
                        {},
                        timestamp,
                    )
                recovered_ids.append(job_id)
        return [self.get_job(job_id) for job_id in recovered_ids]

    def update_progress(
        self,
        job_id: str,
        *,
        current: int,
        total: int,
        step: str,
        now: datetime | None = None,
    ) -> Job:
        if current < 0 or total < 0 or (total and current > total):
            raise ValueError("invalid job progress")
        timestamp = _now(now).isoformat()
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE jobs SET progress_current = ?, progress_total = ?, current_step = ?,
                    updated_at = ? WHERE id = ?
                """,
                (current, total, step, timestamp, job_id),
            )
        if result.rowcount != 1:
            raise JobNotFoundError(job_id)
        return self.get_job(job_id)

    def ensure_chunk(
        self,
        job_id: str,
        *,
        kind: JobKind,
        ordinal: int,
        idempotency_key: str,
        input_payload: dict[str, object],
        now: datetime | None = None,
    ) -> tuple[JobChunk, bool]:
        timestamp = _now(now).isoformat()
        input_json = _canonical_json(input_payload)
        chunk_id = str(uuid4())
        with self.database.connect() as connection:
            result = connection.execute(
                """
                INSERT INTO job_chunks (
                    id, job_id, kind, ordinal, state, idempotency_key,
                    input_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, idempotency_key) DO NOTHING
                """,
                (
                    chunk_id,
                    job_id,
                    kind.value,
                    ordinal,
                    ChunkState.QUEUED.value,
                    idempotency_key,
                    input_json,
                    timestamp,
                    timestamp,
                ),
            )
            created = result.rowcount == 1
            row = connection.execute(
                "SELECT * FROM job_chunks WHERE job_id = ? AND idempotency_key = ?",
                (job_id, idempotency_key),
            ).fetchone()
            if row is not None and (
                row["input_json"] != input_json
                or int(row["ordinal"]) != ordinal
                or row["kind"] != kind.value
            ):
                raise JobIdempotencyConflictError(
                    "同一任务块幂等键对应了不同输入"
                )
        if row is None:
            raise JobNotFoundError(chunk_id)
        return self._chunk(row), created

    def load_chunk_input(self, chunk_id: str) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT input_json FROM job_chunks WHERE id = ?", (chunk_id,)
            ).fetchone()
        if row is None:
            raise JobNotFoundError(chunk_id)
        loaded = json.loads(row["input_json"])
        if not isinstance(loaded, dict):
            raise TypeError("任务块输入不是对象")
        return loaded

    def list_chunks(self, job_id: str) -> list[JobChunk]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_chunks WHERE job_id = ? ORDER BY ordinal, id",
                (job_id,),
            ).fetchall()
        return [self._chunk(row) for row in rows]

    def transition_chunk(
        self,
        chunk_id: str,
        target: ChunkState,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> JobChunk:
        legal: dict[ChunkState, set[ChunkState]] = {
            ChunkState.QUEUED: {ChunkState.RUNNING, ChunkState.CANCELLED},
            ChunkState.RUNNING: {
                ChunkState.SUCCEEDED,
                ChunkState.FAILED,
                ChunkState.INTERRUPTED,
                ChunkState.CANCELLED,
            },
            ChunkState.SUCCEEDED: set(),
            ChunkState.FAILED: {ChunkState.QUEUED, ChunkState.CANCELLED},
            ChunkState.INTERRUPTED: {ChunkState.QUEUED, ChunkState.CANCELLED},
            ChunkState.CANCELLED: {ChunkState.QUEUED},
        }
        timestamp = _now(now).isoformat()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_chunks WHERE id = ?", (chunk_id,)
            ).fetchone()
            if row is None:
                raise JobNotFoundError(chunk_id)
            current = ChunkState(row["state"])
            if target not in legal[current]:
                raise ValueError(f"illegal chunk transition: {current.value} -> {target.value}")
            connection.execute(
                """
                UPDATE job_chunks SET state = ?, error_code = ?, error_message = ?,
                    updated_at = ? WHERE id = ? AND state = ?
                """,
                (
                    target.value,
                    None if target == ChunkState.QUEUED else error_code,
                    None if target == ChunkState.QUEUED else error_message,
                    timestamp,
                    chunk_id,
                    current.value,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM job_chunks WHERE id = ?", (chunk_id,)
            ).fetchone()
        if updated is None:
            raise JobNotFoundError(chunk_id)
        return self._chunk(updated)

    def start_attempt(
        self,
        job_id: str,
        *,
        provider: str,
        model: str,
        chunk_id: str | None = None,
        now: datetime | None = None,
    ) -> JobAttempt:
        timestamp = _now(now).isoformat()
        attempt_id = str(uuid4())
        with self.database.connect() as connection:
            ordinal = int(connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 FROM job_attempts WHERE job_id = ?",
                (job_id,),
            ).fetchone()[0])
            connection.execute(
                """
                INSERT INTO job_attempts (
                    id, job_id, chunk_id, ordinal, state, provider, model, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    job_id,
                    chunk_id,
                    ordinal,
                    AttemptState.RUNNING.value,
                    provider,
                    model,
                    timestamp,
                ),
            )
            if chunk_id is not None:
                connection.execute(
                    "UPDATE job_chunks SET attempt_count = attempt_count + 1, updated_at = ? WHERE id = ?",
                    (timestamp, chunk_id),
                )
            row = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        if row is None:
            raise JobNotFoundError(attempt_id)
        return self._attempt(row)

    def finish_attempt(
        self,
        attempt_id: str,
        state: AttemptState,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> JobAttempt:
        if state == AttemptState.RUNNING:
            raise ValueError("attempt must finish in a terminal state")
        timestamp = _now(now).isoformat()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
            if row is None:
                raise JobNotFoundError(attempt_id)
            result = connection.execute(
                """
                UPDATE job_attempts SET state = ?, input_tokens = ?, output_tokens = ?,
                    error_code = ?, error_message = ?, completed_at = ?
                WHERE id = ? AND state = ?
                """,
                (
                    state.value,
                    input_tokens,
                    output_tokens,
                    error_code,
                    error_message,
                    timestamp,
                    attempt_id,
                    AttemptState.RUNNING.value,
                ),
            )
            if result.rowcount == 1:
                connection.execute(
                    """
                    UPDATE jobs SET completed_calls = completed_calls + 1, updated_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, row["job_id"]),
                )
            updated = connection.execute(
                "SELECT * FROM job_attempts WHERE id = ?", (attempt_id,)
            ).fetchone()
        if updated is None:
            raise JobNotFoundError(attempt_id)
        return self._attempt(updated)

    def fail_open_attempts(
        self,
        job_id: str,
        *,
        error_code: str,
        error_message: str,
        now: datetime | None = None,
    ) -> int:
        timestamp = _now(now).isoformat()
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM job_attempts WHERE job_id = ? AND state = ?",
                (job_id, AttemptState.RUNNING.value),
            ).fetchall()
            if not rows:
                return 0
            connection.execute(
                """
                UPDATE job_attempts SET state = ?, error_code = ?, error_message = ?,
                    completed_at = ? WHERE job_id = ? AND state = ?
                """,
                (
                    AttemptState.FAILED.value,
                    error_code,
                    error_message,
                    timestamp,
                    job_id,
                    AttemptState.RUNNING.value,
                ),
            )
            connection.execute(
                """
                UPDATE jobs SET completed_calls = completed_calls + ?, updated_at = ?
                WHERE id = ?
                """,
                (len(rows), timestamp, job_id),
            )
        return len(rows)

    def put_artifact(
        self,
        job_id: str,
        *,
        kind: str,
        artifact_key: str,
        payload: str,
        content_type: str,
        provider: str,
        model: str,
        chunk_id: str | None = None,
        metadata: dict[str, object] | None = None,
        now: datetime | None = None,
    ) -> tuple[JobArtifactContent, bool]:
        timestamp = _now(now).isoformat()
        digest = sha256(payload.encode("utf-8")).hexdigest()
        artifact_id = str(uuid4())
        metadata_json = _canonical_json(metadata or {})
        with self.database.connect() as connection:
            result = connection.execute(
                """
                INSERT INTO job_artifacts (
                    id, job_id, chunk_id, kind, artifact_key, content_type, payload,
                    payload_sha256, metadata_json, provider, model, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, artifact_key) DO NOTHING
                """,
                (
                    artifact_id,
                    job_id,
                    chunk_id,
                    kind,
                    artifact_key,
                    content_type,
                    payload,
                    digest,
                    metadata_json,
                    provider,
                    model,
                    timestamp,
                ),
            )
            created = result.rowcount == 1
            row = connection.execute(
                "SELECT * FROM job_artifacts WHERE job_id = ? AND artifact_key = ?",
                (job_id, artifact_key),
            ).fetchone()
            if row is not None and (
                row["payload_sha256"] != digest
                or row["kind"] != kind
                or row["content_type"] != content_type
            ):
                raise ArtifactConflictError("不可变任务产物键对应了不同内容")
        if row is None:
            raise JobNotFoundError(artifact_id)
        return self._artifact_content(row), created

    def get_artifact(self, artifact_id: str) -> JobArtifactContent:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise JobNotFoundError(artifact_id)
        return self._artifact_content(row)

    def find_artifact(
        self,
        job_id: str,
        artifact_key: str,
    ) -> JobArtifactContent | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM job_artifacts WHERE job_id = ? AND artifact_key = ?",
                (job_id, artifact_key),
            ).fetchone()
        return self._artifact_content(row) if row is not None else None

    @staticmethod
    def _append_event(
        connection: Connection,
        job_id: str,
        event_type: str,
        from_state: JobState | None,
        to_state: JobState | None,
        detail: dict[str, object],
        timestamp: str,
    ) -> None:
        sequence = int(connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM job_events WHERE job_id = ?",
            (job_id,),
        ).fetchone()[0])
        connection.execute(
            """
            INSERT INTO job_events (
                id, job_id, sequence, event_type, from_state, to_state, detail_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                job_id,
                sequence,
                event_type,
                from_state.value if from_state else None,
                to_state.value if to_state else None,
                _canonical_json(detail),
                timestamp,
            ),
        )

    @staticmethod
    def _job(row: Row) -> Job:
        return Job.model_validate(dict(row))

    @staticmethod
    def _chunk(row: Row) -> JobChunk:
        return JobChunk.model_validate(dict(row))

    @staticmethod
    def _attempt(row: Row) -> JobAttempt:
        return JobAttempt.model_validate(dict(row))

    @staticmethod
    def _artifact(row: Row) -> JobArtifact:
        return JobArtifact.model_validate({
            **dict(row),
            "metadata": json.loads(row["metadata_json"]),
        })

    @classmethod
    def _artifact_content(cls, row: Row) -> JobArtifactContent:
        return JobArtifactContent.model_validate({
            **cls._artifact(row).model_dump(mode="json"),
            "payload": row["payload"],
        })

    @staticmethod
    def _event(row: Row) -> JobEvent:
        return JobEvent.model_validate({
            **dict(row),
            "detail": json.loads(row["detail_json"]),
        })
