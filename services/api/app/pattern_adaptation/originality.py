from __future__ import annotations

import json
import re
import unicodedata
from enum import StrEnum
from hashlib import sha256
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.models import BookBlueprintContent, OriginalityRiskLevel
from app.writing_patterns.models import ModelSafeWritingPatternProfile

THRESHOLD_VERSION: Final = "writing-pattern-originality-v1"

_CLAUSE_SPLIT_RE = re.compile(r"[\n\r。！？!?;；，,:>→、]+")
_NORMALIZE_RE = re.compile(r"[^0-9a-z㐀-鿿]+")
_CHINESE_RE = re.compile(r"[㐀-鿿]+")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PROPER_NOUN_SUFFIXES: Final = (
    "宗",
    "门",
    "派",
    "宫",
    "阁",
    "盟",
    "会",
    "庭",
    "教",
    "国",
    "邦",
    "城",
    "域",
    "塔",
    "院",
    "府",
    "族",
    "军",
    "团",
    "印",
    "剑",
    "戒",
    "典",
    "书",
)
_GENERIC_PROPER_NOUNS: Final = {
    "主角",
    "导师",
    "盟友",
    "敌人",
    "家族",
    "王国",
    "宗门",
    "公会",
    "教会",
    "资源",
}
_SEMANTIC_GROUPS: Final[dict[str, tuple[str, ...]]] = {
    "join": ("加入", "入门", "投身", "归附", "进入"),
    "grant": ("授予", "赐予", "传承", "获得", "拿到"),
    "cast": ("施术", "催动", "发动", "使用能力", "运用能力"),
    "cost": ("代价", "消耗", "失去", "反噬", "牺牲", "损伤"),
    "pursuit": ("追捕", "追杀", "围剿", "通缉", "逼迫"),
    "betrayal": ("背叛", "倒戈", "出卖", "反水"),
    "resource_lock": ("封锁资源", "断供", "断绝资源", "夺走资源"),
    "resource_gain": ("资源增长", "获得资源", "夺得资源", "资源入手"),
    "destroy": ("摧毁", "破坏", "焚毁", "舍弃"),
    "freedom": ("自由", "摆脱控制", "脱离束缚"),
    "mentor": ("导师", "师父", "引路人"),
    "ally": ("盟友", "同伴", "战友", "合作者"),
    "protection": ("庇护", "保护", "救助", "护送"),
    "authority": ("圣庭", "王权", "教会", "官府", "统治者"),
    "dependence": ("依赖", "依附", "受制于", "听命"),
}
_RELATIONSHIP_FEATURES: Final = frozenset(
    {"mentor", "ally", "protection", "authority", "dependence", "betrayal"}
)
_CAUSAL_RESOURCE_FEATURES: Final = frozenset(
    {
        "grant",
        "cast",
        "cost",
        "pursuit",
        "betrayal",
        "resource_lock",
        "resource_gain",
        "destroy",
        "freedom",
    }
)


class PatternOriginalitySignal(StrEnum):
    PROPER_NOUN_LIKE = "proper_noun_like"
    RELATIONSHIP_FUNCTION = "relationship_function"
    ORDERED_SCENE = "ordered_scene"
    CAUSAL_RESOURCE_COMBINATION = "causal_resource_combination"
    MULTI_SOURCE_AGGREGATION = "multi_source_aggregation"


class PatternOriginalityFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal: PatternOriginalitySignal
    score: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=300)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PatternOriginalityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_level: OriginalityRiskLevel
    score: int = Field(ge=0, le=100)
    findings: list[PatternOriginalityFinding] = Field(max_length=5)
    threshold_version: str = Field(min_length=1, max_length=80)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _normalize(value: str) -> str:
    return _NORMALIZE_RE.sub("", unicodedata.normalize("NFKC", value).lower())


def _clauses(value: str) -> list[str]:
    return [part for item in _CLAUSE_SPLIT_RE.split(value) if (part := _normalize(item))]


