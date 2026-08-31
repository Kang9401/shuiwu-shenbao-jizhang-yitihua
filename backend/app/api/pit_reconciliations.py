from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import require_company, require_period
from app.core.company_context import current_company_id
from app.db.session import get_db
from app.models.pit_reconciliation import (PitBankTaxMatch, PitDeclarationSummary, PitOccurrenceCheck, PitReconciliationDifferenceDetail, PitReconciliationOrgSummary, PitReconciliationSource, PitReconciliationWorkpaper, PitTaxAmountCheck)
from app.schemas.pit_reconciliation import PitManualUpdate
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
@router.get("/tax-amount-checks")
def tax_amount_checks(period_id:int=Query(...),db:Session=Depends(get_db)): return _list(PitTaxAmountCheck,period_id,db)
@router.get("/occurrence-checks")
def occurrence_checks(period_id:int=Query(...),db:Session=Depends(get_db)): return _list(PitOccurrenceCheck,period_id,db)
@router.get("/org-summaries")
def org_summaries(period_id:int=Query(...),db:Session=Depends(get_db)): return _list(PitReconciliationOrgSummary,period_id,db)
@router.get("/declaration-summaries")
def declaration_summaries(period_id:int=Query(...),db:Session=Depends(get_db)): return _list(PitDeclarationSummary,period_id,db)
@router.get("/difference-details")
def difference_details(period_id:int=Query(...),detail_type:str|None=Query(None),org_code:str|None=Query(None),db:Session=Depends(get_db)):
    row=_workpaper(db,period_id); query=db.query(PitReconciliationDifferenceDetail).filter_by(workpaper_id=row.id,company_id=current_company_id())
    if detail_type:query=query.filter_by(detail_type=detail_type)
    if org_code:query=query.filter_by(org_code=org_code)
    return [_payload(item) for item in query.all()]
@router.get("/bank-matches")
def bank_matches(period_id:int=Query(...),db:Session=Depends(get_db)): return _list(PitBankTaxMatch,period_id,db)

def _patch(model,record_id:int,values:PitManualUpdate,db:Session,manual_field:str):
    row=db.query(model).filter_by(id=record_id,company_id=current_company_id()).first()
    if row is None:raise HTTPException(status_code=404,detail="核对记录不存在")
    if values.manual_reason is not None:setattr(row,manual_field,values.manual_reason)
    if values.remark is not None:setattr(row,"remark",values.remark)
    db.commit();db.refresh(row);return _payload(row)
@router.patch("/tax-amount-checks/{record_id}")
def patch_tax(record_id:int,values:PitManualUpdate,field:str=Query("business_declared_manual_reason",pattern="^(current_manual_reason|cumulative_manual_reason|business_declared_manual_reason)$"),db:Session=Depends(get_db)): return _patch(PitTaxAmountCheck,record_id,values,db,field)
@router.patch("/occurrence-checks/{record_id}")
def patch_occurrence(record_id:int,values:PitManualUpdate,field:str=Query("declared_income_manual_reason",pattern="^(broker_occurrence_manual_reason|declared_income_manual_reason)$"),db:Session=Depends(get_db)): return _patch(PitOccurrenceCheck,record_id,values,db,field)
@router.patch("/org-summaries/{record_id}")
def patch_summary(record_id:int,values:PitManualUpdate,field:str=Query("difference_1_manual_reason",pattern="^difference_[1-7]_manual_reason$"),db:Session=Depends(get_db)): return _patch(PitReconciliationOrgSummary,record_id,values,db,field)
@router.patch("/difference-details/{record_id}")
def patch_detail(record_id:int,values:PitManualUpdate,db:Session=Depends(get_db)): return _patch(PitReconciliationDifferenceDetail,record_id,values,db,"manual_reason")
