from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from app.ai import AiGatewayManager
from app.database import Database
from app.jobs.models import Job, JobKind, JobState
from app.jobs.repository import JobRepository
from app.jobs.runtime import JobRuntime
from app.main import create_app
from app.models import (
    AiChapterBriefProposal,
    AiProvider,
    AiStatus,
    Chapter,
    CreateProjectRequest,
    Genre,
    ImportReferenceWorkRequest,
    ReferenceBookAnalysis,
    ReferenceChunkAnalysis,
    ReferenceDimensionSynthesis,
    ReferencePatternCard,
    ReferenceRightsBasis,
    ReferenceSynthesisProposal,
    ReferenceSynthesisRequest,
    Workspace,
)
from app.reference_jobs import ReferenceJobService
from app.reference_lab import ReferenceAnalysisInput
from app.repository import ProjectRepository


class RecoverableReferenceGateway:
    def __init__(self, fail_once_at: int | None = None) -> None:
        self.call_count = 0
        self.fail_once_at = fail_once_at
        self.failed = False
        self.map_call_keys: list[tuple[str, int, int]] = []
        self.on_call: Callable[[], None] | None = None

    def status(self) -> AiStatus:
        return AiStatus(
            configured=True,
            provider=AiProvider.OPENAI,
            model="recoverable-reference-test",
            key_source="test",
        )

    def _before_call(self) -> None:
        self.call_count += 1
        if self.on_call is not None:
            callback, self.on_call = self.on_call, None
            callback()
        if self.fail_once_at == self.call_count and not self.failed:
            self.failed = True
            raise TimeoutError("injected provider timeout")

    def analyze_reference_chunk(
        self,
        segment: ReferenceAnalysisInput,
        chunk_start: int,
        chunk_end: int,
    ) -> ReferenceChunkAnalysis:
        self.map_call_keys.append((segment.segment_id, chunk_start, chunk_end))
        self._before_call()
        return ReferenceChunkAnalysis(
            era="时代窗口",
            core_desire="改变命运",
            conflict_causality="行动引发旧秩序反制",
            resource_system="信息转化为资源",
            key_scene_sequence=["验证机会", "扩大冲突"],
            ending="阶段胜利打开更大冲突",
        )

    def reduce_reference_book(
        self,
        work_id: str,
        work_title: str,
        mapped_analyses: list[dict[str, object]],
        author_focus: str,
    ) -> ReferenceBookAnalysis:
        del author_focus
        self._before_call()
        return ReferenceBookAnalysis(
            work_id=work_id,
            work_title=work_title,
            source_segment_ids=list(dict.fromkeys(
                str(item["segment_id"]) for item in mapped_analyses
            )),
            era="单书时代窗口",
            core_desire="单书核心欲望",
            conflict_causality="单书冲突因果",
            resource_system="单书资源体系",
            key_scene_sequence=["机会验证", "阶段升级"],
            ending="单书阶段落点",
        )

    def fuse_reference_books(
        self,
        book_analyses: list[ReferenceBookAnalysis],
        allowed_source_segment_ids: list[str],
        author_focus: str,
    ) -> ReferenceSynthesisProposal:
        del book_analyses, author_focus
        self._before_call()

        def dimension(summary: str) -> ReferenceDimensionSynthesis:
            return ReferenceDimensionSynthesis(
                summary=summary,
                source_segment_ids=allowed_source_segment_ids,
                transferable_logic="只迁移抽象功能并重组人物关系。",
                adaptation_risk="不得复制专名与独特场景序列。",
            )

        return ReferenceSynthesisProposal(
            era=dimension("跨书时代结构"),
            core_desire=dimension("跨书欲望结构"),
            conflict_causality=dimension("跨书冲突结构"),
            resource_system=dimension("跨书资源结构"),
            key_scene_sequence=dimension("跨书场景功能结构"),
            ending=dimension("跨书结局结构"),
            shared_patterns=["机会必须通过行动验证"],
            differences=["资源路径不同"],
            relationship_recomposition="改为全新师徒竞争关系。",
            originality_risks=["重新设计产业、地点和具体顺序"],
        )

    def synthesize_references(
        self,
        segments: list[ReferenceAnalysisInput],
        author_focus: str,
    ) -> ReferenceSynthesisProposal:
        raise AssertionError("产品任务入口不应调用旧同步方法")

    def propose_brief(
        self,
        workspace: Workspace,
        chapter: Chapter,
        author_intent: str,
    ) -> AiChapterBriefProposal:
        del workspace, chapter, author_intent
        raise AssertionError("not used")

    def draft_chapter(
        self,
        workspace: Workspace,
        chapter: Chapter,
        author_intent: str,
    ) -> str:
        del workspace, chapter, author_intent
        raise AssertionError("not used")


