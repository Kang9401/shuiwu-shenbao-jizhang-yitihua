from __future__ import annotations

import os
import sys
from pathlib import Path

from app.core.version import APP_SLUG


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def executable_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()


def resource_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    return Path(bundle_root).resolve() if bundle_root else project_root()


def default_storage_root() -> Path:
    if not is_frozen() and os.getenv("APP_RUNTIME_MODE", "development") != "desktop":
        return project_root() / "storage"
    local_app_data = os.getenv("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / APP_SLUG


def default_backup_root() -> Path:
    if not is_frozen() and os.getenv("APP_RUNTIME_MODE", "development") != "desktop":
        return project_root() / "storage" / "backups"
    documents = Path(os.getenv("USERPROFILE", str(Path.home()))) / "Documents"
    return documents / "税务申报核对工作台" / "备份"


def default_frontend_dist() -> Path:
    if is_frozen():
        return resource_root() / "frontend_dist"
    return project_root() / "frontend" / "dist"


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"
