# backend/app/api/tax.py
"""个税申报 API 路由"""
from __future__ import annotations

import shutil
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.api.dependencies import require_company, require_period
from app.models.accounting import OrganizationMapping
from app.models.core import Period
from app.models.tax import TaxMonthlyArtifact, VerificationRound, VerificationSession
from app.schemas.tax import (
    ConfirmRequest,
    GenerateResponse,
    SessionCreate,
    SessionRead,
)
from app.services.generation import generate_declarations
from app.services.personnel_declaration import build_monthly_personnel_change_table
from app.services.personnel_master import (
    PersonnelMasterResolver,
    materialize_employee_id_updates,
    resolve_employee_history_path,
    save_generated_employee_master,
)
from app.services.salary_classifier import normalize_payroll_files
from app.services.personnel_review import (
    build_personnel_change_review_table,
    write_personnel_change_review_table,
)
from app.services.personnel_update import (
    PersonnelUpdateValidationError,
    apply_staff_info_update,
    build_personnel_collection_files,
)
from app.services.storage import save_upload
from app.core.company_context import current_company_id
from app.services.verification import (
    build_reconciliation_report,
    build_verification_checks,
    build_working_sheet,
    detect_employee_id_only_changes,
    check_no_blocking_issues,
    report_for_json,
    verify,
    write_reconciliation_report,
)

router = APIRouter(prefix="/tax", tags=["tax"], dependencies=[Depends(require_company)])
logger = logging.getLogger(__name__)

ARTIFACT_DIR = settings.artifact_dir


def tax_artifact_dir(session_id: int) -> Path:
    company_id = current_company_id(default=None)
    target = (
        ARTIFACT_DIR / str(company_id) / "tax" / str(session_id)
        if company_id is not None
        else ARTIFACT_DIR / str(session_id)
    )
    target.mkdir(parents=True, exist_ok=True)
    return target


def monthly_tax_artifact_dir(period_id: int) -> Path:
    company_id = current_company_id(default=None)
    target = (
        ARTIFACT_DIR / str(company_id) / "tax" / "monthly" / str(period_id)
        if company_id is not None
        else ARTIFACT_DIR / "monthly" / str(period_id)
    )
    target.mkdir(parents=True, exist_ok=True)
    return target

ARTIFACT_TYPE_WORKING_SHEET = "working_sheet"


def _taxpayer_org_mapping(db: Session) -> tuple[dict[str, str], set[str]]:
    grouped: dict[str, list[str]] = {}
    mappings = db.query(OrganizationMapping).filter(OrganizationMapping.active == 1).all()
    for item in mappings:
        taxpayer_id = "".join((item.taxpayer_id or "").split()).upper()
        if taxpayer_id:
            grouped.setdefault(taxpayer_id, []).append((item.org_code or "").strip())
    duplicates = {taxpayer_id for taxpayer_id, codes in grouped.items() if len(codes) != 1}
    return {
        taxpayer_id: codes[0]
        for taxpayer_id, codes in grouped.items()
        if taxpayer_id not in duplicates
    }, duplicates


def _period_working_sheet_name(period: Period | None) -> str:
    if period:
        return f"{period.year}年{period.month:02d}月_底稿.xlsx"
    return "底稿.xlsx"


def _get_monthly_artifact(db: Session, period_id: int, artifact_type: str) -> TaxMonthlyArtifact | None:
    return (
        db.query(TaxMonthlyArtifact)
        .filter(
            TaxMonthlyArtifact.period_id == period_id,
            TaxMonthlyArtifact.artifact_type == artifact_type,
        )
        .first()
    )


def _upsert_monthly_artifact(
    db: Session,
    *,
    period_id: int,
    artifact_type: str,
    file_name: str,
    source_path: Path,
    session_id: int,
    round_number: int,
    overwrite: bool = True,
) -> TaxMonthlyArtifact:
    monthly_dir = monthly_tax_artifact_dir(period_id)
    monthly_dir.mkdir(parents=True, exist_ok=True)
    dest = monthly_dir / file_name

    artifact = _get_monthly_artifact(db, period_id, artifact_type)
    if artifact is not None and not overwrite:
        return artifact

    shutil.copy2(source_path, dest)
    if artifact is None:
        artifact = TaxMonthlyArtifact(period_id=period_id, artifact_type=artifact_type)
        db.add(artifact)
    artifact.file_name = file_name
    artifact.stored_path = str(dest)
    artifact.source_session_id = session_id
    artifact.source_round_number = round_number
    return artifact


