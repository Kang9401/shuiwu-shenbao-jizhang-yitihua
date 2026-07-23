# backend/app/services/generation.py
"""申报表生成服务

全部核对通过后，基于底稿生成申报文件。
复现 通用个税模板.py 的 to_excelBycompany 逻辑。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services.verification import DECLARATION_COLUMNS, _normalize_emp_id, _clean_text


SALARY_RECONCILIATION_ONLY_FIELDS = {
    "工资单_累计子女教育扣除",
    "工资单_累计继续教育扣除",
    "工资单_累计住房贷款利息扣除",
    "工资单_累计住房租金扣除",
    "工资单_累计赡养老人扣除",
    "工资单_累计婴幼儿照护扣除",
    "工资单_累计商业保险扣除",
    "工资单_累计个人养老金",
}
DECLARATION_OUTPUT_FIELDS = frozenset(DECLARATION_COLUMNS)
if DECLARATION_OUTPUT_FIELDS & SALARY_RECONCILIATION_ONLY_FIELDS:
    raise RuntimeError("申报字段白名单不得包含工资核对专用累计扣除字段")


def generate_declarations(
    sheet: pd.DataFrame,
    output_dir: str,
    year: int,
    month: int,
    staff_df: pd.DataFrame | None = None,
) -> list[str]:
    """生成申报文件，返回产出文件路径列表。

    产出:
    - {org}_3-个税申报表(YYYY年MM月).xls  按机构拆分
    - 个税差异一览表.xls
    - 个税汇总一览表.xls
    - 人员信息变动汇总表.xlsx（含入职/调岗/离职三类，需传入 staff_df 才能检测离职）

    Args:
        sheet: 底稿 DataFrame
        output_dir: 输出目录
        year: 申报年度
        month: 申报月份
        staff_df: 人员信息表中"正常"状态的人员（用于离职反向差集检测）。
                  若不传，人员信息变动汇总表只含入职和调岗，不含离职。
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = []

    org_col = "机构代码_工资单" if "机构代码_工资单" in sheet.columns else "机构代码"
    if org_col not in sheet.columns:
        return files

    work = sheet.copy()

    # ---- 个税申报表（按机构拆分） ----
    for org, grp in work.groupby(org_col):
        org_str = str(org or "未知机构").strip()
        if not org_str or org_str == "nan":
            continue

        # 选择申报列
        output_cols = [c for c in DECLARATION_COLUMNS if c in grp.columns and c not in SALARY_RECONCILIATION_ONLY_FIELDS]
        org_sheet = grp[output_cols].copy()

        # 文本列：工号/姓名/证件类型/证件号码/备注 必须保留为字符串，禁止数值化
        text_cols = {"工号", "*姓名", "*证件类型", "*证件号码", "备注"}
        # 数值列：整数显示为整数（3723.0→"3723"），小数保留两位（3723.5→"3723.50"）
        for col in org_sheet.columns:
            if col in text_cols:
                org_sheet[col] = org_sheet[col].fillna("").astype(str).str.strip()
                # 去掉 float 转字符串残留的 ".0"（如 12345.0 → 12345）
                org_sheet[col] = org_sheet[col].str.replace(r"^nan$", "", regex=True)
                org_sheet[col] = org_sheet[col].str.replace(r"\.0$", "", regex=True)
            elif pd.api.types.is_float_dtype(org_sheet[col]):
                rounded = org_sheet[col].round(2).fillna(0)
                # 整数直接转 int 再转 str，避免 ".0"；小数保留两位
                org_sheet[col] = rounded.map(
                    lambda v: str(int(v)) if float(v).is_integer() else f"{float(v):.2f}"
                )
            else:
                org_sheet[col] = org_sheet[col].fillna("").astype(str)
                org_sheet[col] = org_sheet[col].str.replace(r"^nan$", "", regex=True)

        fname = f"{org_str}_3-个税申报表({year}年{month:02d}月).xls"
        fpath = out / fname
        org_sheet.to_excel(fpath, index=False)
        files.append(str(fpath))

    # ---- 个税差异一览表 ----
    if "个税差异" in work.columns:
        tax_col = "本期应预扣预缴税额 SUM" if "本期应预扣预缴税额 SUM" in work.columns else None
        diff_mask = work["个税差异"] != 0
        if tax_col:
            diff_mask = diff_mask & (work[tax_col] != 0)

        if diff_mask.any():
            display_cols = [c for c in [
                "*姓名", "员工编号", "证件类型", "证件号码",
                org_col, "本期应预扣预缴税额 SUM", "个人所得税 SUM", "个税差异"
            ] if c in work.columns]
            diff_sheet = work[diff_mask][display_cols].copy()
            fpath = out / "个税差异一览表.xls"
            diff_sheet.to_excel(fpath, index=False)
            files.append(str(fpath))

    # ---- 个税汇总一览表（按机构 pivot） ----
    if "本期应预扣预缴税额 SUM" in work.columns and "个人所得税 SUM" in work.columns:
        summary_cols = {}
        for name, col in [
            ("个人所得税汇总", "个人所得税 SUM"),
            ("个税差异汇总", "个税差异"),
            ("预扣预缴税额汇总", "本期应预扣预缴税额 SUM"),
        ]:
            if col in work.columns:
                summary_cols[name] = (col, "sum")

        if summary_cols:
            pivot = work.groupby(org_col).agg(**{
                name: (col, "sum") for name, (col, _) in summary_cols.items()
            }).reset_index()
            fpath = out / "个税汇总一览表.xls"
            pivot.to_excel(fpath, index=False)
            files.append(str(fpath))

    # ---- 人员信息变动汇总表（含入职/调岗/离职三类） ----
    changes = []
    if "机构代码_人员信息表" in work.columns:
        org_staff = work["机构代码_人员信息表"].fillna("").astype(str).str.strip()
        org_pay = work[org_col].fillna("").astype(str).str.strip()
        cert = work.get("证件号码", pd.Series("", index=work.index))
        cert = cert.fillna("").astype(str).str.strip()

        # 入职
        for _, row in work[cert == ""].iterrows():
            changes.append({
                "变动类型": "入职", "姓名": row.get("*姓名", ""),
                "原机构": "", "新机构": row.get(org_col, ""),
                "员工编号": row.get("员工编号", ""),
            })
        # 调岗
        diff_mask = (org_staff != "") & (org_pay != "") & (org_staff != org_pay)
        for _, row in work[diff_mask].iterrows():
            changes.append({
                "变动类型": "调岗", "姓名": row.get("*姓名", ""),
                "原机构": row.get("机构代码_人员信息表", ""),
                "新机构": row.get(org_col, ""),
                "员工编号": row.get("员工编号", ""),
            })

    # 离职：人员信息表（正常状态）有，但工资表没有的人
    # 复现原脚本 pd.merge(HRINFO, pt10, how='left') 找机构代码_y.isnull() 的逻辑
    if staff_df is not None and not staff_df.empty:
        staff_work = staff_df.copy()
        for col in ["员工编号", "*姓名", "机构代码"]:
            if col not in staff_work.columns:
                staff_work[col] = ""
        staff_work["员工编号"] = _normalize_emp_id(staff_work["员工编号"])
        staff_work["*姓名"] = staff_work["*姓名"].astype(str).str.strip()

        sheet_keys = pd.DataFrame({
            "员工编号": _normalize_emp_id(work.get("员工编号", pd.Series("", index=work.index))),
            "*姓名": work.get("*姓名", pd.Series("", index=work.index)).astype(str).str.strip(),
        }).drop_duplicates()

        staff_keys = staff_work[["员工编号", "*姓名", "机构代码"]].drop_duplicates(subset=["员工编号", "*姓名"])
        departed = staff_keys.merge(
            sheet_keys, on=["员工编号", "*姓名"], how="left", indicator=True
        )
        departed = departed[departed["_merge"] == "left_only"].drop(columns=["_merge"])

        for _, row in departed.iterrows():
            changes.append({
                "变动类型": "离职", "姓名": row.get("*姓名", ""),
                "原机构": row.get("机构代码", ""), "新机构": "",
                "员工编号": row.get("员工编号", ""),
            })

    if changes:
        changes_df = pd.DataFrame(changes)
        fpath = out / "人员信息变动汇总表.xlsx"
        changes_df.to_excel(fpath, index=False)
        files.append(str(fpath))

    return files
