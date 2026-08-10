from app.models import BookBlueprint, BookBlueprintField, DirectorRegenerationImpact

DEPENDENCIES: dict[BookBlueprintField, set[BookBlueprintField]] = {
    BookBlueprintField.TITLE: set(),
    BookBlueprintField.GENRE: {
        BookBlueprintField.TARGET_AUDIENCE,
        BookBlueprintField.CORE_SELLING_POINTS,
        BookBlueprintField.RESOURCE_GROWTH,
    },
    BookBlueprintField.REBIRTH_YEAR: {
        BookBlueprintField.DIVERGENCE_POINT,
        BookBlueprintField.RESOURCE_GROWTH,
    },
    BookBlueprintField.REBIRTH_LOCATION: {
        BookBlueprintField.DIVERGENCE_POINT,
        BookBlueprintField.RELATIONSHIP_DESIGN,
    },
    BookBlueprintField.TARGET_AUDIENCE: {
        BookBlueprintField.CORE_SELLING_POINTS,
        BookBlueprintField.LONG_TERM_PROMISE,
    },
    BookBlueprintField.CORE_SELLING_POINTS: {
        BookBlueprintField.LONG_TERM_PROMISE,
        BookBlueprintField.RESOURCE_GROWTH,
    },
    BookBlueprintField.CORE_DESIRE: {
        BookBlueprintField.PROTAGONIST_ARC,
        BookBlueprintField.ENDING_DIRECTION,
    },
    BookBlueprintField.DIVERGENCE_POINT: {
        BookBlueprintField.CORE_DESIRE,
        BookBlueprintField.PROTAGONIST_ARC,
        BookBlueprintField.RESOURCE_GROWTH,
    },
    BookBlueprintField.LONG_TERM_PROMISE: {
        BookBlueprintField.ENDING_DIRECTION,
    },
    BookBlueprintField.ENDING_DIRECTION: {
        BookBlueprintField.PROTAGONIST_ARC,
    },
    BookBlueprintField.PROTAGONIST_ARC: set(),
    BookBlueprintField.RESOURCE_GROWTH: set(),
    BookBlueprintField.RELATIONSHIP_DESIGN: {
        BookBlueprintField.PROTAGONIST_ARC,
    },
}


def _transitive_dependants(target: BookBlueprintField) -> set[BookBlueprintField]:
    discovered: set[BookBlueprintField] = set()
    pending = list(DEPENDENCIES[target])
    while pending:
        field = pending.pop()
        if field in discovered:
            continue
        discovered.add(field)
        pending.extend(DEPENDENCIES[field])
    return discovered


def regeneration_impact(
    blueprint: BookBlueprint,
    target: BookBlueprintField,
) -> DirectorRegenerationImpact:
    downstream = _transitive_dependants(target)
    ordered = [field for field in BookBlueprintField if field in downstream]
    return DirectorRegenerationImpact(
        target_field=target,
        directly_affected=[field for field in BookBlueprintField if field in DEPENDENCIES[target]],
        downstream_affected=ordered,
        locked_conflicts=[field for field in ordered if blueprint.locks[field]],
        will_mark_plan_stale=target not in {BookBlueprintField.TITLE},
    )
