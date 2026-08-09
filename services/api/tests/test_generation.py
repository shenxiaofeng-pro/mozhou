from pathlib import Path

import pytest

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
from app.repository import InvalidChapterStateError, ProjectRepository, StaleRevisionError


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


def test_apply_rejects_chapter_changed_after_generation(
    generation_setup: tuple[Database, ProjectRepository, str],
) -> None:
    _, repository, chapter_id = generation_setup
    run = GenerationService(repository).start(chapter_id, expected_revision=0)
    repository.update_chapter(
        chapter_id,
        UpdateChapterRequest(content="作者刚写的新内容", expected_revision=0),
    )

    with pytest.raises(StaleRevisionError):
        repository.apply_generation(run.id, expected_revision=0)


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
