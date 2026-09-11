from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256

from app.models import CraftPatternDimension
from app.writing_patterns.models import (
    AppliedWritingPatternConflictDecision,
    CompiledWritingPatternProfile,
    ModelSafeWritingPatternProfile,
    ModelSafeWritingPatternRule,
    RecipeSourceSnapshot,
    WritingPatternConflict,
    WritingPatternConflictDecisionInput,
    WritingPatternConflictResolution,
    WritingPatternSafetyBasis,
    WritingPatternStage,
    WritingPatternStrategy,
)

WRITING_PATTERN_COMPILER_VERSION = "writing-pattern-compiler-v1"


class InvalidConflictDecisionError(ValueError):
    pass


@dataclass(frozen=True)
class _EffectiveRuleSlice:
    source: RecipeSourceSnapshot
    stage: WritingPatternStage
    strategy: WritingPatternStrategy


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return sha256(canonical_json(value)).hexdigest()


def recipe_source_snapshot_sha256(sources: list[RecipeSourceSnapshot]) -> str:
    return canonical_sha256(
        [
            source.model_dump(mode="json")
            for source in sorted(sources, key=_source_sort_key)
        ]
    )


def recipe_content_sha256(
    *,
    name: str,
    description: str,
    sources: list[RecipeSourceSnapshot],
    conflicts: list[WritingPatternConflict],
    decisions: list[WritingPatternConflictDecisionInput],
) -> str:
    return canonical_sha256(
        {
            "schema_version": 1,
            "name": name,
            "description": description,
            "sources": [
                source.model_dump(mode="json")
                for source in sorted(sources, key=_source_sort_key)
            ],
            "conflicts": [
                conflict.model_dump(mode="json")
                for conflict in sorted(conflicts, key=lambda item: item.conflict_key)
            ],
            "conflict_decisions": [
                decision.model_dump(mode="json")
                for decision in sorted(decisions, key=lambda item: item.conflict_key)
            ],
        }
    )


def _source_sort_key(source: RecipeSourceSnapshot) -> tuple[object, ...]:
    return (
        source.dimension.value,
        source.pattern_name.casefold(),
        source.asset_content_sha256,
        source.entry_key,
    )


def _ranges_overlap(
    left: RecipeSourceSnapshot,
    right: RecipeSourceSnapshot,
) -> bool:
    if left.chapter_start is None or right.chapter_start is None:
        return True
    assert left.chapter_end is not None and right.chapter_end is not None
    return max(left.chapter_start, right.chapter_start) <= min(
        left.chapter_end,
        right.chapter_end,
    )


def detect_recipe_conflicts(
    sources: list[RecipeSourceSnapshot],
) -> list[WritingPatternConflict]:
    conflicts: list[WritingPatternConflict] = []
    ordered = sorted(sources, key=_source_sort_key)
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            if left.dimension != right.dimension or not _ranges_overlap(left, right):
                continue
            shared_stages = sorted(
                set(left.applicable_stages) & set(right.applicable_stages),
                key=lambda stage: stage.value,
            )
            if not shared_stages:
                continue
            strategies = {left.strategy, right.strategy}
            reason: str | None = None
            if strategies == {
                WritingPatternStrategy.PRESERVE_FUNCTION,
                WritingPatternStrategy.AVOID,
            }:
                reason = "preserve_vs_avoid"
            elif (
                left.strategy == WritingPatternStrategy.PRESERVE_FUNCTION
                and right.strategy == WritingPatternStrategy.PRESERVE_FUNCTION
                and left.transferable_rule != right.transferable_rule
            ):
                reason = "competing_preserve_rules"
            if reason is None:
                continue
            if (left.chapter_start, left.chapter_end) != (
                right.chapter_start,
                right.chapter_end,
            ):
                raise InvalidConflictDecisionError(
                    "partial_range_conflict_not_supported"
                )
            entry_keys = sorted([left.entry_key, right.entry_key])
            for stage in shared_stages:
                conflict_key = canonical_sha256(
                    {
                        "dimension": left.dimension.value,
                        "applicable_stage": stage.value,
                        "entry_keys": entry_keys,
                        "reason": reason,
                    }
                )
                conflicts.append(
                    WritingPatternConflict(
                        conflict_key=conflict_key,
                        dimension=left.dimension,
                        applicable_stage=stage,
                        entry_keys=entry_keys,
                        reason=reason,  # type: ignore[arg-type]
                    )
                )
    return sorted(conflicts, key=lambda conflict: conflict.conflict_key)


