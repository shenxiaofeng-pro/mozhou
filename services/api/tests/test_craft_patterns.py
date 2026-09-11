import json
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai import AiGateway, AiGatewayManager, build_chapter_context
from app.archive import ProjectArchiveService, canonical_json
from app.craft_patterns import (
    CRAFT_ANALYSIS_WORKFLOW,
    CRAFT_FUSION_WORKFLOW,
    CraftPatternRepository,
    CraftPatternService,
    InvalidCraftPatternError,
)
from app.database import Database
from app.jobs.models import JobKind, JobState
from app.jobs.repository import JobRepository, JobRequiresNewPreflightError
from app.jobs.runtime import JobRuntime
from app.main import create_app
from app.models import (
    AiProvider,
    AiStatus,
    CraftPatternAnalysisPreviewRequest,
    CraftPatternAsset,
    CraftPatternAssetType,
    CraftPatternDimension,
    CraftPatternEvidence,
    CraftPatternFusionPreviewRequest,
    CraftPatternItem,
    CraftPatternLifecycleState,
    CraftPatternMapDraft,
    CraftPatternMapEvidenceDraft,
    CraftPatternMapItemDraft,
    CraftPatternMaterial,
    CraftPatternReductionDraft,
    CraftPatternReductionItemDraft,
    CreateProjectRequest,
    Genre,
    ImportReferenceWorkRequest,
    ReferenceRightsBasis,
    SubmitCraftPatternAnalysisRequest,
    SubmitCraftPatternFusionRequest,
    UpdateCraftPatternLifecycleRequest,
)
from app.repository import ProjectRepository, StaleRevisionError


def _unique_excerpt(text: str) -> str:
    for start in range(max(1, len(text) - 16)):
        candidate = text[start : start + 16]
        if len(candidate) >= 8 and text.count(candidate) == 1:
            return candidate
    raise AssertionError("fixture must contain a unique evidence excerpt")


class CraftGateway:
    input_cost_microusd_per_million = 1_000_000
    output_cost_microusd_per_million = 1_000_000

    def __init__(self) -> None:
        self.call_count = 0
        self.contexts: list[str] = []
        self.on_call: Callable[[int], None] | None = None
        self.fusion_first_source_only = False

    def status(self) -> AiStatus:
        return AiStatus(
            configured=True,
            provider=AiProvider.OPENAI,
            model="craft-test-v2",
            key_source="test",
        )

    def _called(self, context_text: str) -> None:
        self.call_count += 1
        self.contexts.append(context_text)
        if self.on_call is not None:
            self.on_call(self.call_count)

    def analyze_craft_pattern_chunk(self, context_text: str) -> CraftPatternMapDraft:
        self._called(context_text)
        value = json.loads(context_text)
        source = value["source"]
        excerpt = _unique_excerpt(value["reference_text"])
        return CraftPatternMapDraft(
            title="阶段处理块",
            summary="抽象技法观察",
            craft_items=[
                CraftPatternMapItemDraft(
                    dimension=dimension,
                    name=f"{dimension.value} technique",
                    observation=f"{dimension.value} observation",
                    transferable_rule=f"{dimension.value} transferable rule",
                    adaptation_risk=f"{dimension.value} adaptation risk",
                    evidence=[
                        CraftPatternMapEvidenceDraft(
                            work_id=source["work_id"],
                            segment_id=source["segment_id"],
                            evidence_text=excerpt,
                            evidence_summary="abstract evidence function",
                            confidence=0.9,
                        )
                    ],
                )
                for dimension in CraftPatternDimension
            ],
        )

    def _reduce(self, context_text: str, title: str) -> CraftPatternReductionDraft:
        self._called(context_text)
        value = json.loads(context_text)
        evidence_by_segment: dict[str, str] = {}
        for material in value["materials"]:
            for item in material["craft_items"]:
                for evidence in item["evidence"]:
                    evidence_by_segment.setdefault(evidence["segment_id"], evidence["id"])
        evidence_ids = list(evidence_by_segment.values())
        return CraftPatternReductionDraft(
            title=title,
            summary="抽象演变规律",
            craft_items=[
                CraftPatternReductionItemDraft(
                    dimension=dimension,
                    name=f"{dimension.value} synthesis",
                    observation=f"{dimension.value} abstract observation",
                    transferable_rule=f"{dimension.value} abstract rule",
                    adaptation_risk=f"{dimension.value} recomposition risk",
                    evidence_ids=(
                        evidence_ids[index :: len(CraftPatternDimension)]
                        or [evidence_ids[index % len(evidence_ids)]]
                    ),
                )
                for index, dimension in enumerate(CraftPatternDimension)
            ],
        )

    def reduce_craft_pattern_stage(
        self, context_text: str
    ) -> CraftPatternReductionDraft:
        return self._reduce(context_text, "阶段卡")

    def evolve_craft_pattern_book(
        self, context_text: str
    ) -> CraftPatternReductionDraft:
        return self._reduce(context_text, "单书演变")

    def fuse_craft_pattern_assets(
        self, context_text: str
    ) -> CraftPatternReductionDraft:
        self._called(context_text)
        value = json.loads(context_text)
        evidence_by_parent: list[str] = []
        for asset in value["source_asset_versions"]:
            selected: str | None = None
            for item in asset["craft_items"]:
                for evidence in item["evidence"]:
                    selected = evidence["id"]
                    break
                if selected is not None:
                    break
            assert selected is not None
            evidence_by_parent.append(selected)
        evidence_ids = list(dict.fromkeys(evidence_by_parent))
        assert len(evidence_ids) >= 2
        if self.fusion_first_source_only:
            evidence_ids = evidence_ids[:1]
        return CraftPatternReductionDraft(
            title="多书融合",
            summary="跨作品抽象融合规律",
            craft_items=[
                CraftPatternReductionItemDraft(
                    dimension=dimension,
                    name=f"{dimension.value} fusion",
                    observation=f"{dimension.value} cross-book observation",
                    transferable_rule=f"{dimension.value} cross-book rule",
                    adaptation_risk=f"{dimension.value} recomposition risk",
                    evidence_ids=evidence_ids,
                )
                for dimension in CraftPatternDimension
            ],
        )


