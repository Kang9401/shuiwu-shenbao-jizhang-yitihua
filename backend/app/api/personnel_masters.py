from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.dependencies import require_company, require_period
from app.services.personnel_master import (
    PersonnelMasterValidationError,
    get_personnel_master_artifact,
    import_personnel_master,
    list_personnel_master_batches,
    list_personnel_master_status,
)

router = APIRouter(prefix="/personnel-masters", tags=["personnel-masters"], dependencies=[Depends(require_company)])


def _artifact_payload(artifact) -> dict:
    return {
        "id": artifact.id,
        "period_id": artifact.period_id,
        "person_type": artifact.person_type,
        "scope_type": artifact.scope_type,
        "scope_code": artifact.scope_code,
        "file_name": artifact.file_name,
        "row_count": artifact.row_count,
        "validation_issues": artifact.validation_issues or [],
        "updated_at": artifact.updated_at,
        "download_url": (
            f"/api/personnel-masters/export?period_id={artifact.period_id}"
            f"&person_type={artifact.person_type}&scope_type={artifact.scope_type}&scope_code={artifact.scope_code}"
        ),
    }


@router.post("/import")
def import_master(
    period_id: int = Form(...),
    person_type: str = Form(...),
    scope_type: str = Form("month"),
    scope_code: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    require_period(db, period_id)
    try:
        artifact = import_personnel_master(
            db,
            period_id=period_id,
            person_type=person_type,
            scope_type=scope_type,
            scope_code=scope_code,
            file=file,
        )
    except PersonnelMasterValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.issues) from exc
    return _artifact_payload(artifact)


@router.get("/status")
def status(
    period_id: int = Query(...),
    person_type: str = Query(...),
    db: Session = Depends(get_db),
) -> list[dict]:
    require_period(db, period_id)
    return [_artifact_payload(artifact) for artifact in list_personnel_master_status(db, period_id, person_type)]


@router.get("/batches")
def batches(
    period_id: int = Query(...),
    person_type: str = Query(...),
    db: Session = Depends(get_db),
) -> list[dict]:
    require_period(db, period_id)
    return [
        {
            "id": batch.id,
            "period_id": batch.period_id,
            "person_type": batch.person_type,
            "scope_type": batch.scope_type,
            "scope_code": batch.scope_code,
            "original_name": batch.original_name,
            "row_count": batch.row_count,
            "validation_issues": batch.validation_issues or [],
            "created_at": batch.created_at,
        }
        for batch in list_personnel_master_batches(db, period_id, person_type)
    ]


@router.get("/export")
def export_master(
    period_id: int = Query(...),
    person_type: str = Query(...),
    scope_type: str = Query("month"),
    scope_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> FileResponse:
    require_period(db, period_id)
    artifact = get_personnel_master_artifact(db, period_id, person_type, scope_type, scope_code)
    if not artifact:
        raise HTTPException(status_code=404, detail="该人员主数据尚未初始化")
    path = Path(artifact.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="人员主数据文件已丢失")
    return FileResponse(path, filename=artifact.file_name)
