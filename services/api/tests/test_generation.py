from pathlib import Path

import pytest

from app.creative_safety import CreativeSafetyProvenance
from app.database import Database
from app.generation import GenerationService
from app.models import (
    ChapterStatus,
    CreateProjectRequest,
    GenerationState,
    Genre,
    TransitionChapterRequest,
    UpdateChapterBriefRequest,
    UpdateChapterRequest,
)
from app.repository import (
    InvalidChapterStateError,
    OriginalityGateBlockedError,
    ProjectRepository,
    StaleRevisionError,
)


class MutableCreativeSafetyGate:
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


def _safety(project_id: str, token: str) -> CreativeSafetyProvenance:
    return CreativeSafetyProvenance(
        project_id=project_id,
        mode="pattern_adaptation",
        fingerprint_sha256=token * 64,
    )


@pytest.fixture
def generation_setup(tmp_path: Path) -> tuple[Database, ProjectRepository, str]:
    database = Database(tmp_path / "mozhou.db")
    database.initialize()
    repository = ProjectRepository(database)
    workspace = repository.create_project(
        CreateProjectRequest(
            title="回到九八年的南平",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    return database, repository, workspace.chapters[0].id


def test_fake_generation_persists_recoverable_state_events(
    generation_setup: tuple[Database, ProjectRepository, str],
) -> None:
    database, repository, chapter_id = generation_setup

    run = GenerationService(repository).start(chapter_id, expected_revision=0)

    assert run.state == GenerationState.DRAFTED
    assert run.candidate_content is not None
    assert "1998年的慢车驶进福建南平" in run.candidate_content
    with database.connect() as connection:
        events = connection.execute(
            "SELECT state FROM run_events WHERE run_id = ? ORDER BY sequence",
            (run.id,),
        ).fetchall()
    assert [event["state"] for event in events] == ["context_ready", "generating", "drafted"]


def test_demo_generation_and_apply_reject_stale_frozen_creative_safety(
    generation_setup: tuple[Database, ProjectRepository, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _database, repository, chapter_id = generation_setup
    project_id = repository.get_workspace_for_chapter(chapter_id).project.id
    gate = MutableCreativeSafetyGate(_safety(project_id, "a"))
    repository.set_creative_safety_gate(gate)
    queued = repository.create_generation_run(chapter_id, expected_revision=0)

    calls = 0

    def counted_demo_draft(context: object) -> str:
        nonlocal calls
        del context
        calls += 1
        return "不应生成"

    monkeypatch.setattr("app.generation.generate_demo_draft", counted_demo_draft)
    gate.current = _safety(project_id, "b")
    with pytest.raises(OriginalityGateBlockedError, match="creative_safety_changed"):
        GenerationService(repository).resume(queued.id)
    assert calls == 0
    assert repository.get_generation_run(queued.id).state == GenerationState.CONTEXT_READY

    interrupted = repository.transition_generation(
        queued.id,
        GenerationState.CONTEXT_READY,
        GenerationState.INTERRUPTED,
        error_message="安全依赖变化",
    )
    assert interrupted.state == GenerationState.INTERRUPTED

    gate.current = _safety(project_id, "a")
    candidate = repository.materialize_generation_run(
        "frozen-candidate",
        chapter_id,
        0,
        "冻结候选正文",
        "test",
        "test",
        creative_safety=gate.current,
    )
    gate.current = _safety(project_id, "b")
    with pytest.raises(OriginalityGateBlockedError, match="creative_safety_changed"):
        repository.apply_generation(candidate.id, expected_revision=0)
    assert repository.get_chapter(chapter_id).content == ""


@pytest.mark.parametrize(
    ("genre", "title", "story_year", "story_location", "expected_scene"),
    [
        (Genre.EASTERN_FANTASY, "万山问道", 728, "九州云泽", "测灵碑"),
        (Genre.WESTERN_FANTASY, "灰塔之誓", 1243, "阿尔登北境", "法师塔"),
    ],
)
def test_fake_generation_uses_fantasy_worlds_without_forcing_rebirth(
    tmp_path: Path,
    genre: Genre,
    title: str,
    story_year: int,
    story_location: str,
    expected_scene: str,
) -> None:
    database = Database(tmp_path / f"{genre.value}.db")
    database.initialize()
    repository = ProjectRepository(database)
    workspace = repository.create_project(
        CreateProjectRequest(
            title=title,
            genre=genre,
            rebirth_year=story_year,
            rebirth_location=story_location,
        )
    )

    run = GenerationService(repository).start(
        workspace.chapters[0].id,
        expected_revision=0,
    )

    assert run.candidate_content is not None
    assert expected_scene in run.candidate_content
    assert "上一世" not in run.candidate_content
    assert "这一世" not in run.candidate_content


def test_context_ready_run_can_resume_after_restart(
    generation_setup: tuple[Database, ProjectRepository, str],
) -> None:
    _, repository, chapter_id = generation_setup
    created = repository.create_generation_run(chapter_id, expected_revision=0)

    resumed = GenerationService(repository).resume(created.id)

    assert resumed.state == GenerationState.DRAFTED
    assert resumed.candidate_content


def test_fake_generation_reads_saved_chapter_brief(
    generation_setup: tuple[Database, ProjectRepository, str],
) -> None:
    _, repository, chapter_id = generation_setup
    repository.update_chapter_brief(
        chapter_id,
        UpdateChapterBriefRequest(
            opening_hook="洪水预警只剩六小时",
            state_change="说服父亲调走仓库物资",
            ending_cliffhanger="失踪多年的舅舅打来电话",
            expected_revision=0,
        ),
    )

    run = GenerationService(repository).start(chapter_id, expected_revision=1)

    assert run.candidate_content is not None
    assert "洪水预警只剩六小时" in run.candidate_content
    assert "说服父亲调走仓库物资" in run.candidate_content
    assert "失踪多年的舅舅打来电话" in run.candidate_content


def test_candidate_only_changes_chapter_after_explicit_apply(
    generation_setup: tuple[Database, ProjectRepository, str],
) -> None:
    database, repository, chapter_id = generation_setup
    run = GenerationService(repository).start(chapter_id, expected_revision=0)

    with database.connect() as connection:
        before_apply = connection.execute(
            "SELECT content FROM chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
    applied = repository.apply_generation(run.id, expected_revision=0)

    assert before_apply is not None
    assert before_apply["content"] == ""
    assert applied.content == run.candidate_content
    assert applied.revision == 1
    assert applied.status.value == "drafted"


def test_apply_rejects_stale_candidate_when_request_uses_current_chapter_revision(
    generation_setup: tuple[Database, ProjectRepository, str],
) -> None:
    _, repository, chapter_id = generation_setup
    run = GenerationService(repository).start(chapter_id, expected_revision=0)
    edited = repository.update_chapter(
        chapter_id,
        UpdateChapterRequest(content="作者刚写的新内容", expected_revision=0),
    )

    with pytest.raises(StaleRevisionError):
        repository.apply_generation(run.id, expected_revision=edited.revision)

    unchanged = repository.get_chapter(chapter_id)
    unapplied = repository.get_generation_run(run.id)
    assert unchanged.content == "作者刚写的新内容"
    assert unchanged.revision == 1
    assert unapplied.state == GenerationState.DRAFTED


def test_apply_never_overwrites_approved_chapter_even_when_revisions_match(
    generation_setup: tuple[Database, ProjectRepository, str],
) -> None:
    database, repository, chapter_id = generation_setup
    run = GenerationService(repository).start(chapter_id, expected_revision=0)
    with database.connect() as connection:
        connection.execute(
            "UPDATE chapters SET content = ?, status = ? WHERE id = ?",
            ("作者确认的定稿", ChapterStatus.APPROVED.value, chapter_id),
        )

    with pytest.raises(StaleRevisionError):
        repository.apply_generation(run.id, expected_revision=0)

    unchanged = repository.get_chapter(chapter_id)
    unapplied = repository.get_generation_run(run.id)
    assert unchanged.content == "作者确认的定稿"
    assert unchanged.status == ChapterStatus.APPROVED
    assert unchanged.revision == 0
    assert unapplied.state == GenerationState.DRAFTED


def test_reviewing_chapter_cannot_start_a_new_generation(
    generation_setup: tuple[Database, ProjectRepository, str],
) -> None:
    _, repository, chapter_id = generation_setup
    chapter = repository.update_chapter(
        chapter_id,
        UpdateChapterRequest(content="列车驶进南平站。", expected_revision=0),
    )
    chapter = repository.update_chapter_brief(
        chapter_id,
        UpdateChapterBriefRequest(
            opening_hook="广播突然中断",
            state_change="主角改变原定行程",
            ending_cliffhanger="旧友提前出现",
            expected_revision=chapter.revision,
        ),
    )
    chapter = repository.transition_chapter(
        chapter_id,
        TransitionChapterRequest(
            target_status=ChapterStatus.DRAFTED,
            expected_revision=chapter.revision,
        ),
    )
    chapter = repository.transition_chapter(
        chapter_id,
        TransitionChapterRequest(
            target_status=ChapterStatus.REVIEWING,
            expected_revision=chapter.revision,
        ),
    )

    with pytest.raises(InvalidChapterStateError):
        GenerationService(repository).start(chapter_id, expected_revision=chapter.revision)
