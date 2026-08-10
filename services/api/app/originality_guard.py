import hashlib
import json
import unicodedata
from collections import Counter
from collections.abc import Iterable
from difflib import SequenceMatcher

from app.models import (
    BlueprintMode,
    OriginalityAssessment,
    OriginalityEvidence,
    OriginalityRiskLevel,
    OriginalitySignal,
    ReferenceBlueprintState,
    ReferencePatternDimension,
)
from app.reference_lab import ReferenceAnalysisInput

THRESHOLD_VERSION = "originality-rules-v1"
LEGAL_NOTICE = "原创性风险提示用于创作风控，不是法律结论。"
_PHRASE_SEED = 8
_COMMON_TROPE_PHRASES = {
    "重生改变命运",
    "利用信息差",
    "一步一步成长",
    "解决眼前危机",
    "留下新的悬念",
    "人物关系发生变化",
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalized(value: str) -> str:
    return "".join(
        character.casefold()
        for character in unicodedata.normalize("NFKC", value)
        if character.isalnum()
    )


def _normalized_with_positions(value: str) -> tuple[str, list[int]]:
    characters: list[str] = []
    positions: list[int] = []
    for index, source_character in enumerate(value):
        for character in unicodedata.normalize("NFKC", source_character):
            if character.isalnum():
                characters.append(character.casefold())
                positions.append(index)
    return "".join(characters), positions


def _longest_seeded_overlap(candidate: str, source: str) -> tuple[int, int]:
    candidate = _normalized(candidate)
    source = _normalized(source)
    if len(candidate) < _PHRASE_SEED or len(source) < _PHRASE_SEED:
        return 0, -1
    candidate_seeds: dict[str, list[int]] = {}
    for index in range(len(candidate) - _PHRASE_SEED + 1):
        candidate_seeds.setdefault(candidate[index:index + _PHRASE_SEED], []).append(index)
    best_length = 0
    best_source_start = -1
    for source_start in range(len(source) - _PHRASE_SEED + 1):
        seed = source[source_start:source_start + _PHRASE_SEED]
        candidate_starts = candidate_seeds.get(seed)
        if not candidate_starts:
            continue
        for candidate_start in candidate_starts[:12]:
            length = _PHRASE_SEED
            while (
                candidate_start + length < len(candidate)
                and source_start + length < len(source)
                and candidate[candidate_start + length] == source[source_start + length]
            ):
                length += 1
            if length > best_length:
                best_length = length
                best_source_start = source_start
    return best_length, best_source_start


def _phrase_score(length: int) -> int:
    if length >= 24:
        return 50
    if length >= 16:
        return 35
    if length >= 10:
        return 18
    return 0


def _fingerprint(*values: object) -> str:
    return hashlib.sha256(_canonical_json(values).encode()).hexdigest()


def _evidence(
    *,
    signal: OriginalitySignal,
    score: int,
    summary: str,
    dimension: ReferencePatternDimension | None = None,
    source: ReferenceAnalysisInput | None = None,
    source_start: int | None = None,
    source_end: int | None = None,
    fingerprint_values: tuple[object, ...],
) -> OriginalityEvidence:
    return OriginalityEvidence(
        signal=signal,
        score=score,
        summary=summary,
        dimension=dimension,
        source_segment_id=source.segment_id if source is not None else None,
        source_character_start=(
            source.start_char + source_start
            if source is not None and source_start is not None else None
        ),
        source_character_end=(
            source.start_char + source_end
            if source is not None and source_end is not None else None
        ),
        evidence_sha256=_fingerprint(*fingerprint_values),
    )


def _best_phrase_evidence(
    dimension: ReferencePatternDimension,
    candidate_fields: Iterable[str],
    sources: list[ReferenceAnalysisInput],
) -> OriginalityEvidence | None:
    best: tuple[int, int, ReferenceAnalysisInput, str] | None = None
    for candidate in candidate_fields:
        normalized_candidate = _normalized(candidate)
        if normalized_candidate in _COMMON_TROPE_PHRASES:
            continue
        for source in sources:
            overlap, normalized_start = _longest_seeded_overlap(candidate, source.content)
            if best is None or overlap > best[0]:
                best = (overlap, normalized_start, source, normalized_candidate)
    if best is None:
        return None
    overlap, normalized_start, source, normalized_candidate = best
    score = _phrase_score(overlap)
    if score == 0:
        return None
    _, positions = _normalized_with_positions(source.content)
    if normalized_start < 0 or normalized_start >= len(positions):
        return None
    raw_start = positions[normalized_start]
    normalized_end = min(normalized_start + overlap - 1, len(positions) - 1)
    raw_end = positions[normalized_end] + 1
    return _evidence(
        signal=OriginalitySignal.PHRASE_OVERLAP,
        score=score,
        summary=f"候选蓝图与来源存在 {overlap} 字规范化连续重合；报告不保存来源原句。",
        dimension=dimension,
        source=source,
        source_start=raw_start,
        source_end=raw_end,
        fingerprint_values=(dimension.value, normalized_candidate, source.segment_id, raw_start, raw_end),
    )


def _proper_noun_evidence(
    dimension: ReferencePatternDimension,
    names: list[str],
    sources: list[ReferenceAnalysisInput],
) -> OriginalityEvidence | None:
    collisions: list[tuple[str, ReferenceAnalysisInput, int, int]] = []
    for name in names:
        normalized_name = _normalized(name)
        if len(normalized_name) < 2:
            continue
        for source in sources:
            normalized_source, positions = _normalized_with_positions(source.content)
            index = normalized_source.find(normalized_name)
            if index < 0:
                continue
            raw_start = positions[index]
            raw_end = positions[min(index + len(normalized_name) - 1, len(positions) - 1)] + 1
            collisions.append((normalized_name, source, raw_start, raw_end))
            break
    if not collisions:
        return None
    score = 25 if len(collisions) >= 2 else 12
    name, source, raw_start, raw_end = collisions[0]
    return _evidence(
        signal=OriginalitySignal.PROPER_NOUN,
        score=score,
        summary=f"检测到 {len(collisions)} 个候选专名与来源碰撞；报告只保存哈希和位置。",
        dimension=dimension,
        source=source,
        source_start=raw_start,
        source_end=raw_end,
        fingerprint_values=(dimension.value, sorted(item[0] for item in collisions)),
    )


def _beat_similarity(source_beats: list[str], candidate_beats: list[str]) -> float:
    source = [_normalized(item) for item in source_beats if _normalized(item)]
    candidate = [_normalized(item) for item in candidate_beats if _normalized(item)]
    if len(source) < 3 or len(candidate) < 3:
        return 0.0
    lengths = [[0] * (len(candidate) + 1) for _ in range(len(source) + 1)]
    for source_index, source_beat in enumerate(source, start=1):
        for candidate_index, candidate_beat in enumerate(candidate, start=1):
            if _beat_equivalent(source_beat, candidate_beat):
                lengths[source_index][candidate_index] = (
                    lengths[source_index - 1][candidate_index - 1] + 1
                )
            else:
                lengths[source_index][candidate_index] = max(
                    lengths[source_index - 1][candidate_index],
                    lengths[source_index][candidate_index - 1],
                )
    return lengths[-1][-1] / max(len(source), len(candidate))


def _beat_equivalent(source: str, candidate: str) -> bool:
    if source == candidate:
        return True
    if min(len(source), len(candidate)) < 4:
        return False
    sequence_ratio = SequenceMatcher(a=source, b=candidate, autojunk=False).ratio()
    source_counts = Counter(source)
    candidate_counts = Counter(candidate)
    shared_characters = sum((source_counts & candidate_counts).values())
    character_overlap = shared_characters / max(len(source), len(candidate))
    return sequence_ratio >= 0.6 or character_overlap >= 0.65


def _dimension_evidence(
    dimension: ReferencePatternDimension,
    blueprint: ReferenceBlueprintState,
    sources_by_id: dict[str, ReferenceAnalysisInput],
) -> list[OriginalityEvidence]:
    state = blueprint.dimensions[dimension]
    sources = [
        sources_by_id[source_id]
        for source_id in state.source.source_segment_ids
        if source_id in sources_by_id
    ]
    evidence: list[OriginalityEvidence] = []
    phrase = _best_phrase_evidence(
        dimension,
        (state.generated_variant.summary, state.generated_variant.transferable_logic),
        sources,
    )
    if phrase is not None:
        evidence.append(phrase)
    proper_noun = _proper_noun_evidence(
        dimension,
        [entity.name for entity in state.named_entities],
        sources,
    )
    if proper_noun is not None:
        evidence.append(proper_noun)
    similarity = _beat_similarity(state.source_beats, state.key_beats)
    beat_score = 35 if similarity >= 0.8 else 20 if similarity >= 0.6 else 0
    if beat_score:
        evidence.append(_evidence(
            signal=OriginalitySignal.BEAT_SEQUENCE,
            score=beat_score,
            summary=f"关键场景节拍顺序相似度为 {round(similarity * 100)}%。",
            dimension=dimension,
            fingerprint_values=(dimension.value, state.source_beats, state.key_beats),
        ))
    return evidence


def _global_evidence(blueprint: ReferenceBlueprintState) -> list[OriginalityEvidence]:
    evidence: list[OriginalityEvidence] = []
    preserved = sum(
        state.mode == BlueprintMode.PRESERVE for state in blueprint.dimensions.values()
    )
    multi_score = 35 if preserved >= 5 else 20 if preserved >= 3 else 0
    if multi_score:
        evidence.append(_evidence(
            signal=OriginalitySignal.MULTI_DIMENSION,
            score=multi_score,
            summary=f"最终组合保留了 {preserved} 个来源维度；常见单一套路不会因此单独判高风险。",
            fingerprint_values=("preserved_dimensions", preserved),
        ))
    relationships = blueprint.relationship.relationships
    if blueprint.relationship.mode == BlueprintMode.PRESERVE and len(relationships) >= 2:
        relation_score = 25 if len(relationships) >= 3 else 15
        evidence.append(_evidence(
            signal=OriginalitySignal.CHARACTER_COMBINATION,
            score=relation_score,
            summary=f"人物关系组合保留了 {len(relationships)} 条来源角色功能，需要显式重组。",
            fingerprint_values=(
                "relationships",
                sorted(
                    (item.left_role, item.right_role, item.relation)
                    for item in relationships
                ),
            ),
        ))
    return evidence


def assess_blueprint(
    blueprint: ReferenceBlueprintState,
    sources: list[ReferenceAnalysisInput],
    *,
    changed_dimensions: set[ReferencePatternDimension] | None = None,
    relationship_changed: bool = True,
    previous: OriginalityAssessment | None = None,
) -> OriginalityAssessment:
    all_dimensions = set(blueprint.dimensions)
    checked_dimensions = all_dimensions if changed_dimensions is None else changed_dimensions
    if not checked_dimensions <= all_dimensions:
        raise ValueError("changed_dimensions contains unavailable blueprint dimensions")
    sources_by_id = {source.segment_id: source for source in sources}
    evidence: list[OriginalityEvidence] = []
    if previous is not None and changed_dimensions is not None:
        evidence.extend(
            item
            for item in previous.evidence
            if (
                item.dimension is not None
                and item.dimension not in changed_dimensions
            ) or (
                item.signal == OriginalitySignal.CHARACTER_COMBINATION
                and not relationship_changed
            )
        )
    for dimension in sorted(checked_dimensions, key=lambda item: item.value):
        evidence.extend(_dimension_evidence(dimension, blueprint, sources_by_id))
    evidence.extend(_global_evidence(blueprint))
    score = min(100, sum(item.score for item in evidence))
    has_critical_phrase = any(
        item.signal == OriginalitySignal.PHRASE_OVERLAP and item.score >= 50
        for item in evidence
    )
    has_combination_signal = any(
        item.signal in {
            OriginalitySignal.MULTI_DIMENSION,
            OriginalitySignal.PROPER_NOUN,
            OriginalitySignal.BEAT_SEQUENCE,
            OriginalitySignal.CHARACTER_COMBINATION,
        }
        and item.score >= 20
        for item in evidence
    )
    risk_level = (
        OriginalityRiskLevel.HIGH
        if score >= 70 or (has_critical_phrase and has_combination_signal)
        else OriginalityRiskLevel.MEDIUM
        if score >= 35
        else OriginalityRiskLevel.LOW
    )
    source_segment_ids = sorted({
        source_id
        for state in blueprint.dimensions.values()
        for source_id in state.source.source_segment_ids
    })
    input_sha256 = hashlib.sha256(_canonical_json({
        "blueprint": blueprint.model_dump(mode="json"),
        "source_hashes": {
            source.segment_id: hashlib.sha256(source.content.encode()).hexdigest()
            for source in sources
            if source.segment_id in source_segment_ids
        },
        "threshold_version": THRESHOLD_VERSION,
    }).encode()).hexdigest()
    return OriginalityAssessment(
        risk_level=risk_level,
        score=score,
        threshold_version=THRESHOLD_VERSION,
        checked_dimensions=sorted(checked_dimensions, key=lambda item: item.value),
        evidence=evidence,
        source_segment_ids=source_segment_ids,
        input_sha256=input_sha256,
        legal_notice=LEGAL_NOTICE,
    )