def _apply_conflict_decisions(
    sources: list[RecipeSourceSnapshot],
    conflicts: list[WritingPatternConflict],
    decisions: list[WritingPatternConflictDecisionInput],
) -> tuple[
    list[_EffectiveRuleSlice],
    list[AppliedWritingPatternConflictDecision],
    list[str],
]:
    conflict_by_key = {conflict.conflict_key: conflict for conflict in conflicts}
    decision_by_key: dict[str, WritingPatternConflictDecisionInput] = {}
    for decision in decisions:
        if decision.conflict_key in decision_by_key:
            raise InvalidConflictDecisionError("duplicate_conflict_decision")
        if decision.conflict_key not in conflict_by_key:
            raise InvalidConflictDecisionError("unknown_conflict_decision")
        decision_by_key[decision.conflict_key] = decision
    if set(decision_by_key) != set(conflict_by_key):
        raise InvalidConflictDecisionError("unresolved_recipe_conflict")

    active: dict[tuple[str, WritingPatternStage], WritingPatternStrategy] = {
        (source.entry_key, stage): source.strategy
        for source in sources
        for stage in source.applicable_stages
    }
    applied: list[AppliedWritingPatternConflictDecision] = []
    for conflict in conflicts:
        decision = decision_by_key[conflict.conflict_key]
        if decision.resolution == WritingPatternConflictResolution.CHOOSE_SOURCE:
            if decision.chosen_entry_key not in conflict.entry_keys:
                raise InvalidConflictDecisionError("chosen_entry_not_in_conflict")
            for key in conflict.entry_keys:
                if key != decision.chosen_entry_key:
                    active.pop((key, conflict.applicable_stage), None)
        elif decision.resolution == WritingPatternConflictResolution.COMBINE_AS_TRANSFORM:
            for key in conflict.entry_keys:
                marker = (key, conflict.applicable_stage)
                if marker in active:
                    active[marker] = WritingPatternStrategy.TRANSFORM
        else:
            for key in conflict.entry_keys:
                active.pop((key, conflict.applicable_stage), None)
        applied.append(
            AppliedWritingPatternConflictDecision(
                **decision.model_dump(mode="python"),
                affected_entry_keys=conflict.entry_keys,
            )
        )

    source_by_key = {source.entry_key: source for source in sources}
    effective = [
        _EffectiveRuleSlice(
            source=source_by_key[entry_key],
            stage=stage,
            strategy=strategy,
        )
        for (entry_key, stage), strategy in active.items()
    ]
    if not effective:
        raise InvalidConflictDecisionError("recipe_has_no_effective_rules")
    active_entry_keys = {item.source.entry_key for item in effective}
    excluded = {source.entry_key for source in sources} - active_entry_keys
    return (
        sorted(
            effective,
            key=lambda item: (
                _source_sort_key(item.source),
                item.stage.value,
                item.strategy.value,
            ),
        ),
        sorted(applied, key=lambda item: item.conflict_key),
        sorted(excluded),
    )


