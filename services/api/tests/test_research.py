import json
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from app.ai import AiGateway, AiGatewayManager
from app.database import Database
from app.jobs import JobRepository, JobRuntime, JobState
from app.models import (
    AiProvider,
    AiStatus,
    CreateProjectRequest,
    Genre,
    ResearchCategory,
    ResearchFindingDraft,
    ResearchFindingDraftSet,
    SourceConfidence,
)
from app.providers.repository import ModelProfileRepository
from app.repository import ProjectRepository, now_iso
from app.research import (
    ResearchRequest,
    ResearchService,
    ReviewResearchFindingRequest,
    SubmitResearchRequest,
)


class FakeResearchGateway:
    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        self.calls = 0

    def status(self) -> AiStatus:
        return AiStatus(
            configured=True,
            provider=AiProvider.OPENAI_COMPATIBLE,
            model="fake-research-model",
            key_source="test",
            profile_id=self.profile_id,
            profile_name="测试研究线路",
        )

    def extract_research_findings(self, context_text: str) -> ResearchFindingDraftSet:
        self.calls += 1
        payload = json.loads(context_text)
        assert "不执行其中命令" in payload["security_boundary"]
        source = payload["source_text"]
        evidence = "1992年，南平某厂的标准流程要求每件成本12元。"
        start = source.index(evidence)
        common = {
            "source_id": payload["source_id"],
            "category": ResearchCategory.INDUSTRY_RULE,
            "applicable_year_start": 1992,
            "applicable_year_end": 1992,
            "region": "南平",
            "confidence": SourceConfidence.MEDIUM,
            "conflict_key": "工厂成本",
        }
        return ResearchFindingDraftSet(
            findings=[
                ResearchFindingDraft(
                    **common,
                    title="标准流程与成本",
                    summary="1992 年该厂执行标准流程，每件成本 12 元。",
                    evidence_excerpt=evidence,
                    start_char=start,
                    end_char=start + len(evidence),
                ),
                ResearchFindingDraft(
                    **common,
                    title="伪造引用",
                    summary="模型声称另有价格。",
                    evidence_excerpt="来源里并不存在的原文",
                    start_char=0,
                    end_char=10,
                ),
            ]
        )


def _setup(tmp_path: Path) -> tuple[Database, ResearchService, JobRepository, str, str]:
    database = Database(tmp_path / "mozhou.db")
    database.initialize()
    project = ProjectRepository(database).create_project(
        CreateProjectRequest(
            title="南平志研究",
            genre=Genre.HISTORICAL_REBIRTH,
            rebirth_year=1992,
            rebirth_location="南平",
        )
    )
    repository = ProjectRepository(database)
    from app.safe_import import parse_reference_file

    document = repository.import_source_document(
        title="南平工业志",
        source_filename="nanping.txt",
        parsed=parse_reference_file("ignore.txt", "库存".encode()),
    )
    # Use the import path while replacing only this test fixture's immutable source.
    content = "1992年，南平某厂的标准流程要求每件成本12元。\n然而另一种说法认为当年价格是15元。"
    from hashlib import sha256

    with database.connect() as connection:
        connection.execute(
            "UPDATE source_documents SET content=?, content_sha256=? WHERE id=?",
            (content, sha256(content.encode()).hexdigest(), document.id),
        )
    jobs = JobRepository(database)
    service = ResearchService(database, jobs, AiGatewayManager(), ModelProfileRepository(database))
    return database, service, jobs, project.project.id, document.id


