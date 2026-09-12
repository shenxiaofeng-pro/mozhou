from __future__ import annotations

import json
from collections import defaultdict
from hmac import compare_digest
from typing import Any

from pydantic import ValidationError

from app.writing_patterns.compiler import (
    WRITING_PATTERN_COMPILER_VERSION,
    canonical_sha256,
    compile_writing_pattern_profile,
    detect_recipe_conflicts,
    recipe_content_sha256,
    recipe_source_snapshot_sha256,
)
from app.writing_patterns.models import (
    ModelSafeWritingPatternProfile,
    RecipeSourceSnapshot,
    WritingPatternConflict,
    WritingPatternConflictDecisionInput,
    WritingPatternLifecycleState,
    WritingPatternSafetyBasis,
)


class InvalidWritingPatternArchiveError(ValueError):
    pass


def _json_value(value: object) -> Any:
    if not isinstance(value, str):
        raise InvalidWritingPatternArchiveError("invalid_writing_pattern_json")
    try:
        return json.loads(value)
    except (json.JSONDecodeError, RecursionError) as error:
        raise InvalidWritingPatternArchiveError("invalid_writing_pattern_json") from error


def _json_text(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _entry_payload(source: RecipeSourceSnapshot) -> dict[str, object]:
    return {
        "asset_version_id": source.asset_version_id,
        "asset_series_id": source.asset_series_id,
        "asset_version": source.asset_version,
        "asset_content_sha256": source.asset_content_sha256,
        "dimension": source.dimension.value,
        "pattern_name": source.pattern_name,
        "purpose": source.purpose.value,
        "strategy": source.strategy.value,
        "weight": source.weight,
        "applicable_stages": sorted(
            stage.value for stage in source.applicable_stages
        ),
        "chapter_start": source.chapter_start,
        "chapter_end": source.chapter_end,
        "note": source.note,
    }


def _source_payload(source: RecipeSourceSnapshot) -> dict[str, object]:
    return {
        **_entry_payload(source),
        "entry_key": source.entry_key,
        "asset_type": source.asset_type.value,
        "transferable_rule": source.transferable_rule,
        "adaptation_risk": source.adaptation_risk,
        "source_work_fingerprints": [
            item.model_dump(mode="json")
            for item in sorted(
                source.source_work_fingerprints,
                key=lambda item: item.identity_sha256,
            )
        ],
    }


def _source_from_row(row: dict[str, Any]) -> RecipeSourceSnapshot:
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
            "applicable_stages": _json_value(row["applicable_stages_json"]),
            "chapter_start": row["chapter_start"],
            "chapter_end": row["chapter_end"],
            "note": row["note"],
            "source_work_fingerprints": _json_value(
                row["source_work_fingerprints_json"]
            ),
            "source_snapshot_sha256": row["source_snapshot_sha256"],
        }
    )


def _validated_source(
    row: dict[str, Any],
    craft_assets: dict[str, dict[str, Any]],
) -> RecipeSourceSnapshot:
    source = _source_from_row(row)
    expected_entry_key = canonical_sha256(_entry_payload(source))
    if not compare_digest(expected_entry_key, source.entry_key):
        raise InvalidWritingPatternArchiveError("invalid_recipe_entry_key")
    expected_source_hash = canonical_sha256(_source_payload(source))
    if not compare_digest(expected_source_hash, source.source_snapshot_sha256):
        raise InvalidWritingPatternArchiveError("invalid_recipe_source_hash")
    asset = craft_assets.get(source.asset_version_id)
    if asset is None:
        raise InvalidWritingPatternArchiveError("external_recipe_asset")
    if (
        source.asset_series_id != asset["series_id"]
        or source.asset_version != asset["version"]
        or source.asset_content_sha256 != asset["content_sha256"]
        or source.asset_type.value != asset["asset_type"]
    ):
        raise InvalidWritingPatternArchiveError("invalid_recipe_asset_snapshot")
    return source


