from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.company_context import current_company_id
from app.db.session import Base


class IncomeImportBatch(Base):
    """Current structured source for non-payroll income workflows.

    A batch is replaced atomically for one workflow, period, role and
    organisation.  The source workbook remains available through the legacy
    UploadedFile table for compatibility, but calculations can use these rows
    directly.
    """

    __tablename__ = "income_import_batches"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "period_id", "workflow_code", "source_role", "org_code",
            name="uq_income_import_company_period_workflow_role_org",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    workflow_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_role: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    source_file_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    source_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="valid", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IncomeRecord(Base):
    """One raw, source-shaped row belonging to the current income batch."""

    __tablename__ = "income_records"
    __table_args__ = (
        UniqueConstraint("batch_id", "source_row_number", name="uq_income_record_batch_row"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("income_import_batches.id"), nullable=False, index=True)
    workflow_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_role: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    org_code: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    source_row_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    person_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    id_number: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    employee_no: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    data_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class IncomeWorkpaper(Base):
    """Latest calculated detail and review state for a non-payroll workflow."""

    __tablename__ = "income_workpapers"
    __table_args__ = (
        UniqueConstraint("company_id", "period_id", "workflow_code", name="uq_income_workpaper_company_period_workflow"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), default=current_company_id, nullable=False, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    workflow_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="valid", nullable=False, index=True)
    input_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    detail_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    summary_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    issues_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    manual_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
