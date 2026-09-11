from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.company_context import current_company_id
from app.models.accounting import ReconciliationImportRow
from app.models.pit_reconciliation import PitReconciliationWorkpaper

from app.db.session import get_db
from app.api.dependencies import require_company, require_period
from app.models.accounting import ReconciliationImportBatch
from app.services.reconciliation_import import (
    ReconciliationImportValidationError,
    import_reconciliation_file,
    import_pit_declaration_file,
    import_pit_declaration_files,
    import_tax_certificate_files,
    list_reconciliation_batches,
)

router = APIRouter(prefix="/reconciliation-imports", tags=["reconciliation-imports"], dependencies=[Depends(require_company)])


class ClearImports(BaseModel):
    period_id: int
    import_type: str
    batch_ids: list[int] | None = None


@router.post("/clear")
def clear_imports(payload: ClearImports, db: Session = Depends(get_db)) -> dict:
    require_period(db, payload.period_id)
    if payload.import_type not in {"bank_statement", "pit_declaration", "tax_certificate", "balance_sheet", "declaration_result", "accounting_ledger"}:
        raise HTTPException(400, "未知导入类型")
    query = db.query(ReconciliationImportBatch).filter_by(company_id=current_company_id(), period_id=payload.period_id, import_type=payload.import_type)
    if payload.batch_ids is not None:
        query = query.filter(ReconciliationImportBatch.id.in_(payload.batch_ids))
    ids = [item.id for item in query.all()]
    if payload.batch_ids is not None and set(ids) != set(payload.batch_ids):
        raise HTTPException(404, "部分批次不存在或不属于当前分公司、期间和类型")
    deleted_rows = db.query(ReconciliationImportRow).filter(ReconciliationImportRow.company_id == current_company_id(), ReconciliationImportRow.batch_id.in_(ids)).delete(synchronize_session=False)
    query.delete(synchronize_session=False)
    if ids:
        for workpaper in db.query(PitReconciliationWorkpaper).filter_by(company_id=current_company_id(), period_id=payload.period_id):
            workpaper.calculation_status = "stale"
            workpaper.last_error = "核对来源已清空，请重新核对"
    db.commit()
    return {"deleted_batches": len(ids), "deleted_rows": deleted_rows}


def _batch_payload(batch: ReconciliationImportBatch) -> dict:
    return {
        "id": batch.id,
        "period_id": batch.period_id,
        "import_type": batch.import_type,
        "original_name": batch.original_name,
        "row_count": batch.row_count,
        "validation_issues": batch.validation_issues or [],
        "file_results": batch.file_results or [],
        "created_at": batch.created_at,
        "download_url": f"/api/reconciliation-imports/{batch.id}/download",
    }


def _import(import_type: str, period_id: int, file: UploadFile, db: Session) -> dict:
    require_period(db, period_id)
    try:
        batch = import_reconciliation_file(db, period_id=period_id, import_type=import_type, file=file)
    except ReconciliationImportValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.issues) from exc
    return _batch_payload(batch)


@router.post("/bank-statement")
def import_bank_statement(
    period_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    return _import("bank_statement", period_id, file, db)


@router.post("/declaration-result")
def import_declaration_result(
    period_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    return _import("declaration_result", period_id, file, db)


@router.post("/accounting-ledger")
def import_accounting_ledger(
    period_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    return _import("accounting_ledger", period_id, file, db)


@router.post("/balance-sheet")
def import_balance_sheet(
    period_id: int = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    return _import("balance_sheet", period_id, file, db)


@router.post("/pit-declaration")
def import_pit_declaration(period_id: int = Query(...), file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    require_period(db, period_id)
    try: batch = import_pit_declaration_file(db, period_id=period_id, file=file)
    except ReconciliationImportValidationError as exc: raise HTTPException(status_code=400, detail=exc.issues) from exc
    return _batch_payload(batch)


@router.post("/pit-declarations")
def import_pit_declarations(period_id: int = Query(...), files: list[UploadFile] = File(...), db: Session = Depends(get_db)) -> dict:
    require_period(db, period_id)
    try:
        batch = import_pit_declaration_files(db, period_id=period_id, files=files)
    except ReconciliationImportValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.issues) from exc
    return _batch_payload(batch)


@router.post("/tax-certificates")
def import_tax_certificates(period_id: int = Query(...), files: list[UploadFile] = File(...), db: Session = Depends(get_db)) -> dict:
    require_period(db, period_id)
    try: batch = import_tax_certificate_files(db, period_id=period_id, files=files)
    except ReconciliationImportValidationError as exc: raise HTTPException(status_code=400, detail=exc.issues) from exc
    return _batch_payload(batch)


@router.get("")
def list_batches(
    period_id: Optional[int] = Query(None),
    import_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [_batch_payload(batch) for batch in list_reconciliation_batches(db, period_id=period_id, import_type=import_type)]


@router.get("/{batch_id}/download")
def download_batch(batch_id: int, db: Session = Depends(get_db)) -> FileResponse:
    from app.core.company_context import current_company_id
    batch = db.query(ReconciliationImportBatch).filter(ReconciliationImportBatch.id == batch_id, ReconciliationImportBatch.company_id == current_company_id()).first()
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    path = Path(str(batch.stored_path).split(";", 1)[0])
    if not path.exists():
        raise HTTPException(status_code=404, detail="原始导入文件已丢失")
    return FileResponse(path, filename=batch.original_name)
