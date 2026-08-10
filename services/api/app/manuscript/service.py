from hashlib import sha256
from uuid import uuid4

from app.database import Database
from app.models import (
    ChapterStatus,
    ChapterVersionSource,
    ConfirmManuscriptImportRequest,
    ManuscriptExport,
    Workspace,
)
from app.repository import NotFoundError, ProjectRepository, now_iso
from app.review.repository import ReviewRepository


class ManuscriptService:
    def __init__(self, database: Database, projects: ProjectRepository) -> None:
        self.database = database
        self.projects = projects

    def confirm_import(self, request: ConfirmManuscriptImportRequest) -> Workspace:
        project_id = str(uuid4())
        timestamp = now_iso()
        chapter_number = 0
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    id, title, genre, rebirth_year, rebirth_location,
                    chapter_target_words, safety_buffer_chapters, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    request.title,
                    request.genre.value,
                    request.rebirth_year,
                    request.rebirth_location,
                    request.chapter_target_words,
                    request.safety_buffer_chapters,
                    timestamp,
                    timestamp,
                ),
            )
            for volume_number, volume in enumerate(request.volumes, start=1):
                volume_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO manuscript_volumes (
                        id, project_id, volume_number, title, sort_key,
                        revision, deleted_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?)
                    """,
                    (
                        volume_id,
                        project_id,
                        volume_number,
                        volume.title,
                        volume_number * 1024,
                        timestamp,
                        timestamp,
                    ),
                )
                for volume_chapter_number, imported in enumerate(volume.chapters, start=1):
                    chapter_number += 1
                    chapter_id = str(uuid4())
                    content = imported.content
                    if (
                        chapter_number == 1
                        and request.unrecognized_text
                        and request.unrecognized_action == "prepend_first_chapter"
                    ):
                        content = f"{request.unrecognized_text.rstrip()}\n\n{content.lstrip()}".strip()
                    connection.execute(
                        """
                        INSERT INTO chapters (
                            id, project_id, volume_id, volume_number, chapter_number,
                            sort_key, title, content, reader_promise, opening_hook,
                            state_change, emotional_payoff, ending_cliffhanger,
                            status, revision, deleted_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', '', '', '', ?, 0, NULL, ?)
                        """,
                        (
                            chapter_id,
                            project_id,
                            volume_id,
                            volume_number,
                            chapter_number,
                            volume_chapter_number * 1024,
                            imported.title,
                            content,
                            (
                                ChapterStatus.DRAFTED.value
                                if content.strip()
                                else ChapterStatus.PLANNED.value
                            ),
                            timestamp,
                        ),
                    )
                    ReviewRepository.append_chapter_version(
                        connection,
                        chapter_id=chapter_id,
                        chapter_revision=0,
                        content=content,
                        source=ChapterVersionSource.INITIAL,
                        source_id=request.source_sha256,
                        created_at=timestamp,
                    )
        return self.projects.get_workspace(project_id)

    def export_markdown(self, project_id: str) -> ManuscriptExport:
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise NotFoundError(project_id)
            rows = connection.execute(
                """
                SELECT v.id AS volume_id, v.title AS volume_title,
                       c.id AS chapter_id, c.title AS chapter_title, c.content
                FROM manuscript_volumes v
                JOIN chapters c ON c.volume_id = v.id
                WHERE v.project_id = ? AND v.deleted_at IS NULL AND c.deleted_at IS NULL
                ORDER BY v.sort_key, v.id, c.sort_key, c.id
                """,
                (project_id,),
            ).fetchall()
        if not rows:
            raise ValueError("empty_manuscript")
        lines = [f"# {project['title']}", ""]
        current_volume_id: str | None = None
        volume_count = 0
        for row in rows:
            if row["volume_id"] != current_volume_id:
                current_volume_id = str(row["volume_id"])
                volume_count += 1
                lines.extend((f"## {row['volume_title']}", ""))
            lines.extend((f"### {row['chapter_title']}", "", str(row["content"]), ""))
        content = "\n".join(lines).rstrip() + "\n"
        filename_stem = "".join(
            "_" if character in '\\/:*?"<>|' or ord(character) < 32 else character
            for character in str(project["title"])
        ).strip() or "墨舟作品"
        return ManuscriptExport(
            filename=f"{filename_stem}.md",
            content=content,
            content_sha256=sha256(content.encode("utf-8")).hexdigest(),
            volume_count=volume_count,
            chapter_count=len(rows),
        )
