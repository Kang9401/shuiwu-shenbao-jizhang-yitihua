from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.accounting import PersonnelMasterArtifact, PersonnelMasterImportBatch
from app.models.core import Period, UploadedFile
from app.services.excel import read_excel, write_workbook
from app.services.storage import save_upload


PERSON_TYPES = {"employee", "intern", "broker", "customer"}
SCOPE_TYPES = {"month", "org", "branch"}
ORG_NAME_ALIASES = ["营业部全称", "机构名称", "单位名称", "部门名称"]
ORG_CODE_ALIASES = ["机构代码", "分支机构代码", "单位编号"]


class PersonnelMasterValidationError(ValueError):
    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = issues
        super().__init__("；".join(issue["message"] for issue in issues))


def _clean_org_code(value: Any) -> str:
    text = _clean(value).replace(" ", "")
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def list_rpa_organizations(db: Session, *, period_id: int, person_type: str = "employee") -> list[dict]:
    path = PersonnelMasterResolver(db, period_id).resolve_path(person_type)
    if not path:
        raise PersonnelMasterValidationError([{"issue_type": "missing_personnel_master", "message": "所属期间没有雇员人员主数据"}])
    frame = read_excel(path).fillna("")
    name_col = _first_existing(frame.columns, ORG_NAME_ALIASES)
    code_col = _first_existing(frame.columns, ORG_CODE_ALIASES)
    issues: list[dict[str, Any]] = []
    if not name_col:
        issues.append({"issue_type": "missing_column", "column": "营业部全称", "message": "人员主数据缺少营业部全称列"})
    if not code_col:
        issues.append({"issue_type": "missing_column", "column": "机构代码", "message": "人员主数据缺少机构代码列"})
    if issues:
        raise PersonnelMasterValidationError(issues)
    status_col = _first_existing(frame.columns, ["人员状态", "*人员状态", "状态"])
    active = frame[frame[status_col].map(_is_active_status)] if status_col else frame
    code_names: dict[str, set[str]] = {}
    name_codes: dict[str, set[str]] = {}
    counts: dict[tuple[str, str], int] = {}
    for index, row in active.iterrows():
        name, code = _clean(row.get(name_col)), _clean_org_code(row.get(code_col))
        if not name:
            issues.append({"issue_type": "missing_org_name", "row_number": int(index + 2), "message": f"第 {index + 2} 行营业部全称为空"})
            continue
        if not code:
            issues.append({"issue_type": "missing_org_code", "row_number": int(index + 2), "message": f"第 {index + 2} 行机构代码为空"})
            continue
        code_names.setdefault(code, set()).add(name)
        name_codes.setdefault(name, set()).add(code)
        counts[(code, name)] = counts.get((code, name), 0) + 1
    for code, names in code_names.items():
        if len(names) > 1:
            issues.append({"issue_type": "org_code_name_conflict", "org_code": code, "names": sorted(names), "message": f"机构代码 {code} 对应多个营业部全称"})
    for name, codes in name_codes.items():
        if len(codes) > 1:
            issues.append({"issue_type": "org_name_code_conflict", "org_name": name, "codes": sorted(codes), "message": f"营业部全称 {name} 对应多个机构代码"})
    if issues:
        raise PersonnelMasterValidationError(issues)
    return [
        {"code": code, "name": next(iter(code_names[code])), "employee_count": counts[(code, next(iter(code_names[code])))]}
        for code in sorted(code_names)
    ]


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _is_active_status(value: Any) -> bool:
    status = _clean(value)
    return status in {"", "正常", "在职"}