def _upsert_monthly_working_sheet(
    db: Session,
    *,
    period_id: int,
    period: Period | None,
    source_path: Path,
    session_id: int,
    round_number: int,
) -> TaxMonthlyArtifact:
    return _upsert_monthly_artifact(
        db,
        period_id=period_id,
        artifact_type=ARTIFACT_TYPE_WORKING_SHEET,
        file_name=_period_working_sheet_name(period),
        source_path=source_path,
        session_id=session_id,
        round_number=round_number,
        overwrite=True,
    )


def _resolve_previous_month_employee_master_path(db: Session, period: Period | None) -> str:
    if period is None:
        raise HTTPException(status_code=400, detail="所属期间不存在，无法读取人员主数据")

    previous_year = period.year if period.month > 1 else period.year - 1
    previous_month = period.month - 1 if period.month > 1 else 12
    previous_period = (
        db.query(Period)
        .filter(Period.year == previous_year, Period.month == previous_month)
        .first()
    )
    label = f"{previous_year}年{previous_month:02d}月"
    if previous_period is None:
        raise HTTPException(status_code=400, detail=f"未找到{label}所属期间，请先维护该月份的员工人员主数据")

    path = PersonnelMasterResolver(db, previous_period.id).resolve_path("employee")
    if path:
        return path
    raise HTTPException(status_code=400, detail=f"请先导入{label}的人员主数据（人员类型：员工）")


def _previous_period(db: Session, period: Period | None) -> Period | None:
    if period is None:
        return None
    previous_year = period.year if period.month > 1 else period.year - 1
    previous_month = period.month - 1 if period.month > 1 else 12
    return (
        db.query(Period)
        .filter(Period.year == previous_year, Period.month == previous_month)
        .first()
    )


def _build_monthly_personnel_declaration_changes(db: Session, period: Period | None) -> pd.DataFrame:
    """Compare consecutive complete employee masters for personnel declaration only."""
    if period is None:
        return pd.DataFrame()
    previous_period = _previous_period(db, period)
    if previous_period is None:
        return pd.DataFrame()
    previous_path = resolve_employee_history_path(db, previous_period.id)
    current_path = resolve_employee_history_path(db, period.id)
    if not previous_path or not current_path:
        return pd.DataFrame()
    return build_monthly_personnel_change_table(previous_path, current_path, period.year, period.month)


def _resolve_employee_master_for_verification(db: Session, period: Period | None) -> str:
    if period is None:
        raise HTTPException(status_code=400, detail="所属期间不存在，无法读取人员主数据")
    current_path = PersonnelMasterResolver(db, period.id).resolve_path("employee")
    return current_path or _resolve_previous_month_employee_master_path(db, period)


def _resolve_staff_path_for_verification(
    db: Session,
    period: Period | None,
    *,
    session_id: int,
    verification_stage: str,
    has_staff_change: bool,
) -> str:
    """Resolve the employee master according to the monthly verification stage."""
    if verification_stage not in {"initial", "recheck"}:
        raise HTTPException(status_code=400, detail="核对阶段不合法")

    previous_path = _resolve_previous_month_employee_master_path(db, period)
    if verification_stage == "initial" or has_staff_change:
        return previous_path

    if period is None:
        raise HTTPException(status_code=400, detail="所属期间不存在，无法读取人员主数据")
    current_path = PersonnelMasterResolver(db, period.id).resolve_path("employee")
    if current_path:
        return current_path

    # No personnel changes: materialize this month's master from last month for recheck.
    artifact = save_generated_employee_master(
        db,
        period_id=period.id,
        display_path=previous_path,
        full_history_path=previous_path,
        source_session_id=session_id,
    )
    return artifact.stored_path


