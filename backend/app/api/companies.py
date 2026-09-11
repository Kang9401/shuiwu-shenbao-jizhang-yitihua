from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.core import Company
from app.schemas.company import CompanyPayload, CompanyRead, CompanyStatusUpdate


router = APIRouter(prefix="/companies", tags=["companies"])


def _ensure_unique(db: Session, payload: CompanyPayload, exclude_id: int | None = None) -> None:
    query = db.query(Company).filter(
        (func.lower(Company.name) == payload.name.lower())
        | (func.lower(Company.code) == payload.code.lower())
    )
    if exclude_id is not None:
        query = query.filter(Company.id != exclude_id)
    existing = query.first()
    if existing is None:
        return
    field = "名称" if existing.name.lower() == payload.name.lower() else "编码"
    raise HTTPException(status_code=409, detail=f"分公司{field}已存在")


@router.get("", response_model=list[CompanyRead])
def list_companies(include_inactive: bool = False, db: Session = Depends(get_db)) -> list[Company]:
    query = db.query(Company)
    if not include_inactive:
        query = query.filter(Company.active == 1)
    return query.order_by(Company.active.desc(), Company.name, Company.id).all()


@router.post("", response_model=CompanyRead, status_code=201)
def create_company(payload: CompanyPayload, db: Session = Depends(get_db)) -> Company:
    _ensure_unique(db, payload)
    item = Company(**payload.model_dump(), active=1)
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="分公司名称或编码已存在") from exc
    db.refresh(item)
    return item


@router.post("/{company_id}/select", response_model=CompanyRead)
def select_company(company_id: int, db: Session = Depends(get_db)) -> Company:
    item = db.query(Company).filter(Company.id == company_id, Company.active == 1).first()
    if item is None:
        raise HTTPException(status_code=404, detail="分公司不存在或已停用")
    from app.bank_fetch import bank_fetch_service
    from app.rpa.service import rpa_service

    if rpa_service.manager.running and rpa_service.company_id != company_id:
        raise HTTPException(status_code=409, detail="RPA 任务运行中，不能切换分公司")
    if bank_fetch_service.has_running_task() and not bank_fetch_service.is_company_running(company_id):
        raise HTTPException(status_code=409, detail="银行流水任务运行中，不能切换分公司")
    return item


@router.put("/{company_id}", response_model=CompanyRead)
def update_company(company_id: int, payload: CompanyPayload, db: Session = Depends(get_db)) -> Company:
    item = db.query(Company).filter(Company.id == company_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="分公司不存在")
    _ensure_unique(db, payload, exclude_id=company_id)
    for field, value in payload.model_dump().items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{company_id}/status", response_model=CompanyRead)
def update_company_status(
    company_id: int,
    payload: CompanyStatusUpdate,
    db: Session = Depends(get_db),
) -> Company:
    item = db.query(Company).filter(Company.id == company_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="分公司不存在")
    if not payload.active:
        active_count = db.query(Company).filter(Company.active == 1).count()
        if item.active and active_count <= 1:
            raise HTTPException(status_code=409, detail="至少需要保留一个启用的分公司")
        from app.bank_fetch import bank_fetch_service
        from app.rpa.service import rpa_service

        if rpa_service.is_company_running(company_id) or bank_fetch_service.is_company_running(company_id):
            raise HTTPException(status_code=409, detail="该分公司有自动化任务正在运行，不能停用")
    item.active = int(payload.active)
    db.commit()
    db.refresh(item)
    return item
