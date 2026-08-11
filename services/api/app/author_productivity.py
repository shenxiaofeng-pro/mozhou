from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from sqlite3 import Row
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.database import Database
from app.repository import NotFoundError, StaleRevisionError, now_iso


class WritingCalendarDay(BaseModel):
    date: str
    net_characters: int
    target_characters: int
    met_goal: bool


class WritingCalendar(BaseModel):
    project_id: str
    timezone: str
    days: list[WritingCalendarDay]
    total_net_characters: int
    streak_days: int


class ChapterAnnotation(BaseModel):
    id: str
    project_id: str
    chapter_id: str
    chapter_revision: int
    content_sha256: str
    start_char: int
    end_char: int
    selected_text: str
    context_before: str
    context_after: str
    comment: str
    status: Literal["open", "resolved", "stale"]
    revision: int
    created_at: str
    updated_at: str


class CreateAnnotationRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    expected_chapter_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> CreateAnnotationRequest:
        if self.end_char <= self.start_char:
            raise ValueError("批注选区无效")
        return self


class ResolveAnnotationRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class AuthorIdea(BaseModel):
    id: str
    project_id: str | None
    title: str
    content: str
    tags: list[str]
    status: Literal["inbox", "planned", "applied", "archived"]
    target_kind: Literal["chapter_brief", "source_card", "character"] | None
    target_id: str | None
    revision: int
    created_at: str
    updated_at: str


class CreateIdeaRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    project_id: str | None = Field(default=None, max_length=36)
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        tags = [tag.strip() for tag in value if tag.strip()]
        if any(len(tag) > 30 or "\x00" in tag for tag in tags):
            raise ValueError("灵感标签无效")
        return list(dict.fromkeys(tags))


class UpdateIdeaRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    status: Literal["inbox", "planned", "applied", "archived"]
    expected_revision: int = Field(ge=0)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        tags = [tag.strip() for tag in value if tag.strip()]
        if any(len(tag) > 30 or "\x00" in tag for tag in tags):
            raise ValueError("灵感标签无效")
        return list(dict.fromkeys(tags))


class PrepareIdeaRequest(BaseModel):
    target_kind: Literal["chapter_brief", "source_card", "character"]
    expected_revision: int = Field(ge=0)


class StoryRelationship(BaseModel):
    id: str
    project_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    summary: str
    status: Literal["active", "historical"]
    source_chapter_id: str | None
    revision: int
    created_at: str
    updated_at: str


class CreateRelationshipRequest(BaseModel):
    source_entity_id: str = Field(min_length=36, max_length=36)
    target_entity_id: str = Field(min_length=36, max_length=36)
    relation_type: str = Field(min_length=1, max_length=80)
    summary: str = Field(default="", max_length=1000)
    source_chapter_id: str | None = Field(default=None, max_length=36)


class GraphNode(BaseModel):
    id: str
    label: str
    kind: Literal["character", "resource", "thread", "chapter"]
    status: str


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    status: str
    chapter_id: str | None = None


class StoryGraphs(BaseModel):
    relationship_nodes: list[GraphNode]
    relationship_edges: list[GraphEdge]
    thread_nodes: list[GraphNode]
    thread_edges: list[GraphEdge]


