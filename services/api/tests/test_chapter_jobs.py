from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from app.ai import AiGateway, AiGatewayManager, OpenAiGateway
from app.chapter_jobs import ChapterJobService
from app.creative_safety import CreativeSafetyProvenance
from app.database import Database
from app.jobs.models import JobKind, JobState
from app.jobs.repository import JobRepository
from app.jobs.runtime import JobRuntime
from app.main import create_app
from app.models import (
    AiChapterBriefProposal,
    AiChapterBriefRequest,
    AiDraftRequest,
    AiProvider,
    AiStatus,
    Chapter,
    CreateProjectRequest,
    CreateStoryEntityRequest,
    GenerationRun,
    Genre,
    ReferenceBookAnalysis,
    ReferenceChunkAnalysis,
    ReferenceSynthesisProposal,
    StoryEntityKind,
    UpdateChapterBriefRequest,
    Workspace,
)
from app.providers import (
    AiErrorCategory,
    AiTaskType,
    CreateModelProfileRequest,
    ModelProfile,
    ModelProfileRepository,
    ProviderAdapterConfig,
    ProviderCallError,
    ProviderResult,
    ProviderUsage,
    UpdateAiTaskDefaultRequest,
)
from app.providers.models import ModelCapabilities, ProviderKind
from app.reference_lab import ReferenceAnalysisInput
from app.repository import ProjectRepository


class MutableChapterSafetyGate:
    def __init__(self, current: CreativeSafetyProvenance) -> None:
        self.current = current

    def require_creative_safety(
        self,
        project_id: str,
        expected: CreativeSafetyProvenance | None = None,
    ) -> CreativeSafetyProvenance:
        assert project_id == self.current.project_id
        if expected is not None and expected != self.current:
            raise ValueError("creative_safety_changed")
        return self.current


class RecoverableChapterGateway:
    def __init__(self, *, draft_failure: Exception | None = None) -> None:
        self.brief_calls = 0
        self.draft_calls = 0
        self.draft_failure = draft_failure

    def status(self) -> AiStatus:
        return AiStatus(
            configured=True,
            provider=AiProvider.OPENAI,
            model="recoverable-chapter-test",
            key_source="test",
        )

    def propose_brief(
        self,
        workspace: Workspace,
        chapter: Chapter,
        author_intent: str,
    ) -> AiChapterBriefProposal:
        del workspace, chapter, author_intent
        self.brief_calls += 1
        return AiChapterBriefProposal(
            title="第一章 名单之前",
            reader_promise="主角第一次改变家庭命运",
            opening_hook="停产名单比记忆中提前贴出",
            state_change="主角让父亲避开首轮裁员",
            emotional_payoff="父亲保住岗位却开始怀疑儿子",
            ending_cliffhanger="厂长拿出一张不该存在的旧照片",
            why_this_works="信息差立即转化为行动和家庭回报。",
            risk_notes=["厂办流程需要现实资料校验"],
        )

    def draft_chapter(
        self,
        workspace: Workspace,
        chapter: Chapter,
        author_intent: str,
    ) -> str:
        del workspace, chapter, author_intent
        self.draft_calls += 1
        if self.draft_failure is not None:
            failure, self.draft_failure = self.draft_failure, None
            raise failure
        return "一九九八年的梅山坡还没有后来那排高楼。" * 30

    def synthesize_references(
        self,
        segments: list[ReferenceAnalysisInput],
        author_focus: str,
    ) -> ReferenceSynthesisProposal:
        raise AssertionError("not used")

    def analyze_reference_chunk(
        self,
        segment: ReferenceAnalysisInput,
        chunk_start: int,
        chunk_end: int,
    ) -> ReferenceChunkAnalysis:
        raise AssertionError("not used")

    def reduce_reference_book(
        self,
        work_id: str,
        work_title: str,
        mapped_analyses: list[dict[str, object]],
        author_focus: str,
    ) -> ReferenceBookAnalysis:
        raise AssertionError("not used")

    def fuse_reference_books(
        self,
        book_analyses: list[ReferenceBookAnalysis],
        allowed_source_segment_ids: list[str],
        author_focus: str,
    ) -> ReferenceSynthesisProposal:
        raise AssertionError("not used")


