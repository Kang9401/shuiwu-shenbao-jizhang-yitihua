"""Database-first storage for normalized payroll rows and monthly workpapers.

The existing Excel readers remain the only place that understands workbook
headers. This module stores their normalized output and reconstructs the same
DataFrame shape for later calculations, so business formulas stay unchanged.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from sqlalchemy.orm import Session

from app.core.company_context import current_company_id
from app.models.payroll import (
    PayrollCalculationResult,
    PayrollEmployeeRecord,
    PayrollImportBatch,
    PayrollWorkpaper,
)
from app.services.verification import (
    PAYROLL_ROLE_LABELS,
    _clean_text,
    _normalize_emp_id,
    load_employee_payroll,
    load_headquarters_payroll,
)


def _safe_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return _safe_value(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _safe_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _safe_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _company_id(period: Any) -> int:
    value = getattr(period, "company_id", None) or current_company_id(default=None)
    if value is None:
        raise ValueError("工资数据缺少所属公司")
    return int(value)


def _employee_id(value: Any) -> str:
    """Normalize one scalar employee number (the legacy helper accepts Series)."""
    text = _clean_text(value)
    return text[:-2] if text.endswith(".0") else text


def _source_digest(path: str) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except (OSError, ValueError):
        return ""


def _frame_org_code(row: dict[str, Any]) -> str:
    return _clean_text(row.get("机构代码_工资单") or row.get("机构代码") or "")


def _identity_from_staff(staff_path: str | None) -> dict[tuple[str, str], dict[str, str]]:
    if not staff_path or not Path(staff_path).exists():
        return {}
    try:
        staff = pd.read_excel(staff_path, dtype=str).fillna("")
    except Exception:
        return {}
    for column in ("员工编号", "*姓名", "证件类型", "证件号码", "机构代码"):
        if column not in staff.columns:
            staff[column] = ""
    result: dict[tuple[str, str], dict[str, str]] = {}
    for _, row in staff.iterrows():
        key = (_employee_id(row.get("员工编号", "")), _clean_text(row.get("*姓名", "")))
        if not key[0] or not key[1]:
            continue
        result.setdefault(key, {
            "证件类型": _clean_text(row.get("证件类型", "")),
            "证件号码": _clean_text(row.get("证件号码", "")),
            "机构代码": _clean_text(row.get("机构代码", "")),
        })
    return result


def normalized_payroll_frames(
    payroll_files: list[tuple[str, str]],
    taxpayer_org_map: dict[str, str] | None = None,
    duplicate_taxpayer_ids: set[str] | None = None,
) -> list[tuple[str, pd.DataFrame]]:
    """Read uploaded files once through the existing header/role readers."""
    frames: list[tuple[str, pd.DataFrame]] = []
    for role, path in payroll_files:
        if not path:
            continue
        if role == "headquarters_salary":
            frame = load_headquarters_payroll(path, taxpayer_org_map, duplicate_taxpayer_ids)
        else:
            frame = load_employee_payroll(
                path,
                taxpayer_org_map,
                duplicate_taxpayer_ids,
                payroll_role=role,
            )
        if not frame.empty:
            frame = frame.copy()
            frame["工资单类型"] = role
            frames.append((role, frame.reset_index(drop=True)))
    return frames


def _delete_current_rows(
    db: Session,
    *,
    company_id: int,
    period_id: int,
    salary_type: str,
    org_codes: Iterable[str],
) -> None:
    codes = list(dict.fromkeys(org_codes))
    if not codes:
        return
    batches = db.query(PayrollImportBatch).filter(
        PayrollImportBatch.company_id == company_id,
        PayrollImportBatch.period_id == period_id,
        PayrollImportBatch.salary_type == salary_type,
        PayrollImportBatch.org_code.in_(codes),
    ).all()
    batch_ids = [batch.id for batch in batches]
    if batch_ids:
        db.query(PayrollEmployeeRecord).filter(
            PayrollEmployeeRecord.import_batch_id.in_(batch_ids)
        ).delete(synchronize_session=False)
    for batch in batches:
        db.delete(batch)
    db.query(PayrollCalculationResult).filter(
        PayrollCalculationResult.company_id == company_id,
        PayrollCalculationResult.period_id == period_id,
        PayrollCalculationResult.salary_type == salary_type,
        PayrollCalculationResult.org_code.in_(codes),
    ).delete(synchronize_session=False)


def replace_payroll_imports(
    db: Session,
    *,
    period: Any,
    payroll_files: list[tuple[str, str]],
    taxpayer_org_map: dict[str, str] | None = None,
    duplicate_taxpayer_ids: set[str] | None = None,
    staff_info_path: str | None = None,
) -> dict[str, Any]:
    """Atomically replace current rows for every imported role/org.

    All Excel parsing happens before any existing rows are deleted. Callers can
    put this function in a SQLAlchemy nested transaction so a later calculation
    failure restores the previous valid import.
    """
    company_id = _company_id(period)
    period_id = int(period.id)
    frames = normalized_payroll_frames(payroll_files, taxpayer_org_map, duplicate_taxpayer_ids)
    identity = _identity_from_staff(staff_info_path)
    prepared: list[dict[str, Any]] = []
    for role, frame in frames:
        source_path = next((path for candidate, path in payroll_files if candidate == role), "")
        source_name = Path(source_path).name if source_path else ""
        digest = _source_digest(source_path) if source_path else ""
        rows = _safe_records(frame)
        grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for source_row_number, row in enumerate(rows):
            org_code = _frame_org_code(row)
            grouped.setdefault(org_code, []).append((source_row_number, row))
        for org_code, group in grouped.items():
            prepared.append({
                "role": role,
                "org_code": org_code,
                "source_name": source_name,
                "source_path": source_path,
                "digest": digest,
                "rows": group,
            })

    if prepared:
        # Any successful source replacement invalidates the previous
        # calculation/workpaper.  The caller's transaction restores these
        # rows automatically if later verification fails.
        db.query(PayrollCalculationResult).filter(
            PayrollCalculationResult.company_id == company_id,
            PayrollCalculationResult.period_id == period_id,
        ).delete(synchronize_session=False)
        db.query(PayrollWorkpaper).filter(
            PayrollWorkpaper.company_id == company_id,
            PayrollWorkpaper.period_id == period_id,
        ).update({PayrollWorkpaper.status: "invalidated"}, synchronize_session=False)

    for item in prepared:
        role = item["role"]
        org_code = item["org_code"]
        _delete_current_rows(
            db,
            company_id=company_id,
            period_id=period_id,
            salary_type=role,
            org_codes=[org_code],
        )
        batch = PayrollImportBatch(
            company_id=company_id,
            period_id=period_id,
            salary_type=role,
            org_code=org_code,
            source_file_name=item["source_name"],
            source_path=item["source_path"],
            source_sha256=item["digest"],
            row_count=len(item["rows"]),
            status="valid",
        )
        db.add(batch)
        db.flush()
        for source_row_number, row in item["rows"]:
            employee_no = _employee_id(row.get("员工编号", ""))
            person_name = _clean_text(row.get("*姓名", ""))
            profile = identity.get((employee_no, person_name), {})
            row.setdefault("证件类型", profile.get("证件类型", ""))
            row.setdefault("证件号码", profile.get("证件号码", ""))
            row.setdefault("机构代码_人员信息表", profile.get("机构代码", ""))
            db.add(PayrollEmployeeRecord(
                company_id=company_id,
                period_id=period_id,
                import_batch_id=batch.id,
                salary_type=role,
                org_code=org_code,
                source_row_number=source_row_number,
                employee_no=employee_no,
                person_name=person_name,
                id_type=_clean_text(row.get("证件类型", "")),
                id_number=_clean_text(row.get("证件号码", "")),
                salary_scheme=_clean_text(row.get("工资单类型", "")),
                data_json=row,
            ))
    return {
        "company_id": company_id,
        "period_id": period_id,
        "batch_count": len(prepared),
        "row_count": sum(len(item["rows"]) for item in prepared),
        "roles": sorted({item["role"] for item in prepared}),
    }


def load_payroll_frames_from_db(
    db: Session,
    *,
    company_id: int,
    period_id: int,
    roles: set[str] | None = None,
) -> list[tuple[str, pd.DataFrame]]:
    query = db.query(PayrollEmployeeRecord).filter(
        PayrollEmployeeRecord.company_id == company_id,
        PayrollEmployeeRecord.period_id == period_id,
    ).order_by(PayrollEmployeeRecord.salary_type, PayrollEmployeeRecord.source_row_number)
    if roles:
        query = query.filter(PayrollEmployeeRecord.salary_type.in_(roles))
    records = query.all()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        row = dict(record.data_json or {})
        row.setdefault("员工编号", record.employee_no)
        row.setdefault("*姓名", record.person_name)
        row.setdefault("证件类型", record.id_type)
        row.setdefault("证件号码", record.id_number)
        row.setdefault("机构代码", record.org_code)
        row["工资单类型"] = PAYROLL_ROLE_LABELS.get(record.salary_type, record.salary_type)
        grouped.setdefault(record.salary_type, []).append(row)
    return [(role, pd.DataFrame(rows)) for role, rows in grouped.items()]


def save_payroll_workpaper(
    db: Session,
    *,
    period: Any,
    sheet: pd.DataFrame,
    report: dict[str, Any] | None,
    input_sha256: str = "",
) -> PayrollWorkpaper:
    company_id = _company_id(period)
    period_id = int(period.id)
    if not input_sha256:
        source_digests = [
            batch.source_sha256
            for batch in db.query(PayrollImportBatch).filter(
                PayrollImportBatch.company_id == company_id,
                PayrollImportBatch.period_id == period_id,
                PayrollImportBatch.status == "valid",
            ).order_by(PayrollImportBatch.id).all()
            if batch.source_sha256
        ]
        input_sha256 = hashlib.sha256("|".join(source_digests).encode("utf-8")).hexdigest()
    db.query(PayrollCalculationResult).filter(
        PayrollCalculationResult.company_id == company_id,
        PayrollCalculationResult.period_id == period_id,
    ).delete(synchronize_session=False)
    for row_number, row in enumerate(_safe_records(sheet)):
        role = _clean_text(row.get("工资单类型", "")) or "combined"
        org_code = _clean_text(row.get("机构代码_工资单") or row.get("机构代码") or "")
        db.add(PayrollCalculationResult(
            company_id=company_id,
            period_id=period_id,
            salary_type=role,
            org_code=org_code,
            source_row_number=row_number,
            employee_no=_employee_id(row.get("员工编号", "")),
            person_name=_clean_text(row.get("*姓名", "")),
            input_sha256=input_sha256,
            status="valid",
            result_json=row,
        ))
    workpaper = db.query(PayrollWorkpaper).filter(
        PayrollWorkpaper.company_id == company_id,
        PayrollWorkpaper.period_id == period_id,
    ).first()
    if workpaper is None:
        workpaper = PayrollWorkpaper(company_id=company_id, period_id=period_id)
        db.add(workpaper)
    workpaper.input_sha256 = input_sha256
    workpaper.status = "valid"
    workpaper.sheet_rows_json = _safe_records(sheet)
    workpaper.report_json = _safe_value(report) if report is not None else None
    workpaper.manual_json = {
        "confirmed_personnel": (report or {}).get("confirmed_personnel", []),
        "monthly_personnel_changes": (report or {}).get("monthly_personnel_changes", []),
    }
    db.flush()
    return workpaper


def invalidate_payroll_workpaper(db: Session, *, company_id: int, period_id: int) -> None:
    workpaper = db.query(PayrollWorkpaper).filter(
        PayrollWorkpaper.company_id == company_id,
        PayrollWorkpaper.period_id == period_id,
    ).first()
    if workpaper is not None:
        workpaper.status = "invalidated"
    db.query(PayrollCalculationResult).filter(
        PayrollCalculationResult.company_id == company_id,
        PayrollCalculationResult.period_id == period_id,
    ).delete(synchronize_session=False)


def workpaper_frame(workpaper: PayrollWorkpaper | None) -> pd.DataFrame:
    if workpaper is None or workpaper.status != "valid":
        return pd.DataFrame()
    rows = workpaper.sheet_rows_json or []
    return pd.DataFrame(rows) if rows else pd.DataFrame()
