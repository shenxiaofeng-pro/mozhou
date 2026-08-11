from __future__ import annotations

import json
import re
import unicodedata
from hashlib import sha256
from itertools import pairwise

from app.models import (
    OriginalityRiskLevel,
    ReferenceBlueprintState,
    ReferencePatternDimension,
    SceneGraphEdge,
    SceneGraphNode,
    SceneOriginalityAssessment,
    SceneOriginalityFinding,
    SceneOriginalitySignal,
    ScenePlotGraph,
)
from app.reference_lab import ReferenceAnalysisInput

THRESHOLD_VERSION = "scene-plot-graph-v1"
LEGAL_NOTICE = "场景语义与情节图检测用于创作风控，不是抄袭认定或法律结论。"

_SPLIT_RE = re.compile(r"[\n；;。.!！？?、→>]+")
_NON_WORD_RE = re.compile(r"[^0-9a-z\u3400-\u9fff]+")
_SEMANTIC_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("取得", ("获得", "得到", "拿到", "赢得", "掌握", "夺得", "收购")),
    ("揭示", ("揭露", "曝光", "公开", "公布", "披露", "戳穿", "证明")),
    ("调查", ("调查", "查明", "追查", "摸清", "核查", "查证")),
    ("背叛", ("背叛", "倒戈", "出卖", "反水", "反咬")),
    ("合作", ("合作", "联手", "结盟", "协作", "联合")),
    ("对抗", ("对抗", "反击", "抗衡", "冲突", "争夺", "阻止")),
    ("交换", ("交换", "交易", "谈判", "置换", "议价")),
    ("失去", ("失去", "丢掉", "损失", "被夺", "破产", "失败")),
    ("证物", ("证据", "账本", "名单", "文件", "录音", "凭证")),
    ("公开场合", ("当众", "公开场合", "众人面前", "会上", "现场")),
    ("亲缘", ("父亲", "母亲", "家人", "兄弟", "姐妹", "亲属")),
    ("权力者", ("厂长", "老板", "领导", "官员", "主管", "掌权者")),
)


def _normalize(value: str) -> str:
    return _NON_WORD_RE.sub("", unicodedata.normalize("NFKC", value).lower())


def _terms(value: str) -> set[str]:
    normalized = _normalize(value)
    terms = {
        canonical
        for canonical, variants in _SEMANTIC_GROUPS
        if any(_normalize(variant) in normalized for variant in variants)
    }
    if len(normalized) >= 2:
        terms.update(normalized[index : index + 2] for index in range(len(normalized) - 1))
    return terms


def _semantic_terms(value: str) -> list[str]:
    semantic = [
        canonical
        for canonical, variants in _SEMANTIC_GROUPS
        if any(_normalize(variant) in _normalize(value) for variant in variants)
    ]
    return semantic[:24]


def _edge_relation(source: str, target: str) -> str:
    del source
    target_terms = set(_semantic_terms(target))
    for term, relation in (
        ("失去", "resource_loss"),
        ("取得", "resource_gain"),
        ("背叛", "allegiance_shift"),
        ("合作", "alliance_shift"),
        ("揭示", "disclosure"),
        ("对抗", "conflict_escalation"),
    ):
        if term in target_terms:
            return relation
    return "leads_to"


def _similarity(left: str, right: str) -> float:
    left_terms = _terms(left)
    right_terms = _terms(right)
    if not left_terms or not right_terms:
        return 0.0
    semantic_left = set(_semantic_terms(left))
    semantic_right = set(_semantic_terms(right))
    semantic_union = semantic_left | semantic_right
    semantic_score = (
        len(semantic_left & semantic_right) / len(semantic_union) if semantic_union else 0.0
    )
    ngram_score = len(left_terms & right_terms) / len(left_terms | right_terms)
    return min(1.0, semantic_score * 0.7 + ngram_score * 0.3)


