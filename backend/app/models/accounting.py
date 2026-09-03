from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.core.company_context import current_company_id


class InvoiceLedger(Base):
    __tablename__ = "invoice_ledgers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("periods.id"), nullable=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    invoice_no: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    seller_name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    buyer_name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    invoice_date: Mapped[Optional[str]] = mapped_column(String(40))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="draft")
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CertificationLedger(Base):
    __tablename__ = "certification_ledgers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("periods.id"), nullable=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    invoice_no: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    booking_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    match_status: Mapped[str] = mapped_column(String(40), default="unmatched")
    issue_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VoucherDraft(Base):
    __tablename__ = "voucher_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("periods.id"), nullable=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(80), index=True)
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    debit_account: Mapped[Optional[str]] = mapped_column(String(120))
    credit_account: Mapped[Optional[str]] = mapped_column(String(120))
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), default="draft")
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PersonnelMasterArtifact(Base):
    __tablename__ = "personnel_master_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "period_id",
            "person_type",
            "scope_type",
            "scope_code",
            name="uq_personnel_master_period_type_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    person_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scope_code: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_issues: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PersonnelMasterImportBatch(Base):
    __tablename__ = "personnel_master_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    artifact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("personnel_master_artifacts.id"), nullable=True)
    person_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scope_code: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_issues: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReconciliationImportBatch(Base):
    __tablename__ = "reconciliation_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    import_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_issues: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    file_results: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ReconciliationImportRow(Base):
    __tablename__ = "reconciliation_import_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("reconciliation_import_batches.id"), nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    import_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    organization_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    branch_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    transaction_date: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    counterparty: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    serial_no: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    declaration_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    taxpayer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    income_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    declaration_status: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    tax_period: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    account_code: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    account_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    auxiliary: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    debit_credit: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    voucher_no: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OrganizationMapping(Base):
    __tablename__ = "organization_mappings"
    __table_args__ = (
        UniqueConstraint("company_id", "branch_name", name="uq_organization_mapping_company_branch_name"),
        UniqueConstraint("company_id", "org_code", name="uq_organization_mapping_company_org_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    branch_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    taxpayer_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    rpa_enabled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rpa_org_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    rpa_search_result_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_branch: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    bank_subaccount: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
