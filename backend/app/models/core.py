from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.core.version import APP_VERSION, RULESET_VERSION


class Period(Base):
    __tablename__ = "periods"
    __table_args__ = (UniqueConstraint("year", "month", name="uq_period_year_month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("periods.id"), nullable=True)
    file_role: Mapped[str] = mapped_column(String(80), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    validation_status: Mapped[str] = mapped_column(String(32), default="pending")
    validation_issues: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    period: Mapped[Optional[Period]] = relationship()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workflow_code: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    period_id: Mapped[Optional[int]] = mapped_column(ForeignKey("periods.id"), nullable=True)
    operation: Mapped[str] = mapped_column(String(40), default="generate", nullable=False, index=True)
    app_version: Mapped[str] = mapped_column(String(32), default=APP_VERSION, nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(32), default=RULESET_VERSION, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    input_file_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    result_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    period: Mapped[Optional[Period]] = relationship()
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="job")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped[Job] = relationship(back_populates="artifacts")
