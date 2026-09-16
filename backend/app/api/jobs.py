from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.api.dependencies import require_company, require_period
from app.core.company_context import current_company_id
from app.core.config import settings
from app.models.core import Job, UploadedFile
from app.core.version import APP_VERSION, RULESET_VERSION
from app.schemas.core import JobCreate, JobDetail, JobRead, JobSaveAllRequest
from app.services.artifact_export import exportable_artifacts, safe_artifact_name, save_artifacts, writable_directory
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
    query = db.query(Job).filter(Job.company_id == current_company_id())
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
        .filter(Job.company_id == current_company_id(), Job.workflow_code == workflow_code, Job.period_id == period_id)
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
        .filter(Job.id == job_id, Job.company_id == current_company_id())
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
        .filter(Job.id == job_id, Job.company_id == current_company_id())
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    declaration_artifacts = exportable_artifacts(job.artifacts)
    if not declaration_artifacts:
        raise HTTPException(status_code=404, detail="该任务没有可批量下载的申报文件")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in declaration_artifacts:
            archive.write(artifact.stored_path, f"申报文件/{safe_artifact_name(artifact.file_name)}")
    zip_labels = {
        "general_salary_tax": "工资薪金个税申报文件",
        "broker_tax": "经纪人个税申报文件",
        "intern_tax": "实习生个税申报文件",
        "part_time_tax": "劳务报酬个税申报文件",
        "restricted_stock_interest_tax": "限售股个税申报文件",
    }
    filename = f"{zip_labels.get(job.workflow_code, '个税申报文件')}.zip"
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post("/{job_id}/save-all")
def save_job_declarations(job_id: int, payload: JobSaveAllRequest, db: Session = Depends(get_db)) -> dict:
    if settings.runtime_mode != "desktop":
        raise HTTPException(status_code=403, detail="仅桌面版允许保存文件到本机目录")
    job = (
        db.query(Job)
        .options(selectinload(Job.artifacts))
        .filter(Job.id == job_id, Job.company_id == current_company_id())
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    directory = Path(payload.directory)
    if not writable_directory(directory):
        raise HTTPException(status_code=400, detail="目标目录不存在、不是目录或不可写")
    saved = save_artifacts(job.artifacts, directory)
    if not saved:
        raise HTTPException(status_code=404, detail="该任务没有可保存的申报文件")
    return {"saved_count": len(saved), "directory": str(directory), "files": saved}