def _content(size: int, marker: str) -> str:
    blocks: list[str] = []
    index = 0
    total = 0
    while total < size:
        block = f"{marker}{index:08d}abcdefghijklmnopqrstuvwxyz\n"
        blocks.append(block)
        total += len(block)
        index += 1
    return "".join(blocks)[:size]


def _system(
    path: Path,
) -> tuple[ProjectRepository, JobRepository, CraftPatternService, JobRuntime, CraftGateway, str]:
    database = Database(path)
    database.initialize()
    repository = ProjectRepository(database)
    project_id = repository.create_project(
        CreateProjectRequest(
            title="写作模式 v2",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    ).project.id
    jobs = JobRepository(database)
    gateway = CraftGateway()
    service = CraftPatternService(
        repository,
        jobs,
        AiGatewayManager(cast(AiGateway, gateway)),
    )
    runtime = JobRuntime(jobs, {JobKind.REFERENCE_FUSION: service.handle})
    return repository, jobs, service, runtime, gateway, project_id


def _import(
    repository: ProjectRepository,
    project_id: str,
    *,
    size: int,
    marker: str,
    segment_size: int,
) -> tuple[str, list[str]]:
    work = repository.import_reference_work(
        project_id,
        ImportReferenceWorkRequest(
            title=f"自有作品 {marker}",
            source_filename=f"{marker}.txt",
            rights_basis=ReferenceRightsBasis.SELF_OWNED,
            segment_target_characters=segment_size,
            content=_content(size, marker),
        ),
    )
    return work.id, [segment.id for segment in work.segments]


def _abstract_evidence(
    *, work_id: str, segment_id: str, work_title: str, ordinal: int
) -> CraftPatternEvidence:
    return CraftPatternEvidence(
        id=str(uuid4()),
        work_id=work_id,
        work_title=work_title,
        segment_id=segment_id,
        stage_label=f"第 {ordinal} 阶段",
        chapter_label=None,
        absolute_start_char=ordinal * 10,
        absolute_end_char=ordinal * 10 + 8,
        evidence_summary=f"阶段 {ordinal} 的抽象证据功能",
        evidence_sha256=sha256(f"evidence-{segment_id}".encode()).hexdigest(),
        confidence=0.9,
    )


def _abstract_material(
    title: str, evidences: list[CraftPatternEvidence]
) -> CraftPatternMaterial:
    dimensions = list(CraftPatternDimension)
    return CraftPatternMaterial(
        title=title,
        summary="仅含结构化抽象规律",
        craft_items=[
            CraftPatternItem(
                dimension=dimension,
                name=f"{title}-{dimension.value}",
                observation=f"{dimension.value} abstract observation",
                transferable_rule=f"{dimension.value} transferable rule",
                adaptation_risk=f"{dimension.value} adaptation risk",
                evidence=(
                    evidences[index :: len(dimensions)]
                    or [evidences[index % len(evidences)]]
                ),
            )
            for index, dimension in enumerate(dimensions)
        ],
    )


def _materialize_abstract_book(
    repository: ProjectRepository,
    project_id: str,
    *,
    segment_count: int,
    marker: str,
) -> CraftPatternAsset:
    assets = CraftPatternRepository(repository.database)
    work_id = str(uuid4())
    work_title = f"已净化作品 {marker}"
    segment_ids = [str(uuid4()) for _ in range(segment_count)]
    evidences = [
        _abstract_evidence(
            work_id=work_id,
            segment_id=segment_id,
            work_title=work_title,
            ordinal=index,
        )
        for index, segment_id in enumerate(segment_ids, start=1)
    ]
    stage_assets = []
    for index, (segment_id, evidence) in enumerate(
        zip(segment_ids, evidences, strict=True), start=1
    ):
        stage_assets.append(
            assets.materialize_and_link(
                project_id=project_id,
                asset_type=CraftPatternAssetType.STAGE,
                generation_fingerprint_sha256=sha256(
                    f"{marker}-stage-{index}".encode()
                ).hexdigest(),
                source_fingerprint_sha256=sha256(
                    f"{marker}-source-{index}".encode()
                ).hexdigest(),
                source_job_id=None,
                output_ordinal=index - 1,
                source_work_ids=[work_id],
                source_segment_ids=[segment_id],
                source_asset_version_ids=[],
                material=_abstract_material(f"阶段 {index}", [evidence]),
                author_focus="",
                provider="test",
                provider_profile_id=None,
                profile_revision=None,
                model="abstract-fixture",
            )
        )
    return assets.materialize_and_link(
        project_id=project_id,
        asset_type=CraftPatternAssetType.BOOK_EVOLUTION,
        generation_fingerprint_sha256=sha256(f"{marker}-book".encode()).hexdigest(),
        source_fingerprint_sha256=sha256(
            f"{marker}-book-source".encode()
        ).hexdigest(),
        source_job_id=None,
        output_ordinal=segment_count,
        source_work_ids=[work_id],
        source_segment_ids=segment_ids,
        source_asset_version_ids=[asset.id for asset in stage_assets],
        material=_abstract_material(f"单书 {marker}", evidences),
        author_focus="",
        provider="test",
        provider_profile_id=None,
        profile_revision=None,
        model="abstract-fixture",
    )


@pytest.mark.parametrize(
    ("size", "segment_size", "expected_stages", "expected_calls"),
    [
        (30_000, 100_000, 1, 3),
        (500_000, 500_000, 1, 12),
        (3_000_000, 500_000, 6, 67),
    ],
)
def test_preflight_plans_long_work_at_three_levels(
    tmp_path: Path,
    size: int,
    segment_size: int,
    expected_stages: int,
    expected_calls: int,
) -> None:
    repository, _jobs, service, _runtime, _gateway, project_id = _system(
        tmp_path / f"plan-{size}.db"
    )
    _work_id, segment_ids = _import(
        repository,
        project_id,
        size=size,
        marker="A",
        segment_size=segment_size,
    )

    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )

    assert preview.stage_card_count == expected_stages
    assert preview.book_evolution_count == 1
    assert preview.map_calls == expected_calls - expected_stages - 1
    assert preview.planned_calls == expected_calls
    assert preview.uncached_calls == expected_calls


