"""Database-first storage for non-payroll income workflows.

The existing Excel readers remain responsible for template/header handling.
This module only stores their source-shaped rows and the latest calculation
snapshot, allowing later runs and exports to use SQLite without requiring an
old workbook to remain on disk.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from sqlalchemy.orm import Session

from app.core.company_context import current_company_id
from app.models.income import IncomeImportBatch, IncomeRecord, IncomeWorkpaper


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return _safe(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(k): _safe(v) for k, v in row.items()} for row in frame.to_dict(orient="records")]


def _company_id(period: Any) -> int:
    value = getattr(period, "company_id", None) or current_company_id(default=None)
    if value is None:
        raise ValueError("收入数据缺少所属公司")
    return int(value)


def _digest(path: str | None) -> str:
    if not path:
        return ""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except (OSError, ValueError):
        return ""


def _org_code(row: dict[str, Any]) -> str:
    for key in ("机构代码", "分支机构代码", "归属机构代码", "机构编号", "公司段", "单位编号"):
        value = _clean(row.get(key))
        if value:
            return value
    return ""


def _person_name(row: dict[str, Any]) -> str:
    for key in ("*姓名", "姓名", "客户姓名", "员工姓名", "经纪人姓名"):
        value = _clean(row.get(key))
        if value:
            return value
    return ""


def _id_number(row: dict[str, Any]) -> str:
    for key in ("*证件号码", "证件号码", "证件号码（同名必填）", "证件号码(同名必填)", "身份证号码"):
        value = _clean(row.get(key))
        if value:
            return value
    return ""


def _employee_no(row: dict[str, Any]) -> str:
    for key in ("员工编号", "工号", "人员编号", "员工编码"):
        value = _clean(row.get(key))
        if value:
            return value[:-2] if value.endswith(".0") else value
    return ""


def replace_income_sources(
    db: Session,
    *,
    period: Any,
    workflow_code: str,
    frames: dict[str, pd.DataFrame],
    source_paths: dict[str, str] | None = None,
    source_roles: Iterable[str] | None = None,
) -> dict[str, int]:
    """Atomically replace the supplied source roles for one workflow/period.

    Rows are prepared before the savepoint deletes old batches.  A failed
    insert therefore leaves the previous valid source untouched.
    """
    company_id = _company_id(period)
    period_id = int(period.id)
    roles = list(source_roles or frames.keys())
    prepared = []
    for role in roles:
        frame = frames.get(role)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        rows = _records(frame.reset_index(drop=True))
        grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for row_number, row in enumerate(rows):
            grouped.setdefault(_org_code(row), []).append((row_number, row))
        path = (source_paths or {}).get(role, "")
        for org_code, group in grouped.items():
            prepared.append((role, org_code, path, group))
    if not prepared:
        return {"batch_count": 0, "row_count": 0}

    with db.begin_nested():
        for role in {item[0] for item in prepared}:
            old = db.query(IncomeImportBatch).filter(
                IncomeImportBatch.company_id == company_id,
                IncomeImportBatch.period_id == period_id,
                IncomeImportBatch.workflow_code == workflow_code,
                IncomeImportBatch.source_role == role,
            ).all()
            old_ids = [item.id for item in old]
            for item in old:
                db.expunge(item)
            if old_ids:
                db.query(IncomeRecord).filter(IncomeRecord.batch_id.in_(old_ids)).delete(synchronize_session=False)
            db.query(IncomeImportBatch).filter(IncomeImportBatch.id.in_(old_ids)).delete(synchronize_session=False)
        db.flush()
        for role, org_code, path, group in prepared:
            batch = IncomeImportBatch(
                company_id=company_id, period_id=period_id, workflow_code=workflow_code,
                source_role=role, org_code=org_code, source_file_name=Path(path).name if path else "",
                source_path=path or "", source_sha256=_digest(path), row_count=len(group), status="valid",
            )
            db.add(batch)
            db.flush()
            for row_number, row in group:
                db.add(IncomeRecord(
                    company_id=company_id, period_id=period_id, batch_id=batch.id,
                    workflow_code=workflow_code, source_role=role, org_code=org_code,
                    source_row_number=row_number, person_name=_person_name(row),
                    id_number=_id_number(row), employee_no=_employee_no(row), data_json=row,
                ))
    return {"batch_count": len(prepared), "row_count": sum(len(item[3]) for item in prepared)}


def load_income_frames(
    db: Session,
    *,
    company_id: int,
    period_id: int,
    workflow_code: str,
    roles: set[str] | None = None,
) -> dict[str, pd.DataFrame]:
    query = db.query(IncomeImportBatch).filter(
        IncomeImportBatch.company_id == company_id,
        IncomeImportBatch.period_id == period_id,
        IncomeImportBatch.workflow_code == workflow_code,
        IncomeImportBatch.status == "valid",
    ).order_by(IncomeImportBatch.id)
    if roles:
        query = query.filter(IncomeImportBatch.source_role.in_(roles))
    batches = query.all()
    if not batches:
        return {}
    rows = db.query(IncomeRecord).filter(
        IncomeRecord.batch_id.in_([batch.id for batch in batches]),
    ).order_by(IncomeRecord.source_role, IncomeRecord.source_row_number).all()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.source_role, []).append(dict(row.data_json or {}))
    return {role: pd.DataFrame(values) for role, values in grouped.items()}


def save_income_workpaper(
    db: Session,
    *,
    period: Any,
    workflow_code: str,
    detail: pd.DataFrame,
    summary: pd.DataFrame,
    issues: list[dict[str, Any]],
    status: str,
    input_sha256: str = "",
) -> IncomeWorkpaper:
    company_id = _company_id(period)
    period_id = int(period.id)
    workpaper = db.query(IncomeWorkpaper).filter(
        IncomeWorkpaper.company_id == company_id,
        IncomeWorkpaper.period_id == period_id,
        IncomeWorkpaper.workflow_code == workflow_code,
    ).first()
    if workpaper is None:
        workpaper = IncomeWorkpaper(company_id=company_id, period_id=period_id, workflow_code=workflow_code)
        db.add(workpaper)
    workpaper.status = status
    workpaper.input_sha256 = input_sha256
    workpaper.detail_json = _records(detail if isinstance(detail, pd.DataFrame) else pd.DataFrame(detail))
    workpaper.summary_json = _records(summary if isinstance(summary, pd.DataFrame) else pd.DataFrame(summary))
    workpaper.issues_json = [_safe(item) for item in (issues or [])]
    db.flush()
    return workpaper


def load_income_workpaper(db: Session, *, company_id: int, period_id: int, workflow_code: str) -> IncomeWorkpaper | None:
    return db.query(IncomeWorkpaper).filter(
        IncomeWorkpaper.company_id == company_id,
        IncomeWorkpaper.period_id == period_id,
        IncomeWorkpaper.workflow_code == workflow_code,
    ).first()
