from datetime import UTC, datetime
from sqlite3 import Row
from uuid import uuid4

from app.database import Database
from app.models import (
    SerialDailyGoal,
    SerialDashboard,
    SetSerialDailyGoalRequest,
    WorkspaceSearchResult,
)
from app.repository import NotFoundError, StaleRevisionError, now_iso


class SerialService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _actual_characters(version_rows: list[Row], goal_date: str) -> int:
        previous_by_chapter: dict[str, int] = {}
        actual = 0
        for row in version_rows:
            chapter_id = str(row["chapter_id"])
            current = len(str(row["content"]))
            previous = previous_by_chapter.get(chapter_id, 0)
            created_date = datetime.fromisoformat(str(row["created_at"])).astimezone().date().isoformat()
            if created_date == goal_date and not bool(row["is_candidate"]):
                actual += max(0, current - previous)
            previous_by_chapter[chapter_id] = current
        return actual

    def dashboard(self, project_id: str, goal_date: str | None = None) -> SerialDashboard:
        selected_date = goal_date or datetime.now(UTC).astimezone().date().isoformat()
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise NotFoundError(project_id)
            chapters = connection.execute(
                "SELECT id, status, content FROM chapters "
                "WHERE project_id = ? AND deleted_at IS NULL ORDER BY chapter_number",
                (project_id,),
            ).fetchall()
            versions = connection.execute(
                """
                SELECT v.chapter_id, v.content, v.is_candidate, v.created_at,
                       v.version_number
                FROM chapter_versions v
                JOIN chapters c ON c.id = v.chapter_id
                WHERE c.project_id = ?
                ORDER BY v.chapter_id, v.version_number
                """,
                (project_id,),
            ).fetchall()
            goal_row = connection.execute(
                "SELECT * FROM serial_daily_goals WHERE project_id = ? AND goal_date = ?",
                (project_id, selected_date),
            ).fetchone()
        target = int(goal_row["target_characters"]) if goal_row is not None else int(
            project["chapter_target_words"]
        )
        revision = int(goal_row["revision"]) if goal_row is not None else 0
        updated_at = str(goal_row["updated_at"]) if goal_row is not None else str(
            project["updated_at"]
        )
        counts = {state: sum(1 for row in chapters if row["status"] == state) for state in (
            "planned", "drafted", "reviewing", "approved"
        )}
        stockpile = sum(
            1 for row in chapters
            if row["status"] in {"drafted", "reviewing", "approved"} and str(row["content"]).strip()
        )
        return SerialDashboard(
            project_id=project_id,
            goal=SerialDailyGoal(
                project_id=project_id,
                goal_date=selected_date,
                target_characters=target,
                actual_characters=self._actual_characters(list(versions), selected_date),
                revision=revision,
                updated_at=updated_at,
            ),
            total_characters=sum(len(str(row["content"]).replace(" ", "")) for row in chapters),
            chapter_count=len(chapters),
            planned_chapters=counts["planned"],
            drafted_chapters=counts["drafted"],
            reviewing_chapters=counts["reviewing"],
            approved_chapters=counts["approved"],
            stockpile_chapters=stockpile,
            pending_review_chapters=counts["drafted"],
            ready_to_publish_chapters=counts["approved"],
        )

    def set_goal(
        self,
        project_id: str,
        goal_date: str,
        request: SetSerialDailyGoalRequest,
    ) -> SerialDashboard:
        timestamp = now_iso()
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
                raise NotFoundError(project_id)
            current = connection.execute(
                "SELECT revision FROM serial_daily_goals WHERE project_id = ? AND goal_date = ?",
                (project_id, goal_date),
            ).fetchone()
            if current is None:
                if request.expected_revision not in {None, 0}:
                    raise StaleRevisionError("0")
                connection.execute(
                    "INSERT INTO serial_daily_goals(id, project_id, goal_date, target_characters, revision, updated_at) "
                    "VALUES (?, ?, ?, ?, 0, ?)",
                    (str(uuid4()), project_id, goal_date, request.target_characters, timestamp),
                )
            else:
                if request.expected_revision is None or int(current["revision"]) != request.expected_revision:
                    raise StaleRevisionError(str(current["revision"]))
                connection.execute(
                    "UPDATE serial_daily_goals SET target_characters = ?, revision = revision + 1, "
                    "updated_at = ? WHERE project_id = ? AND goal_date = ? AND revision = ?",
                    (
                        request.target_characters, timestamp, project_id, goal_date,
                        request.expected_revision,
                    ),
                )
        return self.dashboard(project_id, goal_date)

    @staticmethod
    def _snippet(text: str, query: str, width: int = 160) -> str:
        normalized = " ".join(text.split())
        index = normalized.casefold().find(query.casefold())
        if index < 0:
            return normalized[:width]
        start = max(0, index - width // 3)
        end = min(len(normalized), start + width)
        prefix = "…" if start else ""
        suffix = "…" if end < len(normalized) else ""
        return f"{prefix}{normalized[start:end]}{suffix}"

    def search(self, project_id: str, query: str, limit: int = 50) -> list[WorkspaceSearchResult]:
        needle = query.strip()
        if not needle:
            return []
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        with self.database.connect() as connection:
            project = connection.execute(
                "SELECT id, title, rebirth_location FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project is None:
                raise NotFoundError(project_id)
            chapters = connection.execute(
                "SELECT id, title, content FROM chapters WHERE project_id = ? AND deleted_at IS NULL "
                "AND (title LIKE ? ESCAPE '\\' COLLATE NOCASE OR content LIKE ? ESCAPE '\\' COLLATE NOCASE) "
                "ORDER BY chapter_number LIMIT ?",
                (project_id, like, like, limit),
            ).fetchall()
            entities = connection.execute(
                "SELECT id, kind, name, role, goal, current_state, relationship_notes FROM story_entities "
                "WHERE project_id = ? AND (name LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR role LIKE ? ESCAPE '\\' COLLATE NOCASE OR goal LIKE ? ESCAPE '\\' COLLATE NOCASE "
                "OR current_state LIKE ? ESCAPE '\\' COLLATE NOCASE OR relationship_notes LIKE ? ESCAPE '\\' COLLATE NOCASE) "
                "ORDER BY name LIMIT ?",
                (project_id, like, like, like, like, like, limit),
            ).fetchall()
            threads = connection.execute(
                "SELECT id, source_chapter_id, title, summary FROM story_threads WHERE project_id = ? "
                "AND (title LIKE ? ESCAPE '\\' COLLATE NOCASE OR summary LIKE ? ESCAPE '\\' COLLATE NOCASE) "
                "ORDER BY created_at DESC LIMIT ?",
                (project_id, like, like, limit),
            ).fetchall()
        results: list[WorkspaceSearchResult] = []
        project_text = f"{project['title']} {project['rebirth_location']}"
        if needle.casefold() in project_text.casefold():
            results.append(WorkspaceSearchResult(
                kind="project", id=str(project["id"]), title=str(project["title"]),
                snippet=self._snippet(project_text, needle),
            ))
        results.extend(WorkspaceSearchResult(
            kind="chapter", id=str(row["id"]), title=str(row["title"]),
            snippet=self._snippet(f"{row['title']} {row['content']}", needle),
            chapter_id=str(row["id"]),
        ) for row in chapters)
        results.extend(WorkspaceSearchResult(
            kind="character" if row["kind"] == "character" else "resource",
            id=str(row["id"]), title=str(row["name"]),
            snippet=self._snippet(
                " ".join(str(row[field]) for field in ("name", "role", "goal", "current_state", "relationship_notes")),
                needle,
            ),
        ) for row in entities)
        results.extend(WorkspaceSearchResult(
            kind="thread", id=str(row["id"]), title=str(row["title"]),
            snippet=self._snippet(f"{row['title']} {row['summary']}", needle),
            chapter_id=str(row["source_chapter_id"]) if row["source_chapter_id"] else None,
        ) for row in threads)
        return results[:limit]