def _first_existing(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    return None


def _period_label(period: Period | None, period_id: int) -> str:
    return f"{period.year}{period.month:02d}" if period else str(period_id)


def _scope_code(scope_type: str, scope_code: Optional[str]) -> str:
    return "" if scope_type == "month" else _clean(scope_code)


def _validate_master_frame(
    df: pd.DataFrame,
    *,
    scope_type: str,
    scope_code: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    name_col = _first_existing(df.columns, ["*姓名", "姓名", "员工姓名", "客户姓名", "人员姓名"])
    id_col = _first_existing(df.columns, ["*证件号码", "证件号码", "身份证号", "证件号"])
    if name_col is None:
        issues.append({"issue_type": "missing_column", "message": "人员主数据缺少姓名列", "column": "姓名"})
    if id_col is None:
        issues.append({"issue_type": "missing_column", "message": "人员主数据缺少证件号码列", "column": "证件号码"})
    if issues:
        return issues

    for idx, row in df.iterrows():
        missing = []
        if not _clean(row.get(name_col)):
            missing.append(name_col)
        if not _clean(row.get(id_col)):
            missing.append(id_col)
        if missing:
            issues.append({
                "issue_type": "missing_required_fields",
                "message": f"第 {idx + 2} 行缺少：{'、'.join(missing)}",
                "row_number": int(idx + 2),
                "missing_fields": missing,
            })

    status_col = _first_existing(df.columns, ["人员状态", "*人员状态", "状态"])
    active_df = df[df[status_col].map(_is_active_status)] if status_col else df
    duplicated_active = active_df[
        active_df[id_col].map(_clean).duplicated(keep=False) & (active_df[id_col].map(_clean) != "")
    ]
    for idx, row in duplicated_active.iterrows():
        issues.append({
            "issue_type": "duplicate_id_number",
            "message": f"第 {idx + 2} 行正常状态证件号码重复：{_clean(row.get(id_col))}",
            "row_number": int(idx + 2),
            "id_number": _clean(row.get(id_col)),
            "status": _clean(row.get(status_col)) if status_col else "正常",
        })

    if scope_type in {"org", "branch"}:
        candidates = ["机构代码", "分支机构代码", "单位编号"] if scope_type == "org" else ["分公司代码", "分公司", "分支机构代码"]
        scope_col = _first_existing(df.columns, candidates)
        if scope_col is None:
            issues.append({
                "issue_type": "missing_scope_column",
                "message": f"{scope_type} 范围导入缺少范围匹配列",
                "scope_type": scope_type,
            })
        else:
            mismatch = df[df[scope_col].map(_clean) != scope_code]
            for idx, row in mismatch.iterrows():
                issues.append({
                    "issue_type": "scope_mismatch",
                    "message": f"第 {idx + 2} 行范围值 {_clean(row.get(scope_col))} 与导入范围 {scope_code} 不一致",
                    "row_number": int(idx + 2),
                    "scope_column": scope_col,
                    "actual": _clean(row.get(scope_col)),
                    "expected": scope_code,
                })
    return issues


def import_personnel_master(
    db: Session,
    *,
    period_id: int,
    person_type: str,
    scope_type: str,
    scope_code: Optional[str],
    file: UploadFile,
) -> PersonnelMasterArtifact:
    if person_type not in PERSON_TYPES:
        raise PersonnelMasterValidationError([{"issue_type": "invalid_person_type", "message": "人员类型不合法"}])
    if scope_type not in SCOPE_TYPES:
        raise PersonnelMasterValidationError([{"issue_type": "invalid_scope_type", "message": "导入口径不合法"}])
    normalized_scope_code = _scope_code(scope_type, scope_code)
    if scope_type != "month" and not normalized_scope_code:
        raise PersonnelMasterValidationError([{"issue_type": "missing_scope_code", "message": "按机构或分公司导入时必须填写范围代码"}])

    source_path, _ = save_upload(file, period_id, f"personnel_master_{person_type}_{scope_type}")
    df = read_excel(source_path).fillna("")
    issues = _validate_master_frame(df, scope_type=scope_type, scope_code=normalized_scope_code)
    if issues:
        raise PersonnelMasterValidationError(issues)

    period = db.query(Period).filter(Period.id == period_id).first()
    period_label = _period_label(period, period_id)
    file_name = f"{period_label}_{person_type}_{scope_type}_{normalized_scope_code or 'all'}.xlsx"
    target_dir = settings.artifact_dir / "personnel_masters" / str(period_id) / person_type
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_path = target_dir / file_name
    shutil.copy2(source_path, stored_path)

    artifact = (
        db.query(PersonnelMasterArtifact)
        .filter(
            PersonnelMasterArtifact.period_id == period_id,
            PersonnelMasterArtifact.person_type == person_type,
            PersonnelMasterArtifact.scope_type == scope_type,
            PersonnelMasterArtifact.scope_code == normalized_scope_code,
        )
        .first()
    )
    if artifact is None:
        artifact = PersonnelMasterArtifact(
            period_id=period_id,
            person_type=person_type,
            scope_type=scope_type,
            scope_code=normalized_scope_code,
            file_name=file_name,
            stored_path=str(stored_path),
        )
    artifact.file_name = file_name
    artifact.stored_path = str(stored_path)
    artifact.row_count = int(len(df))
    artifact.validation_issues = []
    artifact.updated_at = datetime.utcnow()
    db.add(artifact)
    db.flush()

    db.add(
        PersonnelMasterImportBatch(
            period_id=period_id,
            artifact_id=artifact.id,
            person_type=person_type,
            scope_type=scope_type,
            scope_code=normalized_scope_code,
            original_name=file.filename or file_name,
            stored_path=str(source_path),
            row_count=int(len(df)),
            validation_issues=[],
        )
    )
    db.commit()
    db.refresh(artifact)
    return artifact


def save_generated_employee_master(
    db: Session,
    *,
    period_id: int,
    display_path: str | Path,
    full_history_path: str | Path,
    source_session_id: int,
) -> PersonnelMasterArtifact:
    """保存工资薪金核对生成的本月员工主数据。

    对外人员信息表隐藏历史非正常人员；完整历史文件保留在同一期间目录中。
    """
    period = db.query(Period).filter(Period.id == period_id).first()
    period_label = _period_label(period, period_id)
    target_dir = settings.artifact_dir / "personnel_masters" / str(period_id) / "employee"
    target_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{period_label}_employee_month_all.xlsx"
    stored_path = target_dir / file_name
    history_path = target_dir / f"{period_label}_employee_history.xlsx"
    shutil.copy2(display_path, stored_path)
    shutil.copy2(full_history_path, history_path)

    frame = read_excel(stored_path).fillna("")
    artifact = get_personnel_master_artifact(db, period_id, "employee", "month")
    if artifact is None:
        artifact = PersonnelMasterArtifact(
            period_id=period_id,
            person_type="employee",
            scope_type="month",
            scope_code="",
            file_name=file_name,
            stored_path=str(stored_path),
        )
        db.add(artifact)
        db.flush()
    artifact.file_name = file_name
    artifact.stored_path = str(stored_path)
    artifact.row_count = int(len(frame))
    artifact.validation_issues = []
    artifact.updated_at = datetime.utcnow()
    db.add(
        PersonnelMasterImportBatch(
            period_id=period_id,
            artifact_id=artifact.id,
            person_type="employee",
            scope_type="month",
            scope_code="",
            original_name="工资薪金核对生成的本月员工主数据",
            stored_path=str(history_path),
            row_count=int(len(frame)),
            validation_issues=[],
        )
    )
    db.flush()
    return artifact


def get_personnel_master_artifact(
    db: Session,
    period_id: int,
    person_type: str,
    scope_type: str = "month",
    scope_code: Optional[str] = None,
) -> PersonnelMasterArtifact | None:
    return (
        db.query(PersonnelMasterArtifact)
        .filter(
            PersonnelMasterArtifact.period_id == period_id,
            PersonnelMasterArtifact.person_type == person_type,
            PersonnelMasterArtifact.scope_type == scope_type,
            PersonnelMasterArtifact.scope_code == _scope_code(scope_type, scope_code),
        )
        .first()
    )


def resolve_employee_history_path(db: Session, period_id: int) -> str | None:
    """Return the complete employee master, including historical non-normal rows."""
    artifact = get_personnel_master_artifact(db, period_id, "employee", "month")
    if artifact is None:
        return None

    stored_path = Path(artifact.stored_path)
    if not stored_path.exists():
        return None

    period = db.query(Period).filter(Period.id == period_id).first()
    history_path = stored_path.parent / f"{_period_label(period, period_id)}_employee_history.xlsx"
    return str(history_path if history_path.exists() else stored_path)


def list_personnel_master_status(db: Session, period_id: int, person_type: str) -> list[PersonnelMasterArtifact]:
    return (
        db.query(PersonnelMasterArtifact)
        .filter(
            PersonnelMasterArtifact.period_id == period_id,
            PersonnelMasterArtifact.person_type == person_type,
        )
        .order_by(PersonnelMasterArtifact.scope_type, PersonnelMasterArtifact.scope_code)
        .all()
    )


def list_personnel_master_batches(db: Session, period_id: int, person_type: str) -> list[PersonnelMasterImportBatch]:
    return (
        db.query(PersonnelMasterImportBatch)
        .filter(
            PersonnelMasterImportBatch.period_id == period_id,
            PersonnelMasterImportBatch.person_type == person_type,
        )
        .order_by(PersonnelMasterImportBatch.created_at.desc())
        .limit(200)
        .all()
    )


class PersonnelMasterResolver:
    def __init__(self, db: Session, period_id: Optional[int]):
        self.db = db
        self.period_id = period_id

    def resolve_uploaded_file(self, person_type: str, file_role: str = "staff_info") -> UploadedFile | None:
        path = self.resolve_path(person_type)
        if path is None:
            return None
        file_path = Path(path)
        return UploadedFile(
            period_id=self.period_id,
            file_role=file_role,
            original_name=file_path.name,
            stored_path=str(file_path),
            size_bytes=file_path.stat().st_size,
            validation_status="shared_personnel_master",
            validation_issues=[],
        )

    def resolve_path(self, person_type: str) -> str | None:
        if self.db is None or self.period_id is None:
            return None
        month_artifact = get_personnel_master_artifact(self.db, self.period_id, person_type, "month")
        if month_artifact and Path(month_artifact.stored_path).exists():
            return month_artifact.stored_path

        scoped = (
            self.db.query(PersonnelMasterArtifact)
            .filter(
                PersonnelMasterArtifact.period_id == self.period_id,
                PersonnelMasterArtifact.person_type == person_type,
            )
            .order_by(PersonnelMasterArtifact.scope_type, PersonnelMasterArtifact.scope_code)
            .all()
        )
        frames = []
        for artifact in scoped:
            path = Path(artifact.stored_path)
            if path.exists():
                frames.append(read_excel(path).fillna(""))
        if frames:
            combined = pd.concat(frames, ignore_index=True, sort=False)
            output = settings.artifact_dir / "personnel_masters" / str(self.period_id) / person_type / "combined.xlsx"
            write_workbook(output, {"人员主数据": combined})
            return str(output)

        return None
