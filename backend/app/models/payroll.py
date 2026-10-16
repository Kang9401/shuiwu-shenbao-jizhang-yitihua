from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.company_context import current_company_id
from app.db.session import Base


class PayrollImportBatch(Base):
    """The current successful import for one payroll kind and organization."""

    __tablename__ = "payroll_import_batches"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "period_id",
            "salary_type",
            "org_code",
            name="uq_payroll_import_company_period_type_org",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    salary_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    source_file_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    source_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="valid", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PayrollEmployeeRecord(Base):
    """One normalized employee row from the current payroll import."""

    __tablename__ = "payroll_employee_records"
    __table_args__ = (
        UniqueConstraint(
            "import_batch_id",
            "source_row_number",
            name="uq_payroll_record_batch_row",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    import_batch_id: Mapped[int] = mapped_column(ForeignKey("payroll_import_batches.id"), nullable=False, index=True)
    salary_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    source_row_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    employee_no: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    person_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    id_type: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    id_number: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    salary_scheme: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    data_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PayrollCalculationResult(Base):
    """Latest calculated row, including reconciliation fields and manual data."""

    __tablename__ = "payroll_calculation_results"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "period_id",
            "salary_type",
            "org_code",
            "source_row_number",
            name="uq_payroll_result_company_period_row",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    salary_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    source_row_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    employee_no: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    person_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="valid", nullable=False, index=True)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PayrollWorkpaper(Base):
    """Current database-backed monthly workpaper; no Excel/BLOB is required."""

    __tablename__ = "payroll_workpapers"
    __table_args__ = (
        UniqueConstraint("company_id", "period_id", name="uq_payroll_workpaper_company_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    input_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="valid", nullable=False, index=True)
    sheet_rows_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    report_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    manual_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
