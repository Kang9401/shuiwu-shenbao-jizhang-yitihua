from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.company_context import current_company_id
from app.db.session import Base


def _public_id() -> str:
    return str(uuid.uuid4())


class _PitBase:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    public_id: Mapped[str] = mapped_column(String(36), default=_public_id, unique=True, nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PitReconciliationWorkpaper(_PitBase, Base):
    __tablename__ = "pit_reconciliation_workpapers"
    __table_args__ = (UniqueConstraint("company_id", "period_id", "tax_type", name="uq_pit_workpaper_company_period_type"),)
    tax_type: Mapped[str] = mapped_column(String(20), default="pit", nullable=False)
    stage: Mapped[str] = mapped_column(String(30), default="pre_payment", nullable=False)
    data_status: Mapped[str] = mapped_column(String(30), default="incomplete", nullable=False)
    calculation_status: Mapped[str] = mapped_column(String(30), default="idle", nullable=False)
    rule_version: Mapped[str] = mapped_column(String(50), default="pit_legacy_v1", nullable=False)
    missing_sources_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source_snapshot_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_calculated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PitReconciliationSource(_PitBase, Base):
    __tablename__ = "pit_reconciliation_sources"
    __table_args__ = (UniqueConstraint("workpaper_id", "source_type", name="uq_pit_source_workpaper_type"),)
    workpaper_id: Mapped[int] = mapped_column(ForeignKey("pit_reconciliation_workpapers.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_status: Mapped[str] = mapped_column(String(30), nullable=False)
    required: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_kind: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    issues_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)


class PitDeclarationSummary(_PitBase, Base):
    __tablename__ = "pit_declaration_summaries"
    __table_args__ = (UniqueConstraint("workpaper_id", "org_code", "declaration_type", "income_item", name="uq_pit_declaration_summary"),)
    workpaper_id: Mapped[int] = mapped_column(ForeignKey("pit_reconciliation_workpapers.id"), nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(80), nullable=False)
    org_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    declaration_type: Mapped[str] = mapped_column(String(80), nullable=False)
    income_item: Mapped[str] = mapped_column(String(255), nullable=False)
    person_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    income_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)
    tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)


class PitTaxAmountCheck(_PitBase, Base):
    __tablename__ = "pit_tax_amount_checks"
    __table_args__ = (UniqueConstraint("workpaper_id", "org_code", "subject_code", name="uq_pit_tax_amount_check"),)
    workpaper_id: Mapped[int] = mapped_column(ForeignKey("pit_reconciliation_workpapers.id"), nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(80), nullable=False)
    org_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    subject_code: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    opening_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    debit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    credit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    closing_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    business_tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    declared_tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    current_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    current_manual_reason: Mapped[Optional[str]] = mapped_column(Text)
    cumulative_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    cumulative_manual_reason: Mapped[Optional[str]] = mapped_column(Text)
    scoped_declared_tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    business_declared_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    business_declared_manual_reason: Mapped[Optional[str]] = mapped_column(Text)
    remark: Mapped[Optional[str]] = mapped_column(Text)
    check_status: Mapped[str] = mapped_column(String(30), default="missing_source", nullable=False)


class PitOccurrenceCheck(_PitBase, Base):
    __tablename__ = "pit_occurrence_checks"
    __table_args__ = (UniqueConstraint("workpaper_id", "org_code", "subject_code", name="uq_pit_occurrence_check"),)
    workpaper_id: Mapped[int] = mapped_column(ForeignKey("pit_reconciliation_workpapers.id"), nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(80), nullable=False)
    org_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    subject_code: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    income_type: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    opening_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); debit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); credit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); closing_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    occurrence_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); broker_payroll_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); broker_occurrence_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); broker_occurrence_manual_reason: Mapped[Optional[str]] = mapped_column(Text)
    expected_declared_income: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); expected_income_description: Mapped[Optional[str]] = mapped_column(String(500)); actual_declared_income: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); declared_income_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); declared_income_manual_reason: Mapped[Optional[str]] = mapped_column(Text); remark: Mapped[Optional[str]] = mapped_column(Text); check_status: Mapped[str] = mapped_column(String(30), default="missing_source", nullable=False)


class PitReconciliationOrgSummary(_PitBase, Base):
    __tablename__ = "pit_reconciliation_org_summaries"
    __table_args__ = (UniqueConstraint("workpaper_id", "org_code", name="uq_pit_org_summary"),)
    workpaper_id: Mapped[int] = mapped_column(ForeignKey("pit_reconciliation_workpapers.id"), nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(80), nullable=False); org_name: Mapped[str] = mapped_column(String(255), default="", nullable=False); org_full_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    declared_tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); balance_tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference_1: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference_1_manual_reason: Mapped[Optional[str]] = mapped_column(Text)
    scoped_declared_tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); payroll_business_tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference_2: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference_2_manual_reason: Mapped[Optional[str]] = mapped_column(Text)
    taxable_income_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference_3_manual_reason: Mapped[Optional[str]] = mapped_column(Text); certificate_tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference_4: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference_4_manual_reason: Mapped[Optional[str]] = mapped_column(Text); bank_tax_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference_5: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference_5_manual_reason: Mapped[Optional[str]] = mapped_column(Text); broker_occurrence_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference_6_manual_reason: Mapped[Optional[str]] = mapped_column(Text); other_income_difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference_7_manual_reason: Mapped[Optional[str]] = mapped_column(Text); remark: Mapped[Optional[str]] = mapped_column(Text); check_status: Mapped[str] = mapped_column(String(30), default="missing_source", nullable=False)


class PitReconciliationDifferenceDetail(_PitBase, Base):
    __tablename__ = "pit_reconciliation_difference_details"
    __table_args__ = (UniqueConstraint("workpaper_id", "detail_type", "org_code", "identity_key", name="uq_pit_difference_detail"),)
    workpaper_id: Mapped[int] = mapped_column(ForeignKey("pit_reconciliation_workpapers.id"), nullable=False, index=True)
    detail_type: Mapped[str] = mapped_column(String(40), nullable=False); org_code: Mapped[str] = mapped_column(String(80), nullable=False); org_name: Mapped[str] = mapped_column(String(255), default="", nullable=False); subject_code: Mapped[Optional[str]] = mapped_column(String(20)); identity_key: Mapped[str] = mapped_column(String(255), nullable=False); person_or_customer_name: Mapped[str] = mapped_column(String(255), default="", nullable=False); id_number: Mapped[Optional[str]] = mapped_column(String(80)); source_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); target_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); difference: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); auto_reason: Mapped[Optional[str]] = mapped_column(Text); manual_reason: Mapped[Optional[str]] = mapped_column(Text); remark: Mapped[Optional[str]] = mapped_column(Text); detail_json: Mapped[Optional[dict]] = mapped_column(JSON)


class PitBankTaxMatch(_PitBase, Base):
    __tablename__ = "pit_bank_tax_matches"
    workpaper_id: Mapped[int] = mapped_column(ForeignKey("pit_reconciliation_workpapers.id"), nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(80), nullable=False); org_full_name: Mapped[str] = mapped_column(String(255), default="", nullable=False); bank_account: Mapped[Optional[str]] = mapped_column(String(120)); transaction_time: Mapped[Optional[str]] = mapped_column(String(80)); transaction_summary: Mapped[Optional[str]] = mapped_column(String(500)); debit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2)); source_batch_id: Mapped[Optional[int]] = mapped_column(Integer); source_row_id: Mapped[Optional[int]] = mapped_column(Integer)
