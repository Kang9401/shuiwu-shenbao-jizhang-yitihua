"""通用个税流程回归对账工具。

这个模块不替代业务 workflow，只用于把一批样例数据跑成稳定快照：
- 底稿人数、机构数、金额汇总；
- 个税差异、人员变动、证件缺失、专项扣除异常数量；
- 待 HR 确认的 `人员信息变动表-雇员.xlsx`。

后续迁移旧脚本中的精细公式时，先看这里的快照有没有变化，避免无意改坏口径。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.services.personnel_review import build_personnel_change_review_table
from app.services.verification import build_working_sheet, verify


@dataclass(frozen=True)
class TaxSamplePaths:
    sample_dir: Path
    staff_info: Path
    deduction_dir: Path
    payroll_files: list[tuple[str, Path]]


def default_tax_test_paths(sample_dir: str | Path) -> TaxSamplePaths:
    """按当前 `个税测试` 文件名组装样例路径。"""
    base = Path(sample_dir)
    payroll_files = [
        ("rank_salary", base / "工资横表（薪资 202502）.xls"),
        ("marketing_salary", base / "零售数字化营销平台 - 营销人员综合业绩指标(新) - 20250314.xlsx"),
        ("headquarters_salary", base / "总部代发-成都分公司202502.xlsx"),
        ("branch_salary", base / "零售数字化营销平台 - 机构业务人员综合业绩指标 - 20250314.xlsx"),
        ("advisor_salary", base / "零售数字化营销平台 - 投资顾问、理财经理及零售经理工资明细 - 20250317.xlsx"),
    ]
    paths = TaxSamplePaths(
        sample_dir=base,
        staff_info=base / "人员信息表(2025年02月).xlsx",
        deduction_dir=base / "专项附加扣除",
        payroll_files=payroll_files,
    )
    missing = [str(p) for _, p in payroll_files if not p.exists()]
    for p in [paths.staff_info, paths.deduction_dir]:
        if not p.exists():
            missing.append(str(p))
    if missing:
        raise FileNotFoundError("个税测试样例缺少文件：" + "；".join(missing))
    return paths


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _sum(sheet: pd.DataFrame, column: str) -> float:
    if column not in sheet.columns:
        return 0.0
    return round(float(pd.to_numeric(sheet[column], errors="coerce").fillna(0).sum()), 2)


def run_tax_regression_snapshot(
    sample_dir: str | Path,
    output_dir: str | Path,
    year: int = 2025,
    month: int = 2,
) -> dict:
    paths = default_tax_test_paths(sample_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    sheet, staff_df = build_working_sheet(
        [(role, str(path)) for role, path in paths.payroll_files],
        str(paths.staff_info),
        str(paths.deduction_dir),
    )
    report = verify(sheet, str(paths.deduction_dir), staff_df=staff_df, year=year, month=month)
    change_table = build_personnel_change_review_table(report, year, month)

    sheet_path = out / "平台底稿.xlsx"
    change_path = out / "人员信息变动表-雇员.xlsx"
    summary_path = out / "个税回归对账摘要.json"
    sheet.to_excel(sheet_path, index=False)
    change_table.to_excel(change_path, index=False)

    change_counts = Counter(item["change_type"] for item in report["personnel_changes"]["items"])
    org_col = "机构代码_工资单" if "机构代码_工资单" in sheet.columns else "机构代码"
    summary = {
        "sample_dir": str(paths.sample_dir),
        "period": f"{year}-{month:02d}",
        "outputs": {
            "working_sheet": str(sheet_path),
            "personnel_change_review": str(change_path),
            "summary": str(summary_path),
        },
        "sheet": {
            "rows": int(len(sheet)),
            "columns": int(len(sheet.columns)),
            "staff_active_rows": int(len(staff_df)),
            "org_count": int(sheet[org_col].nunique()) if org_col in sheet.columns else 0,
            "orgs": sorted([_clean(v) for v in sheet[org_col].dropna().unique()]) if org_col in sheet.columns else [],
        },
        "amounts": {
            "income_total": _sum(sheet, "本期收入"),
            "declared_tax_total": _sum(sheet, "个人所得税 SUM"),
            "withheld_tax_total": _sum(sheet, "本期应预扣预缴税额 SUM"),
            "tax_diff_total": _sum(sheet, "个税差异"),
        },
        "issues": {
            "total": int(report["summary"]["total_issues"]),
            "tax_diff": len(report["tax_diff"]["items"]),
            "personnel_changes": len(report["personnel_changes"]["items"]),
            "personnel_change_types": dict(sorted(change_counts.items())),
            "missing_cert": len(report["missing_cert"]["items"]),
            "deduction_duplicates": len(report["deduction_warnings"]["duplicates"]),
            "deduction_missing_orgs": len(report["deduction_warnings"]["missing_orgs"]),
        },
        "review_table": {
            "rows": int(len(change_table)),
            "columns": change_table.columns.tolist(),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
