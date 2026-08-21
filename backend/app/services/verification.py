# backend/app/services/verification.py
"""个税申报核心核对服务

复现 通用个税模板（网络版）260204.py 的核心逻辑：
1. build_working_sheet() — 构建底稿（大表）
2. verify() — 多维度核对底稿
3. check_all_clear() — 判断是否所有问题清零
"""
from __future__ import annotations

import calendar
import re
from pathlib import Path
from typing import Any

import pandas as pd

# ---- 机构代码映射（原脚本 dict_cpy） ----
ORG_CODE_MAP = {
    9001: 17001, 9002: 17002, 9003: 17003, 9004: 17004,
    9005: 17005, 9006: 17006, 9007: 17007, 9010: 17023,
    9012: 17010, 9013: 17013, 9014: 17014, 9015: 17015,
    9016: 17016, 9018: 17018, 9019: 17029, 9020: 17020,
    9021: 17021, 9025: 17025, 9028: 17028, 9030: 17030,
    7027: 17027,
}

# ---- 申报表输出列（原脚本 pt4 最终列序） ----
DECLARATION_COLUMNS = [
    "工号", "*姓名", "*证件类型", "*证件号码",
    "本期收入", "本期免税收入",
    "基本养老保险费", "基本医疗保险费", "失业保险费", "住房公积金",
    "累计子女教育", "累计继续教育", "累计住房贷款利息", "累计住房租金",
    "累计赡养老人", "累计3岁以下婴幼儿照护", "累计个人养老金",
    "企业(职业)年金", "商业健康保险", "税延养老保险",
    "公务交通费用", "通讯费用", "律师办案费用", "西藏附加减除费用",
    "其他", "准予扣除的捐赠额", "减免税额", "协定减免", "备注",
]

# ---- 专项扣除列 ----
DEDUCTION_COLUMNS = [
    "累计子女教育", "累计继续教育", "累计住房贷款利息",
    "累计住房租金", "累计赡养老人", "累计3岁以下婴幼儿照护",
    "累计个人养老金",
]

PAYROLL_RECONCILIATION_FIELDS = {
    "工资单_累计子女教育扣除": ("累计当月子女教育附加扣除", "累计子女教育附加扣除"),
    "工资单_累计继续教育扣除": ("累计当月继续教育附加扣除", "累计继续教育附加扣除"),
    "工资单_累计住房贷款利息扣除": ("累计当月住房贷款利息附加扣除", "累计住房贷款利息附加扣除"),
    "工资单_累计住房租金扣除": ("累计当月住房租金附加扣除", "累计住房租金附加扣除"),
    "工资单_累计赡养老人扣除": ("累计当月赡养老人附加扣除", "累计赡养老人附加扣除"),
    "工资单_累计婴幼儿照护扣除": ("累计当月婴幼儿照护费用附加扣除", "累计婴幼儿照护费用附加扣除"),
    "工资单_累计商业保险扣除": ("累计商业保险扣除",),
    "工资单_累计个人养老金": ("累计个人养老金",),
}

PAYROLL_ROLE_LABELS = {
    "rank_salary": "职级工资单",
    "marketing_salary": "营销工资单",
    "branch_salary": "机构工资单",
    "headquarters_salary": "总部工资单",
    "digital_ops_salary": "数字化运营工资单",
    "advisor_salary": "投顾工资单",
}

VERIFICATION_RULE_CONFIG = {
    "tax_diff_tolerance": 0.01,
    "blocking_codes": {
        "key_field_missing",
        "deduction_duplicates",
        "personnel_update_match_failed",
        "headcount_reconciliation_failed",
        "taxpayer_org_mapping",
        "invalid_resident_id",
        "duplicate_id_in_staff",
        "duplicate_id_in_change",
    },
    "warning_codes": {
        "personnel_changes",
        "tax_diff_within_tolerance",
        "deduction_missing_orgs",
        "deduction_low_confidence",
        "deduction_name_mismatch",
        "personnel_update_multiple_matches",
        "duplicate_addition",
        "invalid_org_code_format",
    },
}

EMPLOYEE_PAYROLL_FIELD_ALIASES = {
    "员工编号": ("员工编号", "员工编码", "人员编号", "工号"),
    "*姓名": ("*姓名", "姓名", "员工姓名", "员工姓名CN"),
    "机构代码": ("机构代码", "单位编号", "单位编码", "分支机构代码"),
    "应发工资": (
        "本期收入", "应发合计 SUM", "应发合计",
        "应发工资 I=A+B+C+D+E-F-G+H+J+K+A10",
        "应发工资 I=A+B+D-F-G9+K", "应发工资H=A+B+J",
        "应发工资H=A+B+E+I+J+K-A8",
    ),
    "福利费": ("福利费", "福利费用", "福利费 SUM"),
    "调增应纳税所得额": ("调增应纳税所得额 SUM", "调增应纳税所得额"),
    "本期免税收入": ("本期免税收入 SUM", "本期免税收入", "免税支出 SUM", "免税支出"),
    "基本养老保险费": ("基本养老保险费", "养老(个人部分)", "养老保险金的员工部分 SUM", "养老保险金的员工部分"),
    "基本医疗保险费": ("基本医疗保险费", "医疗(个人部分)", "医疗保险金的员工部分 SUM", "医疗保险金的员工部分"),
    "失业保险费": ("失业保险费", "失业(个人部分)", "失业保险金的员工部分 SUM", "失业保险金的员工部分"),
    "住房公积金": ("住房公积金", "公积金(个人部分)", "公积金（个人部分）", "住房公积金的员工部分 SUM", "住房公积金的员工部分"),
    "企业(职业)年金": ("企业(职业)年金", "企业年金(个人部分)", "企业年金（个人部分）", "企业年金的员工部分 SUM", "企业年金的员工部分"),
    "商业健康保险": ("商业健康保险", "商业保险扣除 SUM", "商业保险扣除", "累计商业保险扣除"),
    "本期应预扣预缴税额 SUM": ("本期应预扣预缴税额 SUM", "本期应预扣预缴税额"),
    "个人所得税 SUM": ("个人所得税 SUM", "个人所得税"),
}


class RetirementWelfareColumnSelectionError(ValueError):
    """Raised when a retirement welfare workbook needs a user-selected amount column."""

    def __init__(self, columns: list[str]):
        self.columns = columns
        super().__init__("退休福利表存在多个慰问金额列，请选择本次导入列")

PAYROLL_DEDUCTION_ALIASES = {
    "累计子女教育": ("累计子女教育", "累计当月子女教育附加扣除", "累计子女教育附加扣除"),
    "累计继续教育": ("累计继续教育", "累计当月继续教育附加扣除", "累计继续教育附加扣除"),
    "累计住房贷款利息": ("累计住房贷款利息", "累计当月住房贷款利息附加扣除", "累计住房贷款利息附加扣除"),
    "累计住房租金": ("累计住房租金", "累计当月住房租金附加扣除", "累计住房租金附加扣除"),
    "累计赡养老人": ("累计赡养老人", "累计当月赡养老人附加扣除", "累计赡养老人附加扣除"),
    "累计3岁以下婴幼儿照护": ("累计3岁以下婴幼儿照护", "累计当月婴幼儿照护费用附加扣除", "累计婴幼儿照护费用附加扣除"),
    "累计个人养老金": ("累计个人养老金",),
}

PERSONNEL_CHANGE_REQUIRED_FIELDS = {
    "入职": ["证件类型", "证件号码", "手机号码", "任职受雇从业日期"],
    "离职": ["证件号码", "离职日期"],
}


def normalize_org_code(value: Any) -> str:
    """复现原脚本 Plus_表头(x) 逻辑"""
    if value is None or pd.isna(value) or str(value).strip() == "":
        return ""
    text = str(value).strip()
    try:
        num = int(float(text))
    except ValueError:
        return text
    if num > 9000:
        num = ORG_CODE_MAP.get(num, num)
    else:
        num = num + 10000
    return str(num)[:5]


def _to_numeric(series: pd.Series) -> pd.Series:
    """安全转换数值列"""
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False),
        errors="coerce",
    ).fillna(0)


def _normalize_emp_id(series: pd.Series) -> pd.Series:
    """标准化员工编号：去空格，去 .0 后缀"""
    return series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)


def _key_text(value: Any) -> str:
    text = _clean_text(value)
    return "" if text.lower() == "nan" else text


def detect_employee_id_only_changes(payroll: pd.DataFrame, staff: pd.DataFrame) -> list[dict[str, str]]:
    payroll_org_col = "机构代码_工资单" if "机构代码_工资单" in payroll.columns else "机构代码"
    if payroll.empty or staff.empty or not {"*姓名", payroll_org_col, "员工编号"}.issubset(payroll.columns) or not {"*姓名", "机构代码", "员工编号"}.issubset(staff.columns):
        return []
    p = payroll.copy(); s = staff.copy()
    if "人员状态" in s.columns:
        s = s[s["人员状态"].map(_clean_text).isin(["", "正常", "在职"])].copy()
    for frame in (p, s):
        frame["_name"] = frame["*姓名"].map(_key_text)
        frame["_org"] = frame[(payroll_org_col if frame is p else "机构代码")].map(normalize_org_code)
        frame["_employee_id"] = _normalize_emp_id(frame["员工编号"])
    p = p[~p.duplicated(["_name", "_org"], keep=False)].set_index(["_name", "_org"])
    s = s[~s.duplicated(["_name", "_org"], keep=False)].set_index(["_name", "_org"])
    changes = []
    for key in p.index.intersection(s.index):
        prow, srow = p.loc[key], s.loc[key]
        old_id, new_id = _clean_text(srow.get("_employee_id")), _clean_text(prow.get("_employee_id"))
        if not old_id or not new_id or old_id == new_id:
            continue
        changes.append({
            "name": _clean_text(srow.get("*姓名")),
            "id_number": _normalize_id_number(srow.get("证件号码", "")),
            "org_code": normalize_org_code(srow.get("机构代码", "")),
            "old_employee_id": old_id,
            "new_employee_id": new_id,
            "message": f"仅员工编号变化，已由 {old_id} 自动更新为 {new_id}",
        })
    return changes


def _first_col(columns: list[str], *candidates: str) -> str | None:
    """在列名列表中查找第一个匹配的列"""
    for c in candidates:
        if c in columns:
            return c
    return None


def _copy_payroll_reconciliation_fields(result: pd.DataFrame, source: pd.DataFrame) -> None:
    columns = source.columns.tolist()
    for normalized, aliases in PAYROLL_RECONCILIATION_FIELDS.items():
        column = _first_col(columns, *aliases)
        result[normalized] = _to_numeric(source[column]) if column else 0


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _normalize_id_number(value: Any) -> str:
    return _clean_text(value).replace(" ", "").upper()


