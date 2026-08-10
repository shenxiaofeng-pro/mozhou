from app.models import (
    AppliedReferenceDimension,
    BlueprintDimensionState,
    BlueprintEntityKind,
    BlueprintMode,
    BlueprintNamedEntity,
    BlueprintRelationship,
    BlueprintRelationshipState,
    OriginalityRiskLevel,
    OriginalitySignal,
    ReferenceBlueprintState,
    ReferenceDimensionSynthesis,
    ReferencePatternDimension,
)
from app.originality_guard import LEGAL_NOTICE, THRESHOLD_VERSION, assess_blueprint
from app.reference_lab import ReferenceAnalysisInput

DIMENSIONS = list(ReferencePatternDimension)


def _source(segment_id: str, content: str) -> ReferenceAnalysisInput:
    return ReferenceAnalysisInput(
        work_id=f"work-{segment_id}",
        work_title="合成参考作品",
        segment_id=segment_id,
        ordinal=0,
        start_char=100,
        end_char=100 + len(content),
        chapter_start="第一章",
        chapter_end="第一章",
        content=content,
    )


def _dimension(
    segment_id: str,
    *,
    mode: BlueprintMode = BlueprintMode.RECONSTRUCT,
    source_summary: str = "来源抽象结构",
    candidate_summary: str = "重组后的功能方案",
    entities: list[BlueprintNamedEntity] | None = None,
    source_beats: list[str] | None = None,
    key_beats: list[str] | None = None,
) -> BlueprintDimensionState:
    return BlueprintDimensionState(
        source=ReferenceDimensionSynthesis(
            summary=source_summary,
            source_segment_ids=[segment_id],
            transferable_logic="先验证一个小目标，再扩大冲突",
            adaptation_risk="避免沿用专名和具体顺序",
        ),
        mode=mode,
        author_edits="改换人物、地点和现实资源",
        generated_variant=AppliedReferenceDimension(
            summary=candidate_summary,
            transferable_logic="让新人物基于本地条件作出不同选择",
        ),
        named_entities=entities or [],
        source_beats=source_beats or [],
        key_beats=key_beats or [],
    )


def _blueprint(
    segment_id: str,
    *,
    mode: BlueprintMode = BlueprintMode.RECONSTRUCT,
    overrides: dict[ReferencePatternDimension, BlueprintDimensionState] | None = None,
    relationship_mode: BlueprintMode = BlueprintMode.RECONSTRUCT,
    relationships: list[BlueprintRelationship] | None = None,
) -> ReferenceBlueprintState:
    dimensions = {
        dimension: _dimension(segment_id, mode=mode)
        for dimension in DIMENSIONS
    }
    dimensions.update(overrides or {})
    return ReferenceBlueprintState(
        dimensions=dimensions,
        relationship=BlueprintRelationshipState(
            source="来源人物功能组合",
            mode=relationship_mode,
            author_edits="重新安排利益关系",
            generated_variant="师徒竞争转为跨代合作",
            relationships=relationships or [],
        ),
    )


def test_unrelated_reconstructed_blueprint_is_low_risk() -> None:
    source = _source("segment-a", "旧城工厂里的人们等待一份岗位名单。")

    assessment = assess_blueprint(_blueprint(source.segment_id), [source])

    assert assessment.risk_level == OriginalityRiskLevel.LOW
    assert assessment.score == 0
    assert assessment.threshold_version == THRESHOLD_VERSION
    assert assessment.legal_notice == LEGAL_NOTICE
    assert assessment.checked_dimensions == sorted(DIMENSIONS, key=lambda item: item.value)


def test_long_phrase_plus_preserved_combination_is_blocking_without_raw_excerpt() -> None:
    copied_phrase = "厂长当众撕碎名单逼父亲在所有工友面前低头认错"
    source = _source("segment-a", f"夜班铃响。{copied_phrase}。人群突然安静。")
    era = _dimension(
        source.segment_id,
        mode=BlueprintMode.PRESERVE,
        candidate_summary=copied_phrase,
    )
    blueprint = _blueprint(
        source.segment_id,
        mode=BlueprintMode.PRESERVE,
        overrides={ReferencePatternDimension.ERA: era},
    )

    assessment = assess_blueprint(blueprint, [source])

    assert assessment.risk_level == OriginalityRiskLevel.HIGH
    phrase = next(
        evidence
        for evidence in assessment.evidence
        if evidence.signal == OriginalitySignal.PHRASE_OVERLAP
    )
    assert phrase.source_segment_id == source.segment_id
    assert phrase.source_character_start is not None
    assert phrase.source_character_end is not None
    assert copied_phrase not in assessment.model_dump_json()


