from __future__ import annotations

import pytest

from app.models import (
    BookBlueprintContent,
    CraftPatternDimension,
    Genre,
    OriginalityRiskLevel,
)
from app.pattern_adaptation.originality import (
    THRESHOLD_VERSION,
    PatternOriginalitySignal,
    assess_pattern_adaptation_originality,
)
from app.writing_patterns.models import (
    ModelSafeWritingPatternProfile,
    ModelSafeWritingPatternRule,
    WritingPatternPurpose,
    WritingPatternSafetyBasis,
    WritingPatternStage,
    WritingPatternStrategy,
)


def _rule(
    source: str,
    dimension: CraftPatternDimension,
    transferable_rule: str,
    adaptation_risk: str,
) -> ModelSafeWritingPatternRule:
    return ModelSafeWritingPatternRule(
        source_content_sha256=source * 64,
        dimension=dimension,
        name="抽象写作功能",
        transferable_rule=transferable_rule,
        adaptation_risk=adaptation_risk,
        purpose=WritingPatternPurpose.LEARN,
        strategy=WritingPatternStrategy.TRANSFORM,
        weight_basis_points=5000,
        applicable_stages=[WritingPatternStage.STARTUP],
    )


def _profile() -> ModelSafeWritingPatternProfile:
    return ModelSafeWritingPatternProfile(
        compiler_version="writing-pattern-compiler-v1",
        topic_revision=3,
        topic_content_sha256="c" * 64,
        recipe_content_sha256="d" * 64,
        safety_basis=WritingPatternSafetyBasis.SOURCE_VERIFIED,
        rules=[
            _rule(
                "a",
                CraftPatternDimension.KEY_SCENE_SEQUENCE,
                "流亡继承人加入星环会，导师授予赤曜印；每次施术都失去记忆，盟友受圣庭逼迫后倒戈。",
                "应改变组织专名、能力代价、导师与盟友的功能关系及倒戈原因。",
            ),
            _rule(
                "b",
                CraftPatternDimension.CONFLICT_CAUSALITY,
                "圣庭追捕使盟友背叛，背叛导致星环会封锁资源，主角被迫摧毁赤曜印换取自由。",
                "不要保留“追捕—背叛—资源断供—摧毁能力核心”的完整因果链。",
            ),
        ],
    )


def _blueprint() -> BookBlueprintContent:
    return BookBlueprintContent(
        title="星环会的末代继承人",
        genre=Genre.WESTERN_FANTASY,
        rebirth_year=1243,
        rebirth_location="圣庭边境",
        target_audience="喜欢成长、阴谋和高代价魔法的读者",
        core_selling_points=["赤曜印使用后会失去记忆"],
        core_desire="摆脱圣庭对命运的控制",
        divergence_point="主角在星环会接受导师授予的赤曜印",
        long_term_promise="找出圣庭追捕继承人的真正原因",
        ending_direction="摧毁赤曜印，失去力量并换得自由",
        protagonist_arc="从依赖导师的继承人成为自主决策者",
        resource_growth="借赤曜印获得禁术，每次施术都失去一段记忆",
        relationship_design="导师先庇护主角，盟友因圣庭追捕而背叛并封锁资源",
    )


def test_distinctive_multi_source_structure_is_high_and_report_is_non_reversible() -> None:
    scenes = [
        "流亡继承人加入星环会",
        "导师授予赤曜印",
        "主角施术后失去记忆",
        "圣庭追捕迫使盟友背叛并封锁资源",
        "主角摧毁赤曜印换取自由",
    ]

    work_fingerprints = ["1" * 64, "2" * 64]
    first = assess_pattern_adaptation_originality(
        _profile(),
        _blueprint(),
        scenes,
        source_work_fingerprints=work_fingerprints,
    )
    second = assess_pattern_adaptation_originality(
        _profile(),
        _blueprint(),
        scenes,
        source_work_fingerprints=work_fingerprints,
    )

    assert first == second
    assert first.risk_level == OriginalityRiskLevel.HIGH
    assert first.score >= 75
    assert first.threshold_version == THRESHOLD_VERSION
    assert len(first.input_sha256) == 64
    assert {finding.signal for finding in first.findings} >= {
        PatternOriginalitySignal.PROPER_NOUN_LIKE,
        PatternOriginalitySignal.RELATIONSHIP_FUNCTION,
        PatternOriginalitySignal.ORDERED_SCENE,
        PatternOriginalitySignal.CAUSAL_RESOURCE_COMBINATION,
        PatternOriginalitySignal.MULTI_SOURCE_AGGREGATION,
    }
    serialized = first.model_dump_json()
    for prohibited in ("星环会", "赤曜印", "圣庭"):
        assert prohibited not in serialized
    assert all(len(finding.evidence_sha256) == 64 for finding in first.findings)


