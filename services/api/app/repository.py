import json
from datetime import UTC, datetime
from hashlib import sha256
from sqlite3 import Connection, IntegrityError, Row
from typing import cast
from uuid import uuid4

from app.continuity import enrich_serial_control
from app.database import Database
from app.fake_model import ChapterContext
from app.models import (
    AppliedReferenceDimension,
    ApplyFactChangeSetRequest,
    ApplyReferencePatternRequest,
    Chapter,
    ChapterStatus,
    ChapterSummary,
    CreateChapterRequest,
    CreateFutureKnowledgeRequest,
    CreateProjectRequest,
    CreateSourceCardRequest,
    CreateStoryEntityRequest,
    CreateStoryThreadRequest,
    CreateTimelineEventRequest,
    FactChange,
    FactChangeSet,
    FactChangeSetState,
    FactKind,
    FutureKnowledge,
    GenerationRun,
    GenerationState,
    ImportReferenceWorkRequest,
    KnowledgeReviewAction,
    KnowledgeStatus,
    Project,
    ReferenceFormat,
    ReferencePatternApplication,
    ReferencePatternCard,
    ReferenceSegment,
    ReferenceSynthesisProposal,
    ReferenceWork,
    RejectFactChangeSetRequest,
    ReviewFutureKnowledgeRequest,
    SetSourceCardConfirmationRequest,
    SourceCard,
    StoryEntity,
    StoryFact,
    StoryThread,
    StoryThreadStatus,
    TimelineEvent,
    TimelineLayer,
    TransitionChapterRequest,
    TransitionStoryThreadRequest,
    UpdateChapterBriefRequest,
    UpdateChapterRequest,
    UpdateStoryEntityRequest,
    Workspace,
    WorkspaceSummary,
)
from app.reference_lab import ReferenceAnalysisInput, segment_reference_text


class NotFoundError(Exception):
    pass


class StaleRevisionError(Exception):
    pass


class StaleChapterSequenceError(Exception):
    pass


class InvalidChapterStateError(Exception):
    pass


class InvalidFactChangeSetStateError(Exception):
    pass


class InvalidFactSelectionError(Exception):
    pass


class InvalidFutureKnowledgeStateError(Exception):
    pass


class InvalidStoryThreadStateError(Exception):
    pass


class InvalidReferenceImportError(Exception):
    pass


class InvalidReferenceSelectionError(Exception):
    pass


class InvalidReferenceApplicationError(Exception):
    pass