class UsageFixtureAdapter:
    config = ProviderAdapterConfig(
        provider=ProviderKind.OPENAI,
        base_url="https://api.openai.com/v1",
        model="usage-fixture",
        capabilities=ModelCapabilities(
            structured_output=True,
            usage=True,
        ),
    )

    def __init__(self, *, failure: ProviderCallError | None = None) -> None:
        self.failure = failure
        self.structured_inputs: list[str] = []
        self.text_inputs: list[str] = []

    def generate_text(
        self,
        *,
        instructions: str,
        input_text: str,
        max_output_tokens: int | None = None,
    ) -> ProviderResult[str]:
        del instructions, max_output_tokens
        self.text_inputs.append(input_text)
        return ProviderResult(
            output="一九九八年的梅山坡还没有后来那排高楼。" * 30,
            usage=ProviderUsage(input_tokens=500, output_tokens=800),
            duration_ms=420,
        )

    def generate_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        output_model: type[AiChapterBriefProposal],
    ) -> ProviderResult[AiChapterBriefProposal]:
        del instructions, output_model
        self.structured_inputs.append(input_text)
        if self.failure is not None:
            raise self.failure
        return ProviderResult(
            output=AiChapterBriefProposal(
                title="第一章 名单之前",
                reader_promise="主角第一次改变家庭命运",
                opening_hook="停产名单比记忆中提前贴出",
                state_change="主角让父亲避开首轮裁员",
                emotional_payoff="父亲保住岗位却开始怀疑儿子",
                ending_cliffhanger="厂长拿出一张不该存在的旧照片",
                why_this_works="信息差立即转化为行动和家庭回报。",
                risk_notes=[],
            ),
            usage=ProviderUsage(input_tokens=120, output_tokens=80),
            duration_ms=250,
        )


class CancellableStreamingAdapter(UsageFixtureAdapter):
    config = ProviderAdapterConfig(
        provider=ProviderKind.OPENAI,
        base_url="https://api.openai.com/v1",
        model="streaming-fixture",
        capabilities=ModelCapabilities(streaming=True, usage=True),
    )

    def __init__(self) -> None:
        super().__init__()
        self.cancel_between_deltas: Callable[[], None] | None = None

    def generate_text_stream(
        self,
        *,
        instructions: str,
        input_text: str,
        on_delta: Callable[[str], None],
        max_output_tokens: int | None = None,
    ) -> ProviderResult[str]:
        del instructions, input_text, max_output_tokens
        first = "一九九八年的梅山坡" * 10
        second = "停产名单在风里卷起一角" * 30
        on_delta(first)
        if self.cancel_between_deltas is not None:
            self.cancel_between_deltas()
        on_delta(second)
        return ProviderResult(
            output=first + second,
            usage=ProviderUsage(input_tokens=100, output_tokens=200),
            duration_ms=300,
        )

def build_chapter_runtime(
    database_path: Path,
    gateway: AiGateway,
) -> tuple[ProjectRepository, JobRepository, ChapterJobService, JobRuntime, Chapter]:
    database = Database(database_path)
    database.initialize()
    repository = ProjectRepository(database)
    workspace = repository.create_project(CreateProjectRequest(
        title="回到九八年的南平",
        genre=Genre.URBAN_REBIRTH,
        rebirth_year=1998,
        rebirth_location="福建南平",
    ))
    jobs = JobRepository(database)
    service = ChapterJobService(repository, jobs, AiGatewayManager(gateway))
    runtime = JobRuntime(jobs, {
        JobKind.CHAPTER_BRIEF: service.handle_brief,
        JobKind.CHAPTER_DRAFT: service.handle_draft,
    })
    return repository, jobs, service, runtime, workspace.chapters[0]


