import sqlite3
from datetime import UTC, datetime

SOURCE_CARD_COLUMNS = {
    "source_document_id": "TEXT REFERENCES source_documents(id) ON DELETE SET NULL",
    "source_date": "TEXT CHECK(source_date IS NULL OR length(source_date) <= 40)",
    "page_number_start": "INTEGER CHECK(page_number_start IS NULL OR page_number_start > 0)",
    "page_number_end": "INTEGER CHECK(page_number_end IS NULL OR page_number_end >= page_number_start)",
    "start_char": "INTEGER CHECK(start_char IS NULL OR start_char >= 0)",
    "end_char": "INTEGER CHECK(end_char IS NULL OR end_char > start_char)",
}


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Add isolated global reality documents and candidate-card provenance."""
    connection.executescript(schema)
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(source_cards)")}
    for name, definition in SOURCE_CARD_COLUMNS.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE source_cards ADD COLUMN {name} {definition}")
    connection.execute(
        "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (11, "global_reality_sources", datetime.now(UTC).isoformat()),
    )