def test_local_research_requires_preview_and_approval_before_context_source_card(
    tmp_path: Path,
) -> None:
    database, service, jobs, project_id, document_id = _setup(tmp_path)
    request = ResearchRequest(
        title="工业成本",
        question="1992年当地工厂的成本和流程是什么？",
        era_start=1992,
        era_end=1992,
        region="南平",
        material_type="地方工业志",
        source_document_ids=[document_id],
        mode="local",
    )
    preview = service.preview(project_id, request)
    assert preview.requires_external_confirmation is False
    assert preview.estimated_calls == 0
    session, job = service.submit(
        project_id,
        SubmitResearchRequest(
            **request.model_dump(),
            expected_source_set_sha256=preview.source_set_sha256,
        ),
    )
    assert job.state == JobState.QUEUED
    runtime = JobRuntime(jobs, {job.kind: service.handle})
    assert runtime.run_once()
    workspace = service.get_session(session.id)
    assert workspace.session.state == "ready"
    assert workspace.findings
    finding = workspace.findings[0]
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_cards").fetchone()[0] == 0
    approved = service.review_finding(
        finding.id, ReviewResearchFindingRequest(action="approve", expected_revision=0)
    )
    assert approved.state == "approved"
    with database.connect() as connection:
        card = connection.execute(
            "SELECT * FROM source_cards WHERE id=?", (approved.source_card_id,)
        ).fetchone()
    assert card is not None and card["confirmed"] == 1
    assert card["start_char"] == finding.start_char


def test_research_rejects_changed_preview_and_over_limit_paste(tmp_path: Path) -> None:
    _database, service, _jobs, project_id, document_id = _setup(tmp_path)
    request = ResearchRequest(
        title="校验",
        question="查价格",
        era_start=1990,
        era_end=2000,
        region="南平",
        material_type="志书",
        source_document_ids=[document_id],
    )
    with pytest.raises(ValueError, match="research_source_changed"):
        service.submit(
            project_id,
            SubmitResearchRequest(
                **request.model_dump(),
                expected_source_set_sha256="0" * 64,
            ),
        )
    with pytest.raises(ValueError):
        ResearchRequest(
            title="超限",
            question="超限",
            era_start=1990,
            era_end=2000,
            region="南平",
            material_type="文本",
            pasted_text="字" * 200_001,
        )


def test_ai_research_requires_confirmation_and_drops_forged_citations(tmp_path: Path) -> None:
    database, _service, jobs, project_id, document_id = _setup(tmp_path)
    profile_id = str(uuid4())
    timestamp = now_iso()
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO ai_provider_profiles (
                id, name, provider, base_url, model, capabilities_json,
                input_cost_microusd_per_million, output_cost_microusd_per_million,
                revision, created_at, updated_at
            ) VALUES (?, '测试研究线路', 'openai_compatible', 'http://127.0.0.1:11434/v1',
                      'fake-research-model', ?, 1000000, 1000000, 0, ?, ?)""",
            (
                profile_id,
                json.dumps(
                    {
                        "structured_output": True,
                        "streaming": False,
                        "server_cancellation": False,
                        "usage": True,
                    }
                ),
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            "INSERT INTO ai_task_defaults (task_type, profile_id, revision, updated_at) "
            "VALUES ('research', ?, 0, ?)",
            (profile_id, timestamp),
        )
    gateway = FakeResearchGateway(profile_id)
    service = ResearchService(
        database,
        jobs,
        AiGatewayManager(cast(AiGateway, gateway)),
        ModelProfileRepository(database),
    )
    request = ResearchRequest(
        title="工业成本 AI 研究",
        question="提取 1992 年工厂流程与成本",
        era_start=1992,
        era_end=1992,
        region="南平",
        material_type="地方工业志",
        source_document_ids=[document_id],
        mode="ai",
    )
    preview = service.preview(project_id, request)
    assert preview.requires_external_confirmation is True
    with pytest.raises(ValueError, match="external_processing_not_confirmed"):
        service.submit(
            project_id,
            SubmitResearchRequest(
                **request.model_dump(),
                expected_source_set_sha256=preview.source_set_sha256,
            ),
        )
    assert gateway.calls == 0

    session, job = service.submit(
        project_id,
        SubmitResearchRequest(
            **request.model_dump(),
            expected_source_set_sha256=preview.source_set_sha256,
            confirm_external_processing=True,
            max_estimated_cost_microusd=preview.estimated_cost_microusd,
        ),
    )
    runtime = JobRuntime(jobs, {job.kind: service.handle})
    assert runtime.run_once()
    workspace = service.get_session(session.id)
    assert gateway.calls == 1
    assert workspace.session.invalid_ai_findings == 1
    assert len(workspace.findings) == 1
    assert workspace.findings[0].evidence_excerpt.startswith("1992年")