def validate_writing_pattern_tables(
    tables: dict[str, list[dict[str, Any]]],
    *,
    craft_asset_rows: list[dict[str, Any]] | None = None,
) -> None:
    """Validate the immutable recipe/profile closure without reading raw sources."""
    try:
        recipes = {str(row["id"]): row for row in tables["writing_pattern_recipes"]}
        versions = {
            str(row["id"]): row
            for row in tables["writing_pattern_recipe_versions"]
        }
        craft_assets = {
            str(row["id"]): row
            for row in (
                craft_asset_rows
                if craft_asset_rows is not None
                else tables["craft_pattern_assets"]
            )
        }
        for row in recipes.values():
            WritingPatternLifecycleState(str(row["lifecycle_state"]))
            if not isinstance(row["lifecycle_revision"], int) or row[
                "lifecycle_revision"
            ] < 0:
                raise InvalidWritingPatternArchiveError("invalid_recipe_lifecycle")

        source_rows: dict[str, list[tuple[int, RecipeSourceSnapshot]]] = defaultdict(list)
        for row in tables["writing_pattern_recipe_sources"]:
            version_id = str(row["recipe_version_id"])
            if version_id not in versions:
                raise InvalidWritingPatternArchiveError("orphan_recipe_source")
            ordinal = row["ordinal"]
            if not isinstance(ordinal, int) or ordinal < 0:
                raise InvalidWritingPatternArchiveError("invalid_recipe_source_ordinal")
            source_rows[version_id].append(
                (ordinal, _validated_source(row, craft_assets))
            )

        versions_by_recipe: dict[str, list[int]] = defaultdict(list)
        validated_sources: dict[str, list[RecipeSourceSnapshot]] = {}
        for version_id, row in versions.items():
            recipe_id = str(row["recipe_id"])
            if recipe_id not in recipes:
                raise InvalidWritingPatternArchiveError("orphan_recipe_version")
            version = row["version"]
            if not isinstance(version, int) or version < 1:
                raise InvalidWritingPatternArchiveError("invalid_recipe_version")
            versions_by_recipe[recipe_id].append(version)
            ordered = sorted(source_rows.get(version_id, []), key=lambda item: item[0])
            if [ordinal for ordinal, _source in ordered] != list(range(len(ordered))):
                raise InvalidWritingPatternArchiveError("invalid_recipe_source_ordinal")
            sources = [source for _ordinal, source in ordered]
            if not sources:
                raise InvalidWritingPatternArchiveError("recipe_without_sources")
            validated_sources[version_id] = sources
            conflicts = [
                WritingPatternConflict.model_validate(item)
                for item in _json_value(row["conflicts_json"])
            ]
            decisions = [
                WritingPatternConflictDecisionInput.model_validate(item)
                for item in _json_value(row["conflict_decisions_json"])
            ]
            detected = detect_recipe_conflicts(sources)
            if detected != conflicts:
                raise InvalidWritingPatternArchiveError("invalid_recipe_conflicts")
            source_hash = recipe_source_snapshot_sha256(sources)
            content_hash = recipe_content_sha256(
                name=str(row["name"]),
                description=str(row["description"]),
                sources=sources,
                conflicts=conflicts,
                decisions=decisions,
            )
            work_ids = {
                fingerprint.identity_sha256
                for source in sources
                for fingerprint in source.source_work_fingerprints
            }
            if (
                row["source_asset_count"]
                != len({source.asset_version_id for source in sources})
                or row["source_work_count"] != len(work_ids)
                or not 1 <= len(work_ids) <= 5
                or row["source_snapshot_sha256"] != source_hash
                or row["content_sha256"] != content_hash
            ):
                raise InvalidWritingPatternArchiveError("invalid_recipe_version_hash")
            selected_families: dict[str, str] = {}
            for source in sources:
                previous = selected_families.setdefault(
                    source.asset_series_id, source.asset_version_id
                )
                if previous != source.asset_version_id:
                    raise InvalidWritingPatternArchiveError(
                        "multiple_asset_versions_in_family"
                    )
            compile_writing_pattern_profile(
                sources,
                decisions=decisions,
                topic_revision=1,
                topic_content_sha256="0" * 64,
                recipe_content_sha256=content_hash,
                safety_basis=WritingPatternSafetyBasis(str(row["safety_basis"])),
            )

        for recipe_id in recipes:
            values = sorted(versions_by_recipe.get(recipe_id, []))
            if not values or values != list(range(1, values[-1] + 1)):
                raise InvalidWritingPatternArchiveError("invalid_recipe_version_sequence")

        topic_versions = {
            str(row["id"]): row for row in tables["topic_decision_versions"]
        }
        profile_rows = {
            str(row["id"]): row
            for row in tables["writing_pattern_profile_versions"]
        }
        for profile_id, row in profile_rows.items():
            version_id = str(row["recipe_version_id"])
            version = versions.get(version_id)
            topic = topic_versions.get(str(row["topic_decision_version_id"]))
            if version is None or topic is None:
                raise InvalidWritingPatternArchiveError("external_profile_snapshot")
            if (
                row["recipe_content_sha256"] != version["content_sha256"]
                or row["topic_revision"] != topic["revision"]
                or row["topic_content_sha256"] != topic["content_sha256"]
                or row["source_snapshot_sha256"]
                != version["source_snapshot_sha256"]
                or row["compiler_version"] != WRITING_PATTERN_COMPILER_VERSION
            ):
                raise InvalidWritingPatternArchiveError("invalid_profile_binding")
            decisions = [
                WritingPatternConflictDecisionInput.model_validate(item)
                for item in _json_value(version["conflict_decisions_json"])
            ]
            compiled = compile_writing_pattern_profile(
                validated_sources[version_id],
                decisions=decisions,
                topic_revision=int(row["topic_revision"]),
                topic_content_sha256=str(row["topic_content_sha256"]),
                recipe_content_sha256=str(row["recipe_content_sha256"]),
                safety_basis=WritingPatternSafetyBasis(str(row["safety_basis"])),
            )
            profile = ModelSafeWritingPatternProfile.model_validate(
                _json_value(row["profile_json"])
            )
            if (
                profile != compiled.model_safe_profile
                or _json_value(row["conflicts_json"])
                != [item.model_dump(mode="json") for item in compiled.conflicts]
                or _json_value(row["decisions_json"])
                != [item.model_dump(mode="json") for item in compiled.decisions]
                or _json_value(row["excluded_entry_keys_json"])
                != compiled.excluded_entry_keys
                or row["profile_fingerprint_sha256"]
                != compiled.profile_fingerprint_sha256
            ):
                raise InvalidWritingPatternArchiveError("invalid_compiled_profile")

        linked_profiles: set[str] = set()
        active_by_project: dict[str, int] = defaultdict(int)
        for row in tables["project_writing_pattern_profiles"]:
            profile_id = str(row["profile_version_id"])
            profile_row = profile_rows.get(profile_id)
            if (
                profile_row is None
                or profile_id in linked_profiles
                or profile_row["project_id"] != row["project_id"]
            ):
                raise InvalidWritingPatternArchiveError("invalid_profile_link")
            linked_profiles.add(profile_id)
            state = WritingPatternLifecycleState(str(row["lifecycle_state"]))
            if not isinstance(row["lifecycle_revision"], int) or row[
                "lifecycle_revision"
            ] < 0:
                raise InvalidWritingPatternArchiveError("invalid_profile_lifecycle")
            if state == WritingPatternLifecycleState.ACTIVE:
                active_by_project[str(row["project_id"])] += 1
        if linked_profiles != set(profile_rows) or any(
            count > 1 for count in active_by_project.values()
        ):
            raise InvalidWritingPatternArchiveError("invalid_profile_link")
    except InvalidWritingPatternArchiveError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise InvalidWritingPatternArchiveError("invalid_writing_pattern_rows") from error