def test_analysis_is_single_work_and_materializes_stage_then_book(
    tmp_path: Path,
) -> None:
    repository, jobs, service, runtime, gateway, project_id = _system(
        tmp_path / "analysis.db"
    )
    _first_work, first_ids = _import(
        repository, project_id, size=60_000, marker="A", segment_size=100_000
    )
    _second_work, second_ids = _import(
        repository, project_id, size=60_000, marker="B", segment_size=100_000
    )
    with pytest.raises(InvalidCraftPatternError, match="single_work_required"):
        service.preview_analysis(
            project_id,
            CraftPatternAnalysisPreviewRequest(
                selected_segment_ids=[first_ids[0], second_ids[0]]
            ),
        )

    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=first_ids),
    )
    job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=first_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )
    assert job.workflow == CRAFT_ANALYSIS_WORKFLOW
    assert runtime.run_once() is True
    assert jobs.get_job(job.id).state == JobState.SUCCEEDED
    assets = CraftPatternRepository(repository.database).get_job_assets(job.id)
    assert [asset.asset_type.value for asset in assets] == ["stage", "book_evolution"]
    assert assets[1].source_asset_version_ids == [assets[0].id]
    assert gateway.call_count == preview.uncached_calls
    with repository.database.connect() as connection:
        persisted = "\n".join(
            str(row[0])
            for row in connection.execute(
                "SELECT craft_items_json FROM craft_pattern_assets"
            ).fetchall()
        )
    assert "evidence_text" not in persisted
    assert _content(60_000, "A")[:100] not in persisted


def test_full_cache_needs_no_consent_and_focus_reuses_only_map(
    tmp_path: Path,
) -> None:
    repository, jobs, service, runtime, gateway, project_id = _system(
        tmp_path / "cache.db"
    )
    _work, segment_ids = _import(
        repository, project_id, size=120_000, marker="A", segment_size=500_000
    )
    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    first = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )
    runtime.run_once()
    assert jobs.get_job(first.id).state == JobState.SUCCEEDED
    calls = gateway.call_count

    full_hit = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    assert full_hit.uncached_calls == 0
    assert full_hit.estimated_cost_microusd == 0
    cached_job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            expected_preflight_sha256=full_hit.preflight_sha256,
        ),
    )
    runtime.run_once()
    assert jobs.get_job(cached_job.id).state == JobState.SUCCEEDED
    assert gateway.call_count == calls

    changed_focus = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(
            selected_segment_ids=segment_ids,
            author_focus="重点观察情绪兑现",
        ),
    )
    assert changed_focus.cache_hit_calls == changed_focus.map_calls
    assert changed_focus.uncached_calls == 2