ALLOWED_CHAPTER_TRANSITIONS: dict[ChapterStatus, set[ChapterStatus]] = {
    ChapterStatus.PLANNED: {ChapterStatus.DRAFTED},
    ChapterStatus.DRAFTED: {ChapterStatus.REVIEWING},
    ChapterStatus.REVIEWING: {ChapterStatus.DRAFTED, ChapterStatus.APPROVED},
    ChapterStatus.APPROVED: {ChapterStatus.DRAFTED},
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ProjectRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_project(self, request: CreateProjectRequest) -> Workspace:
        project_id = str(uuid4())
        chapter_id = str(uuid4())
        timestamp = now_iso()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    id, title, genre, rebirth_year, rebirth_location,
                    chapter_target_words, safety_buffer_chapters, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    request.title,
                    request.genre.value,
                    request.rebirth_year,
                    request.rebirth_location,
                    request.chapter_target_words,
                    request.safety_buffer_chapters,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO chapters (
                    id, project_id, volume_number, chapter_number, title,
                    content, status, revision, updated_at
                ) VALUES (?, ?, 1, 1, ?, '', ?, 0, ?)
                """,
                (chapter_id, project_id, "第一章 未命名", ChapterStatus.PLANNED.value, timestamp),
            )
        return self.get_workspace(project_id)

    def list_projects(self) -> list[Project]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [self._project(row) for row in rows]

    def get_workspace(self, project_id: str) -> Workspace:
        return cast(Workspace, self._get_workspace(project_id, include_chapter_content=True))

    def get_workspace_summary(self, project_id: str) -> WorkspaceSummary:
        return cast(
            WorkspaceSummary,
            self._get_workspace(project_id, include_chapter_content=False),
        )

    def _get_workspace(
        self,
        project_id: str,
        *,
        include_chapter_content: bool,
    ) -> Workspace | WorkspaceSummary:
        with self.database.connect() as connection:
            project_row = connection.execute(
                "SELECT * FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project_row is None:
                raise NotFoundError(project_id)
            if include_chapter_content:
                chapter_rows = connection.execute(
                    "SELECT * FROM chapters WHERE project_id = ? ORDER BY chapter_number",
                    (project_id,),
                ).fetchall()
            else:
                chapter_rows = connection.execute(
                    """
                    SELECT id, project_id, volume_number, chapter_number, title,
                           reader_promise, opening_hook, state_change, emotional_payoff,
                           ending_cliffhanger, status, revision, updated_at,
                           CASE WHEN LENGTH(TRIM(content)) > 0 THEN 1 ELSE 0 END AS has_content,
                           LENGTH(content) AS content_characters
                    FROM chapters
                    WHERE project_id = ?
                    ORDER BY chapter_number
                    """,
                    (project_id,),
                ).fetchall()
            timeline_rows = connection.execute(
                """
                SELECT * FROM timeline_events
                WHERE project_id = ?
                ORDER BY layer, event_year, created_at
                """,
                (project_id,),
            ).fetchall()
            fact_rows = connection.execute(
                """
                SELECT * FROM story_facts
                WHERE project_id = ?
                ORDER BY created_at, id
                """,
                (project_id,),
            ).fetchall()
            change_set_rows = connection.execute(
                """
                SELECT s.*
                FROM fact_change_sets s
                JOIN chapters c ON c.id = s.chapter_id
                WHERE c.project_id = ?
                ORDER BY s.created_at, s.id
                """,
                (project_id,),
            ).fetchall()
            change_rows = connection.execute(
                """
                SELECT f.*
                FROM fact_changes f
                JOIN fact_change_sets s ON s.id = f.change_set_id
                JOIN chapters c ON c.id = s.chapter_id
                WHERE c.project_id = ?
                ORDER BY f.rowid
                """,
                (project_id,),
            ).fetchall()
            knowledge_rows = connection.execute(
                """
                SELECT * FROM future_knowledge
                WHERE project_id = ?
                ORDER BY future_year, created_at, id
                """,
                (project_id,),
            ).fetchall()
            entity_rows = connection.execute(
                """
                SELECT * FROM story_entities
                WHERE project_id = ?
                ORDER BY kind, name, created_at
                """,
                (project_id,),
            ).fetchall()
            thread_rows = connection.execute(
                """
                SELECT * FROM story_threads
                WHERE project_id = ?
                ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'resolved' THEN 1 ELSE 2 END,
                         created_at, id
                """,
                (project_id,),
            ).fetchall()
            source_rows = connection.execute(
                """
                SELECT * FROM source_cards
                WHERE project_id = ?
                ORDER BY confirmed DESC, applicable_year_start, created_at
                """,
                (project_id,),
            ).fetchall()
            reference_work_rows = connection.execute(
                """
                SELECT w.* FROM reference_works w
                JOIN project_reference_works p ON p.reference_work_id = w.id
                WHERE p.project_id = ?
                ORDER BY w.created_at, w.id
                """,
                (project_id,),
            ).fetchall()
            reference_segment_rows = connection.execute(
                """
                SELECT id, reference_work_id, ordinal, start_char, end_char,
                       character_count, chapter_start, chapter_end, created_at
                FROM reference_segments
                WHERE reference_work_id IN (
                    SELECT reference_work_id FROM project_reference_works WHERE project_id = ?
                )
                ORDER BY reference_work_id, ordinal
                """,
                (project_id,),
            ).fetchall()
            reference_pattern_rows = connection.execute(
                """
                SELECT * FROM reference_pattern_cards
                WHERE project_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (project_id,),
            ).fetchall()
            reference_application_rows = connection.execute(
                """
                SELECT * FROM reference_pattern_applications
                WHERE project_id = ?
                ORDER BY created_at, id
                """,
                (project_id,),
            ).fetchall()
        changes_by_set: dict[str, list[FactChange]] = {}
        for row in change_rows:
            changes_by_set.setdefault(row["change_set_id"], []).append(self._fact_change(row))
        segments_by_work: dict[str, list[ReferenceSegment]] = {}
        for row in reference_segment_rows:
            segments_by_work.setdefault(row["reference_work_id"], []).append(
                self._reference_segment(row)
            )
        workspace_payload: dict[str, object] = {
            "project": self._project(project_row),
            "chapters": (
                [self._chapter(row) for row in chapter_rows]
                if include_chapter_content
                else [self._chapter_summary(row) for row in chapter_rows]
            ),
            "timeline_events": [self._timeline_event(row) for row in timeline_rows],
            "story_facts": [self._story_fact(row) for row in fact_rows],
            "fact_change_sets": [
                self._fact_change_set(row, changes_by_set.get(row["id"], []))
                for row in change_set_rows
            ],
            "future_knowledge": [self._future_knowledge(row) for row in knowledge_rows],
            "story_entities": [self._story_entity(row) for row in entity_rows],
            "story_threads": [self._story_thread(row) for row in thread_rows],
            "source_cards": [self._source_card(row) for row in source_rows],
            "reference_works": [
                self._reference_work(
                    row,
                    segments_by_work.get(row["id"], []),
                    project_ids=[project_id],
                )
                for row in reference_work_rows
            ],
            "reference_pattern_cards": [
                self._reference_pattern_card(row) for row in reference_pattern_rows
            ],
            "reference_pattern_applications": [
                self._reference_pattern_application(row)
                for row in reference_application_rows
            ],
        }
        if include_chapter_content:
            return enrich_serial_control(Workspace.model_validate(workspace_payload))
        return enrich_serial_control(WorkspaceSummary.model_validate(workspace_payload))

    def get_workspace_for_chapter(self, chapter_id: str) -> Workspace:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT project_id FROM chapters WHERE id = ?",
                (chapter_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(chapter_id)
        return self.get_workspace(row["project_id"])

    def get_chapter(self, chapter_id: str) -> Chapter:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM chapters WHERE id = ?",
                (chapter_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(chapter_id)
        return self._chapter(row)

    def import_reference_work(
        self,
        project_id: str,
        request: ImportReferenceWorkRequest,
    ) -> ReferenceWork:
        content = request.content.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
        work = self._create_global_reference_work(request, content)
        return self.link_reference_work(project_id, work.id)

    def import_global_reference_work(
        self,
        request: ImportReferenceWorkRequest,
    ) -> ReferenceWork:
        extension = request.source_filename.lower().rsplit(".", 1)[-1]
        if extension not in {"txt", "md", "markdown"}:
            raise InvalidReferenceImportError("unsupported_format")
        content = request.content.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
        return self._create_global_reference_work(request, content)

    def _create_global_reference_work(
        self,
        request: ImportReferenceWorkRequest,
        content: str,
    ) -> ReferenceWork:
        extension = request.source_filename.lower().rsplit(".", 1)[-1]
        if extension == "txt":
            source_format = ReferenceFormat.TXT
        elif extension in {"md", "markdown"}:
            source_format = ReferenceFormat.MARKDOWN
        else:
            raise InvalidReferenceImportError("unsupported_format")
        segments = segment_reference_text(content, request.segment_target_characters)
        if not segments:
            raise InvalidReferenceImportError("empty_content")
        work_id = str(uuid4())
        timestamp = now_iso()
        content_sha256 = sha256(content.encode("utf-8")).hexdigest()
        with self.database.connect() as connection:
            duplicate = connection.execute(
                "SELECT id FROM reference_works WHERE content_sha256 = ? ORDER BY created_at, id LIMIT 1",
                (content_sha256,),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO reference_works (
                    id, title, source_filename, source_format, rights_basis,
                    total_characters, segment_target_characters, content_sha256,
                    source_encoding, encoding_confidence, import_state,
                    duplicate_of_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'utf-8', 1.0, 'ready', ?, ?, ?)
                """,
                (
                    work_id,
                    request.title,
                    request.source_filename,
                    source_format.value,
                    request.rights_basis.value,
                    len(content),
                    request.segment_target_characters,
                    content_sha256,
                    duplicate["id"] if duplicate is not None else None,
                    timestamp,
                    timestamp,
                ),
            )
            connection.executemany(
                """
                INSERT INTO reference_segments (
                    id, reference_work_id, ordinal, start_char, end_char,
                    character_count, chapter_start, chapter_end, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(uuid4()),
                        work_id,
                        segment.ordinal,
                        segment.start_char,
                        segment.end_char,
                        segment.character_count,
                        segment.chapter_start,
                        segment.chapter_end,
                        segment.content,
                        timestamp,
                    )
                    for segment in segments
                ],
            )
        return self.get_reference_work(work_id)

    def list_reference_works(self) -> list[ReferenceWork]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reference_works ORDER BY created_at DESC, id DESC"
            ).fetchall()
            segment_rows = connection.execute(
                """
                SELECT id, reference_work_id, ordinal, start_char, end_char,
                       character_count, chapter_start, chapter_end, created_at
                FROM reference_segments ORDER BY reference_work_id, ordinal
                """
            ).fetchall()
            link_rows = connection.execute(
                "SELECT project_id, reference_work_id FROM project_reference_works ORDER BY project_id"
            ).fetchall()
        segments_by_work: dict[str, list[ReferenceSegment]] = {}
        for row in segment_rows:
            segments_by_work.setdefault(row["reference_work_id"], []).append(
                self._reference_segment(row)
            )
        projects_by_work: dict[str, list[str]] = {}
        for row in link_rows:
            projects_by_work.setdefault(row["reference_work_id"], []).append(row["project_id"])
        return [
            self._reference_work(
                row,
                segments_by_work.get(row["id"], []),
                project_ids=projects_by_work.get(row["id"], []),
            )
            for row in rows
        ]

    def link_reference_work(self, project_id: str, work_id: str) -> ReferenceWork:
        timestamp = now_iso()
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
                raise NotFoundError(project_id)
            if connection.execute(
                "SELECT id FROM reference_works WHERE id = ?", (work_id,)
            ).fetchone() is None:
                raise NotFoundError(work_id)
            connection.execute(
                """
                INSERT INTO project_reference_works(project_id, reference_work_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id, reference_work_id) DO NOTHING
                """,
                (project_id, work_id, timestamp),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )
        return self.get_reference_work(work_id)

    def unlink_reference_work(self, project_id: str, work_id: str) -> None:
        timestamp = now_iso()
        with self.database.connect() as connection:
            result = connection.execute(
                "DELETE FROM project_reference_works WHERE project_id = ? AND reference_work_id = ?",
                (project_id, work_id),
            )
            if result.rowcount == 0:
                raise NotFoundError(work_id)
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )

    def get_reference_work(self, work_id: str) -> ReferenceWork:
        with self.database.connect() as connection:
            work = connection.execute(
                "SELECT * FROM reference_works WHERE id = ?",
                (work_id,),
            ).fetchone()
            segment_rows = connection.execute(
                """
                SELECT id, reference_work_id, ordinal, start_char, end_char,
                       character_count, chapter_start, chapter_end, created_at
                FROM reference_segments
                WHERE reference_work_id = ?
                ORDER BY ordinal
                """,
                (work_id,),
            ).fetchall()
            project_rows = connection.execute(
                "SELECT project_id FROM project_reference_works WHERE reference_work_id = ? ORDER BY project_id",
                (work_id,),
            ).fetchall()
        if work is None:
            raise NotFoundError(work_id)
        return self._reference_work(
            work,
            [self._reference_segment(row) for row in segment_rows],
            project_ids=[row["project_id"] for row in project_rows],
        )

    def get_reference_segments_for_analysis(
        self,
        project_id: str,
        segment_ids: list[str],
    ) -> list[ReferenceAnalysisInput]:
        placeholders = ", ".join("?" for _ in segment_ids)
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone() is None:
                raise NotFoundError(project_id)
            rows = connection.execute(
                f"""
                SELECT w.id AS work_id, w.title AS work_title,
                       s.id AS segment_id, s.ordinal, s.start_char, s.end_char,
                       s.chapter_start, s.chapter_end, s.content
                FROM reference_segments s
                JOIN reference_works w ON w.id = s.reference_work_id
                JOIN project_reference_works p ON p.reference_work_id = w.id
                WHERE p.project_id = ? AND s.id IN ({placeholders})
                """,
                (project_id, *segment_ids),
            ).fetchall()
        by_id = {
            row["segment_id"]: ReferenceAnalysisInput(**dict(row))
            for row in rows
        }
        if len(by_id) != len(segment_ids):
            raise InvalidReferenceSelectionError("missing_or_cross_project_segment")
        selected = [by_id[segment_id] for segment_id in segment_ids]
        if len({segment.work_id for segment in selected}) < 2:
            raise InvalidReferenceSelectionError("multiple_works_required")
        if sum(len(segment.content) for segment in selected) > 2_000_000:
            raise InvalidReferenceSelectionError("selection_too_large")
        return selected

    def save_reference_pattern_card(
        self,
        project_id: str,
        selected_segment_ids: list[str],
        author_focus: str,
        proposal: ReferenceSynthesisProposal,
        provider: str,
        model: str,
        source_job_id: str | None = None,
    ) -> ReferencePatternCard:
        card_id = str(uuid4())
        timestamp = now_iso()
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone() is None:
                raise NotFoundError(project_id)
            if source_job_id is not None:
                existing = connection.execute(
                    "SELECT * FROM reference_pattern_cards WHERE source_job_id = ?",
                    (source_job_id,),
                ).fetchone()
                if existing is not None:
                    return self._reference_pattern_card(existing)
            connection.execute(
                """
                INSERT INTO reference_pattern_cards (
                    id, project_id, selected_segment_ids_json, author_focus,
                    proposal_json, provider, model, source_job_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    project_id,
                    json.dumps(selected_segment_ids, separators=(",", ":")),
                    author_focus,
                    proposal.model_dump_json(),
                    provider,
                    model,
                    source_job_id,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM reference_pattern_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(card_id)
        return self._reference_pattern_card(row)

    def apply_reference_pattern(
        self,
        project_id: str,
        card_id: str,
        request: ApplyReferencePatternRequest,
    ) -> ReferencePatternApplication:
        application_id = str(uuid4())
        timestamp = now_iso()
        with self.database.connect() as connection:
            card = connection.execute(
                """
                SELECT proposal_json FROM reference_pattern_cards
                WHERE id = ? AND project_id = ?
                """,
                (card_id, project_id),
            ).fetchone()
            if card is None:
                raise NotFoundError(card_id)
            proposal = ReferenceSynthesisProposal.model_validate_json(card["proposal_json"])
            dimensions = {
                dimension.value: AppliedReferenceDimension(
                    summary=getattr(proposal, dimension.value).summary,
                    transferable_logic=getattr(proposal, dimension.value).transferable_logic,
                ).model_dump(mode="json")
                for dimension in request.selected_dimensions
            }
            try:
                connection.execute(
                    """
                    INSERT INTO reference_pattern_applications (
                        id, project_id, pattern_card_id, selected_dimensions_json,
                        dimensions_json, relationship_recomposition,
                        application_note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        application_id,
                        project_id,
                        card_id,
                        json.dumps(
                            [dimension.value for dimension in request.selected_dimensions],
                            separators=(",", ":"),
                        ),
                        json.dumps(dimensions, ensure_ascii=False, separators=(",", ":")),
                        proposal.relationship_recomposition,
                        request.application_note,
                        timestamp,
                    ),
                )
            except IntegrityError as error:
                raise InvalidReferenceApplicationError("pattern_already_applied") from error
            row = connection.execute(
                "SELECT * FROM reference_pattern_applications WHERE id = ?",
                (application_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(application_id)
        return self._reference_pattern_application(row)

    def create_story_entity(
        self,
        project_id: str,
        request: CreateStoryEntityRequest,
    ) -> StoryEntity:
        entity_id = str(uuid4())
        timestamp = now_iso()
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone() is None:
                raise NotFoundError(project_id)
            connection.execute(
                """
                INSERT INTO story_entities (
                    id, project_id, kind, name, role, goal, current_state,
                    relationship_notes, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    entity_id,
                    project_id,
                    request.kind.value,
                    request.name,
                    request.role,
                    request.goal,
                    request.current_state,
                    request.relationship_notes,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )
            row = connection.execute(
                "SELECT * FROM story_entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(entity_id)
        return self._story_entity(row)

    def update_story_entity(
        self,
        entity_id: str,
        request: UpdateStoryEntityRequest,
    ) -> StoryEntity:
        timestamp = now_iso()
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT project_id, revision FROM story_entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
            if current is None:
                raise NotFoundError(entity_id)
            if current["revision"] != request.expected_revision:
                raise StaleRevisionError(str(current["revision"]))
            result = connection.execute(
                """
                UPDATE story_entities
                SET name = ?, role = ?, goal = ?, current_state = ?,
                    relationship_notes = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    request.name,
                    request.role,
                    request.goal,
                    request.current_state,
                    request.relationship_notes,
                    timestamp,
                    entity_id,
                    request.expected_revision,
                ),
            )
            if result.rowcount == 0:
                raise StaleRevisionError(entity_id)
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, current["project_id"]),
            )
            row = connection.execute(
                "SELECT * FROM story_entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(entity_id)
        return self._story_entity(row)

    def create_story_thread(
        self,
        project_id: str,
        request: CreateStoryThreadRequest,
    ) -> StoryThread:
        thread_id = str(uuid4())
        timestamp = now_iso()
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone() is None:
                raise NotFoundError(project_id)
            if request.planted_chapter_number is not None and connection.execute(
                "SELECT id FROM chapters WHERE project_id = ? AND chapter_number = ?",
                (project_id, request.planted_chapter_number),
            ).fetchone() is None:
                raise NotFoundError(str(request.planted_chapter_number))
            connection.execute(
                """
                INSERT INTO story_threads (
                    id, project_id, source_chapter_id, title, summary, status,
                    planted_chapter_number, resolved_chapter_id, revision, created_at, updated_at
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, NULL, 0, ?, ?)
                """,
                (
                    thread_id,
                    project_id,
                    request.title,
                    request.summary,
                    StoryThreadStatus.OPEN.value,
                    request.planted_chapter_number,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM story_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(thread_id)
        return self._story_thread(row)

    def transition_story_thread(
        self,
        thread_id: str,
        request: TransitionStoryThreadRequest,
    ) -> StoryThread:
        timestamp = now_iso()
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT * FROM story_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
            if current is None:
                raise NotFoundError(thread_id)
            if current["revision"] != request.expected_revision:
                raise StaleRevisionError(str(current["revision"]))
            current_status = StoryThreadStatus(current["status"])
            target = request.target_status
            if target == current_status or (
                current_status != StoryThreadStatus.OPEN and target != StoryThreadStatus.OPEN
            ):
                raise InvalidStoryThreadStateError(f"{current_status.value}->{target.value}")
            resolved_chapter_id = None
            if target == StoryThreadStatus.RESOLVED and request.resolved_chapter_id is not None:
                chapter = connection.execute(
                    "SELECT project_id FROM chapters WHERE id = ?",
                    (request.resolved_chapter_id,),
                ).fetchone()
                if chapter is None or chapter["project_id"] != current["project_id"]:
                    raise NotFoundError(request.resolved_chapter_id)
                resolved_chapter_id = request.resolved_chapter_id
            result = connection.execute(
                """
                UPDATE story_threads
                SET status = ?, resolved_chapter_id = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ? AND status = ?
                """,
                (
                    target.value,
                    resolved_chapter_id,
                    timestamp,
                    thread_id,
                    request.expected_revision,
                    current_status.value,
                ),
            )
            if result.rowcount == 0:
                raise StaleRevisionError(thread_id)
            row = connection.execute(
                "SELECT * FROM story_threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(thread_id)
        return self._story_thread(row)

    def create_source_card(
        self,
        project_id: str,
        request: CreateSourceCardRequest,
    ) -> SourceCard:
        card_id = str(uuid4())
        timestamp = now_iso()
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone() is None:
                raise NotFoundError(project_id)
            connection.execute(
                """
                INSERT INTO source_cards (
                    id, project_id, source_kind, title, source_reference,
                    applicable_year_start, applicable_year_end, confidence,
                    excerpt, confirmed, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
                """,
                (
                    card_id,
                    project_id,
                    request.source_kind.value,
                    request.title,
                    request.source_reference,
                    request.applicable_year_start,
                    request.applicable_year_end,
                    request.confidence.value,
                    request.excerpt,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM source_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(card_id)
        return self._source_card(row)

    def set_source_card_confirmation(
        self,
        card_id: str,
        request: SetSourceCardConfirmationRequest,
    ) -> SourceCard:
        timestamp = now_iso()
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT revision FROM source_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
            if current is None:
                raise NotFoundError(card_id)
            if current["revision"] != request.expected_revision:
                raise StaleRevisionError(str(current["revision"]))
            result = connection.execute(
                """
                UPDATE source_cards
                SET confirmed = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    int(request.confirmed),
                    timestamp,
                    card_id,
                    request.expected_revision,
                ),
            )
            if result.rowcount == 0:
                raise StaleRevisionError(card_id)
            row = connection.execute(
                "SELECT * FROM source_cards WHERE id = ?",
                (card_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(card_id)
        return self._source_card(row)

    def create_future_knowledge(
        self,
        project_id: str,
        request: CreateFutureKnowledgeRequest,
    ) -> FutureKnowledge:
        knowledge_id = str(uuid4())
        timestamp = now_iso()
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT id, rebirth_year FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project is None:
                raise NotFoundError(project_id)
            if request.future_year < project["rebirth_year"]:
                raise ValueError("future_year_before_rebirth")
            connection.execute(
                """
                INSERT INTO future_knowledge (
                    id, project_id, future_year, content, source_note, confidence,
                    status, divergence_event_id, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
                """,
                (
                    knowledge_id,
                    project_id,
                    request.future_year,
                    request.content,
                    request.source_note,
                    request.confidence.value,
                    KnowledgeStatus.VALID.value,
                    timestamp,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )
            row = connection.execute(
                "SELECT * FROM future_knowledge WHERE id = ?",
                (knowledge_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(knowledge_id)
        return self._future_knowledge(row)

    def review_future_knowledge(
        self,
        knowledge_id: str,
        request: ReviewFutureKnowledgeRequest,
    ) -> FutureKnowledge:
        timestamp = now_iso()
        next_status = (
            KnowledgeStatus.VALID
            if request.action == KnowledgeReviewAction.KEEP_VALID
            else KnowledgeStatus.INVALID
        )
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT status, revision FROM future_knowledge WHERE id = ?",
                (knowledge_id,),
            ).fetchone()
            if current is None:
                raise NotFoundError(knowledge_id)
            if current["revision"] != request.expected_revision:
                raise StaleRevisionError(str(current["revision"]))
            if current["status"] != KnowledgeStatus.CANDIDATE_INVALID.value:
                raise InvalidFutureKnowledgeStateError(current["status"])
            result = connection.execute(
                """
                UPDATE future_knowledge
                SET status = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ? AND status = ?
                """,
                (
                    next_status.value,
                    timestamp,
                    knowledge_id,
                    request.expected_revision,
                    KnowledgeStatus.CANDIDATE_INVALID.value,
                ),
            )
            if result.rowcount == 0:
                raise StaleRevisionError(knowledge_id)
            row = connection.execute(
                "SELECT * FROM future_knowledge WHERE id = ?",
                (knowledge_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(knowledge_id)
        return self._future_knowledge(row)

    def create_original_timeline_event(
        self,
        project_id: str,
        request: CreateTimelineEventRequest,
    ) -> TimelineEvent:
        event_id = str(uuid4())
        timestamp = now_iso()
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project is None:
                raise NotFoundError(project_id)
            connection.execute(
                """
                INSERT INTO timeline_events (
                    id, project_id, layer, event_year, title, summary,
                    source_chapter_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    event_id,
                    project_id,
                    TimelineLayer.ORIGINAL.value,
                    request.event_year,
                    request.title,
                    request.summary,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )
            row = connection.execute(
                "SELECT * FROM timeline_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(event_id)
        return self._timeline_event(row)

    def create_fact_change_set(self, chapter_id: str) -> FactChangeSet:
        change_set_id = str(uuid4())
        timestamp = now_iso()
        with self.database.connect() as connection:
            chapter = connection.execute(
                """
                SELECT c.*, p.rebirth_year
                FROM chapters c
                JOIN projects p ON p.id = c.project_id
                WHERE c.id = ?
                """,
                (chapter_id,),
            ).fetchone()
            if chapter is None:
                raise NotFoundError(chapter_id)
            if chapter["status"] != ChapterStatus.APPROVED.value:
                raise InvalidChapterStateError(chapter["status"])
            existing = connection.execute(
                """
                SELECT id FROM fact_change_sets
                WHERE chapter_id = ? AND chapter_revision = ?
                """,
                (chapter_id, chapter["revision"]),
            ).fetchone()
            if existing is not None:
                change_set_id = existing["id"]
            else:
                state_change = chapter["state_change"].strip()
                open_thread = chapter["ending_cliffhanger"].strip()
                if not state_change or not open_thread:
                    raise InvalidChapterStateError("incomplete_brief")
                connection.execute(
                    """
                    INSERT INTO fact_change_sets (
                        id, chapter_id, chapter_revision, state, revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        change_set_id,
                        chapter_id,
                        chapter["revision"],
                        FactChangeSetState.CANDIDATE.value,
                        timestamp,
                        timestamp,
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO fact_changes (
                        id, change_set_id, kind, content, event_year
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            str(uuid4()),
                            change_set_id,
                            FactKind.STATE_CHANGE.value,
                            state_change,
                            chapter["rebirth_year"],
                        ),
                        (
                            str(uuid4()),
                            change_set_id,
                            FactKind.OPEN_THREAD.value,
                            open_thread,
                            None,
                        ),
                    ],
                )
        return self.get_fact_change_set(change_set_id)

    def get_fact_change_set(self, change_set_id: str) -> FactChangeSet:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM fact_change_sets WHERE id = ?",
                (change_set_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(change_set_id)
            change_rows = connection.execute(
                "SELECT * FROM fact_changes WHERE change_set_id = ? ORDER BY rowid",
                (change_set_id,),
            ).fetchall()
        return self._fact_change_set(row, [self._fact_change(item) for item in change_rows])

    def apply_fact_change_set(
        self,
        change_set_id: str,
        request: ApplyFactChangeSetRequest,
    ) -> FactChangeSet:
        timestamp = now_iso()
        selected_ids = set(request.selected_change_ids)
        with self.database.connect() as connection:
            change_set = connection.execute(
                """
                SELECT s.*, c.project_id, c.title AS chapter_title,
                       c.chapter_number, p.rebirth_year
                FROM fact_change_sets s
                JOIN chapters c ON c.id = s.chapter_id
                JOIN projects p ON p.id = c.project_id
                WHERE s.id = ?
                """,
                (change_set_id,),
            ).fetchone()
            if change_set is None:
                raise NotFoundError(change_set_id)
            if change_set["revision"] != request.expected_revision:
                raise StaleRevisionError(str(change_set["revision"]))
            if change_set["state"] != FactChangeSetState.CANDIDATE.value:
                raise InvalidFactChangeSetStateError(change_set["state"])
            change_rows = connection.execute(
                "SELECT * FROM fact_changes WHERE change_set_id = ? ORDER BY rowid",
                (change_set_id,),
            ).fetchall()
            known_ids = {row["id"] for row in change_rows}
            if not selected_ids.issubset(known_ids):
                raise InvalidFactSelectionError(change_set_id)
            result = connection.execute(
                """
                UPDATE fact_change_sets
                SET state = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND state = ? AND revision = ?
                """,
                (
                    FactChangeSetState.APPLIED.value,
                    timestamp,
                    change_set_id,
                    FactChangeSetState.CANDIDATE.value,
                    request.expected_revision,
                ),
            )
            if result.rowcount == 0:
                raise StaleRevisionError(change_set_id)
            for change in change_rows:
                if change["id"] not in selected_ids:
                    continue
                connection.execute(
                    """
                    INSERT INTO story_facts (
                        id, project_id, source_chapter_id, kind, content, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        change_set["project_id"],
                        change_set["chapter_id"],
                        change["kind"],
                        change["content"],
                        timestamp,
                    ),
                )
                if change["kind"] == FactKind.STATE_CHANGE.value:
                    timeline_event_id = str(uuid4())
                    connection.execute(
                        """
                        INSERT INTO timeline_events (
                            id, project_id, layer, event_year, title, summary,
                            source_chapter_id, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            timeline_event_id,
                            change_set["project_id"],
                            TimelineLayer.NOVEL.value,
                            change["event_year"] or change_set["rebirth_year"],
                            change_set["chapter_title"],
                            change["content"],
                            change_set["chapter_id"],
                            timestamp,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE future_knowledge
                        SET status = ?, divergence_event_id = ?,
                            revision = revision + 1, updated_at = ?
                        WHERE project_id = ? AND status = ? AND future_year >= ?
                        """,
                        (
                            KnowledgeStatus.CANDIDATE_INVALID.value,
                            timeline_event_id,
                            timestamp,
                            change_set["project_id"],
                            KnowledgeStatus.VALID.value,
                            change["event_year"] or change_set["rebirth_year"],
                        ),
                    )
                elif change["kind"] == FactKind.OPEN_THREAD.value:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO story_threads (
                            id, project_id, source_chapter_id, title, summary, status,
                            planted_chapter_number, resolved_chapter_id, revision,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            change_set["project_id"],
                            change_set["chapter_id"],
                            change["content"],
                            "由定稿事实自动建立",
                            StoryThreadStatus.OPEN.value,
                            change_set["chapter_number"],
                            timestamp,
                            timestamp,
                        ),
                    )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, change_set["project_id"]),
            )
        return self.get_fact_change_set(change_set_id)

    def reject_fact_change_set(
        self,
        change_set_id: str,
        request: RejectFactChangeSetRequest,
    ) -> FactChangeSet:
        timestamp = now_iso()
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT state, revision FROM fact_change_sets WHERE id = ?",
                (change_set_id,),
            ).fetchone()
            if current is None:
                raise NotFoundError(change_set_id)
            if current["revision"] != request.expected_revision:
                raise StaleRevisionError(str(current["revision"]))
            if current["state"] != FactChangeSetState.CANDIDATE.value:
                raise InvalidFactChangeSetStateError(current["state"])
            connection.execute(
                """
                UPDATE fact_change_sets
                SET state = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND state = ? AND revision = ?
                """,
                (
                    FactChangeSetState.REJECTED.value,
                    timestamp,
                    change_set_id,
                    FactChangeSetState.CANDIDATE.value,
                    request.expected_revision,
                ),
            )
        return self.get_fact_change_set(change_set_id)

    def create_chapter(self, project_id: str, request: CreateChapterRequest) -> Chapter:
        chapter_id = str(uuid4())
        timestamp = now_iso()
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project is None:
                raise NotFoundError(project_id)
            last_number = connection.execute(
                "SELECT COALESCE(MAX(chapter_number), 0) FROM chapters WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            if last_number != request.expected_last_chapter_number:
                raise StaleChapterSequenceError(str(last_number))
            next_number = last_number + 1
            title = request.title or f"第{next_number}章 未命名"
            connection.execute(
                """
                INSERT INTO chapters (
                    id, project_id, volume_number, chapter_number, title, content,
                    reader_promise, opening_hook, state_change, emotional_payoff,
                    ending_cliffhanger,
                    status, revision, updated_at
                ) VALUES (?, ?, 1, ?, ?, '', ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    chapter_id,
                    project_id,
                    next_number,
                    title,
                    request.reader_promise,
                    request.opening_hook,
                    request.state_change,
                    request.emotional_payoff,
                    request.ending_cliffhanger,
                    ChapterStatus.PLANNED.value,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )
            row = connection.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
        if row is None:
            raise NotFoundError(chapter_id)
        return self._chapter(row)

    def update_chapter(self, chapter_id: str, request: UpdateChapterRequest) -> Chapter:
        timestamp = now_iso()
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE chapters
                SET content = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ? AND status != ?
                """,
                (
                    request.content,
                    timestamp,
                    chapter_id,
                    request.expected_revision,
                    ChapterStatus.APPROVED.value,
                ),
            )
            if result.rowcount == 0:
                current = connection.execute(
                    "SELECT revision FROM chapters WHERE id = ?",
                    (chapter_id,),
                ).fetchone()
                if current is None:
                    raise NotFoundError(chapter_id)
                status = connection.execute(
                    "SELECT status FROM chapters WHERE id = ?",
                    (chapter_id,),
                ).fetchone()["status"]
                if status == ChapterStatus.APPROVED.value:
                    raise InvalidChapterStateError(status)
                raise StaleRevisionError(str(current["revision"]))
            connection.execute(
                """
                UPDATE projects SET updated_at = ?
                WHERE id = (SELECT project_id FROM chapters WHERE id = ?)
                """,
                (timestamp, chapter_id),
            )
            row = connection.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
        if row is None:  # defensive: the row was updated in the same transaction
            raise NotFoundError(chapter_id)
        return self._chapter(row)

    def update_chapter_brief(
        self,
        chapter_id: str,
        request: UpdateChapterBriefRequest,
    ) -> Chapter:
        timestamp = now_iso()
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE chapters
                SET title = COALESCE(?, title), reader_promise = ?, opening_hook = ?,
                    state_change = ?, emotional_payoff = ?, ending_cliffhanger = ?,
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ? AND status != ?
                """,
                (
                    request.title,
                    request.reader_promise,
                    request.opening_hook,
                    request.state_change,
                    request.emotional_payoff,
                    request.ending_cliffhanger,
                    timestamp,
                    chapter_id,
                    request.expected_revision,
                    ChapterStatus.APPROVED.value,
                ),
            )
            if result.rowcount == 0:
                current = connection.execute(
                    "SELECT revision FROM chapters WHERE id = ?",
                    (chapter_id,),
                ).fetchone()
                if current is None:
                    raise NotFoundError(chapter_id)
                status = connection.execute(
                    "SELECT status FROM chapters WHERE id = ?",
                    (chapter_id,),
                ).fetchone()["status"]
                if status == ChapterStatus.APPROVED.value:
                    raise InvalidChapterStateError(status)
                raise StaleRevisionError(str(current["revision"]))
            connection.execute(
                """
                UPDATE projects SET updated_at = ?
                WHERE id = (SELECT project_id FROM chapters WHERE id = ?)
                """,
                (timestamp, chapter_id),
            )
            row = connection.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
        if row is None:
            raise NotFoundError(chapter_id)
        return self._chapter(row)

    def transition_chapter(
        self,
        chapter_id: str,
        request: TransitionChapterRequest,
    ) -> Chapter:
        timestamp = now_iso()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM chapters WHERE id = ?",
                (chapter_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(chapter_id)
            if row["revision"] != request.expected_revision:
                raise StaleRevisionError(str(row["revision"]))
            current_status = ChapterStatus(row["status"])
            if request.target_status not in ALLOWED_CHAPTER_TRANSITIONS[current_status]:
                raise InvalidChapterStateError(
                    f"{current_status.value}->{request.target_status.value}"
                )
            if request.target_status in {
                ChapterStatus.DRAFTED,
                ChapterStatus.REVIEWING,
                ChapterStatus.APPROVED,
            } and not row["content"].strip():
                raise InvalidChapterStateError("empty_content")
            if request.target_status in {ChapterStatus.REVIEWING, ChapterStatus.APPROVED} and not all(
                row[field].strip()
                for field in ("opening_hook", "state_change", "ending_cliffhanger")
            ):
                raise InvalidChapterStateError("incomplete_brief")
            connection.execute(
                """
                UPDATE chapters
                SET status = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    request.target_status.value,
                    timestamp,
                    chapter_id,
                    request.expected_revision,
                ),
            )
            connection.execute(
                """
                INSERT INTO chapter_events (
                    id, chapter_id, from_status, to_status, revision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    chapter_id,
                    current_status.value,
                    request.target_status.value,
                    request.expected_revision + 1,
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, row["project_id"]),
            )
            updated = connection.execute(
                "SELECT * FROM chapters WHERE id = ?",
                (chapter_id,),
            ).fetchone()
        if updated is None:
            raise NotFoundError(chapter_id)
        return self._chapter(updated)

    def create_generation_run(
        self,
        chapter_id: str,
        expected_revision: int,
        provider: str = "demo",
        model: str = "replay-v1",
    ) -> GenerationRun:
        run_id = str(uuid4())
        timestamp = now_iso()
        with self.database.connect() as connection:
            chapter = connection.execute(
                "SELECT revision, status FROM chapters WHERE id = ?",
                (chapter_id,),
            ).fetchone()
            if chapter is None:
                raise NotFoundError(chapter_id)
            if chapter["revision"] != expected_revision:
                raise StaleRevisionError(str(chapter["revision"]))
            if chapter["status"] not in {
                ChapterStatus.PLANNED.value,
                ChapterStatus.DRAFTED.value,
            }:
                raise InvalidChapterStateError(chapter["status"])
            connection.execute(
                """
                INSERT INTO generation_runs (
                    id, chapter_id, state, expected_chapter_revision,
                    candidate_content, error_message, provider, model, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    chapter_id,
                    GenerationState.CONTEXT_READY.value,
                    expected_revision,
                    provider,
                    model,
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event(connection, run_id, GenerationState.CONTEXT_READY, timestamp)
        return self.get_generation_run(run_id)

    def get_generation_run(self, run_id: str) -> GenerationRun:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(run_id)
        return self._generation_run(row)

    def materialize_generation_run(
        self,
        run_id: str,
        chapter_id: str,
        expected_revision: int,
        candidate_content: str,
        provider: str,
        model: str,
    ) -> GenerationRun:
        """Materialize an immutable job artifact as an author-reviewable candidate."""
        timestamp = now_iso()
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT id FROM chapters WHERE id = ?",
                (chapter_id,),
            ).fetchone() is None:
                raise NotFoundError(chapter_id)
            result = connection.execute(
                """
                INSERT INTO generation_runs (
                    id, chapter_id, state, expected_chapter_revision,
                    candidate_content, error_message, provider, model, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    run_id,
                    chapter_id,
                    GenerationState.DRAFTED.value,
                    expected_revision,
                    candidate_content,
                    provider,
                    model,
                    timestamp,
                    timestamp,
                ),
            )
            if result.rowcount == 1:
                for state in (
                    GenerationState.CONTEXT_READY,
                    GenerationState.GENERATING,
                    GenerationState.DRAFTED,
                ):
                    self._append_event(connection, run_id, state, timestamp)
            row = connection.execute(
                "SELECT * FROM generation_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(run_id)
        run = self._generation_run(row)
        if (
            run.chapter_id != chapter_id
            or run.expected_chapter_revision != expected_revision
            or run.candidate_content != candidate_content
            or run.provider != provider
            or run.model != model
        ):
            raise ValueError("生成候选标识对应了不同产物")
        return run

    def get_generation_context(self, run_id: str) -> ChapterContext:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT p.title AS project_title, p.genre, p.rebirth_year, p.rebirth_location,
                       c.title AS chapter_title, c.reader_promise, c.opening_hook,
                       c.state_change, c.emotional_payoff, c.ending_cliffhanger
                FROM generation_runs r
                JOIN chapters c ON c.id = r.chapter_id
                JOIN projects p ON p.id = c.project_id
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(run_id)
        return ChapterContext(
            project_title=row["project_title"],
            genre=row["genre"],
            rebirth_year=row["rebirth_year"],
            rebirth_location=row["rebirth_location"],
            chapter_title=row["chapter_title"],
            reader_promise=row["reader_promise"],
            opening_hook=row["opening_hook"],
            state_change=row["state_change"],
            emotional_payoff=row["emotional_payoff"],
            ending_cliffhanger=row["ending_cliffhanger"],
        )

    def transition_generation(
        self,
        run_id: str,
        expected_state: GenerationState,
        next_state: GenerationState,
        candidate_content: str | None = None,
        error_message: str | None = None,
    ) -> GenerationRun:
        timestamp = now_iso()
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE generation_runs
                SET state = ?, candidate_content = COALESCE(?, candidate_content),
                    error_message = ?, updated_at = ?
                WHERE id = ? AND state = ?
                """,
                (
                    next_state.value,
                    candidate_content,
                    error_message,
                    timestamp,
                    run_id,
                    expected_state.value,
                ),
            )
            if result.rowcount == 0:
                current = connection.execute(
                    "SELECT state FROM generation_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                if current is None:
                    raise NotFoundError(run_id)
                return self.get_generation_run(run_id)
            self._append_event(connection, run_id, next_state, timestamp)
        return self.get_generation_run(run_id)

    def apply_generation(self, run_id: str, expected_revision: int) -> Chapter:
        timestamp = now_iso()
        with self.database.connect() as connection:
            run = connection.execute(
                "SELECT * FROM generation_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise NotFoundError(run_id)
            if run["state"] != GenerationState.DRAFTED.value or run["candidate_content"] is None:
                raise ValueError("生成任务尚无可采用草稿")
            result = connection.execute(
                """
                UPDATE chapters
                SET content = ?, status = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    run["candidate_content"],
                    ChapterStatus.DRAFTED.value,
                    timestamp,
                    run["chapter_id"],
                    expected_revision,
                ),
            )
            if result.rowcount == 0:
                current = connection.execute(
                    "SELECT revision FROM chapters WHERE id = ?",
                    (run["chapter_id"],),
                ).fetchone()
                if current is None:
                    raise NotFoundError(run["chapter_id"])
                raise StaleRevisionError(str(current["revision"]))
            connection.execute(
                "UPDATE generation_runs SET state = ?, updated_at = ? WHERE id = ?",
                (GenerationState.APPLIED.value, timestamp, run_id),
            )
            self._append_event(connection, run_id, GenerationState.APPLIED, timestamp)
            chapter = connection.execute(
                "SELECT * FROM chapters WHERE id = ?",
                (run["chapter_id"],),
            ).fetchone()
        if chapter is None:
            raise NotFoundError(run_id)
        return self._chapter(chapter)

    @staticmethod
    def _append_event(connection: Connection, run_id: str, state: GenerationState, timestamp: str) -> None:
        cursor = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM run_events WHERE run_id = ?",
            (run_id,),
        )
        sequence = cursor.fetchone()[0]
        connection.execute(
            "INSERT INTO run_events (id, run_id, sequence, state, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid4()), run_id, sequence, state.value, timestamp),
        )

    @staticmethod
    def _project(row: Row) -> Project:
        return Project.model_validate(dict(row))

    @staticmethod
    def _chapter(row: Row) -> Chapter:
        return Chapter.model_validate(dict(row))

    @staticmethod
    def _chapter_summary(row: Row) -> ChapterSummary:
        return ChapterSummary.model_validate(dict(row))

    @staticmethod
    def _generation_run(row: Row) -> GenerationRun:
        return GenerationRun.model_validate(dict(row))

    @staticmethod
    def _timeline_event(row: Row) -> TimelineEvent:
        return TimelineEvent.model_validate(dict(row))

    @staticmethod
    def _story_fact(row: Row) -> StoryFact:
        return StoryFact.model_validate(dict(row))

    @staticmethod
    def _fact_change(row: Row) -> FactChange:
        return FactChange.model_validate(dict(row))

    @staticmethod
    def _fact_change_set(row: Row, changes: list[FactChange]) -> FactChangeSet:
        return FactChangeSet.model_validate({**dict(row), "changes": changes})

    @staticmethod
    def _future_knowledge(row: Row) -> FutureKnowledge:
        return FutureKnowledge.model_validate(dict(row))

    @staticmethod
    def _story_entity(row: Row) -> StoryEntity:
        return StoryEntity.model_validate(dict(row))

    @staticmethod
    def _story_thread(row: Row) -> StoryThread:
        return StoryThread.model_validate(dict(row))

    @staticmethod
    def _source_card(row: Row) -> SourceCard:
        return SourceCard.model_validate(dict(row))

    @staticmethod
    def _reference_segment(row: Row) -> ReferenceSegment:
        return ReferenceSegment.model_validate(dict(row))

    @staticmethod
    def _reference_work(
        row: Row,
        segments: list[ReferenceSegment],
        *,
        project_ids: list[str] | None = None,
    ) -> ReferenceWork:
        projects = project_ids or []
        return ReferenceWork.model_validate({
            **dict(row),
            "project_id": projects[0] if len(projects) == 1 else None,
            "project_ids": projects,
            "segments": segments,
        })

    @staticmethod
    def _reference_pattern_card(row: Row) -> ReferencePatternCard:
        return ReferencePatternCard.model_validate({
            **dict(row),
            **json.loads(row["proposal_json"]),
            "selected_segment_ids": json.loads(row["selected_segment_ids_json"]),
        })

    @staticmethod
    def _reference_pattern_application(row: Row) -> ReferencePatternApplication:
        return ReferencePatternApplication.model_validate({
            **dict(row),
            "selected_dimensions": json.loads(row["selected_dimensions_json"]),
            "dimensions": json.loads(row["dimensions_json"]),
        })
