from __future__ import annotations

import json
import sqlite3
from sqlite3 import Connection, Row
from typing import cast
from uuid import uuid4

from app.database import Database
from app.repository import now_iso
from app.writing_patterns.compiler import (
    WRITING_PATTERN_COMPILER_VERSION,
    canonical_json,
    canonical_sha256,
    recipe_content_sha256,
    recipe_source_snapshot_sha256,
)
from app.writing_patterns.models import (
    AppliedWritingPatternConflictDecision,
    ModelSafeWritingPatternProfile,
    RecipeSourceSnapshot,
    UpdateWritingPatternLifecycleRequest,
    WritingPatternConflict,
    WritingPatternConflictDecisionInput,
    WritingPatternLifecycleState,
    WritingPatternProfilePreview,
    WritingPatternProfileSummary,
    WritingPatternProfileVersion,
    WritingPatternRecipePage,
    WritingPatternRecipePreview,
    WritingPatternRecipeSeries,
    WritingPatternRecipeSummary,
    WritingPatternRecipeVersion,
    WritingPatternRecipeVersionSummary,
    WritingPatternSafetyBasis,
)


class WritingPatternError(ValueError):
    pass


class WritingPatternNotFoundError(WritingPatternError):
    pass


def _json_text(value: object) -> str:
    return canonical_json(value).decode("utf-8")


class WritingPatternRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_recipe_version(self, version_id: str) -> WritingPatternRecipeVersion:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM writing_pattern_recipe_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
            if row is None:
                raise WritingPatternNotFoundError("recipe_version_not_found")
            sources = self._source_rows(connection, version_id)
        return self._recipe_version(row, sources)

    def get_recipe_series(self, recipe_id: str) -> WritingPatternRecipeSeries:
        with self.database.connect() as connection:
            recipe = connection.execute(
                "SELECT * FROM writing_pattern_recipes WHERE id = ?",
                (recipe_id,),
            ).fetchone()
            if recipe is None:
                raise WritingPatternNotFoundError("recipe_not_found")
            version_rows = connection.execute(
                """
                SELECT * FROM writing_pattern_recipe_versions
                WHERE recipe_id = ? ORDER BY version DESC
                """,
                (recipe_id,),
            ).fetchall()
        return WritingPatternRecipeSeries(
            id=str(recipe["id"]),
            lifecycle_state=WritingPatternLifecycleState(str(recipe["lifecycle_state"])),
            lifecycle_revision=int(recipe["lifecycle_revision"]),
            versions=[self._recipe_version_summary(row) for row in version_rows],
            created_at=str(recipe["created_at"]),
            updated_at=str(recipe["updated_at"]),
        )

    def list_recipe_summaries(
        self,
        *,
        lifecycle_state: WritingPatternLifecycleState | None,
        limit: int,
        offset: int,
    ) -> WritingPatternRecipePage:
        filters: list[str] = []
        parameters: list[object] = []
        if lifecycle_state is not None:
            filters.append("r.lifecycle_state = ?")
            parameters.append(lifecycle_state.value)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.database.connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM writing_pattern_recipes r {where}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT r.id, r.lifecycle_state, r.lifecycle_revision,
                       r.created_at, r.updated_at,
                       v.id AS version_id, v.version, v.name, v.description,
                       v.source_asset_count, v.source_work_count, v.safety_basis,
                       v.source_snapshot_sha256, v.content_sha256,
                       v.created_at AS version_created_at
                FROM writing_pattern_recipes r
                JOIN writing_pattern_recipe_versions v
                  ON v.recipe_id = r.id
                 AND v.version = (
                    SELECT MAX(v2.version) FROM writing_pattern_recipe_versions v2
                    WHERE v2.recipe_id = r.id
                 )
                {where}
                ORDER BY r.updated_at DESC, r.id
                LIMIT ? OFFSET ?
                """,
                (*parameters, limit, offset),
            ).fetchall()
        return WritingPatternRecipePage(
            items=[self._recipe_summary(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    def latest_recipe_version_number(self, recipe_id: str) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT r.lifecycle_state, MAX(v.version) AS latest_version
                FROM writing_pattern_recipes r
                LEFT JOIN writing_pattern_recipe_versions v ON v.recipe_id = r.id
                WHERE r.id = ? GROUP BY r.id
                """,
                (recipe_id,),
            ).fetchone()
        if row is None or row["latest_version"] is None:
            raise WritingPatternNotFoundError("recipe_not_found")
        if row["lifecycle_state"] != WritingPatternLifecycleState.ACTIVE.value:
            raise WritingPatternError("recipe_archived")
        return int(row["latest_version"])

    def verify_recipe_sources(
        self,
        project_id: str,
        sources: list[RecipeSourceSnapshot],
        *,
        require_project_link: bool,
    ) -> WritingPatternSafetyBasis:
        with self.database.connect() as connection:
            self._assert_source_dependencies(
                connection,
                project_id,
                sources,
                require_project_link=require_project_link,
            )
            return self._current_safety_basis(connection, sources)

    def persist_recipe_version(
        self,
        project_id: str,
        preview: WritingPatternRecipePreview,
        *,
        recipe_id: str | None,
        expected_latest_version: int | None,
    ) -> WritingPatternRecipeVersion:
        if preview.unresolved_conflict_count:
            raise WritingPatternError("unresolved_recipe_conflict")
        timestamp = now_iso()
        version_id = str(uuid4())
        with self.database.connect() as connection:
            # Serialize the compare-and-swap checks with the immutable insert.
            # This turns concurrent create/version requests into a stable
            # idempotent result or a domain conflict instead of a UNIQUE error.
            connection.execute("BEGIN IMMEDIATE")
            self._assert_current_topic(
                connection,
                project_id,
                preview.expected_topic_revision,
            )
            self._assert_source_dependencies(
                connection,
                project_id,
                preview.sources,
                require_project_link=True,
            )
            if self._current_safety_basis(connection, preview.sources) != preview.safety_basis:
                raise WritingPatternError("preview_changed")
            if recipe_id is None:
                if expected_latest_version is not None:
                    raise WritingPatternError("invalid_recipe_version_request")
                recipe_id = str(uuid4())
                version = 1
                connection.execute(
                    """
                    INSERT INTO writing_pattern_recipes (
                        id, created_from_project_id, lifecycle_state,
                        lifecycle_revision, created_at, updated_at
                    ) VALUES (?, ?, 'active', 0, ?, ?)
                    """,
                    (recipe_id, project_id, timestamp, timestamp),
                )
            else:
                recipe = connection.execute(
                    "SELECT lifecycle_state FROM writing_pattern_recipes WHERE id = ?",
                    (recipe_id,),
                ).fetchone()
                if recipe is None:
                    raise WritingPatternNotFoundError("recipe_not_found")
                if recipe["lifecycle_state"] != WritingPatternLifecycleState.ACTIVE.value:
                    raise WritingPatternError("recipe_archived")
                latest = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(version), 0)
                        FROM writing_pattern_recipe_versions WHERE recipe_id = ?
                        """,
                        (recipe_id,),
                    ).fetchone()[0]
                )
                if expected_latest_version is None or latest != expected_latest_version:
                    raise WritingPatternError("recipe_version_changed")
                if connection.execute(
                    """
                    SELECT 1 FROM writing_pattern_recipe_versions
                    WHERE recipe_id = ? AND content_sha256 = ?
                    """,
                    (recipe_id, preview.recipe_content_sha256),
                ).fetchone() is not None:
                    raise WritingPatternError("duplicate_recipe_version")
                version = latest + 1
            connection.execute(
                """
                INSERT INTO writing_pattern_recipe_versions (
                    id, recipe_id, version, name, description,
                    conflict_decisions_json, conflicts_json,
                    source_asset_count, source_work_count, safety_basis,
                    source_snapshot_sha256, content_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    recipe_id,
                    version,
                    preview.name,
                    preview.description,
                    _json_text(
                        [item.model_dump(mode="json") for item in preview.decisions]
                    ),
                    _json_text(
                        [item.model_dump(mode="json") for item in preview.conflicts]
                    ),
                    preview.source_asset_count,
                    preview.source_work_count,
                    preview.safety_basis.value,
                    preview.source_snapshot_sha256,
                    preview.recipe_content_sha256,
                    timestamp,
                ),
            )
            connection.executemany(
                """
                INSERT INTO writing_pattern_recipe_sources (
                    id, recipe_version_id, ordinal, entry_key,
                    asset_version_id, asset_series_id, asset_version,
                    asset_content_sha256, asset_type, dimension, pattern_name,
                    transferable_rule, adaptation_risk, purpose, strategy, weight,
                    applicable_stages_json, chapter_start, chapter_end, note,
                    source_work_fingerprints_json, source_snapshot_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(uuid4()),
                        version_id,
                        ordinal,
                        source.entry_key,
                        source.asset_version_id,
                        source.asset_series_id,
                        source.asset_version,
                        source.asset_content_sha256,
                        source.asset_type.value,
                        source.dimension.value,
                        source.pattern_name,
                        source.transferable_rule,
                        source.adaptation_risk,
                        source.purpose.value,
                        source.strategy.value,
                        source.weight,
                        _json_text([stage.value for stage in source.applicable_stages]),
                        source.chapter_start,
                        source.chapter_end,
                        source.note,
                        _json_text(
                            [
                                fingerprint.model_dump(mode="json")
                                for fingerprint in source.source_work_fingerprints
                            ]
                        ),
                        source.source_snapshot_sha256,
                    )
                    for ordinal, source in enumerate(preview.sources)
                ],
            )
            connection.execute(
                "UPDATE writing_pattern_recipes SET updated_at = ? WHERE id = ?",
                (timestamp, recipe_id),
            )
        return self.get_recipe_version(version_id)

    def update_recipe_lifecycle(
        self,
        recipe_id: str,
        request: UpdateWritingPatternLifecycleRequest,
    ) -> WritingPatternRecipeSeries:
        current = self.get_recipe_series(recipe_id)
        if current.lifecycle_revision != request.expected_lifecycle_revision:
            raise WritingPatternError("stale_lifecycle_revision")
        if current.lifecycle_state == request.state:
            return current
        timestamp = now_iso()
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE writing_pattern_recipes
                SET lifecycle_state = ?, lifecycle_revision = lifecycle_revision + 1,
                    updated_at = ?
                WHERE id = ? AND lifecycle_revision = ?
                """,
                (
                    request.state.value,
                    timestamp,
                    recipe_id,
                    request.expected_lifecycle_revision,
                ),
            )
            if result.rowcount != 1:
                raise WritingPatternError("stale_lifecycle_revision")
        return self.get_recipe_series(recipe_id)

    def persist_profile(
        self,
        project_id: str,
        preview: WritingPatternProfilePreview,
    ) -> tuple[WritingPatternProfileVersion, bool]:
        timestamp = now_iso()
        profile_version_id = str(uuid4())
        link_id = str(uuid4())
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            version_row = connection.execute(
                """
                SELECT v.content_sha256, v.recipe_id, r.lifecycle_state
                FROM writing_pattern_recipe_versions v
                JOIN writing_pattern_recipes r ON r.id = v.recipe_id
                WHERE v.id = ?
                """,
                (preview.recipe_version_id,),
            ).fetchone()
            if version_row is None:
                raise WritingPatternNotFoundError("recipe_version_not_found")
            if version_row["lifecycle_state"] != WritingPatternLifecycleState.ACTIVE.value:
                raise WritingPatternError("recipe_archived")
            if version_row["content_sha256"] != preview.recipe_content_sha256:
                raise WritingPatternError("recipe_version_changed")
            topic_row = self._assert_current_topic(
                connection,
                project_id,
                preview.topic_revision,
                expected_content_sha256=preview.topic_content_sha256,
            )
            if str(topic_row["version_id"]) != preview.topic_decision_version_id:
                raise WritingPatternError("topic_changed")
            sources = self._source_rows(connection, preview.recipe_version_id)
            self._assert_source_dependencies(
                connection,
                project_id,
                sources,
                require_project_link=False,
            )
            if self._current_safety_basis(connection, sources) != preview.safety_basis:
                raise WritingPatternError("preview_changed")
            existing = connection.execute(
                """
                SELECT p.id, l.lifecycle_state
                FROM writing_pattern_profile_versions p
                JOIN project_writing_pattern_profiles l ON l.profile_version_id = p.id
                WHERE p.project_id = ? AND p.profile_fingerprint_sha256 = ?
                """,
                (project_id, preview.profile_fingerprint_sha256),
            ).fetchone()
            if existing is not None:
                if existing["lifecycle_state"] == WritingPatternLifecycleState.ACTIVE.value:
                    existing_id = str(existing["id"])
                else:
                    raise WritingPatternError("profile_already_archived")
            else:
                active = connection.execute(
                    """
                    SELECT 1 FROM project_writing_pattern_profiles
                    WHERE project_id = ? AND lifecycle_state = 'active'
                    """,
                    (project_id,),
                ).fetchone()
                if active is not None:
                    raise WritingPatternError("active_profile_exists")
                connection.execute(
                    """
                    INSERT INTO writing_pattern_profile_versions (
                        id, project_id, recipe_version_id, recipe_content_sha256,
                        topic_decision_version_id, topic_revision, topic_content_sha256,
                        compiler_version, safety_basis, source_snapshot_sha256,
                        profile_json, conflicts_json, decisions_json,
                        excluded_entry_keys_json, profile_fingerprint_sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile_version_id,
                        project_id,
                        preview.recipe_version_id,
                        preview.recipe_content_sha256,
                        preview.topic_decision_version_id,
                        preview.topic_revision,
                        preview.topic_content_sha256,
                        WRITING_PATTERN_COMPILER_VERSION,
                        preview.safety_basis.value,
                        preview.source_snapshot_sha256,
                        _json_text(preview.model_safe_profile.model_dump(mode="json")),
                        _json_text(
                            [item.model_dump(mode="json") for item in preview.conflicts]
                        ),
                        _json_text(
                            [item.model_dump(mode="json") for item in preview.decisions]
                        ),
                        _json_text(preview.excluded_entry_keys),
                        preview.profile_fingerprint_sha256,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO project_writing_pattern_profiles (
                        id, project_id, profile_version_id, lifecycle_state,
                        lifecycle_revision, created_at, updated_at
                    ) VALUES (?, ?, ?, 'active', 0, ?, ?)
                    """,
                    (link_id, project_id, profile_version_id, timestamp, timestamp),
                )
                existing_id = profile_version_id
        return self.get_profile(project_id, existing_id), existing is None

    def get_active_profile(self, project_id: str) -> WritingPatternProfileVersion:
        with self.database.connect() as connection:
            row = self._profile_row(
                connection,
                project_id,
                profile_version_id=None,
                active_only=True,
            )
        if row is None:
            raise WritingPatternNotFoundError("active_profile_not_found")
        return self._profile(row)

    def get_profile(
        self,
        project_id: str,
        profile_version_id: str,
    ) -> WritingPatternProfileVersion:
        with self.database.connect() as connection:
            row = self._profile_row(
                connection,
                project_id,
                profile_version_id=profile_version_id,
                active_only=False,
            )
        if row is None:
            raise WritingPatternNotFoundError("profile_not_found")
        return self._profile(row)

    def list_profiles(self, project_id: str) -> list[WritingPatternProfileSummary]:
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
                raise WritingPatternNotFoundError("project_not_found")
            rows = connection.execute(
                """
                SELECT p.id, p.project_id, p.recipe_version_id,
                       p.recipe_content_sha256, p.topic_revision,
                       p.topic_content_sha256, p.safety_basis,
                       p.profile_fingerprint_sha256, p.created_at,
                       l.lifecycle_state, l.lifecycle_revision,
                       l.updated_at AS link_updated_at,
                       d.revision AS current_topic_revision,
                       d.confirmed_revision AS current_confirmed_revision,
                       rv.content_sha256 AS current_recipe_content_sha256
                FROM writing_pattern_profile_versions p
                JOIN project_writing_pattern_profiles l ON l.profile_version_id = p.id
                LEFT JOIN topic_decisions d ON d.project_id = p.project_id
                JOIN writing_pattern_recipe_versions rv ON rv.id = p.recipe_version_id
                WHERE p.project_id = ?
                ORDER BY l.updated_at DESC, p.id
                """,
                (project_id,),
            ).fetchall()
        return [self._profile_summary(row) for row in rows]

    def update_profile_lifecycle(
        self,
        project_id: str,
        profile_version_id: str,
        request: UpdateWritingPatternLifecycleRequest,
    ) -> WritingPatternProfileVersion:
        current = self.get_profile(project_id, profile_version_id)
        if current.lifecycle_revision != request.expected_lifecycle_revision:
            raise WritingPatternError("stale_lifecycle_revision")
        if current.lifecycle_state == request.state:
            return current
        timestamp = now_iso()
        with self.database.connect() as connection:
            if request.state == WritingPatternLifecycleState.ACTIVE:
                try:
                    self._assert_current_topic(
                        connection,
                        project_id,
                        current.topic_revision,
                        expected_content_sha256=current.topic_content_sha256,
                    )
                except WritingPatternError as error:
                    if str(error) == "topic_changed":
                        raise WritingPatternError("profile_stale") from error
                    raise
                other = connection.execute(
                    """
                    SELECT 1 FROM project_writing_pattern_profiles
                    WHERE project_id = ? AND lifecycle_state = 'active'
                      AND profile_version_id != ?
                    """,
                    (project_id, profile_version_id),
                ).fetchone()
                if other is not None:
                    raise WritingPatternError("active_profile_exists")
            try:
                result = connection.execute(
                    """
                    UPDATE project_writing_pattern_profiles
                    SET lifecycle_state = ?, lifecycle_revision = lifecycle_revision + 1,
                        updated_at = ?
                    WHERE project_id = ? AND profile_version_id = ?
                      AND lifecycle_revision = ?
                    """,
                    (
                        request.state.value,
                        timestamp,
                        project_id,
                        profile_version_id,
                        request.expected_lifecycle_revision,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise WritingPatternError("active_profile_exists") from error
            if result.rowcount != 1:
                raise WritingPatternError("stale_lifecycle_revision")
        return self.get_profile(project_id, profile_version_id)

    @staticmethod
    def _source_rows(
        connection: Connection,
        recipe_version_id: str,
    ) -> list[RecipeSourceSnapshot]:
        rows = connection.execute(
            """
            SELECT * FROM writing_pattern_recipe_sources
            WHERE recipe_version_id = ? ORDER BY ordinal
            """,
            (recipe_version_id,),
        ).fetchall()
        return [WritingPatternRepository._source(row) for row in rows]

    @staticmethod
    def _source(row: Row) -> RecipeSourceSnapshot:
        return RecipeSourceSnapshot.model_validate(
            {
                "entry_key": row["entry_key"],
                "asset_version_id": row["asset_version_id"],
                "asset_series_id": row["asset_series_id"],
                "asset_version": row["asset_version"],
                "asset_content_sha256": row["asset_content_sha256"],
                "asset_type": row["asset_type"],
                "dimension": row["dimension"],
                "pattern_name": row["pattern_name"],
                "transferable_rule": row["transferable_rule"],
                "adaptation_risk": row["adaptation_risk"],
                "purpose": row["purpose"],
                "strategy": row["strategy"],
                "weight": row["weight"],
                "applicable_stages": json.loads(str(row["applicable_stages_json"])),
                "chapter_start": row["chapter_start"],
                "chapter_end": row["chapter_end"],
                "note": row["note"],
                "source_work_fingerprints": json.loads(
                    str(row["source_work_fingerprints_json"])
                ),
                "source_snapshot_sha256": row["source_snapshot_sha256"],
            }
        )

    @staticmethod
    def _recipe_version_summary(row: Row) -> WritingPatternRecipeVersionSummary:
        return WritingPatternRecipeVersionSummary(
            id=str(row["id"]),
            recipe_id=str(row["recipe_id"]),
            version=int(row["version"]),
            name=str(row["name"]),
            description=str(row["description"]),
            source_asset_count=int(row["source_asset_count"]),
            source_work_count=int(row["source_work_count"]),
            safety_basis=WritingPatternSafetyBasis(str(row["safety_basis"])),
            source_snapshot_sha256=str(row["source_snapshot_sha256"]),
            content_sha256=str(row["content_sha256"]),
            created_at=str(row["created_at"]),
        )

    @classmethod
    def _recipe_version(
        cls,
        row: Row,
        sources: list[RecipeSourceSnapshot],
    ) -> WritingPatternRecipeVersion:
        conflicts = [
            WritingPatternConflict.model_validate(item)
            for item in json.loads(str(row["conflicts_json"]))
        ]
        decisions = [
            WritingPatternConflictDecisionInput.model_validate(item)
            for item in json.loads(str(row["conflict_decisions_json"]))
        ]
        expected_source_hash = recipe_source_snapshot_sha256(sources)
        expected_content_hash = recipe_content_sha256(
            name=str(row["name"]),
            description=str(row["description"]),
            sources=sources,
            conflicts=conflicts,
            decisions=decisions,
        )
        if (
            expected_source_hash != row["source_snapshot_sha256"]
            or expected_content_hash != row["content_sha256"]
        ):
            raise WritingPatternError("recipe_content_hash_mismatch")
        return WritingPatternRecipeVersion(
            **cls._recipe_version_summary(row).model_dump(mode="python"),
            sources=sources,
            conflicts=conflicts,
            conflict_decisions=decisions,
        )

    @classmethod
    def _recipe_summary(cls, row: Row) -> WritingPatternRecipeSummary:
        version = WritingPatternRecipeVersionSummary(
            id=str(row["version_id"]),
            recipe_id=str(row["id"]),
            version=int(row["version"]),
            name=str(row["name"]),
            description=str(row["description"]),
            source_asset_count=int(row["source_asset_count"]),
            source_work_count=int(row["source_work_count"]),
            safety_basis=WritingPatternSafetyBasis(str(row["safety_basis"])),
            source_snapshot_sha256=str(row["source_snapshot_sha256"]),
            content_sha256=str(row["content_sha256"]),
            created_at=str(row["version_created_at"]),
        )
        return WritingPatternRecipeSummary(
            id=str(row["id"]),
            lifecycle_state=WritingPatternLifecycleState(str(row["lifecycle_state"])),
            lifecycle_revision=int(row["lifecycle_revision"]),
            latest_version=version,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _assert_current_topic(
        connection: Connection,
        project_id: str,
        expected_revision: int,
        *,
        expected_content_sha256: str | None = None,
    ) -> Row:
        row = connection.execute(
            """
            SELECT d.revision, d.confirmed_revision,
                   v.id AS version_id, v.content_sha256
            FROM topic_decisions d
            LEFT JOIN topic_decision_versions v
              ON v.topic_decision_id = d.id AND v.revision = d.confirmed_revision
            WHERE d.project_id = ?
            """,
            (project_id,),
        ).fetchone()
        if (
            row is None
            or row["confirmed_revision"] is None
            or int(row["revision"]) != int(row["confirmed_revision"])
            or int(row["revision"]) != expected_revision
            or row["version_id"] is None
        ):
            raise WritingPatternError("topic_changed")
        if (
            expected_content_sha256 is not None
            and row["content_sha256"] != expected_content_sha256
        ):
            raise WritingPatternError("topic_changed")
        return cast(Row, row)

    @staticmethod
    def _assert_source_dependencies(
        connection: Connection,
        project_id: str,
        sources: list[RecipeSourceSnapshot],
        *,
        require_project_link: bool,
    ) -> None:
        seen_series: dict[str, str] = {}
        for source in sources:
            row = connection.execute(
                """
                SELECT a.series_id, a.version, a.content_sha256,
                       p.lifecycle_state AS project_lifecycle
                FROM craft_pattern_assets a
                LEFT JOIN project_craft_pattern_assets p
                  ON p.asset_version_id = a.id AND p.project_id = ?
                WHERE a.id = ?
                """,
                (project_id, source.asset_version_id),
            ).fetchone()
            if row is None:
                raise WritingPatternNotFoundError("source_asset_not_found")
            if require_project_link and row["project_lifecycle"] != "active":
                raise WritingPatternNotFoundError("source_asset_not_found")
            if (
                row["series_id"] != source.asset_series_id
                or int(row["version"]) != source.asset_version
                or row["content_sha256"] != source.asset_content_sha256
            ):
                raise WritingPatternError("asset_hash_mismatch")
            selected_asset = seen_series.setdefault(
                source.asset_series_id,
                source.asset_version_id,
            )
            if selected_asset != source.asset_version_id:
                raise WritingPatternError("multiple_asset_versions_in_family")

    @staticmethod
    def _current_safety_basis(
        connection: Connection,
        sources: list[RecipeSourceSnapshot],
    ) -> WritingPatternSafetyBasis:
        fingerprints = {
            (item.basis, item.identity_sha256)
            for source in sources
            for item in source.source_work_fingerprints
        }
        if any(basis == "abstract_lineage" for basis, _identity in fingerprints):
            return WritingPatternSafetyBasis.ABSTRACT_ONLY
        content_hashes = {identity for _basis, identity in fingerprints}
        if not content_hashes:
            return WritingPatternSafetyBasis.ABSTRACT_ONLY
        placeholders = ",".join("?" for _ in content_hashes)
        available = {
            str(row[0])
            for row in connection.execute(
                f"""
                SELECT DISTINCT content_sha256 FROM reference_works
                WHERE content_sha256 IN ({placeholders})
                """,
                sorted(content_hashes),
            ).fetchall()
        }
        return (
            WritingPatternSafetyBasis.SOURCE_VERIFIED
            if available == content_hashes
            else WritingPatternSafetyBasis.ABSTRACT_ONLY
        )

    @staticmethod
    def _profile_row(
        connection: Connection,
        project_id: str,
        *,
        profile_version_id: str | None,
        active_only: bool,
    ) -> Row | None:
        filters = ["p.project_id = ?"]
        parameters: list[object] = [project_id]
        if profile_version_id is not None:
            filters.append("p.id = ?")
            parameters.append(profile_version_id)
        if active_only:
            filters.append("l.lifecycle_state = 'active'")
        return cast(
            Row | None,
            connection.execute(
            f"""
            SELECT p.*, l.lifecycle_state, l.lifecycle_revision,
                   l.updated_at AS link_updated_at,
                   d.revision AS current_topic_revision,
                   d.confirmed_revision AS current_confirmed_revision,
                   rv.content_sha256 AS current_recipe_content_sha256
            FROM writing_pattern_profile_versions p
            JOIN project_writing_pattern_profiles l ON l.profile_version_id = p.id
            LEFT JOIN topic_decisions d ON d.project_id = p.project_id
            JOIN writing_pattern_recipe_versions rv ON rv.id = p.recipe_version_id
            WHERE {' AND '.join(filters)}
            ORDER BY l.updated_at DESC LIMIT 1
            """,
            parameters,
            ).fetchone(),
        )

    @classmethod
    def _profile_summary(cls, row: Row) -> WritingPatternProfileSummary:
        return WritingPatternProfileSummary(
            id=str(row["id"]),
            project_id=str(row["project_id"]),
            recipe_version_id=str(row["recipe_version_id"]),
            recipe_content_sha256=str(row["recipe_content_sha256"]),
            topic_revision=int(row["topic_revision"]),
            topic_content_sha256=str(row["topic_content_sha256"]),
            safety_basis=WritingPatternSafetyBasis(str(row["safety_basis"])),
            profile_fingerprint_sha256=str(row["profile_fingerprint_sha256"]),
            lifecycle_state=WritingPatternLifecycleState(str(row["lifecycle_state"])),
            lifecycle_revision=int(row["lifecycle_revision"]),
            is_current=(
                row["current_confirmed_revision"] is not None
                and int(row["current_topic_revision"])
                == int(row["current_confirmed_revision"])
                == int(row["topic_revision"])
                and row["current_recipe_content_sha256"]
                == row["recipe_content_sha256"]
            ),
            created_at=str(row["created_at"]),
            updated_at=str(row["link_updated_at"]),
        )

    @classmethod
    def _profile(cls, row: Row) -> WritingPatternProfileVersion:
        profile = ModelSafeWritingPatternProfile.model_validate(
            json.loads(str(row["profile_json"]))
        )
        if canonical_sha256(profile.model_dump(mode="json")) != row[
            "profile_fingerprint_sha256"
        ]:
            raise WritingPatternError("profile_content_hash_mismatch")
        if (
            profile.compiler_version != row["compiler_version"]
            or profile.recipe_content_sha256 != row["recipe_content_sha256"]
            or profile.topic_content_sha256 != row["topic_content_sha256"]
            or profile.topic_revision != row["topic_revision"]
            or row["current_recipe_content_sha256"] != row["recipe_content_sha256"]
        ):
            raise WritingPatternError("profile_content_hash_mismatch")
        return WritingPatternProfileVersion(
            **cls._profile_summary(row).model_dump(mode="python"),
            topic_decision_version_id=str(row["topic_decision_version_id"]),
            compiler_version=str(row["compiler_version"]),
            source_snapshot_sha256=str(row["source_snapshot_sha256"]),
            model_safe_profile=profile,
            conflicts=[
                WritingPatternConflict.model_validate(item)
                for item in json.loads(str(row["conflicts_json"]))
            ],
            decisions=[
                AppliedWritingPatternConflictDecision.model_validate(item)
                for item in json.loads(str(row["decisions_json"]))
            ],
            excluded_entry_keys=[
                str(item) for item in json.loads(str(row["excluded_entry_keys_json"]))
            ],
        )
