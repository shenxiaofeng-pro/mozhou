import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import pairwise

_CHAPTER_HEADING = re.compile(
    r"(?m)^[ \t]*(?:第[零〇一二三四五六七八九十百千万两\d]+[章节回篇][^\n]{0,80}|Chapter[ \t]+\d+[^\n]{0,80})[ \t]*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ReferenceSegmentDraft:
    ordinal: int
    start_char: int
    end_char: int
    chapter_start: str | None
    chapter_end: str | None
    content: str

    @property
    def character_count(self) -> int:
        return self.end_char - self.start_char


@dataclass(frozen=True, slots=True)
class ReferenceAnalysisInput:
    work_id: str
    work_title: str
    segment_id: str
    ordinal: int
    start_char: int
    end_char: int
    chapter_start: str | None
    chapter_end: str | None
    content: str


def reference_chapter_label_at(content: str, relative_position: int) -> str | None:
    """Return the nearest chapter heading at or before a verified source position."""
    if relative_position < 0 or relative_position > len(content):
        raise ValueError("reference position is outside the segment")
    label: str | None = None
    for match in _CHAPTER_HEADING.finditer(content):
        if match.start() > relative_position:
            break
        label = match.group(0).strip()
    return label


def segment_reference_text(
    content: str,
    target_characters: int = 500_000,
) -> list[ReferenceSegmentDraft]:
    """Split reference text into contiguous author-facing analysis segments."""
    if target_characters <= 0:
        raise ValueError("target_characters must be positive")
    if not content:
        return []
    headings = [(match.start(), match.group(0).strip()) for match in _CHAPTER_HEADING.finditer(content)]
    heading_positions = [position for position, _ in headings]
    tolerance = max(1, target_characters // 10)
    boundaries = [0]
    while boundaries[-1] + target_characters < len(content):
        start = boundaries[-1]
        desired = start + target_characters
        left = bisect_left(heading_positions, desired - tolerance)
        right = bisect_right(heading_positions, desired + tolerance)
        candidates = [position for position in heading_positions[left:right] if position > start]
        end = min(candidates, key=lambda position: (abs(position - desired), position)) if candidates else desired
        boundaries.append(end)
    boundaries.append(len(content))

    def chapter_at(position: int, *, inclusive: bool) -> str | None:
        index = (
            bisect_right(heading_positions, position)
            if inclusive
            else bisect_left(heading_positions, position)
        ) - 1
        return headings[index][1] if index >= 0 else None

    return [
        ReferenceSegmentDraft(
            ordinal=index + 1,
            start_char=start,
            end_char=end,
            chapter_start=chapter_at(start, inclusive=True),
            chapter_end=chapter_at(end, inclusive=False),
            content=content[start:end],
        )
        for index, (start, end) in enumerate(pairwise(boundaries))
    ]
