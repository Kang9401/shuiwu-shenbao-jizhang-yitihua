from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


LEGACY_SALARY_ROLE_ALIASES = {
    "branch_salary": "marketing_salary",
    "digital_ops_salary": "marketing_salary",
    "advisor_salary": "marketing_salary",
    "marketing_salary": "marketing_salary",
    "rank_salary": "rank_salary",
    "headquarters_salary": "headquarters_salary",
}

BROKER_KEYWORDS = ("经纪人", "证券经纪")
MARKETING_KEYWORDS = ("营销", "投顾", "投资顾问", "理财经理", "数字化", "机构业务")


@dataclass(frozen=True)
class SalaryClassification:
    role: str
    reason: str
    warnings: tuple[str, ...] = ()


def normalize_salary_role(role: str) -> str:
    try:
        return LEGACY_SALARY_ROLE_ALIASES[role]
    except KeyError as exc:
        raise ValueError(f"未知工资角色：{role}") from exc


def normalize_employee_id(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def _first_column(frame: pd.DataFrame, names: Iterable[str]):
    return next((name for name in names if name in frame.columns), None)


def classify_salary_frame(frame: pd.DataFrame, filename: str = "") -> SalaryClassification:
    text_parts = [filename]
    suite_column = _first_column(frame, ("薪资套", "工资套", "薪资方案", "工资类别"))
    if suite_column:
        text_parts.extend(str(value) for value in frame[suite_column].dropna().unique()[:20])
    signature = " ".join(text_parts)
    if any(word in signature for word in BROKER_KEYWORDS) or len(frame.columns) == 27:
        return SalaryClassification("broker_salary", "经纪人薪资套或独立模板")
    if "总部" in signature:
        return SalaryClassification("headquarters_salary", "总部薪资套")
    if any(word in signature for word in MARKETING_KEYWORDS):
        return SalaryClassification("marketing_salary", "营销类薪资套")

    id_column = _first_column(frame, ("员工编号", "人员编号", "工号", "员工工号"))
    ids = [normalize_employee_id(value) for value in frame[id_column]] if id_column else []
    ids = [value for value in ids if value]
    five = sum(value.isdigit() and len(value) == 5 for value in ids)
    seven = sum(value.isdigit() and len(value) == 7 for value in ids)
    if seven > five and seven >= max(1, len(ids) // 2):
        return SalaryClassification("marketing_salary", "员工编号主要为 7 位")
    if five >= seven and five >= max(1, len(ids) // 2):
        return SalaryClassification("rank_salary", "员工编号主要为 5 位")
    raise ValueError(f"无法可靠识别工资文件类型：{Path(filename).name or '未命名文件'}")


def classify_salary_file(path: Path, filename: str = "") -> SalaryClassification:
    return classify_salary_frame(pd.read_excel(path, dtype=object), filename or path.name)


def normalize_payroll_files(files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    normalized: dict[str, str] = {}
    for role, path in files:
        target = normalize_salary_role(role)
        if target in normalized:
            raise ValueError(f"检测到多份{target}文件，请确认已合并后再上传")
        normalized[target] = path
    return list(normalized.items())
