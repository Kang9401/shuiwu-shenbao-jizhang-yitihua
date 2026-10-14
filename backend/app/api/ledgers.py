from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.api.dependencies import require_company
from app.models.accounting import CertificationLedger, InvoiceLedger, VoucherDraft
from app.schemas.ledger import (
    CertificationLedgerRead,
    InvoiceLedgerRead,
    VoucherDraftRead,
)

router = APIRouter(prefix="/ledgers", tags=["ledgers"], dependencies=[Depends(require_company)])


@router.get("/invoices", response_model=List[InvoiceLedgerRead])
def list_invoice_ledgers(
    period_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> List[InvoiceLedger]:
    query = db.query(InvoiceLedger)
    if period_id is not None:
        query = query.filter(InvoiceLedger.period_id == period_id)
    return query.order_by(InvoiceLedger.created_at.desc()).limit(500).all()


@router.get("/certifications", response_model=List[CertificationLedgerRead])
def list_certification_ledgers(
    period_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> List[CertificationLedger]:
    query = db.query(CertificationLedger)
    if period_id is not None:
        query = query.filter(CertificationLedger.period_id == period_id)
    return query.order_by(CertificationLedger.created_at.desc()).limit(500).all()


@router.get("/vouchers", response_model=List[VoucherDraftRead])
def list_voucher_drafts(
    period_id: Optional[int] = None,
    db: Session = Depends(get_db),
) -> List[VoucherDraft]:
    query = db.query(VoucherDraft)
    if period_id is not None:
        query = query.filter(VoucherDraft.period_id == period_id)
    return query.order_by(VoucherDraft.created_at.desc()).limit(500).all()
