from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_company, require_period
from app.core.company_context import current_company_id
from app.db.session import get_db
from app.models.pit_reconciliation import (PitBankTaxMatch, PitDeclarationSummary, PitOccurrenceCheck, PitReconciliationDifferenceDetail, PitReconciliationOrgSummary, PitReconciliationSource, PitReconciliationWorkpaper, PitTaxAmountCheck)
from app.schemas.pit_reconciliation import PitManualUpdate, PitOccurrenceCheckUpdate, PitSummaryUpdate, PitTaxAmountCheckUpdate
from app.services.pit_reconciliation.engine import PitReconciliationEngine
from app.services.pit_reconciliation.repository import PitReconciliationRepository
from app.services.pit_reconciliation.source_service import PitSourceService

router=APIRouter(prefix="/pit-reconciliations",tags=["pit-reconciliations"],dependencies=[Depends(require_company)])

def _workpaper(db: Session, period_id: int):
    require_period(db,period_id)
    row=db.query(PitReconciliationWorkpaper).filter_by(company_id=current_company_id(),period_id=period_id,tax_type="pit").first()
    if row is None: raise HTTPException(status_code=404,detail="当前所属期尚未生成个税核对底稿")
    return row

def _payload(row):
    return {column.name:getattr(row,column.name) for column in row.__table__.columns}

@router.get("/overview")
def overview(period_id:int=Query(...),db:Session=Depends(get_db)):
    try: row=_workpaper(db,period_id)
    except HTTPException as exc:
        if exc.status_code==404:return {"exists":False,"period_id":period_id}
        raise
    return {"exists":True,"workpaper":_payload(row),"counts":{"sources":db.query(PitReconciliationSource).filter_by(workpaper_id=row.id).count(),"tax_checks":db.query(PitTaxAmountCheck).filter_by(workpaper_id=row.id).count(),"occurrence_checks":db.query(PitOccurrenceCheck).filter_by(workpaper_id=row.id).count(),"details":db.query(PitReconciliationDifferenceDetail).filter_by(workpaper_id=row.id).count()}}

@router.get("/readiness")
def readiness(period_id:int=Query(...),db:Session=Depends(get_db)):
    try: row=_workpaper(db,period_id)
    except HTTPException as exc:
        if exc.status_code==404:
            bundle=PitSourceService(db,current_company_id(),period_id).load_bundle()
            return [{"source_type":source.source_type,"source_status":source.status,"required":source.required,"row_count":len(source.rows),"issues_json":source.issues} for source in (bundle.organizations,bundle.salary,bundle.declarations,bundle.balance,bundle.broker,bundle.bond_interest,bundle.restricted_stock,bundle.certificates,bundle.bank)]
        raise
    return [_payload(item) for item in db.query(PitReconciliationSource).filter_by(workpaper_id=row.id).order_by(PitReconciliationSource.source_type).all()]

@router.post("/recalculate")
def recalculate(period_id:int=Query(...),db:Session=Depends(get_db)):
    require_period(db,period_id); repository=PitReconciliationRepository(db,current_company_id(),period_id); workpaper=repository.get_or_create_workpaper(); workpaper.calculation_status="running"; db.commit()
    try:
        result=PitReconciliationEngine().calculate(PitSourceService(db,current_company_id(),period_id).load_bundle())
        repository.replace(workpaper,result); db.commit(); db.refresh(workpaper); return {"workpaper":_payload(workpaper),"message":"已覆盖更新同一份月度个税核对底稿"}
    except Exception as exc:
        db.rollback(); workpaper=repository.get_or_create_workpaper(); workpaper.calculation_status="failed"; workpaper.last_error=str(exc); db.commit(); raise HTTPException(status_code=400,detail=f"个税底稿计算失败：{exc}") from exc

def _list(model,period_id,db):
    row=_workpaper(db,period_id); return [_payload(item) for item in db.query(model).filter_by(workpaper_id=row.id,company_id=current_company_id()).all()]

def _has_difference(*values):
    return any(value is not None and abs(value) > Decimal("0.01") for value in values)
