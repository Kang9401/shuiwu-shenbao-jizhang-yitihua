from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.core.company_context import current_company_id


def ensure_storage() -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.artifact_dir.mkdir(parents=True, exist_ok=True)


def save_upload(file: UploadFile, period_id: Optional[int], file_role: str) -> Tuple[Path, int]:
    ensure_storage()
    period_part = str(period_id or "unassigned")
    company_id = current_company_id(default=None)
    root = settings.upload_dir / str(company_id) if company_id is not None else settings.upload_dir
    target_dir = root / period_part / file_role
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "upload.xlsx").suffix or ".xlsx"
    target = target_dir / f"{uuid4().hex}{suffix}"
    size = 0
    with target.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            out.write(chunk)
    return target, size


def artifact_path(job_id: int, file_name: str) -> Path:
    ensure_storage()
    company_id = current_company_id(default=None)
    target_dir = (
        settings.artifact_dir / str(company_id) / "jobs" / str(job_id)
        if company_id is not None
        else settings.artifact_dir / str(job_id)
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / file_name
