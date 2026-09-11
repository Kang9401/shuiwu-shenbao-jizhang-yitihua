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
    with sqlite3.connect(database) as connection:
        pit_tables = {
            row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'pit_%'")
        }
    assert {"pit_reconciliation_workpapers", "pit_reconciliation_sources", "pit_declaration_summaries", "pit_tax_amount_checks", "pit_occurrence_checks", "pit_reconciliation_org_summaries", "pit_reconciliation_difference_details", "pit_bank_tax_matches"}.issubset(pit_tables)


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


def test_migration_8_backfills_monthly_artifact_content(tmp_path):
    database = tmp_path / "monthly_artifact.db"
    source = tmp_path / "底稿.xlsx"
    source.write_bytes(b"working-sheet-bytes")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE tax_monthly_artifacts (
                id INTEGER PRIMARY KEY,
                period_id INTEGER NOT NULL,
                artifact_type VARCHAR(80) NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                stored_path VARCHAR(500) NOT NULL,
                source_session_id INTEGER,
                source_round_number INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO tax_monthly_artifacts "
            "(id, period_id, artifact_type, file_name, stored_path, created_at, updated_at) "
            "VALUES (1, 1, 'working_sheet', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (source.name, str(source)),
        )
        connection.execute(
            "CREATE TABLE app_schema_version (id INTEGER PRIMARY KEY, version INTEGER, app_version TEXT, updated_at DATETIME)"
        )
        connection.execute("INSERT INTO app_schema_version VALUES (1, 7, '0.9.0', CURRENT_TIMESTAMP)")
    engine = create_engine(f"sqlite:///{database.as_posix()}")

    assert run_migrations(engine) == SCHEMA_VERSION
    with sqlite3.connect(database) as connection:
        content, digest = connection.execute(
            "SELECT file_content, content_sha256 FROM tax_monthly_artifacts WHERE id = 1"
        ).fetchone()
    assert content == source.read_bytes()
    assert len(digest) == 64


def test_migration_9_to_latest_adds_bank_subaccount_and_file_results(tmp_path):
    database = tmp_path / "v9.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE organization_mappings (id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, branch_name TEXT NOT NULL, org_code TEXT NOT NULL, taxpayer_id TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, rpa_enabled INTEGER NOT NULL DEFAULT 0, rpa_org_name TEXT NOT NULL DEFAULT '', rpa_search_result_index INTEGER NOT NULL DEFAULT 1, parent_branch TEXT NOT NULL DEFAULT '', created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)")
        connection.execute("INSERT INTO organization_mappings VALUES (1, 1, '保留机构', '10001', '', 1, 0, '', 1, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute("CREATE TABLE reconciliation_import_batches (id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, period_id INTEGER NOT NULL, import_type TEXT NOT NULL, original_name TEXT NOT NULL, stored_path TEXT NOT NULL, row_count INTEGER NOT NULL DEFAULT 0, validation_issues JSON, created_at DATETIME NOT NULL)")
        connection.execute("CREATE TABLE app_schema_version (id INTEGER PRIMARY KEY, version INTEGER, app_version TEXT, updated_at DATETIME)")
        connection.execute("INSERT INTO app_schema_version VALUES (1, 9, '0.9.1', CURRENT_TIMESTAMP)")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert run_migrations(engine) == SCHEMA_VERSION
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(organization_mappings)")}
        batch_columns = {row[1] for row in connection.execute("PRAGMA table_info(reconciliation_import_batches)")}
        assert "bank_subaccount" in columns
        assert "file_results" in batch_columns
        assert connection.execute("SELECT branch_name FROM organization_mappings WHERE id = 1").fetchone() == ("保留机构",)

