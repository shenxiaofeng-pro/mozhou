from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

CanonKindValue = Literal[
    "character_state",
    "relationship",
    "resource_state",
    "location_state",
    "character_knowledge",
    "future_knowledge",
    "story_thread",
    "progression",
    "timeline_event",
]


@dataclass(frozen=True)
class TextSpan:
    start_char: int
    end_char: int
    excerpt: str


@dataclass(frozen=True)
class ExtractedCanonCandidate:
    kind: CanonKindValue
    subject_key: str
    summary: str
    payload: dict[str, object]
    evidence: TextSpan


@dataclass(frozen=True)
class ExtractedPreferenceCandidate:
    dimension: Literal[
        "pacing",
        "paragraphing",
        "dialogue_density",
        "narrative_distance",
        "tension",
        "sentence_style",
    ]
    compact_rule: str
    confidence: float
    comparison_metrics: dict[str, float | int]


_SENTENCE_PATTERN = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
_NAME_PATTERN = re.compile(r"[\u3400-\u9fffA-Za-z·]{2,12}")
_YEAR_PATTERN = re.compile(r"(?<!\d)((?:18|19|20|21)\d{2})(?!\d)")

_KEYWORDS: dict[CanonKindValue, tuple[str, ...]] = {
    "character_state": ("受伤", "死亡", "失踪", "身份", "成为", "决定", "苏醒"),
    "relationship": ("结盟", "决裂", "背叛", "信任", "敌对", "订婚", "联手"),
    "resource_state": (
        "灵石",
        "丹药",
        "法器",
        "金币",
        "资金",
        "订单",
        "股份",
        "获得",
        "得到",
        "失去",
        "耗尽",
    ),
    "location_state": ("来到", "抵达", "进入", "离开", "占领", "搬到", "逃出"),
    "character_knowledge": ("得知", "发现", "知晓", "明白", "意识到"),
    "future_knowledge": ("前世", "重生", "未来", "预言", "上一世", "记得"),
    "story_thread": ("秘密", "谜团", "追查", "尚未", "伏笔", "暗示", "真相"),
    "progression": ("突破", "晋升", "境界", "修为", "法术", "魔法", "能力", "阶位"),
    "timeline_event": (),
}


def text_sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def sentence_spans(body: str, *, max_excerpt_characters: int = 1_200) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for match in _SENTENCE_PATTERN.finditer(body):
        raw = match.group(0)
        leading = len(raw) - len(raw.lstrip())
        excerpt = raw.strip()
        if not excerpt:
            continue
        start = match.start() + leading
        end = start + min(len(excerpt), max_excerpt_characters)
        exact = body[start:end]
        if exact.strip() and len(exact) >= 2:
            spans.append(TextSpan(start_char=start, end_char=end, excerpt=exact))
    return spans


def _first_name(text: str, *, fallback: str = "主角") -> str:
    match = _NAME_PATTERN.search(text)
    if match is None:
        return fallback
    value = match.group(0)
    for prefix in ("当年", "此时", "随后", "然而", "终于", "突然", "原来"):
        if value.startswith(prefix) and len(value) > len(prefix) + 1:
            value = value[len(prefix) :]
    return value[:12] or fallback


def _two_names(text: str) -> tuple[str, str]:
    names = [match.group(0)[:12] for match in _NAME_PATTERN.finditer(text)]
    if len(names) >= 2:
        return names[0], names[1]
    if names:
        return names[0], "对方"
    return "主角", "对方"


def _keyword(text: str, kind: CanonKindValue, fallback: str) -> str:
    return next((item for item in _KEYWORDS[kind] if item in text), fallback)


def _payload(
    kind: CanonKindValue,
    text: str,
    *,
    default_event_year: int | None,
) -> tuple[str, dict[str, object]]:
    character = _first_name(text)
    if kind == "character_state":
        state = _keyword(text, kind, "状态改变")
        return character, {"character_name": character, "state": state, "change": text}
    if kind == "relationship":
        source, target = _two_names(text)
        relation = _keyword(text, kind, "关系改变")
        return f"{source}→{target}", {
            "source_name": source,
            "target_name": target,
            "relation_type": relation,
            "summary": text,
        }
    if kind == "resource_state":
        resource = _keyword(text, kind, "关键资源")
        delta = next(
            (item for item in ("获得", "得到", "失去", "耗尽", "花费") if item in text),
            "变化",
        )
        return f"{character}:{resource}", {
            "owner_name": character,
            "resource_name": resource,
            "delta": delta,
            "state": text,
        }
    if kind == "location_state":
        movement = _keyword(text, kind, "位置改变")
        location = text.split(movement, 1)[-1].strip("，。！？!?；; ")[:80] or "未命名地点"
        return character, {
            "subject_name": character,
            "location": location,
            "movement": movement,
        }
    if kind == "character_knowledge":
        marker = _keyword(text, kind, "得知")
        knowledge = text.split(marker, 1)[-1].strip("，。！？!?；; ") or text
        return character, {"character_name": character, "knowledge": knowledge}
    if kind == "future_knowledge":
        year_match = _YEAR_PATTERN.search(text)
        return character, {
            "holder_name": character,
            "knowledge": text,
            "confidence": "likely",
            "event_year": int(year_match.group(1)) if year_match else default_event_year,
        }
    if kind == "story_thread":
        marker = _keyword(text, kind, "未决线索")
        return marker, {"title": marker, "status": "open", "summary": text}
    if kind == "progression":
        rank = _keyword(text, kind, "能力变化")
        system = "魔法" if "魔法" in text else "修炼" if any(
            item in text for item in ("境界", "修为", "突破", "灵力")
        ) else "能力"
        return character, {
            "character_name": character,
            "system": system,
            "rank": rank,
            "change": text,
        }
    year_match = _YEAR_PATTERN.search(text)
    return text[:40], {
        "layer": "novel",
        "event_year": int(year_match.group(1)) if year_match else default_event_year,
        "title": text[:80],
        "summary": text,
    }


