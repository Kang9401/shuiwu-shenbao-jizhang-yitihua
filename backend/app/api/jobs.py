from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.api.dependencies import require_company, require_period
from app.models.core import Job, UploadedFile
from app.core.version import APP_VERSION, RULESET_VERSION
from app.schemas.core import JobCreate, JobDetail, JobRead
from app.services.job_runner import run_job
from app.workflows import get_workflow

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_company)])


@router.get("", response_model=List[JobRead])
def list_jobs(
    workflow_code: Optional[str] = None,
    period_id: Optional[int] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> List[Job]:
    query = db.query(Job)
    if workflow_code:
        query = query.filter(Job.workflow_code == workflow_code)
    if period_id is not None:
        query = query.filter(Job.period_id == period_id)
    return query.order_by(Job.created_at.desc()).limit(max(1, min(limit, 200))).all()


@router.post("", response_model=JobDetail)
def create_job(payload: JobCreate, db: Session = Depends(get_db)) -> Job:
    try:
        get_workflow(payload.workflow_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.period_id is not None:
        require_period(db, payload.period_id)
    if payload.input_file_ids:
        found_ids = {
            row[0] for row in db.query(UploadedFile.id).filter(UploadedFile.id.in_(payload.input_file_ids)).all()
        }
        if found_ids != set(payload.input_file_ids):
            raise HTTPException(status_code=404, detail="部分上传文件不存在")
    job = Job(
        workflow_code=payload.workflow_code,
        period_id=payload.period_id,
        operation=payload.operation,
        app_version=APP_VERSION,
        ruleset_version=RULESET_VERSION,
        input_file_ids=payload.input_file_ids,
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return run_job(db, job, operation=payload.operation)


@router.get("/latest", response_model=JobDetail)
def get_latest_job(
    workflow_code: str,
    period_id: int,
    operation: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Job:
    query = (
        db.query(Job)
        .options(selectinload(Job.artifacts))
        .filter(Job.workflow_code == workflow_code, Job.period_id == period_id)
    )
    if operation:
        query = query.filter(Job.operation == operation)
    job = query.order_by(Job.created_at.desc(), Job.id.desc()).first()
    if not job:
        raise HTTPException(status_code=404, detail="该所属期间暂无运行记录")
    return job


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: int, db: Session = Depends(get_db)) -> Job:
    job = (
        db.query(Job)
        .options(selectinload(Job.artifacts))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.get("/{job_id}/download-all")
def download_job_declarations(job_id: int, db: Session = Depends(get_db)) -> Response:
    import io
    import zipfile
    from urllib.parse import quote

    job = (
        db.query(Job)
        .options(selectinload(Job.artifacts))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    declaration_artifacts = [
        artifact for artifact in job.artifacts
        if artifact.artifact_type in {"declaration", "personnel_collection"}
        and Path(artifact.stored_path).exists()
    ]
    if not declaration_artifacts:
        raise HTTPException(status_code=404, detail="该任务没有可批量下载的申报文件")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in declaration_artifacts:
            archive.write(artifact.stored_path, f"申报文件/{artifact.file_name}")
    filename = f"{job.workflow_code}_申报文件.zip"
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
