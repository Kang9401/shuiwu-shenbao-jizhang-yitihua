from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.bank_fetch import bank_fetch_service

router = APIRouter(prefix="/bank-fetch", tags=["bank-fetch"])


class BankFetchStart(BaseModel):
    period_id: int = Field(gt=0)
    accounts: str = Field(min_length=1, max_length=20000)
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/start")
def start(request: BankFetchStart):
    try:
        return bank_fetch_service.start(**request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/status")
def status():
    return bank_fetch_service.status()


@router.post("/open-login")
def open_login():
    try:
        return bank_fetch_service.open_login()
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/stop")
def stop():
    return bank_fetch_service.stop()