def _merge_personnel_update_report(report: dict, personnel_update_report: dict | None) -> None:
    if not personnel_update_report:
        return
    report["personnel_update_issues"] = {
        "match_failures": personnel_update_report.get("match_failures", []),
        "duplicate_additions": personnel_update_report.get("duplicate_additions", []),
        "multiple_matches": personnel_update_report.get("multiple_matches", []),
    }
    report["headcount_reconciliation"] = personnel_update_report.get(
        "headcount_reconciliation", {"has_issues": False, "items": []}
    )
    report["report_sheets"] = build_reconciliation_report(report)


def _mark_personnel_update_blocking(report: dict, issues: list[dict]) -> None:
    report["key_field_missing"] = {"has_issues": bool(issues), "items": issues}
    report["summary"]["total_issues"] = int(report["summary"].get("total_issues", 0)) + len(issues)
    report["summary"]["blocking_issues"] = int(report["summary"].get("blocking_issues", 0)) + len(issues)
    report["summary"]["has_blocking_issues"] = report["summary"]["blocking_issues"] > 0
    report["checks"] = build_verification_checks(report)
    report["report_sheets"] = build_reconciliation_report(report)


def _remove_previous_session_results(
    db: Session,
    session_id: int,
    keep_round_id: int,
    keep_round_number: int,
) -> None:
    """Keep only the latest successful verification result for a session."""
    db.query(VerificationRound).filter(
        VerificationRound.session_id == session_id,
        VerificationRound.id != keep_round_id,
    ).delete(synchronize_session=False)

    session_dir = tax_artifact_dir(session_id)
    keep_dir = f"round_{keep_round_number}"
    if session_dir.exists():
        for artifact_dir in session_dir.glob("round_*"):
            if artifact_dir.is_dir() and artifact_dir.name != keep_dir:
                shutil.rmtree(artifact_dir)

    output_dir = session_dir / "output"
    if output_dir.exists():
        shutil.rmtree(output_dir)


@router.post("/sessions", response_model=SessionRead)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    require_period(db, payload.period_id)
    existing = (
        db.query(VerificationSession)
        .filter(VerificationSession.period_id == payload.period_id)
        .first()
    )
    if existing:
        return existing
    s = VerificationSession(period_id=payload.period_id)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/sessions", response_model=list[SessionRead])
def list_sessions(period_id: int = Query(None), db: Session = Depends(get_db)):
    q = db.query(VerificationSession)
    if period_id is not None:
        q = q.filter(VerificationSession.period_id == period_id)
    return q.all()


@router.get("/sessions/{session_id}", response_model=SessionRead)
def get_session(session_id: int, db: Session = Depends(get_db)):
    s = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    return s


@router.get("/sessions/{session_id}/latest-result")
def get_latest_result(session_id: int, db: Session = Depends(get_db)) -> dict:
    session = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    latest_round = (
        db.query(VerificationRound)
        .filter(VerificationRound.session_id == session_id)
        .order_by(VerificationRound.round_number.desc())
        .first()
    )
    if latest_round is None or not latest_round.report_data:
        return {"status": session.status, "round_number": None, "report": None, "artifacts": [], "generated_files": []}

    round_dir = tax_artifact_dir(session_id) / f"round_{latest_round.round_number}"
    artifacts: list[dict] = []
    change_review = round_dir / "人员信息变动表-雇员.xlsx"
    if change_review.exists():
        artifacts.append({
            "name": change_review.name,
            "download_url": f"/api/tax/round-files/{session_id}/{latest_round.round_number}/{change_review.name}",
            "file_type": "personnel_change_review",
        })
    report_path = round_dir / "总体核对报告.xlsx"
    if not report_path.exists():
        report_path = round_dir / "核对报告.xlsx"
    if report_path.exists():
        artifacts.append({
            "name": report_path.name,
            "download_url": f"/api/tax/round-files/{session_id}/{latest_round.round_number}/{report_path.name}",
            "file_type": "reconciliation_report",
        })

    output_dir = tax_artifact_dir(session_id) / "output"
    generated_files = []
    if session.status == "done" and output_dir.exists():
        for path in sorted(output_dir.glob("*.xls")):
            file_type = "declaration" if "_3-" in path.name else "personnel_collection"
            if file_type == "declaration" or "_1-人员信息采集_员工" in path.name:
                generated_files.append({
                    "name": path.name,
                    "download_url": f"/api/tax/files/{session_id}/{path.name}",
                    "file_type": file_type,
                })
    return {
        "status": session.status,
        "round_number": latest_round.round_number,
        "report": latest_round.report_data,
        "artifacts": artifacts,
        "generated_files": generated_files,
    }


