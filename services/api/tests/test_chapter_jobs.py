from pathlib import Path
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from app.ai import AiGatewayManager
from app.chapter_jobs import ChapterJobService
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
from app.reference_lab import ReferenceAnalysisInput
from app.repository import ProjectRepository


class RecoverableChapterGateway:
    def __init__(self, *, fail_draft_once: bool = False) -> None:
        self.brief_calls = 0
        self.draft_calls = 0
        self.fail_draft_once = fail_draft_once

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
        if self.fail_draft_once:
            self.fail_draft_once = False
            raise TimeoutError("injected timeout")
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


def build_chapter_runtime(
    database_path: Path,
    gateway: RecoverableChapterGateway,
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


def test_failed_draft_job_retries_without_duplicate_candidate(tmp_path: Path) -> None:
    gateway = RecoverableChapterGateway(fail_draft_once=True)
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
    assert jobs.get_job_detail(job.id).artifacts == []

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
    assert len(jobs.get_job_detail(job.id).artifacts) == 1
    calls_after_failure = gateway.draft_calls

    jobs.retry_job(job.id)
    runtime.run_once()

    assert jobs.get_job(job.id).state == JobState.SUCCEEDED
    assert gateway.draft_calls == calls_after_failure
    assert service.get_draft_result(job.id).candidate_content


def test_job_rejects_changed_context_before_spending_model_call(tmp_path: Path) -> None:
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

    failed = jobs.get_job(job.id)
    assert failed.state == JobState.FAILED
    assert failed.error_code == "context_changed"
    assert gateway.brief_calls == 0


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
        deadline = monotonic() + 3
        while detail["state"] not in {"succeeded", "failed", "cancelled"} and monotonic() < deadline:
            sleep(0.01)
            detail = client.get(f"/api/jobs/{detail['id']}").json()
        result = client.get(f"/api/jobs/{detail['id']}/chapter-brief-result")

    assert submitted.status_code == 202
    assert detail["state"] == "succeeded"
    assert result.status_code == 200
    assert result.json()["title"] == "第一章 名单之前"
