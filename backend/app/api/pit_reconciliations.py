from __future__ import annotations

import io
import json
from decimal import Decimal

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from typing import Literal
from urllib.parse import quote
from sqlalchemy.orm import Session

from app.api.dependencies import require_company, require_period
from app.core.company_context import current_company_id
from app.db.session import get_db
from app.models.pit_reconciliation import (PitBankTaxMatch, PitDeclarationSummary, PitOccurrenceCheck, PitReconciliationDifferenceDetail, PitReconciliationOrgSummary, PitReconciliationSource, PitReconciliationWorkpaper, PitTaxAmountCheck)
from app.schemas.pit_reconciliation import PitManualUpdate, PitOccurrenceCheckUpdate, PitReasonAggregationRequest, PitSummaryUpdate, PitTaxAmountCheckUpdate
from app.services.pit_reconciliation.engine import PitReconciliationEngine
from app.services.pit_reconciliation.repository import PitReconciliationRepository
from app.services.pit_reconciliation.source_service import PitSourceService
from app.services.pit_reconciliation.exporter import build_occurrence_descriptions_xlsx, sheet_names_for_stage, build_pit_workpaper_sheets, build_pit_workpaper_xlsx
from app.services.pit_reconciliation.reason_aggregation import aggregate_reasons
from app.integrations.fmss.errors import FmssError
from app.services.pit_online_service import PitOnlineService

router=APIRouter(prefix="/pit-reconciliations",tags=["pit-reconciliations"],dependencies=[Depends(require_company)])

def _workpaper(db: Session, period_id: int, stage: Literal["pre_payment", "post_payment"], *, allow_stale: bool = False):
    require_period(db,period_id)
    row=db.query(PitReconciliationWorkpaper).filter_by(company_id=current_company_id(),period_id=period_id,tax_type="pit",stage=stage).first()
    if row is None: raise HTTPException(status_code=404,detail="当前所属期尚未生成个税核对底稿")
    if row.calculation_status == "stale" and not allow_stale:
        raise HTTPException(status_code=409, detail="核对来源已改变，请重新核对后查看或导出")
    return row

def _payload(row):
    return {column.name:getattr(row,column.name) for column in row.__table__.columns}


def _ensure_online_editable(db: Session, workpaper: PitReconciliationWorkpaper) -> None:
    """FMSS is authoritative once a local workpaper is linked to a declaration."""
    if not workpaper.platform_submission_id:
        return
    try:
        PitOnlineService(db).enforce_editable(workpaper)
    except FmssError as exc:
        # A failed state lookup must not unlock a workpaper that is already online.
        raise HTTPException(status_code=409, detail=exc.user_message if exc.user_message else "该底稿存在FMSS线上关联，连接FMSS后才能继续修改。") from exc


def _stage_sources(bundle, stage: str):
    sources = (bundle.organizations, bundle.salary, bundle.declarations, bundle.balance, bundle.broker, bundle.bond_interest, bundle.restricted_stock) if stage == "pre_payment" else (bundle.certificates, bundle.bank)
    return [{"source_type": source.source_type, "source_status": source.status, "required": True, "row_count": len(source.rows), "source_kind": source.source_kind, "source_id": source.source_id, "source_ref": source.source_ref, "issues_json": source.issues} for source in sources]

@router.get("/overview")
def overview(period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),db:Session=Depends(get_db)):
    try: row=_workpaper(db,period_id,stage,allow_stale=True)
    except HTTPException as exc:
        if exc.status_code==404:return {"exists":False,"period_id":period_id,"stage":stage}
        raise
    return {"exists":True,"workpaper":_payload(row),"counts":{"sources":db.query(PitReconciliationSource).filter_by(workpaper_id=row.id).count(),"tax_checks":db.query(PitTaxAmountCheck).filter_by(workpaper_id=row.id).count(),"occurrence_checks":db.query(PitOccurrenceCheck).filter_by(workpaper_id=row.id).count(),"details":db.query(PitReconciliationDifferenceDetail).filter_by(workpaper_id=row.id).count()}}

@router.get("/readiness")
def readiness(period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),db:Session=Depends(get_db)):
    require_period(db, period_id)
    # Readiness describes today's source data, not the prior calculation snapshot.
    return _stage_sources(PitSourceService(db,current_company_id(),period_id).load_bundle(), stage)

