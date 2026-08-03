from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.version import APP_VERSION, PRODUCT_NAME, RULESET_VERSION, SCHEMA_VERSION


BACKUP_DIRECTORIES = ("uploads", "artifacts", "rpa")


def database_path() -> Path:
    from app.db.session import engine

    database = engine.url.database
    if engine.url.get_backend_name() != "sqlite" or not database or database == ":memory:":
        raise RuntimeError("当前数据库不是可备份的本地 SQLite 数据库")
    return Path(database).resolve()


def _snapshot_sqlite(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_db = sqlite3.connect(str(source))
    target_db = sqlite3.connect(str(target))
    try:
        source_db.backup(target_db)
    finally:
        target_db.close()
        source_db.close()


def _safe_name(label: str) -> str:
    cleaned = "".join(char for char in label if char.isalnum() or char in {"-", "_"})
    return cleaned or "manual"


def create_backup(
    label: str = "manual",
    *,
    target_dir: Path | None = None,
    database_file: Path | None = None,
    data_root: Path | None = None,
) -> dict[str, Any]:
    source_db = (database_file or database_path()).resolve()
    if not source_db.exists():
        raise FileNotFoundError("本地数据库不存在，无法备份")
    root = (data_root or settings.storage_root).resolve()
    destination = (target_dir or settings.backup_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"TaxWorkbench_{timestamp}_{_safe_name(label)}.zip"
    output = destination / filename

    with tempfile.TemporaryDirectory(prefix="taxworkbench-backup-") as temp_value:
        temp = Path(temp_value)
        snapshot = temp / "tax_accounting.db"
        _snapshot_sqlite(source_db, snapshot)
        manifest = {
            "product": PRODUCT_NAME,
            "app_version": APP_VERSION,
            "ruleset_version": RULESET_VERSION,
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "format_version": 1,
        }
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.write(snapshot, "data/tax_accounting.db")
            for directory_name in BACKUP_DIRECTORIES:
                directory = root / directory_name
                archive.writestr(f"data/{directory_name}/", "")
                if not directory.exists():
                    continue
                for path in directory.rglob("*"):
                    if path.is_file():
                        archive.write(path, f"data/{directory_name}/{path.relative_to(directory).as_posix()}")
    return {
        "file_name": filename,
        "path": str(output),
        "size_bytes": output.stat().st_size,
        "created_at": datetime.fromtimestamp(output.stat().st_mtime),
    }


def list_backups(target_dir: Path | None = None) -> list[dict[str, Any]]:
    destination = (target_dir or settings.backup_dir).resolve()
    if not destination.exists():
        return []
    return [
        {
            "file_name": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime),
        }
        for path in sorted(destination.glob("TaxWorkbench_*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
        if path.is_file()
    ]


def resolve_backup(filename: str, target_dir: Path | None = None) -> Path:
    destination = (target_dir or settings.backup_dir).resolve()
    candidate = (destination / Path(filename).name).resolve()
    if candidate.parent != destination or not candidate.is_file():
        raise FileNotFoundError("备份文件不存在")
    return candidate


def _validate_archive(archive: zipfile.ZipFile) -> dict[str, Any]:
    for info in archive.infolist():
        path = Path(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("备份包包含不安全路径")
    required = {"manifest.json", "data/tax_accounting.db"}
    if not required.issubset(archive.namelist()):
        raise ValueError("不是有效的税务申报核对工作台备份")
    manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
    if manifest.get("format_version") != 1:
        raise ValueError("备份格式版本不受支持")
    return manifest


def restore_backup(
    backup_file: Path,
    *,
    database_file: Path | None = None,
    data_root: Path | None = None,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    source = backup_file.resolve()
    root = (data_root or settings.storage_root).resolve()
    target_db = (database_file or database_path()).resolve()
    if not source.is_file():
        raise FileNotFoundError("待恢复的备份文件不存在")

    with tempfile.TemporaryDirectory(prefix="taxworkbench-restore-") as temp_value:
        staging = Path(temp_value)
        with zipfile.ZipFile(source, "r") as archive:
            manifest = _validate_archive(archive)
            archive.extractall(staging)
        restored_db = staging / "data" / "tax_accounting.db"
        connection = sqlite3.connect(str(restored_db))
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
        finally:
            connection.close()
        if not integrity or integrity[0] != "ok":
            raise ValueError("备份数据库完整性检查失败")

        safety_backup = None
        if target_db.exists():
            safety_backup = create_backup(
                "pre_restore",
                target_dir=backup_dir,
                database_file=target_db,
                data_root=root,
            )

        if database_file is None:
            from app.db.session import engine

            engine.dispose()
        target_db.parent.mkdir(parents=True, exist_ok=True)
        replacement = target_db.with_suffix(".restore-new")
        shutil.copy2(restored_db, replacement)
        replacement.replace(target_db)

        for directory_name in BACKUP_DIRECTORIES:
            restored_directory = staging / "data" / directory_name
            target_directory = root / directory_name
            old_directory = root / f".{directory_name}.pre-restore"
            if old_directory.exists():
                shutil.rmtree(old_directory)
            if target_directory.exists():
                target_directory.replace(old_directory)
            try:
                if restored_directory.exists():
                    shutil.copytree(restored_directory, target_directory)
                else:
                    target_directory.mkdir(parents=True, exist_ok=True)
            except Exception:
                if target_directory.exists():
                    shutil.rmtree(target_directory)
                if old_directory.exists():
                    old_directory.replace(target_directory)
                raise
            if old_directory.exists():
                shutil.rmtree(old_directory)

    return {"manifest": manifest, "safety_backup": safety_backup}
