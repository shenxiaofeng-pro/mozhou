import json
from sqlite3 import Connection, Row
from uuid import uuid4

from app.database import Database
from app.director.rules import regeneration_impact
from app.models import (
    BookBlueprint,
    BookBlueprintContent,
    BookBlueprintField,
    DirectorEntityProposal,
    DirectorExpansionDraft,
    DirectorFieldProposal,
    DirectorPlanningSnapshot,
    DirectorStartupCandidate,
    Genre,
    RollingChapterPlan,
    RollingChapterPlanContent,
    UpdateBookBlueprintRequest,
    UpdateRollingChapterPlanRequest,
    UpdateVolumePlanRequest,
    VolumePlan,
    VolumePlanContent,
)


class DirectorNotFoundError(LookupError):
    pass


class StaleDirectorRevisionError(RuntimeError):
    pass


class InvalidDirectorChangeError(ValueError):
    pass


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _all_field_state[Value](value: Value) -> dict[BookBlueprintField, Value]:
    return {field: value for field in BookBlueprintField}


class DirectorRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_book_blueprint(self, project_id: str) -> BookBlueprint | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM book_blueprints WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return self.parse_book_blueprint(row) if row is not None else None

    def get_snapshot(self, project_id: str) -> DirectorPlanningSnapshot:
        with self.database.connect() as connection:
            if (
                connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
                is None
            ):
                raise DirectorNotFoundError(project_id)
        return DirectorPlanningSnapshot(
            book_blueprint=self.get_book_blueprint(project_id),
            volume_plans=self.list_volume_plans(project_id),
            rolling_chapter_plans=self.list_rolling_chapter_plans(project_id),
        )

    def require_book_blueprint(self, project_id: str) -> BookBlueprint:
        blueprint = self.get_book_blueprint(project_id)
        if blueprint is None:
            raise DirectorNotFoundError(project_id)
        return blueprint

    def list_volume_plans(self, project_id: str) -> list[VolumePlan]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM volume_plans WHERE project_id = ? ORDER BY volume_number",
                (project_id,),
            ).fetchall()
        return [self.parse_volume_plan(row) for row in rows]

    def list_rolling_chapter_plans(self, project_id: str) -> list[RollingChapterPlan]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM rolling_chapter_plans WHERE project_id = ? ORDER BY chapter_number",
                (project_id,),
            ).fetchall()
        return [self.parse_rolling_plan(row) for row in rows]

    def get_rolling_plan_for_chapter(
        self,
        project_id: str,
        chapter_number: int,
    ) -> RollingChapterPlan | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM rolling_chapter_plans WHERE project_id = ? AND chapter_number = ?",
                (project_id, chapter_number),
            ).fetchone()
        return self.parse_rolling_plan(row) if row is not None else None

    def select_startup_candidate(
        self,
        project_id: str,
        idea: str,
        candidate: DirectorStartupCandidate,
        expected_blueprint_revision: int | None,
    ) -> BookBlueprint:
        timestamp = _now_iso()
        blueprint_id = str(uuid4())
        locks = _all_field_state(False)
        versions = _all_field_state(1)
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if project is None:
                raise DirectorNotFoundError(project_id)
            existing = connection.execute(
                "SELECT revision FROM book_blueprints WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if existing is not None:
                if expected_blueprint_revision != int(existing["revision"]):
                    raise StaleDirectorRevisionError(str(existing["revision"]))
                raise InvalidDirectorChangeError("startup_candidate_already_selected")
            if expected_blueprint_revision is not None:
                raise StaleDirectorRevisionError("missing_blueprint")
            connection.execute(
                """
                INSERT INTO book_blueprints (
                    id, project_id, idea, content_json, locks_json,
                    field_versions_json, stale_fields_json, plan_stale,
                    source_candidate_id, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', 1, ?, 0, ?, ?)
                """,
                (
                    blueprint_id,
                    project_id,
                    idea,
                    candidate.blueprint.model_dump_json(),
                    _json({field.value: value for field, value in locks.items()}),
                    _json({field.value: value for field, value in versions.items()}),
                    candidate.id,
                    timestamp,
                    timestamp,
                ),
            )
            self._sync_project(connection, project_id, candidate.blueprint, timestamp)
            row = connection.execute(
                "SELECT * FROM book_blueprints WHERE id = ?",
                (blueprint_id,),
            ).fetchone()
        if row is None:
            raise DirectorNotFoundError(blueprint_id)
        return self.parse_book_blueprint(row)

    def update_book_blueprint(
        self,
        project_id: str,
        request: UpdateBookBlueprintRequest,
    ) -> BookBlueprint:
        current = self.require_book_blueprint(project_id)
        if current.revision != request.expected_revision:
            raise StaleDirectorRevisionError(str(current.revision))
        before = current.content.model_dump(mode="json")
        after = request.content.model_dump(mode="json")
        actual_changed = {
            field for field in BookBlueprintField if before[field.value] != after[field.value]
        }
        declared = set(request.changed_fields)
        if actual_changed != declared:
            raise InvalidDirectorChangeError("declared_fields_do_not_match")
        for field in actual_changed:
            remains_locked = request.lock_updates.get(field, current.locks[field])
            if current.locks[field] and remains_locked:
                raise InvalidDirectorChangeError("locked_field")
        locks = dict(current.locks)
        locks.update(request.lock_updates)
        versions = dict(current.field_versions)
        for field in actual_changed:
            versions[field] += 1
        stale = set(current.stale_fields)
        plan_stale = current.plan_stale
        for field in actual_changed:
            stale.discard(field)
            impact = regeneration_impact(current, field)
            stale.update(
                dependant for dependant in impact.downstream_affected if not locks[dependant]
            )
            plan_stale = plan_stale or impact.will_mark_plan_stale
        revision = current.revision + 1
        timestamp = _now_iso()
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE book_blueprints
                SET content_json = ?, locks_json = ?, field_versions_json = ?,
                    stale_fields_json = ?, plan_stale = ?, revision = ?, updated_at = ?
                WHERE project_id = ? AND revision = ?
                """,
                (
                    request.content.model_dump_json(),
                    _json({field.value: value for field, value in locks.items()}),
                    _json({field.value: value for field, value in versions.items()}),
                    _json([field.value for field in BookBlueprintField if field in stale]),
                    int(plan_stale),
                    revision,
                    timestamp,
                    project_id,
                    request.expected_revision,
                ),
            )
            if result.rowcount != 1:
                raise StaleDirectorRevisionError(str(current.revision))
            self._sync_project(connection, project_id, request.content, timestamp)
            row = connection.execute(
                "SELECT * FROM book_blueprints WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            raise DirectorNotFoundError(project_id)
        return self.parse_book_blueprint(row)

    def apply_field_proposal(
        self,
        project_id: str,
        proposal: DirectorFieldProposal,
        expected_revision: int,
    ) -> BookBlueprint:
        current = self.require_book_blueprint(project_id)
        if (
            current.revision != expected_revision
            or proposal.project_id != project_id
            or proposal.blueprint_revision != expected_revision
        ):
            raise StaleDirectorRevisionError(str(current.revision))
        field = proposal.target_field
        if current.locks[field]:
            raise InvalidDirectorChangeError("locked_field")
        next_value = self._coerce_field_value(field, proposal.value)
        content_payload = current.content.model_dump(mode="json")
        if content_payload[field.value] == next_value:
            raise InvalidDirectorChangeError("unchanged_proposal")
        content_payload[field.value] = next_value
        return self.update_book_blueprint(
            project_id,
            UpdateBookBlueprintRequest(
                content=BookBlueprintContent.model_validate(content_payload),
                changed_fields=[field],
                expected_revision=expected_revision,
            ),
        )

    def apply_expansion(
        self,
        project_id: str,
        proposal: DirectorExpansionDraft,
        expected_blueprint_revision: int,
    ) -> tuple[BookBlueprint, list[VolumePlan], list[RollingChapterPlan]]:
        blueprint = self.require_book_blueprint(project_id)
        if blueprint.revision != expected_blueprint_revision:
            raise StaleDirectorRevisionError(str(blueprint.revision))
        if blueprint.stale_fields:
            raise InvalidDirectorChangeError("blueprint_has_stale_fields")
        timestamp = _now_iso()
        volumes_by_number: dict[int, str] = {}
        with self.database.connect() as connection:
            for volume_content in proposal.volumes:
                existing = connection.execute(
                    "SELECT * FROM volume_plans WHERE project_id = ? AND volume_number = ?",
                    (project_id, volume_content.volume_number),
                ).fetchone()
                if existing is not None and bool(existing["locked"]):
                    if (
                        VolumePlanContent.model_validate_json(existing["content_json"])
                        != volume_content
                    ):
                        raise InvalidDirectorChangeError("locked_volume_plan")
                    volume_id = str(existing["id"])
                elif existing is None:
                    volume_id = str(uuid4())
                    connection.execute(
                        """
                        INSERT INTO volume_plans (
                            id, project_id, volume_number, content_json, locked,
                            revision, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, 0, 0, ?, ?)
                        """,
                        (
                            volume_id,
                            project_id,
                            volume_content.volume_number,
                            volume_content.model_dump_json(),
                            timestamp,
                            timestamp,
                        ),
                    )
                else:
                    volume_id = str(existing["id"])
                    connection.execute(
                        """
                        UPDATE volume_plans SET content_json = ?, revision = revision + 1,
                            updated_at = ? WHERE id = ?
                        """,
                        (volume_content.model_dump_json(), timestamp, volume_id),
                    )
                volumes_by_number[volume_content.volume_number] = volume_id

            default_volume_id = volumes_by_number[min(volumes_by_number)]
            for chapter_content in proposal.chapters:
                existing = connection.execute(
                    "SELECT * FROM rolling_chapter_plans "
                    "WHERE project_id = ? AND chapter_number = ?",
                    (project_id, chapter_content.chapter_number),
                ).fetchone()
                if existing is not None and bool(existing["locked"]):
                    if (
                        RollingChapterPlanContent.model_validate_json(existing["content_json"])
                        != chapter_content
                    ):
                        raise InvalidDirectorChangeError("locked_chapter_plan")
                elif existing is None:
                    connection.execute(
                        """
                        INSERT INTO rolling_chapter_plans (
                            id, project_id, volume_plan_id, chapter_number,
                            content_json, locked, revision, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            project_id,
                            default_volume_id,
                            chapter_content.chapter_number,
                            chapter_content.model_dump_json(),
                            timestamp,
                            timestamp,
                        ),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE rolling_chapter_plans
                        SET volume_plan_id = ?, content_json = ?, revision = revision + 1,
                            updated_at = ? WHERE id = ?
                        """,
                        (
                            default_volume_id,
                            chapter_content.model_dump_json(),
                            timestamp,
                            existing["id"],
                        ),
                    )
                chapter = connection.execute(
                    "SELECT id FROM chapters WHERE project_id = ? AND chapter_number = ?",
                    (project_id, chapter_content.chapter_number),
                ).fetchone()
                if chapter is None:
                    connection.execute(
                        """
                        INSERT INTO chapters (
                            id, project_id, volume_number, chapter_number, title,
                            content, status, revision, updated_at
                        ) VALUES (?, ?, 1, ?, ?, '', 'planned', 0, ?)
                        """,
                        (
                            str(uuid4()),
                            project_id,
                            chapter_content.chapter_number,
                            chapter_content.title,
                            timestamp,
                        ),
                    )
            for entity in proposal.entities:
                self._insert_entity_if_missing(connection, project_id, entity, timestamp)
            result = connection.execute(
                """
                UPDATE book_blueprints
                SET plan_stale = 0, revision = revision + 1, updated_at = ?
                WHERE project_id = ? AND revision = ?
                """,
                (timestamp, project_id, expected_blueprint_revision),
            )
            if result.rowcount != 1:
                raise StaleDirectorRevisionError(str(blueprint.revision))
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )
        return (
            self.require_book_blueprint(project_id),
            self.list_volume_plans(project_id),
            self.list_rolling_chapter_plans(project_id),
        )

    def update_volume_plan(
        self,
        project_id: str,
        plan_id: str,
        request: UpdateVolumePlanRequest,
    ) -> VolumePlan:
        timestamp = _now_iso()
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT * FROM volume_plans WHERE id = ? AND project_id = ?",
                (plan_id, project_id),
            ).fetchone()
            if current is None:
                raise DirectorNotFoundError(plan_id)
            if int(current["revision"]) != request.expected_revision:
                raise StaleDirectorRevisionError(str(current["revision"]))
            previous = VolumePlanContent.model_validate_json(current["content_json"])
            if bool(current["locked"]) and request.locked and previous != request.content:
                raise InvalidDirectorChangeError("locked_volume_plan")
            result = connection.execute(
                """
                UPDATE volume_plans SET volume_number = ?, content_json = ?, locked = ?,
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND project_id = ? AND revision = ?
                """,
                (
                    request.content.volume_number,
                    request.content.model_dump_json(),
                    int(request.locked),
                    timestamp,
                    plan_id,
                    project_id,
                    request.expected_revision,
                ),
            )
            if result.rowcount != 1:
                raise StaleDirectorRevisionError(str(request.expected_revision))
            row = connection.execute(
                "SELECT * FROM volume_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            raise DirectorNotFoundError(plan_id)
        return self.parse_volume_plan(row)

    def update_rolling_plan(
        self,
        project_id: str,
        plan_id: str,
        request: UpdateRollingChapterPlanRequest,
    ) -> RollingChapterPlan:
        timestamp = _now_iso()
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT * FROM rolling_chapter_plans WHERE id = ? AND project_id = ?",
                (plan_id, project_id),
            ).fetchone()
            if current is None:
                raise DirectorNotFoundError(plan_id)
            if int(current["revision"]) != request.expected_revision:
                raise StaleDirectorRevisionError(str(current["revision"]))
            previous = RollingChapterPlanContent.model_validate_json(current["content_json"])
            if bool(current["locked"]) and request.locked and previous != request.content:
                raise InvalidDirectorChangeError("locked_chapter_plan")
            result = connection.execute(
                """
                UPDATE rolling_chapter_plans
                SET chapter_number = ?, content_json = ?, locked = ?,
                    revision = revision + 1, updated_at = ?
                WHERE id = ? AND project_id = ? AND revision = ?
                """,
                (
                    request.content.chapter_number,
                    request.content.model_dump_json(),
                    int(request.locked),
                    timestamp,
                    plan_id,
                    project_id,
                    request.expected_revision,
                ),
            )
            if result.rowcount != 1:
                raise StaleDirectorRevisionError(str(request.expected_revision))
            row = connection.execute(
                "SELECT * FROM rolling_chapter_plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            raise DirectorNotFoundError(plan_id)
        return self.parse_rolling_plan(row)

    @staticmethod
    def _coerce_field_value(
        field: BookBlueprintField,
        value: str | list[str],
    ) -> object:
        if field == BookBlueprintField.CORE_SELLING_POINTS:
            if not isinstance(value, list):
                raise InvalidDirectorChangeError("selling_points_must_be_list")
            return value
        if not isinstance(value, str):
            raise InvalidDirectorChangeError("field_must_be_text")
        if field == BookBlueprintField.REBIRTH_YEAR:
            try:
                return int(value)
            except ValueError as error:
                raise InvalidDirectorChangeError("rebirth_year_must_be_integer") from error
        if field == BookBlueprintField.GENRE:
            try:
                return Genre(value).value
            except ValueError as error:
                raise InvalidDirectorChangeError("invalid_genre") from error
        return value

    @staticmethod
    def _sync_project(
        connection: Connection,
        project_id: str,
        content: BookBlueprintContent,
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            UPDATE projects
            SET title = ?, genre = ?, rebirth_year = ?, rebirth_location = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                content.title,
                content.genre.value,
                content.rebirth_year,
                content.rebirth_location,
                timestamp,
                project_id,
            ),
        )

    @staticmethod
    def _insert_entity_if_missing(
        connection: Connection,
        project_id: str,
        entity: DirectorEntityProposal,
        timestamp: str,
    ) -> None:
        existing = connection.execute(
            "SELECT 1 FROM story_entities WHERE project_id = ? AND kind = ? AND name = ?",
            (project_id, entity.kind.value, entity.name),
        ).fetchone()
        if existing is not None:
            return
        connection.execute(
            """
            INSERT INTO story_entities (
                id, project_id, kind, name, role, goal, current_state,
                relationship_notes, revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                str(uuid4()),
                project_id,
                entity.kind.value,
                entity.name,
                entity.role,
                entity.goal,
                entity.initial_state,
                entity.relationship_notes,
                timestamp,
                timestamp,
            ),
        )

    @staticmethod
    def parse_book_blueprint(row: Row) -> BookBlueprint:
        return BookBlueprint.model_validate(
            {
                **dict(row),
                "content": json.loads(row["content_json"]),
                "locks": json.loads(row["locks_json"]),
                "field_versions": json.loads(row["field_versions_json"]),
                "stale_fields": json.loads(row["stale_fields_json"]),
                "plan_stale": bool(row["plan_stale"]),
            }
        )

    @staticmethod
    def parse_volume_plan(row: Row) -> VolumePlan:
        return VolumePlan.model_validate(
            {
                **json.loads(row["content_json"]),
                "id": row["id"],
                "project_id": row["project_id"],
                "revision": row["revision"],
                "locked": bool(row["locked"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    @staticmethod
    def parse_rolling_plan(row: Row) -> RollingChapterPlan:
        return RollingChapterPlan.model_validate(
            {
                **json.loads(row["content_json"]),
                "id": row["id"],
                "project_id": row["project_id"],
                "volume_plan_id": row["volume_plan_id"],
                "revision": row["revision"],
                "locked": bool(row["locked"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
