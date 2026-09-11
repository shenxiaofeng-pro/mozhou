import json
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from app.ai import AiGateway, AiGatewayManager, AiProviderError
from app.database import Database
from app.jobs import JobKind, JobRepository, JobRuntime, JobState
from app.models import AiProvider, AiStatus, CreateProjectRequest, Genre
from app.providers.models import AiErrorCategory
from app.providers.repository import ModelProfileRepository
from app.repository import ProjectRepository, now_iso
from app.sandbox import (
    CreateSandboxBranchRequest,
    CreateSandboxRunRequest,
    CreateSandboxSnapshotRequest,
    NarrativeSandboxService,
    SandboxAiActionDraft,
    SandboxAiRoundDraft,
)
from app.sandbox_ai import SandboxAiService, SubmitSandboxAiRoundRequest


class FakeSandboxGateway:
    def __init__(
        self,
        profile_id: str,
        proposal: SandboxAiRoundDraft,
        *,
        failure: AiProviderError | None = None,
    ) -> None:
        self.profile_id = profile_id
        self.proposal = proposal
        self.failure = failure
        self.calls = 0

    def status(self) -> AiStatus:
        return AiStatus(
            configured=True,
            provider=AiProvider.OPENAI_COMPATIBLE,
            model="fake-sandbox-model",
            key_source="test",
            profile_id=self.profile_id,
            profile_name="测试沙盘线路",
        )

    def propose_sandbox_round(self, context_text: str) -> SandboxAiRoundDraft:
        self.calls += 1
        assert '"security_boundary"' in context_text
        if self.failure is not None:
            raise self.failure
        return self.proposal


def _proposal(*, invalid: bool = False) -> SandboxAiRoundDraft:
    return SandboxAiRoundDraft(
        actions=[
            SandboxAiActionDraft(
                actor_id="new_company",
                action_kind="trade",
                target_actor_id="incumbent",
                location="南平",
                required_knowledge=["不存在的内幕"] if invalid else ["潜在客户痛点"],
                motive="用首笔订单验证现金流，同时试探龙头的底线。",
                intended_consequence="若交付成功，供应商会重新评估主角团队的信用。",
            ),
            *(
                [
                    SandboxAiActionDraft(
                        actor_id="invented_actor",
                        action_kind="observe",
                        location="南平",
                        motive="凭空出现。",
                        intended_consequence="不应进入状态。",
                    )
                ]
                if invalid
                else []
            ),
        ],
        round_assumption="竞争者会关注首单，但尚未掌握主角的全部计划。",
    )


