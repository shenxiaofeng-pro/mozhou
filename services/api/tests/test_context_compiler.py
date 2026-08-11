from pathlib import Path
from time import perf_counter

from app.context import (
    ContextCompiler,
    ContextDirectiveAction,
    ContextDirectiveRequest,
    ContextItemKind,
    ContextRepository,
    ContextTaskType,
)
from app.database import Database
from app.models import (
    Chapter,
    ChapterStatus,
    CreateProjectRequest,
    CreateStoryEntityRequest,
    FutureKnowledge,
    Genre,
    KnowledgeConfidence,
    KnowledgeStatus,
    Project,
    SourceCard,
    SourceConfidence,
    SourceKind,
    StoryEntity,
    StoryEntityKind,
    StoryFact,
    StoryThread,
    StoryThreadStatus,
    TimelineEvent,
    TimelineLayer,
    Workspace,
)
from app.repository import ProjectRepository

NOW = "2026-08-10T00:00:00+00:00"


def _chapter(project_id: str, number: int, *, content: str = "") -> Chapter:
    return Chapter(
        id=f"chapter-{number}",
        project_id=project_id,
        volume_number=1,
        chapter_number=number,
        title=f"第 {number} 章",
        content=content,
        reader_promise=f"兑现第 {number} 章承诺",
        opening_hook=f"第 {number} 章开场异变",
        state_change=f"主角完成第 {number} 次状态推进",
        emotional_payoff=f"第 {number} 次回报落地",
        ending_cliffhanger=f"第 {number} 章留下新问题",
        status=ChapterStatus.DRAFTED,
        revision=number,
        updated_at=f"2026-07-{number % 28 + 1:02d}T00:00:00+00:00",
    )