def _features(value: str) -> frozenset[str]:
    normalized = _normalize(value)
    return frozenset(
        feature
        for feature, variants in _SEMANTIC_GROUPS.items()
        if any(_normalize(variant) in normalized for variant in variants)
    )


def _proper_noun_hashes(value: str) -> frozenset[str]:
    candidates: set[str] = set()
    for run in _CHINESE_RE.findall(unicodedata.normalize("NFKC", value)):
        for end in range(2, len(run) + 1):
            if run[end - 1] not in _PROPER_NOUN_SUFFIXES:
                continue
            for length in range(2, min(6, end) + 1):
                candidate = run[end - length : end]
                if candidate not in _GENERIC_PROPER_NOUNS:
                    candidates.add(candidate)
    return frozenset(sha256(item.encode("utf-8")).hexdigest() for item in candidates)


def _similarity(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _lcs_ratio(source: list[frozenset[str]], candidate: list[frozenset[str]]) -> float:
    if not source or not candidate:
        return 0.0
    row = [0] * (len(candidate) + 1)
    for source_features in source:
        previous = row[:]
        for index, candidate_features in enumerate(candidate, start=1):
            if _similarity(source_features, candidate_features) >= 0.5:
                row[index] = previous[index - 1] + 1
            else:
                row[index] = max(previous[index], row[index - 1])
    return row[-1] / max(1, min(len(source), len(candidate)))


def _score_overlap(source: frozenset[str], candidate: frozenset[str]) -> int:
    if not source or not candidate:
        return 0
    return round(100 * len(source & candidate) / max(1, len(source)))


def _finding(
    signal: PatternOriginalitySignal,
    score: int,
    summary: str,
    evidence: object,
) -> PatternOriginalityFinding:
    return PatternOriginalityFinding(
        signal=signal,
        score=score,
        summary=summary,
        evidence_sha256=sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    )


def assess_pattern_adaptation_originality(
    profile: ModelSafeWritingPatternProfile,
    blueprint: BookBlueprintContent,
    key_scene_sequence: list[str],
    *,
    source_work_fingerprints: list[str] | None = None,
) -> PatternOriginalityAssessment:
    """Compare an adaptation only with model-safe abstractions.

    The returned report contains scores, counts and one-way evidence fingerprints; it
    deliberately contains neither profile terms nor candidate terms.
    """

    if not key_scene_sequence or any(
        not item.strip() or "\x00" in item for item in key_scene_sequence
    ):
        raise ValueError("抽象关键场景顺序不完整")
    work_fingerprints = sorted(set(source_work_fingerprints or []))
    if any(_SHA256_RE.fullmatch(item) is None for item in work_fingerprints):
        raise ValueError("来源作品指纹无效")

    source_text_by_fingerprint: dict[str, str] = {}
    source_sequences: list[list[frozenset[str]]] = []
    for rule in profile.rules:
        safe_text = f"{rule.transferable_rule}。{rule.adaptation_risk}"
        source_text_by_fingerprint[rule.source_content_sha256] = (
            f"{source_text_by_fingerprint.get(rule.source_content_sha256, '')}。{safe_text}"
        )
        sequence = [
            features
            for clause in _clauses(rule.transferable_rule)
            if (features := _features(clause))
        ]
        if sequence:
            source_sequences.append(sequence)

    source_text = "。".join(source_text_by_fingerprint.values())
    blueprint_values = blueprint.model_dump(mode="json")
    candidate_text = "。".join(
        [
            *(str(value) for value in blueprint_values.values() if not isinstance(value, list)),
            *(
                item
                for value in blueprint_values.values()
                if isinstance(value, list)
                for item in value
            ),
            *key_scene_sequence,
        ]
    )

    source_proper_hashes = _proper_noun_hashes(source_text)
    candidate_proper_hashes = _proper_noun_hashes(candidate_text)
    matched_proper_hashes = sorted(source_proper_hashes & candidate_proper_hashes)
    proper_score = min(100, len(matched_proper_hashes) * 35)

    source_features = _features(source_text)
    candidate_features = _features(candidate_text)
    relationship_source = source_features & _RELATIONSHIP_FEATURES
    relationship_candidate = candidate_features & _RELATIONSHIP_FEATURES
    relationship_score = _score_overlap(relationship_source, relationship_candidate)

    candidate_sequence = [
        features for scene in key_scene_sequence if (features := _features(scene))
    ]
    ordered_score = round(
        100
        * max(
            (_lcs_ratio(sequence, candidate_sequence) for sequence in source_sequences),
            default=0.0,
        )
    )

    causal_source = source_features & _CAUSAL_RESOURCE_FEATURES
    causal_candidate = candidate_features & _CAUSAL_RESOURCE_FEATURES
    causal_score = _score_overlap(causal_source, causal_candidate)
    if not ({"cost", "resource_lock", "resource_gain"} & causal_source):
        causal_score = min(causal_score, 40)

    source_count = len(work_fingerprints)
    has_abstract_match = any((proper_score, relationship_score, ordered_score, causal_score))
    multi_source_score = 100 if source_count >= 2 and has_abstract_match else 0

    signal_scores = (
        (
            PatternOriginalitySignal.PROPER_NOUN_LIKE,
            proper_score,
            "候选专名与抽象风险词的指纹出现重合。",
        ),
        (
            PatternOriginalitySignal.RELATIONSHIP_FUNCTION,
            relationship_score,
            "人物功能关系的角色与转折组合接近。",
        ),
        (
            PatternOriginalitySignal.ORDERED_SCENE,
            ordered_score,
            "多个抽象场景功能以相近顺序出现。",
        ),
        (
            PatternOriginalitySignal.CAUSAL_RESOURCE_COMBINATION,
            causal_score,
            "冲突因果、资源变化与能力代价的组合接近。",
        ),
        (
            PatternOriginalitySignal.MULTI_SOURCE_AGGREGATION,
            multi_source_score,
            "风险信号在多个独立抽象来源中聚合。",
        ),
    )
    evidence_by_signal: dict[PatternOriginalitySignal, object] = {
        PatternOriginalitySignal.PROPER_NOUN_LIKE: matched_proper_hashes,
        PatternOriginalitySignal.RELATIONSHIP_FUNCTION: {
            "matched_count": len(relationship_source & relationship_candidate),
            "source_count": len(relationship_source),
        },
        PatternOriginalitySignal.ORDERED_SCENE: {
            "candidate_scene_count": len(candidate_sequence),
            "source_sequence_count": len(source_sequences),
        },
        PatternOriginalitySignal.CAUSAL_RESOURCE_COMBINATION: {
            "matched_count": len(causal_source & causal_candidate),
            "source_count": len(causal_source),
        },
        PatternOriginalitySignal.MULTI_SOURCE_AGGREGATION: {
            "work_fingerprint_set_sha256": sha256(
                "\n".join(work_fingerprints).encode("utf-8")
            ).hexdigest(),
            "unique_work_count": source_count,
        },
    }
    findings = [
        _finding(signal, signal_score, summary, evidence_by_signal[signal])
        for signal, signal_score, summary in signal_scores
        if signal_score >= 35
    ]

    score = min(
        100,
        round(
            proper_score * 0.20
            + relationship_score * 0.20
            + ordered_score * 0.25
            + causal_score * 0.25
            + multi_source_score * 0.10
        ),
    )
    risk = (
        OriginalityRiskLevel.HIGH
        if score >= 75
        else OriginalityRiskLevel.MEDIUM
        if score >= 45
        else OriginalityRiskLevel.LOW
    )
    canonical_input = {
        "profile": profile.model_dump(mode="json"),
        "blueprint": blueprint.model_dump(mode="json"),
        "key_scene_sequence": key_scene_sequence,
        "source_work_fingerprints": work_fingerprints,
        "threshold_version": THRESHOLD_VERSION,
    }
    return PatternOriginalityAssessment(
        risk_level=risk,
        score=score,
        findings=findings,
        threshold_version=THRESHOLD_VERSION,
        input_sha256=sha256(
            json.dumps(
                canonical_input,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
    )
