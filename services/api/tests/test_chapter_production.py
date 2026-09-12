from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai import AiGatewayManager
from app.archive import ProjectArchiveService, canonical_json
from app.chapter_production.demo import DeterministicDemoChapterAdapter
from app.chapter_production.models import (
    AdoptCandidateRequest,
    AdoptionMode,
    CandidateVersionOperation,
    ChapterOutline,
    CreativeContextSnapshot,
    DraftGenerationInput,
    EditableTextSelection,
    GenerateDraftRequest,
    GenerateOutlineRequest,
    MergeCandidatesRequest,
    MergeSource,
    ModelTrace,
    OutlineGenerationInput,
    OutlineGuard,
    ReviewCandidateRequest,
    ReviewGenerationInput,
    RewriteGenerationInput,
    SubmitDraftJobRequest,
    SubmitOutlineJobRequest,
    SubmitReviewJobRequest,
    TextSelection,
)
from app.chapter_production.repository import (
    ChapterProductionConflictError,
    ChapterProductionRepository,
    LockedSelectionError,
    text_sha256,
)
from app.chapter_production.service import ChapterProductionService
from app.context import ContextRepository, CreativeContextPurpose, CreativeContextService
from app.database import Database
from app.jobs import JobKind, JobRepository, JobRuntime, JobState
from app.main import create_app
from app.models import CreateProjectRequest, Genre, UpdateChapterRequest
from app.providers import ModelProfileRepository
from app.repository import ProjectRepository