def test_fusion_uses_immutable_assets_after_raw_sources_are_purged(
    tmp_path: Path,
) -> None:
    repository, jobs, service, runtime, gateway, project_id = _system(
        tmp_path / "fusion.db"
    )
    book_assets = []
    work_ids = []
    for marker in ("A", "B"):
        work_id, segment_ids = _import(
            repository, project_id, size=60_000, marker=marker, segment_size=100_000
        )
        work_ids.append(work_id)
        preview = service.preview_analysis(
            project_id,
            CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
        )
        job = service.submit_analysis(
            project_id,
            SubmitCraftPatternAnalysisRequest(
                selected_segment_ids=segment_ids,
                confirm_external_processing=True,
                max_estimated_cost_microusd=preview.estimated_cost_microusd,
                expected_preflight_sha256=preview.preflight_sha256,
            ),
        )
        runtime.run_once()
        book_assets.append(CraftPatternRepository(repository.database).get_job_assets(job.id)[1])
    for work_id in work_ids:
        repository.purge_reference_work(work_id)

    fusion_preview = service.preview_fusion(
        project_id,
        CraftPatternFusionPreviewRequest(
            selected_asset_version_ids=[asset.id for asset in book_assets]
        ),
    )
    fusion_job = service.submit_fusion(
        project_id,
        SubmitCraftPatternFusionRequest(
            selected_asset_version_ids=[asset.id for asset in book_assets],
            confirm_external_processing=True,
            max_estimated_cost_microusd=fusion_preview.estimated_cost_microusd,
            expected_preflight_sha256=fusion_preview.preflight_sha256,
        ),
    )
    assert fusion_job.workflow == CRAFT_FUSION_WORKFLOW
    assert runtime.run_once() is True
    assert jobs.get_job(fusion_job.id).state == JobState.SUCCEEDED
    fusion_assets = CraftPatternRepository(repository.database).get_job_assets(fusion_job.id)
    assert [asset.asset_type.value for asset in fusion_assets] == ["fusion_material"]
    fusion_context = gateway.contexts[-1]
    assert "reference_text" not in fusion_context
    assert _content(60_000, "A")[:100] not in fusion_context


def test_v13_archive_restores_asset_parent_closure_without_raw_text(
    tmp_path: Path,
) -> None:
    repository, _jobs, service, runtime, _gateway, project_id = _system(
        tmp_path / "archive-source.db"
    )
    work_id, segment_ids = _import(
        repository, project_id, size=60_000, marker="A", segment_size=100_000
    )
    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )
    runtime.run_once()
    repository.purge_reference_work(work_id)
    archive_service = ProjectArchiveService(repository.database)
    archive = archive_service.export_project(project_id)
    assert archive["format_version"] == 15
    assert archive["tables"]["reference_works"] == []
    assert len(archive["tables"]["craft_pattern_assets"]) == 2

    restored_same = archive_service.import_project(canonical_json(archive))
    same_assets = CraftPatternRepository(repository.database).get_assets_for_project(
        restored_same
    )
    assert len(same_assets) == 2

    fresh_database = Database(tmp_path / "archive-fresh.db")
    fresh_database.initialize()
    restored_fresh = ProjectArchiveService(fresh_database).import_project(
        canonical_json(archive)
    )
    fresh_assets = CraftPatternRepository(fresh_database).get_assets_for_project(
        restored_fresh
    )
    assert len(fresh_assets) == 2
    book = next(asset for asset in fresh_assets if asset.asset_type.value == "book_evolution")
    stage = next(asset for asset in fresh_assets if asset.asset_type.value == "stage")
    assert book.source_asset_version_ids == [stage.id]


def test_worker_validates_all_promised_cache_hits_before_any_billable_call(
    tmp_path: Path,
) -> None:
    repository, jobs, service, runtime, gateway, project_id = _system(
        tmp_path / "promised-cache-race.db"
    )
    _work_id, segment_ids = _import(
        repository, project_id, size=220_000, marker="A", segment_size=100_000
    )
    initial_preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    initial_job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=initial_preview.estimated_cost_microusd,
            expected_preflight_sha256=initial_preview.preflight_sha256,
        ),
    )
    runtime.run_once()
    assert jobs.get_job(initial_job.id).state == JobState.SUCCEEDED
    initial_nodes = jobs.load_input(initial_job.id)["nodes"]
    stage_nodes = [node for node in initial_nodes if node["level"] == "segment"]
    assert len(stage_nodes) >= 2
    book_node = next(node for node in initial_nodes if node["level"] == "book")
    with repository.database.connect() as connection:
        connection.execute(
            "DELETE FROM reference_analysis_cache WHERE cache_key IN (?, ?)",
            (stage_nodes[0]["cache_key"], book_node["cache_key"]),
        )

    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )
    planned_nodes = jobs.load_input(job.id)["nodes"]
    first_miss = next(
        index
        for index, node in enumerate(planned_nodes)
        if not node["promised_cache_hit"]
    )
    later_hit = next(
        node
        for node in planned_nodes[first_miss + 1 :]
        if node["promised_cache_hit"]
    )
    with repository.database.connect() as connection:
        connection.execute(
            "DELETE FROM reference_analysis_cache WHERE cache_key = ?",
            (later_hit["cache_key"],),
        )
    calls_before = gateway.call_count

    assert runtime.run_once() is True
    failed = jobs.get_job(job.id)
    assert failed.state == JobState.FAILED
    assert failed.error_code == "preflight_cache_changed"
    assert gateway.call_count == calls_before


