# backend/app/models/tax.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class VerificationSession(Base):
    """核对会话 — 代表某个申报月份的个税申报全过程"""
    __tablename__ = "verification_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), default="uploading", index=True)
    current_round: Mapped[int] = mapped_column(Integer, default=1)
    confirmed_personnel: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    rounds: Mapped[list["VerificationRound"]] = relationship(back_populates="session", order_by="VerificationRound.round_number")


class VerificationRound(Base):
    """核对轮次 — 每次上传文件后运行核对产生一轮"""
    __tablename__ = "verification_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("verification_sessions.id"), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_files: Mapped[list] = mapped_column(JSON, nullable=False)
    report_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["VerificationSession"] = relationship(back_populates="rounds")


class TaxMonthlyArtifact(Base):
    """按申报月份保留的一份正式个税产物。"""
    __tablename__ = "tax_monthly_artifacts"
    __table_args__ = (
        UniqueConstraint("period_id", "artifact_type", name="uq_tax_monthly_artifact_period_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    source_session_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_round_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