def save_complete_brief(repository: ProjectRepository, chapter: Chapter) -> Chapter:
    return repository.update_chapter_brief(
        chapter.id,
        UpdateChapterBriefRequest(
            opening_hook="停产名单比记忆中提前贴出",
            state_change="主角让父亲避开首轮裁员",
            ending_cliffhanger="厂长拿出一张旧照片",
            expected_revision=chapter.revision,
        ),
    )


def test_brief_job_is_idempotent_and_keeps_saved_chapter_unchanged(tmp_path: Path) -> None:
    gateway = RecoverableChapterGateway()
    repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "brief.db",
        gateway,
    )
    request = AiChapterBriefRequest(
        expected_revision=chapter.revision,
        author_intent="让主角先用信息差救下父亲",
    )

    first = service.submit_brief(chapter.id, request)
    duplicate = service.submit_brief(chapter.id, request)
    runtime.run_once()

    result = service.get_brief_result(first.id)
    unchanged = repository.get_chapter(chapter.id)
    assert duplicate.id == first.id
    assert jobs.get_job(first.id).state == JobState.SUCCEEDED
    assert gateway.brief_calls == 1
    assert result.title == "第一章 名单之前"
    assert unchanged.opening_hook == ""


def test_chapter_attempt_records_usage_duration_and_estimated_cost(tmp_path: Path) -> None:
    gateway = OpenAiGateway(
        "unused-test-key-value-abcdefghijklmnopqrstuvwxyz",
        "usage-fixture",
        "test",
        adapter=UsageFixtureAdapter(),
        input_cost_microusd_per_million=2_500_000,
        output_cost_microusd_per_million=15_000_000,
        profile_id="profile-usage-fixture",
        profile_name="计费测试 profile",
    )
    _repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "usage.db",
        gateway,
    )
    job = service.submit_brief(
        chapter.id,
        AiChapterBriefRequest(expected_revision=chapter.revision, author_intent=""),
    )

    runtime.run_once()

    detail = jobs.get_job_detail(job.id)
    attempt = detail.attempts[0]
    assert detail.provider_profile_id == "profile-usage-fixture"
    assert attempt.provider_profile_id == "profile-usage-fixture"
    brief_artifact = next(item for item in detail.artifacts if item.kind == "chapter_brief")
    assert brief_artifact.provider_profile_id == "profile-usage-fixture"
    assert attempt.input_tokens == 120
    assert attempt.output_tokens == 80
    assert attempt.duration_ms == 250
    assert attempt.estimated_cost_microusd == 1_500


def test_queued_job_keeps_its_bound_gateway_after_active_profile_switch(tmp_path: Path) -> None:
    database = Database(tmp_path / "profile-switch.db")
    database.initialize()
    repository = ProjectRepository(database)
    workspace = repository.create_project(CreateProjectRequest(
        title="回到九八年的南平",
        genre=Genre.URBAN_REBIRTH,
        rebirth_year=1998,
        rebirth_location="福建南平",
    ))
    jobs = JobRepository(database)
    first_gateway = OpenAiGateway(
        "unused-first",
        "brief-model",
        "test",
        adapter=UsageFixtureAdapter(),
        profile_id="profile-first",
        profile_name="章纲模型",
    )
    manager = AiGatewayManager(first_gateway)
    service = ChapterJobService(repository, jobs, manager)
    runtime = JobRuntime(jobs, {JobKind.CHAPTER_BRIEF: service.handle_brief})
    job = service.submit_brief(
        workspace.chapters[0].id,
        AiChapterBriefRequest(expected_revision=0, author_intent=""),
    )
    manager.activate_profile(
        ModelProfile(
            id="profile-second",
            name="正文模型",
            provider=ProviderKind.OPENAI_COMPATIBLE,
            base_url="https://provider.test/v1",
            model="draft-model",
            capabilities=ModelCapabilities(),
            input_cost_microusd_per_million=None,
            output_cost_microusd_per_million=None,
            revision=0,
            created_at="2026-08-10T00:00:00Z",
            updated_at="2026-08-10T00:00:00Z",
        ),
        "unused-second",
        key_source="test",
    )

    runtime.run_once()

    detail = jobs.get_job_detail(job.id)
    assert detail.state == JobState.SUCCEEDED
    assert detail.provider_profile_id == "profile-first"
    brief_artifact = next(item for item in detail.artifacts if item.kind == "chapter_brief")
    assert brief_artifact.provider_profile_id == "profile-first"