def test_unpromised_invalid_cache_is_ignored_and_confirmed_miss_runs(
    tmp_path: Path,
) -> None:
    repository, jobs, service, runtime, gateway, project_id = _system(
        tmp_path / "surprise-cache.db"
    )
    work_id, segment_ids = _import(
        repository, project_id, size=30_000, marker="A", segment_size=100_000
    )
    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )
    first_node = jobs.load_input(job.id)["nodes"][0]
    repository.put_reference_analysis_cache(
        cache_key=first_node["cache_key"],
        asset_level=first_node["level"],
        reference_work_id=work_id,
        source_fingerprint_sha256=first_node["source_fingerprint_sha256"],
        prompt_version="craft-pattern-v2",
        provider=job.provider,
        model=job.model,
        payload="{}",
        metadata={"schema_version": 2},
        source_work_ids=[work_id],
    )

    assert runtime.run_once() is True
    completed_job = jobs.get_job(job.id)
    assert completed_job.state == JobState.SUCCEEDED, (
        completed_job.error_code,
        completed_job.error_message,
    )
    assert gateway.call_count == preview.planned_calls
    repaired = repository.get_reference_analysis_cache(first_node["cache_key"])
    assert repaired is not None
    assert repaired.payload != "{}"


def test_purge_during_provider_call_stops_further_calls_and_persistence(
    tmp_path: Path,
) -> None:
    repository, jobs, service, runtime, gateway, project_id = _system(
        tmp_path / "purge-race.db"
    )
    work_id, segment_ids = _import(
        repository, project_id, size=120_000, marker="A", segment_size=500_000
    )
    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )
    gateway.on_call = lambda call_number: (
        repository.purge_reference_work(work_id) if call_number == 1 else None
    )

    assert runtime.run_once() is True
    failed = jobs.get_job(job.id)
    assert failed.state == JobState.FAILED
    assert failed.error_code == "craft_source_changed"
    assert gateway.call_count == 1
    assert CraftPatternRepository(repository.database).get_job_assets(job.id) == []
    assert jobs.get_job_detail(job.id).artifacts == []
    with repository.database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM reference_analysis_cache"
        ).fetchone()[0] == 0


def test_fusion_rejects_output_that_omits_a_selected_source_work(
    tmp_path: Path,
) -> None:
    repository, jobs, service, runtime, gateway, project_id = _system(
        tmp_path / "fusion-coverage.db"
    )
    book_assets = []
    for marker in ("A", "B"):
        _work_id, segment_ids = _import(
            repository, project_id, size=30_000, marker=marker, segment_size=100_000
        )
        preview = service.preview_analysis(
            project_id,
            CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
        )
        job = service.submit_analysis(
            project_id,
            SubmitCraftPatternAnalysisRequest(
                selected_segment_ids=segment_ids,
                confirm_external_processing=True,
                max_estimated_cost_microusd=preview.estimated_cost_microusd,
                expected_preflight_sha256=preview.preflight_sha256,
            ),
        )
        runtime.run_once()
        book_assets.append(
            CraftPatternRepository(repository.database).get_job_assets(job.id)[1]
        )
    fusion_preview = service.preview_fusion(
        project_id,
        CraftPatternFusionPreviewRequest(
            selected_asset_version_ids=[asset.id for asset in book_assets]
        ),
    )
    gateway.fusion_first_source_only = True
    fusion_job = service.submit_fusion(
        project_id,
        SubmitCraftPatternFusionRequest(
            selected_asset_version_ids=[asset.id for asset in book_assets],
            confirm_external_processing=True,
            max_estimated_cost_microusd=fusion_preview.estimated_cost_microusd,
            expected_preflight_sha256=fusion_preview.preflight_sha256,
        ),
    )

    assert runtime.run_once() is True
    failed = jobs.get_job(fusion_job.id)
    assert failed.state == JobState.FAILED
    assert failed.error_code == "invalid_response"
    assert CraftPatternRepository(repository.database).get_job_assets(fusion_job.id) == []
    assert jobs.get_job_detail(fusion_job.id).artifacts == []
    fusion_node = jobs.load_input(fusion_job.id)["nodes"][0]
    assert repository.get_reference_analysis_cache(fusion_node["cache_key"]) is None