def _is_valid_resident_id(id_number: str) -> bool:
    text = _normalize_id_number(id_number)
    if not re.fullmatch(r"\d{17}[\dX]", text):
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    checks = "10X98765432"
    total = sum(int(text[i]) * weights[i] for i in range(17))
    return checks[total % 11] == text[-1]


def _missing_fields(row: pd.Series, fields: list[str]) -> list[str]:
    return [field for field in fields if _clean_text(row.get(field, "")) == ""]


def _normalize_taxpayer_id(value: Any) -> str:
    return "".join(_clean_text(value).split()).upper()


def _apply_payroll_org_mapping(
    result: pd.DataFrame,
    source: pd.DataFrame,
    columns: list[str],
    taxpayer_org_map: dict[str, str] | None,
    duplicate_taxpayer_ids: set[str] | None = None,
) -> None:
    taxpayer_col = _first_col(columns, "个税扣缴义务人纳税人识别号")
    taxpayer_ids = (
        source[taxpayer_col].map(_normalize_taxpayer_id)
        if taxpayer_col
        else pd.Series("", index=source.index, dtype=object)
    )
    result["个税扣缴义务人纳税人识别号"] = taxpayer_ids
    if "机构代码" not in result.columns:
        result["机构代码"] = ""
    result["机构代码"] = result["机构代码"].map(normalize_org_code)
    result["机构映射异常"] = ""
    if taxpayer_org_map is None:
        return

    valid_org = result["机构代码"].astype(str).str.fullmatch(r"\d{5}", na=False)
    needs_mapping = ~valid_org
    duplicate_ids = duplicate_taxpayer_ids or set()
    mapped = taxpayer_ids.map(taxpayer_org_map).fillna("")
    result.loc[needs_mapping & mapped.ne(""), "机构代码"] = mapped
    result.loc[needs_mapping & taxpayer_ids.eq(""), "机构映射异常"] = "工资单缺少个税扣缴义务人纳税人识别号"
    result.loc[needs_mapping & taxpayer_ids.isin(duplicate_ids), "机构映射异常"] = "机构名称维护表中该纳税人识别号存在重复"
    unknown = needs_mapping & taxpayer_ids.ne("") & mapped.eq("") & ~taxpayer_ids.isin(duplicate_ids)
    result.loc[unknown, "机构映射异常"] = "机构名称维护表中找不到该纳税人识别号"


def _read_employee_payroll(file_path: str) -> pd.DataFrame:
    first = pd.read_excel(file_path, dtype=str)
    markers = set(EMPLOYEE_PAYROLL_FIELD_ALIASES["员工编号"]) | {"所在部门"}
    if any(column in markers for column in first.columns):
        return first
    raw = pd.read_excel(file_path, header=None, dtype=str)
    for row_index, row in raw.iterrows():
        values = {_clean_text(value) for value in row.tolist()}
        if values.intersection(markers):
            return pd.read_excel(file_path, skiprows=int(row_index), dtype=str)
    return first


def load_retirement_welfare(
    file_path: str,
    selected_column: str = "",
) -> pd.DataFrame:
    """Read a retirement welfare workbook with a variable header row and amount label."""
    raw = pd.read_excel(file_path, header=None, dtype=object)
    header_index = None
    for index, row in raw.iterrows():
        values = [_clean_text(value) for value in row.tolist()]
        if any("姓名" in value for value in values) and any("机构段" in value for value in values):
            header_index = int(index)
            break
    if header_index is None:
        raise ValueError("退休福利表未找到同时包含姓名和机构段的表头")

    headers = [_clean_text(value) for value in raw.iloc[header_index].tolist()]
    welfare_columns = [header for header in headers if "慰问" in header]
    if not welfare_columns:
        raise ValueError("退休福利表未找到包含“慰问”的金额列")
    if not selected_column and len(welfare_columns) > 1:
        raise RetirementWelfareColumnSelectionError(welfare_columns)
    amount_column = selected_column or welfare_columns[0]
    if amount_column not in welfare_columns:
        raise ValueError("所选退休福利金额列不在当前上传表中")

    name_index = next(index for index, header in enumerate(headers) if "姓名" in header)
    org_index = next(index for index, header in enumerate(headers) if "机构段" in header)
    id_index = next(
        (index for index, header in enumerate(headers) if "身份证" in header or "证件号码" in header),
        None,
    )
    amount_index = headers.index(amount_column)
    records: list[dict[str, Any]] = []
    for _, row in raw.iloc[header_index + 1:].iterrows():
        name = _clean_text(row.iloc[name_index])
        org_code = normalize_org_code(row.iloc[org_index])
        id_number = _normalize_id_number(row.iloc[id_index]) if id_index is not None else ""
        amount = float(_to_numeric(pd.Series([row.iloc[amount_index]])).iloc[0])
        if not name or not org_code or amount == 0:
            continue
        records.append({
            "姓名": name,
            "机构代码": org_code,
            "慰问金额": amount,
            "慰问列": amount_column,
            "身份证号": id_number,
        })
    return pd.DataFrame(records, columns=["姓名", "机构代码", "慰问金额", "慰问列", "身份证号"])


def load_employee_payroll(
    file_path: str,
    taxpayer_org_map: dict[str, str] | None = None,
    duplicate_taxpayer_ids: set[str] | None = None,
) -> pd.DataFrame:
    """统一读取职级、营销及分支工资表，保留工资表专项扣除明细。"""
    source = _read_employee_payroll(file_path)
    columns = source.columns.tolist()
    result = pd.DataFrame(index=source.index)
    for target, aliases in EMPLOYEE_PAYROLL_FIELD_ALIASES.items():
        source_col = _first_col(columns, *aliases)
        if target == "*姓名":
            result[target] = source[source_col].map(_clean_text) if source_col else ""
        elif target == "员工编号":
            result[target] = _normalize_emp_id(source[source_col]) if source_col else ""
        elif target == "机构代码":
            result[target] = source[source_col].map(normalize_org_code) if source_col else ""
        else:
            result[target] = _to_numeric(source[source_col]) if source_col else 0
    _apply_payroll_org_mapping(result, source, columns, taxpayer_org_map, duplicate_taxpayer_ids)
    for target, aliases in PAYROLL_DEDUCTION_ALIASES.items():
        source_col = _first_col(columns, *aliases)
        result[target] = _to_numeric(source[source_col]) if source_col else 0
    annual_col = _first_col(columns, "年累计专项附加扣除金额", "年累计专项附加扣除")
    result["年累计专项附加扣除"] = _to_numeric(source[annual_col]) if annual_col else 0
    _copy_payroll_reconciliation_fields(result, source)
    return result.reset_index(drop=True)


# Compatibility for callers importing the historical names.


def load_marketing_style_payroll(
    file_path: str,
    taxpayer_org_map: dict[str, str] | None = None,
    duplicate_taxpayer_ids: set[str] | None = None,
) -> pd.DataFrame:
    """加载营销/机构/数字化/投顾类工资单。

    统一列名为标准名称。处理不同工资单的列名差异。
    """
    df = pd.read_excel(file_path, dtype={"员工编号": str})
    cols = df.columns.tolist()

    result = pd.DataFrame()

    # 员工编号 + 姓名
    emp_id_col = _first_col(cols, "员工编号")
    emp_name_col = _first_col(cols, "员工姓名", "员工姓名CN", "姓名")
    org_col = _first_col(cols, "单位编号", "单位编码")
    org_name_col = _first_col(cols, "单位名称", "单位名称CN")

    if emp_id_col:
        result["员工编号"] = _normalize_emp_id(df[emp_id_col])
    if emp_name_col:
        result["*姓名"] = df[emp_name_col].astype(str)
    if org_col:
        result["机构代码"] = df[org_col].astype(str).apply(normalize_org_code)
    if org_name_col:
        result["单位名称"] = df[org_name_col].astype(str)
    _apply_payroll_org_mapping(result, df, cols, taxpayer_org_map, duplicate_taxpayer_ids)

    # 应发工资（优先取调整后的）
    salary_col = _first_col(
        cols,
        "应发工资 I=A+B+C+D+E-F-G+H+J+K+A10",
        "应发工资 I=A+B+D-F-G9+K",
        "应发工资H=A+B+J",
        "应发工资H=A+B+E+I+J+K-A8",
    )
    if not salary_col:
        for c in cols:
            if "应发工资" in c and "调整前" not in c:
                salary_col = c
                break

    # 各项社保公积金
    housing_col = _first_col(cols, "公积金(个人部分)", "公积金（个人部分）")
    pension_col = _first_col(cols, "养老(个人部分)")
    medical_col = _first_col(cols, "医疗(个人部分)")
    unemployed_col = _first_col(cols, "失业(个人部分)")
    annuity_col = _first_col(cols, "企业年金(个人部分)", "企业年金（个人部分）")
    adjust_col = _first_col(cols, "调增应纳税所得额")
    annual_ded_col = _first_col(cols, "年累计专项附加扣除金额", "年累计专项附加扣除")
    tax_col = _first_col(cols, "个人所得税")

    result["应发工资"] = _to_numeric(df[salary_col]) if salary_col else 0
    result["住房公积金"] = _to_numeric(df[housing_col]) if housing_col else 0
    result["基本养老保险费"] = _to_numeric(df[pension_col]) if pension_col else 0
    result["基本医疗保险费"] = _to_numeric(df[medical_col]) if medical_col else 0
    result["失业保险费"] = _to_numeric(df[unemployed_col]) if unemployed_col else 0
    result["企业(职业)年金"] = _to_numeric(df[annuity_col]) if annuity_col else 0
    result["调增应纳税所得额"] = _to_numeric(df[adjust_col]) if adjust_col else 0
    result["年累计专项附加扣除"] = _to_numeric(df[annual_ded_col]) if annual_ded_col else 0
    result["个人所得税 SUM"] = _to_numeric(df[tax_col]) if tax_col else 0

    # 这些字段营销工资单通常没有
    result["本期应预扣预缴税额 SUM"] = 0
    result["本期免税收入"] = 0
    result["商业健康保险"] = 0

    _copy_payroll_reconciliation_fields(result, df)

    return result