def _candidate_beats(blueprint: ReferenceBlueprintState) -> list[str]:
    scene = blueprint.dimensions.get(ReferencePatternDimension.KEY_SCENE_SEQUENCE)
    if scene is not None:
        beats = [item.strip() for item in scene.key_beats if item.strip()]
        if beats:
            return beats[:40]
        combined = f"{scene.generated_variant.summary}。{scene.generated_variant.transferable_logic}"
        beats = [item.strip() for item in _SPLIT_RE.split(combined) if item.strip()]
        if beats:
            return beats[:40]
    fallback: list[str] = []
    for dimension in blueprint.dimensions.values():
        fallback.extend(
            item.strip()
            for item in _SPLIT_RE.split(dimension.generated_variant.summary)
            if item.strip()
        )
    return fallback[:40]


def _source_beats(blueprint: ReferenceBlueprintState) -> list[tuple[str, list[str]]]:
    results: list[tuple[str, list[str]]] = []
    for dimension in blueprint.dimensions.values():
        beats = [item.strip() for item in dimension.source_beats if item.strip()]
        for beat in beats[:20]:
            results.append((beat, list(dimension.source.source_segment_ids)))
    return results[:120]


def _lcs_ratio(candidate: list[str], sources: list[str]) -> float:
    if not candidate or not sources:
        return 0.0
    rows = [0] * (len(sources) + 1)
    for candidate_beat in candidate:
        previous = rows[:]
        for index, source_beat in enumerate(sources, start=1):
            if _similarity(candidate_beat, source_beat) >= 0.5:
                rows[index] = previous[index - 1] + 1
            else:
                rows[index] = max(previous[index], rows[index - 1])
    return rows[-1] / max(1, min(len(candidate), len(sources)))


