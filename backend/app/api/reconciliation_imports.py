from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.dependencies import require_company, require_period
from app.models.accounting import ReconciliationImportBatch
from app.services.reconciliation_import import (
    ReconciliationImportValidationError,
    import_reconciliation_file,
    import_pit_declaration_file,
    import_tax_certificate_files,
    list_reconciliation_batches,
)

router = APIRouter(prefix="/reconciliation-imports", tags=["reconciliation-imports"], dependencies=[Depends(require_company)])


def _batch_payload(batch: ReconciliationImportBatch) -> dict:
    return {
        "id": batch.id,
        "period_id": batch.period_id,
        "import_type": batch.import_type,
        "original_name": batch.original_name,
        "row_count": batch.row_count,
        "validation_issues": batch.validation_issues or [],
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