def test_chapter_task_default_selects_loaded_non_active_profile(tmp_path: Path) -> None:
    database = Database(tmp_path / "task-route.db")
    database.initialize()
    repository = ProjectRepository(database)
    workspace = repository.create_project(CreateProjectRequest(
        title="回到九八年的南平",
        genre=Genre.URBAN_REBIRTH,
        rebirth_year=1998,
        rebirth_location="福建南平",
    ))
    profiles = ModelProfileRepository(database)
    brief_profile = profiles.create_profile(CreateModelProfileRequest(
        name="章纲线路",
        provider=ProviderKind.OPENAI,
        base_url="https://api.openai.com/v1",
        model="brief-model",
    ))
    active_profile = profiles.create_profile(CreateModelProfileRequest(
        name="正文线路",
        provider=ProviderKind.OPENAI_COMPATIBLE,
        base_url="https://models.example.com/v1",
        model="draft-model",
    ))
    profiles.set_task_default(
        AiTaskType.CHAPTER_BRIEF,
        UpdateAiTaskDefaultRequest(profile_id=brief_profile.id),
    )
    brief_gateway = OpenAiGateway(
        "unused-brief-key",
        brief_profile.model,
        "test",
        adapter=UsageFixtureAdapter(),
        profile_id=brief_profile.id,
        profile_name=brief_profile.name,
    )
    manager = AiGatewayManager(brief_gateway)
    manager.activate_profile(active_profile, "unused-active-key", key_source="test")
    jobs = JobRepository(database)
    service = ChapterJobService(repository, jobs, manager, profiles)
    runtime = JobRuntime(jobs, {JobKind.CHAPTER_BRIEF: service.handle_brief})

    job = service.submit_brief(
        workspace.chapters[0].id,
        AiChapterBriefRequest(expected_revision=0, author_intent=""),
    )
    runtime.run_once()

    detail = jobs.get_job_detail(job.id)
    assert manager.status().profile_id == active_profile.id
    assert detail.state == JobState.SUCCEEDED
    assert detail.provider_profile_id == brief_profile.id
    brief_artifact = next(item for item in detail.artifacts if item.kind == "chapter_brief")
    assert brief_artifact.provider_profile_id == brief_profile.id


def test_streaming_draft_honours_cancel_and_can_retry_without_partial_artifact(
    tmp_path: Path,
) -> None:
    adapter = CancellableStreamingAdapter()
    gateway = OpenAiGateway(
        "unused-streaming",
        "streaming-fixture",
        "test",
        adapter=adapter,
        profile_id="profile-streaming",
        profile_name="流式测试",
    )
    repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "stream-cancel.db",
        gateway,
    )
    chapter = save_complete_brief(repository, chapter)
    job = service.submit_draft(
        chapter.id,
        AiDraftRequest(expected_revision=chapter.revision, author_intent=""),
    )
    adapter.cancel_between_deltas = lambda: jobs.request_cancel(job.id)

    runtime.run_once()

    cancelled = jobs.get_job_detail(job.id)
    assert cancelled.state == JobState.CANCELLED
    assert cancelled.attempts[0].error_code == AiErrorCategory.CANCELLED.value
    assert [item.kind for item in cancelled.artifacts] == ["context_packet"]

    adapter.cancel_between_deltas = None
    jobs.retry_job(job.id)
    runtime.run_once()

    completed = jobs.get_job_detail(job.id)
    assert completed.state == JobState.SUCCEEDED
    assert len(completed.attempts) == 2
    assert {item.kind for item in completed.artifacts} == {"context_packet", "chapter_draft"}


