from __future__ import annotations

import sqlite3
import hashlib
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


def _migration_3(connection: sqlite3.Connection) -> None:
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'organization_mappings'"
    ).fetchone()
    if table is None:
        return
    columns = _table_columns(connection, "organization_mappings")
    additions = {
        "rpa_enabled": "INTEGER NOT NULL DEFAULT 0",
        "rpa_org_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        "parent_branch": "VARCHAR(255) NOT NULL DEFAULT ''",
    }
    for column, declaration in additions.items():
        if column not in columns:
            connection.execute(f'ALTER TABLE organization_mappings ADD COLUMN "{column}" {declaration}')


def _migration_4(connection: sqlite3.Connection) -> None:
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'organization_mappings'"
    ).fetchone()
    if table is None:
        return
    columns = _table_columns(connection, "organization_mappings")
    if "taxpayer_id" not in columns:
        connection.execute(
            'ALTER TABLE organization_mappings ADD COLUMN "taxpayer_id" VARCHAR(64) NOT NULL DEFAULT \'\''
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_mappings_taxpayer_id "
        "ON organization_mappings (taxpayer_id)"
    )


def _migration_5(connection: sqlite3.Connection) -> None:
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'organization_mappings'"
    ).fetchone()
    if table is None:
        return
    connection.execute(
        """
        DELETE FROM organization_mappings
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM organization_mappings
            GROUP BY org_code
        )
        """
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_mapping_org_code "
        "ON organization_mappings (org_code)"
    )


def _has_legacy_business_data(connection: sqlite3.Connection) -> bool:
    for table in ("periods", "uploaded_files", "jobs", "organization_mappings", "verification_sessions"):
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if exists and connection.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone():
            return True
    return False


def _rebuild_company_unique_tables(connection: sqlite3.Connection) -> None:
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'periods'"
    ).fetchone():
        connection.execute(
            """
        CREATE TABLE periods_company_new (
            id INTEGER NOT NULL PRIMARY KEY,
            company_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            name VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT uq_period_company_year_month UNIQUE (company_id, year, month),
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )
            """
        )
        connection.execute(
            "INSERT INTO periods_company_new (id, company_id, year, month, name, status, created_at) "
            "SELECT id, company_id, year, month, name, status, created_at FROM periods"
        )
        connection.execute("DROP TABLE periods")
        connection.execute("ALTER TABLE periods_company_new RENAME TO periods")
        connection.execute("CREATE INDEX ix_periods_id ON periods (id)")
        connection.execute("CREATE INDEX ix_periods_company_id ON periods (company_id)")

    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'organization_mappings'"
    ).fetchone() is None:
        return
    connection.execute(
        """
        CREATE TABLE organization_mappings_company_new (
            id INTEGER NOT NULL PRIMARY KEY,
            company_id INTEGER NOT NULL,
            branch_name VARCHAR(255) NOT NULL,
            org_code VARCHAR(20) NOT NULL,
            taxpayer_id VARCHAR(64) NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            rpa_enabled INTEGER NOT NULL DEFAULT 0,
            rpa_org_name VARCHAR(255) NOT NULL DEFAULT '',
            rpa_search_result_index INTEGER NOT NULL DEFAULT 1,
            parent_branch VARCHAR(255) NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT uq_organization_mapping_company_branch_name UNIQUE (company_id, branch_name),
            CONSTRAINT uq_organization_mapping_company_org_code UNIQUE (company_id, org_code),
            FOREIGN KEY(company_id) REFERENCES companies(id)
        )
        """
    )
    columns = _table_columns(connection, "organization_mappings")
    expressions = {
        "taxpayer_id": "taxpayer_id" if "taxpayer_id" in columns else "''",
        "active": "active" if "active" in columns else "1",
        "rpa_enabled": "rpa_enabled" if "rpa_enabled" in columns else "0",
        "rpa_org_name": "rpa_org_name" if "rpa_org_name" in columns else "''",
        "rpa_search_result_index": "rpa_search_result_index" if "rpa_search_result_index" in columns else "1",
        "parent_branch": "parent_branch" if "parent_branch" in columns else "''",
        "created_at": "created_at" if "created_at" in columns else "CURRENT_TIMESTAMP",
        "updated_at": "updated_at" if "updated_at" in columns else "CURRENT_TIMESTAMP",
    }
    connection.execute(
        f"""
        INSERT INTO organization_mappings_company_new (
            id, company_id, branch_name, org_code, taxpayer_id, active, rpa_enabled,
            rpa_org_name, rpa_search_result_index, parent_branch, created_at, updated_at
        )
        SELECT id, company_id, branch_name, org_code, {expressions['taxpayer_id']}, {expressions['active']},
               {expressions['rpa_enabled']}, {expressions['rpa_org_name']}, {expressions['rpa_search_result_index']}, {expressions['parent_branch']},
               {expressions['created_at']}, {expressions['updated_at']}
        FROM organization_mappings
        """
    )
    connection.execute("DROP TABLE organization_mappings")
    connection.execute("ALTER TABLE organization_mappings_company_new RENAME TO organization_mappings")
    for column in ("id", "company_id", "branch_name", "org_code", "taxpayer_id"):
        connection.execute(
            f"CREATE INDEX ix_organization_mappings_{column} ON organization_mappings ({column})"
        )
    connection.execute(
        "CREATE UNIQUE INDEX uq_organization_mapping_org_code "
        "ON organization_mappings (company_id, org_code)"
    )