@router.post("/recalculate")
def recalculate(period_id:int=Query(...),stage:Literal["pre_payment","post_payment"] = Query(...),db:Session=Depends(get_db)):
    require_period(db,period_id); repository=PitReconciliationRepository(db,current_company_id(),period_id,stage); workpaper=repository.get_or_create_workpaper()
    _ensure_online_editable(db, workpaper)
    if workpaper.workflow_status in {"submitted", "reviewed"}: raise HTTPException(status_code=409,detail="当前底稿已锁定，不能重新计算")
    previous_calculation_status = workpaper.calculation_status
    previous_workflow_status = workpaper.workflow_status
    workpaper.calculation_status="running"; db.commit()
    try:
        bundle = PitSourceService(db,current_company_id(),period_id).load_bundle()
        if bundle.salary.status == "invalid":
            messages = [str(issue.get("message", "")) for issue in bundle.salary.issues if issue.get("message")]
            raise ValueError("；".join(messages) or "工资底稿字段无效")
        if stage == "post_payment" and bundle.certificates.status in {"missing", "invalid"}:
            raise ValueError("扣款后核对需要先导入完税凭证")
        if stage == "post_payment" and bundle.bank.status in {"missing", "invalid"}:
            raise ValueError("扣款后核对需要先导入银行流水")
        result=PitReconciliationEngine().calculate(bundle)
        result["stage"] = stage
        stage_sources = _stage_sources(bundle, stage)
        complete = all(item["source_status"] in {"ready", "ready_empty", "not_applicable"} and not item["issues_json"] for item in stage_sources)
        result["data_status"] = "ready" if complete else "incomplete"
        result["missing_sources"] = [item["source_type"] for item in stage_sources if item["source_status"] in {"missing", "invalid"} or item["issues_json"]]
        workpaper=repository.replace(workpaper,result); db.commit(); db.refresh(workpaper); return {"workpaper":_payload(workpaper),"message":"已覆盖更新同一份月度个税核对底稿"}
    except Exception as exc:
        db.rollback()
        workpaper=repository.get_or_create_workpaper()
        # A failed retry must not invalidate an already usable, independently saved workpaper.
        if previous_calculation_status == "success":
            workpaper.calculation_status = "success"
            workpaper.workflow_status = previous_workflow_status
        else:
            workpaper.calculation_status = "failed"
            workpaper.workflow_status = "data_preparation"
        workpaper.last_error=str(exc)
        db.commit()
        raise HTTPException(status_code=400,detail=f"个税底稿计算失败：{exc}") from exc


@router.post("/aggregate-reasons")
def aggregate_reason_fields(
    payload: PitReasonAggregationRequest,
    period_id: int = Query(...),
    stage: Literal["pre_payment", "post_payment"] = Query(...),
    db: Session = Depends(get_db),
):
    if stage != "pre_payment":
        raise HTTPException(status_code=400, detail="缴款后没有下级人工原因结构，不能汇总")
    workpaper = _workpaper(db, period_id, stage)
    _ensure_online_editable(db, workpaper)
    if workpaper.workflow_status in {"submitted", "reviewed"}:
        raise HTTPException(status_code=409, detail="当前底稿已锁定，不能汇总原因")
    result = aggregate_reasons(db, workpaper, payload.mode)
    if result.changed:
        if workpaper.workflow_status == "returned":
            workpaper.workflow_status = "pending_submission"
        workpaper.draft_revision += 1
        db.commit()
        db.refresh(workpaper)
    return {
        "changed": result.changed,
        "draft_revision": workpaper.draft_revision,
        "updated_counts": result.updated_counts,
        "skipped_manual_fields": result.skipped_manual_fields,
        "message": (
            f"已更新{sum(result.updated_counts.values())}项自动汇总，保留{result.skipped_manual_fields}项人工填写"
            if result.changed else "没有需要更新的汇总原因"
        ),
    }

def _list(model,period_id,stage,db):
    row=_workpaper(db,period_id,stage); return [_payload(item) for item in db.query(model).filter_by(workpaper_id=row.id,company_id=current_company_id()).all()]

def _has_difference(*values):
    return any(value is not None and abs(value) > Decimal("0.01") for value in values)
@router.get("/tax-amount-checks")
def tax_amount_checks(period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),org_code:str|None=Query(None),subject_code:str|None=Query(None),only_differences:bool=False,db:Session=Depends(get_db)):
    row=_workpaper(db,period_id,stage); query=db.query(PitTaxAmountCheck).filter_by(workpaper_id=row.id,company_id=current_company_id())
    if org_code: query=query.filter_by(org_code=org_code)
    if subject_code: query=query.filter_by(subject_code=subject_code)
    items=query.order_by(PitTaxAmountCheck.org_code,PitTaxAmountCheck.subject_code).all()
    if only_differences: items=[item for item in items if _has_difference(item.current_difference,item.cumulative_difference,item.business_declared_difference)]
    return [_payload(item) for item in items]
