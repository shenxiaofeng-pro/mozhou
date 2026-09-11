from __future__ import annotations

import unicodedata

from app.craft_patterns import CraftPatternRepository, InvalidCraftPatternError
from app.database import Database
from app.models import (
    CraftPatternAsset,
    CraftPatternItem,
    CraftPatternLifecycleState,
    TopicDecisionVersion,
)
from app.repository import NotFoundError
from app.topic_decisions import (
    TopicDecisionNotConfirmedError,
    TopicDecisionNotFoundError,
    TopicDecisionService,
)
from app.writing_patterns.compiler import (
    InvalidConflictDecisionError,
    canonical_sha256,
    compile_writing_pattern_profile,
    detect_recipe_conflicts,
    recipe_content_sha256,
    recipe_source_snapshot_sha256,
)
from app.writing_patterns.models import (
    CreateWritingPatternRecipeRequest,
    CreateWritingPatternRecipeVersionRequest,
    PreviewWritingPatternRecipeRequest,
    PreviewWritingPatternRecipeVersionRequest,
    PreviewWritingPatternReuseRequest,
    RecipeSourceSnapshot,
    ReuseWritingPatternRecipeRequest,
    UpdateWritingPatternLifecycleRequest,
    WritingPatternConflictResolution,
    WritingPatternLifecycleState,
    WritingPatternProfilePreview,
    WritingPatternProfileSummary,
    WritingPatternProfileVersion,
    WritingPatternRecipeEntryInput,
    WritingPatternRecipePage,
    WritingPatternRecipePreview,
    WritingPatternRecipeSeries,
    WritingPatternRecipeVersion,
    WritingPatternWorkFingerprint,
)
from app.writing_patterns.repository import (
    WritingPatternError,
    WritingPatternNotFoundError,
    WritingPatternRepository,
)


