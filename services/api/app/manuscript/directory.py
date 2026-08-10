import json
from sqlite3 import Connection, Row
from typing import Literal, cast
from uuid import uuid4

from app.database import Database
from app.models import (
    ChapterStatus,
    ChapterVersionSource,
    CreateDirectoryNodeRequest,
    DeleteDirectoryNodeRequest,
    DirectoryDeleteImpact,
    DirectoryEvent,
    MoveDirectoryNodeRequest,
    RenameDirectoryNodeRequest,
    WorkspaceSummary,
)
from app.repository import NotFoundError, ProjectRepository, StaleRevisionError, now_iso
from app.review.repository import ReviewRepository

NodeKind = Literal["volume", "chapter", "scene"]


class DirectoryConflictError(Exception):
    pass


class DirectoryConfirmationRequiredError(Exception):
    pass


class DirectoryService:
    def __init__(self, database: Database, projects: ProjectRepository) -> None:
        self.database = database
        self.projects = projects

    @staticmethod
    def _table(kind: NodeKind) -> str:
        return {
            "volume": "manuscript_volumes",
            "chapter": "chapters",
            "scene": "manuscript_scenes",
        }[kind]

    @staticmethod
    def _active_row(connection: Connection, kind: NodeKind, node_id: str) -> Row:
        row = connection.execute(
            f"SELECT * FROM {DirectoryService._table(kind)} "
            "WHERE id = ? AND deleted_at IS NULL",
            (node_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(node_id)
        return cast(Row, row)

    @staticmethod
    def _record_event(
        connection: Connection,
        *,
        project_id: str,
        action: Literal["create", "rename", "move", "delete"],
        kind: NodeKind,
        node_id: str,
        payload: dict[str, object],
        timestamp: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO directory_events(
                id, project_id, action, node_kind, node_id,
                payload_json, undone_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                str(uuid4()),
                project_id,
                action,
                kind,
                node_id,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                timestamp,
            ),
        )

    @staticmethod
    def _touch_project(connection: Connection, project_id: str, timestamp: str) -> None:
        connection.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?", (timestamp, project_id)
        )

    def create_node(
        self, project_id: str, request: CreateDirectoryNodeRequest
    ) -> WorkspaceSummary:
        timestamp = now_iso()
        node_id = str(uuid4())
        with self.database.connect() as connection:
            if connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
                raise NotFoundError(project_id)
            if request.kind == "volume":
                if request.parent_id is not None:
                    raise DirectoryConflictError("volume_cannot_have_parent")
                volume_number = int(connection.execute(
                    "SELECT COALESCE(MAX(volume_number), 0) + 1 FROM manuscript_volumes "
                    "WHERE project_id = ?",
                    (project_id,),
                ).fetchone()[0])
                sort_key = int(connection.execute(
                    "SELECT COALESCE(MAX(sort_key), 0) + 1024 FROM manuscript_volumes "
                    "WHERE project_id = ? AND deleted_at IS NULL",
                    (project_id,),
                ).fetchone()[0])
                connection.execute(
                    """
                    INSERT INTO manuscript_volumes(
                        id, project_id, volume_number, title, sort_key,
                        revision, deleted_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?)
                    """,
                    (node_id, project_id, volume_number, request.title, sort_key, timestamp, timestamp),
                )
            elif request.kind == "chapter":
                if request.parent_id is None:
                    raise DirectoryConflictError("chapter_requires_volume")
                volume = self._active_row(connection, "volume", request.parent_id)
                if volume["project_id"] != project_id:
                    raise DirectoryConflictError("parent_project_mismatch")
                chapter_number = int(connection.execute(
                    "SELECT COALESCE(MAX(chapter_number), 0) + 1 FROM chapters WHERE project_id = ?",
                    (project_id,),
                ).fetchone()[0])
                sort_key = int(connection.execute(
                    "SELECT COALESCE(MAX(sort_key), 0) + 1024 FROM chapters "
                    "WHERE volume_id = ? AND deleted_at IS NULL",
                    (request.parent_id,),
                ).fetchone()[0])
                connection.execute(
                    """
                    INSERT INTO chapters(
                        id, project_id, volume_id, volume_number, chapter_number,
                        sort_key, title, content, reader_promise, opening_hook,
                        state_change, emotional_payoff, ending_cliffhanger,
                        status, revision, deleted_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, '', '', '', '', '', '', ?, 0, NULL, ?)
                    """,
                    (
                        node_id, project_id, request.parent_id, volume["volume_number"],
                        chapter_number, sort_key, request.title,
                        ChapterStatus.PLANNED.value, timestamp,
                    ),
                )
                ReviewRepository.append_chapter_version(
                    connection,
                    chapter_id=node_id,
                    chapter_revision=0,
                    content="",
                    source=ChapterVersionSource.INITIAL,
                    created_at=timestamp,
                )
            else:
                if request.parent_id is None:
                    raise DirectoryConflictError("scene_requires_chapter")
                chapter = self._active_row(connection, "chapter", request.parent_id)
                if chapter["project_id"] != project_id:
                    raise DirectoryConflictError("parent_project_mismatch")
                sort_key = int(connection.execute(
                    "SELECT COALESCE(MAX(sort_key), 0) + 1024 FROM manuscript_scenes "
                    "WHERE chapter_id = ? AND deleted_at IS NULL",
                    (request.parent_id,),
                ).fetchone()[0])
                connection.execute(
                    """
                    INSERT INTO manuscript_scenes(
                        id, project_id, chapter_id, title, summary, sort_key,
                        revision, deleted_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)
                    """,
                    (
                        node_id, project_id, request.parent_id, request.title,
                        request.summary, sort_key, timestamp, timestamp,
                    ),
                )
            self._record_event(
                connection, project_id=project_id, action="create", kind=request.kind,
                node_id=node_id, payload={"created_revision": 0}, timestamp=timestamp,
            )
            self._touch_project(connection, project_id, timestamp)
        return self.projects.get_workspace_summary(project_id)

    def rename_node(
        self, kind: NodeKind, node_id: str, request: RenameDirectoryNodeRequest
    ) -> WorkspaceSummary:
        timestamp = now_iso()
        with self.database.connect() as connection:
            row = self._active_row(connection, kind, node_id)
            if int(row["revision"]) != request.expected_revision:
                raise StaleRevisionError(str(row["revision"]))
            before = {"title": str(row["title"]), "revision": int(row["revision"])}
            if kind == "scene":
                before["summary"] = str(row["summary"])
                summary = str(row["summary"]) if request.summary is None else request.summary
                connection.execute(
                    "UPDATE manuscript_scenes SET title = ?, summary = ?, revision = revision + 1, "
                    "updated_at = ? WHERE id = ? AND revision = ?",
                    (request.title, summary, timestamp, node_id, request.expected_revision),
                )
            else:
                connection.execute(
                    f"UPDATE {self._table(kind)} SET title = ?, revision = revision + 1, "
                    "updated_at = ? WHERE id = ? AND revision = ?",
                    (request.title, timestamp, node_id, request.expected_revision),
                )
            project_id = str(row["project_id"])
            self._record_event(
                connection, project_id=project_id, action="rename", kind=kind,
                node_id=node_id, payload={"before": before}, timestamp=timestamp,
            )
            self._touch_project(connection, project_id, timestamp)
        return self.projects.get_workspace_summary(project_id)

    @staticmethod
    def _rebalance(
        connection: Connection,
        table: str,
        parent_column: str,
        parent_id: str,
        ordered_ids: list[str],
    ) -> None:
        for ordinal, sibling_id in enumerate(ordered_ids, start=1):
            connection.execute(
                f"UPDATE {table} SET sort_key = ? WHERE id = ? AND {parent_column} = ?",
                (ordinal * 1024, sibling_id, parent_id),
            )

    def move_node(
        self, kind: NodeKind, node_id: str, request: MoveDirectoryNodeRequest
    ) -> WorkspaceSummary:
        timestamp = now_iso()
        with self.database.connect() as connection:
            row = self._active_row(connection, kind, node_id)
            if int(row["revision"]) != request.expected_revision:
                raise StaleRevisionError(str(row["revision"]))
            project_id = str(row["project_id"])
            if kind == "volume":
                if request.parent_id is not None:
                    raise DirectoryConflictError("volume_cannot_have_parent")
                table, parent_column, parent_id = "manuscript_volumes", "project_id", project_id
                before_parent: str | None = None
            elif kind == "chapter":
                if request.parent_id is None:
                    raise DirectoryConflictError("chapter_requires_volume")
                parent = self._active_row(connection, "volume", request.parent_id)
                if parent["project_id"] != project_id:
                    raise DirectoryConflictError("parent_project_mismatch")
                table, parent_column, parent_id = "chapters", "volume_id", request.parent_id
                before_parent = str(row["volume_id"])
            else:
                if request.parent_id is None:
                    raise DirectoryConflictError("scene_requires_chapter")
                parent = self._active_row(connection, "chapter", request.parent_id)
                if parent["project_id"] != project_id:
                    raise DirectoryConflictError("parent_project_mismatch")
                table, parent_column, parent_id = "manuscript_scenes", "chapter_id", request.parent_id
                before_parent = str(row["chapter_id"])
            siblings = [
                str(item["id"])
                for item in connection.execute(
                    f"SELECT id FROM {table} WHERE {parent_column} = ? "
                    "AND deleted_at IS NULL AND id != ? ORDER BY sort_key, id",
                    (parent_id, node_id),
                ).fetchall()
            ]
            if request.before_id is not None:
                if request.before_id not in siblings:
                    raise DirectoryConflictError("invalid_before_node")
                siblings.insert(siblings.index(request.before_id), node_id)
            else:
                siblings.append(node_id)
            before = {
                "parent_id": before_parent,
                "sort_key": int(row["sort_key"]),
                "revision": int(row["revision"]),
            }
            if kind == "chapter":
                connection.execute(
                    "UPDATE chapters SET volume_id = ?, volume_number = ?, revision = revision + 1, "
                    "updated_at = ? WHERE id = ? AND revision = ?",
                    (parent_id, parent["volume_number"], timestamp, node_id, request.expected_revision),
                )
            elif kind == "scene":
                connection.execute(
                    "UPDATE manuscript_scenes SET chapter_id = ?, revision = revision + 1, "
                    "updated_at = ? WHERE id = ? AND revision = ?",
                    (parent_id, timestamp, node_id, request.expected_revision),
                )
            else:
                connection.execute(
                    "UPDATE manuscript_volumes SET revision = revision + 1, updated_at = ? "
                    "WHERE id = ? AND revision = ?",
                    (timestamp, node_id, request.expected_revision),
                )
            self._rebalance(connection, table, parent_column, parent_id, siblings)
            if before_parent is not None and before_parent != parent_id:
                old_ids = [str(item["id"]) for item in connection.execute(
                    f"SELECT id FROM {table} WHERE {parent_column} = ? AND deleted_at IS NULL "
                    "ORDER BY sort_key, id",
                    (before_parent,),
                ).fetchall()]
                self._rebalance(connection, table, parent_column, before_parent, old_ids)
            self._record_event(
                connection, project_id=project_id, action="move", kind=kind,
                node_id=node_id, payload={"before": before}, timestamp=timestamp,
            )
            self._touch_project(connection, project_id, timestamp)
        return self.projects.get_workspace_summary(project_id)

    @staticmethod
    def _reference_counts(connection: Connection, chapter_ids: list[str]) -> dict[str, int]:
        if not chapter_ids:
            return {}
        placeholders = ",".join("?" for _ in chapter_ids)
        checks = {
            "正式事实": ("story_facts", "source_chapter_id"),
            "事实变更集": ("fact_change_sets", "chapter_id"),
            "章节版本": ("chapter_versions", "chapter_id"),
            "生成候选": ("generation_runs", "chapter_id"),
            "审校发现": ("review_findings", "chapter_id"),
            "文本变更集": ("text_change_sets", "chapter_id"),
        }
        existing_tables = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        result: dict[str, int] = {}
        for label, (table, column) in checks.items():
            if table not in existing_tables:
                continue
            count = int(connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({placeholders})",
                chapter_ids,
            ).fetchone()[0])
            if count:
                result[label] = count
        return result

    def delete_impact(self, kind: NodeKind, node_id: str) -> DirectoryDeleteImpact:
        with self.database.connect() as connection:
            row = self._active_row(connection, kind, node_id)
            project_id = str(row["project_id"])
            if kind == "volume":
                chapter_ids = [str(item["id"]) for item in connection.execute(
                    "SELECT id FROM chapters WHERE volume_id = ? AND deleted_at IS NULL",
                    (node_id,),
                ).fetchall()]
            elif kind == "chapter":
                chapter_ids = [node_id]
            else:
                chapter_ids = []
            scene_count = int(connection.execute(
                "SELECT COUNT(*) FROM manuscript_scenes WHERE deleted_at IS NULL AND chapter_id IN "
                f"({','.join('?' for _ in chapter_ids) or 'NULL'})",
                chapter_ids,
            ).fetchone()[0])
            active_volumes = int(connection.execute(
                "SELECT COUNT(*) FROM manuscript_volumes WHERE project_id = ? AND deleted_at IS NULL",
                (project_id,),
            ).fetchone()[0])
            active_chapters = int(connection.execute(
                "SELECT COUNT(*) FROM chapters WHERE project_id = ? AND deleted_at IS NULL",
                (project_id,),
            ).fetchone()[0])
            reason: str | None = None
            if kind == "volume" and active_volumes <= 1:
                reason = "作品至少需要保留一卷"
            elif kind in {"volume", "chapter"} and len(chapter_ids) >= active_chapters:
                reason = "作品至少需要保留一章"
            return DirectoryDeleteImpact(
                node_kind=kind,
                node_id=node_id,
                title=str(row["title"]),
                descendant_chapters=len(chapter_ids),
                descendant_scenes=scene_count,
                references=self._reference_counts(connection, chapter_ids),
                can_delete=reason is None,
                reason=reason,
            )

    def delete_node(
        self, kind: NodeKind, node_id: str, request: DeleteDirectoryNodeRequest
    ) -> WorkspaceSummary:
        impact = self.delete_impact(kind, node_id)
        if not impact.can_delete:
            raise DirectoryConflictError(impact.reason or "cannot_delete")
        if not request.confirm_impact:
            raise DirectoryConfirmationRequiredError(node_id)
        timestamp = now_iso()
        with self.database.connect() as connection:
            row = self._active_row(connection, kind, node_id)
            if int(row["revision"]) != request.expected_revision:
                raise StaleRevisionError(str(row["revision"]))
            snapshots: list[dict[str, object]] = []
            targets: list[tuple[NodeKind, Row]] = [(kind, row)]
            if kind == "volume":
                chapters = connection.execute(
                    "SELECT * FROM chapters WHERE volume_id = ? AND deleted_at IS NULL",
                    (node_id,),
                ).fetchall()
                targets.extend(("chapter", item) for item in chapters)
                chapter_ids = [str(item["id"]) for item in chapters]
                if chapter_ids:
                    placeholders = ",".join("?" for _ in chapter_ids)
                    targets.extend(("scene", item) for item in connection.execute(
                        f"SELECT * FROM manuscript_scenes WHERE chapter_id IN ({placeholders}) "
                        "AND deleted_at IS NULL",
                        chapter_ids,
                    ).fetchall())
            elif kind == "chapter":
                targets.extend(("scene", item) for item in connection.execute(
                    "SELECT * FROM manuscript_scenes WHERE chapter_id = ? AND deleted_at IS NULL",
                    (node_id,),
                ).fetchall())
            for target_kind, target in targets:
                snapshots.append({
                    "kind": target_kind,
                    "id": str(target["id"]),
                    "revision": int(target["revision"]),
                })
                connection.execute(
                    f"UPDATE {self._table(target_kind)} SET deleted_at = ?, "
                    "revision = revision + 1, updated_at = ? WHERE id = ?",
                    (timestamp, timestamp, target["id"]),
                )
            project_id = str(row["project_id"])
            self._record_event(
                connection, project_id=project_id, action="delete", kind=kind,
                node_id=node_id, payload={"snapshots": snapshots}, timestamp=timestamp,
            )
            self._touch_project(connection, project_id, timestamp)
        return self.projects.get_workspace_summary(project_id)

    def list_events(self, project_id: str) -> list[DirectoryEvent]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, project_id, action, node_kind, node_id, undone_at, created_at "
                "FROM directory_events WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT 30",
                (project_id,),
            ).fetchall()
        return [DirectoryEvent.model_validate(dict(row)) for row in rows]

    def undo_latest(self, project_id: str) -> WorkspaceSummary:
        timestamp = now_iso()
        with self.database.connect() as connection:
            event = connection.execute(
                "SELECT * FROM directory_events WHERE project_id = ? AND undone_at IS NULL "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            if event is None:
                raise NotFoundError(project_id)
            kind = str(event["node_kind"])
            if kind not in {"volume", "chapter", "scene"}:
                raise DirectoryConflictError("invalid_event")
            node_kind: NodeKind = kind  # type: ignore[assignment]
            payload = json.loads(str(event["payload_json"]))
            row = connection.execute(
                f"SELECT * FROM {self._table(node_kind)} WHERE id = ?",
                (event["node_id"],),
            ).fetchone()
            if row is None:
                raise DirectoryConflictError("node_missing")
            action = str(event["action"])
            if action == "create":
                if row["deleted_at"] is not None or int(row["revision"]) != int(payload["created_revision"]):
                    raise DirectoryConflictError("node_changed_after_event")
                connection.execute(
                    f"UPDATE {self._table(node_kind)} SET deleted_at = ?, revision = revision + 1, "
                    "updated_at = ? WHERE id = ?",
                    (timestamp, timestamp, row["id"]),
                )
            elif action == "rename":
                before = payload["before"]
                if int(row["revision"]) != int(before["revision"]) + 1:
                    raise DirectoryConflictError("node_changed_after_event")
                if node_kind == "scene":
                    connection.execute(
                        "UPDATE manuscript_scenes SET title = ?, summary = ?, revision = revision + 1, "
                        "updated_at = ? WHERE id = ?",
                        (before["title"], before["summary"], timestamp, row["id"]),
                    )
                else:
                    connection.execute(
                        f"UPDATE {self._table(node_kind)} SET title = ?, revision = revision + 1, "
                        "updated_at = ? WHERE id = ?",
                        (before["title"], timestamp, row["id"]),
                    )
            elif action == "move":
                before = payload["before"]
                if int(row["revision"]) != int(before["revision"]) + 1:
                    raise DirectoryConflictError("node_changed_after_event")
                if node_kind == "chapter":
                    parent = self._active_row(connection, "volume", str(before["parent_id"]))
                    connection.execute(
                        "UPDATE chapters SET volume_id = ?, volume_number = ?, sort_key = ?, "
                        "revision = revision + 1, updated_at = ? WHERE id = ?",
                        (parent["id"], parent["volume_number"], before["sort_key"], timestamp, row["id"]),
                    )
                elif node_kind == "scene":
                    self._active_row(connection, "chapter", str(before["parent_id"]))
                    connection.execute(
                        "UPDATE manuscript_scenes SET chapter_id = ?, sort_key = ?, "
                        "revision = revision + 1, updated_at = ? WHERE id = ?",
                        (before["parent_id"], before["sort_key"], timestamp, row["id"]),
                    )
                else:
                    connection.execute(
                        "UPDATE manuscript_volumes SET sort_key = ?, revision = revision + 1, "
                        "updated_at = ? WHERE id = ?",
                        (before["sort_key"], timestamp, row["id"]),
                    )
            elif action == "delete":
                for snapshot in payload["snapshots"]:
                    target_kind = str(snapshot["kind"])
                    if target_kind not in {"volume", "chapter", "scene"}:
                        raise DirectoryConflictError("invalid_snapshot")
                    typed_kind: NodeKind = target_kind  # type: ignore[assignment]
                    current = connection.execute(
                        f"SELECT revision, deleted_at FROM {self._table(typed_kind)} WHERE id = ?",
                        (snapshot["id"],),
                    ).fetchone()
                    if (
                        current is None
                        or current["deleted_at"] is None
                        or int(current["revision"]) != int(snapshot["revision"]) + 1
                    ):
                        raise DirectoryConflictError("node_changed_after_event")
                for snapshot in payload["snapshots"]:
                    target_kind = str(snapshot["kind"])
                    typed_kind = target_kind  # type: ignore[assignment]
                    connection.execute(
                        f"UPDATE {self._table(typed_kind)} SET deleted_at = NULL, "
                        "revision = revision + 1, updated_at = ? WHERE id = ?",
                        (timestamp, snapshot["id"]),
                    )
            else:
                raise DirectoryConflictError("invalid_event")
            connection.execute(
                "UPDATE directory_events SET undone_at = ? WHERE id = ? AND undone_at IS NULL",
                (timestamp, event["id"]),
            )
            self._touch_project(connection, project_id, timestamp)
        return self.projects.get_workspace_summary(project_id)