def test_chapter_attempt_keeps_normalized_provider_failure_actionable(tmp_path: Path) -> None:
    provider_failure = ProviderCallError(
        AiErrorCategory.RATE_LIMIT,
        "模型服务限流，稍后可安全重试",
        retryable=True,
        duration_ms=321,
    )
    gateway = OpenAiGateway(
        "unused-test-key-value-abcdefghijklmnopqrstuvwxyz",
        "usage-fixture",
        "test",
        adapter=UsageFixtureAdapter(failure=provider_failure),
    )
    _repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "rate-limit.db",
        gateway,
    )
    job = service.submit_brief(
        chapter.id,
        AiChapterBriefRequest(expected_revision=chapter.revision, author_intent=""),
    )

    runtime.run_once()

    detail = jobs.get_job_detail(job.id)
    attempt = detail.attempts[0]
    assert detail.state == JobState.FAILED
    assert detail.error_code == "rate_limit"
    assert detail.error_message == "模型服务限流，稍后可安全重试"
    assert attempt.error_code == "rate_limit"
    assert attempt.duration_ms == 321


def test_draft_job_materializes_candidate_but_never_overwrites_body(tmp_path: Path) -> None:
    gateway = RecoverableChapterGateway()
    repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "draft.db",
        gateway,
    )
    chapter = save_complete_brief(repository, chapter)
    request = AiDraftRequest(expected_revision=chapter.revision, author_intent="")

    job = service.submit_draft(chapter.id, request)
    duplicate = service.submit_draft(chapter.id, request)
    runtime.run_once()

    candidate_run = service.get_draft_result(job.id)
    before_apply = repository.get_chapter(chapter.id)
    applied = repository.apply_generation(candidate_run.id, chapter.revision)
    assert duplicate.id == job.id
    assert jobs.get_job(job.id).state == JobState.SUCCEEDED
    assert gateway.draft_calls == 1
    assert before_apply.content == ""
    assert candidate_run.candidate_content
    assert applied.content == candidate_run.candidate_content
    assert applied.revision == chapter.revision + 1


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(ConnectionError("injected disconnect"), id="disconnect"),
        pytest.param(TimeoutError("injected timeout"), id="timeout"),
        pytest.param(RuntimeError("injected rate limit"), id="rate-limit"),
        pytest.param(ValueError("injected malformed response"), id="invalid-format"),
    ],
)
def test_failed_draft_job_retries_without_duplicate_candidate(
    tmp_path: Path,
    failure: Exception,
) -> None:
    gateway = RecoverableChapterGateway(draft_failure=failure)
    repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "retry.db",
        gateway,
    )
    chapter = save_complete_brief(repository, chapter)
    job = service.submit_draft(
        chapter.id,
        AiDraftRequest(expected_revision=chapter.revision, author_intent=""),
    )

    runtime.run_once()
    assert jobs.get_job(job.id).state == JobState.FAILED
    assert [item.kind for item in jobs.get_job_detail(job.id).artifacts] == ["context_packet"]

    jobs.retry_job(job.id)
    runtime.run_once()

    assert jobs.get_job(job.id).state == JobState.SUCCEEDED
    assert gateway.draft_calls == 2
    with repository.database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM generation_runs WHERE provider = ?",
            ("openai",),
        ).fetchone()[0]
    assert count == 1


