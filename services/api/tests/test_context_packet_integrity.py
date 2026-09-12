import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.context import (
    ContextPacket,
    ContextRepository,
    CreativeContextCompileRequest,
    CreativeContextPurpose,
    CreativeContextService,
    CreativeContextSubject,
    CreativeContextSubjectKind,
    InvalidContextPacketError,
)
from app.database import Database
from app.models import CreateProjectRequest, Genre
from app.repository import ProjectRepository


def _compiled_packet(tmp_path: Path) -> tuple[Database, ContextPacket]:
    database = Database(tmp_path / "context-integrity.db")
    database.initialize()
    projects = ProjectRepository(database)
    workspace = projects.create_project(
        CreateProjectRequest(
            title="南平回潮",
            genre=Genre.URBAN_REBIRTH,
            rebirth_year=1998,
            rebirth_location="福建南平",
        )
    )
    packet = CreativeContextService(
        projects,
        ContextRepository(database),
    ).compile(
        workspace,
        CreativeContextCompileRequest(
            purpose=CreativeContextPurpose.STARTUP,
            subject=CreativeContextSubject(
                kind=CreativeContextSubjectKind.PROJECT,
                id=workspace.project.id,
            ),
            token_budget=8_000,
            author_intent="从家庭危机切入产业线",
        ),
    )
    return database, packet


def test_artifact_packet_rejects_tampered_item_content(tmp_path: Path) -> None:
    _database, packet = _compiled_packet(tmp_path)
    payload = packet.model_dump(mode="json")
    payload["items"][0]["content"] = "被篡改的创作资料"

    with pytest.raises(ValidationError, match="上下文条目内容指纹不匹配"):
        type(packet).model_validate_json(json.dumps(payload, ensure_ascii=False))


def test_artifact_packet_rejects_rendered_context_not_derived_from_items(
    tmp_path: Path,
) -> None:
    _database, packet = _compiled_packet(tmp_path)
    payload = packet.model_dump(mode="json")
    payload["rendered_context"] = '{"creative_context":{"purpose":"draft"}}'

    with pytest.raises(ValidationError, match="上下文渲染内容与条目快照不匹配"):
        type(packet).model_validate(payload)


def test_artifact_packet_recomputes_source_fingerprint(tmp_path: Path) -> None:
    _database, packet = _compiled_packet(tmp_path)
    payload = packet.model_dump(mode="json")
    payload["source_fingerprint_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="上下文来源指纹不匹配"):
        type(packet).model_validate(payload)


def test_artifact_packet_recomputes_packet_fingerprint(tmp_path: Path) -> None:
    _database, packet = _compiled_packet(tmp_path)
    payload = packet.model_dump(mode="json")
    payload["packet_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="上下文包指纹不匹配"):
        type(packet).model_validate(payload)


def test_repository_rejects_sql_columns_that_disagree_with_packet_json(
    tmp_path: Path,
) -> None:
    database, packet = _compiled_packet(tmp_path)
    with database.connect() as connection:
        connection.execute(
            "UPDATE context_packets SET rendered_context = ? WHERE id = ?",
            ('{"tampered":true}', packet.id),
        )

    with pytest.raises(InvalidContextPacketError, match="context_packet_storage_mismatch"):
        ContextRepository(database).get_packet(packet.id)


def test_repository_stops_tampered_packet_before_any_adapter_call(tmp_path: Path) -> None:
    database, packet = _compiled_packet(tmp_path)
    payload = packet.model_dump(mode="json")
    payload["packet_sha256"] = "0" * 64
    with database.connect() as connection:
        connection.execute(
            "UPDATE context_packets SET packet_json = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False), packet.id),
        )

    adapter_calls = 0
    with pytest.raises(InvalidContextPacketError, match="context_packet_integrity_invalid"):
        ContextRepository(database).get_packet(packet.id)
        adapter_calls += 1
    assert adapter_calls == 0