def build_reference_job(
    database_path: Path,
    gateway: RecoverableReferenceGateway,
    *,
    characters_per_work: int = 1_000_000,
) -> tuple[ProjectRepository, JobRepository, ReferenceJobService, JobRuntime, str, list[str]]:
    database = Database(database_path)
    database.initialize()
    repository = ProjectRepository(database)
    workspace = repository.create_project(CreateProjectRequest(
        title="长篇可恢复拆书",
        genre=Genre.URBAN_REBIRTH,
        rebirth_year=1998,
        rebirth_location="福建南平",
    ))
    segment_ids: list[str] = []
    for ordinal, character in enumerate(("甲", "乙"), start=1):
        work = repository.import_reference_work(
            workspace.project.id,
            ImportReferenceWorkRequest(
                title=f"自有参考 {ordinal}",
                source_filename=f"owned-{ordinal}.txt",
                rights_basis=ReferenceRightsBasis.SELF_OWNED,
                segment_target_characters=1_000_000,
                content=character * characters_per_work,
            ),
        )
        segment_ids.extend(segment.id for segment in work.segments)
    jobs = JobRepository(database)
    service = ReferenceJobService(repository, jobs, AiGatewayManager(gateway))
    runtime = JobRuntime(jobs, {JobKind.REFERENCE_FUSION: service.handle})
    return repository, jobs, service, runtime, workspace.project.id, segment_ids


def submit_reference_job(
    service: ReferenceJobService,
    project_id: str,
    segment_ids: list[str],
) -> Job:
    return service.submit(project_id, ReferenceSynthesisRequest(
        selected_segment_ids=segment_ids,
        author_focus="比较资源增长与阶段结局",
        confirm_external_processing=True,
    ))


@pytest.mark.parametrize("fail_once_at", [1, 20, 39, 40, 41, 43])
def test_reference_job_reuses_every_artifact_before_failed_call(
    tmp_path: Path,
    fail_once_at: int,
) -> None:
    gateway = RecoverableReferenceGateway(fail_once_at)
    repository, jobs, service, runtime, project_id, segment_ids = build_reference_job(
        tmp_path / f"failure-{fail_once_at}.db",
        gateway,
    )
    job = submit_reference_job(service, project_id, segment_ids)

    assert runtime.run_once() is True
    failed = jobs.get_job_detail(job.id)
    assert failed.state == JobState.FAILED
    assert len(failed.artifacts) == fail_once_at - 1

    jobs.retry_job(job.id)
    assert runtime.run_once() is True

    completed = jobs.get_job_detail(job.id)
    workspace = repository.get_workspace(project_id)
    assert completed.state == JobState.SUCCEEDED
    assert completed.progress_current == completed.progress_total == 43
    assert len(completed.artifacts) == 43
    assert gateway.call_count == 44
    assert len(workspace.reference_pattern_cards) == 1
    assert workspace.reference_pattern_cards[0].source_job_id == job.id


def test_reference_job_reuses_fusion_artifact_if_card_materialization_crashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = RecoverableReferenceGateway()
    repository, jobs, service, runtime, project_id, segment_ids = build_reference_job(
        tmp_path / "materialization.db",
        gateway,
        characters_per_work=100_000,
    )
    original_save = repository.save_reference_pattern_card
    save_calls = 0

    def fail_first_save(
        target_project_id: str,
        selected_segment_ids: list[str],
        author_focus: str,
        proposal: ReferenceSynthesisProposal,
        provider: str,
        model: str,
        source_job_id: str | None = None,
    ) -> ReferencePatternCard:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 1:
            raise RuntimeError("injected materialization crash")
        return original_save(
            target_project_id,
            selected_segment_ids,
            author_focus,
            proposal,
            provider,
            model,
            source_job_id,
        )

    monkeypatch.setattr(repository, "save_reference_pattern_card", fail_first_save)
    job = submit_reference_job(service, project_id, segment_ids)

    runtime.run_once()
    failed = jobs.get_job_detail(job.id)
    calls_after_failure = gateway.call_count
    assert failed.state == JobState.FAILED
    assert len(failed.artifacts) == 7
    assert repository.get_workspace(project_id).reference_pattern_cards == []

    jobs.retry_job(job.id)
    runtime.run_once()

    assert jobs.get_job(job.id).state == JobState.SUCCEEDED
    assert gateway.call_count == calls_after_failure
    assert len(repository.get_workspace(project_id).reference_pattern_cards) == 1