def test_draft_artifact_survives_materialization_crash_without_second_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = RecoverableChapterGateway()
    repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "materialize.db",
        gateway,
    )
    chapter = save_complete_brief(repository, chapter)
    original = repository.materialize_generation_run
    materialize_calls = 0

    def fail_first_materialization(
        run_id: str,
        chapter_id: str,
        expected_revision: int,
        candidate_content: str,
        provider: str,
        model: str,
    ) -> GenerationRun:
        nonlocal materialize_calls
        materialize_calls += 1
        if materialize_calls == 1:
            raise RuntimeError("injected materialization crash")
        return original(
            run_id,
            chapter_id,
            expected_revision,
            candidate_content,
            provider,
            model,
        )

    monkeypatch.setattr(repository, "materialize_generation_run", fail_first_materialization)
    job = service.submit_draft(
        chapter.id,
        AiDraftRequest(expected_revision=chapter.revision, author_intent=""),
    )

    runtime.run_once()
    assert jobs.get_job(job.id).state == JobState.FAILED
    assert {item.kind for item in jobs.get_job_detail(job.id).artifacts} == {
        "context_packet",
        "chapter_draft",
    }
    calls_after_failure = gateway.draft_calls

    jobs.retry_job(job.id)
    runtime.run_once()

    assert jobs.get_job(job.id).state == JobState.SUCCEEDED
    assert gateway.draft_calls == calls_after_failure
    assert service.get_draft_result(job.id).candidate_content


def test_chapter_worker_rejects_changed_creative_safety_before_model_call(
    tmp_path: Path,
) -> None:
    gateway = RecoverableChapterGateway()
    repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "chapter-safety-drift.db",
        gateway,
    )
    chapter = save_complete_brief(repository, chapter)
    project_id = repository.get_workspace_for_chapter(chapter.id).project.id
    first = CreativeSafetyProvenance(
        project_id=project_id,
        mode="pattern_adaptation",
        fingerprint_sha256="a" * 64,
    )
    gate = MutableChapterSafetyGate(first)
    repository.set_creative_safety_gate(gate)
    job = service.submit_draft(
        chapter.id,
        AiDraftRequest(expected_revision=chapter.revision, author_intent=""),
    )
    gate.current = first.model_copy(update={"fingerprint_sha256": "b" * 64})

    assert runtime.run_once()
    failed = jobs.get_job(job.id)
    assert failed.state == JobState.FAILED
    assert failed.error_code == "creative_safety_changed"
    assert gateway.draft_calls == 0


def test_queued_job_replays_frozen_context_when_story_data_changes(tmp_path: Path) -> None:
    gateway = RecoverableChapterGateway()
    repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "context-change.db",
        gateway,
    )
    job = service.submit_brief(
        chapter.id,
        AiChapterBriefRequest(expected_revision=chapter.revision, author_intent=""),
    )
    repository.create_story_entity(
        chapter.project_id,
        CreateStoryEntityRequest(
            kind=StoryEntityKind.CHARACTER,
            name="新加入的人物",
            role="竞争者",
            goal="抢先拿下订单",
            current_state="尚未登场",
            relationship_notes="与主角无旧关系",
        ),
    )

    runtime.run_once()

    completed = jobs.get_job(job.id)
    assert completed.state == JobState.SUCCEEDED
    assert gateway.brief_calls == 1
    packet_artifact = next(
        item for item in jobs.get_job_detail(job.id).artifacts
        if item.kind == "context_packet"
    )
    assert "新加入的人物" not in jobs.get_artifact(packet_artifact.id).payload


def test_openai_adapter_consumes_exact_previewed_context_packet(tmp_path: Path) -> None:
    adapter = UsageFixtureAdapter()
    gateway = OpenAiGateway(
        "unused-context-packet",
        "context-fixture",
        "test",
        adapter=adapter,
    )
    repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "compiled-context.db",
        gateway,
    )
    request = AiChapterBriefRequest(
        expected_revision=chapter.revision,
        author_intent="先救下父亲",
        context_token_budget=8000,
    )
    preview = service.preview_brief(chapter.id, request)
    job = service.submit_brief(
        chapter.id,
        request.model_copy(update={"context_packet_id": preview.context_packet.id}),
    )
    repository.create_story_entity(
        chapter.project_id,
        CreateStoryEntityRequest(
            kind=StoryEntityKind.CHARACTER,
            name="提交后加入的人物",
            role="竞争者",
            goal="抢下订单",
            current_state="尚未登场",
            relationship_notes="",
        ),
    )

    runtime.run_once()

    assert jobs.get_job(job.id).state == JobState.SUCCEEDED
    assert adapter.structured_inputs == [preview.context_packet.rendered_context]
    assert "提交后加入的人物" not in adapter.structured_inputs[0]