@router.post("/sessions/{session_id}/verify")
async def run_verify(
    session_id: int,
    rank_salary: UploadFile = File(...),
    marketing_salary: UploadFile = File(...),
    branch_salary: Optional[UploadFile] = File(None),
    headquarters_salary: Optional[UploadFile] = File(None),
    digital_ops_salary: Optional[UploadFile] = File(None),
    advisor_salary: Optional[UploadFile] = File(None),
    staff_change: Optional[UploadFile] = File(None),
    deduction_files: list[UploadFile] = File(default_factory=list),
    verification_stage: str = Form("initial"),
    db: Session = Depends(get_db),
):
    session = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    session.status = "verifying"
    db.commit()

    round_num = session.current_round
    uploaded: list[dict] = []
    payroll_files: list[tuple[str, str]] = []

    for role, upload in [
        ("rank_salary", rank_salary),
        ("marketing_salary", marketing_salary),
        ("branch_salary", branch_salary),
        ("headquarters_salary", headquarters_salary),
        ("digital_ops_salary", digital_ops_salary),
        ("advisor_salary", advisor_salary),
    ]:
        if upload:
            path, _ = save_upload(upload, session.period_id, role)
            uploaded.append({"file_role": role, "original_name": upload.filename, "stored_path": str(path)})
            payroll_files.append((role, str(path)))
    try:
        payroll_files = normalize_payroll_files(payroll_files)
    except ValueError as exc:
        session.status = "needs_review"
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    period = db.query(Period).filter(Period.id == session.period_id).first()
    year, month = period.year if period else 2025, period.month if period else 1

    staff_path = _resolve_staff_path_for_verification(
        db,
        period,
        session_id=session_id,
        verification_stage=verification_stage,
        has_staff_change=staff_change is not None,
    )

    # 专项附加扣除保存到同一个文件夹
    deduction_dir = ""
    if deduction_files:
        dedup_dir = settings.upload_dir / str(session.period_id) / "deductions"
        dedup_dir.mkdir(parents=True, exist_ok=True)
        for existing in dedup_dir.iterdir():
            if existing.is_file() and existing.suffix.lower() in {".xls", ".xlsx"}:
                existing.unlink()
        for df in deduction_files:
            safe_name = Path(df.filename or "deduction.xlsx").name
            dest = dedup_dir / safe_name
            with dest.open("wb") as out:
                while chunk := df.file.read(1024 * 1024):
                    out.write(chunk)
        deduction_dir = str(dedup_dir)

    artifact_path = tax_artifact_dir(session_id) / f"round_{round_num}"
    personnel_update_dir = artifact_path / "personnel_update"
    personnel_update_report = None
    personnel_update_result = None
    change_df = None
    source_staff_path = staff_path

    if staff_change:
        path, _ = save_upload(staff_change, session.period_id, "staff_change")
        uploaded.append({"file_role": "staff_change", "original_name": staff_change.filename, "stored_path": str(path)})
        try:
            change_df = pd.read_excel(path, dtype=str).fillna("")
        except Exception:
            change_df = None
        if change_df is None:
            raise HTTPException(status_code=400, detail="人员信息变动表无法读取")
        try:
            update_result = apply_staff_info_update(
                staff_info_path=staff_path,
                change_table_path=str(path),
                output_dir=str(personnel_update_dir),
                year=year,
                month=month,
            )
        except PersonnelUpdateValidationError as exc:
            session.status = "needs_review"
            db.commit()
            raise HTTPException(status_code=400, detail={
                "message": str(exc),
                "issues": exc.issues,
            }) from exc
        except ValueError as exc:
            session.status = "needs_review"
            db.commit()
            raise HTTPException(status_code=400, detail={
                "message": str(exc),
                "issues": [{"issue_type": "personnel_update_error", "message": str(exc)}],
            }) from exc
        except Exception as exc:
            session.status = "needs_review"
            db.commit()
            raise HTTPException(status_code=400, detail=f"人员信息变动表处理失败：{exc}") from exc
        personnel_update_report = update_result.get("report")
        personnel_update_result = update_result
        save_generated_employee_master(
            db,
            period_id=session.period_id,
            display_path=update_result["updated_staff_path"],
            full_history_path=update_result["full_staff_path"],
            source_session_id=session_id,
        )

    try:
        # 构建底稿 + 核对
        taxpayer_org_map, duplicate_taxpayer_ids = _taxpayer_org_mapping(db)
        effective_staff_path = (personnel_update_result or {}).get("updated_staff_path", source_staff_path)
        review_sheet, review_staff_df = build_working_sheet(
            payroll_files, effective_staff_path, deduction_dir, taxpayer_org_map, duplicate_taxpayer_ids
        )
        employee_id_changes = detect_employee_id_only_changes(review_sheet, review_staff_df)
        if employee_id_changes:
            update_dir = artifact_path / "employee_id_updates"
            update_source_path = (personnel_update_result or {}).get("full_staff_path", effective_staff_path)
            update_result = materialize_employee_id_updates(
                update_source_path, employee_id_changes, update_dir, year, month
            )
            save_generated_employee_master(
                db,
                period_id=session.period_id,
                display_path=update_result["updated_staff_path"],
                full_history_path=update_result["full_staff_path"],
                source_session_id=session_id,
            )
            effective_staff_path = update_result["updated_staff_path"]
        sheet, staff_df = (
            build_working_sheet(
                payroll_files, effective_staff_path, deduction_dir,
                taxpayer_org_map, duplicate_taxpayer_ids,
            )
            if employee_id_changes
            else (review_sheet, review_staff_df)
        )
        report = verify(
            sheet, deduction_dir, session.confirmed_personnel or [],
            staff_df=staff_df,
            change_df=change_df,
            year=year,
            month=month,
        )
        _merge_personnel_update_report(report, personnel_update_report)
        report["employee_id_changes"] = {
            "has_issues": bool(employee_id_changes),
            "items": employee_id_changes,
        }
        monthly_personnel_changes = _build_monthly_personnel_declaration_changes(db, period)
        report["monthly_personnel_changes"] = monthly_personnel_changes.to_dict(orient="records")

        # 保存轮次
        stored_report = report_for_json(report)
        round_obj = VerificationRound(
            session_id=session_id,
            round_number=round_num,
            uploaded_files=uploaded,
            report_data=stored_report,
            status="done",
        )
        db.add(round_obj)

        # 保存底稿
        artifact_path.mkdir(parents=True, exist_ok=True)
        working_sheet_path = artifact_path / "底稿.xlsx"
        sheet.to_excel(str(working_sheet_path), index=False)
        monthly_artifact = _upsert_monthly_working_sheet(
            db,
            period_id=session.period_id,
            period=period,
            source_path=working_sheet_path,
            session_id=session_id,
            round_number=round_num,
        )
        artifacts = [
            {
                "name": "底稿.xlsx",
                "download_url": f"/api/tax/round-files/{session_id}/{round_num}/底稿.xlsx",
                "file_type": "working_sheet",
            },
            {
                "name": monthly_artifact.file_name,
                "download_url": f"/api/tax/monthly-artifacts/{session.period_id}/working-sheet/download",
                "file_type": "monthly_working_sheet",
            }
        ]
        change_review = build_personnel_change_review_table(report, year, month)
        report["personnel_change_review"] = change_review.to_dict(orient="records")
        if not change_review.empty:
            change_review_path = artifact_path / "人员信息变动表-雇员.xlsx"
            write_personnel_change_review_table(change_review, change_review_path)
            artifacts.append({
                "name": change_review_path.name,
                "download_url": f"/api/tax/round-files/{session_id}/{round_num}/{change_review_path.name}",
                "file_type": "personnel_change_review",
            })
        if personnel_update_result:
            updated_staff_path = Path(personnel_update_result["updated_staff_path"])
            artifacts.append({
                "name": updated_staff_path.name,
                "download_url": f"/api/tax/round-files/{session_id}/{round_num}/personnel_update/{updated_staff_path.name}",
                "file_type": "updated_staff",
            })
            for collection_file in personnel_update_result.get("collection_files", []):
                collection_path = Path(collection_file)
                artifacts.append({
                    "name": collection_path.name,
                    "download_url": f"/api/tax/round-files/{session_id}/{round_num}/personnel_update/税务申报/{collection_path.name}",
                    "file_type": "personnel_collection",
                })

        report_path = artifact_path / "总体核对报告.xlsx"
        write_reconciliation_report(report, report_path)
        artifacts.append({
            "name": report_path.name,
            "download_url": f"/api/tax/round-files/{session_id}/{round_num}/{report_path.name}",
            "file_type": "reconciliation_report",
        })
        stored_report = report_for_json(report)
        round_obj.report_data = stored_report
        db.flush()
        _remove_previous_session_results(db, session_id, round_obj.id, round_num)

        if check_no_blocking_issues(report):
            session.status = "ready_to_generate"
        else:
            session.status = "needs_review"
        # Confirmations belong to the current run only and must never carry into a later export.
        session.confirmed_personnel = []
        # 关键：本轮已落库为 round_num，session.current_round 递增为下一轮做准备
        # 避免下一轮核对用相同 round_number 覆盖本轮底稿与数据库记录
        session.current_round = round_num + 1
        db.commit()

        return {
            "session_id": session_id,
            "round_number": round_num,
            "status": session.status,
            "report": stored_report,
            "artifacts": artifacts,
        }
    except Exception as exc:
        logger.exception("工资薪金核对失败")
        db.rollback()
        fresh_session = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
        if fresh_session:
            fresh_session.status = "needs_review"
            db.commit()
        raise HTTPException(status_code=400, detail=f"核对失败：{exc}") from exc