def test_promised_fusion_cache_rejects_forged_evidence_with_valid_id(
    tmp_path: Path,
) -> None:
    repository, jobs, service, runtime, gateway, project_id = _system(
        tmp_path / "forged-fusion-cache.db"
    )
    book_assets = []
    for marker in ("A", "B"):
        _work_id, segment_ids = _import(
            repository, project_id, size=30_000, marker=marker, segment_size=100_000
        )
        preview = service.preview_analysis(
            project_id,
            CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
        )
        job = service.submit_analysis(
            project_id,
            SubmitCraftPatternAnalysisRequest(
                selected_segment_ids=segment_ids,
                confirm_external_processing=True,
                max_estimated_cost_microusd=preview.estimated_cost_microusd,
                expected_preflight_sha256=preview.preflight_sha256,
            ),
        )
        runtime.run_once()
        book_assets.append(
            CraftPatternRepository(repository.database).get_job_assets(job.id)[1]
        )
    request = CraftPatternFusionPreviewRequest(
        selected_asset_version_ids=[asset.id for asset in book_assets]
    )
    preview = service.preview_fusion(project_id, request)
    first = service.submit_fusion(
        project_id,
        SubmitCraftPatternFusionRequest(
            selected_asset_version_ids=request.selected_asset_version_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )
    runtime.run_once()
    assert jobs.get_job(first.id).state == JobState.SUCCEEDED
    cached_preview = service.preview_fusion(project_id, request)
    assert cached_preview.uncached_calls == 0
    cached_job = service.submit_fusion(
        project_id,
        SubmitCraftPatternFusionRequest(
            selected_asset_version_ids=request.selected_asset_version_ids,
            expected_preflight_sha256=cached_preview.preflight_sha256,
        ),
    )
    node = jobs.load_input(cached_job.id)["nodes"][0]
    with repository.database.connect() as connection:
        payload = json.loads(
            connection.execute(
                "SELECT payload_json FROM reference_analysis_cache WHERE cache_key = ?",
                (node["cache_key"],),
            ).fetchone()[0]
        )
        payload["craft_items"][0]["evidence"][0]["work_title"] = "伪造来源标题"
        connection.execute(
            "UPDATE reference_analysis_cache SET payload_json = ? WHERE cache_key = ?",
            (json.dumps(payload, ensure_ascii=False), node["cache_key"]),
        )
    calls_before = gateway.call_count

    assert runtime.run_once() is True
    failed = jobs.get_job(cached_job.id)
    assert failed.state == JobState.FAILED
    assert failed.error_code == "preflight_cache_changed"
    assert gateway.call_count == calls_before
    assert CraftPatternRepository(repository.database).get_job_assets(cached_job.id) == []


def test_submit_rejects_pricing_cache_and_source_drift_without_creating_job(
    tmp_path: Path,
) -> None:
    repository, jobs, service, _runtime, gateway, project_id = _system(
        tmp_path / "preflight-drift.db"
    )
    work_id, segment_ids = _import(
        repository, project_id, size=30_000, marker="A", segment_size=100_000
    )
    request = CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids)

    pricing_preview = service.preview_analysis(project_id, request)
    gateway.input_cost_microusd_per_million += 1
    with pytest.raises(InvalidCraftPatternError, match="preflight_changed"):
        service.submit_analysis(
            project_id,
            SubmitCraftPatternAnalysisRequest(
                selected_segment_ids=segment_ids,
                confirm_external_processing=True,
                max_estimated_cost_microusd=pricing_preview.estimated_cost_microusd,
                expected_preflight_sha256=pricing_preview.preflight_sha256,
            ),
        )
    gateway.input_cost_microusd_per_million -= 1

    cache_preview = service.preview_analysis(project_id, request)
    planned = service._plan_analysis(project_id, request)
    node = planned.nodes[0]
    repository.put_reference_analysis_cache(
        cache_key=node.cache_key,
        asset_level=node.level,
        reference_work_id=work_id,
        source_fingerprint_sha256=node.source_fingerprint_sha256,
        prompt_version="craft-pattern-v2",
        provider="openai",
        model="craft-test-v2",
        payload="{}",
        metadata={"schema_version": 2},
        source_work_ids=[work_id],
    )
    with pytest.raises(InvalidCraftPatternError, match="preflight_changed"):
        service.submit_analysis(
            project_id,
            SubmitCraftPatternAnalysisRequest(
                selected_segment_ids=segment_ids,
                confirm_external_processing=True,
                max_estimated_cost_microusd=cache_preview.estimated_cost_microusd,
                expected_preflight_sha256=cache_preview.preflight_sha256,
            ),
        )
    with repository.database.connect() as connection:
        connection.execute("DELETE FROM reference_analysis_cache")

    source_preview = service.preview_analysis(project_id, request)
    with repository.database.connect() as connection:
        current = connection.execute(
            "SELECT content FROM reference_segments WHERE id = ?", (segment_ids[0],)
        ).fetchone()[0]
        changed = ("Z" if current[0] != "Z" else "Y") + current[1:]
        connection.execute(
            "UPDATE reference_segments SET content = ? WHERE id = ?",
            (changed, segment_ids[0]),
        )
    with pytest.raises(InvalidCraftPatternError, match="preflight_changed"):
        service.submit_analysis(
            project_id,
            SubmitCraftPatternAnalysisRequest(
                selected_segment_ids=segment_ids,
                confirm_external_processing=True,
                max_estimated_cost_microusd=source_preview.estimated_cost_microusd,
                expected_preflight_sha256=source_preview.preflight_sha256,
            ),
        )
    assert jobs.list_jobs(project_id) == []
    assert gateway.call_count == 0


def test_unknown_price_requires_explicit_confirmation_but_full_hit_costs_zero(
    tmp_path: Path,
) -> None:
    repository, jobs, service, runtime, gateway, project_id = _system(
        tmp_path / "unknown-price.db"
    )
    gateway.input_cost_microusd_per_million = None
    gateway.output_cost_microusd_per_million = None
    _work_id, segment_ids = _import(
        repository, project_id, size=30_000, marker="A", segment_size=100_000
    )
    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    assert preview.estimated_cost_microusd is None
    with pytest.raises(InvalidCraftPatternError, match="unknown_cost_not_confirmed"):
        service.submit_analysis(
            project_id,
            SubmitCraftPatternAnalysisRequest(
                selected_segment_ids=segment_ids,
                confirm_external_processing=True,
                expected_preflight_sha256=preview.preflight_sha256,
            ),
        )
    job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            confirm_external_processing=True,
            confirm_unknown_cost=True,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )
    runtime.run_once()
    assert jobs.get_job(job.id).state == JobState.SUCCEEDED

    cached = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    assert cached.uncached_calls == 0
    assert cached.estimated_cost_microusd == 0
    cached_job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            expected_preflight_sha256=cached.preflight_sha256,
        ),
    )
    runtime.run_once()
    assert jobs.get_job(cached_job.id).state == JobState.SUCCEEDED


