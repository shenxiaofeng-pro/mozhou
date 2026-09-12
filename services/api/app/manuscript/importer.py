import re
from pathlib import Path

from app.models import (
    ManuscriptImportChapter,
    ManuscriptImportPreview,
    ManuscriptImportVolume,
)
from app.safe_import import ParsedReferenceFile, UnsafeImportError, parse_reference_file

MAX_CHAPTER_CHARACTERS = 1_500_000
LONG_CHAPTER_CHARACTERS = 80_000
NUMBER = r"[0-9零〇一二三四五六七八九十百千万两]+"
VOLUME_PATTERN = re.compile(
    rf"^(?:(?:第\s*{NUMBER}\s*卷|卷\s*{NUMBER})"
    rf"(?:\s+.*|\s*[:：·、-]\s*.*)?|正文)$",
    re.IGNORECASE,
)
CHAPTER_PATTERN = re.compile(
    rf"^(?:第\s*{NUMBER}\s*章|章\s*{NUMBER}|chapter\s+\d+)(?:\s*[:：·、-]?\s*.*)?$",
    re.IGNORECASE,
)
MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _clean_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).strip("# \t")[:120]


def _split_oversized(content: str) -> list[str]:
    if len(content) <= MAX_CHAPTER_CHARACTERS:
        return [content]
    pieces: list[str] = []
    remaining = content
    while len(remaining) > MAX_CHAPTER_CHARACTERS:
        boundary = remaining.rfind("\n\n", 0, MAX_CHAPTER_CHARACTERS)
        if boundary < MAX_CHAPTER_CHARACTERS // 2:
            boundary = MAX_CHAPTER_CHARACTERS
        # Preserve the exact separator across adjacent pieces so a safety
        # split can always be joined back into the author's original text.
        pieces.append(remaining[:boundary])
        remaining = remaining[boundary:]
    pieces.append(remaining)
    return pieces


def _parse_structure(parsed: ParsedReferenceFile, filename: str) -> ManuscriptImportPreview:
    volumes: list[dict[str, object]] = []
    current_volume: dict[str, object] | None = None
    current_title: str | None = None
    current_confidence = 1.0
    current_lines: list[str] = []
    preamble: list[str] = []
    project_heading: str | None = None
    global_warnings = list(parsed.warnings)

    def ensure_volume() -> dict[str, object]:
        nonlocal current_volume
        if current_volume is None:
            current_volume = {"title": "正文", "chapters": []}
            volumes.append(current_volume)
        return current_volume

    def flush_chapter() -> None:
        nonlocal current_title, current_confidence, current_lines
        if current_title is None:
            return
        content = "".join(current_lines).strip("\n")
        parts = _split_oversized(content)
        destination = ensure_volume()["chapters"]
        if not isinstance(destination, list):
            raise TypeError("稿件卷结构无效")
        for part_index, part in enumerate(parts, start=1):
            warnings: list[str] = []
            if not part.strip():
                warnings.append("empty_chapter")
            if len(part) >= LONG_CHAPTER_CHARACTERS:
                warnings.append("long_chapter")
            if len(parts) > 1:
                warnings.append("oversized_chapter_split")
            title = current_title
            if len(parts) > 1:
                title = f"{current_title}（导入分段 {part_index}/{len(parts)}）"
            destination.append(
                {
                    "title": title,
                    "content": part,
                    "heading_confidence": current_confidence,
                    "warnings": warnings,
                }
            )
        current_title = None
        current_confidence = 1.0
        current_lines = []

    for line in parsed.content.splitlines(keepends=True):
        stripped = line.strip()
        markdown_match = MARKDOWN_HEADING.match(stripped)
        heading_level = len(markdown_match.group(1)) if markdown_match else None
        candidate = _clean_heading(markdown_match.group(2) if markdown_match else stripped)
        if candidate and VOLUME_PATTERN.fullmatch(candidate):
            flush_chapter()
            current_volume = {"title": candidate, "chapters": []}
            volumes.append(current_volume)
            continue
        if candidate and CHAPTER_PATTERN.fullmatch(candidate):
            flush_chapter()
            ensure_volume()
            current_title = candidate
            current_confidence = 1.0 if markdown_match or candidate.startswith("第") else 0.9
            continue
        if (
            markdown_match
            and heading_level == 1
            and project_heading is None
            and current_title is None
            and not any(volume["chapters"] for volume in volumes)
        ):
            project_heading = candidate
            continue
        if current_title is None:
            preamble.append(line)
        else:
            current_lines.append(line)
    flush_chapter()

    nonempty_volumes = [volume for volume in volumes if volume["chapters"]]
    unrecognized = "".join(preamble).strip("\n")
    if not nonempty_volumes:
        fallback_content = unrecognized
        if not fallback_content.strip():
            raise UnsafeImportError("empty_content")
        unrecognized = ""
        global_warnings.append("no_chapter_headings")
        fallback_parts = _split_oversized(fallback_content)
        nonempty_volumes = [{
            "title": "正文",
            "chapters": [
                {
                    "title": (
                        "第一章 导入稿"
                        if len(fallback_parts) == 1
                        else f"第{ordinal}章 导入分段"
                    ),
                    "content": part,
                    "heading_confidence": 0.35,
                    "warnings": [
                        "low_heading_confidence",
                        *(["oversized_chapter_split"] if len(fallback_parts) > 1 else []),
                        *(["long_chapter"] if len(part) >= LONG_CHAPTER_CHARACTERS else []),
                    ],
                }
                for ordinal, part in enumerate(fallback_parts, start=1)
            ],
        }]
    elif unrecognized:
        global_warnings.append("unrecognized_preamble")

    model_volumes: list[ManuscriptImportVolume] = []
    for volume_ordinal, raw_volume in enumerate(nonempty_volumes, start=1):
        raw_chapters = raw_volume["chapters"]
        if not isinstance(raw_chapters, list):
            raise TypeError("稿件章节结构无效")
        model_volumes.append(
            ManuscriptImportVolume(
                client_id=f"volume-{volume_ordinal}",
                title=str(raw_volume["title"]),
                chapters=[
                    ManuscriptImportChapter(
                        client_id=f"volume-{volume_ordinal}-chapter-{chapter_ordinal}",
                        **raw_chapter,
                    )
                    for chapter_ordinal, raw_chapter in enumerate(raw_chapters, start=1)
                ],
            )
        )
    chapter_count = sum(len(volume.chapters) for volume in model_volumes)
    total_characters = len(unrecognized) + sum(
        len(chapter.content)
        for volume in model_volumes
        for chapter in volume.chapters
    )
    inferred = project_heading or Path(filename).name.rsplit(".", 1)[0]
    inferred = _clean_heading(inferred) or "导入作品"
    return ManuscriptImportPreview(
        source_filename=filename,
        source_format=parsed.source_format,
        source_encoding=parsed.source_encoding,
        encoding_confidence=parsed.encoding_confidence,
        source_sha256=parsed.source_sha256,
        inferred_project_title=inferred,
        volumes=model_volumes,
        unrecognized_text=unrecognized,
        total_characters=total_characters,
        chapter_count=chapter_count,
        warnings=list(dict.fromkeys(global_warnings)),
    )


def preview_manuscript_file(filename: str, payload: bytes) -> ManuscriptImportPreview:
    parsed = parse_reference_file(filename, payload)
    if parsed.source_format not in {"txt", "markdown", "docx", "epub"}:
        raise UnsafeImportError("unsupported_manuscript_format")
    return _parse_structure(parsed, filename)