def load_rank_payroll(
    file_path: str,
    taxpayer_org_map: dict[str, str] | None = None,
    duplicate_taxpayer_ids: set[str] | None = None,
) -> pd.DataFrame:
    """加载职级工资单。

    复现原脚本 L176-185：先查找 '所在部门' 位置判断是否有表头元数据行。
    """
    # 第一次读取：看看 '所在部门' 是否是列名
    df_first = pd.read_excel(file_path, dtype={"员工编号": str, "机构代码": str})
    cols = df_first.columns.tolist()

    if "所在部门" in cols:
        # '所在部门' 就是列名（表头），直接使用
        df = df_first
    else:
        # '所在部门' 不在列名中，可能是元数据行中的值
        # 先用 header=None 读取找到它
        raw = pd.read_excel(file_path, header=None, dtype=str)
        positions = raw[raw.eq("所在部门").any(axis=1)].index.tolist()
        skiprows = positions[0] + 1 if positions else 0
        df = pd.read_excel(
            file_path,
            dtype={"员工编号": str, "机构代码": str},
            skiprows=skiprows,
        )
        cols = df.columns.tolist()

    result = pd.DataFrame()

    emp_id_col = _first_col(cols, "员工编号")
    emp_name_col = _first_col(cols, "姓名", "员工姓名")
    dept_col = _first_col(cols, "所在部门")
    org_col = _first_col(cols, "机构代码")

    if emp_id_col:
        result["员工编号"] = _normalize_emp_id(df[emp_id_col])
    if emp_name_col:
        result["*姓名"] = df[emp_name_col].astype(str)
    if dept_col:
        result["所在部门"] = df[dept_col].astype(str)
    if org_col:
        result["机构代码"] = df[org_col].astype(str).apply(normalize_org_code)
    _apply_payroll_org_mapping(result, df, cols, taxpayer_org_map, duplicate_taxpayer_ids)

    salary_col = _first_col(cols, "应发合计 SUM", "应发合计")
    housing_col = _first_col(cols, "住房公积金的员工部分 SUM", "住房公积金的员工部分")
    pension_col = _first_col(cols, "养老保险金的员工部分 SUM", "养老保险金的员工部分")
    medical_col = _first_col(cols, "医疗保险金的员工部分 SUM", "医疗保险金的员工部分")
    unemployed_col = _first_col(cols, "失业保险金的员工部分 SUM", "失业保险金的员工部分")
    annuity_col = _first_col(cols, "企业年金的员工部分 SUM", "企业年金的员工部分")
    adjust_col = _first_col(cols, "调增应纳税所得额 SUM", "调增应纳税所得额")
    insurance_col = _first_col(cols, "商业保险扣除 SUM", "商业保险扣除", "累计商业保险扣除")
    withhold_col = _first_col(cols, "本期应预扣预缴税额 SUM", "本期应预扣预缴税额")
    tax_col = _first_col(cols, "个人所得税 SUM", "个人所得税")
    exempt_col = _first_col(cols, "免税支出 SUM", "免税支出")

    result["应发工资"] = _to_numeric(df[salary_col]) if salary_col else 0
    result["住房公积金"] = _to_numeric(df[housing_col]) if housing_col else 0
    result["基本养老保险费"] = _to_numeric(df[pension_col]) if pension_col else 0
    result["基本医疗保险费"] = _to_numeric(df[medical_col]) if medical_col else 0
    result["失业保险费"] = _to_numeric(df[unemployed_col]) if unemployed_col else 0
    result["企业(职业)年金"] = _to_numeric(df[annuity_col]) if annuity_col else 0
    result["调增应纳税所得额"] = _to_numeric(df[adjust_col]) if adjust_col else 0
    result["商业健康保险"] = _to_numeric(df[insurance_col]) if insurance_col else 0
    result["本期应预扣预缴税额 SUM"] = _to_numeric(df[withhold_col]) if withhold_col else 0
    result["个人所得税 SUM"] = _to_numeric(df[tax_col]) if tax_col else 0
    result["本期免税收入"] = _to_numeric(df[exempt_col]) if exempt_col else 0
    result["年累计专项附加扣除"] = 0

    _copy_payroll_reconciliation_fields(result, df)

    return result


def load_headquarters_payroll(
    file_path: str,
    taxpayer_org_map: dict[str, str] | None = None,
    duplicate_taxpayer_ids: set[str] | None = None,
) -> pd.DataFrame:
    """加载总部工资单，映射列名为标准名称。

    复现原脚本 L188-200。
    """
    df = pd.read_excel(file_path, dtype={"员工编号": str})
    cols = df.columns.tolist()

    result = pd.DataFrame()

    emp_id_col = _first_col(cols, "员工编号")
    emp_name_col = _first_col(cols, "姓名", "员工姓名")
    dept_col = _first_col(cols, "工资发放地", "所在部门")
    org_col = _first_col(cols, "机构代码")

    if emp_id_col:
        result["员工编号"] = _normalize_emp_id(df[emp_id_col])
    if emp_name_col:
        result["*姓名"] = df[emp_name_col].astype(str)
    if dept_col:
        result["所在部门"] = df[dept_col].astype(str)
    if org_col:
        result["机构代码"] = df[org_col].astype(str).apply(normalize_org_code)
    _apply_payroll_org_mapping(result, df, cols, taxpayer_org_map, duplicate_taxpayer_ids)

    salary_col = _first_col(cols, "本期收入", "应发合计 SUM")
    welfare_col = _first_col(cols, "福利费", "福利费用", "福利费 SUM")
    housing_col = _first_col(cols, "住房公积金的员工部分", "住房公积金的员工部分 SUM")
    pension_col = _first_col(cols, "养老保险金的员工部分", "养老保险金的员工部分 SUM")
    medical_col = _first_col(cols, "医疗保险金的员工部分", "医疗保险金的员工部分 SUM")
    unemployed_col = _first_col(cols, "失业保险金的员工部分", "失业保险金的员工部分 SUM")
    annuity_col = _first_col(cols, "企业年金的员工部分", "企业年金的员工部分 SUM")
    insurance_col = _first_col(cols, "累计商业保险扣除", "商业保险扣除 SUM", "商业保险扣除")
    tax_col = _first_col(cols, "个人所得税", "个人所得税 SUM")
    exempt_col = _first_col(cols, "免税支出", "免税支出 SUM")

    result["应发工资"] = _to_numeric(df[salary_col]) if salary_col else 0
    result["福利费"] = _to_numeric(df[welfare_col]) if welfare_col else 0
    result["住房公积金"] = _to_numeric(df[housing_col]) if housing_col else 0
    result["基本养老保险费"] = _to_numeric(df[pension_col]) if pension_col else 0
    result["基本医疗保险费"] = _to_numeric(df[medical_col]) if medical_col else 0
    result["失业保险费"] = _to_numeric(df[unemployed_col]) if unemployed_col else 0
    result["企业(职业)年金"] = _to_numeric(df[annuity_col]) if annuity_col else 0
    result["商业健康保险"] = _to_numeric(df[insurance_col]) if insurance_col else 0
    result["个人所得税 SUM"] = _to_numeric(df[tax_col]) if tax_col else 0
    result["本期免税收入"] = _to_numeric(df[exempt_col]) if exempt_col else 0
    result["本期应预扣预缴税额 SUM"] = 0
    result["调增应纳税所得额"] = 0
    result["年累计专项附加扣除"] = 0

    _copy_payroll_reconciliation_fields(result, df)

    return result