def test_common_preserved_structure_is_medium_not_automatically_high() -> None:
    source = _source("segment-a", "主角重生后利用信息差解决危机。")

    assessment = assess_blueprint(
        _blueprint(source.segment_id, mode=BlueprintMode.PRESERVE),
        [source],
    )

    assert assessment.risk_level == OriginalityRiskLevel.MEDIUM
    assert assessment.score == 35
    assert [item.signal for item in assessment.evidence] == [
        OriginalitySignal.MULTI_DIMENSION
    ]


def test_proper_nouns_are_hashed_and_beat_sequence_detects_rewording_boundary() -> None:
    source = _source("segment-a", "南平星火厂与闽北远航社同时公布改制安排。")
    entities = [
        BlueprintNamedEntity(
            kind=BlueprintEntityKind.ORGANIZATION,
            name="南平·星火厂",
            function="旧单位",
        ),
        BlueprintNamedEntity(
            kind=BlueprintEntityKind.ORGANIZATION,
            name="闽北-远航社",
            function="竞争组织",
        ),
    ]
    sequence = ["收到停产通知", "争取保留名额", "公开岗位名单", "对手发动反击"]
    reworded_sequence = ["接到停产通知", "争夺保留名额", "岗位名单公开", "对手开始反击"]
    scene = _dimension(
        source.segment_id,
        entities=entities,
        source_beats=sequence,
        key_beats=reworded_sequence,
    )
    blueprint = _blueprint(
        source.segment_id,
        overrides={ReferencePatternDimension.KEY_SCENE_SEQUENCE: scene},
    )

    assessment = assess_blueprint(blueprint, [source])

    assert assessment.risk_level == OriginalityRiskLevel.MEDIUM
    assert {item.signal for item in assessment.evidence} == {
        OriginalitySignal.PROPER_NOUN,
        OriginalitySignal.BEAT_SEQUENCE,
    }
    serialized = assessment.model_dump_json()
    assert "南平星火厂" not in serialized
    assert "闽北远航社" not in serialized


def test_preserved_relationship_isomorphism_combines_with_multiple_dimensions() -> None:
    source = _source("segment-a", "常见的创业竞争与家庭选择。")
    preserved = {
        dimension: _dimension(source.segment_id, mode=BlueprintMode.PRESERVE)
        for dimension in DIMENSIONS[:3]
    }
    relationships = [
        BlueprintRelationship(left_role="主角", right_role="导师", relation="依赖与超越"),
        BlueprintRelationship(left_role="主角", right_role="对手", relation="竞争资源"),
        BlueprintRelationship(left_role="导师", right_role="对手", relation="旧怨"),
    ]

    assessment = assess_blueprint(
        _blueprint(
            source.segment_id,
            overrides=preserved,
            relationship_mode=BlueprintMode.PRESERVE,
            relationships=relationships,
        ),
        [source],
    )

    assert assessment.risk_level == OriginalityRiskLevel.MEDIUM
    assert {item.signal for item in assessment.evidence} == {
        OriginalitySignal.MULTI_DIMENSION,
        OriginalitySignal.CHARACTER_COMBINATION,
    }


def test_partial_edit_rechecks_only_changed_dimension_and_reuses_other_evidence() -> None:
    copied_phrase = "他提前封存全部账册让对手无法销毁关键证据"
    source = _source("segment-a", copied_phrase)
    era = _dimension(source.segment_id, candidate_summary=copied_phrase)
    first_blueprint = _blueprint(
        source.segment_id,
        overrides={ReferencePatternDimension.ERA: era},
    )
    first = assess_blueprint(first_blueprint, [source])
    changed = _dimension(source.segment_id, candidate_summary="重新设计的家庭目标")
    second_blueprint = _blueprint(
        source.segment_id,
        overrides={
            ReferencePatternDimension.ERA: era,
            ReferencePatternDimension.CORE_DESIRE: changed,
        },
    )

    second = assess_blueprint(
        second_blueprint,
        [source],
        changed_dimensions={ReferencePatternDimension.CORE_DESIRE},
        relationship_changed=False,
        previous=first,
    )

    assert second.checked_dimensions == [ReferencePatternDimension.CORE_DESIRE]
    assert any(
        item.dimension == ReferencePatternDimension.ERA
        and item.signal == OriginalitySignal.PHRASE_OVERLAP
        for item in second.evidence
    )