def test_one_fusion_asset_with_two_work_fingerprints_is_multi_source() -> None:
    profile = _profile().model_copy(update={"rules": [_profile().rules[0]]})

    assessment = assess_pattern_adaptation_originality(
        profile,
        _blueprint(),
        [
            "流亡继承人加入星环会",
            "导师授予赤曜印",
            "主角施术后失去记忆",
        ],
        source_work_fingerprints=["1" * 64, "2" * 64],
    )

    assert any(
        finding.signal == PatternOriginalitySignal.MULTI_SOURCE_AGGREGATION
        for finding in assessment.findings
    )


def test_multiple_assets_from_one_work_are_not_multi_source() -> None:
    assessment = assess_pattern_adaptation_originality(
        _profile(),
        _blueprint(),
        [
            "流亡继承人加入星环会",
            "导师授予赤曜印",
            "圣庭追捕迫使盟友背叛并封锁资源",
        ],
        source_work_fingerprints=["1" * 64, "1" * 64],
    )

    assert all(
        finding.signal != PatternOriginalitySignal.MULTI_SOURCE_AGGREGATION
        for finding in assessment.findings
    )


def test_common_single_trope_cannot_be_high_risk() -> None:
    profile = ModelSafeWritingPatternProfile(
        compiler_version="writing-pattern-compiler-v1",
        topic_revision=1,
        topic_content_sha256="1" * 64,
        recipe_content_sha256="2" * 64,
        safety_basis=WritingPatternSafetyBasis.ABSTRACT_ONLY,
        rules=[
            _rule(
                "e",
                CraftPatternDimension.KEY_SCENE_SEQUENCE,
                "主角受到欺辱，意外获得力量，反击敌人，赢得胜利。",
                "这是常见的成长节拍，需要替换具体触发条件。",
            )
        ],
    )
    blueprint = _blueprint().model_copy(
        update={
            "title": "逆境成长",
            "core_selling_points": ["受挫后获得新力量"],
            "core_desire": "赢得尊重",
            "divergence_point": "意外获得力量",
            "long_term_promise": "不断反击更强敌人",
            "ending_direction": "赢得最终胜利",
            "protagonist_arc": "从弱小到强大",
            "resource_growth": "通过挑战获得力量",
            "relationship_design": "对手不断施压，主角逐步反击",
        }
    )

    assessment = assess_pattern_adaptation_originality(
        profile,
        blueprint,
        ["主角受到欺辱", "意外获得力量", "反击敌人", "赢得胜利"],
    )

    assert assessment.risk_level == OriginalityRiskLevel.LOW
    assert assessment.score < 45


def test_score_from_45_through_74_is_medium_and_scene_change_changes_input_sha() -> None:
    profile = ModelSafeWritingPatternProfile(
        compiler_version="writing-pattern-compiler-v1",
        topic_revision=2,
        topic_content_sha256="3" * 64,
        recipe_content_sha256="4" * 64,
        safety_basis=WritingPatternSafetyBasis.SOURCE_VERIFIED,
        rules=[
            _rule(
                "a",
                CraftPatternDimension.CONFLICT_CAUSALITY,
                "导师庇护星环会的继承人。",
                "避免沿用导师的庇护功能和星环会专名。",
            ),
            _rule(
                "b",
                CraftPatternDimension.CONFLICT_CAUSALITY,
                "盟友受圣庭逼迫后背叛。",
                "避免沿用盟友背叛和圣庭施压的组合。",
            ),
        ],
    )
    blueprint = _blueprint().model_copy(
        update={
            "core_desire": "在城市中寻找自由",
            "divergence_point": "星环会的导师庇护主角",
            "long_term_promise": "调查圣庭施压的原因",
            "ending_direction": "主角离开城市",
            "protagonist_arc": "从受庇护者成为独立决策者",
            "resource_growth": "通过完成任务积累普通资源",
            "relationship_design": "导师庇护主角，盟友受圣庭逼迫后背叛",
        }
    )

    first = assess_pattern_adaptation_originality(profile, blueprint, ["主角走进大厅"])
    changed = assess_pattern_adaptation_originality(profile, blueprint, ["主角走出大厅"])

    assert 45 <= first.score < 75
    assert first.risk_level == OriginalityRiskLevel.MEDIUM
    assert changed.input_sha256 != first.input_sha256


def test_key_scene_sequence_must_be_non_empty_and_model_safe() -> None:
    with pytest.raises(ValueError, match="抽象关键场景顺序不完整"):
        assess_pattern_adaptation_originality(_profile(), _blueprint(), [])

    with pytest.raises(ValueError, match="抽象关键场景顺序不完整"):
        assess_pattern_adaptation_originality(_profile(), _blueprint(), ["不合\x00法"])