@router.get("/occurrence-checks")
def occurrence_checks(period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),org_code:str|None=Query(None),subject_code:str|None=Query(None),only_differences:bool=False,db:Session=Depends(get_db)):
    row=_workpaper(db,period_id,stage); query=db.query(PitOccurrenceCheck).filter_by(workpaper_id=row.id,company_id=current_company_id())
    if org_code: query=query.filter_by(org_code=org_code)
    if subject_code: query=query.filter_by(subject_code=subject_code)
    items=query.order_by(PitOccurrenceCheck.org_code,PitOccurrenceCheck.subject_code).all()
    if only_differences: items=[item for item in items if _has_difference(item.broker_occurrence_difference,item.declared_income_difference)]
    return [_payload(item) for item in items]
@router.get("/org-summaries")
def org_summaries(period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),db:Session=Depends(get_db)): return _list(PitReconciliationOrgSummary,period_id,stage,db)
@router.get("/declaration-summaries")
def declaration_summaries(period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),db:Session=Depends(get_db)): return _list(PitDeclarationSummary,period_id,stage,db)
@router.get("/difference-details")
def difference_details(period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),detail_type:str|None=Query(None),org_code:str|None=Query(None),subject_code:str|None=Query(None),search:str|None=Query(None),db:Session=Depends(get_db)):
    row=_workpaper(db,period_id,stage); query=db.query(PitReconciliationDifferenceDetail).filter_by(workpaper_id=row.id,company_id=current_company_id())
    if detail_type:query=query.filter_by(detail_type=detail_type)
    if org_code:query=query.filter_by(org_code=org_code)
    if subject_code:query=query.filter_by(subject_code=subject_code)
    if search:query=query.filter(PitReconciliationDifferenceDetail.person_or_customer_name.ilike(f"%{search.strip()}%"))
    return [_payload(item) for item in query.all()]
@router.get("/bank-matches")
def bank_matches(period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),db:Session=Depends(get_db)): return _list(PitBankTaxMatch,period_id,stage,db)

