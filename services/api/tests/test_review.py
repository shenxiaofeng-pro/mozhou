from pathlib import Path
from threading import Lock
from time import sleep

import pytest

from app.ai import AiGatewayManager, AiProviderError
from app.database import Database
from app.jobs import JobKind, JobRepository, JobRuntime
from app.models import (
    AiProvider,
    AiStatus,
    ApplyTextChangeSetRequest,
    CreateChapterRequest,
    CreateProjectRequest,
    CreateTextChangeSetRequest,
    Genre,
    ReviewChapterRequest,
    ReviewDimension,
    ReviewEvidence,
    ReviewEvidenceKind,
    ReviewFindingDraft,
    ReviewFindingDraftSet,
    ReviewSeverity,
    RollbackChapterVersionRequest,
    UpdateChapterBriefRequest,
    UpdateChapterRequest,
)
from app.repository import ProjectRepository
from app.review.repository import ReviewRepository, StaleReviewRevisionError
from app.review.rules import make_finding
from app.review.service import ReviewService


class ReviewGateway:
    def __init__(self) -> None:
        self.failed_dimensions: set[ReviewDimension] = set()
        self.calls: list[ReviewDimension] = []
        self.active_calls = 0
        self.max_active_calls = 0
        self._lock = Lock()

    def status(self) -> AiStatus:
        return AiStatus(
            configured=True,
            provider=AiProvider.OPENAI,
            model="review-fixture",
            key_source="test",
        )

    def review_chapter(
        self,
        _context_text: str,
        dimension: ReviewDimension,
    ) -> ReviewFindingDraftSet:
        with self._lock:
            self.calls.append(dimension)
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            sleep(0.02)
            if dimension in self.failed_dimensions:
                raise AiProviderError(
                    "fixture failure",
                    safe_message="该维度暂时失败，可单独重跑",
                )
            evidence_by_dimension = {
                ReviewDimension.CHARACTER: "老陈突然改口叫他沈总。",
                ReviewDimension.REALISM: "一九九八年，他掏出智能手机扫码付款。",
                ReviewDimension.REBIRTH_LOGIC: "分歧发生后，他仍断言原历史会逐日照搬。",
                ReviewDimension.STYLE: "命运的齿轮开始转动，一切都在不言中。",
                ReviewDimension.FORMAT: "他说：“现在出发。",
            }
            evidence = evidence_by_dimension[dimension]
            return ReviewFindingDraftSet(
                findings=[
                    ReviewFindingDraft(
                        code=f"fixture_{dimension.value}",
                        severity=ReviewSeverity.WARNING,
                        title=f"{dimension.value} 可验证问题",
                        evidence_text=evidence,
                        explanation="该句与当前维度的已确认约束冲突。",
                        suggestion="只修改这一处，并保留当前场景功能。",
                        suggested_replacement=f"【修正】{evidence}",
                        confidence=0.92,
                    )
                ]
            )
        finally:
            with self._lock:
                self.active_calls -= 1