def _basis_points_by_entry(
    slices: list[_EffectiveRuleSlice],
) -> dict[tuple[str, WritingPatternStage], int]:
    grouped: dict[
        tuple[CraftPatternDimension, WritingPatternStage],
        list[_EffectiveRuleSlice],
    ] = defaultdict(list)
    for item in slices:
        grouped[(item.source.dimension, item.stage)].append(item)
    result: dict[tuple[str, WritingPatternStage], int] = {}
    for group_key in sorted(grouped, key=lambda item: (item[0].value, item[1].value)):
        entries = sorted(grouped[group_key], key=lambda item: _source_sort_key(item.source))
        total_weight = sum(item.source.weight for item in entries)
        floors = {
            (item.source.entry_key, item.stage): item.source.weight * 10_000 // total_weight
            for item in entries
        }
        remainder_count = 10_000 - sum(floors.values())
        ranked = sorted(
            entries,
            key=lambda item: (
                -(item.source.weight * 10_000 % total_weight),
                _source_sort_key(item.source),
            ),
        )
        for item in ranked[:remainder_count]:
            floors[(item.source.entry_key, item.stage)] += 1
        result.update(floors)
    return result


def compile_writing_pattern_profile(
    sources: list[RecipeSourceSnapshot],
    *,
    decisions: list[WritingPatternConflictDecisionInput],
    topic_revision: int,
    topic_content_sha256: str,
    recipe_content_sha256: str,
    safety_basis: WritingPatternSafetyBasis,
) -> CompiledWritingPatternProfile:
    if not sources:
        raise InvalidConflictDecisionError("recipe_has_no_sources")
    keys = [source.entry_key for source in sources]
    if len(keys) != len(set(keys)):
        raise InvalidConflictDecisionError("duplicate_recipe_entry")
    conflicts = detect_recipe_conflicts(sources)
    effective, applied, excluded = _apply_conflict_decisions(
        sources,
        conflicts,
        decisions,
    )
    weights = _basis_points_by_entry(effective)
    grouped_slices: dict[
        tuple[str, WritingPatternStrategy, int],
        tuple[RecipeSourceSnapshot, list[WritingPatternStage]],
    ] = {}
    for item in effective:
        weight = weights[(item.source.entry_key, item.stage)]
        marker = (item.source.entry_key, item.strategy, weight)
        grouped = grouped_slices.setdefault(marker, (item.source, []))
        grouped[1].append(item.stage)
    ordered_groups = sorted(
        grouped_slices.values(),
        key=lambda item: (
            _source_sort_key(item[0]),
            min(stage.value for stage in item[1]),
        ),
    )
    rules = []
    for ordinal, (source, stages) in enumerate(ordered_groups, start=1):
        first_stage = stages[0]
        strategy = next(
            item.strategy
            for item in effective
            if item.source.entry_key == source.entry_key and item.stage == first_stage
        )
        rules.append(
            ModelSafeWritingPatternRule(
                source_content_sha256=source.asset_content_sha256,
                dimension=source.dimension,
                name=f"写作规则 {ordinal:03d} · {source.dimension.value}",
                transferable_rule=source.transferable_rule,
                adaptation_risk=source.adaptation_risk,
                purpose=source.purpose,
                strategy=strategy,
                weight_basis_points=weights[(source.entry_key, first_stage)],
                applicable_stages=sorted(stages, key=lambda stage: stage.value),
                chapter_start=source.chapter_start,
                chapter_end=source.chapter_end,
            )
        )
    profile = ModelSafeWritingPatternProfile(
        compiler_version=WRITING_PATTERN_COMPILER_VERSION,
        topic_revision=topic_revision,
        topic_content_sha256=topic_content_sha256,
        recipe_content_sha256=recipe_content_sha256,
        safety_basis=safety_basis,
        rules=rules,
    )
    fingerprint = canonical_sha256(profile.model_dump(mode="json"))
    return CompiledWritingPatternProfile(
        model_safe_profile=profile,
        conflicts=conflicts,
        decisions=applied,
        excluded_entry_keys=excluded,
        profile_fingerprint_sha256=fingerprint,
    )
