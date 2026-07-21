from pathlib import Path

from app.core.config import settings
from app.core.paths import resource_root


def vendor_dir() -> Path:
    return resource_root() / "backend" / "vendor" / "etax_rpa"


def rpa_root() -> Path:
    return settings.storage_root / "rpa" / "etax"


def runtime_app_dir() -> Path:
    return rpa_root() / "app"


def state_dir() -> Path:
    return rpa_root() / "state"


def uploads_dir() -> Path:
    return rpa_root() / "uploads"


def helper_resource_dir() -> Path:
    return resource_root() / "rpa_helpers"
