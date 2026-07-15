from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import Engine

from app.core.version import APP_VERSION, RULESET_VERSION, SCHEMA_VERSION
from app.services.backup import create_backup


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()}


def _ensure_schema_version_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_schema_version (
            id INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL,
            app_version VARCHAR(32) NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """
    )


def _schema_version(connection: sqlite3.Connection) -> int:
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'app_schema_version'"
    ).fetchone()
    if table is None:
        return 0
    row = connection.execute("SELECT version FROM app_schema_version WHERE id = 1").fetchone()
    return int(row[0]) if row else 0


def _migration_1(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tax_monthly_artifacts (
            id INTEGER NOT NULL PRIMARY KEY,
            period_id INTEGER NOT NULL,
            artifact_type VARCHAR(80) NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            stored_path VARCHAR(500) NOT NULL,
            source_session_id INTEGER,
            source_round_number INTEGER,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT uq_tax_monthly_artifact_period_type UNIQUE (period_id, artifact_type),
            FOREIGN KEY(period_id) REFERENCES periods (id)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS ix_tax_monthly_artifacts_id ON tax_monthly_artifacts (id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_tax_monthly_artifacts_period_id ON tax_monthly_artifacts (period_id)")


def _migration_2(connection: sqlite3.Connection) -> None:
    columns = _table_columns(connection, "jobs")
    additions = {
        "operation": "VARCHAR(40) NOT NULL DEFAULT 'generate'",
        "app_version": f"VARCHAR(32) NOT NULL DEFAULT '{APP_VERSION}'",
        "ruleset_version": f"VARCHAR(32) NOT NULL DEFAULT '{RULESET_VERSION}'",
    }
    for column, declaration in additions.items():
        if column not in columns:
            connection.execute(f'ALTER TABLE jobs ADD COLUMN "{column}" {declaration}')
    connection.execute("CREATE INDEX IF NOT EXISTS ix_jobs_operation ON jobs (operation)")


MIGRATIONS = {1: _migration_1, 2: _migration_2}


def run_migrations(engine: Engine, *, backup_existing: bool = False) -> int:
    if engine.url.get_backend_name() != "sqlite":
        return SCHEMA_VERSION
    database = engine.url.database
    if not database or database == ":memory:":
        return SCHEMA_VERSION
    path = Path(database).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as connection:
        _ensure_schema_version_table(connection)
        current = _schema_version(connection)
    if current >= SCHEMA_VERSION:
        return current
    if backup_existing and path.exists() and path.stat().st_size:
        create_backup("pre_upgrade", database_file=path, data_root=path.parent)
    with sqlite3.connect(str(path)) as connection:
        _ensure_schema_version_table(connection)
        current = _schema_version(connection)
        for version in range(current + 1, SCHEMA_VERSION + 1):
            migration = MIGRATIONS.get(version)
            if migration is None:
                raise RuntimeError(f"缺少数据库迁移版本 {version}")
            migration(connection)
            connection.execute(
                """
                INSERT INTO app_schema_version (id, version, app_version, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    version = excluded.version,
                    app_version = excluded.app_version,
                    updated_at = excluded.updated_at
                """,
                (version, APP_VERSION, datetime.utcnow().isoformat()),
            )
            connection.commit()
    return SCHEMA_VERSION


def current_schema_version(engine: Engine) -> int:
    if engine.url.get_backend_name() != "sqlite":
        return SCHEMA_VERSION
    database = engine.url.database
    if not database or database == ":memory:" or not Path(database).exists():
        return 0
    with sqlite3.connect(str(Path(database).resolve())) as connection:
        return _schema_version(connection)