def load_deduction_files(folder_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """遍历专项附加扣除文件夹，合并所有文件。

    返回: (合并去重后的扣除数据, 重复人员列表)
    """
    folder = Path(folder_path)
    if not folder.exists():
        return pd.DataFrame(), pd.DataFrame()

    all_frames = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in (".xls", ".xlsx"):
            continue
        try:
            ff = pd.read_excel(f, dtype={"证件号码": str})
        except Exception:
            continue

        cols = ff.columns.tolist()
        name_col = _first_col(cols, "姓名", "*姓名")
        id_col = _first_col(cols, "证件号码")

        if not name_col or not id_col:
            continue

        row = pd.DataFrame()
        row["*姓名"] = ff[name_col].astype(str)
        row["证件号码"] = ff[id_col].map(_normalize_id_number)

        for target_col in DEDUCTION_COLUMNS:
            found = _first_col(cols, target_col)
            if found:
                row[target_col] = _to_numeric(ff[found])
            else:
                row[target_col] = 0

        row["文件名"] = f.name
        all_frames.append(row)

    if not all_frames:
        return pd.DataFrame(), pd.DataFrame()

    combined = pd.concat(all_frames, ignore_index=True)
    combined["*姓名"] = combined["*姓名"].map(_clean_text)
    combined["证件号码"] = combined["证件号码"].map(_normalize_id_number)

    # 检测重复人员
    dup_mask = combined.duplicated(subset=["证件号码", "*姓名"], keep=False)
    duplicates = combined[dup_mask].sort_values("*姓名").copy() if dup_mask.any() else pd.DataFrame()

    # 去重；保留来源文件名，便于追踪覆盖来源。
    combined = combined.drop_duplicates(subset=["证件号码", "*姓名"], keep="first")

    return combined, duplicates


def _is_masked_id_number(id_number: str) -> bool:
    return "*" in _normalize_id_number(id_number)


def _id_first_last(id_number: str) -> tuple[str, str]:
    value = _normalize_id_number(id_number)
    return value[:1], value[-1:]


def apply_deduction_matches(sheet: pd.DataFrame, deductions: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """带入专项附加扣除，并记录无法唯一识别的脱敏证件号码。

    优先按完整证件号码和姓名匹配。专项表证件号码脱敏时，按姓名和证件号码
    首尾匹配；只有一个工资人员候选时自动带入，多个候选时要求补录完整证件号码。
    """
    result = sheet.copy()
    quality = {"low_confidence": [], "name_mismatches": []}
    if deductions.empty or "证件号码" not in result.columns:
        return result, quality

    for column in DEDUCTION_COLUMNS:
        if column not in result.columns:
            result[column] = 0
    result["专项附加扣除匹配状态"] = ""
    result["专项附加扣除来源文件"] = ""

    payroll = result.copy()
    payroll["_id_key"] = payroll["证件号码"].map(_normalize_id_number)
    payroll["_name_key"] = payroll["*姓名"].map(_clean_text)

    ded = deductions.copy()
    ded["_id_key"] = ded["证件号码"].map(_normalize_id_number)
    ded["_name_key"] = ded["*姓名"].map(_clean_text)

    for _, deduction in ded.iterrows():
        id_key = deduction["_id_key"]
        name_key = deduction["_name_key"]
        if not id_key or not name_key:
            continue

        exact = payroll[(payroll["_id_key"] == id_key) & (payroll["_name_key"] == name_key)]
        if len(exact) == 1:
            target_index = exact.index[0]
        elif len(exact) > 1:
            quality["low_confidence"].append({
                "name": name_key,
                "id_number": id_key,
                "candidate_count": int(len(exact)),
                "candidate_names": "、".join(sorted(exact["*姓名"].map(_clean_text).unique().tolist())),
                "match_rule": "完整证件号码和姓名匹配到多条工资记录，未自动带入",
                "requires_confirmation": True,
            })
            continue
        else:
            same_id = payroll[payroll["_id_key"] == id_key]
            if not same_id.empty:
                quality["name_mismatches"].append({
                    "name": "、".join(sorted(same_id["*姓名"].map(_clean_text).unique().tolist())),
                    "id_number": id_key,
                    "deduction_names": name_key,
                    "org_code": "、".join(sorted(same_id.get("机构代码_工资单", pd.Series(dtype=str)).map(_clean_text).unique().tolist())),
                    "issue": "证件号码相同但姓名不一致",
                })
                continue

            if not _is_masked_id_number(id_key):
                continue

            first, last = _id_first_last(id_key)
            masked_candidates = payroll[
                (payroll["_name_key"] == name_key)
                & (payroll["_id_key"].str[:1] == first)
                & (payroll["_id_key"].str[-1:] == last)
            ]
            if len(masked_candidates) != 1:
                if not masked_candidates.empty:
                    quality["low_confidence"].append({
                        "name": name_key,
                        "id_number": id_key,
                        "candidate_count": int(len(masked_candidates)),
                        "candidate_names": "、".join(sorted(masked_candidates["*姓名"].map(_clean_text).unique().tolist())),
                        "candidate_id_numbers": "、".join(sorted(masked_candidates["_id_key"].unique().tolist())),
                        "match_rule": "姓名和证件号码首尾匹配到多名工资人员，未自动带入",
                        "message": "专项附加扣除表的证件号码已脱敏，姓名和证件号码首尾存在多个候选人。请录入完整证件号码后重新核对。",
                        "requires_confirmation": True,
                    })
                continue
            target_index = masked_candidates.index[0]

        for column in DEDUCTION_COLUMNS:
            result.at[target_index, column] = _to_numeric(pd.Series([deduction.get(column, 0)])).iat[0]
        result.at[target_index, "专项附加扣除匹配状态"] = "已匹配"
        result.at[target_index, "专项附加扣除来源文件"] = _clean_text(deduction.get("文件名", ""))

    return result, quality


def analyze_deduction_matches(sheet: pd.DataFrame, deductions: pd.DataFrame) -> dict:
    """返回专项附加扣除匹配质量报告，不修改调用方数据。"""
    _, quality = apply_deduction_matches(sheet, deductions)
    return quality


def build_working_sheet(
    payroll_files: list[tuple[str, str]],
    staff_info_path: str,
    deduction_folder: str,
    taxpayer_org_map: dict[str, str] | None = None,
    duplicate_taxpayer_ids: set[str] | None = None,
    retirement_welfare_path: str = "",
    retirement_welfare_column: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """构建完整底稿（大表）。返回 (sheet, staff_df)。"""
    # ---- 1. 加载人员信息表 ----
    staff = pd.read_excel(staff_info_path, dtype=str)
    staff_full = staff.copy()
    if "人员状态" in staff.columns:
        # 规范化取值：在职→正常、离职→非正常、空值→正常
        status = staff["人员状态"].astype(str).str.strip()
        status = status.replace({"在职": "正常", "离职": "非正常", "nan": "正常", "": "正常"})
        staff["人员状态"] = status
        staff_full["人员状态"] = status  # 同步到 full，供回退使用
        staff = staff[staff["人员状态"] == "正常"].copy()
        # 兜底：若正常人员为空（如取值全非标准），回退使用全量（排除明确"非正常"），
        # 避免离职检测整体失效（漏报比误报更严重）
        if staff.empty:
            staff = staff_full[staff_full["人员状态"] != "非正常"].copy()
            if staff.empty:
                staff = staff_full.copy()
    else:
        # 无"人员状态"列时，视为全部正常
        staff["人员状态"] = "正常"
        staff_full["人员状态"] = "正常"
    for frame in (staff, staff_full):
        for col in [
            "员工编号", "*姓名", "证件类型", "证件号码", "机构代码",
            "手机号码", "任职受雇从业日期", "离职日期",
        ]:
            if col not in frame.columns:
                frame[col] = ""
        frame["员工编号"] = _normalize_emp_id(frame["员工编号"])
        frame["*姓名"] = frame["*姓名"].map(_clean_text)
        frame["机构代码"] = frame["机构代码"].map(normalize_org_code)

    retirement_welfare = (
        load_retirement_welfare(retirement_welfare_path, retirement_welfare_column)
        if retirement_welfare_path else pd.DataFrame(columns=["姓名", "机构代码", "慰问金额", "慰问列"])
    )

    # ---- 2. 分类型加载工资单 ----
    all_frames = []
    for role, path in payroll_files:
        if not path:
            continue
        if role == "headquarters_salary":
            df = load_headquarters_payroll(path, taxpayer_org_map, duplicate_taxpayer_ids)
        else:
            df = load_employee_payroll(path, taxpayer_org_map, duplicate_taxpayer_ids)
        if not df.empty:
            df["工资单类型"] = PAYROLL_ROLE_LABELS.get(role, role)
            all_frames.append(df)

    if not all_frames:
        return pd.DataFrame()

    all_payroll = pd.concat(all_frames, ignore_index=True, join="outer")

    # 确保关键列存在
    for col in ["员工编号", "*姓名", "机构代码"]:
        if col not in all_payroll.columns:
            all_payroll[col] = ""

    # 去除非必要的 NaN 行 / 空行
    all_payroll = all_payroll.dropna(subset=["员工编号"])
    all_payroll = all_payroll[all_payroll["员工编号"].astype(str).str.strip() != ""]
    all_payroll = all_payroll[all_payroll["*姓名"].fillna("").astype(str).str.strip() != ""]
    all_payroll = all_payroll[all_payroll["*姓名"].astype(str).str.strip() != "nan"]

    retirement_reconciliation: list[dict[str, Any]] = []
    retirement_profiles: dict[str, dict[str, Any]] = {}
    if not retirement_welfare.empty:
        retirement_welfare = retirement_welfare.copy()
        retirement_welfare["_name_key"] = retirement_welfare["姓名"].map(_key_text)
        retirement_welfare["_org_key"] = retirement_welfare["机构代码"].map(normalize_org_code)
        retirement_welfare["身份证号"] = retirement_welfare["身份证号"].map(_normalize_id_number)

        full_lookup = {
            key: group for key, group in staff_full.groupby(
                [staff_full["*姓名"].map(_key_text), staff_full["机构代码"].map(normalize_org_code)], sort=False
            )
        }
        identity_lookup = {
            key: group for key, group in staff_full.groupby(
                [staff_full["机构代码"].map(normalize_org_code), staff_full["证件号码"].map(_normalize_id_number)], sort=False
            )
        }
        payroll = all_payroll.copy()
        payroll["_name_key"] = payroll["*姓名"].map(_key_text)
        payroll["_org_key"] = payroll["机构代码"].map(normalize_org_code)
        payroll["_employee_key"] = _normalize_emp_id(payroll["员工编号"])
        welfare_groups = {
            key: group for key, group in retirement_welfare.groupby(["_name_key", "_org_key"], sort=False)
        }
        synthetic_rows: list[dict[str, Any]] = []

        def append_reconciliation(
            welfare_row: pd.Series,
            *,
            payroll_exists: bool,
            personnel_status: str,
            match_method: str,
            payroll_taxable_adjustment: float,
            status: str,
            action: str,
            blocking: bool,
            id_number: str = "",
        ) -> None:
            retirement_reconciliation.append({
                "name": _key_text(welfare_row["姓名"]),
                "org_code": normalize_org_code(welfare_row["机构代码"]),
                "id_number": id_number or _normalize_id_number(welfare_row.get("身份证号", "")),
                "welfare_column": welfare_row["慰问列"],
                "welfare_amount": round(float(welfare_row["慰问金额"]), 2),
                "payroll_exists": payroll_exists,
                "personnel_status": personnel_status or "未找到",
                "match_method": match_method,
                "payroll_taxable_adjustment": round(payroll_taxable_adjustment, 2),
                "status": status,
                "action": action,
                "blocking": blocking,
            })

        for _, welfare_row in retirement_welfare.iterrows():
            name = welfare_row["_name_key"]
            org_code = welfare_row["_org_key"]
            id_number = _normalize_id_number(welfare_row["身份证号"])
            welfare_group = welfare_groups[(name, org_code)]
            duplicate_welfare_rows = len(welfare_group) > 1
            exact_duplicate_ready = (
                duplicate_welfare_rows
                and welfare_group["身份证号"].ne("").all()
                and welfare_group["身份证号"].nunique() == len(welfare_group)
            )
            if duplicate_welfare_rows and not exact_duplicate_ready:
                append_reconciliation(
                    welfare_row,
                    payroll_exists=False,
                    personnel_status="待确认",
                    match_method="机构+姓名（重复记录）",
                    payroll_taxable_adjustment=0,
                    status="重复退休记录待确认",
                    action="同机构同名退休记录存在相同或缺失身份证号，需人工确认后重新核对",
                    blocking=True,
                )
                continue

            if not duplicate_welfare_rows:
                payroll_rows = payroll[
                    (payroll["_name_key"].eq(name)) & (payroll["_org_key"].eq(org_code))
                ]
                if not payroll_rows.empty:
                    basic_matches = full_lookup.get((name, org_code), pd.DataFrame())
                    basic_profile = basic_matches.iloc[0].to_dict() if len(basic_matches) == 1 else {}
                    payroll_taxable_adjustment = float(payroll_rows["调增应纳税所得额"].sum())
                    status = "金额一致" if round(payroll_taxable_adjustment, 2) == round(float(welfare_row["慰问金额"]), 2) else "福利费待核对"
                    append_reconciliation(
                        welfare_row,
                        payroll_exists=True,
                        personnel_status=_clean_text(basic_profile.get("人员状态", "")),
                        match_method="机构+姓名",
                        payroll_taxable_adjustment=payroll_taxable_adjustment,
                        status=status,
                        action="本月工资已存在该人员，仅核对调增应纳税所得额，不新增工资或人员变动；待核对时请更正原工资表后重新核对",
                        blocking=False,
                        id_number=_normalize_id_number(basic_profile.get("证件号码", "")),
                    )
                    continue

            profile_matches = full_lookup.get((name, org_code), pd.DataFrame())
            match_method = "机构+姓名"
            if exact_duplicate_ready or (len(profile_matches) > 1 and id_number):
                identity_matches = identity_lookup.get((org_code, id_number), pd.DataFrame())
                identity_matches = identity_matches[
                    identity_matches["*姓名"].map(_key_text).eq(name)
                ]
                profile_matches = identity_matches
                match_method = "机构+身份证号"
            if len(profile_matches) > 1:
                append_reconciliation(
                    welfare_row,
                    payroll_exists=False,
                    personnel_status="待确认",
                    match_method=match_method,
                    payroll_taxable_adjustment=0,
                    status="人员信息待确认",
                    action="同机构同名人员不唯一，需补充身份证号或人工确认后重新核对",
                    blocking=True,
                    id_number=id_number,
                )
                continue

            profile: dict[str, Any] = profile_matches.iloc[0].to_dict() if len(profile_matches) == 1 else {}
            employee_id = _clean_text(profile.get("员工编号", ""))
            payroll_match_method = match_method
            if exact_duplicate_ready and employee_id:
                payroll_rows = payroll[payroll["_employee_key"].eq(employee_id)]
                payroll_match_method = "工资员工编号+身份证号"
            else:
                payroll_rows = payroll[(payroll["_name_key"].eq(name)) & (payroll["_org_key"].eq(org_code))]
            payroll_exists = not payroll_rows.empty
            personnel_status = _clean_text(profile.get("人员状态", ""))
            profile_id = _normalize_id_number(profile.get("证件号码", ""))
            resolved_id_number = id_number or profile_id

            if payroll_exists:
                payroll_taxable_adjustment = float(payroll_rows["调增应纳税所得额"].sum())
                status = "金额一致" if round(payroll_taxable_adjustment, 2) == round(float(welfare_row["慰问金额"]), 2) else "福利费待核对"
                append_reconciliation(
                    welfare_row,
                    payroll_exists=True,
                    personnel_status=personnel_status,
                    match_method=payroll_match_method,
                    payroll_taxable_adjustment=payroll_taxable_adjustment,
                    status=status,
                    action="本月工资已存在该人员，仅核对调增应纳税所得额，不新增工资或人员变动；待核对时请更正原工资表后重新核对",
                    blocking=False,
                    id_number=resolved_id_number,
                )
                continue

            profile_key = f"{name}|{org_code}|{resolved_id_number or employee_id or len(synthetic_rows)}"
            row = {column: 0 for column in all_payroll.columns}
            row.update({
                "员工编号": employee_id,
                "*姓名": name,
                "机构代码": org_code,
                "工资单类型": "退休福利工资单",
                "机构映射异常": "",
                "应发工资": float(welfare_row["慰问金额"]),
                "福利费": float(welfare_row["慰问金额"]),
                "退休福利标记": "是",
                "退休福利匹配键": profile_key,
            })
            synthetic_rows.append(row)
            retirement_profiles[profile_key] = {**profile, "证件号码": resolved_id_number}
            if personnel_status == "正常":
                status = "正常人员补入工资"
                action = "人员信息为正常且本月工资缺失，已补入退休福利工资，不作为离职处理"
                blocking = False
            elif profile:
                status = "非正常人员入职"
                action = "人员信息为非正常，已补入退休福利工资并作为本月入职处理"
                blocking = False
            else:
                status = "无人员信息待补"
                action = "人员信息表无记录，已补入退休福利工资并作为本月入职；资料不全时不可申报"
                blocking = True
            append_reconciliation(
                welfare_row,
                payroll_exists=False,
                personnel_status=personnel_status,
                match_method=match_method,
                payroll_taxable_adjustment=float(welfare_row["慰问金额"]),
                status=status,
                action=action,
                blocking=blocking,
                id_number=resolved_id_number,
            )
        if synthetic_rows:
            all_payroll = pd.concat([all_payroll, pd.DataFrame(synthetic_rows)], ignore_index=True, sort=False)

    # 填充数值列为0
    numeric_cols = [
        "应发工资", "住房公积金", "基本养老保险费", "基本医疗保险费",
        "失业保险费", "企业(职业)年金", "调增应纳税所得额",
        "商业健康保险", "本期应预扣预缴税额 SUM", "个人所得税 SUM",
        "本期免税收入", "福利费",
    ]
    for col in numeric_cols:
        if col in all_payroll.columns:
            all_payroll[col] = all_payroll[col].fillna(0)

    # ---- 3. 计算本期收入 = 应发工资 + 调增应纳税所得额 ----
    all_payroll["本期收入"] = (
        all_payroll.get("应发工资", 0) + all_payroll.get("调增应纳税所得额", 0)
    )

    # ---- 4. 计算个税差异 ----
    all_payroll["个税差异"] = (
        all_payroll.get("本期应预扣预缴税额 SUM", 0) - all_payroll.get("个人所得税 SUM", 0)
    )

    # ---- 5. 关联人员信息表（right join = 以工资表为准） ----
    sheet = all_payroll.merge(
        staff[["员工编号", "*姓名", "证件类型", "证件号码", "机构代码",
               "手机号码", "任职受雇从业日期", "离职日期"]],
        on=["员工编号", "*姓名"],
        how="left",
        suffixes=("_工资单", "_人员信息表"),
    )

    # 工资单里有些人员员工编号为空，但人员信息表中用 0 表示。
    # 这种场景按姓名 + 工资单机构做唯一兜底匹配，避免误报入职/离职。
    if "机构代码_人员信息表" in sheet.columns and "机构代码_工资单" in sheet.columns:
        staff_lookup_cols = [
            "*姓名", "证件类型", "证件号码", "机构代码",
            "手机号码", "任职受雇从业日期", "离职日期",
        ]
        staff_lookup = staff[staff_lookup_cols].copy()
        staff_lookup["_name_key"] = staff_lookup["*姓名"].map(_key_text)
        staff_lookup["_org_key"] = staff_lookup["机构代码"].map(_key_text)
        unique_staff_lookup = staff_lookup[
            ~staff_lookup.duplicated(subset=["_name_key", "_org_key"], keep=False)
        ].set_index(["_name_key", "_org_key"])

        unmatched = sheet["机构代码_人员信息表"].fillna("").astype(str).str.strip() == ""
        for idx in sheet[unmatched].index:
            lookup_key = (
                _key_text(sheet.at[idx, "*姓名"]),
                _key_text(sheet.at[idx, "机构代码_工资单"]),
            )
            if lookup_key not in unique_staff_lookup.index:
                continue
            matched_staff = unique_staff_lookup.loc[lookup_key]
            sheet.at[idx, "证件类型"] = matched_staff.get("证件类型", "")
            sheet.at[idx, "证件号码"] = matched_staff.get("证件号码", "")
            sheet.at[idx, "机构代码_人员信息表"] = matched_staff.get("机构代码", "")
            for col in ["手机号码", "任职受雇从业日期", "离职日期"]:
                if col in sheet.columns:
                    sheet.at[idx, col] = matched_staff.get(col, "")

    if "退休福利标记" in sheet.columns:
        for idx in sheet[sheet["退休福利标记"].fillna("").eq("是")].index:
            profile_key = _clean_text(sheet.at[idx, "退休福利匹配键"])
            profile = retirement_profiles.get(profile_key)
            if not profile:
                continue
            for field in ["证件类型", "证件号码", "手机号码", "任职受雇从业日期", "离职日期"]:
                if field in sheet.columns and _clean_text(sheet.at[idx, field]) == "":
                    sheet.at[idx, field] = profile.get(field, "")

    # ---- 6. 关联专项附加扣除（完整证件号优先；脱敏号码按姓名和首尾唯一匹配）----
    deductions, _ = load_deduction_files(deduction_folder)
    if not deductions.empty and "证件号码" in sheet.columns:
        sheet["证件号码"] = sheet["证件号码"].map(_normalize_id_number)
        sheet, deduction_match_quality = apply_deduction_matches(sheet, deductions)
        sheet.attrs["deduction_match_quality"] = deduction_match_quality
    else:
        sheet.attrs["deduction_match_quality"] = {"low_confidence": [], "name_mismatches": []}

    # ---- 7. 填充缺失列 ----
    for col in DEDUCTION_COLUMNS:
        if col not in sheet.columns:
            sheet[col] = 0

    for col in DECLARATION_COLUMNS:
        if col not in sheet.columns:
            sheet[col] = "" if col in ("工号", "*姓名", "*证件类型", "*证件号码", "备注") else 0

    if "员工编号" in sheet.columns:
        sheet["工号"] = sheet["员工编号"]

    # 确保证件信息列
    for col in ["*证件类型", "*证件号码", "证件类型", "证件号码"]:
        if col not in sheet.columns:
            sheet[col] = ""

    # 复现旧脚本 L478-479: rename 证件类型→*证件类型, 证件号码→*证件号码
    # 申报表需要带 * 前缀的列，需从无 * 的源列填充
    if "证件类型" in sheet.columns:
        mask = sheet["*证件类型"].fillna("").astype(str).str.strip() == ""
        sheet.loc[mask, "*证件类型"] = sheet.loc[mask, "证件类型"]
    if "证件号码" in sheet.columns:
        mask = sheet["*证件号码"].fillna("").astype(str).str.strip() == ""
        sheet.loc[mask, "*证件号码"] = sheet.loc[mask, "证件号码"]

    # 工号保留为字符串，避免前导零丢失 / 科学计数法
    if "工号" in sheet.columns:
        sheet["工号"] = sheet["工号"].astype(str).str.replace(r"\.0$", "", regex=True).fillna("")
    if "员工编号" in sheet.columns:
        sheet["员工编号"] = sheet["员工编号"].astype(str).str.replace(r"\.0$", "", regex=True).fillna("")

    sheet.attrs["retirement_welfare"] = sorted(
        retirement_reconciliation,
        key=lambda item: (item["status"] != "福利费待核对", item["name"], item["org_code"]),
    )
    return sheet, staff


# ============================================================
# 核对函数
# ============================================================

def check_tax_diff(sheet: pd.DataFrame) -> dict:
    """检查个税差异。复现原脚本 L337-347。"""
    if "个税差异" not in sheet.columns:
        return {"has_issues": False, "items": [], "by_org": []}

    diff_mask = (sheet["个税差异"] != 0)
    if "本期应预扣预缴税额 SUM" in sheet.columns:
        diff_mask = diff_mask & (sheet["本期应预扣预缴税额 SUM"] != 0)

    diff_rows = sheet[diff_mask].copy()
    items = []
    for _, row in diff_rows.iterrows():
        items.append({
            "name": str(row.get("*姓名", "")),
            "org_code": str(row.get("机构代码_工资单", row.get("机构代码", ""))),
            "id_number": str(row.get("证件号码", "")),
            "payroll_tax": round(float(row.get("本期应预扣预缴税额 SUM", 0)), 2),
            "declared_tax": round(float(row.get("个人所得税 SUM", 0)), 2),
            "diff": round(float(row.get("个税差异", 0)), 2),
        })

    return {
        "has_issues": len(items) > 0,
        "items": items,
        "by_org": [],
    }


PERSONNEL_REQUIRED_FIELDS = {
    "入职": ["证件类型", "证件号码", "手机号码", "员工编号", "任职受雇从业日期"],
    "离职": ["证件号码", "员工编号", "离职日期"],
    "调岗": ["证件号码", "员工编号", "离职日期", "任职受雇从业日期"],
}


def _previous_month_last_day(year: int | None, month: int | None) -> str:
    if not year or not month:
        return ""
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    last_day = calendar.monthrange(prev_year, prev_month)[1]
    return f"{prev_year}/{prev_month:02d}/{last_day:02d}"


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _missing_fields(row: pd.Series | dict, required: list[str]) -> list[str]:
    missing = []
    for field in required:
        if _clean_text(row.get(field, "")) == "":
            missing.append(field)
    return missing


def _item_required_values(item: dict) -> dict:
    return {
        "证件类型": item.get("cert_type", ""),
        "证件号码": item.get("id_number", ""),
        "手机号码": item.get("phone", ""),
        "员工编号": item.get("employee_id", ""),
        "任职受雇从业日期": item.get("hire_date", ""),
        "离职日期": item.get("leave_date", ""),
    }


def _recheck_personnel_item(item: dict) -> None:
    required = PERSONNEL_REQUIRED_FIELDS.get(item.get("change_type"), [])
    item["missing_fields"] = _missing_fields(_item_required_values(item), required)
    item["can_confirm"] = len(item["missing_fields"]) == 0
    if item["missing_fields"]:
        item["action_required"] = "信息不完整，请下载/导入人员信息变动表-雇员补齐后再确认"
    else:
        item["action_required"] = "信息完整，可线上确认"


def _make_personnel_item(
    change_type: str,
    row: pd.Series | dict,
    org_from: str = "",
    org_to: str = "",
    year: int | None = None,
    month: int | None = None,
) -> dict:
    cert_type = _clean_text(row.get("证件类型", row.get("*证件类型", "")))
    id_number = _clean_text(row.get("证件号码", row.get("*证件号码", "")))
    employee_id = _clean_text(row.get("员工编号", row.get("工号", "")))
    phone = _clean_text(row.get("手机号码", ""))
    hire_date = _clean_text(row.get("任职受雇从业日期", ""))
    leave_date = _clean_text(row.get("离职日期", ""))

    if change_type in {"离职", "调岗"} and not leave_date:
        leave_date = _previous_month_last_day(year, month)

    item = {
        "name": _clean_text(row.get("*姓名", row.get("姓名", ""))),
        "change_type": change_type,
        "org_code_from": _clean_text(org_from),
        "org_code_to": _clean_text(org_to),
        "cert_type": cert_type,
        "id_number": id_number,
        "employee_id": employee_id,
        "phone": phone,
        "hire_date": hire_date,
        "leave_date": leave_date,
        "missing_fields": [],
        "can_confirm": False,
        "action_required": "",
        "is_transfer_like": False,
    }
    _recheck_personnel_item(item)
    return item


def _is_personnel_change_confirmed(item: dict, confirmed_personnel: list | None) -> bool:
    if not confirmed_personnel:
        return False
    if item.get("missing_fields"):
        return False
    item_name = _clean_text(item.get("name"))
    item_id = _clean_text(item.get("id_number"))
    item_type = _clean_text(item.get("change_type"))
    item_transfer = bool(item.get("is_transfer_like"))
    for confirmed in confirmed_personnel:
        if not confirmed.get("confirmed", True) or not confirmed.get("applied", False):
            continue
        if _clean_text(confirmed.get("name")) != item_name:
            continue
        confirmed_transfer = bool(confirmed.get("is_transfer_like"))
        confirmed_type = _clean_text(confirmed.get("change_type"))
        confirmed_id = _clean_text(confirmed.get("id_number"))
        if item_transfer and confirmed_transfer:
            return True
        # 要求 item_id 非空才允许 confirmed 过滤，避免证件号码缺失的项被误过滤
        if item_type == "离职" and confirmed_transfer and item_id and confirmed_id == item_id:
            return True
        if confirmed_type == item_type and item_id and confirmed_id == item_id:
            return True
    return False


def _enrich_transfer_like_changes(items: list[dict], year: int | None = None, month: int | None = None) -> None:
    departed_by_name: dict[str, dict | None] = {}
    for item in items:
        if item.get("change_type") != "离职":
            continue
        name = _clean_text(item.get("name"))
        if not name:
            continue
        departed_by_name[name] = None if name in departed_by_name else item

    default_hire_date = f"{year}/{month:02d}/01" if year and month else ""
    for item in items:
        if item.get("change_type") != "入职":
            continue
        departed = departed_by_name.get(_clean_text(item.get("name")))
        if not departed:
            continue
        if not _clean_text(item.get("id_number")):
            item["id_number"] = _clean_text(departed.get("id_number"))
        if not _clean_text(item.get("employee_id")):
            item["employee_id"] = _clean_text(departed.get("employee_id"))
        if not _clean_text(item.get("phone")):
            item["phone"] = _clean_text(departed.get("phone"))
        if not _clean_text(item.get("hire_date")) and default_hire_date:
            item["hire_date"] = default_hire_date
        item["leave_date"] = ""
        if not _clean_text(item.get("cert_type")) and _clean_text(item.get("id_number")):
            item["cert_type"] = "居民身份证"
        item["is_transfer_like"] = True
        _recheck_personnel_item(item)
        item["action_required"] = "疑似变动单位，已沿用原人员身份证号、员工编号等信息，可线上确认或下载雇员表确认"


def check_personnel_changes(
    sheet: pd.DataFrame,
    confirmed_personnel: list | None = None,
    staff_df: pd.DataFrame | None = None,
    year: int = 2025,
    month: int = 1,
) -> dict:
    """检测人员变动：入职 / 离职 / 调岗。"""
    items = []

    org_staff = sheet.get("机构代码_人员信息表", pd.Series("", index=sheet.index))
    org_staff = org_staff.fillna("").astype(str).map(normalize_org_code).str.strip()
    org_payroll = sheet.get("机构代码_工资单", pd.Series("", index=sheet.index))
    org_payroll = org_payroll.fillna("").astype(str).map(normalize_org_code).str.strip()

    # 入职：工资表有，人员信息表没有匹配到员工。
    new_hire_mask = org_staff == ""
    for _, row in sheet[new_hire_mask].iterrows():
        item = _make_personnel_item(
            "入职",
            row,
            "",
            str(row.get("机构代码_工资单", row.get("机构代码", ""))),
            year,
            month,
        )
        items.append(item)

    # 申报机构变动：人员信息表机构与工资单机构都存在，但机构代码不一致。
    # 业务上要落成两条人员变动：原机构非正常 + 新机构正常。
    has_both = (org_staff != "") & (org_payroll != "")
    different = has_both & (org_staff != org_payroll)
    for _, row in sheet[different].iterrows():
        org_from = normalize_org_code(row.get("机构代码_人员信息表", ""))
        org_to = normalize_org_code(row.get("机构代码_工资单", row.get("机构代码", "")))
        departure = _make_personnel_item("离职", row, org_from, "", year, month)
        departure["is_transfer_like"] = True
        departure["action_required"] = "申报机构变动：需在原机构办理非正常"
        hire = _make_personnel_item("入职", row, "", org_to, year, month)
        hire["is_transfer_like"] = True
        hire["hire_date"] = f"{year}/{month:02d}/01"
        hire["leave_date"] = ""
        _recheck_personnel_item(hire)
        hire["action_required"] = "申报机构变动：需在新机构办理正常入职"
        items.extend([departure, hire])

    # 离职：人员信息表正常人员左连接工资单，工资单无匹配 → 离职
    # 复现旧脚本 260204.py L332-353:
    #   pt10 = pd.merge(HRINFO, pt10, how='left', on=['*姓名','员工编号'])
    #   filtered_pt10 = pt10[pt10['机构代码_y'].isnull()]
    if staff_df is not None and not staff_df.empty:
        staff_normal = (
            staff_df[staff_df["人员状态"].astype(str).str.strip() == "正常"].copy()
            if "人员状态" in staff_df.columns
            else staff_df.copy()
        )
        if "员工编号" in staff_normal.columns and "员工编号" in sheet.columns:
            # 员工编号已在 build_working_sheet 中规范化，此处保持一致
            staff_normal["员工编号"] = _normalize_emp_id(staff_normal["员工编号"])
            # 工资单中的(员工编号, 姓名)键集合 —— 左连接后无匹配即为离职
            payroll_keys = sheet[["员工编号", "*姓名"]].drop_duplicates()
            departed = staff_normal.merge(
                payroll_keys, on=["员工编号", "*姓名"], how="left", indicator=True
            )
            departed = departed[departed["_merge"] == "left_only"].drop(columns=["_merge"])
            for _, row in departed.iterrows():
                items.append(_make_personnel_item(
                    "离职", row,
                    str(row.get("机构代码", "")), "",
                    year, month,
                ))

    _enrich_transfer_like_changes(items, year, month)
    visible_items = [
        item for item in items
        if not _is_personnel_change_confirmed(item, confirmed_personnel)
    ]

    return {
        "has_issues": len(visible_items) > 0,
        "items": visible_items,
    }


def check_missing_cert(sheet: pd.DataFrame) -> dict:
    """检查证件信息缺失。"""
    cert_values = sheet.get("证件号码", pd.Series("", index=sheet.index))
    cert_values = cert_values.fillna("").astype(str).str.strip()
    missing_mask = cert_values == ""
    if "机构代码_人员信息表" in sheet.columns:
        matched_staff = sheet["机构代码_人员信息表"].fillna("").astype(str).str.strip() != ""
        missing_mask = missing_mask & matched_staff
    missing = sheet[missing_mask].copy()

    items = []
    for _, row in missing.iterrows():
        items.append({
            "name": str(row.get("*姓名", "")),
            "org_code": str(row.get("机构代码_工资单", row.get("机构代码", ""))),
            "employee_id": str(row.get("员工编号", "")),
        })

    return {
        "has_issues": len(items) > 0,
        "items": items,
    }


def check_deduction_issues(deduction_folder: str) -> dict:
    """检查专项附加扣除重复人员。"""
    _, duplicates = load_deduction_files(deduction_folder)

    dup_items = []
    if not duplicates.empty:
        for (name, id_number), group in duplicates.groupby(["*姓名", "证件号码"], dropna=False):
            details = []
            for _, row in group.iterrows():
                amounts = [
                    f"{column.replace('累计', '')} {float(row.get(column, 0) or 0):.2f}"
                    for column in DEDUCTION_COLUMNS
                    if float(row.get(column, 0) or 0) != 0
                ]
                details.append({
                    "file_name": str(row.get("文件名", "")),
                    "deduction_summary": "；".join(amounts) or "各专项扣除均为 0",
                })
            dup_items.append({
                "name": str(name),
                "id_number": str(id_number),
                "file_count": int(len(group)),
                "file_names": "、".join(detail["file_name"] for detail in details),
                "details": details,
            })

    return {
        "has_issues": len(dup_items) > 0,
        "duplicates": dup_items,
        "missing_orgs": [],
    }


def check_payroll_org_format(sheet: pd.DataFrame) -> dict:
    """检查工资人员归属机构代码，必须为 5 位数字。"""
    org_col = "机构代码_工资单" if "机构代码_工资单" in sheet.columns else "机构代码"
    if org_col not in sheet.columns:
        return {"has_issues": False, "items": []}
    items = []
    for _, row in sheet.iterrows():
        org_code = _clean_text(row.get(org_col, ""))
        if org_code and re.fullmatch(r"\d{5}", org_code):
            continue
        items.append({
            "payroll_type": _clean_text(row.get("工资单类型", "")),
            "name": _clean_text(row.get("*姓名", "")),
            "employee_id": _clean_text(row.get("员工编号", "")),
            "org_code": org_code,
            "message": "工资人员归属机构代码必须为 5 位数字",
        })
    return {"has_issues": bool(items), "items": items}


def check_taxpayer_org_mapping(sheet: pd.DataFrame) -> dict:
    if "机构映射异常" not in sheet.columns:
        return {"has_issues": False, "items": []}
    items = []
    for _, row in sheet[sheet["机构映射异常"].fillna("").astype(str).str.strip().ne("")].iterrows():
        items.append({
            "payroll_type": _clean_text(row.get("工资单类型", "")),
            "name": _clean_text(row.get("*姓名", "")),
            "employee_id": _clean_text(row.get("员工编号", "")),
            "taxpayer_id": _clean_text(row.get("个税扣缴义务人纳税人识别号", "")),
            "message": _clean_text(row.get("机构映射异常", "")),
        })
    return {"has_issues": bool(items), "items": items}


def check_deduction_coverage(sheet: pd.DataFrame) -> list[str]:
    """只报告没有任何独立扣除文件匹配记录的机构。"""
    org_col = "机构代码_工资单" if "机构代码_工资单" in sheet.columns else "机构代码"
    if org_col not in sheet.columns or "专项附加扣除匹配状态" not in sheet.columns:
        return []
    missing = []
    for org_code, group in sheet.groupby(org_col, dropna=False):
        if not group["专项附加扣除匹配状态"].eq("已匹配").any():
            value = _clean_text(org_code)
            if value:
                missing.append(value)
    return missing


def check_data_quality(
    staff_df: pd.DataFrame | None = None,
    change_df: pd.DataFrame | None = None,
    valid_org_codes: set[str] | None = None,
) -> dict:
    """基础数据质量前置校验。"""
    issues: list[dict] = []

    def scan_ids(df: pd.DataFrame, source: str) -> None:
        if df is None or df.empty or "证件号码" not in df.columns:
            return
        name_col = "*姓名" if "*姓名" in df.columns else "姓名"
        cert_type_col = "证件类型" if "证件类型" in df.columns else "*证件类型"
        for idx, row in df.iterrows():
            cert_type = _clean_text(row.get(cert_type_col, ""))
            id_number = _normalize_id_number(row.get("证件号码", row.get("*证件号码", "")))
            if not id_number:
                continue
            if cert_type in {"居民身份证", "身份证", ""} and len(id_number) == 18 and not _is_valid_resident_id(id_number):
                issues.append({
                    "source": source,
                    "issue_code": "invalid_resident_id",
                    "severity": "blocking",
                    "row_number": int(idx + 2),
                    "name": _clean_text(row.get(name_col, "")),
                    "id_number": id_number,
                    "message": "居民身份证校验位不通过",
                })
            elif cert_type not in {"居民身份证", "身份证"} and len(id_number) < 5:
                issues.append({
                    "source": source,
                    "issue_code": "suspicious_non_resident_id",
                    "severity": "warning",
                    "row_number": int(idx + 2),
                    "name": _clean_text(row.get(name_col, "")),
                    "id_number": id_number,
                    "message": "非居民身份证证件号码长度偏短，请确认",
                })

        duplicate_frame = df
        if "人员状态" in df.columns:
            duplicate_frame = df[df["人员状态"].map(_clean_text).isin(["", "正常", "在职"])]
        dup_mask = duplicate_frame["证件号码"].map(_normalize_id_number).duplicated(keep=False)
        for idx, row in duplicate_frame[dup_mask].iterrows():
            issues.append({
                "source": source,
                "issue_code": "duplicate_id_in_staff" if source == "人员信息表" else "duplicate_id_in_change",
                "severity": "blocking",
                "row_number": int(idx + 2),
                "name": _clean_text(row.get(name_col, "")),
                "id_number": _normalize_id_number(row.get("证件号码", "")),
                "message": f"{source}内证件号码重复",
            })

    def scan_orgs(df: pd.DataFrame, source: str) -> None:
        if df is None or df.empty:
            return
        candidates = ["机构代码", "机构代码(人员信息表)", "机构代码(工资单)", "机构代码_工资单", "机构代码_人员信息表"]
        for col in [c for c in candidates if c in df.columns]:
            for idx, value in df[col].items():
                org = _clean_text(value)
                if not org:
                    continue
                if not re.fullmatch(r"\d{5}", org):
                    issues.append({
                        "source": source,
                        "issue_code": "invalid_org_code_format",
                        "severity": "warning",
                        "row_number": int(idx + 2),
                        "org_code": org,
                        "message": f"{col} 格式不是 5 位数字",
                    })
                elif valid_org_codes and org not in valid_org_codes:
                    issues.append({
                        "source": source,
                        "issue_code": "invalid_org_code",
                        "severity": "blocking",
                        "row_number": int(idx + 2),
                        "org_code": org,
                        "message": f"{col} 不在有效机构代码清单内",
                    })

    if staff_df is not None:
        scan_ids(staff_df, "人员信息表")
        scan_orgs(staff_df, "人员信息表")
    if change_df is not None:
        scan_ids(change_df, "人员信息变动表")
        scan_orgs(change_df, "人员信息变动表")

    return {"has_issues": bool(issues), "items": issues}


def build_reconciliation_report(report: dict) -> dict[str, pd.DataFrame]:
    """统一核对报告工作簿结构。"""
    personnel_items = report["personnel_changes"]["items"]
    new_items = [item for item in personnel_items if item.get("change_type") == "入职" and not item.get("is_transfer_like")]
    leaver_items = [item for item in personnel_items if item.get("change_type") == "离职"]
    transfer_items = [
        item for item in personnel_items
        if item.get("change_type") == "调岗" or item.get("is_transfer_like")
    ]
    tax_items = report["tax_diff"]["items"]
    tolerance = report.get("config", {}).get("tax_diff_tolerance", VERIFICATION_RULE_CONFIG["tax_diff_tolerance"])

    summary_rows = [
        {"项目": "本期人数", "数量": report["summary"].get("total_employees", 0), "分级": "信息", "是否阻断": False},
        {"项目": "新增人员候选", "数量": len(new_items), "分级": "提醒项", "是否阻断": False},
        {"项目": "离职人员候选", "数量": len(leaver_items), "分级": "提醒项", "是否阻断": False},
        {"项目": "机构变动候选", "数量": len(transfer_items), "分级": "提醒项", "是否阻断": False},
        {"项目": "关键字段缺失", "数量": len(report.get("key_field_missing", {}).get("items", [])), "分级": "阻断项", "是否阻断": bool(report.get("key_field_missing", {}).get("items", []))},
        {"项目": "工资机构代码格式", "数量": len(report.get("payroll_org_format", {}).get("items", [])), "分级": "阻断项", "是否阻断": bool(report.get("payroll_org_format", {}).get("items", []))},
        {"项目": "工资机构纳税人识别号映射", "数量": len(report.get("taxpayer_org_mapping", {}).get("items", [])), "分级": "阻断项", "是否阻断": bool(report.get("taxpayer_org_mapping", {}).get("items", []))},
        {"项目": "个税差异", "数量": len(tax_items), "分级": "阻断项", "是否阻断": bool(tax_items)},
        {"项目": "专项附加扣除重复", "数量": len(report["deduction_warnings"]["duplicates"]), "分级": "阻断项", "是否阻断": bool(report["deduction_warnings"]["duplicates"])},
        {"项目": "专项附加扣除机构遗漏", "数量": len(report["deduction_warnings"]["missing_orgs"]), "分级": "提醒项", "是否阻断": False},
        {"项目": "专项附加扣除低置信度匹配", "数量": len(report.get("deduction_match_quality", {}).get("low_confidence", [])), "分级": "提醒项", "是否阻断": False},
        {"项目": "非正常人员匹配失败", "数量": len(report.get("personnel_update_issues", {}).get("match_failures", [])), "分级": "阻断项", "是否阻断": bool(report.get("personnel_update_issues", {}).get("match_failures", []))},
        {"项目": "新增人员疑似重复", "数量": len(report.get("personnel_update_issues", {}).get("duplicate_additions", [])), "分级": "提醒项", "是否阻断": False},
        {"项目": "数据质量问题", "数量": len(report.get("data_quality", {}).get("items", [])), "分级": "阻断/提醒", "是否阻断": any(item.get("severity") == "blocking" for item in report.get("data_quality", {}).get("items", []))},
        {"项目": "人数对账异常", "数量": len(report.get("headcount_reconciliation", {}).get("items", [])), "分级": "阻断项", "是否阻断": bool(report.get("headcount_reconciliation", {}).get("items", []))},
        {"项目": "退休福利慰问核对", "数量": len(report.get("retirement_welfare", {}).get("items", [])), "分级": "提示/阻断", "是否阻断": any(item.get("blocking") for item in report.get("retirement_welfare", {}).get("items", []))},
    ]

    tax_rows = []
    for item in tax_items:
        row = dict(item)
        row["容差"] = tolerance
        row["是否超容差"] = abs(float(item.get("diff", 0))) > tolerance
        tax_rows.append(row)

    missing_org_rows = [{"org_code": org, "issue": "专项附加扣除合计为0"} for org in report["deduction_warnings"]["missing_orgs"]]
    low_confidence = list(report.get("deduction_match_quality", {}).get("low_confidence", []))
    low_confidence.extend(report.get("deduction_match_quality", {}).get("name_mismatches", []))

    return {
        "00_汇总": pd.DataFrame(summary_rows),
        "01_新增人员候选": pd.DataFrame(new_items),
        "02_离职人员候选": pd.DataFrame(leaver_items),
        "03_机构变动候选": pd.DataFrame(transfer_items),
        "04_关键字段缺失": pd.DataFrame(report.get("key_field_missing", {}).get("items", [])),
        "04A_工资机构代码格式": pd.DataFrame(report.get("payroll_org_format", {}).get("items", [])),
        "04B_工资机构识别号映射": pd.DataFrame(report.get("taxpayer_org_mapping", {}).get("items", [])),
        "05_个税差异": pd.DataFrame(tax_rows),
        "06_专项附加扣除重复": pd.DataFrame(report["deduction_warnings"]["duplicates"]),
        "07_专项附加扣除机构遗漏": pd.DataFrame(missing_org_rows),
        "08_专项附加扣除低置信度匹配": pd.DataFrame(low_confidence),
        "09_非正常人员匹配失败": pd.DataFrame(report.get("personnel_update_issues", {}).get("match_failures", [])),
        "10_新增人员疑似重复": pd.DataFrame(report.get("personnel_update_issues", {}).get("duplicate_additions", [])),
        "11_数据质量前置校验": pd.DataFrame(report.get("data_quality", {}).get("items", [])),
        "12_人数对账": pd.DataFrame(report.get("headcount_reconciliation", {}).get("items", [])),
        "13_退休福利慰问核对": pd.DataFrame(report.get("retirement_welfare", {}).get("items", [])),
    }


def write_reconciliation_report(report: dict, output_path: str | Path) -> str:
    """Write the unified reconciliation report workbook."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheets = report.get("report_sheets") or build_reconciliation_report(report)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = sheet_name[:31]
            (df if not df.empty else pd.DataFrame()).to_excel(writer, sheet_name=safe_name, index=False)
    return str(path)


def report_for_json(report: dict) -> dict:
    """Drop DataFrame-only report sheets before storing/returning JSON."""
    result = dict(report)
    result.pop("report_sheets", None)
    return result


def build_verification_checks(report: dict) -> list[dict]:
    """Build the frontend-facing check summary from detailed report sections."""
    tax_count = len(report["tax_diff"]["items"])
    personnel_items = report["personnel_changes"]["items"]
    personnel_count = len(personnel_items)
    missing_cert_count = len(report["missing_cert"]["items"])
    deduction_count = (
        len(report["deduction_warnings"]["duplicates"])
        + len(report["deduction_warnings"]["missing_orgs"])
    )
    taxpayer_mapping_count = len(report.get("taxpayer_org_mapping", {}).get("items", []))

    missing_personnel_fields = sum(1 for item in personnel_items if item.get("missing_fields"))
    confirmable_personnel = sum(1 for item in personnel_items if item.get("can_confirm"))

    checks = [
        {
            "code": "tax_diff",
            "title": "个税差异核对",
            "status": "fail" if tax_count else "pass",
            "issue_count": tax_count,
            "message": f"发现 {tax_count} 条应预扣预缴税额与个人所得税不一致，请与 HR/薪酬口径核对。"
            if tax_count else "个税金额核对一致。",
        },
        {
            "code": "personnel_changes",
            "title": "人员变动与 HR 确认",
            "status": "fail" if personnel_count else "pass",
            "issue_count": personnel_count,
            "message": (
                f"发现 {personnel_count} 条入职/离职/调岗记录，其中 {missing_personnel_fields} 条需补齐信息，"
                f"{confirmable_personnel} 条可线上确认。"
            ) if personnel_count else "人员信息与工资数据一致。",
        },
        {
            "code": "missing_cert",
            "title": "证件信息完整性",
            "status": "fail" if missing_cert_count else "pass",
            "issue_count": missing_cert_count,
            "message": f"发现 {missing_cert_count} 条人员证件信息缺失，请补齐后再生成申报文件。"
            if missing_cert_count else "证件信息完整。",
        },
        {
            "code": "taxpayer_org_mapping",
            "title": "工资机构识别号映射",
            "status": "fail" if taxpayer_mapping_count else "pass",
            "issue_count": taxpayer_mapping_count,
            "message": f"发现 {taxpayer_mapping_count} 条工资记录无法通过扣缴义务人识别号映射机构代码。"
            if taxpayer_mapping_count else "工资机构识别号映射通过。",
        },
        {
            "code": "deduction_warnings",
            "title": "专项附加扣除核对",
            "status": "fail" if report["deduction_warnings"]["duplicates"] else ("warn" if report["deduction_warnings"]["missing_orgs"] else "pass"),
            "issue_count": deduction_count,
            "message": f"发现 {deduction_count} 项专项扣除异常，请核对重复人员或缺失机构。"
            if deduction_count else "专项附加扣除核对通过。",
        },
    ]
    retirement_items = report.get("retirement_welfare", {}).get("items", [])
    if retirement_items:
        checks.append({
            "code": "retirement_welfare",
            "title": "退休福利慰问核对",
            "status": "fail" if any(item.get("blocking") for item in retirement_items) else ("warn" if any(item.get("status") != "金额一致" for item in retirement_items) else "pass"),
            "issue_count": sum(1 for item in retirement_items if item.get("status") != "金额一致"),
            "message": f"退休福利表已处理 {len(retirement_items)} 人。",
        })
    return checks


def verify(
    sheet: pd.DataFrame,
    deduction_folder: str = "",
    confirmed_personnel: list | None = None,
    staff_df: pd.DataFrame | None = None,
    change_df: pd.DataFrame | None = None,
    year: int = 2025,
    month: int = 1,
    config: dict | None = None,
) -> dict:
    """对底稿执行全部核对检查。"""
    effective_config = {**VERIFICATION_RULE_CONFIG, **(config or {})}
    org_col = "机构代码_工资单" if "机构代码_工资单" in sheet.columns else "机构代码"
    report = {
        "summary": {
            "total_employees": int(len(sheet)),
            "total_orgs": int(sheet[org_col].nunique()) if org_col in sheet.columns else 0,
        },
        "config": {
            "tax_diff_tolerance": effective_config["tax_diff_tolerance"],
            "blocking_codes": sorted(effective_config["blocking_codes"]),
            "warning_codes": sorted(effective_config["warning_codes"]),
        },
        "data_quality": check_data_quality(staff_df=staff_df, change_df=change_df),
        "tax_diff": check_tax_diff(sheet),
        "personnel_changes": check_personnel_changes(
            sheet, confirmed_personnel, staff_df=staff_df, year=year, month=month,
        ),
        "missing_cert": check_missing_cert(sheet),
        "payroll_org_format": check_payroll_org_format(sheet),
        "taxpayer_org_mapping": check_taxpayer_org_mapping(sheet),
        "deduction_warnings": check_deduction_issues(deduction_folder) if deduction_folder
        else {"has_issues": False, "duplicates": [], "missing_orgs": []},
        "deduction_match_quality": sheet.attrs.get(
            "deduction_match_quality", {"low_confidence": [], "name_mismatches": []}
        ),
        "key_field_missing": {"has_issues": False, "items": []},
        "personnel_update_issues": {"match_failures": [], "duplicate_additions": [], "multiple_matches": []},
        "headcount_reconciliation": {"has_issues": False, "items": []},
        "retirement_welfare": {"items": sheet.attrs.get("retirement_welfare", [])},
    }

    if deduction_folder:
        report["deduction_warnings"]["missing_orgs"] = check_deduction_coverage(sheet)
        report["deduction_warnings"]["has_issues"] = bool(
            report["deduction_warnings"]["duplicates"]
            or report["deduction_warnings"]["missing_orgs"]
        )
    report["deduction_warnings"]["has_blocking_issues"] = bool(report["deduction_warnings"]["duplicates"])

    total = 0
    if report["tax_diff"]["has_issues"]:
        total += len(report["tax_diff"]["items"])
    if report["personnel_changes"]["has_issues"]:
        total += len(report["personnel_changes"]["items"])
    if report["missing_cert"]["has_issues"]:
        total += len(report["missing_cert"]["items"])
    if report["payroll_org_format"]["has_issues"]:
        total += len(report["payroll_org_format"]["items"])
    if report["taxpayer_org_mapping"]["has_issues"]:
        total += len(report["taxpayer_org_mapping"]["items"])
    if report["deduction_warnings"]["has_issues"]:
        total += len(report["deduction_warnings"]["duplicates"])
        total += len(report["deduction_warnings"]["missing_orgs"])
    if report["data_quality"]["has_issues"]:
        total += len(report["data_quality"]["items"])
    total += len(report["deduction_match_quality"].get("low_confidence", []))
    total += len(report["deduction_match_quality"].get("name_mismatches", []))
    total += sum(1 for item in report["retirement_welfare"]["items"] if item.get("status") != "金额一致")

    report["summary"]["total_issues"] = total
    report["summary"]["blocking_issues"] = int(
        len(report["tax_diff"]["items"])
        + len(report["personnel_changes"]["items"])
        + len(report["missing_cert"]["items"])
        + len(report["payroll_org_format"]["items"])
        + len(report["taxpayer_org_mapping"]["items"])
        + len(report["deduction_warnings"]["duplicates"])
        + sum(1 for item in report["data_quality"]["items"] if item.get("severity") == "blocking")
        + sum(1 for item in report["retirement_welfare"]["items"] if item.get("blocking"))
    )
    report["summary"]["has_blocking_issues"] = report["summary"]["blocking_issues"] > 0
    report["checks"] = build_verification_checks(report)
    report["report_sheets"] = build_reconciliation_report(report)
    return report


def check_all_clear(report: dict) -> bool:
    """判断核对报告是否所有问题均已清零。"""
    return (
        not report["summary"].get("has_blocking_issues", False)
        and not report["tax_diff"]["has_issues"]
        and not report["personnel_changes"]["has_issues"]
        and not report["missing_cert"]["has_issues"]
        and not report["deduction_warnings"]["has_issues"]
    )


def check_no_blocking_issues(report: dict) -> bool:
    """判断是否没有阻断项，提醒项可继续但需要人工留痕。"""
    return not report["summary"].get("has_blocking_issues", False)