class AuthorProductivityService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def calendar(self, project_id: str, days: int = 42) -> WritingCalendar:
        if not 7 <= days <= 366:
            raise ValueError("calendar_range_invalid")
        today = datetime.now(UTC).astimezone().date()
        first = today - timedelta(days=days - 1)
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT chapter_target_words FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if project is None:
                raise NotFoundError(project_id)
            versions = connection.execute(
                """SELECT v.chapter_id, v.content, v.is_candidate, v.created_at, v.version_number
                FROM chapter_versions v JOIN chapters c ON c.id=v.chapter_id WHERE c.project_id=?
                ORDER BY v.chapter_id, v.version_number""",
                (project_id,),
            ).fetchall()
            goals = {
                str(row["goal_date"]): int(row["target_characters"])
                for row in connection.execute(
                    "SELECT goal_date, target_characters FROM serial_daily_goals WHERE project_id=? AND goal_date>=?",
                    (project_id, first.isoformat()),
                ).fetchall()
            }
        net_by_date: dict[str, int] = {}
        previous: dict[str, int] = {}
        for row in versions:
            chapter_id = str(row["chapter_id"])
            current = len(str(row["content"]).replace(" ", ""))
            if bool(row["is_candidate"]):
                continue
            delta = current - previous.get(chapter_id, 0)
            previous[chapter_id] = current
            local_date = (
                datetime.fromisoformat(str(row["created_at"])).astimezone().date().isoformat()
            )
            net_by_date[local_date] = net_by_date.get(local_date, 0) + delta
        calendar_days = []
        default_target = int(project["chapter_target_words"])
        for offset in range(days):
            day = (first + timedelta(days=offset)).isoformat()
            net = net_by_date.get(day, 0)
            target = goals.get(day, default_target)
            calendar_days.append(
                WritingCalendarDay(
                    date=day, net_characters=net, target_characters=target, met_goal=net >= target
                )
            )
        streak = 0
        for item in reversed(calendar_days):
            if item.net_characters <= 0:
                break
            streak += 1
        return WritingCalendar(
            project_id=project_id,
            timezone=str(datetime.now().astimezone().tzinfo),
            days=calendar_days,
            total_net_characters=sum(item.net_characters for item in calendar_days),
            streak_days=streak,
        )

    def create_annotation(
        self, chapter_id: str, request: CreateAnnotationRequest
    ) -> ChapterAnnotation:
        timestamp = now_iso()
        with self.database.connect() as connection:
            chapter = connection.execute(
                "SELECT project_id, content, revision FROM chapters WHERE id=? AND deleted_at IS NULL",
                (chapter_id,),
            ).fetchone()
            if chapter is None:
                raise NotFoundError(chapter_id)
            if int(chapter["revision"]) != request.expected_chapter_revision:
                raise StaleRevisionError(str(chapter["revision"]))
            content = str(chapter["content"])
            if (
                request.end_char > len(content)
                or not content[request.start_char : request.end_char]
            ):
                raise ValueError("annotation_range_invalid")
            annotation_id = str(uuid4())
            selected = content[request.start_char : request.end_char]
            connection.execute(
                """INSERT INTO chapter_annotations (id, project_id, chapter_id, chapter_revision,
                content_sha256, start_char, end_char, selected_text, context_before, context_after, comment,
                status, revision, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 0, ?, ?)""",
                (
                    annotation_id,
                    chapter["project_id"],
                    chapter_id,
                    chapter["revision"],
                    sha256(content.encode()).hexdigest(),
                    request.start_char,
                    request.end_char,
                    selected,
                    content[max(0, request.start_char - 80) : request.start_char],
                    content[request.end_char : request.end_char + 80],
                    request.comment,
                    timestamp,
                    timestamp,
                ),
            )
        return self._annotation(annotation_id)

    def list_annotations(self, chapter_id: str) -> list[ChapterAnnotation]:
        self._refresh_annotation_anchors(chapter_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM chapter_annotations WHERE chapter_id=? ORDER BY created_at",
                (chapter_id,),
            ).fetchall()
        return [ChapterAnnotation.model_validate(dict(row)) for row in rows]

    def resolve_annotation(
        self, annotation_id: str, request: ResolveAnnotationRequest
    ) -> ChapterAnnotation:
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT revision FROM chapter_annotations WHERE id=?", (annotation_id,)
            ).fetchone()
            if current is None:
                raise NotFoundError(annotation_id)
            if int(current["revision"]) != request.expected_revision:
                raise StaleRevisionError(str(current["revision"]))
            connection.execute(
                "UPDATE chapter_annotations SET status='resolved', revision=revision+1, updated_at=? WHERE id=?",
                (now_iso(), annotation_id),
            )
        return self._annotation(annotation_id)

    def list_ideas(self, project_id: str | None) -> list[AuthorIdea]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM author_ideas WHERE project_id IS NULL OR project_id=? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        return [self._idea(row) for row in rows]

    def create_idea(self, request: CreateIdeaRequest) -> AuthorIdea:
        timestamp = now_iso()
        idea_id = str(uuid4())
        with self.database.connect() as connection:
            if (
                request.project_id
                and connection.execute(
                    "SELECT 1 FROM projects WHERE id=?", (request.project_id,)
                ).fetchone()
                is None
            ):
                raise NotFoundError(request.project_id)
            connection.execute(
                """INSERT INTO author_ideas (id, project_id, title, content, tags_json, status,
                revision, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'inbox', 0, ?, ?)""",
                (
                    idea_id,
                    request.project_id,
                    request.title,
                    request.content,
                    json.dumps(request.tags, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        return self._idea_by_id(idea_id)

    def update_idea(self, idea_id: str, request: UpdateIdeaRequest) -> AuthorIdea:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT revision FROM author_ideas WHERE id=?", (idea_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(idea_id)
            if int(row["revision"]) != request.expected_revision:
                raise StaleRevisionError(str(row["revision"]))
            connection.execute(
                """UPDATE author_ideas SET title=?, content=?, tags_json=?, status=?,
                revision=revision+1, updated_at=? WHERE id=? AND revision=?""",
                (
                    request.title,
                    request.content,
                    json.dumps(request.tags, ensure_ascii=False),
                    request.status,
                    now_iso(),
                    idea_id,
                    request.expected_revision,
                ),
            )
        return self._idea_by_id(idea_id)

    def prepare_idea(self, idea_id: str, request: PrepareIdeaRequest) -> AuthorIdea:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT revision FROM author_ideas WHERE id=?", (idea_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(idea_id)
            if int(row["revision"]) != request.expected_revision:
                raise StaleRevisionError(str(row["revision"]))
            connection.execute(
                "UPDATE author_ideas SET status='planned', target_kind=?, target_id=NULL, revision=revision+1, updated_at=? WHERE id=?",
                (request.target_kind, now_iso(), idea_id),
            )
        return self._idea_by_id(idea_id)

    def create_relationship(
        self, project_id: str, request: CreateRelationshipRequest
    ) -> StoryRelationship:
        timestamp = now_iso()
        relationship_id = str(uuid4())
        with self.database.connect() as connection:
            entities = connection.execute(
                "SELECT id FROM story_entities WHERE project_id=? AND id IN (?, ?)",
                (project_id, request.source_entity_id, request.target_entity_id),
            ).fetchall()
            if len(entities) != 2 or request.source_entity_id == request.target_entity_id:
                raise ValueError("relationship_entities_invalid")
            if (
                request.source_chapter_id
                and connection.execute(
                    "SELECT 1 FROM chapters WHERE id=? AND project_id=?",
                    (request.source_chapter_id, project_id),
                ).fetchone()
                is None
            ):
                raise ValueError("relationship_chapter_invalid")
            connection.execute(
                """INSERT INTO story_relationships (id, project_id, source_entity_id,
                target_entity_id, relation_type, summary, status, source_chapter_id, revision, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, 0, ?, ?)""",
                (
                    relationship_id,
                    project_id,
                    request.source_entity_id,
                    request.target_entity_id,
                    request.relation_type,
                    request.summary,
                    request.source_chapter_id,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM story_relationships WHERE id=?", (relationship_id,)
            ).fetchone()
        return StoryRelationship.model_validate(dict(row))

    def graphs(self, project_id: str) -> StoryGraphs:
        with self.database.connect() as connection:
            entities = connection.execute(
                "SELECT id, kind, name, current_state FROM story_entities WHERE project_id=? ORDER BY name",
                (project_id,),
            ).fetchall()
            relationships = connection.execute(
                "SELECT * FROM story_relationships WHERE project_id=? ORDER BY created_at",
                (project_id,),
            ).fetchall()
            threads = connection.execute(
                "SELECT * FROM story_threads WHERE project_id=? ORDER BY created_at", (project_id,)
            ).fetchall()
            chapters = {
                str(row["id"]): str(row["title"])
                for row in connection.execute(
                    "SELECT id, title FROM chapters WHERE project_id=?", (project_id,)
                ).fetchall()
            }
        relation_nodes = [
            GraphNode(
                id=str(row["id"]),
                label=str(row["name"]),
                kind=row["kind"],
                status=str(row["current_state"])[:120],
            )
            for row in entities
        ]
        relation_edges = [
            GraphEdge(
                id=str(row["id"]),
                source=str(row["source_entity_id"]),
                target=str(row["target_entity_id"]),
                label=str(row["relation_type"]),
                status=str(row["status"]),
                chapter_id=row["source_chapter_id"],
            )
            for row in relationships
        ]
        thread_nodes: list[GraphNode] = []
        thread_edges: list[GraphEdge] = []
        for row in threads:
            thread_id = str(row["id"])
            source = row["source_chapter_id"]
            resolved = row["resolved_chapter_id"]
            thread_nodes.append(
                GraphNode(
                    id=thread_id, label=str(row["title"]), kind="thread", status=str(row["status"])
                )
            )
            for chapter_id, label in ((source, "埋设"), (resolved, "回收")):
                if chapter_id:
                    chapter_key = f"chapter:{chapter_id}"
                    if not any(node.id == chapter_key for node in thread_nodes):
                        thread_nodes.append(
                            GraphNode(
                                id=chapter_key,
                                label=chapters.get(str(chapter_id), "来源章节"),
                                kind="chapter",
                                status="formal",
                            )
                        )
                    thread_edges.append(
                        GraphEdge(
                            id=f"{thread_id}:{label}",
                            source=chapter_key if label == "埋设" else thread_id,
                            target=thread_id if label == "埋设" else chapter_key,
                            label=label,
                            status=str(row["status"]),
                            chapter_id=str(chapter_id),
                        )
                    )
        return StoryGraphs(
            relationship_nodes=relation_nodes,
            relationship_edges=relation_edges,
            thread_nodes=thread_nodes,
            thread_edges=thread_edges,
        )

    def _refresh_annotation_anchors(self, chapter_id: str) -> None:
        with self.database.connect() as connection:
            chapter = connection.execute(
                "SELECT content, revision FROM chapters WHERE id=?", (chapter_id,)
            ).fetchone()
            if chapter is None:
                raise NotFoundError(chapter_id)
            content = str(chapter["content"])
            digest = sha256(content.encode()).hexdigest()
            timestamp = now_iso()
            rows = connection.execute(
                "SELECT * FROM chapter_annotations WHERE chapter_id=? AND status='open' AND content_sha256<>?",
                (chapter_id, digest),
            ).fetchall()
            for row in rows:
                selected = str(row["selected_text"])
                positions: list[int] = []
                cursor = content.find(selected)
                while cursor >= 0 and len(positions) < 2:
                    positions.append(cursor)
                    cursor = content.find(selected, cursor + 1)
                if len(positions) == 1:
                    start = positions[0]
                    connection.execute(
                        """UPDATE chapter_annotations SET start_char=?, end_char=?, chapter_revision=?,
                        content_sha256=?, revision=revision+1, updated_at=? WHERE id=?""",
                        (
                            start,
                            start + len(selected),
                            chapter["revision"],
                            digest,
                            timestamp,
                            row["id"],
                        ),
                    )
                else:
                    connection.execute(
                        "UPDATE chapter_annotations SET status='stale', revision=revision+1, updated_at=? WHERE id=?",
                        (timestamp, row["id"]),
                    )

    def _annotation(self, annotation_id: str) -> ChapterAnnotation:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM chapter_annotations WHERE id=?", (annotation_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(annotation_id)
        return ChapterAnnotation.model_validate(dict(row))

    @staticmethod
    def _idea(row: Row) -> AuthorIdea:
        data = dict(row)
        data["tags"] = json.loads(data.pop("tags_json"))
        return AuthorIdea.model_validate(data)

    def _idea_by_id(self, idea_id: str) -> AuthorIdea:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM author_ideas WHERE id=?", (idea_id,)).fetchone()
        if row is None:
            raise NotFoundError(idea_id)
        return self._idea(row)
