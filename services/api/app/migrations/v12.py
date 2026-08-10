import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

APPLICATION_COLUMNS = {
    "blueprint_json": "TEXT",
    "originality_status": "TEXT NOT NULL DEFAULT 'needs_check'",
    "risk_level": "TEXT",
    "latest_report_id": "TEXT",
    "threshold_version": "TEXT",
    "revision": "INTEGER NOT NULL DEFAULT 0",
    "updated_at": "TEXT",
}


def _legacy_blueprint(row: sqlite3.Row) -> str:
    proposal = json.loads(row["proposal_json"])
    dimensions = json.loads(row["dimensions_json"])
    selected = json.loads(row["selected_dimensions_json"])
    blueprint_dimensions = {
        dimension: {
            "source": proposal[dimension],
            "mode": "preserve",
            "author_edits": row["application_note"],
            "generated_variant": dimensions[dimension],
            "version": 1,
            "locked": False,
            "named_entities": [],
            "source_beats": [],
            "key_beats": [],
        }
        for dimension in selected
    }
    return json.dumps(
        {
            "dimensions": blueprint_dimensions,
            "relationship": {
                "source": proposal["relationship_recomposition"],
                "mode": "preserve",
                "author_edits": row["application_note"],
                "generated_variant": row["relationship_recomposition"],
                "version": 1,
                "locked": False,
                "relationships": [],
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Turn applied patterns into versioned blueprints gated by originality reports."""
    connection.executescript(schema)
    previous_row_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(reference_pattern_applications)")
    }
    for name, definition in APPLICATION_COLUMNS.items():
        if name not in columns:
            connection.execute(
                f"ALTER TABLE reference_pattern_applications ADD COLUMN {name} {definition}"
            )
    rows = connection.execute(
        """
        SELECT a.*, c.proposal_json
        FROM reference_pattern_applications a
        JOIN reference_pattern_cards c ON c.id = a.pattern_card_id
        WHERE a.blueprint_json IS NULL OR a.blueprint_json = ''
        """
    ).fetchall()
    for row in rows:
        blueprint_json = _legacy_blueprint(row)
        updated_at = row["updated_at"] or row["created_at"]
        connection.execute(
            """
            UPDATE reference_pattern_applications
            SET blueprint_json = ?, originality_status = 'needs_check',
                revision = 0, updated_at = ?
            WHERE id = ?
            """,
            (blueprint_json, updated_at, row["id"]),
        )
        connection.execute(
            """
            INSERT INTO reference_blueprint_versions (
                id, application_id, blueprint_revision, blueprint_json,
                changed_dimensions_json, relationship_changed, created_at
            ) VALUES (?, ?, 0, ?, ?, 1, ?)
            ON CONFLICT(application_id, blueprint_revision) DO NOTHING
            """,
            (
                str(uuid4()),
                row["id"],
                blueprint_json,
                row["selected_dimensions_json"],
                updated_at,
            ),
        )
    connection.execute(
        """
        UPDATE reference_pattern_applications
        SET updated_at = created_at
        WHERE updated_at IS NULL
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (12, "versioned_originality_blueprints", datetime.now(UTC).isoformat()),
    )
    connection.row_factory = previous_row_factory
