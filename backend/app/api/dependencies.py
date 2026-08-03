from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.company_context import reset_company_id, set_company_id
from app.db.session import get_db
from app.models.core import Company, Period


async def require_company(
    x_company_id: Optional[int] = Header(default=None, alias="X-Company-ID", gt=0),
    company_id: Optional[int] = Query(default=None, gt=0),
    db: Session = Depends(get_db),
) -> AsyncGenerator[Company, None]:
    selected_id = x_company_id or company_id
    if selected_id is None:
        raise HTTPException(status_code=400, detail="请选择分公司")
    company = db.query(Company).filter(Company.id == selected_id, Company.active == 1).first()
    if company is None:
        raise HTTPException(status_code=404, detail="分公司不存在或已停用")
    token = set_company_id(company.id)
    try:
        yield company
    finally:
        reset_company_id(token)


def require_period(db: Session, period_id: int) -> Period:
    period = db.query(Period).filter(Period.id == period_id).first()
    if period is None:
        raise HTTPException(status_code=404, detail="所属期间不存在")
    return period
