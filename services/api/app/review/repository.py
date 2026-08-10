import json
from datetime import UTC, datetime
from hashlib import sha256
from itertools import pairwise
from sqlite3 import Connection, Row
from uuid import uuid4

from app.database import Database
from app.models import (
    ApplyTextChangeSetRequest,
    Chapter,
    ChapterStatus,
    ChapterVersion,
    ChapterVersionSource,
    CreateTextChangeSetRequest,
    RejectTextChangeSetRequest,
    ReviewEvidence,
    ReviewFinding,
    ReviewFindingState,
    RollbackChapterVersionRequest,
    TextChange,
    TextChangeSet,
    TextChangeSetState,
)


class ReviewNotFoundError(LookupError):
    pass


class StaleReviewRevisionError(RuntimeError):
    pass


class InvalidTextChangeError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _content_sha256(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


class ReviewRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def append_chapter_version(
        connection: Connection,
        *,
        chapter_id: str,
        chapter_revision: int,
        content: str,
        source: ChapterVersionSource,
        source_id: str | None = None,
        is_candidate: bool = False,
        created_at: str | None = None,
    ) -> ChapterVersion:
        if source_id is not None and source in {
            ChapterVersionSource.GENERATION_CANDIDATE,
            ChapterVersionSource.GENERATION_APPLY,
            ChapterVersionSource.CHANGE_SET_APPLY,
        }:
            existing = connection.execute(
                """
                SELECT * FROM chapter_versions
                WHERE chapter_id = ? AND source = ? AND source_id = ?
                """,
                (chapter_id, source.value, source_id),
            ).fetchone()
            if existing is not None:
                version = ReviewRepository.parse_chapter_version(existing)
                if (
                    version.chapter_revision != chapter_revision
                    or version.content != content
                    or version.is_candidate != is_candidate
                ):
                    raise InvalidTextChangeError("章节版本来源对应了不同内容")
                return version
        latest = connection.execute(
            """
            SELECT id, version_number FROM chapter_versions
            WHERE chapter_id = ? AND is_candidate = 0
            ORDER BY version_number DESC LIMIT 1
            """,
            (chapter_id,),
        ).fetchone()
        version_number = int(
            connection.execute(
                "SELECT COALESCE(MAX(version_number), 0) + 1 FROM chapter_versions WHERE chapter_id = ?",
                (chapter_id,),
            ).fetchone()[0]
        )
        version_id = str(uuid4())
        timestamp = created_at or _now_iso()
        connection.execute(
            """
            INSERT INTO chapter_versions (
                id, chapter_id, version_number, chapter_revision, content,
                content_sha256, source, source_id, parent_version_id,
                is_candidate, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                chapter_id,
                version_number,
                chapter_revision,
                content,
                _content_sha256(content),
                source.value,
                source_id,
                latest["id"] if latest is not None else None,
                int(is_candidate),
                timestamp,
            ),
        )
        row = connection.execute(
            "SELECT * FROM chapter_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if row is None:
            raise ReviewNotFoundError(version_id)
        return ReviewRepository.parse_chapter_version(row)

    def list_chapter_versions(self, chapter_id: str) -> list[ChapterVersion]:
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone() is None:
                raise ReviewNotFoundError(chapter_id)
            rows = connection.execute(
                """
                SELECT * FROM chapter_versions
                WHERE chapter_id = ? ORDER BY version_number DESC
                """,
                (chapter_id,),
            ).fetchall()
        return [self.parse_chapter_version(row) for row in rows]

    def rollback_chapter_version(
        self,
        chapter_id: str,
        version_id: str,
        request: RollbackChapterVersionRequest,
    ) -> Chapter:
        timestamp = _now_iso()
        with self.database.connect() as connection:
            chapter = connection.execute(
                "SELECT * FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone()
            if chapter is None:
                raise ReviewNotFoundError(chapter_id)
            if int(chapter["revision"]) != request.expected_revision:
                raise StaleReviewRevisionError(str(chapter["revision"]))
            target = connection.execute(
                """
                SELECT * FROM chapter_versions
                WHERE id = ? AND chapter_id = ? AND is_candidate = 0
                """,
                (version_id, chapter_id),
            ).fetchone()
            if target is None:
                raise ReviewNotFoundError(version_id)
            new_revision = request.expected_revision + 1
            connection.execute(
                """
                UPDATE chapters
                SET content = ?, status = ?, revision = ?, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    target["content"],
                    ChapterStatus.DRAFTED.value,
                    new_revision,
                    timestamp,
                    chapter_id,
                    request.expected_revision,
                ),
            )
            self.append_chapter_version(
                connection,
                chapter_id=chapter_id,
                chapter_revision=new_revision,
                content=target["content"],
                source=ChapterVersionSource.ROLLBACK,
                source_id=version_id,
                created_at=timestamp,
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, chapter["project_id"]),
            )
            updated = connection.execute(
                "SELECT * FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone()
        if updated is None:
            raise ReviewNotFoundError(chapter_id)
        return Chapter.model_validate(dict(updated))

    def save_findings(self, findings: list[ReviewFinding]) -> list[ReviewFinding]:
        if not findings:
            return []
        with self.database.connect() as connection:
            connection.executemany(
                """
                INSERT INTO review_findings (
                    id, project_id, chapter_id, chapter_revision, review_job_id,
                    dimension, severity, code, title, evidence_json,
                    explanation, suggestion, suggested_replacement, confidence,
                    dedupe_key, state, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                [
                    (
                        finding.id,
                        finding.project_id,
                        finding.chapter_id,
                        finding.chapter_revision,
                        finding.review_job_id,
                        finding.dimension.value,
                        finding.severity.value,
                        finding.code,
                        finding.title,
                        json.dumps(
                            [item.model_dump(mode="json") for item in finding.evidence],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        finding.explanation,
                        finding.suggestion,
                        finding.suggested_replacement,
                        finding.confidence,
                        finding.dedupe_key,
                        finding.state.value,
                        finding.created_at,
                    )
                    for finding in findings
                ],
            )
        return self.list_findings_for_job(findings[0].review_job_id or "")

    def list_findings(
        self,
        chapter_id: str,
        *,
        chapter_revision: int | None = None,
    ) -> list[ReviewFinding]:
        parameters: list[object] = [chapter_id]
        revision_clause = ""
        if chapter_revision is not None:
            revision_clause = "AND chapter_revision = ?"
            parameters.append(chapter_revision)
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone() is None:
                raise ReviewNotFoundError(chapter_id)
            rows = connection.execute(
                f"""
                SELECT * FROM review_findings
                WHERE chapter_id = ? {revision_clause}
                ORDER BY created_at DESC, id DESC
                """,
                parameters,
            ).fetchall()
        deduplicated: dict[str, ReviewFinding] = {}
        for row in rows:
            finding = self.parse_finding(row)
            deduplicated.setdefault(finding.dedupe_key, finding)
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        return sorted(
            deduplicated.values(),
            key=lambda item: (
                severity_order[item.severity.value],
                item.dimension.value,
                item.created_at,
            ),
        )

    def list_findings_for_job(self, job_id: str) -> list[ReviewFinding]:
        if not job_id:
            return []
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM review_findings
                WHERE review_job_id = ? ORDER BY created_at, id
                """,
                (job_id,),
            ).fetchall()
        return [self.parse_finding(row) for row in rows]

    def create_text_change_set(
        self,
        chapter_id: str,
        request: CreateTextChangeSetRequest,
    ) -> TextChangeSet:
        timestamp = _now_iso()
        with self.database.connect() as connection:
            chapter = connection.execute(
                "SELECT * FROM chapters WHERE id = ?", (chapter_id,)
            ).fetchone()
            if chapter is None:
                raise ReviewNotFoundError(chapter_id)
            placeholders = ",".join("?" for _ in request.finding_ids)
            rows = connection.execute(
                f"""
                SELECT * FROM review_findings
                WHERE id IN ({placeholders}) AND chapter_id = ?
                  AND chapter_revision = ? AND state = 'open'
                ORDER BY created_at, id
                """,
                [*request.finding_ids, chapter_id, chapter["revision"]],
            ).fetchall()
            if len(rows) != len(request.finding_ids):
                raise InvalidTextChangeError("审校建议已过期、已处理或不属于当前章节")
            content = str(chapter["content"])
            prepared: list[tuple[Row, ReviewEvidence]] = []
            for row in rows:
                replacement = row["suggested_replacement"]
                if replacement is None:
                    raise InvalidTextChangeError("所选建议没有可应用的局部替换")
                evidences = [
                    ReviewEvidence.model_validate(item)
                    for item in json.loads(row["evidence_json"])
                ]
                body = next(
                    (
                        item
                        for item in evidences
                        if item.kind.value == "body" and item.chapter_id == chapter_id
                    ),
                    None,
                )
                if (
                    body is None
                    or body.start_char is None
                    or body.end_char is None
                    or body.excerpt is None
                    or content[body.start_char : body.end_char] != body.excerpt
                ):
                    raise InvalidTextChangeError("建议正文证据无法匹配当前版本")
                prepared.append((row, body))
            prepared.sort(key=lambda item: int(item[1].start_char or 0))
            for previous, current in pairwise(prepared):
                if int(previous[1].end_char or 0) > int(current[1].start_char or 0):
                    raise InvalidTextChangeError("所选建议的修改范围互相重叠")
            change_set_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO text_change_sets (
                    id, chapter_id, base_chapter_revision, base_content_sha256,
                    title, state, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'candidate', 0, ?, ?)
                """,
                (
                    change_set_id,
                    chapter_id,
                    chapter["revision"],
                    _content_sha256(content),
                    f"审校建议 · {len(prepared)} 处局部修改",
                    timestamp,
                    timestamp,
                ),
            )
            connection.executemany(
                """
                INSERT INTO text_changes (
                    id, change_set_id, ordinal, start_char, end_char,
                    original_text, replacement_text, rationale,
                    review_finding_id, selected, applied_replacement
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                [
                    (
                        str(uuid4()),
                        change_set_id,
                        ordinal,
                        evidence.start_char,
                        evidence.end_char,
                        evidence.excerpt,
                        row["suggested_replacement"],
                        row["suggestion"],
                        row["id"],
                    )
                    for ordinal, (row, evidence) in enumerate(prepared, 1)
                ],
            )
        return self.get_text_change_set(change_set_id)

    def get_text_change_set(self, change_set_id: str) -> TextChangeSet:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM text_change_sets WHERE id = ?", (change_set_id,)
            ).fetchone()
            if row is None:
                raise ReviewNotFoundError(change_set_id)
            change_rows = connection.execute(
                "SELECT * FROM text_changes WHERE change_set_id = ? ORDER BY ordinal",
                (change_set_id,),
            ).fetchall()
        return self.parse_text_change_set(row, change_rows)

    def list_text_change_sets(self, chapter_id: str) -> list[TextChangeSet]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM text_change_sets
                WHERE chapter_id = ? ORDER BY created_at DESC, id DESC
                """,
                (chapter_id,),
            ).fetchall()
            change_rows = connection.execute(
                """
                SELECT t.* FROM text_changes t
                JOIN text_change_sets s ON s.id = t.change_set_id
                WHERE s.chapter_id = ? ORDER BY t.change_set_id, t.ordinal
                """,
                (chapter_id,),
            ).fetchall()
        grouped: dict[str, list[Row]] = {}
        for row in change_rows:
            grouped.setdefault(str(row["change_set_id"]), []).append(row)
        return [
            self.parse_text_change_set(row, grouped.get(str(row["id"]), []))
            for row in rows
        ]

    def apply_text_change_set(
        self,
        change_set_id: str,
        request: ApplyTextChangeSetRequest,
    ) -> Chapter:
        timestamp = _now_iso()
        selected_ids = set(request.selected_change_ids)
        with self.database.connect() as connection:
            change_set = connection.execute(
                "SELECT * FROM text_change_sets WHERE id = ?", (change_set_id,)
            ).fetchone()
            if change_set is None:
                raise ReviewNotFoundError(change_set_id)
            if int(change_set["revision"]) != request.expected_set_revision:
                raise StaleReviewRevisionError(str(change_set["revision"]))
            if change_set["state"] != TextChangeSetState.CANDIDATE.value:
                raise InvalidTextChangeError("文本变更集已经处理")
            chapter = connection.execute(
                "SELECT * FROM chapters WHERE id = ?", (change_set["chapter_id"],)
            ).fetchone()
            if chapter is None:
                raise ReviewNotFoundError(str(change_set["chapter_id"]))
            if (
                int(chapter["revision"]) != request.expected_chapter_revision
                or int(chapter["revision"]) != int(change_set["base_chapter_revision"])
                or _content_sha256(str(chapter["content"]))
                != change_set["base_content_sha256"]
            ):
                raise StaleReviewRevisionError(str(chapter["revision"]))
            changes = connection.execute(
                "SELECT * FROM text_changes WHERE change_set_id = ? ORDER BY ordinal",
                (change_set_id,),
            ).fetchall()
            known_ids = {str(row["id"]) for row in changes}
            if not selected_ids <= known_ids:
                raise InvalidTextChangeError("文本变更选择无效")
            selected = [row for row in changes if row["id"] in selected_ids]
            for previous, current in pairwise(selected):
                if int(previous["end_char"]) > int(current["start_char"]):
                    raise InvalidTextChangeError("所选文本变更范围重叠")
            content = str(chapter["content"])
            for row in reversed(selected):
                start = int(row["start_char"])
                end = int(row["end_char"])
                if content[start:end] != row["original_text"]:
                    raise StaleReviewRevisionError(str(chapter["revision"]))
                replacement = request.edited_replacements.get(
                    str(row["id"]), str(row["replacement_text"])
                )
                content = f"{content[:start]}{replacement}{content[end:]}"
            new_revision = int(chapter["revision"]) + 1
            result = connection.execute(
                """
                UPDATE chapters
                SET content = ?, status = ?, revision = ?, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    content,
                    ChapterStatus.DRAFTED.value,
                    new_revision,
                    timestamp,
                    chapter["id"],
                    request.expected_chapter_revision,
                ),
            )
            if result.rowcount != 1:
                raise StaleReviewRevisionError(str(chapter["revision"]))
            for row in changes:
                change_id = str(row["id"])
                chosen = change_id in selected_ids
                applied = (
                    request.edited_replacements.get(change_id, str(row["replacement_text"]))
                    if chosen
                    else None
                )
                connection.execute(
                    """
                    UPDATE text_changes SET selected = ?, applied_replacement = ?
                    WHERE id = ?
                    """,
                    (int(chosen), applied, change_id),
                )
                if chosen and row["review_finding_id"] is not None:
                    connection.execute(
                        "UPDATE review_findings SET state = ? WHERE id = ? AND state = ?",
                        (
                            ReviewFindingState.ACCEPTED.value,
                            row["review_finding_id"],
                            ReviewFindingState.OPEN.value,
                        ),
                    )
            connection.execute(
                """
                UPDATE text_change_sets
                SET state = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ? AND state = ?
                """,
                (
                    TextChangeSetState.APPLIED.value,
                    timestamp,
                    change_set_id,
                    request.expected_set_revision,
                    TextChangeSetState.CANDIDATE.value,
                ),
            )
            self.append_chapter_version(
                connection,
                chapter_id=str(chapter["id"]),
                chapter_revision=new_revision,
                content=content,
                source=ChapterVersionSource.CHANGE_SET_APPLY,
                source_id=change_set_id,
                created_at=timestamp,
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (timestamp, chapter["project_id"]),
            )
            updated = connection.execute(
                "SELECT * FROM chapters WHERE id = ?", (chapter["id"],)
            ).fetchone()
        if updated is None:
            raise ReviewNotFoundError(str(change_set["chapter_id"]))
        return Chapter.model_validate(dict(updated))

    def reject_text_change_set(
        self,
        change_set_id: str,
        request: RejectTextChangeSetRequest,
    ) -> TextChangeSet:
        timestamp = _now_iso()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM text_change_sets WHERE id = ?", (change_set_id,)
            ).fetchone()
            if row is None:
                raise ReviewNotFoundError(change_set_id)
            if int(row["revision"]) != request.expected_revision:
                raise StaleReviewRevisionError(str(row["revision"]))
            if row["state"] != TextChangeSetState.CANDIDATE.value:
                raise InvalidTextChangeError("文本变更集已经处理")
            connection.execute(
                """
                UPDATE text_change_sets
                SET state = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    TextChangeSetState.REJECTED.value,
                    timestamp,
                    change_set_id,
                    request.expected_revision,
                ),
            )
            connection.execute(
                """
                UPDATE review_findings SET state = ?
                WHERE state = ? AND id IN (
                    SELECT review_finding_id FROM text_changes
                    WHERE change_set_id = ? AND review_finding_id IS NOT NULL
                )
                """,
                (
                    ReviewFindingState.REJECTED.value,
                    ReviewFindingState.OPEN.value,
                    change_set_id,
                ),
            )
        return self.get_text_change_set(change_set_id)

    @staticmethod
    def parse_chapter_version(row: Row) -> ChapterVersion:
        return ChapterVersion.model_validate(
            {**dict(row), "is_candidate": bool(row["is_candidate"])}
        )

    @staticmethod
    def parse_finding(row: Row) -> ReviewFinding:
        return ReviewFinding.model_validate(
            {**dict(row), "evidence": json.loads(row["evidence_json"])}
        )

    @staticmethod
    def parse_text_change(row: Row) -> TextChange:
        return TextChange.model_validate(
            {
                **dict(row),
                "selected": (
                    bool(row["selected"]) if row["selected"] is not None else None
                ),
            }
        )

    @classmethod
    def parse_text_change_set(
        cls,
        row: Row,
        changes: list[Row],
    ) -> TextChangeSet:
        return TextChangeSet.model_validate(
            {
                **dict(row),
                "changes": [cls.parse_text_change(change) for change in changes],
            }
        )
