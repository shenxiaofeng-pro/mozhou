import sqlite3

CHAPTER_BRIEF_COLUMNS = {
    "reader_promise": "TEXT NOT NULL DEFAULT ''",
    "opening_hook": "TEXT NOT NULL DEFAULT ''",
    "state_change": "TEXT NOT NULL DEFAULT ''",
    "emotional_payoff": "TEXT NOT NULL DEFAULT ''",
    "ending_cliffhanger": "TEXT NOT NULL DEFAULT ''",
}

GENERATION_RUN_COLUMNS = {
    "provider": "TEXT NOT NULL DEFAULT 'demo'",
    "model": "TEXT NOT NULL DEFAULT 'replay-v1'",
}


def _add_missing_columns(
    connection: sqlite3.Connection,
    table: str,
    definitions: dict[str, str],
) -> None:
    columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, definition in definitions.items():
        if name not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Complete the v2 tables and add chapter brief plus AI provenance columns."""
    connection.executescript(schema)
    _add_missing_columns(connection, "chapters", CHAPTER_BRIEF_COLUMNS)
    _add_missing_columns(connection, "generation_runs", GENERATION_RUN_COLUMNS)
