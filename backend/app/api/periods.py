from __future__ import annotations

from datetime import date
from typing import List

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException

from app.db.session import get_db
from app.models.core import Period
from app.schemas.core import PeriodCreate, PeriodRead

router = APIRouter(prefix="/periods", tags=["periods"])


def _create_period(db: Session, year: int, month: int) -> Period:
    period = Period(
        year=year,
        month=month,
        name=f"{year}年{month:02d}月",
    )
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


@router.get("", response_model=List[PeriodRead])
def list_periods(db: Session = Depends(get_db)) -> List[Period]:
    rows = db.query(Period).order_by(Period.year.desc(), Period.month.desc()).all()
    if rows:
        return rows
    today = date.today()
    year = today.year if today.month > 1 else today.year - 1
    month = today.month - 1 if today.month > 1 else 12
    return [_create_period(db, year, month)]


@router.post("", response_model=PeriodRead)
def create_period(payload: PeriodCreate, db: Session = Depends(get_db)) -> Period:
    existing = (
        db.query(Period)
        .filter(Period.year == payload.year, Period.month == payload.month)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="该所属期间已存在")
    return _create_period(db, payload.year, payload.month)
