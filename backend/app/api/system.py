from __future__ import annotations

import io
import json
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from app.core.config import settings
from app.core.version import APP_VERSION, PRODUCT_NAME, RULESET_VERSION, SCHEMA_VERSION
from app.db.migrations import current_schema_version
from app.db.session import engine
from app.services.backup import create_backup, list_backups, resolve_backup, restore_backup


router = APIRouter(prefix="/system", tags=["system"])


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


@router.get("/info")
def system_info() -> dict:
    usage = shutil.disk_usage(settings.storage_root.parent)
    return {
        "product_name": PRODUCT_NAME,
        "app_version": APP_VERSION,
        "ruleset_version": RULESET_VERSION,
        "schema_version": current_schema_version(engine),
        "expected_schema_version": SCHEMA_VERSION,
        "runtime_mode": settings.runtime_mode,
        "data_root": str(settings.storage_root),
        "backup_root": str(settings.backup_dir),
        "storage_bytes": _directory_size(settings.storage_root),
        "free_bytes": usage.free,
    }


@router.get("/backups")
def backups() -> list[dict]:
    return list_backups()


@router.post("/backups")
def make_backup() -> dict:
    try:
        return create_backup("manual")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"备份失败：{exc}") from exc


@router.get("/backups/{filename}")
def download_backup(filename: str) -> FileResponse:
    try:
        path = resolve_backup(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/restore")
def restore(file: UploadFile = File(...)) -> dict:
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    target = settings.temp_dir / f"restore-{datetime.now().strftime('%Y%m%d%H%M%S%f')}.zip"
    try:
        with target.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                output.write(chunk)
        result = restore_backup(target)
        from app.db.init_db import init_db

        init_db(create_preupgrade_backup=False)
        return {"status": "restored", **result}
    except (FileNotFoundError, ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail=f"恢复失败：{exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"恢复失败：{exc}") from exc
    finally:
        target.unlink(missing_ok=True)


@router.get("/diagnostics")
def diagnostics() -> Response:
    info = system_info()
    database = Path(engine.url.database).resolve() if engine.url.database else None
    integrity = "not_applicable"
    if database and database.exists() and engine.url.get_backend_name() == "sqlite":
        connection = sqlite3.connect(str(database))
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            integrity = str(row[0]) if row else "unknown"
        finally:
            connection.close()
    info["database_integrity"] = integrity
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("system-info.json", json.dumps(info, ensure_ascii=False, indent=2))
        if settings.log_dir.exists():
            for path in settings.log_dir.glob("*.log*"):
                if path.is_file():
                    archive.write(path, f"logs/{path.name}")
    filename = f"TaxWorkbench_diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