def _setup(
    tmp_path: Path,
    proposal: SandboxAiRoundDraft | None = None,
    *,
    failure: AiProviderError | None = None,
) -> tuple[Database, NarrativeSandboxService, SandboxAiService, JobRepository, FakeSandboxGateway, str]:
    database = Database(tmp_path / "mozhou.db")
    database.initialize()
    project = ProjectRepository(database).create_project(
        CreateProjectRequest(
            title="南平商路",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1992,
            rebirth_location="南平",
            chapter_target_words=3000,
            safety_buffer_chapters=3,
        )
    )
    sandbox = NarrativeSandboxService(database)
    snapshot = sandbox.create_snapshot(
        project.project.id,
        CreateSandboxSnapshotRequest(label="都市快照", template_id="urban-business"),
    )
    branch = sandbox.create_branch(
        snapshot.id,
        CreateSandboxBranchRequest(label="首单分支", variables={"竞争者降价": True}),
    )
    run = sandbox.create_run(
        branch.id,
        CreateSandboxRunRequest(
            requested_rounds=3,
            action_budget=15,
            execution_mode="ai",
        ),
    )
    profile_id = str(uuid4())
    timestamp = now_iso()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO ai_provider_profiles (
                id, name, provider, base_url, model, capabilities_json,
                input_cost_microusd_per_million,
                output_cost_microusd_per_million,
                revision, created_at, updated_at
            ) VALUES (?, '测试沙盘线路', 'openai_compatible', 'http://127.0.0.1:11434/v1',
                      'fake-sandbox-model', ?, 1000000, 1000000, 0, ?, ?)
            """,
            (
                profile_id,
                json.dumps({"structured_output": True, "streaming": False, "server_cancellation": False, "usage": True}),
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            "INSERT INTO ai_task_defaults (task_type, profile_id, revision, updated_at) "
            "VALUES ('sandbox', ?, 0, ?)",
            (profile_id, timestamp),
        )
    gateway = FakeSandboxGateway(profile_id, proposal or _proposal(), failure=failure)
    jobs = JobRepository(database)
    service = SandboxAiService(
        sandbox,
        jobs,
        AiGatewayManager(cast(AiGateway, gateway)),
        ModelProfileRepository(database),
    )
    return database, sandbox, service, jobs, gateway, run.id


def _confirmed(preview_state: str, *, max_cost: int | None = None) -> SubmitSandboxAiRoundRequest:
    return SubmitSandboxAiRoundRequest(
        expected_state_sha256=preview_state,
        confirm_external_processing=True,
        max_estimated_cost_microusd=max_cost,
    )


def test_ai_sandbox_preview_confirmation_cost_and_idempotency_make_zero_early_calls(
    tmp_path: Path,
) -> None:
    _database, _sandbox, service, _jobs, gateway, run_id = _setup(tmp_path)

    preview = service.preview(run_id)
    assert preview.actor_count == 5
    assert preview.estimated_cost_microusd is not None
    assert gateway.calls == 0

    with pytest.raises(ValueError, match="external_processing_not_confirmed"):
        service.submit(
            run_id,
            SubmitSandboxAiRoundRequest(expected_state_sha256=preview.state_sha256),
        )
    with pytest.raises(ValueError, match="estimated_cost_exceeds_limit"):
        service.submit(
            run_id,
            _confirmed(
                preview.state_sha256,
                max_cost=preview.estimated_cost_microusd - 1,
            ),
        )
    first = service.submit(
        run_id,
        _confirmed(preview.state_sha256, max_cost=preview.estimated_cost_microusd),
    )
    second = service.submit(
        run_id,
        _confirmed(preview.state_sha256, max_cost=preview.estimated_cost_microusd),
    )

    assert first.id == second.id
    assert first.kind == JobKind.SANDBOX_AI_ROUND
    assert gateway.calls == 0


def test_ai_sandbox_rules_reject_illegal_actions_and_fill_missing_actors(
    tmp_path: Path,
) -> None:
    database, sandbox, service, jobs, gateway, run_id = _setup(
        tmp_path, _proposal(invalid=True)
    )
    preview = service.preview(run_id)
    with database.connect() as connection:
        chapter_versions_before = connection.execute(
            "SELECT COUNT(*) FROM chapter_versions"
        ).fetchone()[0]
    job = service.submit(run_id, _confirmed(preview.state_sha256))
    runtime = JobRuntime(jobs, {JobKind.SANDBOX_AI_ROUND: service.handle})

    assert runtime.run_once() is True
    finished = jobs.get_job(job.id)
    run = sandbox.get_run(run_id)
    round_item = run.rounds[0]

    assert finished.state == JobState.SUCCEEDED
    assert gateway.calls == 1
    assert round_item.origin == "ai"
    assert len(round_item.actions) == 5
    assert {item["reason"] for item in round_item.rejected_proposals} >= {
        "未知角色",
        "主角团队不知道“不存在的内幕”",
        "模型未为该角色提供行动",
    }
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM story_facts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0] == 0
        assert (
            connection.execute("SELECT COUNT(*) FROM chapter_versions").fetchone()[0]
            == chapter_versions_before
        )


def test_ai_sandbox_reuses_paid_artifact_after_retry_without_calling_model(
    tmp_path: Path,
) -> None:
    _database, sandbox, service, jobs, gateway, run_id = _setup(tmp_path)
    preview = service.preview(run_id)
    job = service.submit(run_id, _confirmed(preview.state_sha256))
    jobs.put_artifact(
        job.id,
        kind="sandbox_ai_proposal",
        artifact_key="sandbox_ai_proposal",
        payload=_proposal().model_dump_json(),
        content_type="application/json",
        provider=job.provider,
        provider_profile_id=job.provider_profile_id,
        model=job.model,
    )

    runtime = JobRuntime(jobs, {JobKind.SANDBOX_AI_ROUND: service.handle})
    assert runtime.run_once() is True

    assert gateway.calls == 0
    assert jobs.get_job(job.id).state == JobState.SUCCEEDED
    assert sandbox.get_run(run_id).rounds[0].job_id == job.id


def test_ai_sandbox_cancelled_job_and_provider_failure_never_write_round(
    tmp_path: Path,
) -> None:
    _database, sandbox, service, jobs, gateway, run_id = _setup(tmp_path / "cancel")
    preview = service.preview(run_id)
    cancelled = service.submit(run_id, _confirmed(preview.state_sha256))
    jobs.request_cancel(cancelled.id)
    runtime = JobRuntime(jobs, {JobKind.SANDBOX_AI_ROUND: service.handle})
    assert runtime.run_once() is False
    assert gateway.calls == 0
    assert sandbox.get_run(run_id).rounds == []

    failure = AiProviderError(
        "invalid",
        category=AiErrorCategory.INVALID_RESPONSE,
        safe_message="模型返回格式无效",
        retryable=True,
    )
    _db2, sandbox2, service2, jobs2, gateway2, run2 = _setup(
        tmp_path / "failure", failure=failure
    )
    preview2 = service2.preview(run2)
    failed = service2.submit(run2, _confirmed(preview2.state_sha256))
    assert JobRuntime(jobs2, {JobKind.SANDBOX_AI_ROUND: service2.handle}).run_once()

    assert gateway2.calls == 1
    assert jobs2.get_job(failed.id).state == JobState.FAILED
    assert sandbox2.get_run(run2).rounds == []


@pytest.mark.parametrize(
    "originality_status",
    ["needs_check", "review_required", "blocked"],
)
def test_ai_sandbox_active_unpassed_gate_blocks_before_model_call(
    tmp_path: Path,
    originality_status: str,
) -> None:
    database, _sandbox, service, jobs, gateway, run_id = _setup(tmp_path)
    project_id = service._project_id_for_run(run_id)
    pattern_id = str(uuid4())
    application_id = str(uuid4())
    timestamp = now_iso()
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO reference_pattern_cards (
                id, project_id, selected_segment_ids_json, author_focus,
                proposal_json, provider, model, created_at
            ) VALUES (?, ?, '[]', '', '{}', 'test', 'test', ?)
            """,
            (pattern_id, project_id, timestamp),
        )
        connection.execute(
            """
            INSERT INTO reference_pattern_applications (
                id, project_id, pattern_card_id, selected_dimensions_json,
                dimensions_json, relationship_recomposition, application_note,
                blueprint_json, originality_status, risk_level, latest_report_id,
                threshold_version, revision, created_at, updated_at
            ) VALUES (?, ?, ?, '[]', '{}', '重组关系', '', '{}',
                      ?, 'high', NULL, 'scene-plot-graph-v1', 0, ?, ?)
            """,
            (
                application_id,
                project_id,
                pattern_id,
                originality_status,
                timestamp,
                timestamp,
            ),
        )

    with pytest.raises(ValueError, match="originality_gate_blocked"):
        service.preview(run_id)
    assert gateway.calls == 0

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE reference_pattern_applications
            SET lifecycle_state = 'archived', lifecycle_revision = 1
            WHERE id = ?
            """,
            (application_id,),
        )

    preview = service.preview(run_id)
    assert preview.run_id == run_id
    assert gateway.calls == 0

    queued = service.submit(run_id, _confirmed(preview.state_sha256))
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE reference_pattern_applications
            SET lifecycle_state = 'active', lifecycle_revision = 2
            WHERE id = ?
            """,
            (application_id,),
        )
    runtime = JobRuntime(jobs, {JobKind.SANDBOX_AI_ROUND: service.handle})
    assert runtime.run_once()
    failed = jobs.get_job(queued.id)
    assert failed.state == JobState.FAILED
    assert failed.error_code == "originality_gate_blocked"
    assert gateway.calls == 0