class WritingPatternService:
    def __init__(
        self,
        database: Database,
        topic_decisions: TopicDecisionService,
    ) -> None:
        self.database = database
        self.topic_decisions = topic_decisions
        self.craft_assets = CraftPatternRepository(database)
        self.repository = WritingPatternRepository(database)

    def preview_recipe(
        self,
        project_id: str,
        request: PreviewWritingPatternRecipeRequest,
    ) -> WritingPatternRecipePreview:
        return self._preview_recipe(project_id, request, expected_latest_version=None)

    def create_recipe(
        self,
        project_id: str,
        request: CreateWritingPatternRecipeRequest,
    ) -> WritingPatternRecipeVersion:
        preview = self.preview_recipe(
            project_id,
            PreviewWritingPatternRecipeRequest.model_validate(
                request.model_dump(exclude={"expected_preview_sha256"})
            ),
        )
        if preview.preview_sha256 != request.expected_preview_sha256:
            raise WritingPatternError("preview_changed")
        return self.repository.persist_recipe_version(
            project_id,
            preview,
            recipe_id=None,
            expected_latest_version=None,
        )

    def preview_recipe_version(
        self,
        project_id: str,
        recipe_id: str,
        request: PreviewWritingPatternRecipeVersionRequest,
    ) -> WritingPatternRecipePreview:
        latest = self.repository.latest_recipe_version_number(recipe_id)
        if latest != request.expected_latest_version:
            raise WritingPatternError("recipe_version_changed")
        base = PreviewWritingPatternRecipeRequest.model_validate(
            request.model_dump(exclude={"expected_latest_version"})
        )
        return self._preview_recipe(
            project_id,
            base,
            expected_latest_version=request.expected_latest_version,
            recipe_id=recipe_id,
        )

    def create_recipe_version(
        self,
        project_id: str,
        recipe_id: str,
        request: CreateWritingPatternRecipeVersionRequest,
    ) -> WritingPatternRecipeVersion:
        preview = self.preview_recipe_version(
            project_id,
            recipe_id,
            PreviewWritingPatternRecipeVersionRequest.model_validate(
                request.model_dump(exclude={"expected_preview_sha256"})
            ),
        )
        if preview.preview_sha256 != request.expected_preview_sha256:
            raise WritingPatternError("preview_changed")
        return self.repository.persist_recipe_version(
            project_id,
            preview,
            recipe_id=recipe_id,
            expected_latest_version=request.expected_latest_version,
        )

    def preview_reuse(
        self,
        project_id: str,
        recipe_version_id: str,
        request: PreviewWritingPatternReuseRequest,
    ) -> WritingPatternProfilePreview:
        version = self.repository.get_recipe_version(recipe_version_id)
        series = self.repository.get_recipe_series(version.recipe_id)
        if series.lifecycle_state != WritingPatternLifecycleState.ACTIVE:
            raise WritingPatternError("recipe_archived")
        if version.content_sha256 != request.expected_recipe_content_sha256:
            raise WritingPatternError("recipe_version_changed")
        topic = self._confirmed_topic(project_id, request.expected_topic_revision)
        safety_basis = self.repository.verify_recipe_sources(
            project_id,
            version.sources,
            require_project_link=False,
        )
        try:
            compiled = compile_writing_pattern_profile(
                version.sources,
                decisions=version.conflict_decisions,
                topic_revision=topic.revision,
                topic_content_sha256=topic.content_sha256,
                recipe_content_sha256=version.content_sha256,
                safety_basis=safety_basis,
            )
        except InvalidConflictDecisionError as error:
            raise WritingPatternError(str(error)) from error
        preview_payload = {
            "operation": "reuse",
            "project_id": project_id,
            "recipe_version_id": version.id,
            "recipe_content_sha256": version.content_sha256,
            "topic_decision_version_id": topic.id,
            "topic_revision": topic.revision,
            "topic_content_sha256": topic.content_sha256,
            "safety_basis": safety_basis.value,
            "source_snapshot_sha256": version.source_snapshot_sha256,
            "profile_fingerprint_sha256": compiled.profile_fingerprint_sha256,
        }
        return WritingPatternProfilePreview(
            recipe_version_id=version.id,
            recipe_content_sha256=version.content_sha256,
            topic_decision_version_id=topic.id,
            topic_revision=topic.revision,
            topic_content_sha256=topic.content_sha256,
            safety_basis=safety_basis,
            model_safe_profile=compiled.model_safe_profile,
            conflicts=compiled.conflicts,
            decisions=compiled.decisions,
            excluded_entry_keys=compiled.excluded_entry_keys,
            source_snapshot_sha256=version.source_snapshot_sha256,
            profile_fingerprint_sha256=compiled.profile_fingerprint_sha256,
            preview_sha256=canonical_sha256(preview_payload),
        )

    def reuse_recipe(
        self,
        project_id: str,
        recipe_version_id: str,
        request: ReuseWritingPatternRecipeRequest,
    ) -> tuple[WritingPatternProfileVersion, bool]:
        preview = self.preview_reuse(
            project_id,
            recipe_version_id,
            PreviewWritingPatternReuseRequest.model_validate(
                request.model_dump(exclude={"expected_preview_sha256"})
            ),
        )
        if preview.preview_sha256 != request.expected_preview_sha256:
            raise WritingPatternError("preview_changed")
        return self.repository.persist_profile(project_id, preview)

    def list_recipes(
        self,
        *,
        lifecycle_state: WritingPatternLifecycleState | None,
        limit: int,
        offset: int,
    ) -> WritingPatternRecipePage:
        return self.repository.list_recipe_summaries(
            lifecycle_state=lifecycle_state,
            limit=limit,
            offset=offset,
        )

    def get_recipe_series(self, recipe_id: str) -> WritingPatternRecipeSeries:
        return self.repository.get_recipe_series(recipe_id)

    def get_recipe_version(self, version_id: str) -> WritingPatternRecipeVersion:
        return self.repository.get_recipe_version(version_id)

    def update_recipe_lifecycle(
        self,
        recipe_id: str,
        request: UpdateWritingPatternLifecycleRequest,
    ) -> WritingPatternRecipeSeries:
        return self.repository.update_recipe_lifecycle(recipe_id, request)

    def list_profiles(self, project_id: str) -> list[WritingPatternProfileSummary]:
        return self.repository.list_profiles(project_id)

    def get_active_profile(self, project_id: str) -> WritingPatternProfileVersion:
        return self.repository.get_active_profile(project_id)

    def get_profile(
        self,
        project_id: str,
        profile_version_id: str,
    ) -> WritingPatternProfileVersion:
        return self.repository.get_profile(project_id, profile_version_id)

    def update_profile_lifecycle(
        self,
        project_id: str,
        profile_version_id: str,
        request: UpdateWritingPatternLifecycleRequest,
    ) -> WritingPatternProfileVersion:
        return self.repository.update_profile_lifecycle(
            project_id,
            profile_version_id,
            request,
        )

    def _preview_recipe(
        self,
        project_id: str,
        request: PreviewWritingPatternRecipeRequest,
        *,
        expected_latest_version: int | None,
        recipe_id: str | None = None,
    ) -> WritingPatternRecipePreview:
        topic = self._confirmed_topic(project_id, request.expected_topic_revision)
        sources = self._resolve_sources(project_id, request.entries)
        try:
            conflicts = detect_recipe_conflicts(sources)
        except InvalidConflictDecisionError as error:
            raise WritingPatternError(str(error)) from error
        decisions = sorted(
            request.conflict_decisions,
            key=lambda decision: decision.conflict_key,
        )
        conflict_by_key = {conflict.conflict_key: conflict for conflict in conflicts}
        for decision in decisions:
            conflict = conflict_by_key.get(decision.conflict_key)
            if conflict is None:
                raise WritingPatternError("unknown_conflict_decision")
            if (
                decision.resolution == WritingPatternConflictResolution.CHOOSE_SOURCE
                and decision.chosen_entry_key not in conflict.entry_keys
            ):
                raise WritingPatternError("chosen_entry_not_in_conflict")
        unresolved = len(set(conflict_by_key) - {item.conflict_key for item in decisions})
        work_keys = {
            fingerprint.identity_sha256
            for source in sources
            for fingerprint in source.source_work_fingerprints
        }
        if not 1 <= len(work_keys) <= 5:
            raise WritingPatternError("one_to_five_works_required")
        source_hash = recipe_source_snapshot_sha256(sources)
        content_hash = recipe_content_sha256(
            name=request.name,
            description=request.description,
            sources=sources,
            conflicts=conflicts,
            decisions=decisions,
        )
        safety_basis = self.repository.verify_recipe_sources(
            project_id,
            sources,
            require_project_link=True,
        )
        preview_payload = {
            "operation": "create" if recipe_id is None else "new_version",
            "project_id": project_id,
            "recipe_id": recipe_id,
            "expected_latest_version": expected_latest_version,
            "topic_revision": topic.revision,
            "topic_content_sha256": topic.content_sha256,
            "source_snapshot_sha256": source_hash,
            "recipe_content_sha256": content_hash,
            "safety_basis": safety_basis.value,
        }
        return WritingPatternRecipePreview(
            name=request.name,
            description=request.description,
            expected_topic_revision=topic.revision,
            expected_latest_version=expected_latest_version,
            sources=sources,
            conflicts=conflicts,
            decisions=decisions,
            unresolved_conflict_count=unresolved,
            source_asset_count=len({source.asset_version_id for source in sources}),
            source_work_count=len(work_keys),
            safety_basis=safety_basis,
            source_snapshot_sha256=source_hash,
            recipe_content_sha256=content_hash,
            preview_sha256=canonical_sha256(preview_payload),
        )

    def _resolve_sources(
        self,
        project_id: str,
        entries: list[WritingPatternRecipeEntryInput],
    ) -> list[RecipeSourceSnapshot]:
        resolved: list[RecipeSourceSnapshot] = []
        family_versions: dict[str, str] = {}
        for entry in entries:
            try:
                asset = self.craft_assets.get_asset(
                    entry.asset_version_id,
                    for_project_id=project_id,
                )
            except (InvalidCraftPatternError, NotFoundError) as error:
                raise WritingPatternNotFoundError("source_asset_not_found") from error
            if asset.lifecycle_state != CraftPatternLifecycleState.ACTIVE:
                raise WritingPatternError("source_asset_not_active")
            if asset.content_sha256 != entry.asset_content_sha256:
                raise WritingPatternError("asset_hash_mismatch")
            selected_asset = family_versions.setdefault(asset.series_id, asset.id)
            if selected_asset != asset.id:
                raise WritingPatternError("multiple_asset_versions_in_family")
            matches = [
                item
                for item in asset.craft_items
                if item.dimension == entry.dimension and item.name == entry.pattern_name
            ]
            if len(matches) != 1:
                raise WritingPatternError("pattern_item_not_found")
            item = matches[0]
            self._assert_no_source_title_leak(item)
            selected_work_ids = sorted({evidence.work_id for evidence in item.evidence})
            work_fingerprints = self._work_fingerprints(asset, selected_work_ids)
            if len(work_fingerprints) > 5:
                raise WritingPatternError("one_to_five_works_required")
            normalized_stages = sorted(entry.applicable_stages, key=lambda stage: stage.value)
            entry_payload = {
                "asset_version_id": asset.id,
                "asset_series_id": asset.series_id,
                "asset_version": asset.version,
                "asset_content_sha256": asset.content_sha256,
                "dimension": entry.dimension.value,
                "pattern_name": item.name,
                "purpose": entry.purpose.value,
                "strategy": entry.strategy.value,
                "weight": entry.weight,
                "applicable_stages": [stage.value for stage in normalized_stages],
                "chapter_start": entry.chapter_start,
                "chapter_end": entry.chapter_end,
                "note": entry.note,
            }
            entry_key = canonical_sha256(entry_payload)
            source_payload = {
                **entry_payload,
                "entry_key": entry_key,
                "asset_type": asset.asset_type.value,
                "transferable_rule": item.transferable_rule,
                "adaptation_risk": item.adaptation_risk,
                "source_work_fingerprints": [
                    value.model_dump(mode="json") for value in work_fingerprints
                ],
            }
            resolved.append(
                RecipeSourceSnapshot.model_validate(
                    {
                        **source_payload,
                        "source_snapshot_sha256": canonical_sha256(source_payload),
                    }
                )
            )
        keys = [source.entry_key for source in resolved]
        if len(keys) != len(set(keys)):
            raise WritingPatternError("duplicate_recipe_entry")
        return sorted(
            resolved,
            key=lambda source: (
                source.dimension.value,
                source.pattern_name.casefold(),
                source.asset_content_sha256,
                source.entry_key,
            ),
        )

    def _work_fingerprints(
        self,
        asset: CraftPatternAsset,
        selected_work_ids: list[str],
    ) -> list[WritingPatternWorkFingerprint]:
        if not selected_work_ids or not set(selected_work_ids) <= set(asset.source_work_ids):
            raise WritingPatternError("invalid_pattern_item_evidence")
        placeholders = ",".join("?" for _ in selected_work_ids)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, content_sha256 FROM reference_works
                WHERE id IN ({placeholders})
                """,
                selected_work_ids,
            ).fetchall()
        content_by_id = {str(row["id"]): str(row["content_sha256"]) for row in rows}
        values: dict[str, WritingPatternWorkFingerprint] = {}
        for work_id in selected_work_ids:
            content_hash = content_by_id.get(work_id)
            if content_hash is not None:
                fingerprint = WritingPatternWorkFingerprint(
                    basis="content_sha256",
                    identity_sha256=content_hash,
                )
            else:
                fingerprint = WritingPatternWorkFingerprint(
                    basis="abstract_lineage",
                    identity_sha256=canonical_sha256(
                        {"kind": "abstract_work_lineage", "work_id": work_id}
                    ),
                )
            values[fingerprint.identity_sha256] = fingerprint
        return sorted(values.values(), key=lambda value: value.identity_sha256)

    @staticmethod
    def _assert_no_source_title_leak(item: CraftPatternItem) -> None:
        def normalized(value: str) -> str:
            return "".join(
                character.casefold()
                for character in unicodedata.normalize("NFKC", value)
                if character.isalnum()
            )

        protected_titles = {
            normalized(evidence.work_title)
            for evidence in item.evidence
            if len(normalized(evidence.work_title)) >= 2
        }
        candidate_fields = (
            normalized(item.name),
            normalized(item.transferable_rule),
            normalized(item.adaptation_risk),
        )
        if any(
            title in field
            for title in protected_titles
            for field in candidate_fields
        ):
            raise WritingPatternError("source_title_leak")

    def _confirmed_topic(
        self,
        project_id: str,
        expected_revision: int,
    ) -> TopicDecisionVersion:
        try:
            topic = self.topic_decisions.get_confirmed_version(project_id)
        except (TopicDecisionNotConfirmedError, TopicDecisionNotFoundError) as error:
            raise WritingPatternError("topic_not_confirmed") from error
        if topic.revision != expected_revision:
            raise WritingPatternError("topic_changed")
        return topic
