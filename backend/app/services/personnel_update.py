"""人员信息表更新服务。

复现 `人员信息表更新模板.py` 的核心规则：
- 用户只维护人员信息变动表；
- 离职人员回写到原人员信息表为非正常；
- 新入职/调岗新增正常人员行；
- 输出更新后的完整人员信息表和税局人员信息采集文件。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


PERSONNEL_COLLECTION_COLUMNS = [
    "工号", "*姓名", "*证件类型", "*证件号码", "*国籍(地区)", "*性别", "*出生日期",
    "是否高级专家", "人员状态", "*任职受雇从业类型", "其他情况说明", "入职年度就业情形",
    "手机号码", "任职受雇从业日期", "离职日期", "是否离职后补发工资", "实际补发工资的月份",
    "是否残疾", "是否烈属", "是否孤老", "残疾证件类型", "残疾证号", "烈属证号",
    "是否扣除减除费用", "个人投资额", "个人投资比例(%)", "备注", "中文名", "涉税事由",
    "出生国家(地区)", "首次入境时间", "预计离境时间", "其他证件类型", "其他证件号码",
    "户籍所在地（省）", "户籍所在地（市）", "户籍所在地（区县）", "户籍所在地（详细地址）",
    "经常居住地（省）", "经常居住地（市）", "经常居住地（区县）", "经常居住地（详细地址）",
    "联系地址（省）", "联系地址（市）", "联系地址（区县）", "联系地址（详细地址）",
    "电子邮箱", "学历", "开户银行", "银行账号", "开户行省份", "职务",
]

CHANGE_REQUIRED_COLUMNS = ["证件类型", "机构代码(人员信息表)", "员工编号", "证件号码", "*姓名", "人员状态"]


class PersonnelUpdateValidationError(ValueError):
    """Validation error with row-level details for the frontend."""

    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = issues
        super().__init__("；".join(issue["message"] for issue in issues))


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = df.copy()
    for col in columns:
        if col not in result.columns:
            result[col] = ""
    return result


def _format_date_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = df.copy()
    for col in columns:
        if col not in result.columns:
            result[col] = ""
            continue
        parsed = pd.to_datetime(result[col], errors="coerce")
        result[col] = parsed.dt.strftime("%Y-%m-%d").fillna("")
    return result


def _write_excel(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fp:
        df.to_excel(fp, index=False, engine="openpyxl")


def _validate_change_table(change: pd.DataFrame) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    missing_columns = [col for col in CHANGE_REQUIRED_COLUMNS if col not in change.columns]
    if missing_columns:
        issues.append({
            "issue_type": "missing_columns",
            "message": f"人员信息变动表缺少列：{'、'.join(missing_columns)}",
            "columns": missing_columns,
        })
        return issues

    base_required = ["证件类型", "员工编号", "证件号码", "*姓名", "机构代码(人员信息表)"]
    for idx, row in change.iterrows():
        status = _clean(row.get("人员状态"))
        required = list(base_required)
        cert_type = _clean(row.get("证件类型"))
        if cert_type and cert_type != "居民身份证":
            required.extend(["国籍(地区)", "性别", "出生日期"])
        missing_fields = [col for col in required if _clean(row.get(col)) == ""]
        if missing_fields:
            name = _clean(row.get("*姓名")) or "未填姓名"
            issues.append({
                "issue_type": "missing_required_fields",
                "message": f"第 {idx + 2} 行 {name} 缺少：{'、'.join(missing_fields)}",
                "row_number": int(idx + 2),
                "name": name,
                "missing_fields": missing_fields,
            })
    return issues


def _find_duplicate_additions(staff: pd.DataFrame, additions: pd.DataFrame) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if additions.empty or "证件号码" not in staff.columns:
        return issues
    existing_ids = set(staff["证件号码"].map(_clean))
    for idx, row in additions.iterrows():
        id_num = _clean(row.get("证件号码"))
        if id_num and id_num in existing_ids:
            issues.append({
                "issue_type": "duplicate_addition",
                "message": f"新增人员 {row.get('*姓名', '')} 的证件号码 {id_num} 已存在于人员信息表",
                "row_number": int(idx + 2),
                "name": _clean(row.get("*姓名")),
                "id_number": id_num,
            })
    return issues


def _headcount_reconciliation(before_count: int, additions: int, leavers: int, after_count: int) -> dict:
    expected = before_count + additions - leavers
    ok = expected == after_count
    return {
        "has_issues": not ok,
        "items": [] if ok else [{
            "issue_type": "headcount_reconciliation_failed",
            "message": f"人数对账不平：更新前 {before_count} + 新增 {additions} - 离职 {leavers} = {expected}，实际更新后 {after_count}",
            "before_count": before_count,
            "additions": additions,
            "leavers": leavers,
            "expected_after_count": expected,
            "actual_after_count": after_count,
        }],
        "before_count": before_count,
        "additions": additions,
        "leavers": leavers,
        "expected_after_count": expected,
        "actual_after_count": after_count,
    }


def _active_staff_count(staff: pd.DataFrame) -> int:
    if "人员状态" not in staff.columns:
        return int(len(staff))
    return int((staff["人员状态"].map(_clean) == "正常").sum())


def build_personnel_collection_files(
    change: pd.DataFrame,
    output_dir: Path,
    year: int,
    month: int,
    *,
    person_type_label: str = "员工",
    duplicate_keep: str | bool = False,
    collection_sequence: str = "1",
    file_extension: str = ".xls",
) -> list[str]:
    work = change.copy()
    if work.empty:
        return []

    if "机构代码(人员信息表)" in work.columns and "机构代码(工资单)" in work.columns:
        work["机构代码(人员信息表)"] = work.apply(
            lambda row: _clean(row.get("机构代码(人员信息表)")) or _clean(row.get("机构代码(工资单)")),
            axis=1,
        )

    work = work.drop_duplicates(
        subset=["*姓名", "证件类型", "证件号码", "机构代码(人员信息表)"],
        keep=duplicate_keep,
    )
    if work.empty:
        return []

    work = work.drop(columns=["机构代码(工资单)", "员工编号"], errors="ignore")
    work = work.rename(columns={
        "证件类型": "*证件类型",
        "证件号码": "*证件号码",
        "国籍(地区)": "*国籍(地区)",
        "性别": "*性别",
        "出生日期": "*出生日期",
        "任职受雇从业类型": "*任职受雇从业类型",
    })

    template = pd.DataFrame(columns=PERSONNEL_COLLECTION_COLUMNS)
    work = pd.concat([template, work], axis=0, ignore_index=True)
    work = work.drop(columns=["人员状态"], errors="ignore")
    work = _format_date_columns(work, ["*出生日期", "任职受雇从业日期", "离职日期"])

    files: list[str] = []
    org_col = "机构代码(人员信息表)"
    if org_col not in work.columns:
        return files

    for org, group in work.groupby(org_col):
        org_text = _clean(org)
        if not org_text:
            continue
        out = group.drop(columns=[org_col], errors="ignore")
        path = output_dir / f"{org_text}_{collection_sequence}-人员信息采集_{person_type_label}({year}年{month:02d}月){file_extension}"
        _write_excel(out, path)
        files.append(str(path))
    return files


def _display_staff_frame(staff: pd.DataFrame, change: pd.DataFrame) -> pd.DataFrame:
    """人员信息表只展示正常人员和本月确认的非正常变动。"""
    if "人员状态" not in staff.columns:
        return staff.copy()
    normal = staff[staff["人员状态"].map(_clean) == "正常"].copy()
    non_normal = staff[staff["人员状态"].map(_clean) == "非正常"].copy()
    current_non_normal = change[change["人员状态"].map(_clean) == "非正常"]
    if current_non_normal.empty or "证件号码" not in staff.columns:
        return normal

    keys = {
        (_clean(row.get("证件号码")), _clean(row.get("机构代码(人员信息表)")))
        for _, row in current_non_normal.iterrows()
    }
    current_non_normal_rows = non_normal[
        non_normal.apply(
            lambda row: (_clean(row.get("证件号码")), _clean(row.get("机构代码"))) in keys,
            axis=1,
        )
    ]
    return pd.concat([normal, current_non_normal_rows], ignore_index=True)


def apply_staff_info_update(
    staff_info_path: str,
    change_table_path: str,
    output_dir: str,
    year: int,
    month: int,
) -> dict:
    staff = pd.read_excel(staff_info_path, dtype=str).fillna("")
    change = pd.read_excel(change_table_path, dtype=str).fillna("")

    issues = _validate_change_table(change)
    if issues:
        raise PersonnelUpdateValidationError(issues)

    staff = _ensure_columns(staff, [
        "人员状态", "证件号码", "机构代码", "国籍(地区)", "性别", "出生日期", "离职日期",
    ])
    change = _ensure_columns(change, [
        "机构代码(工资单)", "任职受雇从业类型", "国籍(地区)", "性别", "出生日期", "离职日期",
    ])
    before_count = _active_staff_count(staff)

    # 离职：按证件号码 + 原人员信息表机构匹配正常人员，更新为非正常。
    leavers = change[change["人员状态"].map(_clean) == "非正常"].copy()
    match_failures: list[dict[str, Any]] = []
    multiple_matches: list[dict[str, Any]] = []
    matched_leaver_updates: list[tuple[int, pd.Series]] = []
    for change_idx, row in leavers.iterrows():
        id_num = _clean(row.get("证件号码"))
        org_code = _clean(row.get("机构代码(人员信息表)"))
        name = _clean(row.get("*姓名"))
        matches = staff[
            (staff["人员状态"].map(_clean) == "正常")
            & (staff["证件号码"].map(_clean) == id_num)
            & (staff["机构代码"].map(_clean) == org_code)
        ].index
        if matches.empty:
            match_failures.append({
                "issue_type": "leaver_not_matched",
                "message": f"离职人员 {name}（证件号码 {id_num}，机构 {org_code}）未在人员信息表中匹配到正常记录",
                "row_number": int(change_idx + 2),
                "name": name,
                "id_number": id_num,
                "org_code": org_code,
            })
            continue
        if len(matches) > 1:
            multiple_matches.append({
                "issue_type": "leaver_multiple_matches",
                "message": f"离职人员 {name}（证件号码 {id_num}，机构 {org_code}）匹配到 {len(matches)} 条正常记录，已使用第一条，请人工确认",
                "row_number": int(change_idx + 2),
                "name": name,
                "id_number": id_num,
                "org_code": org_code,
                "match_count": int(len(matches)),
            })
        matched_leaver_updates.append((int(matches[0]), row))

    # 入职/调岗新增：旧脚本把变动表中正常状态行追加到人员信息表。
    additions = change[change["人员状态"].map(_clean) == "正常"].copy()
    duplicate_additions = _find_duplicate_additions(staff, additions)
    blocking_issues = match_failures
    if blocking_issues:
        raise PersonnelUpdateValidationError(blocking_issues)

    for idx, row in matched_leaver_updates:
        staff.loc[idx, "人员状态"] = "非正常"
        for col in ["国籍(地区)", "性别", "出生日期", "离职日期"]:
            staff.loc[idx, col] = row.get(col, "")

    if not additions.empty:
        if "机构代码(工资单)" in additions.columns:
            additions["机构代码(人员信息表)"] = additions.apply(
                lambda row: _clean(row.get("机构代码(人员信息表)")) or _clean(row.get("机构代码(工资单)")),
                axis=1,
            )
        additions = additions.drop(columns=["机构代码(工资单)"], errors="ignore")
        additions = additions.rename(columns={"机构代码(人员信息表)": "机构代码"})
        additions = additions.drop(columns=["任职受雇从业类型"], errors="ignore")
        additions = additions.reindex(columns=staff.columns, fill_value="")
        staff = pd.concat([staff, additions], axis=0, ignore_index=True)

    headcount = _headcount_reconciliation(
        before_count=before_count,
        additions=int(len(additions)),
        leavers=int(len(matched_leaver_updates)),
        after_count=_active_staff_count(staff),
    )
    if headcount["has_issues"]:
        raise PersonnelUpdateValidationError(headcount["items"])

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    full_staff_path = out_dir / f"人员信息表完整数据({year}年{month:02d}月).xlsx"
    _write_excel(staff, full_staff_path)
    updated_staff_path = out_dir / f"人员信息表({year}年{month:02d}月).xlsx"
    _write_excel(_display_staff_frame(staff, change), updated_staff_path)

    collection_dir = out_dir / "税务申报"
    collection_files = build_personnel_collection_files(change, collection_dir, year, month)

    return {
        "updated_staff_path": str(updated_staff_path),
        "full_staff_path": str(full_staff_path),
        "collection_files": collection_files,
        "report": {
            "match_failures": match_failures,
            "duplicate_additions": duplicate_additions,
            "multiple_matches": multiple_matches,
            "headcount_reconciliation": headcount,
        },
    }