@router.get("/tax-amount-checks")
def tax_amount_checks(period_id:int=Query(...),org_code:str|None=Query(None),subject_code:str|None=Query(None),only_differences:bool=False,db:Session=Depends(get_db)):
    row=_workpaper(db,period_id); query=db.query(PitTaxAmountCheck).filter_by(workpaper_id=row.id,company_id=current_company_id())
    if org_code: query=query.filter_by(org_code=org_code)
    if subject_code: query=query.filter_by(subject_code=subject_code)
    items=query.order_by(PitTaxAmountCheck.org_code,PitTaxAmountCheck.subject_code).all()
    if only_differences: items=[item for item in items if _has_difference(item.current_difference,item.cumulative_difference,item.business_declared_difference)]
    return [_payload(item) for item in items]
@router.get("/occurrence-checks")
def occurrence_checks(period_id:int=Query(...),org_code:str|None=Query(None),subject_code:str|None=Query(None),only_differences:bool=False,db:Session=Depends(get_db)):
    row=_workpaper(db,period_id); query=db.query(PitOccurrenceCheck).filter_by(workpaper_id=row.id,company_id=current_company_id())
    if org_code: query=query.filter_by(org_code=org_code)
    if subject_code: query=query.filter_by(subject_code=subject_code)
    items=query.order_by(PitOccurrenceCheck.org_code,PitOccurrenceCheck.subject_code).all()
    if only_differences: items=[item for item in items if _has_difference(item.broker_occurrence_difference,item.declared_income_difference)]
    return [_payload(item) for item in items]
@router.get("/org-summaries")
def org_summaries(period_id:int=Query(...),db:Session=Depends(get_db)): return _list(PitReconciliationOrgSummary,period_id,db)
@router.get("/declaration-summaries")
def declaration_summaries(period_id:int=Query(...),db:Session=Depends(get_db)): return _list(PitDeclarationSummary,period_id,db)
@router.get("/difference-details")
def difference_details(period_id:int=Query(...),detail_type:str|None=Query(None),org_code:str|None=Query(None),subject_code:str|None=Query(None),search:str|None=Query(None),db:Session=Depends(get_db)):
    row=_workpaper(db,period_id); query=db.query(PitReconciliationDifferenceDetail).filter_by(workpaper_id=row.id,company_id=current_company_id())
    if detail_type:query=query.filter_by(detail_type=detail_type)
    if org_code:query=query.filter_by(org_code=org_code)
    if subject_code:query=query.filter_by(subject_code=subject_code)
    if search:query=query.filter(PitReconciliationDifferenceDetail.person_or_customer_name.ilike(f"%{search.strip()}%"))
    return [_payload(item) for item in query.all()]
@router.get("/bank-matches")
def bank_matches(period_id:int=Query(...),db:Session=Depends(get_db)): return _list(PitBankTaxMatch,period_id,db)

def _patch(model,record_id:int,values,db:Session,manual_field:str|None=None):
    row=db.query(model).filter_by(id=record_id,company_id=current_company_id()).first()
    if row is None:raise HTTPException(status_code=404,detail="核对记录不存在")
    data=values.model_dump(exclude_none=True)
    if manual_field and "manual_reason" in data:setattr(row,manual_field,data.pop("manual_reason"))
    for field,value in data.items():setattr(row,field,value)
    db.commit();db.refresh(row);return _payload(row)
@router.patch("/tax-amount-checks/{record_id}")
def patch_tax(record_id:int,values:PitTaxAmountCheckUpdate,db:Session=Depends(get_db)): return _patch(PitTaxAmountCheck,record_id,values,db)
@router.patch("/occurrence-checks/{record_id}")
def patch_occurrence(record_id:int,values:PitOccurrenceCheckUpdate,db:Session=Depends(get_db)): return _patch(PitOccurrenceCheck,record_id,values,db)
@router.patch("/org-summaries/{record_id}")
def patch_summary(record_id:int,values:PitSummaryUpdate,db:Session=Depends(get_db)): return _patch(PitReconciliationOrgSummary,record_id,values,db)
@router.patch("/difference-details/{record_id}")
def patch_detail(record_id:int,values:PitManualUpdate,db:Session=Depends(get_db)): return _patch(PitReconciliationDifferenceDetail,record_id,values,db,"manual_reason")
