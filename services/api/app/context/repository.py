import json
from datetime import UTC, datetime
from sqlite3 import Connection, IntegrityError, Row
from uuid import uuid4

from app.context.models import (
    ContextDirective,
    ContextDirectiveAction,
    ContextDirectiveRequest,
    ContextPacket,
)
from app.database import Database


class ContextPacketNotFoundError(LookupError):
    pass


class InvalidContextPacketError(ValueError):
    pass


class ContextDirectiveNotFoundError(LookupError):
    pass


class InvalidContextDirectiveError(ValueError):
    pass


class StaleContextDirectiveError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class ContextRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def put_packet(self, packet: ContextPacket) -> ContextPacket:
        packet_json = json.dumps(
            packet.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            with self.database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO context_packets (
                        id, project_id, chapter_id, chapter_revision, task_type,
                        compiler_version, token_budget, used_tokens, overflow_tokens,
                        packet_sha256, source_fingerprint_sha256, packet_json,
                        rendered_context, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        packet.id,
                        packet.project_id,
                        packet.chapter_id,
                        packet.chapter_revision,
                        packet.task_type.value,
                        packet.compiler_version,
                        packet.token_budget,
                        packet.used_tokens,
                        packet.overflow_tokens,
                        packet.packet_sha256,
                        packet.source_fingerprint_sha256,
                        packet_json,
                        packet.rendered_context,
                        packet.created_at,
                    ),
                )
        except IntegrityError:
            existing = self.get_packet(packet.id)
            if (
                existing.packet_sha256 != packet.packet_sha256
                or existing.rendered_context != packet.rendered_context
            ):
                raise RuntimeError("上下文包标识冲突，未覆盖已有快照") from None
            return existing
        return packet

    def get_packet(self, packet_id: str) -> ContextPacket:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT packet_json FROM context_packets WHERE id = ?",
                (packet_id,),
            ).fetchone()
        if row is None:
            raise ContextPacketNotFoundError(packet_id)
        return ContextPacket.model_validate_json(row["packet_json"])

    def list_packets(self, chapter_id: str, *, limit: int = 20) -> list[ContextPacket]:
        if not 1 <= limit <= 100:
            raise ValueError("上下文包列表范围无效")
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT packet_json FROM context_packets
                WHERE chapter_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (chapter_id, limit),
            ).fetchall()
        return [ContextPacket.model_validate_json(row["packet_json"]) for row in rows]

    def list_directives(self, chapter_id: str) -> list[ContextDirective]:
        with self.database.connect() as connection:
            self._chapter_project(connection, chapter_id)
            rows = connection.execute(
                """
                SELECT * FROM context_directives
                WHERE chapter_id = ?
                ORDER BY source_kind, source_id
                """,
                (chapter_id,),
            ).fetchall()
        return [self._directive(row) for row in rows]

    def set_directive(
        self,
        chapter_id: str,
        request: ContextDirectiveRequest,
    ) -> ContextDirective:
        if request.source_kind in {"security", "author_intent", "project", "current_chapter"}:
            raise InvalidContextDirectiveError("硬约束不能固定或排除")
        timestamp = _now_iso()
        with self.database.connect() as connection:
            project_id = self._chapter_project(connection, chapter_id)
            self._validate_source(
                connection,
                project_id=project_id,
                chapter_id=chapter_id,
                source_kind=request.source_kind,
                source_id=request.source_id,
            )
            existing = connection.execute(
                """
                SELECT * FROM context_directives
                WHERE chapter_id = ? AND source_kind = ? AND source_id = ?
                """,
                (chapter_id, request.source_kind, request.source_id),
            ).fetchone()
            if existing is None:
                if request.expected_revision is not None:
                    raise StaleContextDirectiveError("上下文指令不存在")
                directive_id = str(uuid4())
                connection.execute(
                    """
                    INSERT INTO context_directives (
                        id, project_id, chapter_id, source_kind, source_id,
                        action, revision, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        directive_id,
                        project_id,
                        chapter_id,
                        request.source_kind,
                        request.source_id,
                        request.action.value,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                if request.action.value == existing["action"]:
                    return self._directive(existing)
                if request.expected_revision != existing["revision"]:
                    raise StaleContextDirectiveError("上下文指令已更新")
                directive_id = existing["id"]
                result = connection.execute(
                    """
                    UPDATE context_directives
                    SET action = ?, revision = revision + 1, updated_at = ?
                    WHERE id = ? AND revision = ?
                    """,
                    (
                        request.action.value,
                        timestamp,
                        directive_id,
                        request.expected_revision,
                    ),
                )
                if result.rowcount != 1:
                    raise StaleContextDirectiveError("上下文指令已更新")
            row = connection.execute(
                "SELECT * FROM context_directives WHERE id = ?",
                (directive_id,),
            ).fetchone()
        if row is None:
            raise ContextDirectiveNotFoundError(directive_id)
        return self._directive(row)

    def delete_directive(self, directive_id: str, expected_revision: int) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT revision FROM context_directives WHERE id = ?",
                (directive_id,),
            ).fetchone()
            if row is None:
                raise ContextDirectiveNotFoundError(directive_id)
            if row["revision"] != expected_revision:
                raise StaleContextDirectiveError("上下文指令已更新")
            result = connection.execute(
                "DELETE FROM context_directives WHERE id = ? AND revision = ?",
                (directive_id, expected_revision),
            )
            if result.rowcount != 1:
                raise StaleContextDirectiveError("上下文指令已更新")

    @staticmethod
    def _chapter_project(connection: Connection, chapter_id: str) -> str:
        row = connection.execute(
            "SELECT project_id FROM chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
        if row is None:
            raise ContextDirectiveNotFoundError(chapter_id)
        return str(row["project_id"])

    @staticmethod
    def _validate_source(
        connection: Connection,
        *,
        project_id: str,
        chapter_id: str,
        source_kind: str,
        source_id: str,
    ) -> None:
        source_tables = {
            "chapter": ("chapters", "project_id"),
            "fact": ("story_facts", "project_id"),
            "entity": ("story_entities", "project_id"),
            "thread": ("story_threads", "project_id"),
            "timeline": ("timeline_events", "project_id"),
            "future_knowledge": ("future_knowledge", "project_id"),
            "source_card": ("source_cards", "project_id"),
            "blueprint": ("reference_pattern_applications", "project_id"),
        }
        target = source_tables.get(source_kind)
        if target is None:
            raise InvalidContextDirectiveError("上下文来源类型无效")
        if source_kind == "chapter" and source_id == chapter_id:
            raise InvalidContextDirectiveError("当前章节是硬约束，不能固定或排除")
        table, project_column = target
        row = connection.execute(
            f"SELECT 1 FROM {table} WHERE id = ? AND {project_column} = ?",
            (source_id, project_id),
        ).fetchone()
        if row is None:
            raise InvalidContextDirectiveError("上下文来源不存在或不属于当前作品")

    @staticmethod
    def _directive(row: Row) -> ContextDirective:
        return ContextDirective(
            id=row["id"],
            project_id=row["project_id"],
            chapter_id=row["chapter_id"],
            source_kind=row["source_kind"],
            source_id=row["source_id"],
            action=ContextDirectiveAction(row["action"]),
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