def rebind_writing_pattern_rows(
    tables: dict[str, list[dict[str, Any]]],
    *,
    craft_asset_rows: list[dict[str, Any]],
) -> None:
    """Recompute hashes whose canonical payload contains remapped identifiers."""
    assets = {str(row["id"]): row for row in craft_asset_rows}
    versions = {
        str(row["id"]): row for row in tables["writing_pattern_recipe_versions"]
    }
    rows_by_version: dict[str, list[dict[str, Any]]] = defaultdict(list)
    old_to_new_entry: dict[str, str] = {}
    for row in tables["writing_pattern_recipe_sources"]:
        asset = assets.get(str(row["asset_version_id"]))
        if asset is None:
            raise InvalidWritingPatternArchiveError("external_recipe_asset")
        row["asset_series_id"] = asset["series_id"]
        row["asset_version"] = asset["version"]
        row["asset_content_sha256"] = asset["content_sha256"]
        row["asset_type"] = asset["asset_type"]
        provisional = _source_from_row(row)
        old_entry_key = provisional.entry_key
        new_entry_key = canonical_sha256(_entry_payload(provisional))
        row["entry_key"] = new_entry_key
        rebound = _source_from_row(row)
        row["source_snapshot_sha256"] = canonical_sha256(_source_payload(rebound))
        old_to_new_entry[old_entry_key] = new_entry_key
        rows_by_version[str(row["recipe_version_id"])].append(row)

    for version_id, version in versions.items():
        source_rows = sorted(rows_by_version[version_id], key=lambda row: row["ordinal"])
        sources = [_source_from_row(row) for row in source_rows]
        old_conflicts = [
            WritingPatternConflict.model_validate(item)
            for item in _json_value(version["conflicts_json"])
        ]
        new_conflicts = detect_recipe_conflicts(sources)
        new_by_signature = {
            (
                conflict.dimension.value,
                conflict.applicable_stage.value,
                tuple(conflict.entry_keys),
                conflict.reason,
            ): conflict
            for conflict in new_conflicts
        }
        conflict_key_map: dict[str, str] = {}
        for conflict in old_conflicts:
            mapped_keys = tuple(
                sorted(old_to_new_entry[key] for key in conflict.entry_keys)
            )
            signature = (
                conflict.dimension.value,
                conflict.applicable_stage.value,
                mapped_keys,
                conflict.reason,
            )
            mapped = new_by_signature.get(signature)
            if mapped is None:
                raise InvalidWritingPatternArchiveError("invalid_recipe_conflicts")
            conflict_key_map[conflict.conflict_key] = mapped.conflict_key
        decisions = _json_value(version["conflict_decisions_json"])
        if not isinstance(decisions, list):
            raise InvalidWritingPatternArchiveError("invalid_recipe_conflicts")
        rebound_decisions: list[WritingPatternConflictDecisionInput] = []
        for value in decisions:
            if not isinstance(value, dict):
                raise InvalidWritingPatternArchiveError("invalid_recipe_conflicts")
            decision = dict(value)
            decision["conflict_key"] = conflict_key_map[str(decision["conflict_key"])]
            if decision.get("chosen_entry_key") is not None:
                decision["chosen_entry_key"] = old_to_new_entry[
                    str(decision["chosen_entry_key"])
                ]
            rebound_decisions.append(
                WritingPatternConflictDecisionInput.model_validate(decision)
            )
        source_hash = recipe_source_snapshot_sha256(sources)
        content_hash = recipe_content_sha256(
            name=str(version["name"]),
            description=str(version["description"]),
            sources=sources,
            conflicts=new_conflicts,
            decisions=rebound_decisions,
        )
        version["conflicts_json"] = _json_text(
            [item.model_dump(mode="json") for item in new_conflicts]
        )
        version["conflict_decisions_json"] = _json_text(
            [item.model_dump(mode="json") for item in rebound_decisions]
        )
        version["source_snapshot_sha256"] = source_hash
        version["content_sha256"] = content_hash
        version["source_asset_count"] = len(
            {source.asset_version_id for source in sources}
        )
        version["source_work_count"] = len(
            {
                item.identity_sha256
                for source in sources
                for item in source.source_work_fingerprints
            }
        )

    for row in tables["writing_pattern_profile_versions"]:
        profile_version_row = versions.get(str(row["recipe_version_id"]))
        if profile_version_row is None:
            raise InvalidWritingPatternArchiveError("external_profile_snapshot")
        row["recipe_content_sha256"] = profile_version_row["content_sha256"]
        row["source_snapshot_sha256"] = profile_version_row[
            "source_snapshot_sha256"
        ]
        row["compiler_version"] = WRITING_PATTERN_COMPILER_VERSION
        decisions = [
            WritingPatternConflictDecisionInput.model_validate(item)
            for item in _json_value(profile_version_row["conflict_decisions_json"])
        ]
        compiled = compile_writing_pattern_profile(
            [
                _source_from_row(value)
                for value in rows_by_version[str(profile_version_row["id"])]
            ],
            decisions=decisions,
            topic_revision=int(row["topic_revision"]),
            topic_content_sha256=str(row["topic_content_sha256"]),
            recipe_content_sha256=str(row["recipe_content_sha256"]),
            safety_basis=WritingPatternSafetyBasis(str(row["safety_basis"])),
        )
        row["profile_json"] = _json_text(
            compiled.model_safe_profile.model_dump(mode="json")
        )
        row["conflicts_json"] = _json_text(
            [item.model_dump(mode="json") for item in compiled.conflicts]
        )
        row["decisions_json"] = _json_text(
            [item.model_dump(mode="json") for item in compiled.decisions]
        )
        row["excluded_entry_keys_json"] = _json_text(compiled.excluded_entry_keys)
        row["profile_fingerprint_sha256"] = compiled.profile_fingerprint_sha256