def test_chapter_job_replays_frozen_context_artifact_after_archive_restore(
    tmp_path: Path,
) -> None:
    adapter = UsageFixtureAdapter()
    gateway = OpenAiGateway(
        "unused-archive-context-packet",
        "context-fixture",
        "test",
        adapter=adapter,
    )
    repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "restored-context.db",
        gateway,
    )
    request = AiChapterBriefRequest(
        expected_revision=chapter.revision,
        author_intent="先救下父亲",
        context_token_budget=8000,
    )
    preview = service.preview_brief(chapter.id, request)
    job = service.submit_brief(
        chapter.id,
        request.model_copy(update={"context_packet_id": preview.context_packet.id}),
    )
    with repository.database.connect() as connection:
        connection.execute(
            "DELETE FROM context_packets WHERE id = ?",
            (preview.context_packet.id,),
        )

    runtime.run_once()

    assert jobs.get_job(job.id).state == JobState.SUCCEEDED
    assert adapter.structured_inputs == [preview.context_packet.rendered_context]


def test_chapter_worker_repairs_a_job_leased_before_its_plan_was_persisted(
    tmp_path: Path,
) -> None:
    adapter = UsageFixtureAdapter()
    gateway = OpenAiGateway(
        "unused-incomplete-plan",
        "context-fixture",
        "test",
        adapter=adapter,
    )
    repository, jobs, service, runtime, chapter = build_chapter_runtime(
        tmp_path / "incomplete-plan.db",
        gateway,
    )
    request = AiChapterBriefRequest(
        expected_revision=chapter.revision,
        author_intent="先救下父亲",
        context_token_budget=8000,
    )
    preview = service.preview_brief(chapter.id, request)
    job = service.submit_brief(
        chapter.id,
        request.model_copy(update={"context_packet_id": preview.context_packet.id}),
    )
    with repository.database.connect() as connection:
        connection.execute("DELETE FROM job_artifacts WHERE job_id = ?", (job.id,))
        connection.execute("DELETE FROM job_chunks WHERE job_id = ?", (job.id,))

    runtime.run_once()

    detail = jobs.get_job_detail(job.id)
    assert detail.state == JobState.SUCCEEDED
    assert len(detail.chunks) == 1
    assert {item.kind for item in detail.artifacts} == {"context_packet", "chapter_brief"}
    assert adapter.structured_inputs == [preview.context_packet.rendered_context]


def test_chapter_job_api_returns_typed_results(tmp_path: Path) -> None:
    gateway = RecoverableChapterGateway()
    with TestClient(create_app(
        tmp_path / "api.db",
        ai_manager=AiGatewayManager(gateway),
    )) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "异步章节任务",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        chapter = workspace["chapters"][0]
        submitted = client.post(
            f"/api/chapters/{chapter['id']}/ai-brief-jobs",
            json={"expected_revision": 0, "author_intent": "救下父亲"},
        )
        detail = submitted.json()
        # Windows CI can spend several seconds opening SQLite connections while
        # the background worker commits its artifact. Keep this an end-state
        # assertion, but do not turn ordinary runner I/O contention into a race.
        deadline = monotonic() + 15
        while detail["state"] not in {"succeeded", "failed", "cancelled"} and monotonic() < deadline:
            sleep(0.01)
            detail = client.get(f"/api/jobs/{detail['id']}").json()
        result = client.get(f"/api/jobs/{detail['id']}/chapter-brief-result")

    assert submitted.status_code == 202
    assert detail["state"] == "succeeded", detail
    assert result.status_code == 200
    assert result.json()["title"] == "第一章 名单之前"
