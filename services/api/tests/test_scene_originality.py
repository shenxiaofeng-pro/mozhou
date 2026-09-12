import pytest

from app.models import (
    AppliedReferenceDimension,
    BlueprintDimensionState,
    BlueprintMode,
    BlueprintRelationshipState,
    OriginalityRiskLevel,
    ReferenceBlueprintState,
    ReferenceDimensionSynthesis,
    ReferencePatternDimension,
    SceneOriginalitySignal,
)
from app.reference_lab import ReferenceAnalysisInput
from app.scene_originality import LEGAL_NOTICE, THRESHOLD_VERSION, assess_scene_plot_graph


def _source(work_id: str, segment_id: str, content: str) -> ReferenceAnalysisInput:
    return ReferenceAnalysisInput(
        work_id=work_id,
        work_title=f"作品-{work_id}",
        segment_id=segment_id,
        ordinal=0,
        start_char=0,
        end_char=len(content),
        chapter_start="第一章",
        chapter_end="第十章",
        content=content,
    )


def _blueprint(source_beats: list[str], candidate_beats: list[str]) -> ReferenceBlueprintState:
    segment_ids = ["segment-a", "segment-b"]
    return ReferenceBlueprintState(
        dimensions={
            ReferencePatternDimension.KEY_SCENE_SEQUENCE: BlueprintDimensionState(
                source=ReferenceDimensionSynthesis(
                    summary="来源场景仅以抽象节拍参与检测",
                    source_segment_ids=segment_ids,
                    transferable_logic="调查、取得证物、公开事实、引发反击",
                    adaptation_risk="避免复用关键场景的顺序与因果链",
                ),
                mode=BlueprintMode.RECONSTRUCT,
                author_edits="改换场景和人物",
                generated_variant=AppliedReferenceDimension(
                    summary="候选场景顺序",
                    transferable_logic="用新的行业条件推进",
                ),
                source_beats=source_beats,
                key_beats=candidate_beats,
            )
        },
        relationship=BlueprintRelationshipState(
            source="掌权者压制调查者，亲属因证物倒戈",
            mode=BlueprintMode.RECONSTRUCT,
            author_edits="改成合作关系",
            generated_variant="同行先合作再因利益分开",
        ),
    )


def test_reworded_same_scene_chain_is_high_risk_without_source_prose() -> None:
    source_beats = [
        "主角调查仓库并查明名单去向",
        "主角从父亲手中获得关键账本",
        "主角在大会上当众揭露厂长",
        "厂长倒戈的下属公开证据完成反击",
    ]
    candidate_beats = [
        "主人公追查库房，摸清名册流向",
        "主人公从家人处拿到关键文件",
        "主人公在会上公开主管的问题",
        "领导的下属反水并公布凭证，完成抗衡",
    ]
    sources = [
        _source("work-a", "segment-a", "这是不应出现在报告里的作品 A 原文。"),
        _source("work-b", "segment-b", "这是不应出现在报告里的作品 B 原文。"),
    ]

    assessment = assess_scene_plot_graph(_blueprint(source_beats, candidate_beats), sources)

    assert assessment.risk_level == OriginalityRiskLevel.HIGH
    assert assessment.threshold_version == THRESHOLD_VERSION
    assert assessment.source_work_count == 2
    assert assessment.legal_notice == LEGAL_NOTICE
    assert any(
        finding.signal == SceneOriginalitySignal.ORDERED_SEQUENCE for finding in assessment.findings
    )
    serialized = assessment.model_dump_json()
    assert "作品 A 原文" not in serialized
    assert "作品 B 原文" not in serialized
    assert all(len(item.evidence_sha256) == 64 for item in assessment.findings)


def test_reordered_generic_scenes_are_below_high_risk() -> None:
    source_beats = [
        "调查市场价格",
        "获得一份合同",
        "与竞争者谈判",
        "公开交易结果",
    ]
    candidate_beats = [
        "公开项目结果",
        "与伙伴商量合作",
        "调查新的客户需求",
        "失去一次普通机会",
    ]

    assessment = assess_scene_plot_graph(
        _blueprint(source_beats, candidate_beats),
        [_source("work-a", "segment-a", "普通创业故事。")],
    )

    assert assessment.risk_level != OriginalityRiskLevel.HIGH
    assert assessment.score < 70


