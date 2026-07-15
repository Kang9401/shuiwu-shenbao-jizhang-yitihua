import sqlite3
import zipfile

from app.services.backup import create_backup, restore_backup


def _create_database(path, value):
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS sample (value TEXT)")
        connection.execute("DELETE FROM sample")
        connection.execute("INSERT INTO sample (value) VALUES (?)", (value,))
        connection.commit()
    finally:
        connection.close()


def _database_value(path):
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT value FROM sample").fetchone()[0]
    finally:
        connection.close()


def test_full_backup_and_restore_preserve_database_and_artifacts(tmp_path):
    data_root = tmp_path / "data"
    database = data_root / "tax_accounting.db"
    backup_dir = tmp_path / "backups"
    (data_root / "uploads").mkdir(parents=True)
    (data_root / "artifacts").mkdir(parents=True)
    (data_root / "uploads" / "source.xlsx").write_text("source-v1", encoding="utf-8")
    (data_root / "artifacts" / "result.xlsx").write_text("result-v1", encoding="utf-8")
    _create_database(database, "database-v1")

    backup = create_backup(
        "manual",
        target_dir=backup_dir,
        database_file=database,
        data_root=data_root,
    )
    with zipfile.ZipFile(backup["path"]) as archive:
        assert "manifest.json" in archive.namelist()
        assert "data/tax_accounting.db" in archive.namelist()
        assert "data/artifacts/result.xlsx" in archive.namelist()

    _create_database(database, "database-v2")
    (data_root / "uploads" / "source.xlsx").write_text("source-v2", encoding="utf-8")
    (data_root / "artifacts" / "stale.xlsx").write_text("stale", encoding="utf-8")

    result = restore_backup(
        backup_file=backup_dir / backup["file_name"],
        database_file=database,
        data_root=data_root,
        backup_dir=backup_dir,
    )

    assert result["manifest"]["format_version"] == 1
    assert result["safety_backup"] is not None
    assert _database_value(database) == "database-v1"
    assert (data_root / "uploads" / "source.xlsx").read_text(encoding="utf-8") == "source-v1"
    assert (data_root / "artifacts" / "result.xlsx").read_text(encoding="utf-8") == "result-v1"
    assert not (data_root / "artifacts" / "stale.xlsx").exists()
