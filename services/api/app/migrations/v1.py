import sqlite3


def upgrade(connection: sqlite3.Connection, schema: str) -> None:
    """Create the supported legacy business schema for a new or unversioned database."""
    connection.executescript(schema)
