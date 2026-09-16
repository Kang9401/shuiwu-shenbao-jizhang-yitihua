from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.core.paths import resource_root


def vendor_dir() -> Path:
    return resource_root() / "backend" / "vendor" / "etax_rpa"


def rpa_root() -> Path:
    return settings.storage_root / "rpa" / "etax"


def runtime_app_dir() -> Path:
    return rpa_root() / "app"


def company_rpa_root(company_id: int | None = None) -> Path:
    return rpa_root() / "companies" / str(company_id) if company_id is not None else rpa_root()


def state_dir(company_id: int | None = None) -> Path:
    return company_rpa_root(company_id) / "state"


def uploads_dir(company_id: int | None = None) -> Path:
    return company_rpa_root(company_id) / "uploads"


def helper_resource_dir() -> Path:
    return resource_root() / "rpa_helpers"
