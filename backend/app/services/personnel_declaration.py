"""Build employee declaration changes from consecutive monthly personnel masters."""
from __future__ import annotations

import calendar
from pathlib import Path
from typing import Any

import pandas as pd

from app.services.personnel_review import PERSONNEL_CHANGE_COLUMNS


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _first_value(row: pd.Series, columns: list[str]) -> str:
    for column in columns:
        if column in row.index:
            value = _clean(row.get(column))
            if value:
                return value
    return ""


def _is_active(value: str) -> bool:
    return value in {"", "正常", "在职"}


def _id_gender(id_number: str) -> str:
    if len(id_number) != 18 or not id_number[-2].isdigit():
        return ""
    return "男" if int(id_number[-2]) % 2 else "女"


def _id_birth_date(id_number: str) -> str:
    if len(id_number) != 18 or not id_number[6:14].isdigit():
        return ""
    return f"{id_number[6:10]}-{id_number[10:12]}-{id_number[12:14]}"


def _normalize_master(frame: pd.DataFrame) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for _, row in frame.fillna("").iterrows():
        name = _first_value(row, ["*姓名", "姓名", "员工姓名", "人员姓名"])
        id_number = _first_value(row, ["证件号码", "*证件号码", "身份证号码", "证件号"])
        employee_id = _first_value(row, ["员工编号", "工号"])
        identity = id_number or (f"{employee_id}|{name}" if employee_id or name else "")
        if not identity:
            continue
        records.append({
            "identity": identity,
            "name": name,
            "id_number": id_number,
            "employee_id": employee_id,
            "cert_type": _first_value(row, ["证件类型", "*证件类型"]),
            "nationality": _first_value(row, ["国籍(地区)", "*国籍(地区)"]),
            "gender": _first_value(row, ["性别", "*性别"]),
            "birth_date": _first_value(row, ["出生日期", "*出生日期"]),
            "phone": _first_value(row, ["手机号码", "手机", "联系电话"]),
            "hire_date": _first_value(row, ["任职受雇从业日期", "入职日期"]),
            "leave_date": _first_value(row, ["离职日期"]),
            "org_code": _first_value(row, ["机构代码", "机构代码(人员信息表)", "机构代码(工资单)"]),
            "status": _first_value(row, ["人员状态", "*人员状态", "状态"]),
        })
    return records


def _change_row(record: dict[str, str], *, status: str, year: int, month: int, leave_date: str = "") -> dict[str, str]:
    id_number = record["id_number"]
    cert_type = record["cert_type"] or ("居民身份证" if id_number else "")
    default_hire = f"{year}/{month:02d}/01"
    default_leave = f"{year}/{month:02d}/{calendar.monthrange(year, month)[1]:02d}"
    return {
        "*姓名": record["name"],
        "证件类型": cert_type,
        "证件号码": id_number,
        "国籍(地区)": record["nationality"] or ("中国" if id_number else ""),
        "性别": record["gender"] or _id_gender(id_number),
        "出生日期": record["birth_date"] or _id_birth_date(id_number),
        "人员状态": status,
        "任职受雇从业类型": "雇员",
        "手机号码": record["phone"],
        "任职受雇从业日期": record["hire_date"] or (default_hire if status == "正常" else ""),
        "离职日期": leave_date or (default_leave if status == "非正常" else ""),
        "机构代码(人员信息表)": record["org_code"],
        "机构代码(工资单)": record["org_code"] if status == "正常" else "",
        "员工编号": record["employee_id"],
    }


def build_monthly_personnel_change_table(
    previous_master_path: str | Path,
    current_master_path: str | Path,
    year: int,
    month: int,
) -> pd.DataFrame:
    """Return declaration rows for active employee changes between two monthly masters."""
    previous_records = _normalize_master(pd.read_excel(previous_master_path, dtype=str))
    current_records = _normalize_master(pd.read_excel(current_master_path, dtype=str))

    previous_active = {
        (record["identity"], record["org_code"]): record
        for record in previous_records
        if _is_active(record["status"])
    }
    current_active = {
        (record["identity"], record["org_code"]): record
        for record in current_records
        if _is_active(record["status"])
    }
    current_non_normal = {
        (record["identity"], record["org_code"]): record
        for record in current_records
        if not _is_active(record["status"])
    }

    rows: list[dict[str, str]] = []
    for key in sorted(previous_active.keys() - current_active.keys()):
        previous = previous_active[key]
        current = current_non_normal.get(key, previous)
        rows.append(_change_row(previous, status="非正常", year=year, month=month, leave_date=current["leave_date"]))
    for key in sorted(current_active.keys() - previous_active.keys()):
        rows.append(_change_row(current_active[key], status="正常", year=year, month=month))

    return pd.DataFrame(rows, columns=PERSONNEL_CHANGE_COLUMNS)