def test_reference_job_cancel_stops_before_next_provider_call(tmp_path: Path) -> None:
    gateway = RecoverableReferenceGateway()
    _repository, jobs, service, runtime, project_id, segment_ids = build_reference_job(
        tmp_path / "cancel.db",
        gateway,
        characters_per_work=100_000,
    )
    job = submit_reference_job(service, project_id, segment_ids)
    def cancel_after_current_call_started() -> None:
        jobs.request_cancel(job.id)

    gateway.on_call = cancel_after_current_call_started

    runtime.run_once()

    detail = jobs.get_job_detail(job.id)
    assert detail.state == JobState.CANCELLED
    assert gateway.call_count == 1
    assert len(detail.artifacts) == 1
    assert detail.progress_current == 1


def test_reference_job_submission_is_idempotent_and_never_copies_source_text(
    tmp_path: Path,
) -> None:
    gateway = RecoverableReferenceGateway()
    repository, jobs, service, _runtime, project_id, segment_ids = build_reference_job(
        tmp_path / "idempotent.db",
        gateway,
        characters_per_work=100_000,
    )

    first = submit_reference_job(service, project_id, segment_ids)
    second = submit_reference_job(service, project_id, segment_ids)

    assert second.id == first.id
    assert len(jobs.list_chunks(first.id)) == 7
    with repository.database.connect() as connection:
        task_payloads = [
            row[0]
            for row in connection.execute(
                "SELECT input_json FROM jobs UNION ALL SELECT input_json FROM job_chunks"
            ).fetchall()
        ]
    assert all("甲甲甲甲" not in payload and "乙乙乙乙" not in payload for payload in task_payloads)


def test_reference_analysis_job_api_finishes_in_background(tmp_path: Path) -> None:
    manager = AiGatewayManager(RecoverableReferenceGateway())
    with TestClient(create_app(tmp_path / "api.db", ai_manager=manager)) as client:
        workspace = client.post(
            "/api/projects",
            json={
                "title": "异步拆书入口",
                "genre": "urban_rebirth",
                "rebirth_year": 1998,
                "rebirth_location": "福建南平",
            },
        ).json()
        project_id = workspace["project"]["id"]
        segment_ids: list[str] = []
        for ordinal, character in enumerate(("甲", "乙"), start=1):
            work = client.post(
                f"/api/projects/{project_id}/reference-works",
                json={
                    "title": f"自有作品 {ordinal}",
                    "source_filename": f"owned-{ordinal}.txt",
                    "rights_basis": "self_owned",
                    "segment_target_characters": 100_000,
                    "content": character * 100_000,
                },
            ).json()
            segment_ids.append(work["segments"][0]["id"])

        submitted = client.post(
            f"/api/projects/{project_id}/reference-analysis-jobs",
            json={
                "selected_segment_ids": segment_ids,
                "author_focus": "比较资源体系",
                "confirm_external_processing": True,
            },
        )
        deadline = monotonic() + 3
        detail = submitted.json()
        while detail["state"] not in {"succeeded", "failed", "cancelled"} and monotonic() < deadline:
            sleep(0.01)
            detail = client.get(f"/api/jobs/{detail['id']}").json()

        summary = client.get(f"/api/projects/{project_id}/summary").json()

    assert submitted.status_code == 202
    assert detail["state"] == "succeeded"
    assert detail["progress_current"] == detail["progress_total"] == 7
    assert summary["reference_pattern_cards"][0]["source_job_id"] == detail["id"]
