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
        finding.signal == SceneOriginalitySignal.ORDERED_SEQUENCE
        for finding in assessment.findings
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