@router.get("/sheet-data")
def sheet_data(
    period_id: int = Query(...),
    stage: Literal["pre_payment", "post_payment"] = Query(...),
    sheet_name: str = Query(...),
    keyword: str | None = Query(None),
    org_code: str | None = Query(None),
    display_mode: Literal["all", "difference", "missing"] = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    workpaper = _workpaper(db, period_id, stage)
    if sheet_name not in sheet_names_for_stage(stage):
        raise HTTPException(status_code=404, detail="底稿工作表不存在")
    frame = build_pit_workpaper_sheets(db, current_company_id(), period_id, workpaper)[sheet_name]
    if org_code and "机构代码" in frame.columns:
        frame = frame[frame["机构代码"].astype(str) == org_code]
    if keyword:
        needle = keyword.strip().lower()
        if needle:
            frame = frame[frame.astype(str).apply(lambda row: row.str.lower().str.contains(needle, regex=False).any(), axis=1)]
    difference_columns = [column for column in frame.columns if "差异" in str(column)]
    if display_mode == "difference" and difference_columns:
        frame = frame[frame[difference_columns].apply(lambda row: any(value not in (None, "", 0, 0.0) and abs(float(value)) > 0.01 if str(value).replace(".", "", 1).replace("-", "", 1).isdigit() else False for value in row), axis=1)]
    if display_mode == "missing":
        frame = frame[frame.isna().any(axis=1) | frame.eq("").any(axis=1)]
    total = len(frame)
    start = (page - 1) * page_size
    rows = json.loads(frame.iloc[start:start + page_size].to_json(orient="records", date_format="iso", force_ascii=False))
    column_labels = list(frame.columns)
    if sheet_name == "缴税核对":
        column_labels = ["机构代码", "营业部全称", "申报表", "完税证明", "申报表与完税证明差异金额11", "差异原因11", "银行流水个税", "完税证明与银行流水差异金额12", "差异原因12"]
    return {"sheet_name": sheet_name, "columns": list(frame.columns), "column_labels": column_labels, "rows": rows, "total": total, "page": page, "page_size": page_size}

@router.get("/export")
def export_workpaper(period_id: int = Query(...), stage: Literal["pre_payment", "post_payment"] = Query(...), db: Session = Depends(get_db)):
    workpaper = _workpaper(db, period_id, stage)
    content = build_pit_workpaper_xlsx(db, current_company_id(), period_id, workpaper)
    filename = f"个税核对底稿_{period_id}_{'缴款前' if stage == 'pre_payment' else '缴款后'}.xlsx"
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


def _occurrence_import_key(value: object) -> str:
    text = "" if value is None or pd.isna(value) else str(value).strip()
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


@router.get("/occurrence-descriptions/export")
def export_occurrence_descriptions(period_id: int = Query(...), stage: Literal["pre_payment", "post_payment"] = Query(...), db: Session = Depends(get_db)):
    if stage != "pre_payment":
        raise HTTPException(status_code=400, detail="发生额应申报收入说明仅适用于缴款前底稿")
    workpaper = _workpaper(db, period_id, stage)
    content = build_occurrence_descriptions_xlsx(db, current_company_id(), period_id, workpaper)
    filename = f"其他个税发生额核对说明_{period_id}.xlsx"
    return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.post("/occurrence-descriptions/import")
async def import_occurrence_descriptions(
    period_id: int = Query(...),
    stage: Literal["pre_payment", "post_payment"] = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if stage != "pre_payment":
        raise HTTPException(status_code=400, detail="发生额应申报收入说明仅适用于缴款前底稿")
    workpaper = _workpaper(db, period_id, stage)
    _ensure_online_editable(db, workpaper)
    if workpaper.workflow_status in {"submitted", "reviewed"}:
        raise HTTPException(status_code=409, detail="当前底稿已锁定，不能导入说明")
    try:
        frame = pd.read_excel(io.BytesIO(await file.read()), dtype=object)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"说明导入文件无法读取：{exc}") from exc
    required_columns = {"机构代码", "会计科目", "发生额应申报收入说明"}
    missing = required_columns - set(frame.columns)
    if missing:
        raise HTTPException(status_code=400, detail=f"说明导入文件缺少列：{'、'.join(sorted(missing))}")
    rows = db.query(PitOccurrenceCheck).filter_by(workpaper_id=workpaper.id, company_id=current_company_id()).all()
    by_key = {(row.org_code, row.subject_code): row for row in rows}
    updated = 0
    unmatched = 0
    for record in frame.to_dict(orient="records"):
        description = _occurrence_import_key(record.get("发生额应申报收入说明"))
        if not description:
            continue
        row = by_key.get((_occurrence_import_key(record.get("机构代码")), _occurrence_import_key(record.get("会计科目"))))
        if row is None:
            unmatched += 1
            continue
        income_type = _occurrence_import_key(record.get("对应税种"))
        if income_type and income_type != row.income_type:
            unmatched += 1
            continue
        if row.expected_income_description != description:
            row.expected_income_description = description
            updated += 1
    if updated:
        if workpaper.workflow_status == "returned":
            workpaper.workflow_status = "pending_submission"
        workpaper.draft_revision += 1
        db.commit()
        db.refresh(workpaper)
    return {"updated_count": updated, "unmatched_count": unmatched, "draft_revision": workpaper.draft_revision, "workflow_status": workpaper.workflow_status}

def _patch(model,record_id:int,period_id:int,stage,values,db:Session,manual_field:str|None=None):
    workpaper = _workpaper(db, period_id,stage)
    _ensure_online_editable(db, workpaper)
    if workpaper.workflow_status in {"submitted", "reviewed"}:
        raise HTTPException(status_code=409, detail="当前底稿已锁定，不能修改")
    row=db.query(model).filter_by(id=record_id,company_id=current_company_id(),period_id=period_id,workpaper_id=workpaper.id).first()
    if row is None:raise HTTPException(status_code=404,detail="核对记录不存在")
    data=values.model_dump(exclude_none=True)
    if manual_field and "manual_reason" in data:setattr(row,manual_field,data.pop("manual_reason"))
    for field,value in data.items():setattr(row,field,value)
    if workpaper.workflow_status == "returned": workpaper.workflow_status = "pending_submission"
    if workpaper.calculation_status == "success": workpaper.workflow_status = "pending_submission"
    workpaper.draft_revision += 1
    db.commit();db.refresh(row);return _payload(row)
@router.patch("/tax-amount-checks/{record_id}")
def patch_tax(record_id:int,values:PitTaxAmountCheckUpdate,period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),db:Session=Depends(get_db)): return _patch(PitTaxAmountCheck,record_id,period_id,stage,values,db)
@router.patch("/occurrence-checks/{record_id}")
def patch_occurrence(record_id:int,values:PitOccurrenceCheckUpdate,period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),db:Session=Depends(get_db)): return _patch(PitOccurrenceCheck,record_id,period_id,stage,values,db)
@router.patch("/org-summaries/{record_id}")
def patch_summary(record_id:int,values:PitSummaryUpdate,period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),db:Session=Depends(get_db)): return _patch(PitReconciliationOrgSummary,record_id,period_id,stage,values,db)
@router.patch("/difference-details/{record_id}")
def patch_detail(record_id:int,values:PitManualUpdate,period_id:int=Query(...),stage:Literal["pre_payment","post_payment"]=Query(...),db:Session=Depends(get_db)): return _patch(PitReconciliationDifferenceDetail,record_id,period_id,stage,values,db,"manual_reason")
