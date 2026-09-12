from hashlib import sha256
from uuid import uuid4

import pytest

from app.models import CraftPatternDimension
from app.writing_patterns.compiler import (
    InvalidConflictDecisionError,
    compile_writing_pattern_profile,
    detect_recipe_conflicts,
)
from app.writing_patterns.models import (
    RecipeSourceSnapshot,
    WritingPatternConflictDecisionInput,
    WritingPatternConflictResolution,
    WritingPatternPurpose,
    WritingPatternSafetyBasis,
    WritingPatternStage,
    WritingPatternStrategy,
)


def _digest(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def _source(
    label: str,
    *,
    dimension: CraftPatternDimension = CraftPatternDimension.HOOK_MECHANICS,
    strategy: WritingPatternStrategy = WritingPatternStrategy.PRESERVE_FUNCTION,
    weight: int = 50,
    stages: list[WritingPatternStage] | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
) -> RecipeSourceSnapshot:
    asset_id = str(uuid4())
    return RecipeSourceSnapshot(
        entry_key=_digest(f"entry:{label}"),
        asset_version_id=asset_id,
        asset_series_id=_digest(f"series:{label}"),
        asset_version=1,
        asset_content_sha256=_digest(f"asset:{label}"),
        dimension=dimension,
        pattern_name=f"{label}技法",
        transferable_rule=f"{label}只保留功能逻辑",
        adaptation_risk=f"{label}不得复刻具体场景",
        purpose=WritingPatternPurpose.LEARN,
        strategy=strategy,
        weight=weight,
        applicable_stages=stages or [WritingPatternStage.CHAPTER_DRAFT],
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        note="作者配方备注",
        source_work_fingerprints=[
            {
                "basis": "content_sha256",
                "identity_sha256": _digest(f"work:{label}"),
            }
        ],
        source_snapshot_sha256=_digest(f"snapshot:{label}"),
    )


def test_compiler_is_order_stable_and_normalizes_each_dimension_to_basis_points() -> None:
    sources = [
        _source(
            "B",
            dimension=CraftPatternDimension.EMOTIONAL_RHYTHM,
            strategy=WritingPatternStrategy.TRANSFORM,
            weight=1,
        ),
        _source(
            "A",
            dimension=CraftPatternDimension.EMOTIONAL_RHYTHM,
            strategy=WritingPatternStrategy.TRANSFORM,
            weight=2,
        ),
        _source(
            "C",
            dimension=CraftPatternDimension.SCENE_DESIGN,
            strategy=WritingPatternStrategy.AVOID,
            weight=30,
        ),
    ]

    first = compile_writing_pattern_profile(
        sources,
        decisions=[],
        topic_revision=3,
        topic_content_sha256=_digest("topic"),
        recipe_content_sha256=_digest("recipe"),
        safety_basis=WritingPatternSafetyBasis.SOURCE_VERIFIED,
    )
    second = compile_writing_pattern_profile(
        list(reversed(sources)),
        decisions=[],
        topic_revision=3,
        topic_content_sha256=_digest("topic"),
        recipe_content_sha256=_digest("recipe"),
        safety_basis=WritingPatternSafetyBasis.SOURCE_VERIFIED,
    )

    assert first.profile_fingerprint_sha256 == second.profile_fingerprint_sha256
    assert first.model_safe_profile == second.model_safe_profile
    emotional = [
        rule
        for rule in first.model_safe_profile.rules
        if rule.dimension == CraftPatternDimension.EMOTIONAL_RHYTHM
    ]
    assert sum(rule.weight_basis_points for rule in emotional) == 10_000
    assert [rule.weight_basis_points for rule in emotional] == [6667, 3333]
    assert sum(
        rule.weight_basis_points
        for rule in first.model_safe_profile.rules
        if rule.dimension == CraftPatternDimension.SCENE_DESIGN
    ) == 10_000


def test_conflicts_require_an_explicit_non_averaging_decision() -> None:
    left = _source("left")
    right = _source("right")
    conflicts = detect_recipe_conflicts([right, left])

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.entry_keys == sorted([left.entry_key, right.entry_key])
    with pytest.raises(InvalidConflictDecisionError, match="unresolved_recipe_conflict"):
        compile_writing_pattern_profile(
            [left, right],
            decisions=[],
            topic_revision=1,
            topic_content_sha256=_digest("topic"),
            recipe_content_sha256=_digest("recipe"),
            safety_basis=WritingPatternSafetyBasis.ABSTRACT_ONLY,
        )

    selected = compile_writing_pattern_profile(
        [left, right],
        decisions=[
            WritingPatternConflictDecisionInput(
                conflict_key=conflict.conflict_key,
                resolution=WritingPatternConflictResolution.CHOOSE_SOURCE,
                chosen_entry_key=right.entry_key,
            )
        ],
        topic_revision=1,
        topic_content_sha256=_digest("topic"),
        recipe_content_sha256=_digest("recipe"),
        safety_basis=WritingPatternSafetyBasis.ABSTRACT_ONLY,
    )

    assert [rule.transferable_rule for rule in selected.model_safe_profile.rules] == [
        right.transferable_rule
    ]
    assert right.pattern_name not in selected.model_safe_profile.rules[0].name
    assert selected.model_safe_profile.rules[0].weight_basis_points == 10_000
    assert selected.decisions[0].resolution == WritingPatternConflictResolution.CHOOSE_SOURCE


def test_conflict_decision_only_changes_the_conflicting_stage() -> None:
    left = _source(
        "left-scoped",
        stages=[WritingPatternStage.CHAPTER_DRAFT, WritingPatternStage.REVIEW],
    )
    right = _source(
        "right-scoped",
        stages=[WritingPatternStage.CHAPTER_DRAFT],
    )
    conflict = detect_recipe_conflicts([left, right])[0]

    compiled = compile_writing_pattern_profile(
        [left, right],
        decisions=[
            WritingPatternConflictDecisionInput(
                conflict_key=conflict.conflict_key,
                resolution=WritingPatternConflictResolution.CHOOSE_SOURCE,
                chosen_entry_key=right.entry_key,
            )
        ],
        topic_revision=1,
        topic_content_sha256=_digest("topic-scoped"),
        recipe_content_sha256=_digest("recipe-scoped"),
        safety_basis=WritingPatternSafetyBasis.ABSTRACT_ONLY,
    )

    left_rules = [
        rule
        for rule in compiled.model_safe_profile.rules
        if rule.transferable_rule == left.transferable_rule
    ]
    right_rules = [
        rule
        for rule in compiled.model_safe_profile.rules
        if rule.transferable_rule == right.transferable_rule
    ]
    assert [rule.applicable_stages for rule in left_rules] == [
        [WritingPatternStage.REVIEW]
    ]
    assert [rule.applicable_stages for rule in right_rules] == [
        [WritingPatternStage.CHAPTER_DRAFT]
    ]
    assert compiled.excluded_entry_keys == []


def test_partial_range_conflicts_are_rejected_instead_of_over_excluding() -> None:
    left = _source("left-range", chapter_start=1, chapter_end=20)
    right = _source("right-range", chapter_start=10, chapter_end=30)

    with pytest.raises(
        InvalidConflictDecisionError,
        match="partial_range_conflict_not_supported",
    ):
        detect_recipe_conflicts([left, right])


def test_model_safe_profile_contains_no_source_identity_or_evidence_fields() -> None:
    source = _source(
        "safe",
        strategy=WritingPatternStrategy.TRANSFORM,
    )
    compiled = compile_writing_pattern_profile(
        [source],
        decisions=[],
        topic_revision=2,
        topic_content_sha256=_digest("topic"),
        recipe_content_sha256=_digest("recipe"),
        safety_basis=WritingPatternSafetyBasis.ABSTRACT_ONLY,
    )

    payload = compiled.model_safe_profile.model_dump(mode="json")
    encoded = str(payload)
    assert "asset_version_id" not in encoded
    assert "work_id" not in encoded
    assert "work_title" not in encoded
    assert "observation" not in encoded
    assert "evidence" not in encoded
    rule = payload["rules"][0]
    assert set(rule) == {
        "source_content_sha256",
        "dimension",
        "name",
        "transferable_rule",
        "adaptation_risk",
        "purpose",
        "strategy",
        "weight_basis_points",
        "applicable_stages",
        "chapter_start",
        "chapter_end",
    }