class RecordingAdapter(DeterministicDemoChapterAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[str] = []
        self.on_draft: Callable[[], None] | None = None

    @staticmethod
    def _remember(contexts: list[str], context: CreativeContextSnapshot) -> None:
        contexts.append(context.rendered_context)

    def propose_outline(self, request: OutlineGenerationInput):  # type: ignore[no-untyped-def]
        self._remember(self.contexts, request.context)
        return super().propose_outline(request)

    def draft_chapter(self, request: DraftGenerationInput):  # type: ignore[no-untyped-def]
        self._remember(self.contexts, request.context)
        if self.on_draft is not None:
            callback, self.on_draft = self.on_draft, None
            callback()
        return super().draft_chapter(request)

    def rewrite_selection(self, request: RewriteGenerationInput):  # type: ignore[no-untyped-def]
        self._remember(self.contexts, request.context)
        return super().rewrite_selection(request)

    def review_candidate(self, request: ReviewGenerationInput):  # type: ignore[no-untyped-def]
        self._remember(self.contexts, request.context)
        return super().review_candidate(request)


def _complete_outline() -> ChapterOutline:
    return ChapterOutline(
        title="第一章 名单之前",
        reader_promise="主角第一次改变家庭命运",
        opening_hook="停产名单比记忆中提前贴出",
        state_change="主角让父亲避开首轮裁员",
        emotional_payoff="父亲保住岗位却开始怀疑儿子",
        ending_cliffhanger="厂长拿出一张不该存在的旧照片",
        scene_beats=["名单提前出现", "主角抢到行动窗口", "阶段小胜暴露新代价"],
    )


def _trace(purpose: CreativeContextPurpose) -> ModelTrace:
    return ModelTrace(
        purpose=purpose,
        context_packet_id=f"packet-{purpose.value}",
        context_packet_sha256="a" * 64,
        context_dependency_fingerprint_sha256="b" * 64,
        context_compiler_version="test-v1",
        provider="test",
        model="fixture",
        prompt_version="prompt-v1",
    )


def _selection(content: str, start: int, end: int) -> TextSelection:
    return TextSelection(
        start_char=start,
        end_char=end,
        selected_text_sha256=text_sha256(content[start:end]),
    )


def _system(
    path: Path,
    *,
    content: str = "",
) -> tuple[
    Database,
    ProjectRepository,
    ChapterProductionRepository,
    ChapterProductionService,
    JobRuntime,
    RecordingAdapter,
    str,
    str,
]:
    database = Database(path)
    database.initialize()
    projects = ProjectRepository(database)
    workspace = projects.create_project(
        CreateProjectRequest(
            title="回到九八年的南平",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    chapter = workspace.chapters[0]
    if content:
        chapter = projects.update_chapter(
            chapter.id,
            UpdateChapterRequest(content=content, expected_revision=chapter.revision),
        )
    productions = ChapterProductionRepository(database)
    jobs = JobRepository(database)
    contexts = ContextRepository(database)
    creative_context = CreativeContextService(projects, contexts)
    adapter = RecordingAdapter()
    service = ChapterProductionService(
        projects,
        productions,
        jobs,
        AiGatewayManager(),
        ModelProfileRepository(database),
        contexts,
        creative_context,
        adapter=adapter,
    )
    runtime = JobRuntime(
        jobs,
        {
            JobKind.CHAPTER_BRIEF: service.handle,
            JobKind.CHAPTER_DRAFT: service.handle,
            JobKind.REVIEW: service.handle,
        },
    )
    return (
        database,
        projects,
        productions,
        service,
        runtime,
        adapter,
        workspace.project.id,
        chapter.id,
    )


def _create_ready_candidate(
    projects: ProjectRepository,
    productions: ChapterProductionRepository,
    project_id: str,
    chapter_id: str,
    *,
    content: str = "甲乙丙丁戊己庚辛",
):  # type: ignore[no-untyped-def]
    chapter = next(
        item for item in projects.get_workspace(project_id).chapters if item.id == chapter_id
    )
    production = productions.create_production(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_chapter_revision=chapter.revision,
        expected_chapter_content_sha256=text_sha256(chapter.content),
    )
    outline = productions.add_outline_candidate(
        production_id=production.id,
        outline=_complete_outline(),
        label="作者确认章纲",
        trace=_trace(CreativeContextPurpose.BRIEF),
    )
    productions.record_preflight(
        production_id=production.id,
        outline_candidate_id=outline.id,
        expected_outline_revision=outline.current_version.revision,
        expected_outline_content_sha256=outline.current_version.content_sha256,
        checks={
            field: True
            for field in (
                "reader_promise",
                "opening_hook",
                "state_change",
                "emotional_payoff",
                "ending_cliffhanger",
            )
        },
        missing_fields=[],
    )
    candidate = productions.create_draft_candidate(
        production_id=production.id,
        outline_candidate_id=outline.id,
        expected_outline_revision=outline.current_version.revision,
        expected_outline_content_sha256=outline.current_version.content_sha256,
        content=content,
        label="AI 正文候选",
        trace=_trace(CreativeContextPurpose.DRAFT),
    )
    return production, outline, candidate, chapter


def test_repository_workflow_is_versioned_guarded_and_keeps_official_text_isolated(
    tmp_path: Path,
) -> None:
    database, projects, productions, *_rest, project_id, chapter_id = _system(
        tmp_path / "repository.db"
    )
    chapter = projects.get_workspace(project_id).chapters[0]
    production = productions.create_production(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_chapter_revision=chapter.revision,
        expected_chapter_content_sha256=text_sha256(chapter.content),
    )
    replay = productions.create_production(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_chapter_revision=chapter.revision,
        expected_chapter_content_sha256=text_sha256(chapter.content),
    )
    assert replay.id == production.id

    outline = productions.add_outline_candidate(
        production_id=production.id,
        outline=ChapterOutline(opening_hook="名单提前贴出"),
        label="待补章纲",
        trace=_trace(CreativeContextPurpose.BRIEF),
    )
    blocked = productions.record_preflight(
        production_id=production.id,
        outline_candidate_id=outline.id,
        expected_outline_revision=0,
        expected_outline_content_sha256=outline.current_version.content_sha256,
        checks={
            "reader_promise": False,
            "opening_hook": True,
            "state_change": False,
            "emotional_payoff": False,
            "ending_cliffhanger": False,
        },
        missing_fields=[
            "reader_promise",
            "state_change",
            "emotional_payoff",
            "ending_cliffhanger",
        ],
    )
    assert blocked.passed is False
    with pytest.raises(ChapterProductionConflictError, match="preflight_not_passed"):
        productions.create_draft_candidate(
            production_id=production.id,
            outline_candidate_id=outline.id,
            expected_outline_revision=0,
            expected_outline_content_sha256=outline.current_version.content_sha256,
            content="不应生成",
            label="被拦截候选",
            trace=_trace(CreativeContextPurpose.DRAFT),
        )

    outline = productions.edit_outline_candidate(
        production_id=production.id,
        candidate_id=outline.id,
        expected_outline_revision=outline.current_version.revision,
        expected_outline_content_sha256=outline.current_version.content_sha256,
        outline=_complete_outline(),
    )
    passed = productions.record_preflight(
        production_id=production.id,
        outline_candidate_id=outline.id,
        expected_outline_revision=outline.current_version.revision,
        expected_outline_content_sha256=outline.current_version.content_sha256,
        checks={
            field: True
            for field in (
                "reader_promise",
                "opening_hook",
                "state_change",
                "emotional_payoff",
                "ending_cliffhanger",
            )
        },
        missing_fields=[],
    )
    assert passed.passed is True
    candidate = productions.create_draft_candidate(
        production_id=production.id,
        outline_candidate_id=outline.id,
        expected_outline_revision=outline.current_version.revision,
        expected_outline_content_sha256=outline.current_version.content_sha256,
        content="甲乙丙丁戊己",
        label="AI 候选",
        trace=_trace(CreativeContextPurpose.DRAFT),
    )
    assert projects.get_workspace(project_id).chapters[0].content == ""

    locked = productions.lock_selection(
        production_id=production.id,
        candidate_id=candidate.id,
        expected_candidate_revision=0,
        expected_candidate_content_sha256=candidate.current_version.content_sha256,
        selection=_selection(candidate.current_version.content, 1, 3),
    )
    with pytest.raises(LockedSelectionError, match="selection_locked"):
        productions.replace_candidate_selection(
            production_id=production.id,
            candidate_id=candidate.id,
            expected_candidate_revision=0,
            expected_candidate_content_sha256=candidate.current_version.content_sha256,
            selection=EditableTextSelection(
                start_char=2,
                end_char=4,
                selected_text_sha256=text_sha256("丙丁"),
            ),
            replacement="不允许",
            operation=CandidateVersionOperation.AUTHOR_EDIT,
            instruction="author_edit",
        )
    productions.unlock_selection(
        production_id=production.id,
        candidate_id=candidate.id,
        lock_id=locked.id,
        expected_candidate_revision=0,
        expected_candidate_content_sha256=candidate.current_version.content_sha256,
    )
    edited = productions.replace_candidate_selection(
        production_id=production.id,
        candidate_id=candidate.id,
        expected_candidate_revision=0,
        expected_candidate_content_sha256=candidate.current_version.content_sha256,
        selection=EditableTextSelection(
            start_char=2,
            end_char=4,
            selected_text_sha256=text_sha256("丙丁"),
        ),
        replacement="新文",
        operation=CandidateVersionOperation.AUTHOR_EDIT,
        instruction="author_edit",
    )
    restored = productions.undo_candidate(
        production_id=production.id,
        candidate_id=candidate.id,
        expected_candidate_revision=edited.current_version.revision,
        expected_candidate_content_sha256=edited.current_version.content_sha256,
        target_version_id=None,
    )
    assert restored.current_version.content == candidate.current_version.content
    assert [
        item.revision for item in productions.list_candidate_versions(production.id, candidate.id)
    ] == [0, 1, 2]

    with database.connect() as connection:
        before = connection.execute(
            "SELECT COUNT(*) FROM chapter_production_events WHERE production_id = ?",
            (production.id,),
        ).fetchone()[0]
    assert productions.get_current_production(project_id, chapter_id).id == production.id
    with database.connect() as connection:
        after = connection.execute(
            "SELECT COUNT(*) FROM chapter_production_events WHERE production_id = ?",
            (production.id,),
        ).fetchone()[0]
    assert after == before


def test_merge_provenance_and_atomic_whole_adoption_are_replay_safe(tmp_path: Path) -> None:
    _database, projects, productions, *_rest, project_id, chapter_id = _system(
        tmp_path / "adopt.db"
    )
    production, outline, first, chapter = _create_ready_candidate(
        projects, productions, project_id, chapter_id, content="甲乙丙丁"
    )
    second = productions.create_draft_candidate(
        production_id=production.id,
        outline_candidate_id=outline.id,
        expected_outline_revision=outline.current_version.revision,
        expected_outline_content_sha256=outline.current_version.content_sha256,
        content="戊己庚辛",
        label="备选",
        trace=_trace(CreativeContextPurpose.DRAFT),
    )
    sources = [
        MergeSource(
            candidate_id=item.id,
            candidate_version_id=item.current_version.id,
            candidate_revision=item.current_version.revision,
            candidate_content_sha256=item.current_version.content_sha256,
            start_char=0,
            end_char=len(item.current_version.content),
            selected_text_sha256=item.current_version.content_sha256,
        )
        for item in (first, second)
    ]
    merged = productions.merge_candidates(
        production_id=production.id,
        request=MergeCandidatesRequest(sources=sources, label="合并候选", separator="|"),
    )
    assert merged.current_version.content == "甲乙丙丁|戊己庚辛"
    assert productions.list_merge_sources(production.id, merged.id) == sources

    request = AdoptCandidateRequest(
        expected_candidate_revision=merged.current_version.revision,
        expected_candidate_content_sha256=merged.current_version.content_sha256,
        expected_chapter_revision=chapter.revision,
        expected_chapter_content_sha256=text_sha256(chapter.content),
        mode=AdoptionMode.WHOLE,
        idempotency_key="adopt-0001",
    )
    outcome = productions.adopt_candidate(
        production_id=production.id,
        candidate_id=merged.id,
        request=request,
    )
    replay = productions.adopt_candidate(
        production_id=production.id,
        candidate_id=merged.id,
        request=request,
    )
    assert replay.id == outcome.id
    assert outcome.chapter_version_id is not None
    canonical = productions.get_applied_version(outcome.id)
    assert canonical.id == outcome.chapter_version_id
    assert canonical.content == merged.current_version.content
    saved = projects.get_workspace(project_id).chapters[0]
    assert saved.content == merged.current_version.content
    assert saved.revision == chapter.revision + 1
    with pytest.raises(ChapterProductionConflictError, match="idempotency_key_reused"):
        productions.adopt_candidate(
            production_id=production.id,
            candidate_id=merged.id,
            request=request.model_copy(update={"expected_chapter_revision": 99}),
        )


def test_partial_adoption_uses_hash_guarded_ranges(tmp_path: Path) -> None:
    _database, projects, productions, *_rest, project_id, chapter_id = _system(
        tmp_path / "partial.db", content="甲乙丙丁"
    )
    production, _outline, candidate, chapter = _create_ready_candidate(
        projects, productions, project_id, chapter_id, content="新天地"
    )
    outcome = productions.adopt_candidate(
        production_id=production.id,
        candidate_id=candidate.id,
        request=AdoptCandidateRequest(
            expected_candidate_revision=0,
            expected_candidate_content_sha256=candidate.current_version.content_sha256,
            expected_chapter_revision=chapter.revision,
            expected_chapter_content_sha256=text_sha256(chapter.content),
            mode=AdoptionMode.PARTIAL,
            candidate_selection=_selection(candidate.current_version.content, 0, 2),
            chapter_selection=_selection(chapter.content, 1, 3),
            idempotency_key="partial-0001",
        ),
    )
    assert outcome.adoption_detail["mode"] == "partial"
    assert projects.get_workspace(project_id).chapters[0].content == "甲新天丁"


def test_approved_chapter_cannot_be_overwritten_by_a_candidate(tmp_path: Path) -> None:
    database, projects, productions, *_rest, project_id, chapter_id = _system(
        tmp_path / "approved.db"
    )
    production, _outline, candidate, chapter = _create_ready_candidate(
        projects, productions, project_id, chapter_id
    )
    with database.connect() as connection:
        connection.execute("UPDATE chapters SET status = 'approved' WHERE id = ?", (chapter_id,))
    request = AdoptCandidateRequest(
        expected_candidate_revision=0,
        expected_candidate_content_sha256=candidate.current_version.content_sha256,
        expected_chapter_revision=chapter.revision,
        expected_chapter_content_sha256=text_sha256(chapter.content),
        mode=AdoptionMode.WHOLE,
        idempotency_key="approved-001",
    )
    with pytest.raises(ChapterProductionConflictError, match="approved_chapter_immutable"):
        productions.adopt_candidate(
            production_id=production.id,
            candidate_id=candidate.id,
            request=request,
        )
    assert projects.get_workspace(project_id).chapters[0].content == chapter.content


def test_demo_model_flow_only_materializes_candidates_until_author_adopts(tmp_path: Path) -> None:
    (
        _database,
        projects,
        productions,
        service,
        runtime,
        adapter,
        project_id,
        chapter_id,
    ) = _system(tmp_path / "service.db")
    chapter = projects.get_workspace(project_id).chapters[0]
    production = productions.create_production(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_chapter_revision=chapter.revision,
        expected_chapter_content_sha256=text_sha256(chapter.content),
    )
    outline_preview = service.preview_outline(
        production.id, GenerateOutlineRequest(author_intent="先救下父亲")
    )
    outline_job = service.submit_outline(
        production.id,
        SubmitOutlineJobRequest(
            author_intent="先救下父亲",
            context_packet_id=outline_preview.context_packet_id,
            context_packet_sha256=outline_preview.context_packet_sha256,
        ),
    )
    assert runtime.run_once() is True
    assert service.jobs.get_job(outline_job.id).state == JobState.SUCCEEDED
    outline = service.get_outline_result(production.id, outline_job.id)
    guard = OutlineGuard(
        outline_candidate_id=outline.id,
        expected_outline_revision=outline.current_version.revision,
        expected_outline_content_sha256=outline.current_version.content_sha256,
    )
    assert service.preflight(production.id, guard).passed is True

    draft_request = GenerateDraftRequest(**guard.model_dump(), author_intent="保留现实代价")
    draft_preview = service.preview_draft(production.id, draft_request)
    draft_job = service.submit_draft(
        production.id,
        SubmitDraftJobRequest(
            **draft_request.model_dump(),
            context_packet_id=draft_preview.context_packet_id,
            context_packet_sha256=draft_preview.context_packet_sha256,
        ),
    )
    assert runtime.run_once() is True
    candidate = service.get_candidate_result(production.id, draft_job.id, draft_job.workflow)
    assert candidate.current_version.trace is not None
    assert projects.get_workspace(project_id).chapters[0].content == ""

    review_request = ReviewCandidateRequest(
        expected_candidate_revision=candidate.current_version.revision,
        expected_candidate_content_sha256=candidate.current_version.content_sha256,
    )
    review_preview = service.preview_review(production.id, candidate.id, review_request)
    review_job = service.submit_review(
        production.id,
        candidate.id,
        SubmitReviewJobRequest(
            **review_request.model_dump(),
            context_packet_id=review_preview.context_packet_id,
            context_packet_sha256=review_preview.context_packet_sha256,
        ),
    )
    assert runtime.run_once() is True
    review = service.get_review_result(production.id, candidate.id, review_job.id)
    assert len(review.findings) == 7
    assert adapter.review_calls == 7
    assert adapter.contexts
    assert all('"creative_context"' in item for item in adapter.contexts)
    assert all(
        "source_segment_ids" not in item and "source_refs" not in item for item in adapter.contexts
    )


def test_author_edit_during_model_call_blocks_stale_candidate_materialization(
    tmp_path: Path,
) -> None:
    (
        _database,
        projects,
        productions,
        service,
        runtime,
        adapter,
        project_id,
        chapter_id,
    ) = _system(tmp_path / "drift.db")
    chapter = projects.get_workspace(project_id).chapters[0]
    production = productions.create_production(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_chapter_revision=chapter.revision,
        expected_chapter_content_sha256=text_sha256(chapter.content),
    )
    outline = productions.add_outline_candidate(
        production_id=production.id,
        outline=_complete_outline(),
        label="已确认章纲",
        trace=_trace(CreativeContextPurpose.BRIEF),
    )
    guard = OutlineGuard(
        outline_candidate_id=outline.id,
        expected_outline_revision=outline.current_version.revision,
        expected_outline_content_sha256=outline.current_version.content_sha256,
    )
    assert service.preflight(production.id, guard).passed is True
    request = GenerateDraftRequest(**guard.model_dump())
    preview = service.preview_draft(production.id, request)
    job = service.submit_draft(
        production.id,
        SubmitDraftJobRequest(
            **request.model_dump(),
            context_packet_id=preview.context_packet_id,
            context_packet_sha256=preview.context_packet_sha256,
        ),
    )
    adapter.on_draft = lambda: projects.update_chapter(
        chapter_id,
        UpdateChapterRequest(content="作者并发修改", expected_revision=chapter.revision),
    )

    assert runtime.run_once() is True
    failed = service.jobs.get_job(job.id)
    assert failed.state == JobState.FAILED
    assert failed.error_code == "chapter_changed"
    assert productions.get_snapshot(production.id).candidates == []
    assert projects.get_workspace(project_id).chapters[0].content == "作者并发修改"
    assert adapter.draft_calls == 1


def test_api_create_and_get_are_idempotent_and_get_is_pure(tmp_path: Path) -> None:
    database_path = tmp_path / "api.db"
    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "回到九八年的南平",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        chapter = workspace["chapters"][0]
        body = {
            "expected_chapter_revision": chapter["revision"],
            "expected_chapter_content_sha256": sha256(chapter["content"].encode()).hexdigest(),
        }
        created = client.post(
            f"/api/projects/{project_id}/chapters/{chapter['id']}/productions",
            json=body,
        )
        replay = client.post(
            f"/api/projects/{project_id}/chapters/{chapter['id']}/productions",
            json=body,
        )
        assert created.status_code == 201, created.text
        assert replay.status_code == 201, replay.text
        assert replay.json()["production"]["id"] == created.json()["production"]["id"]
        production_id = created.json()["production"]["id"]
        with client.app.state.repository.database.connect() as connection:
            before = connection.execute(
                "SELECT COUNT(*) FROM chapter_production_events "
                "WHERE production_id = ?",
                (production_id,),
            ).fetchone()[0]
        fetched = client.get(f"/api/chapter-productions/{production_id}")
        assert fetched.status_code == 200
        assert fetched.json() == created.json()
        with client.app.state.repository.database.connect() as connection:
            after = connection.execute(
                "SELECT COUNT(*) FROM chapter_production_events "
                "WHERE production_id = ?",
                (production_id,),
            ).fetchone()[0]
        assert after == before
        conflict = client.post(
            f"/api/projects/{project_id}/chapters/{chapter['id']}/productions",
            json={**body, "expected_chapter_revision": 99},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "chapter_changed"


def test_archive_round_trip_preserves_candidate_lineage_and_canonical_version(
    tmp_path: Path,
) -> None:
    (
        database,
        projects,
        productions,
        service,
        runtime,
        _adapter,
        project_id,
        chapter_id,
    ) = _system(tmp_path / "archive.db")
    chapter = projects.get_workspace(project_id).chapters[0]
    production = productions.create_production(
        project_id=project_id,
        chapter_id=chapter_id,
        expected_chapter_revision=chapter.revision,
        expected_chapter_content_sha256=text_sha256(chapter.content),
    )
    outline_preview = service.preview_outline(production.id, GenerateOutlineRequest())
    outline_job = service.submit_outline(
        production.id,
        SubmitOutlineJobRequest(
            context_packet_id=outline_preview.context_packet_id,
            context_packet_sha256=outline_preview.context_packet_sha256,
        ),
    )
    assert runtime.run_once() is True
    outline = service.get_outline_result(production.id, outline_job.id)
    guard = OutlineGuard(
        outline_candidate_id=outline.id,
        expected_outline_revision=outline.current_version.revision,
        expected_outline_content_sha256=outline.current_version.content_sha256,
    )
    assert service.preflight(production.id, guard).passed is True
    draft_request = GenerateDraftRequest(**guard.model_dump())
    draft_preview = service.preview_draft(production.id, draft_request)
    draft_job = service.submit_draft(
        production.id,
        SubmitDraftJobRequest(
            **draft_request.model_dump(),
            context_packet_id=draft_preview.context_packet_id,
            context_packet_sha256=draft_preview.context_packet_sha256,
        ),
    )
    assert runtime.run_once() is True
    candidate = service.get_candidate_result(production.id, draft_job.id, draft_job.workflow)
    outcome = productions.adopt_candidate(
        production_id=production.id,
        candidate_id=candidate.id,
        request=AdoptCandidateRequest(
            expected_candidate_revision=candidate.current_version.revision,
            expected_candidate_content_sha256=candidate.current_version.content_sha256,
            expected_chapter_revision=chapter.revision,
            expected_chapter_content_sha256=text_sha256(chapter.content),
            mode=AdoptionMode.WHOLE,
            idempotency_key="archive-adopt-001",
        ),
    )
    archives = ProjectArchiveService(database)
    archive = archives.export_project(project_id)
    assert archive["format_version"] == 18
    restored_project_id = archives.import_project(canonical_json(archive))

    with database.connect() as connection:
        restored_production = connection.execute(
            "SELECT id FROM chapter_productions WHERE project_id = ?",
            (restored_project_id,),
        ).fetchone()
        assert restored_production is not None
        restored_outcome = connection.execute(
            """
            SELECT o.id, o.chapter_version_id, v.source_id, v.content
            FROM chapter_writing_outcomes o
            JOIN chapter_versions v ON v.id = o.chapter_version_id
            JOIN chapter_productions p ON p.id = o.production_id
            WHERE p.project_id = ?
            """,
            (restored_project_id,),
        ).fetchone()
        assert restored_outcome is not None
        assert restored_outcome["chapter_version_id"] is not None
        assert restored_outcome["source_id"] == restored_outcome["id"]
        assert restored_outcome["content"] == candidate.current_version.content
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    restored_snapshot = productions.get_snapshot(str(restored_production["id"]))
    assert restored_snapshot.production.state.value == "adopted"
    assert len(restored_snapshot.outcomes) == 1
    assert restored_snapshot.outcomes[0].id != outcome.id
    assert (
        projects.get_workspace(restored_project_id).chapters[0].content
        == candidate.current_version.content
    )
