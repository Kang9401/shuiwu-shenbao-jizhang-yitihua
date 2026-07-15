import sqlite3

from sqlalchemy import create_engine

from app.core.version import SCHEMA_VERSION
from app.db.migrations import current_schema_version, run_migrations


def test_migrations_upgrade_legacy_jobs_table(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                workflow_code VARCHAR(80) NOT NULL,
                status VARCHAR(32) NOT NULL,
                input_file_ids JSON NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO jobs (id, workflow_code, status, input_file_ids) VALUES (1, 'broker_tax', 'success', '[]')"
        )
    engine = create_engine(f"sqlite:///{database.as_posix()}")

    assert run_migrations(engine) == SCHEMA_VERSION

    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
        row = connection.execute(
            "SELECT operation, app_version, ruleset_version FROM jobs WHERE id = 1"
        ).fetchone()
    assert {"operation", "app_version", "ruleset_version"}.issubset(columns)
    assert row[0] == "generate"
    assert current_schema_version(engine) == SCHEMA_VERSION

