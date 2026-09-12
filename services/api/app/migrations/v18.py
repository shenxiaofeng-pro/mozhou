import sqlite3
from datetime import UTC, datetime


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add scene-level semantic and plot-graph originality reports."""
    connection.executescript(schema)
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(originality_reports)").fetchall()
    }
    if "acknowledged_at" not in columns:
        connection.execute("ALTER TABLE originality_reports ADD COLUMN acknowledged_at TEXT")
    connection.execute(
        """
        UPDATE originality_reports
        SET acknowledged_at = (
            SELECT a.updated_at FROM reference_pattern_applications a
            WHERE a.latest_report_id = originality_reports.id
        )
        WHERE risk_level = 'medium'
          AND acknowledged_at IS NULL
          AND EXISTS (
              SELECT 1 FROM reference_pattern_applications a
              WHERE a.latest_report_id = originality_reports.id
                AND a.originality_status = 'passed'
          )
        """
    )
    connection.execute(
        """
        UPDATE reference_pattern_applications
        SET originality_status = 'needs_check'
        WHERE NOT EXISTS (
            SELECT 1 FROM scene_originality_checks s
            WHERE s.application_id = reference_pattern_applications.id
              AND s.blueprint_revision = reference_pattern_applications.revision
        )
        """
    )
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (18, "scene_plot_graph_originality", datetime.now(UTC).isoformat()),
    )
