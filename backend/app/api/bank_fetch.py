from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from app.bank_fetch import bank_fetch_service
from app.api.dependencies import require_company, require_period
from app.db.session import get_db
from app.models.core import Company
from sqlalchemy.orm import Session

router = APIRouter(prefix="/bank-fetch", tags=["bank-fetch"], dependencies=[Depends(require_company)])


class BankFetchStart(BaseModel):
    period_id: int = Field(gt=0)
    accounts: str = Field(min_length=1, max_length=20000)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/start")
def start(
    request: BankFetchStart,
    company: Company = Depends(require_company),
    db: Session = Depends(get_db),
):
    try:
        require_period(db, request.period_id)
        return bank_fetch_service.start(company_id=company.id, **request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/status")
def status(company: Company = Depends(require_company)):
    return bank_fetch_service.status_for(company.id)


@router.post("/open-login")
def open_login():
    try:
        return bank_fetch_service.open_login()
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/stop")
def stop(company: Company = Depends(require_company)):
    try:
        return bank_fetch_service.stop(company.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