@router.post("/sessions/{session_id}/confirm")
def confirm_personnel(
    session_id: int,
    payload: ConfirmRequest,
    db: Session = Depends(get_db),
):
    session = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    confirmed = list(session.confirmed_personnel or [])
    for item in payload.confirmed_changes:
        if item.missing_fields:
            raise HTTPException(
                status_code=400,
                detail=f"{item.name} 存在信息缺失：{'、'.join(item.missing_fields)}，请先补齐并导入人员信息变动表-雇员后再确认",
            )
        if not item.id_number and not item.is_transfer_like:
            raise HTTPException(
                status_code=400,
                detail=f"{item.name} 缺少证件号码，请先补齐并导入人员信息变动表-雇员后再确认",
            )
        if item.confirmed:
            record = {
                "name": item.name,
                "id_number": item.id_number,
                "change_type": item.change_type,
                "cert_type": item.cert_type,
                "org_code_from": item.org_code_from,
                "org_code_to": item.org_code_to,
                "employee_id": item.employee_id,
                "phone": item.phone,
                "hire_date": item.hire_date,
                "leave_date": item.leave_date,
                "is_transfer_like": item.is_transfer_like,
                "confirmed": True,
                "applied": False,
            }
            key = (
                record["change_type"], record["name"], record["id_number"],
                record["org_code_from"], record["org_code_to"],
            )
            confirmed = [
                existing for existing in confirmed
                if (
                    existing.get("change_type", ""), existing.get("name", ""), existing.get("id_number", ""),
                    existing.get("org_code_from", ""), existing.get("org_code_to", ""),
                ) != key
            ]
            confirmed.append(record)
    session.confirmed_personnel = confirmed
    db.commit()
    return {"confirmed_count": len(confirmed)}


