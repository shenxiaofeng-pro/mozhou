import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from app.context import (
    ContextItemKind,
    ContextRepository,
    CreativeContextCompileRequest,
    CreativeContextPurpose,
    CreativeContextService,
    CreativeContextSubject,
    CreativeContextSubjectKind,
)
from app.database import Database
from app.models import CreateProjectRequest, Genre
from app.repository import ProjectRepository


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def test_only_confirmed_compact_feedback_enters_creative_context(tmp_path: Path) -> None:
    database = Database(tmp_path / "canon-context.db")
    database.initialize()
    projects = ProjectRepository(database)
    workspace = projects.create_project(
        CreateProjectRequest(
            title="归来仍是剑修",
            genre=Genre.EASTERN_FANTASY,
            rebirth_year=2026,
            rebirth_location="南平",
        )
    )
    chapter = workspace.chapters[0]
    now = datetime.now(UTC).isoformat()
    canon_payload = {
        "character_name": "沈砚",
        "system": "修炼",
        "rank": "筑基",
        "change": "突破筑基",
    }
    rule = "动作与转折处倾向短句，减少多层修饰。"
    rule_sha = sha256(rule.encode("utf-8")).hexdigest()
    preference_id = str(uuid4())
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO canon_records (
                id, project_id, kind, subject_key, payload_json, payload_sha256,
                revision, state, source_candidate_id, created_at, updated_at
            ) VALUES (?, ?, 'progression', '沈砚', ?, ?, 0, 'active', NULL, ?, ?)
            """,
            (
                str(uuid4()),
                workspace.project.id,
                json.dumps(canon_payload, ensure_ascii=False),
                _digest(canon_payload),
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO author_preferences (
                id, project_id, scope_kind, scope_value, dimension, compact_rule,
                rule_sha256, fingerprint_sha256, confidence, occurrence_count,
                state, revision, created_at, updated_at
            ) VALUES (?, ?, 'project', ?, 'sentence_style', ?, ?, ?, 0.72, 2,
                      'active', 0, ?, ?)
            """,
            (
                preference_id,
                workspace.project.id,
                workspace.project.id,
                rule,
                rule_sha,
                _digest(
                    {
                        "scope_kind": "project",
                        "scope_value": workspace.project.id,
                        "dimension": "sentence_style",
                        "rule_sha256": rule_sha,
                    }
                ),
                now,
                now,
            ),
        )

    service = CreativeContextService(projects, ContextRepository(database))
    request = CreativeContextCompileRequest(
        purpose=CreativeContextPurpose.DRAFT,
        subject=CreativeContextSubject(
            kind=CreativeContextSubjectKind.CHAPTER,
            id=chapter.id,
            revision=chapter.revision,
        ),
    )
    first = service.compile(projects.get_workspace(workspace.project.id), request)

    assert first.compiler_version == "creative-context-v2"
    assert first.dependency_snapshot.schema_version == 2
    assert first.dependency_snapshot.canon_state is not None
    assert first.dependency_snapshot.author_preference_state is not None
    kinds = {item.kind for item in first.items if item.included}
    assert ContextItemKind.CANON_RECORD in kinds
    assert ContextItemKind.AUTHOR_PREFERENCE in kinds
    preference_item = next(
        item for item in first.items if item.kind == ContextItemKind.AUTHOR_PREFERENCE
    )
    assert rule in preference_item.content
    assert "diff" not in preference_item.content.casefold()

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE author_preferences
            SET state = 'deleted', revision = revision + 1, updated_at = ?
            WHERE id = ?
            """,
            (datetime.now(UTC).isoformat(), preference_id),
        )
    second = service.compile(projects.get_workspace(workspace.project.id), request)

    assert second.packet_sha256 != first.packet_sha256
    assert second.dependency_fingerprint_sha256 != first.dependency_fingerprint_sha256
    assert all(item.kind != ContextItemKind.AUTHOR_PREFERENCE for item in second.items)
