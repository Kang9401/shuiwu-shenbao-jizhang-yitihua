import sqlite3

from app.db.migrations import _PIT_WORKPAPER_CHILD_TABLES, _migration_13, _migration_14


def test_pit_workpaper_migration_keeps_legacy_stage_and_allows_second_stage():
    connection = sqlite3.connect(":memory:")
    connection.execute("""
        CREATE TABLE pit_reconciliation_workpapers (
            id INTEGER PRIMARY KEY, public_id VARCHAR(36) NOT NULL UNIQUE, company_id INTEGER NOT NULL,
            period_id INTEGER NOT NULL, tax_type VARCHAR(20) NOT NULL, stage VARCHAR(30) NOT NULL,
            data_status VARCHAR(30) NOT NULL, calculation_status VARCHAR(30) NOT NULL, rule_version VARCHAR(50) NOT NULL,
            missing_sources_json JSON, source_snapshot_json JSON, last_calculated_at DATETIME, last_error TEXT,
            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, UNIQUE(company_id, period_id, tax_type)
        )
    """)
    connection.execute("""
        INSERT INTO pit_reconciliation_workpapers VALUES
        (1, 'legacy-pre', 1, 202608, 'pit', 'pre_payment', 'ready', 'success', 'legacy', NULL, NULL, NULL, NULL, '2026-01-01', '2026-01-01')
    """)
    _migration_13(connection)
    connection.execute("""
        INSERT INTO pit_reconciliation_workpapers (
            public_id, company_id, period_id, tax_type, stage, workflow_status, draft_revision,
            data_status, calculation_status, rule_version, created_at, updated_at
        ) VALUES ('post-stage', 1, 202608, 'pit', 'post_payment', 'data_preparation', 0, 'incomplete', 'idle', 'v1', '2026-01-01', '2026-01-01')
    """)
    rows = connection.execute("SELECT stage, workflow_status FROM pit_reconciliation_workpapers ORDER BY stage").fetchall()
    assert rows == [("post_payment", "data_preparation"), ("pre_payment", "pending_submission")]


def test_migration_14_repairs_all_pit_child_workpaper_foreign_keys():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE pit_reconciliation_workpapers (id INTEGER PRIMARY KEY)")
    for table in _PIT_WORKPAPER_CHILD_TABLES:
        connection.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, workpaper_id INTEGER REFERENCES pit_reconciliation_workpapers_legacy_stage(id))")
    _migration_14(connection)
    for table in _PIT_WORKPAPER_CHILD_TABLES:
        foreign_keys = connection.execute(f"PRAGMA foreign_key_list({table})").fetchall()
        assert [(row[3], row[2]) for row in foreign_keys] == [("workpaper_id", "pit_reconciliation_workpapers")]