@router.post("/sessions/{session_id}/generate", response_model=GenerateResponse)
def generate(session_id: int, db: Session = Depends(get_db)):
    session = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.status != "ready_to_generate":
        raise HTTPException(status_code=400, detail="还有未解决的核对问题")

    session.status = "generating"
    db.commit()

    output_dir = tax_artifact_dir(session_id) / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 读取最新底稿
    last_round = (
        db.query(VerificationRound)
        .filter(VerificationRound.session_id == session_id)
        .order_by(VerificationRound.round_number.desc())
        .first()
    )
    sheet_path = tax_artifact_dir(session_id) / f"round_{last_round.round_number}" / "底稿.xlsx"
    sheet = pd.read_excel(sheet_path)

    period = db.query(Period).filter(Period.id == session.period_id).first()
    year, month = period.year if period else 2025, period.month if period else 1

    # 使用本月已确认的员工人员主数据；首次核对时自动回退到上月主数据。
    staff_df = None
    try:
        staff_info_path = _resolve_employee_master_for_verification(db, period)
        staff_df = pd.read_excel(staff_info_path, dtype=str)
        if "人员状态" in staff_df.columns:
            status = staff_df["人员状态"].fillna("").astype(str).str.strip()
            staff_df = staff_df[status.isin(["", "正常", "在职"])].copy()
    except Exception:
        staff_df = None

    decl_files = generate_declarations(sheet, str(output_dir), year, month, staff_df=staff_df)
    for old_collection in output_dir.glob("*_1-人员信息采集_员工(*.xls"):
        old_collection.unlink()
    saved_changes = (last_round.report_data or {}).get("monthly_personnel_changes")
    if saved_changes is None:
        monthly_changes = _build_monthly_personnel_declaration_changes(db, period)
        last_round.report_data = {
            **(last_round.report_data or {}),
            "monthly_personnel_changes": monthly_changes.to_dict(orient="records"),
        }
    else:
        monthly_changes = pd.DataFrame(saved_changes)
    collection_files = build_personnel_collection_files(monthly_changes, output_dir, year, month)

    all_files = []
    for fp in decl_files:
        name = Path(fp).name
        if "_3-" in name:
            all_files.append({"name": name, "download_url": f"/api/tax/files/{session_id}/{name}", "file_type": "declaration"})
    for fp in collection_files:
        name = Path(fp).name
        all_files.append({"name": name, "download_url": f"/api/tax/files/{session_id}/{name}", "file_type": "personnel_collection"})
    session.status = "done"
    db.commit()
    return GenerateResponse(status="done", files=all_files)