def _finding(
    signal: SceneOriginalitySignal,
    score: int,
    summary: str,
    source_segment_ids: list[str],
    fingerprint: object,
) -> SceneOriginalityFinding:
    evidence_sha = sha256(
        json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return SceneOriginalityFinding(
        signal=signal,
        score=score,
        summary=summary,
        source_segment_ids=sorted(set(source_segment_ids)),
        evidence_sha256=evidence_sha,
    )


def assess_scene_plot_graph(
    blueprint: ReferenceBlueprintState,
    sources: list[ReferenceAnalysisInput],
) -> SceneOriginalityAssessment:
    candidate = _candidate_beats(blueprint)
    source_entries = _source_beats(blueprint)
    source_texts = [item[0] for item in source_entries]
    source_ids = sorted({source.segment_id for source in sources})
    work_count = max(1, len({source.work_id for source in sources}))

    nodes = [
        SceneGraphNode(id=f"scene-{index + 1}", label=beat, semantic_terms=_semantic_terms(beat))
        for index, beat in enumerate(candidate)
    ]
    edges = [
        SceneGraphEdge(
            source=nodes[index].id,
            target=nodes[index + 1].id,
            relation=_edge_relation(candidate[index], candidate[index + 1]),
        )
        for index in range(max(0, len(nodes) - 1))
    ]
    graph = ScenePlotGraph(nodes=nodes, edges=edges)

    best_matches: list[tuple[float, int, list[str]]] = []
    for candidate_beat in candidate:
        scored = [
            (_similarity(candidate_beat, source_beat), index, segment_ids)
            for index, (source_beat, segment_ids) in enumerate(source_entries)
        ]
        best_matches.append(max(scored, default=(0.0, -1, []), key=lambda item: item[0]))
    matched = [item for item in best_matches if item[0] >= 0.5]
    semantic_ratio = len(matched) / max(1, len(candidate))
    semantic_score = round(semantic_ratio * 100)
    sequence_ratio = _lcs_ratio(candidate, source_texts)
    sequence_score = round(sequence_ratio * 100)

    consecutive = 0
    for candidate_index, (left, right) in enumerate(pairwise(best_matches)):
        if (
            left[0] >= 0.5
            and right[0] >= 0.5
            and right[1] == left[1] + 1
            and _edge_relation(
                candidate[candidate_index],
                candidate[candidate_index + 1],
            )
            == _edge_relation(source_texts[left[1]], source_texts[right[1]])
        ):
            consecutive += 1
    causal_score = round(100 * consecutive / max(1, len(candidate) - 1))

    source_relationship = blueprint.relationship.source
    candidate_relationship = blueprint.relationship.generated_variant
    relationship_score = round(_similarity(candidate_relationship, source_relationship) * 100)

    findings: list[SceneOriginalityFinding] = []
    matched_source_ids = sorted({sid for _, _, ids in matched for sid in ids})
    if semantic_score >= 35:
        findings.append(
            _finding(
                SceneOriginalitySignal.SEMANTIC_SCENE,
                semantic_score,
                f"{len(matched)}/{max(1, len(candidate))} 个候选场景与来源抽象节拍功能接近；报告未保存来源原句。",
                matched_source_ids,
                [round(score, 3) for score, _, _ in best_matches],
            )
        )
    if sequence_score >= 35:
        findings.append(
            _finding(
                SceneOriginalitySignal.ORDERED_SEQUENCE,
                sequence_score,
                "候选场景的功能顺序与来源节拍序列接近，建议重排触发条件与结果链。",
                matched_source_ids,
                [index for score, index, _ in best_matches if score >= 0.5],
            )
        )
    if causal_score >= 35:
        findings.append(
            _finding(
                SceneOriginalitySignal.CAUSAL_GRAPH,
                causal_score,
                "多个相邻场景保留了相近的因果或资源流向边，建议改变关键决策与代价。",
                matched_source_ids,
                {"consecutive": consecutive, "candidate_count": len(candidate)},
            )
        )
    if relationship_score >= 45:
        relationship_ids = sorted(
            {
                segment_id
                for dimension in blueprint.dimensions.values()
                for segment_id in dimension.source.source_segment_ids
            }
        )
        findings.append(
            _finding(
                SceneOriginalitySignal.CHARACTER_FUNCTION_GRAPH,
                relationship_score,
                "人物功能关系与来源组合接近，建议改写利益依赖、权力方向或背叛条件。",
                relationship_ids,
                {"score": relationship_score},
            )
        )
    if work_count >= 2 and matched_source_ids:
        convergence_score = min(100, 35 + 10 * min(work_count, 6) + semantic_score // 4)
        findings.append(
            _finding(
                SceneOriginalitySignal.MULTI_SOURCE_CONVERGENCE,
                convergence_score,
                f"检测覆盖 {work_count} 本参考作品；相似信号跨来源汇聚时需避免拼接式复用。",
                matched_source_ids,
                {"work_count": work_count, "source_ids": matched_source_ids},
            )
        )

    score = min(
        100,
        round(
            semantic_score * 0.35
            + sequence_score * 0.3
            + causal_score * 0.2
            + relationship_score * 0.15
        ),
    )
    if semantic_score >= 75 and sequence_score >= 65 or score >= 70:
        risk = OriginalityRiskLevel.HIGH
    elif semantic_score >= 40 or sequence_score >= 40 or score >= 38:
        risk = OriginalityRiskLevel.MEDIUM
    else:
        risk = OriginalityRiskLevel.LOW

    canonical_input = {
        "blueprint": blueprint.model_dump(mode="json"),
        "source_fingerprints": [
            {
                "segment_id": source.segment_id,
                "content_sha256": sha256(source.content.encode("utf-8")).hexdigest(),
            }
            for source in sorted(sources, key=lambda item: item.segment_id)
        ],
        "threshold_version": THRESHOLD_VERSION,
    }
    return SceneOriginalityAssessment(
        risk_level=risk,
        score=score,
        threshold_version=THRESHOLD_VERSION,
        candidate_graph=graph,
        findings=findings,
        source_segment_ids=source_ids,
        source_work_count=work_count,
        input_sha256=sha256(
            json.dumps(canonical_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        legal_notice=LEGAL_NOTICE,
    )
