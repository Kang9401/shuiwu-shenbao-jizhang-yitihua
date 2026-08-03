from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.dependencies import require_company, require_period
from app.models.core import UploadedFile
from app.schemas.core import UploadedFileRead
from app.services.storage import save_upload

router = APIRouter(prefix="/files", tags=["files"], dependencies=[Depends(require_company)])


@router.post("", response_model=UploadedFileRead)
def upload_file(
    file: UploadFile = File(...),
    file_role: str = Form(...),
    period_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
) -> UploadedFile:
    if period_id is not None:
        require_period(db, period_id)
    path, size = save_upload(file, period_id, file_role)
    uploaded = UploadedFile(
        period_id=period_id,
        file_role=file_role,
        original_name=file.filename or "upload.xlsx",
        stored_path=str(path),
        content_type=file.content_type,
        size_bytes=size,
        validation_status="uploaded",
        validation_issues=[],
    )
    db.add(uploaded)
    db.commit()
    db.refresh(uploaded)
    return uploaded


@router.get("", response_model=List[UploadedFileRead])
def list_files(period_id: Optional[int] = None, db: Session = Depends(get_db)) -> List[UploadedFile]:
    query = db.query(UploadedFile)
    if period_id is not None:
        query = query.filter(UploadedFile.period_id == period_id)
    return query.order_by(UploadedFile.created_at.desc()).limit(200).all()