def test_fusion_preflight_rejects_source_union_beyond_asset_schema_limit(
    tmp_path: Path,
) -> None:
    repository, jobs, service, _runtime, gateway, project_id = _system(
        tmp_path / "fusion-source-limit.db"
    )
    first = _materialize_abstract_book(
        repository, project_id, segment_count=33, marker="A"
    )
    second = _materialize_abstract_book(
        repository, project_id, segment_count=33, marker="B"
    )

    with pytest.raises(InvalidCraftPatternError, match="selection_too_large"):
        service.preview_fusion(
            project_id,
            CraftPatternFusionPreviewRequest(
                selected_asset_version_ids=[first.id, second.id]
            ),
        )
    assert jobs.list_jobs(project_id) == []
    assert gateway.call_count == 0


def test_analysis_materializes_book_with_more_than_thirty_stage_parents(
    tmp_path: Path,
) -> None:
    repository, jobs, service, runtime, _gateway, project_id = _system(
        tmp_path / "many-stages.db"
    )
    _work_id, segment_ids = _import(
        repository,
        project_id,
        size=3_100_000,
        marker="A",
        segment_size=100_000,
    )
    assert len(segment_ids) == 31
    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )

    assert runtime.run_once() is True
    completed_job = jobs.get_job(job.id)
    assert completed_job.state == JobState.SUCCEEDED, (
        completed_job.error_code,
        completed_job.error_message,
    )
    assets = CraftPatternRepository(repository.database).get_job_assets(job.id)
    book = next(asset for asset in assets if asset.asset_type == CraftPatternAssetType.BOOK_EVOLUTION)
    assert len(book.source_asset_version_ids) == 31
    archive = ProjectArchiveService(repository.database).export_project(project_id)
    assert archive["format_version"] == 15
    assert len(archive["tables"]["craft_pattern_assets"]) == 32


def test_asset_lifecycle_global_summary_and_cross_project_reuse_survive_purge(
    tmp_path: Path,
) -> None:
    repository, _jobs, service, runtime, _gateway, project_id = _system(
        tmp_path / "asset-lifecycle.db"
    )
    work_id, segment_ids = _import(
        repository, project_id, size=30_000, marker="A", segment_size=100_000
    )
    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )
    runtime.run_once()
    assets = CraftPatternRepository(repository.database)
    book = assets.get_job_assets(job.id)[1]
    archived = assets.update_lifecycle(
        project_id,
        book.id,
        UpdateCraftPatternLifecycleRequest(
            state=CraftPatternLifecycleState.ARCHIVED,
            expected_lifecycle_revision=0,
        ),
    )
    assert archived.lifecycle_state == CraftPatternLifecycleState.ARCHIVED
    with pytest.raises(StaleRevisionError, match="1"):
        assets.update_lifecycle(
            project_id,
            book.id,
            UpdateCraftPatternLifecycleRequest(
                state=CraftPatternLifecycleState.ACTIVE,
                expected_lifecycle_revision=0,
            ),
        )
    repository.purge_reference_work(work_id)
    active = assets.update_lifecycle(
        project_id,
        book.id,
        UpdateCraftPatternLifecycleRequest(
            state=CraftPatternLifecycleState.ACTIVE,
            expected_lifecycle_revision=1,
        ),
    )
    assert active.lifecycle_revision == 2

    second_project = repository.create_project(
        CreateProjectRequest(
            title="跨项目复用",
            genre=Genre.EASTERN_FANTASY,
            rebirth_year=0,
            rebirth_location="九州",
        )
    ).project.id
    reused = assets.reuse(second_project, book.id)
    assert reused.content_sha256 == book.content_sha256
    assert reused.lifecycle_state == CraftPatternLifecycleState.ACTIVE
    global_page = assets.list_global_summaries(
        for_project_id=second_project,
        asset_type=CraftPatternAssetType.BOOK_EVOLUTION,
        work_id=None,
        limit=20,
        offset=0,
    )
    summary = next(item for item in global_page.items if item.id == book.id)
    assert summary.content_sha256 == book.content_sha256
    assert summary.lifecycle_state == CraftPatternLifecycleState.ACTIVE
    assert not hasattr(summary, "craft_items")


