from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import Database
from app.jobs import (
    ArtifactConflictError,
    AttemptState,
    JobKind,
    JobRepository,
    JobRuntime,
    JobState,
)
from app.jobs.models import ChunkState
from app.jobs.runtime import JobCancellationRequested, JobExecutionContext
from app.jobs.state_machine import (
    LEGAL_JOB_TRANSITIONS,
    InvalidJobTransitionError,
    require_job_transition,
)
from app.main import create_app
from app.models import CreateProjectRequest, Genre
from app.repository import ProjectRepository


@pytest.fixture
def job_setup(tmp_path: Path) -> tuple[Database, JobRepository, str, str]:
    database = Database(tmp_path / "mozhou.db")
    database.initialize()
    workspace = ProjectRepository(database).create_project(
        CreateProjectRequest(
            title="持久任务测试",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    return database, JobRepository(database), workspace.project.id, workspace.chapters[0].id


def test_job_state_machine_accepts_only_the_frozen_transitions() -> None:
    for current in JobState:
        for target in JobState:
            if target in LEGAL_JOB_TRANSITIONS[current]:
                require_job_transition(current, target)
            else:
                with pytest.raises(InvalidJobTransitionError):
                    require_job_transition(current, target)


def test_repeated_job_submission_returns_the_same_job(
    job_setup: tuple[Database, JobRepository, str, str],
) -> None:
    _, jobs, project_id, chapter_id = job_setup
    arguments = {
        "project_id": project_id,
        "chapter_id": chapter_id,
        "kind": JobKind.CHAPTER_DRAFT,
        "idempotency_key": "chapter-1-revision-0",
        "input_payload": {"expected_revision": 0},
        "provider": "demo",
        "model": "replay-v1",
        "progress_total": 1,
        "estimated_calls": 1,
    }

    first, first_created = jobs.create_job(**arguments)
    second, second_created = jobs.create_job(**arguments)

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert len(jobs.get_job_detail(first.id).events) == 1


def test_artifacts_are_immutable_and_idempotent(
    job_setup: tuple[Database, JobRepository, str, str],
) -> None:
    _, jobs, project_id, _ = job_setup
    job, _ = jobs.create_job(
        project_id=project_id,
        kind=JobKind.REFERENCE_FUSION,
        idempotency_key="fusion-1",
        input_payload={"segments": ["a", "b"]},
        provider="openai",
        model="test-model",
    )

    first, first_created = jobs.put_artifact(
        job.id,
        kind="reference_synthesis",
        artifact_key="final",
        payload='{"era":"时代转型"}',
        content_type="application/json",
        provider="openai",
        model="test-model",
    )
    second, second_created = jobs.put_artifact(
        job.id,
        kind="reference_synthesis",
        artifact_key="final",
        payload='{"era":"时代转型"}',
        content_type="application/json",
        provider="openai",
        model="test-model",
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert jobs.get_artifact(first.id).payload == '{"era":"时代转型"}'
    with pytest.raises(ArtifactConflictError):
        jobs.put_artifact(
            job.id,
            kind="reference_synthesis",
            artifact_key="final",
            payload='{"era":"冲突内容"}',
            content_type="application/json",
            provider="openai",
            model="test-model",
        )


def test_expired_lease_interrupts_attempt_and_requeues_reusable_work(
    job_setup: tuple[Database, JobRepository, str, str],
) -> None:
    _, jobs, project_id, _ = job_setup
    started_at = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    job, _ = jobs.create_job(
        project_id=project_id,
        kind=JobKind.REFERENCE_FUSION,
        idempotency_key="recoverable-fusion",
        input_payload={"segments": ["a", "b"]},
        provider="openai",
        model="test-model",
        now=started_at,
    )
    leased = jobs.lease_next(
        "worker-before-crash",
        {JobKind.REFERENCE_FUSION},
        lease_duration=timedelta(seconds=5),
        now=started_at,
    )
    assert leased is not None
    chunk, _ = jobs.ensure_chunk(
        job.id,
        kind=JobKind.REFERENCE_SEGMENT_MAP,
        ordinal=0,
        idempotency_key="map-a-0-50000",
        input_payload={"start": 0, "end": 50_000},
        now=started_at,
    )
    jobs.transition_chunk(chunk.id, ChunkState.RUNNING, now=started_at)
    attempt = jobs.start_attempt(
        job.id,
        chunk_id=chunk.id,
        provider="openai",
        model="test-model",
        now=started_at,
    )

    recovered = jobs.recover_expired(
        now=started_at + timedelta(seconds=6),
        requeue=True,
    )

    assert [item.id for item in recovered] == [job.id]
    detail = jobs.get_job_detail(job.id)
    assert detail.state == JobState.QUEUED
    assert detail.chunks[0].state == ChunkState.QUEUED
    assert detail.attempts[0].id == attempt.id
    assert detail.attempts[0].state == AttemptState.INTERRUPTED
    assert [(event.from_state, event.to_state) for event in detail.events[-2:]] == [
        (JobState.RUNNING, JobState.INTERRUPTED),
        (JobState.INTERRUPTED, JobState.QUEUED),
    ]


def test_running_job_honours_cancel_at_the_next_checkpoint(
    job_setup: tuple[Database, JobRepository, str, str],
) -> None:
    _, jobs, project_id, _ = job_setup
    job, _ = jobs.create_job(
        project_id=project_id,
        kind=JobKind.REVIEW,
        idempotency_key="cancel-review",
        input_payload={},
        provider="demo",
        model="replay-v1",
    )
    leased = jobs.lease_next(
        "cancel-worker",
        {JobKind.REVIEW},
        lease_duration=timedelta(minutes=1),
    )
    assert leased is not None

    requested = jobs.request_cancel(job.id)
    context = JobExecutionContext(jobs, job.id, "cancel-worker", timedelta(minutes=1))

    assert requested.state == JobState.PAUSE_REQUESTED
    with pytest.raises(JobCancellationRequested):
        context.checkpoint()


def test_runtime_persists_progress_artifact_attempt_and_completion(
    job_setup: tuple[Database, JobRepository, str, str],
) -> None:
    _, jobs, project_id, _ = job_setup
    job, _ = jobs.create_job(
        project_id=project_id,
        kind=JobKind.REVIEW,
        idempotency_key="runtime-review",
        input_payload={"question": "是否连续"},
        provider="demo",
        model="replay-v1",
        progress_total=1,
        estimated_calls=1,
    )

    def handle(context: JobExecutionContext, leased_job: object) -> None:
        del leased_job
        context.checkpoint()
        attempt = jobs.start_attempt(
            job.id,
            provider="demo",
            model="replay-v1",
        )
        jobs.put_artifact(
            job.id,
            kind="review_result",
            artifact_key="final",
            payload="无阻断问题",
            content_type="text/plain",
            provider="demo",
            model="replay-v1",
        )
        jobs.finish_attempt(attempt.id, AttemptState.SUCCEEDED)
        jobs.update_progress(job.id, current=1, total=1, step="审校完成")

    runtime = JobRuntime(jobs, {JobKind.REVIEW: handle})

    assert runtime.run_once() is True
    detail = jobs.get_job_detail(job.id)
    assert detail.state == JobState.SUCCEEDED
    assert detail.progress_current == detail.progress_total == 1
    assert detail.completed_calls == 1
    assert [artifact.kind for artifact in detail.artifacts] == ["review_result"]
    assert detail.attempts[0].state == AttemptState.SUCCEEDED


def test_lease_prevents_two_workers_from_running_the_same_job(
    job_setup: tuple[Database, JobRepository, str, str],
) -> None:
    database, jobs, project_id, _ = job_setup
    jobs.create_job(
        project_id=project_id,
        kind=JobKind.REVIEW,
        idempotency_key="single-lease",
        input_payload={},
        provider="demo",
        model="replay-v1",
    )

    first = jobs.lease_next(
        "worker-one",
        {JobKind.REVIEW},
        lease_duration=timedelta(minutes=1),
    )
    second = JobRepository(database).lease_next(
        "worker-two",
        {JobKind.REVIEW},
        lease_duration=timedelta(minutes=1),
    )

    assert first is not None
    assert second is None


def test_runtime_persists_sanitized_failure_and_closes_open_attempt(
    job_setup: tuple[Database, JobRepository, str, str],
) -> None:
    _, jobs, project_id, _ = job_setup
    job, _ = jobs.create_job(
        project_id=project_id,
        kind=JobKind.REVIEW,
        idempotency_key="failed-review",
        input_payload={},
        provider="openai",
        model="test-model",
        estimated_calls=1,
    )

    def fail_after_starting_attempt(
        context: JobExecutionContext,
        leased_job: object,
    ) -> None:
        del context, leased_job
        jobs.start_attempt(job.id, provider="openai", model="test-model")
        raise RuntimeError("sensitive-provider-message")

    runtime = JobRuntime(jobs, {JobKind.REVIEW: fail_after_starting_attempt})

    assert runtime.run_once() is True
    detail = jobs.get_job_detail(job.id)
    assert detail.state == JobState.FAILED
    assert detail.error_code == "RuntimeError"
    assert detail.error_message == "任务执行失败，可重试并保留已完成结果"
    assert "sensitive" not in detail.model_dump_json()
    assert detail.attempts[0].state == AttemptState.FAILED
    assert detail.completed_calls == 1


def test_job_api_lists_details_artifacts_cancel_and_retry(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "mozhou.db")) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "任务中心接口",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        jobs: JobRepository = client.app.state.job_repository
        job, _ = jobs.create_job(
            project_id=project_id,
            kind=JobKind.REVIEW,
            idempotency_key="api-review",
            input_payload={},
            provider="demo",
            model="replay-v1",
        )
        artifact, _ = jobs.put_artifact(
            job.id,
            kind="review_result",
            artifact_key="partial-result",
            payload="已完成的局部审校结果",
            content_type="text/plain",
            provider="demo",
            model="replay-v1",
        )

        listed = client.get(f"/api/projects/{project_id}/jobs")
        detail = client.get(f"/api/jobs/{job.id}")
        loaded_artifact = client.get(f"/api/job-artifacts/{artifact.id}")
        cancelled = client.post(f"/api/jobs/{job.id}/cancel")
        retried = client.post(f"/api/jobs/{job.id}/retry")

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [job.id]
    assert detail.status_code == 200
    assert detail.json()["events"][0]["event_type"] == "created"
    assert detail.json()["artifacts"][0]["payload_sha256"] == artifact.payload_sha256
    assert "payload" not in detail.json()["artifacts"][0]
    assert loaded_artifact.json()["payload"] == "已完成的局部审校结果"
    assert cancelled.json()["state"] == "cancelled"
    assert retried.json()["state"] == "queued"
