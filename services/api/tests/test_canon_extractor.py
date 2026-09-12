from app.canon_reconciliation.extractor import (
    extract_canon_candidates,
    extract_preference_candidates,
    text_sha256,
)


def test_extracts_evidence_with_python_code_point_offsets() -> None:
    body = "🌙𠀀剑鸣。沈砚得到三枚灵石，并突破炼气二层。"

    candidates = extract_canon_candidates(body)

    assert {item.kind for item in candidates} >= {
        "resource_state",
        "progression",
        "timeline_event",
    }
    for item in candidates:
        evidence = item.evidence
        assert body[evidence.start_char : evidence.end_char] == evidence.excerpt
        assert len(text_sha256(evidence.excerpt)) == 64


def test_four_genre_goldens_produce_relevant_typed_candidates() -> None:
    samples = {
        "eastern_fantasy": (
            "陆沉耗尽三枚灵石，终于突破筑基境界。",
            {"resource_state", "progression"},
        ),
        "western_fantasy": (
            "艾琳进入白塔，发现禁咒需要献出金币，随后与银盾骑士结盟。",
            {"location_state", "character_knowledge", "resource_state", "relationship"},
        ),
        "historical_rebirth": (
            "沈砚记得1998年的洪水会提前到来，这个秘密尚未告诉县令。",
            {"future_knowledge", "story_thread"},
        ),
        "urban_rebirth": (
            "林川得知旧厂订单被截走，决定带着父亲离开南平。",
            {"character_knowledge", "character_state", "location_state", "resource_state"},
        ),
    }

    for body, expected in samples.values():
        assert {item.kind for item in extract_canon_candidates(body)} >= expected


def test_preference_extraction_keeps_only_metrics_and_compact_rules() -> None:
    candidate = "他想了很久。\n" + "这件事情其实需要从很多年前慢慢说起。" * 8
    final = "他抬眼。\n“现在就做。”"

    preferences = extract_preference_candidates(candidate, final)

    assert preferences
    assert {item.dimension for item in preferences} >= {"pacing", "paragraphing"}
    for item in preferences:
        assert len(item.compact_rule) < 100
        assert candidate not in str(item.comparison_metrics)
        assert final not in str(item.comparison_metrics)


def test_identical_ai_candidate_does_not_invent_author_preference() -> None:
    body = "风从旧站台吹过。"

    assert extract_preference_candidates(body, body) == []