def extract_canon_candidates(
    body: str,
    *,
    default_event_year: int | None = None,
) -> list[ExtractedCanonCandidate]:
    """Conservative deterministic extraction; every result remains author-gated."""

    spans = sentence_spans(body)
    if not spans:
        return []
    results: list[ExtractedCanonCandidate] = []
    for kind, keywords in _KEYWORDS.items():
        span = spans[0] if kind == "timeline_event" else next(
            (
                item
                for item in spans
                if any(keyword in item.excerpt for keyword in keywords)
            ),
            None,
        )
        if span is None:
            continue
        subject_key, payload = _payload(
            kind,
            span.excerpt,
            default_event_year=default_event_year,
        )
        results.append(
            ExtractedCanonCandidate(
                kind=kind,
                subject_key=subject_key,
                summary=span.excerpt,
                payload=payload,
                evidence=span,
            )
        )
    return results


def _text_metrics(value: str) -> dict[str, float | int]:
    length = len(value)
    paragraphs = [item.strip() for item in value.splitlines() if item.strip()]
    sentences = sentence_spans(value)
    dialogue_characters = sum(
        len(item)
        for item in re.findall(r"[“\"]([^”\"]+)[”\"]", value)
    )
    return {
        "characters": length,
        "paragraphs": len(paragraphs),
        "average_paragraph_characters": round(
            length / max(1, len(paragraphs)),
            3,
        ),
        "average_sentence_characters": round(
            length / max(1, len(sentences)),
            3,
        ),
        "dialogue_ratio": round(dialogue_characters / max(1, length), 4),
        "emphasis_ratio": round(
            sum(value.count(mark) for mark in "！？!?") / max(1, length),
            4,
        ),
    }


def extract_preference_candidates(
    candidate_body: str,
    final_body: str,
) -> list[ExtractedPreferenceCandidate]:
    """Describe editing tendencies as metrics and compact rules, never a historical diff."""

    if candidate_body == final_body:
        return []
    before = _text_metrics(candidate_body)
    after = _text_metrics(final_body)
    metrics: dict[str, float | int] = {
        f"candidate_{key}": value for key, value in before.items()
    }
    metrics.update({f"final_{key}": value for key, value in after.items()})
    length_ratio = int(after["characters"]) / max(1, int(before["characters"]))
    results: list[ExtractedPreferenceCandidate] = []
    if length_ratio <= 0.88:
        results.append(
            ExtractedPreferenceCandidate(
                dimension="pacing",
                compact_rule="在不丢失因果的前提下压缩解释与重复信息，让情节更快进入结果。",
                confidence=0.68,
                comparison_metrics={**metrics, "length_ratio": round(length_ratio, 4)},
            )
        )
    elif length_ratio >= 1.12:
        results.append(
            ExtractedPreferenceCandidate(
                dimension="pacing",
                compact_rule="关键转折需要补足动作、因果与即时反应，不要只用概述跳过。",
                confidence=0.68,
                comparison_metrics={**metrics, "length_ratio": round(length_ratio, 4)},
            )
        )
    paragraph_ratio = float(after["average_paragraph_characters"]) / max(
        1.0,
        float(before["average_paragraph_characters"]),
    )
    if paragraph_ratio <= 0.82:
        results.append(
            ExtractedPreferenceCandidate(
                dimension="paragraphing",
                compact_rule="高信息密度段落要拆短，用段落切换强化动作和读者停顿。",
                confidence=0.62,
                comparison_metrics={**metrics, "paragraph_length_ratio": round(paragraph_ratio, 4)},
            )
        )
    dialogue_delta = float(after["dialogue_ratio"]) - float(before["dialogue_ratio"])
    if abs(dialogue_delta) >= 0.06:
        results.append(
            ExtractedPreferenceCandidate(
                dimension="dialogue_density",
                compact_rule=(
                    "重要冲突优先通过人物对话交锋呈现。"
                    if dialogue_delta > 0
                    else "避免让对白挤占叙事，用动作和结果承载信息。"
                ),
                confidence=0.64,
                comparison_metrics={**metrics, "dialogue_ratio_delta": round(dialogue_delta, 4)},
            )
        )
    sentence_ratio = float(after["average_sentence_characters"]) / max(
        1.0,
        float(before["average_sentence_characters"]),
    )
    if len(results) < 3 and (sentence_ratio <= 0.8 or sentence_ratio >= 1.25):
        results.append(
            ExtractedPreferenceCandidate(
                dimension="sentence_style",
                compact_rule=(
                    "动作与转折处倾向短句，减少多层修饰。"
                    if sentence_ratio < 1
                    else "关键情绪处允许更完整的复句铺陈，但保持主语清晰。"
                ),
                confidence=0.58,
                comparison_metrics={**metrics, "sentence_length_ratio": round(sentence_ratio, 4)},
            )
        )
    return results[:3]