def _migration_6(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(120) NOT NULL UNIQUE,
            code VARCHAR(60) NOT NULL UNIQUE,
            operator_name VARCHAR(120) NOT NULL,
            notes VARCHAR(500) NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """
    )
    has_legacy_data = _has_legacy_business_data(connection)
    if has_legacy_data and connection.execute("SELECT 1 FROM companies LIMIT 1").fetchone() is None:
        now = datetime.utcnow().isoformat()
        connection.execute(
            """
            INSERT INTO companies (id, name, code, operator_name, notes, active, created_at, updated_at)
            VALUES (1, '默认分公司', 'DEFAULT', '待完善', '由旧版本数据自动迁移', 1, ?, ?)
            """,
            (now, now),
        )

    scoped_tables = (
        "periods",
        "uploaded_files",
        "jobs",
        "artifacts",
        "invoice_ledgers",
        "certification_ledgers",
        "voucher_drafts",
        "personnel_master_artifacts",
        "personnel_master_import_batches",
        "reconciliation_import_batches",
        "reconciliation_import_rows",
        "organization_mappings",
        "verification_sessions",
        "verification_rounds",
        "tax_monthly_artifacts",
    )
    for table in scoped_tables:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if exists and "company_id" not in _table_columns(connection, table):
            connection.execute(
                f'ALTER TABLE "{table}" ADD COLUMN company_id INTEGER NOT NULL DEFAULT 1 REFERENCES companies(id)'
            )
        if exists:
            connection.execute(f'CREATE INDEX IF NOT EXISTS ix_{table}_company_id ON "{table}" (company_id)')

    _rebuild_company_unique_tables(connection)


def _migration_7(connection: sqlite3.Connection) -> None:
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'organization_mappings'"
    ).fetchone()
    if table is None:
        return
    if "rpa_search_result_index" not in _table_columns(connection, "organization_mappings"):
        connection.execute(
            'ALTER TABLE organization_mappings ADD COLUMN "rpa_search_result_index" INTEGER NOT NULL DEFAULT 1'
        )


def _migration_8(connection: sqlite3.Connection) -> None:
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'tax_monthly_artifacts'"
    ).fetchone()
    if table is None:
        return
    columns = _table_columns(connection, "tax_monthly_artifacts")
    if "file_content" not in columns:
        connection.execute('ALTER TABLE tax_monthly_artifacts ADD COLUMN "file_content" BLOB')
    if "content_sha256" not in columns:
        connection.execute('ALTER TABLE tax_monthly_artifacts ADD COLUMN "content_sha256" VARCHAR(64)')
    rows = connection.execute(
        "SELECT id, stored_path FROM tax_monthly_artifacts "
        "WHERE file_content IS NULL AND stored_path IS NOT NULL"
    ).fetchall()
    for artifact_id, stored_path in rows:
        path = Path(str(stored_path))
        if not path.is_file():
            continue
        content = path.read_bytes()
        connection.execute(
            "UPDATE tax_monthly_artifacts SET file_content = ?, content_sha256 = ? WHERE id = ?",
            (content, hashlib.sha256(content).hexdigest(), artifact_id),
        )


MIGRATIONS = {
    1: _migration_1,
    2: _migration_2,
    3: _migration_3,
    4: _migration_4,
    5: _migration_5,
    6: _migration_6,
    7: _migration_7,
    8: _migration_8,
}


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
