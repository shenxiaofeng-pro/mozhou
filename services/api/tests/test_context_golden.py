import json
from pathlib import Path
from typing import Any

import pytest

from app.context import ContextCompiler, ContextTaskType
from app.models import (
    Chapter,
    ChapterStatus,
    FutureKnowledge,
    KnowledgeConfidence,
    Project,
    SourceCard,
    SourceConfidence,
    SourceKind,
    StoryEntity,
    StoryFact,
    StoryThread,
    TimelineEvent,
    Workspace,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "context_golden.json"
GOLDEN_CASES: list[dict[str, Any]] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]
NOW = "2026-08-10T00:00:00+00:00"


def _chapter(project_id: str, number: int, content: str) -> Chapter:
    return Chapter(
        id=f"chapter-{number}",
        project_id=project_id,
        volume_number=1,
        chapter_number=number,
        title=f"第 {number} 章",
        content=content,
        reader_promise=f"第 {number} 章推进主线",
        opening_hook=f"第 {number} 章开场",
        state_change=f"第 {number} 章状态变化",
        emotional_payoff=f"第 {number} 章回报",
        ending_cliffhanger=f"第 {number} 章悬念",
        status=ChapterStatus.DRAFTED,
        revision=number,
        updated_at=NOW,
    )


def _workspace(case: dict[str, Any]) -> Workspace:
    project_id = f"project-{case['name']}"
    project = Project(
        id=project_id,
        title=case["name"],
        genre=case["genre"],
        rebirth_year=case["rebirth_year"],
        rebirth_location=case["rebirth_location"],
        chapter_target_words=3000,
        safety_buffer_chapters=3,
        created_at=NOW,
        updated_at=NOW,
    )
    previous = int(case["previous_chapters"])
    seed = str(case.get("chapter_seed", "南平城里的现实秩序和人物关系继续变化。")) * 60
    chapters = [_chapter(project_id, number, seed) for number in range(1, previous + 2)]
    current = chapters[-1].model_copy(
        update={
            "title": case["current_title"],
            "reader_promise": case["current_state_change"],
            "state_change": case["current_state_change"],
            "ending_cliffhanger": case["current_cliffhanger"],
        }
    )
    chapters[-1] = current
    entities = [
        StoryEntity(
            id=item["id"],
            project_id=project_id,
            kind=item["kind"],
            name=item["name"],
            role="主线对象",
            goal="推进当前主线",
            current_state=item["current_state"],
            relationship_notes="",
            revision=0,
            created_at=NOW,
            updated_at=NOW,
        )
        for item in case["entities"]
    ]
    facts = [
        StoryFact(
            id=item["id"],
            project_id=project_id,
            source_chapter_id=f"chapter-{item['chapter']}",
            kind="state_change",
            content=item["content"],
            created_at=NOW,
        )
        for item in case["facts"]
    ]
    threads = [
        StoryThread(
            id=item["id"],
            project_id=project_id,
            source_chapter_id=f"chapter-{item['planted']}",
            title=item["title"],
            summary=item["summary"],
            status=item["status"],
            planted_chapter_number=item["planted"],
            resolved_chapter_id=(
                f"chapter-{min(previous, item['planted'] + 5)}"
                if item["status"] == "resolved"
                else None
            ),
            revision=0,
            created_at=NOW,
            updated_at=NOW,
        )
        for item in case["threads"]
    ]
    knowledge = [
        FutureKnowledge(
            id=item["id"],
            project_id=project_id,
            future_year=item["future_year"],
            content=item["content"],
            source_note="重生前记忆",
            confidence=KnowledgeConfidence.CERTAIN,
            status=item["status"],
            divergence_event_id=("timeline-novel" if item["status"] != "valid" else None),
            revision=0,
            created_at=NOW,
            updated_at=NOW,
        )
        for item in case["future_knowledge"]
    ]
    timeline = [
        TimelineEvent(
            id=item["id"],
            project_id=project_id,
            layer=item["layer"],
            event_year=item["event_year"],
            title=item["title"],
            summary=item["summary"],
            source_chapter_id=(
                f"chapter-{item['source_chapter']}" if item.get("source_chapter") else None
            ),
            created_at=NOW,
        )
        for item in case["timeline"]
    ]
    sources = [
        SourceCard(
            id=item["id"],
            project_id=project_id,
            source_kind=SourceKind.HISTORICAL_RECORD,
            title=item["title"],
            source_reference="黄金集本地资料卡",
            applicable_year_start=case["rebirth_year"] - 1,
            applicable_year_end=case["rebirth_year"] + 1,
            confidence=SourceConfidence.HIGH,
            excerpt=item["excerpt"],
            confirmed=item["confirmed"],
            revision=0,
            created_at=NOW,
            updated_at=NOW,
        )
        for item in case["sources"]
    ]
    return Workspace(
        project=project,
        chapters=chapters,
        story_entities=entities,
        story_facts=facts,
        story_threads=threads,
        future_knowledge=knowledge,
        timeline_events=timeline,
        source_cards=sources,
    )


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: str(case["name"]))
def test_context_golden_recall_and_hard_constraint_omissions(case: dict[str, Any]) -> None:
    workspace = _workspace(case)
    packet = ContextCompiler().compile(
        workspace,
        workspace.chapters[-1],
        author_intent=case["author_intent"],
        task_type=ContextTaskType.CHAPTER_DRAFT,
        token_budget=case["token_budget"],
    )
    selected_sources = {
        f"{item.source_refs[0].kind}:{item.source_refs[0].source_id}"
        for item in packet.items
        if item.included and item.source_refs
    }
    expected_relevant = set(case["expected_relevant_sources"])
    expected_hard = set(case["expected_hard_sources"])
    must_exclude = set(case["must_exclude_sources"])
    recall = len(selected_sources & expected_relevant) / len(expected_relevant)
    hard_omissions = expected_hard - selected_sources

    assert recall >= 0.95
    assert hard_omissions == set()
    assert selected_sources.isdisjoint(must_exclude)
    assert packet.used_tokens <= packet.token_budget
    if case.get("expect_divergence_note", True):
        assert any("不代表小说分歧后" in note for note in packet.conflict_notes)

    for source_key in expected_hard:
        source_kind, source_id = source_key.split(":", 1)
        item = next(
            item
            for item in packet.items
            if item.source_refs
            and item.source_refs[0].kind == source_kind
            and item.source_refs[0].source_id == source_id
        )
        assert item.required
        assert item.included