def _review_fixture(tmp_path: Path) -> tuple[
    ProjectRepository,
    ReviewRepository,
    JobRepository,
    ReviewService,
    JobRuntime,
    ReviewGateway,
    str,
]:
    database = Database(tmp_path / "review.db")
    database.initialize()
    repository = ProjectRepository(database)
    reviews = ReviewRepository(database)
    jobs = JobRepository(database)
    gateway = ReviewGateway()
    service = ReviewService(
        repository,
        reviews,
        jobs,
        AiGatewayManager(gateway),
    )
    runtime = JobRuntime(jobs, {JobKind.REVIEW: service.handle})
    workspace = repository.create_project(
        CreateProjectRequest(
            title="南平旧厂",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    chapter = workspace.chapters[0]
    chapter = repository.update_chapter_brief(
        chapter.id,
        UpdateChapterBriefRequest(
            reader_promise="主角第一次改变父亲的命运",
            opening_hook="停产通知贴到厂门口",
            state_change="主角拿到关键订单",
            emotional_payoff="父亲第一次相信儿子",
            ending_cliffhanger="厂长要求他明早当众解释",
            expected_revision=chapter.revision,
        ),
    )
    manuscript = (
        "老陈突然改口叫他沈总。\n"
        "一九九八年，他掏出智能手机扫码付款。\n"
        "分歧发生后，他仍断言原历史会逐日照搬。\n"
        "命运的齿轮开始转动，一切都在不言中。\n"
        "他说：“现在出发。"
    )
    chapter = repository.update_chapter(
        chapter.id,
        UpdateChapterRequest(content=manuscript, expected_revision=chapter.revision),
    )
    return repository, reviews, jobs, service, runtime, gateway, chapter.id


def test_seven_dimension_review_keeps_successes_and_reruns_one_failure(
    tmp_path: Path,
) -> None:
    repository, reviews, jobs, service, runtime, gateway, chapter_id = _review_fixture(
        tmp_path
    )
    chapter = repository.get_chapter(chapter_id)
    gateway.failed_dimensions = {ReviewDimension.REALISM}
    request = ReviewChapterRequest(
        expected_revision=chapter.revision,
        window_size=3,
        dimensions=list(ReviewDimension),
        confirm_external_processing=True,
    )

    preview = service.preview(chapter_id, request)
    job = service.submit(chapter_id, request)
    assert preview.estimated_calls == 5
    assert preview.local_dimensions == [
        ReviewDimension.CONTINUITY,
        ReviewDimension.SERIAL_RHYTHM,
    ]
    assert runtime.run_once()

    completed = jobs.get_job(job.id)
    result = service.get_result(job.id)
    assert completed.state.value == "succeeded"
    assert next(
        item for item in result.outcomes if item.dimension == ReviewDimension.REALISM
    ).state.value == "failed"
    assert next(
        item for item in result.outcomes if item.dimension == ReviewDimension.CHARACTER
    ).state.value == "succeeded"
    assert gateway.max_active_calls >= 2
    assert all(finding.evidence for finding in result.findings)
    assert all(
        evidence.excerpt
        == chapter.content[evidence.start_char : evidence.end_char]
        for finding in result.findings
        for evidence in finding.evidence
        if evidence.kind == ReviewEvidenceKind.BODY
        and evidence.start_char is not None
        and evidence.end_char is not None
    )

    gateway.failed_dimensions.clear()
    rerun = service.submit(
        chapter_id,
        ReviewChapterRequest(
            expected_revision=chapter.revision,
            window_size=3,
            dimensions=[ReviewDimension.REALISM],
            confirm_external_processing=True,
            parent_job_id=job.id,
        ),
    )
    assert runtime.run_once()
    rerun_result = service.get_result(rerun.id)
    assert rerun_result.outcomes[0].state.value == "succeeded"
    assert rerun_result.findings[0].dimension == ReviewDimension.REALISM
    current = reviews.list_findings(
        chapter_id, chapter_revision=chapter.revision
    )
    assert {finding.dimension for finding in current} >= {
        ReviewDimension.CHARACTER,
        ReviewDimension.REALISM,
        ReviewDimension.REBIRTH_LOGIC,
        ReviewDimension.STYLE,
        ReviewDimension.FORMAT,
    }


def test_three_and_ten_chapter_windows_freeze_exact_scope(tmp_path: Path) -> None:
    repository, _reviews, jobs, service, _runtime, _gateway, chapter_id = (
        _review_fixture(tmp_path)
    )
    first = repository.get_chapter(chapter_id)
    later_chapters = []
    for number in range(2, 11):
        created = repository.create_chapter(
            first.project_id,
            CreateChapterRequest(
                expected_last_chapter_number=number - 1,
                title=f"第{number}章 窗口测试",
                ending_cliffhanger=f"第{number + 1}章会回答的问题",
            ),
        )
        later_chapters.append(
            repository.update_chapter(
                created.id,
                UpdateChapterRequest(
                    content=f"第{number}章独有正文标记",
                    expected_revision=created.revision,
                ),
            )
        )
    target = later_chapters[-1]

    ten_job = service.submit(
        target.id,
        ReviewChapterRequest(
            expected_revision=target.revision,
            window_size=10,
            dimensions=[ReviewDimension.CONTINUITY],
        ),
    )
    ten_context = jobs.find_artifact(ten_job.id, "review_context")
    assert ten_context is not None
    for number in range(2, 11):
        assert f"第{number}章独有正文标记" in ten_context.payload

    three_job = service.submit(
        target.id,
        ReviewChapterRequest(
            expected_revision=target.revision,
            window_size=3,
            dimensions=[ReviewDimension.CONTINUITY],
        ),
    )
    three_context = jobs.find_artifact(three_job.id, "review_context")
    assert three_context is not None
    for number in range(8, 11):
        assert f"第{number}章独有正文标记" in three_context.payload
    assert "第7章独有正文标记" not in three_context.payload


def test_review_worker_rejects_prior_window_change_before_provider_call(
    tmp_path: Path,
) -> None:
    repository, _reviews, jobs, service, runtime, gateway, chapter_id = _review_fixture(
        tmp_path
    )
    first = repository.get_chapter(chapter_id)
    target = repository.create_chapter(
        first.project_id,
        CreateChapterRequest(expected_last_chapter_number=1, title="第二章 窗口门禁"),
    )
    target = repository.update_chapter(
        target.id,
        UpdateChapterRequest(
            content="老陈突然改口叫他沈总。",
            expected_revision=target.revision,
        ),
    )
    job = service.submit(
        target.id,
        ReviewChapterRequest(
            expected_revision=target.revision,
            window_size=2,
            dimensions=[ReviewDimension.CHARACTER],
            confirm_external_processing=True,
        ),
    )
    repository.update_chapter(
        first.id,
        UpdateChapterRequest(
            content=first.content + "\n作者在提交后改写了前置正文。",
            expected_revision=first.revision,
        ),
    )

    assert runtime.run_once()

    failed = jobs.get_job(job.id)
    assert failed.state.value == "failed"
    assert failed.error_code == "creative_context_changed"
    assert gateway.calls == []


def test_partial_change_set_and_rollback_create_new_versions(tmp_path: Path) -> None:
    repository, reviews, _jobs, _service, _runtime, _gateway, chapter_id = (
        _review_fixture(tmp_path)
    )
    chapter = repository.get_chapter(chapter_id)
    first_text = "老陈突然改口叫他沈总。"
    second_text = "他说：“现在出发。"
    first_start = chapter.content.index(first_text)
    second_start = chapter.content.index(second_text)
    first = make_finding(
        job_id="review-change-fixture",
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        chapter_revision=chapter.revision,
        dimension=ReviewDimension.CHARACTER,
        severity=ReviewSeverity.WARNING,
        code="title_mismatch",
        title="称谓突变",
        evidence=[
            ReviewEvidence(
                kind=ReviewEvidenceKind.BODY,
                chapter_id=chapter.id,
                start_char=first_start,
                end_char=first_start + len(first_text),
                excerpt=first_text,
                label="第 1 章正文",
            )
        ],
        explanation="称谓没有关系变化支撑。",
        suggestion="改回此前称谓。",
        suggested_replacement="老陈仍旧叫他小沈。",
        confidence=0.96,
    ).model_copy(update={"review_job_id": None})
    second = make_finding(
        job_id="review-format-fixture",
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        chapter_revision=chapter.revision,
        dimension=ReviewDimension.FORMAT,
        severity=ReviewSeverity.WARNING,
        code="unclosed_quote",
        title="引号未闭合",
        evidence=[
            ReviewEvidence(
                kind=ReviewEvidenceKind.BODY,
                chapter_id=chapter.id,
                start_char=second_start,
                end_char=second_start + len(second_text),
                excerpt=second_text,
                label="第 1 章正文",
            )
        ],
        explanation="中文引号没有闭合。",
        suggestion="补齐右引号。",
        suggested_replacement="他说：“现在出发。”",
        confidence=1.0,
    ).model_copy(update={"review_job_id": None})
    reviews.save_findings([first, second])
    change_set = reviews.create_text_change_set(
        chapter.id,
        CreateTextChangeSetRequest(finding_ids=[first.id, second.id]),
    )
    selected = change_set.changes[0]

    applied = reviews.apply_text_change_set(
        change_set.id,
        ApplyTextChangeSetRequest(
            selected_change_ids=[selected.id],
            edited_replacements={selected.id: "老陈低声叫他小沈。"},
            expected_set_revision=change_set.revision,
            expected_chapter_revision=chapter.revision,
        ),
    )
    assert "老陈低声叫他小沈。" in applied.content
    assert second_text in applied.content
    history = reviews.get_text_change_set(change_set.id)
    assert [change.selected for change in history.changes] == [True, False]
    assert history.changes[0].applied_replacement == "老陈低声叫他小沈。"
    with pytest.raises(StaleReviewRevisionError):
        reviews.apply_text_change_set(
            change_set.id,
            ApplyTextChangeSetRequest(
                selected_change_ids=[selected.id],
                expected_set_revision=0,
                expected_chapter_revision=chapter.revision,
            ),
        )

    versions = reviews.list_chapter_versions(chapter.id)
    manual_version = next(version for version in versions if version.source.value == "manual_save")
    rolled_back = reviews.rollback_chapter_version(
        chapter.id,
        manual_version.id,
        RollbackChapterVersionRequest(expected_revision=applied.revision),
    )
    assert rolled_back.content == chapter.content
    assert rolled_back.revision == applied.revision + 1
    final_versions = reviews.list_chapter_versions(chapter.id)
    assert final_versions[0].source.value == "rollback"
    assert {version.source.value for version in final_versions} >= {
        "initial",
        "manual_save",
        "change_set_apply",
        "rollback",
    }