def _workspace(*, previous_chapters: int = 20, content_characters: int = 1200) -> Workspace:
    project = Project(
        id="project-context",
        title="闽北回潮",
        genre=Genre.URBAN_REBIRTH,
        rebirth_year=1998,
        rebirth_location="福建南平",
        chapter_target_words=3000,
        safety_buffer_chapters=3,
        created_at=NOW,
        updated_at=NOW,
    )
    seed = "南平纸厂的汽笛穿过梅山坡。"
    content = seed * max(1, content_characters // len(seed) + 1)
    chapters = [
        _chapter(project.id, number, content=content[:content_characters])
        for number in range(1, previous_chapters + 2)
    ]
    return Workspace(project=project, chapters=chapters)


def _current(workspace: Workspace) -> Chapter:
    return workspace.chapters[-1]


def test_context_packet_is_deterministic_and_historical_items_have_traceable_ranges() -> None:
    workspace = _workspace(previous_chapters=20)
    compiler = ContextCompiler()

    first = compiler.compile(
        workspace,
        _current(workspace),
        author_intent="让林川先救父亲，再拿下纸厂订单",
        task_type=ContextTaskType.CHAPTER_DRAFT,
        token_budget=12_000,
    )
    second = compiler.compile(
        workspace,
        _current(workspace),
        author_intent="让林川先救父亲，再拿下纸厂订单",
        task_type=ContextTaskType.CHAPTER_DRAFT,
        token_budget=12_000,
    )

    assert first.id == second.id
    assert first.packet_sha256 == second.packet_sha256
    assert first.source_fingerprint_sha256 == second.source_fingerprint_sha256
    assert first.rendered_context == second.rendered_context
    historical = [
        item for item in first.items
        if item.kind in {
            ContextItemKind.RECENT_CHAPTER_EXCERPT,
            ContextItemKind.DISTANT_CHAPTER_SUMMARY,
        }
    ]
    assert historical
    assert all(item.source_refs[0].chapter_number is not None for item in historical)
    assert all(item.source_refs[0].character_start is not None for item in historical)
    assert all(item.source_refs[0].character_end is not None for item in historical)


def test_context_budget_never_silently_drops_hard_constraints() -> None:
    workspace = _workspace(previous_chapters=2)
    compiler = ContextCompiler()

    packet = compiler.compile(
        workspace,
        _current(workspace),
        author_intent="必须保留" * 200,
        task_type=ContextTaskType.CHAPTER_BRIEF,
        token_budget=1000,
    )

    required = [item for item in packet.items if item.required]
    assert required
    assert all(item.included for item in required)
    assert packet.overflow_tokens > 0
    assert packet.used_tokens == packet.token_budget + packet.overflow_tokens


def test_fantasy_context_uses_world_anchor_without_implying_rebirth() -> None:
    workspace = _workspace(previous_chapters=2)
    workspace = workspace.model_copy(
        update={
            "project": workspace.project.model_copy(
                update={
                    "genre": Genre.EASTERN_FANTASY,
                    "rebirth_year": 728,
                    "rebirth_location": "九州云泽",
                }
            )
        }
    )

    packet = ContextCompiler().compile(
        workspace,
        _current(workspace),
        author_intent="让主角承担越境借力的代价",
        task_type=ContextTaskType.CHAPTER_BRIEF,
        token_budget=4000,
    )

    anchor = next(item for item in packet.items if item.kind == ContextItemKind.PROJECT_ANCHOR)
    assert anchor.label == "作品与世界锚点"
    assert "重生" not in anchor.selection_reason


def test_latest_facts_win_budget_and_same_name_entities_keep_distinct_sources() -> None:
    workspace = _workspace(previous_chapters=60, content_characters=20)
    facts = [
        StoryFact(
            id=f"fact-{number}",
            project_id=workspace.project.id,
            source_chapter_id=f"chapter-{number}",
            kind="state_change",
            content=f"第 {number} 章正式状态：库存与现金流记录 {number}。" * 4,
            created_at=f"2026-06-{number % 28 + 1:02d}T00:00:00+00:00",
        )
        for number in range(1, 61)
    ]
    same_name_entities = [
        StoryEntity(
            id=f"lin-chuan-{index}",
            project_id=workspace.project.id,
            kind=StoryEntityKind.CHARACTER,
            name="林川",
            role="主角" if index == 1 else "同名工人",
            goal="守住家庭" if index == 1 else "调离车间",
            current_state=f"当前状态 {index}",
            relationship_notes="用来源标识消除同名歧义",
            revision=0,
            created_at=NOW,
            updated_at=NOW,
        )
        for index in (1, 2)
    ]
    current = _current(workspace).model_copy(update={
        "title": "林川遇见另一个林川",
        "reader_promise": "辨认两个林川的目标",
    })
    workspace = workspace.model_copy(update={
        "chapters": [*workspace.chapters[:-1], current],
        "story_facts": facts,
        "story_entities": same_name_entities,
    })

    packet = ContextCompiler().compile(
        workspace,
        current,
        author_intent="两个林川都必须保持各自状态",
        task_type=ContextTaskType.CHAPTER_DRAFT,
        token_budget=6000,
    )

    items = {item.id: item for item in packet.items}
    assert items["fact:fact-60"].included
    assert any(
        item.kind == ContextItemKind.CANONICAL_FACT and not item.included
        for item in packet.items
    )
    entity_items = [item for item in packet.items if item.kind == ContextItemKind.STORY_ENTITY]
    assert len(entity_items) == 2
    assert all(item.included and item.required for item in entity_items)
    assert {item.source_refs[0].source_id for item in entity_items} == {
        "lin-chuan-1",
        "lin-chuan-2",
    }


def test_timeline_and_knowledge_statuses_are_explicit_in_selection_reasons() -> None:
    workspace = _workspace(previous_chapters=3)
    current = _current(workspace)
    resolved = StoryThread(
        id="thread-resolved",
        project_id=workspace.project.id,
        source_chapter_id="chapter-1",
        title="已经回收的账本",
        summary="不应继续作为开放伏笔",
        status=StoryThreadStatus.RESOLVED,
        planted_chapter_number=1,
        resolved_chapter_id="chapter-2",
        revision=1,
        created_at=NOW,
        updated_at=NOW,
    )
    invalid_knowledge = FutureKnowledge(
        id="future-invalid",
        project_id=workspace.project.id,
        future_year=2008,
        content="纸厂一定会按原历史倒闭",
        source_note="分歧前记忆",
        confidence=KnowledgeConfidence.CERTAIN,
        status=KnowledgeStatus.CANDIDATE_INVALID,
        divergence_event_id="timeline-novel",
        revision=1,
        created_at=NOW,
        updated_at=NOW,
    )
    original = TimelineEvent(
        id="timeline-original",
        project_id=workspace.project.id,
        layer=TimelineLayer.ORIGINAL,
        event_year=2008,
        title="原历史纸厂停产",
        summary="只用于对照",
        source_chapter_id=None,
        created_at=NOW,
    )
    workspace = workspace.model_copy(update={
        "story_threads": [resolved],
        "future_knowledge": [invalid_knowledge],
        "timeline_events": [original],
    })

    packet = ContextCompiler().compile(
        workspace,
        current,
        author_intent="判断纸厂未来",
        task_type=ContextTaskType.CHAPTER_BRIEF,
        token_budget=6000,
    )

    by_id = {item.id: item for item in packet.items}
    assert not by_id["thread:thread-resolved"].included
    assert "resolved" in (by_id["thread:thread-resolved"].exclusion_reason or "")
    assert not by_id["future:future-invalid"].included
    assert "candidate_invalid" in (by_id["future:future-invalid"].exclusion_reason or "")
    assert any("不代表小说分歧后" in note for note in packet.conflict_notes)
    assert by_id["timeline:timeline-original"].conflict_notes


def test_context_repository_keeps_packets_immutable_and_directives_revisioned(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "mozhou.db")
    database.initialize()
    projects = ProjectRepository(database)
    workspace = projects.create_project(CreateProjectRequest(
        title="南平重启",
        genre=Genre.URBAN_REBIRTH,
        rebirth_year=1998,
        rebirth_location="福建南平",
    ))
    entity = projects.create_story_entity(
        workspace.project.id,
        CreateStoryEntityRequest(
            kind=StoryEntityKind.CHARACTER,
            name="林川",
            role="主角",
            goal="改变家庭命运",
            current_state="刚回到一九九八年",
            relationship_notes="",
        ),
    )
    workspace = projects.get_workspace(workspace.project.id)
    chapter = workspace.chapters[0]
    contexts = ContextRepository(database)
    directive = contexts.set_directive(
        chapter.id,
        ContextDirectiveRequest(
            source_kind="entity",
            source_id=entity.id,
            action=ContextDirectiveAction.PIN,
        ),
    )
    updated = contexts.set_directive(
        chapter.id,
        ContextDirectiveRequest(
            source_kind="entity",
            source_id=entity.id,
            action=ContextDirectiveAction.EXCLUDE,
            expected_revision=directive.revision,
        ),
    )
    packet = ContextCompiler().compile(
        workspace,
        chapter,
        author_intent="先确认家庭状态",
        task_type=ContextTaskType.CHAPTER_BRIEF,
        token_budget=4000,
        directives=contexts.list_directives(chapter.id),
    )

    saved = contexts.put_packet(packet)
    reused = contexts.put_packet(packet)

    assert updated.revision == 1
    assert updated.action == ContextDirectiveAction.EXCLUDE
    assert saved == reused == contexts.get_packet(packet.id)
    assert contexts.list_packets(chapter.id) == [packet]


def test_three_hundred_thousand_character_project_compiles_within_fixed_budget() -> None:
    workspace = _workspace(previous_chapters=100, content_characters=3000)
    start = perf_counter()

    packet = ContextCompiler().compile(
        workspace,
        _current(workspace),
        author_intent="承接上一章悬念",
        task_type=ContextTaskType.CHAPTER_DRAFT,
        token_budget=24_000,
    )

    duration = perf_counter() - start
    assert sum(len(item.content) for item in workspace.chapters[:-1]) >= 290_000
    assert packet.used_tokens <= packet.token_budget
    assert duration < 2.0


def test_confirmed_reality_source_is_selected_but_unconfirmed_source_is_not() -> None:
    workspace = _workspace(previous_chapters=1)
    cards = [
        SourceCard(
            id=f"source-{confirmed}",
            project_id=workspace.project.id,
            source_kind=SourceKind.INDUSTRY,
            title="九十年代纸厂工资表" if confirmed else "待核实传闻",
            source_reference="作者资料夹",
            applicable_year_start=1995,
            applicable_year_end=2000,
            confidence=SourceConfidence.HIGH,
            excerpt="工资构成包括基本工资、岗位津贴和计件奖。",
            confirmed=confirmed,
            revision=0,
            created_at=NOW,
            updated_at=NOW,
        )
        for confirmed in (True, False)
    ]
    workspace = workspace.model_copy(update={"source_cards": cards})

    packet = ContextCompiler().compile(
        workspace,
        _current(workspace),
        author_intent="写清纸厂工资",
        task_type=ContextTaskType.CHAPTER_DRAFT,
        token_budget=6000,
    )

    sources = {item.source_refs[0].source_id: item for item in packet.items if item.kind == ContextItemKind.REALITY_SOURCE}
    assert sources["source-True"].included
    assert not sources["source-False"].included
    assert "尚未" in (sources["source-False"].exclusion_reason or "")
