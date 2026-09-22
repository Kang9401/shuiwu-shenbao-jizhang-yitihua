from __future__ import annotations

import webbrowser
import unicodedata
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import require_company
from app.core.company_context import current_company_id
from app.core.config import settings
from app.db.session import get_db
from app.integrations.fmss.client import FmssClient
from app.integrations.fmss.errors import FmssError, FmssPermissionDenied
from app.integrations.fmss.identity import FmssIdentityResolver
from app.integrations.fmss.session import fmss_session
from app.models.pit_reconciliation import PitReconciliationWorkpaper
from app.services.pit_online_service import PitOnlineService


router = APIRouter(prefix="/fmss", tags=["fmss"])


class SubmitPayload(BaseModel):
    period_id: int = Field(gt=0)
    reviewer: str = Field(min_length=1, max_length=120)
    stage: Literal["pre_payment", "post_payment"] = "pre_payment"


class DecisionPayload(BaseModel):
    id: str | None = None
    passed: bool
    comment: str = Field(default="", max_length=500)


def _fail(exc: FmssError) -> HTTPException:
    return HTTPException(status_code=401 if exc.__class__.__name__ == "FmssNotAuthenticated" else 409, detail=exc.user_message)


def _workpaper(db: Session, period_id: int, stage: Literal["pre_payment", "post_payment"]) -> PitReconciliationWorkpaper:
    row = db.query(PitReconciliationWorkpaper).filter_by(company_id=current_company_id(), period_id=period_id, tax_type="pit", stage=stage).first()
    if row is None:
        raise HTTPException(status_code=404, detail="当前所属期尚未生成个税核对底稿")
    return row


@router.get("/session")
def session_state(validate: bool = Query(False)):
    state = fmss_session.snapshot()
    if not state.connected:
        return {"connected": False, "environment": settings.fmss_environment, "username": None, "displayName": None}
    if validate:
        try:
            # A read-only sheet request validates the token. Identity lookup is
            # isolated and never falls back to submitter/reviewer fields.
            FmssClient().sheets("PRE")
            identity = FmssIdentityResolver().resolve(FmssClient())
            fmss_session.set_identity(identity.username, identity.display_name)
        except FmssError as exc:
            raise _fail(exc) from exc
        state = fmss_session.snapshot()
    return {
        "connected": True,
        "environment": settings.fmss_environment,
        "username": state.username,
        "displayName": state.display_name,
    }


@router.post("/logout")
def logout():
    fmss_session.clear()
    return {"cleared": True}


@router.post("/login/open")
def open_login():
    # Login is intentionally separated from PIT writes.  A desktop bridge must
    # inject the resulting token into the process-only FmssSession.
    webbrowser.open(settings.fmss_login_url)
    return {"opened": True}


@router.get("/iit/branches")
def branches():
    try:
        return FmssClient().branches()
    except FmssError as exc:
        raise _fail(exc) from exc


@router.get("/iit/sheets")
def sheets(stage: Literal["PRE", "POST"] = Query(...)):
    try:
        return FmssClient().sheets(stage)
    except FmssError as exc:
        raise _fail(exc) from exc


@router.get("/iit/declaration", dependencies=[Depends(require_company)])
def declaration(period_id: int = Query(...), stage: Literal["pre_payment", "post_payment"] = Query(...), db: Session = Depends(get_db)):
    try:
        return PitOnlineService(db).sync_workpaper(_workpaper(db, period_id, stage))
    except FmssError as exc:
        raise _fail(exc) from exc


@router.get("/iit/approval-log", dependencies=[Depends(require_company)])
def approval_log(period_id: int = Query(...), db: Session = Depends(get_db)):
    try:
        service = PitOnlineService(db)
        company, period = service._context(current_company_id(), period_id)
        return FmssClient().approval_log(company.fmss_branch_code, f"{period.year}-{period.month:02d}")
    except FmssError as exc:
        raise _fail(exc) from exc


@router.get("/iit/review/{declaration_id}", dependencies=[Depends(require_company)])
def review(declaration_id: str):
    try:
        return FmssClient().review(declaration_id)
    except FmssError as exc:
        raise _fail(exc) from exc


@router.get("/iit/reviewers", dependencies=[Depends(require_company)])
def reviewers(period_id: int = Query(...), stage: Literal["pre_payment"] = Query("pre_payment"), db: Session = Depends(get_db)):
    try:
        service = PitOnlineService(db)
        company, period = service._context(current_company_id(), period_id)
        return FmssClient().reviewers(company.fmss_branch_code, f"{period.year}-{period.month:02d}", "PRE")
    except FmssError as exc:
        raise _fail(exc) from exc


@router.post("/iit/submit", dependencies=[Depends(require_company)])
def submit(payload: SubmitPayload, db: Session = Depends(get_db)):
    try:
        workpaper = _workpaper(db, payload.period_id, payload.stage)
        return PitOnlineService(db).submit_workpaper(workpaper, payload.reviewer)
    except FmssError as exc:
        raise _fail(exc) from exc


@router.post("/iit/decision/{declaration_id}", dependencies=[Depends(require_company)])
def decision(declaration_id: str, payload: DecisionPayload, db: Session = Depends(get_db)):
    workpaper = db.query(PitReconciliationWorkpaper).filter_by(
        company_id=current_company_id(), platform_submission_id=declaration_id,
    ).first()
    if workpaper is None:
        raise HTTPException(status_code=404, detail="本地没有找到该FMSS申报单关联")
    try:
        current_user = fmss_session.snapshot().username
        if not current_user:
            raise FmssPermissionDenied()
        service = PitOnlineService(db)
        company, period = service._context(workpaper.company_id, workpaper.period_id)
        approval = FmssClient().approval_log(company.fmss_branch_code, f"{period.year}-{period.month:02d}")
        rows = approval.get("rows", []) if isinstance(approval, dict) else []
        normal = lambda value: unicodedata.normalize("NFC", str(value or "").strip())
        allowed = any(
            str(row.get("declarationId")) == declaration_id
            and row.get("approvalStatus") == "REVIEWING"
            and normal(row.get("reviewer")) == normal(current_user)
            for row in rows if isinstance(row, dict)
        )
        if not allowed:
            raise FmssPermissionDenied()
        return service.decide_workpaper(workpaper, payload.passed, payload.comment)
    except FmssError as exc:
        raise _fail(exc) from exc


@router.post("/iit/decision", dependencies=[Depends(require_company)])
def decision_body(payload: DecisionPayload, db: Session = Depends(get_db)):
    if not payload.id:
        raise HTTPException(status_code=422, detail="缺少FMSS申报单ID")
    return decision(payload.id, payload, db)


@router.get("/iit/config")
def iit_config(version: str = Query(default="")):
    try:
        return FmssClient().get_iit_config(version)
    except FmssError as exc:
        raise _fail(exc) from exc