def test_candidate_graph_contains_only_candidate_labels() -> None:
    source_beats = ["调查旧案", "取得证据"]
    candidate_beats = ["核查供应链", "拿到采购凭证"]

    assessment = assess_scene_plot_graph(
        _blueprint(source_beats, candidate_beats),
        [_source("work-a", "segment-a", "来源原文不能复制。")],
    )

    assert [node.label for node in assessment.candidate_graph.nodes] == candidate_beats
    assert [edge.relation for edge in assessment.candidate_graph.edges] == ["resource_gain"]


def test_common_fantasy_motif_is_low_risk_even_when_order_matches() -> None:
    """A genre convention is not a distinctive plot graph by itself."""

    generic_chain = [
        "主角受到欺辱",
        "主角意外获得力量",
        "主角修炼升级",
        "主角反击敌人",
    ]

    assessment = assess_scene_plot_graph(
        _blueprint(generic_chain, generic_chain),
        [_source("work-a", "segment-a", "来源原文不得进入检测结果。")],
    )

    assert assessment.risk_level == OriginalityRiskLevel.LOW
    assert assessment.score < 38
    assert all(
        finding.signal != SceneOriginalitySignal.ORDERED_SEQUENCE for finding in assessment.findings
    )


@pytest.mark.parametrize(
    ("source_beats", "candidate_beats", "expected_terms", "expected_relations"),
    [
        (
            [
                "外门弟子耗用三枚灵石冲击筑基境",
                "破境失败会折损十年寿元并灼伤经脉",
                "宗门夺走灵脉后迫使师兄背叛",
                "主角燃尽本命剑封住妖丹",
            ],
            [
                "杂役耗尽三块灵石突破筑基",
                "晋升代价是损失十载寿命并伤及经络",
                "门派封锁灵脉，逼同门倒戈",
                "主人公牺牲本命剑封印妖丹",
            ],
            {"境界提升", "修炼资源", "能力代价", "阵营组织", "资源封锁"},
            {"ability_cost", "resource_lock"},
        ),
        (
            [
                "半精灵加入银徽教会并学习血契禁咒",
                "每次施法都会献出一段记忆",
                "矮人公会封锁魔晶供应",
                "龙裔身份公开后盟友背叛",
            ],
            [
                "混血精灵归附神殿，掌握血契魔法",
                "每回施术都失去一段记忆",
                "矮人行会断供魔晶",
                "龙族血脉被揭露后同伴倒戈",
            ],
            {"魔法施放", "能力代价", "阵营组织", "种族身份", "资源封锁"},
            {"ability_cost", "resource_lock", "identity_reveal"},
        ),
    ],
    ids=["eastern-fantasy-progression-cost", "western-fantasy-magic-faction-race"],
)
def test_distinctive_fantasy_combinations_block_after_rewording(
    source_beats: list[str],
    candidate_beats: list[str],
    expected_terms: set[str],
    expected_relations: set[str],
) -> None:
    sources = [
        _source("work-a", "segment-a", "作品 A 私有原文标记。"),
        _source("work-b", "segment-b", "作品 B 私有原文标记。"),
    ]

    assessment = assess_scene_plot_graph(
        _blueprint(source_beats, candidate_beats),
        sources,
    )

    assert assessment.risk_level == OriginalityRiskLevel.HIGH
    assert expected_relations <= {edge.relation for edge in assessment.candidate_graph.edges}
    assert expected_terms <= {
        term for node in assessment.candidate_graph.nodes for term in node.semantic_terms
    }
    assert {
        SceneOriginalitySignal.ORDERED_SEQUENCE,
        SceneOriginalitySignal.CAUSAL_GRAPH,
    } <= {finding.signal for finding in assessment.findings}
    assert all(finding.source_segment_ids for finding in assessment.findings)
    serialized = assessment.model_dump_json()
    assert "作品 A 私有原文标记" not in serialized
    assert "作品 B 私有原文标记" not in serialized
