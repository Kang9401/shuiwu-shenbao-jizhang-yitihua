from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from app.schemas.common import ORMModel


class TaxLedgerRead(ORMModel):
    id: int
    period_id: Optional[int]
    job_id: Optional[int]
    workflow_code: str
    tax_category: str
    employee_id: Optional[str]
    taxpayer_name: Optional[str]
    organization_code: Optional[str]
    income_amount: Optional[Decimal]
    tax_amount: Optional[Decimal]
    raw_data: Optional[Dict[str, Any]]
    created_at: datetime


class InvoiceLedgerRead(ORMModel):
    id: int
    period_id: Optional[int]
    job_id: Optional[int]
    invoice_no: Optional[str]
    seller_name: Optional[str]
    buyer_name: Optional[str]
    invoice_date: Optional[str]
    amount: Optional[Decimal]
    tax_amount: Optional[Decimal]
    status: str
    created_at: datetime


class CertificationLedgerRead(ORMModel):
    id: int
    period_id: Optional[int]
    job_id: Optional[int]
    invoice_no: Optional[str]
    booking_amount: Optional[Decimal]
    tax_amount: Optional[Decimal]
    match_status: str
    issue_type: Optional[str]
    created_at: datetime


class VoucherDraftRead(ORMModel):
    id: int
    period_id: Optional[int]
    job_id: Optional[int]
    source_type: str
    source_id: Optional[int]
    debit_account: Optional[str]
    credit_account: Optional[str]
    amount: Optional[Decimal]
    summary: Optional[str]
    status: str
    created_at: datetime
