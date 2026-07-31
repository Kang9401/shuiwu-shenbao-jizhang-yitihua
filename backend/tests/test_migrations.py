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


def test_migrations_add_rpa_fields_to_organization_mappings(tmp_path):
    database = tmp_path / "legacy_mappings.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE organization_mappings (
                id INTEGER PRIMARY KEY,
                branch_name VARCHAR(255) NOT NULL,
                org_code VARCHAR(20) NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO organization_mappings VALUES (1, '测试营业部', '12345', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            """
            CREATE TABLE app_schema_version (
                id INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL,
                app_version VARCHAR(32) NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO app_schema_version VALUES (1, 2, '0.9.0', CURRENT_TIMESTAMP)"
        )
    engine = create_engine(f"sqlite:///{database.as_posix()}")

    assert run_migrations(engine) == SCHEMA_VERSION

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT rpa_enabled, rpa_org_name, parent_branch, taxpayer_id "
            "FROM organization_mappings WHERE id = 1"
        ).fetchone()
    assert row == (0, "", "", "")


def test_migration_5_deduplicates_org_codes_and_adds_unique_index(tmp_path):
    database = tmp_path / "duplicate_org_codes.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE organization_mappings (id INTEGER PRIMARY KEY, branch_name TEXT, org_code TEXT)")
        connection.execute("INSERT INTO organization_mappings VALUES (1, '旧记录', '10001')")
        connection.execute("INSERT INTO organization_mappings VALUES (2, '新记录', '10001')")
        connection.execute("CREATE TABLE app_schema_version (id INTEGER PRIMARY KEY, version INTEGER, app_version TEXT, updated_at DATETIME)")
        connection.execute("INSERT INTO app_schema_version VALUES (1, 4, '0.9.0', CURRENT_TIMESTAMP)")
    engine = create_engine(f"sqlite:///{database.as_posix()}")

    assert run_migrations(engine) == SCHEMA_VERSION
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id, branch_name, org_code FROM organization_mappings").fetchall() == [(2, "新记录", "10001")]
        indexes = connection.execute("PRAGMA index_list(organization_mappings)").fetchall()
    assert any(row[1] == "uq_organization_mapping_org_code" and row[2] == 1 for row in indexes)