def test_archive_import_never_runs_or_retries_active_and_failed_craft_jobs(
    tmp_path: Path,
) -> None:
    repository, jobs, service, _runtime, _gateway, project_id = _system(
        tmp_path / "archive-jobs-source.db"
    )
    _work_id, segment_ids = _import(
        repository, project_id, size=30_000, marker="A", segment_size=100_000
    )
    first_preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(
            selected_segment_ids=segment_ids,
            author_focus="queued",
        ),
    )
    _queued = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            author_focus="queued",
            confirm_external_processing=True,
            max_estimated_cost_microusd=first_preview.estimated_cost_microusd,
            expected_preflight_sha256=first_preview.preflight_sha256,
        ),
    )
    second_preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(
            selected_segment_ids=segment_ids,
            author_focus="failed",
        ),
    )
    failed = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            author_focus="failed",
            confirm_external_processing=True,
            max_estimated_cost_microusd=second_preview.estimated_cost_microusd,
            expected_preflight_sha256=second_preview.preflight_sha256,
        ),
    )
    jobs.transition_job(failed.id, JobState.RUNNING, event_type="leased")
    jobs.transition_job(
        failed.id,
        JobState.FAILED,
        event_type="failed",
        error_code="provider_error",
        error_message="safe failure",
    )
    archive = ProjectArchiveService(repository.database).export_project(project_id)

    target_database = Database(tmp_path / "archive-jobs-target.db")
    target_database.initialize()
    restored_project = ProjectArchiveService(target_database).import_project(
        canonical_json(archive)
    )
    target_jobs = JobRepository(target_database)
    restored_jobs = target_jobs.list_jobs(restored_project)
    assert {job.state for job in restored_jobs} == {
        JobState.INTERRUPTED,
        JobState.FAILED,
    }
    assert all(
        job.error_code == "restored_requires_resubmission" for job in restored_jobs
    )
    target_gateway = CraftGateway()
    target_repository = ProjectRepository(target_database)
    target_service = CraftPatternService(
        target_repository,
        target_jobs,
        AiGatewayManager(cast(AiGateway, target_gateway)),
    )
    target_runtime = JobRuntime(
        target_jobs, {JobKind.REFERENCE_FUSION: target_service.handle}
    )
    assert target_runtime.run_once() is False
    assert target_gateway.call_count == 0
    for restored_job in restored_jobs:
        with pytest.raises(JobRequiresNewPreflightError):
            target_jobs.retry_job(restored_job.id)


def test_raw_archive_partial_existing_parent_is_remapped_as_one_closed_graph(
    tmp_path: Path,
) -> None:
    repository, _jobs, service, runtime, _gateway, project_id = _system(
        tmp_path / "partial-closure.db"
    )
    _work_id, segment_ids = _import(
        repository, project_id, size=30_000, marker="A", segment_size=100_000
    )
    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )
    runtime.run_once()
    asset_repository = CraftPatternRepository(repository.database)
    stage, book = asset_repository.get_job_assets(job.id)
    archive_service = ProjectArchiveService(repository.database)
    archive = archive_service.export_project(
        project_id, include_reference_assets=True
    )
    with repository.database.connect() as connection:
        connection.execute(
            "DELETE FROM craft_pattern_job_outputs WHERE asset_version_id = ?",
            (book.id,),
        )
        connection.execute(
            "DELETE FROM project_craft_pattern_assets WHERE asset_version_id = ?",
            (book.id,),
        )
        connection.execute("DELETE FROM craft_pattern_assets WHERE id = ?", (book.id,))

    restored_project = archive_service.import_project(canonical_json(archive))
    restored_assets = asset_repository.get_assets_for_project(restored_project)
    restored_stage = next(
        asset for asset in restored_assets if asset.asset_type == CraftPatternAssetType.STAGE
    )
    restored_book = next(
        asset
        for asset in restored_assets
        if asset.asset_type == CraftPatternAssetType.BOOK_EVOLUTION
    )
    assert restored_stage.id != stage.id
    assert restored_book.id != book.id
    assert restored_book.source_asset_version_ids == [restored_stage.id]
    assert restored_book.source_work_ids != book.source_work_ids


def test_v2_asset_cannot_enter_legacy_application_or_writing_context(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "v2-v1-isolation.db"
    repository, _jobs, service, runtime, _gateway, project_id = _system(database_path)
    _work_id, segment_ids = _import(
        repository, project_id, size=30_000, marker="A", segment_size=100_000
    )
    preview = service.preview_analysis(
        project_id,
        CraftPatternAnalysisPreviewRequest(selected_segment_ids=segment_ids),
    )
    job = service.submit_analysis(
        project_id,
        SubmitCraftPatternAnalysisRequest(
            selected_segment_ids=segment_ids,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
            expected_preflight_sha256=preview.preflight_sha256,
        ),
    )
    runtime.run_once()
    asset = CraftPatternRepository(repository.database).get_job_assets(job.id)[0]

    with TestClient(create_app(database_path, defer_job_runtime=True)) as client:
        rejected = client.post(
            f"/api/projects/{project_id}/reference-pattern-cards/{asset.id}/applications",
            json={
                "selected_dimensions": ["era"],
                "application_note": "不应写入旧应用",
                "confirm_original_adaptation": True,
            },
        )
    assert rejected.status_code == 410
    assert rejected.json()["detail"]["code"] == "reference_v1_read_only"
    workspace = repository.get_workspace(project_id)
    assert workspace.reference_pattern_applications == []
    context = build_chapter_context(workspace, workspace.chapters[0], "")
    assert asset.id not in context
    assert asset.content_sha256 not in context