@router.get("/files/{session_id}/{file_name}")
def download_file(session_id: int, file_name: str):
    fp = tax_artifact_dir(session_id) / "output" / file_name
    if not fp.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(fp, filename=file_name)


@router.delete("/sessions/{session_id}/generated-files")
def clear_generated_files(session_id: int, db: Session = Depends(get_db)):
    session = db.query(VerificationSession).filter(VerificationSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.status == "generating":
        raise HTTPException(status_code=409, detail="申报表生成中，不能清空")
    output_dir = tax_artifact_dir(session_id) / "output"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    latest = (
        db.query(VerificationRound)
        .filter(VerificationRound.session_id == session_id)
        .order_by(VerificationRound.round_number.desc())
        .first()
    )
    report = latest.report_data if latest else {}
    session.status = "needs_review" if report.get("summary", {}).get("has_blocking_issues") else "ready_to_generate"
    db.commit()
    return {"status": session.status, "files": []}


@router.get("/sessions/{session_id}/download-all")
def download_all(session_id: int):
    """打包全部申报文件为 zip，让浏览器弹出"另存为"对话框供用户选择保存路径。"""
    import io
    import zipfile
    from urllib.parse import quote

    output_dir = tax_artifact_dir(session_id) / "output"
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="无可下载的文件")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in sorted(output_dir.rglob("*")):
            if fp.is_file() and fp.suffix.lower() == ".xls" and (
                "_3-" in fp.name or "_1-人员信息采集_员工" in fp.name
            ):
                zf.write(fp, f"申报文件/{fp.name}")
    content = buf.getvalue()

    filename = f"申报文件_session{session_id}.zip"
    # Content-Disposition 需要 URL 编码处理中文文件名
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.get("/monthly-artifacts/{period_id}/working-sheet/download")
def download_monthly_working_sheet(period_id: int, db: Session = Depends(get_db)):
    artifact = (
        db.query(TaxMonthlyArtifact)
        .filter(
            TaxMonthlyArtifact.period_id == period_id,
            TaxMonthlyArtifact.artifact_type == ARTIFACT_TYPE_WORKING_SHEET,
        )
        .first()
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="该月份尚未保存底稿")
    fp = Path(artifact.stored_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="底稿文件不存在")
    return FileResponse(fp, filename=artifact.file_name)


@router.get("/round-files/{session_id}/{round_number}/{file_path:path}")
def download_round_file(session_id: int, round_number: int, file_path: str):
    requested = Path(file_path)
    if requested.is_absolute() or ".." in requested.parts:
        raise HTTPException(status_code=400, detail="文件名不合法")
    fp = tax_artifact_dir(session_id) / f"round_{round_number}" / requested
    if not fp.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(fp, filename=requested.name)
