from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.rpa.service import rpa_service
from app.services.personnel_master import PersonnelMasterValidationError
from app.schemas.rpa import RpaChromeStart, RpaConfigUpdate, RpaDeleteFilesRequest, RpaOrgPreviewRequest, RpaPreparePeriodRequest, RpaTaskStartRequest

router = APIRouter(prefix="/rpa", tags=["rpa"])
ORG_LIMIT = 20 * 1024 * 1024
IMPORT_LIMIT = 100 * 1024 * 1024


def bad_request(exc: Exception):
    if isinstance(exc, FileExistsError):
        raise HTTPException(status_code=409, detail=f"同名文件已存在：{exc}") from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


async def read_limited(file: UploadFile, limit: int) -> bytes:
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(status_code=413, detail=f"文件超过 {limit // 1024 // 1024} MB 限制")
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/status")
def status():
    return rpa_service.get_status()


@router.put("/config")
def save_config(request: RpaConfigUpdate):
    return rpa_service.save_config(request.chrome_path)


@router.post("/org-excel")
async def upload_org_excel(file: UploadFile = File(...)):
    try:
        return rpa_service.upload_org_excel(file.filename or "", await read_limited(file, ORG_LIMIT))
    except HTTPException:
        raise
    except Exception as exc:
        return bad_request(exc)


@router.post("/import-files")
async def upload_import_files(files: list[UploadFile] = File(...), overwrite: bool = Form(False)):
    try:
        payload = [(file.filename or "", await read_limited(file, IMPORT_LIMIT)) for file in files]
        return rpa_service.upload_import_files(payload, overwrite)
    except HTTPException:
        raise
    except Exception as exc:
        return bad_request(exc)


@router.post("/import-files/from-period")
def prepare_from_period(request: RpaPreparePeriodRequest, db: Session = Depends(get_db)):
    try:
        return rpa_service.prepare_from_period(db, request.period_id, request.overwrite)
    except Exception as exc:
        return bad_request(exc)


@router.delete("/import-files")
def delete_import_files(request: RpaDeleteFilesRequest):
    try:
        return rpa_service.delete_import_files(request.names)
    except Exception as exc:
        return bad_request(exc)


@router.post("/chrome/start")
def start_chrome(request: RpaChromeStart):
    try:
        return rpa_service.start_chrome(request.chrome_path)
    except Exception as exc:
        return bad_request(exc)


@router.get("/chrome/status")
def chrome_status():
    return rpa_service.chrome_status()


@router.post("/orgs/preview")
def preview_orgs(request: RpaOrgPreviewRequest, db: Session = Depends(get_db)):
    try:
        if request.period_id:
            items = rpa_service.organizations_for_period(db, request.period_id)
            selected = set(request.org_codes or ([request.org_code] if request.org_code else []))
            if not request.all_orgs:
                items = [item for item in items if item["code"] in selected]
            if request.start_org_code:
                index = next((i for i, item in enumerate(items) if item["code"] == request.start_org_code), None)
                if index is None:
                    raise ValueError("续跑机构不在本次机构范围内")
                items = items[index:]
        else:
            items = rpa_service.preview_orgs(request.all_orgs, request.org_code, request.start_org_code)
        return {"count": len(items), "items": items}
    except PersonnelMasterValidationError as exc:
        raise HTTPException(status_code=400, detail={"message": "人员主数据中的机构信息不完整", "issues": exc.issues}) from exc
    except Exception as exc:
        return bad_request(exc)


@router.get("/organizations")
def organizations(period_id: int = Query(..., gt=0), db: Session = Depends(get_db)):
    try:
        return {"items": rpa_service.organizations_for_period(db, period_id), "warnings": []}
    except PersonnelMasterValidationError as exc:
        raise HTTPException(status_code=400, detail={"message": "人员主数据中的机构信息不完整", "issues": exc.issues}) from exc


@router.post("/tasks/start")
def start_task(request: RpaTaskStartRequest, db: Session = Depends(get_db)):
    try:
        month = request.resolved_month()
        org_codes = request.org_codes or ([request.org_code] if request.org_code else [])
        if request.period_id:
            _, selected = rpa_service.prepare_runtime_org_excel(db, period_id=request.period_id, selected_org_codes=None if request.all_orgs else org_codes)
            result = rpa_service.start_task(request.task_key, month, True, None, request.resume_mode, request.start_org_code)
            def record(data):
                data["current_run"].update(period_id=request.period_id, declaration_month=month, org_codes=[item["code"] for item in selected], all_orgs=request.all_orgs)
            rpa_service.store.update(record)
            return result
        return rpa_service.start_task(request.task_key, month, request.all_orgs, request.org_code, request.resume_mode, request.start_org_code)
    except Exception as exc:
        return bad_request(exc)


@router.post("/tasks/stop")
def stop_task():
    return rpa_service.stop_task()


@router.post("/tasks/resume")
def resume_task():
    try:
        return rpa_service.resume_task()
    except Exception as exc:
        return bad_request(exc)


@router.get("/logs")
def logs(offset: int = Query(default=0, ge=0)):
    return rpa_service.read_logs(offset)


@router.get("/files")
def files():
    return rpa_service.list_output_files()


@router.get("/files/download")
def download(name: str = Query(min_length=1, max_length=255)):
    try:
        path = rpa_service.resolve_output(name)
        return FileResponse(path, filename=path.name)
    except Exception as exc:
        return bad_request(exc)
