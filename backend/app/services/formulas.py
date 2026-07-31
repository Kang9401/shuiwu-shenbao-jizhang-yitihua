from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from app.services.excel import normalize_emp_id
from app.services.intern_org_mapping import INTERN_ORG_CODE_MAP


ORG_CODE_MAP = {
    9001: 17001,
    9002: 17002,
    9003: 17003,
    9004: 17004,
    9005: 17005,
    9006: 17006,
    9007: 17007,
    9010: 17023,
    9012: 17010,
    9013: 17013,
    9014: 17014,
    9015: 17015,
    9016: 17016,
    9018: 17018,
    9019: 17029,
    9020: 17020,
    9021: 17021,
    9025: 17025,
    9028: 17028,
    9030: 17030,
    7027: 17027,
}

GENERAL_SALARY_ROLES = {
    "salary_sheet",
    "marketing_salary_sheet",
    "rank_salary_sheet",
    "branch_salary_sheet",
    "headquarters_salary_sheet",
    "digital_ops_salary_sheet",
    "advisor_salary_sheet",
}

SALARY_ROLE_LABELS = {
    "salary_sheet": "通用工资单",
    "marketing_salary_sheet": "营销工资单",
    "rank_salary_sheet": "职级工资单",
    "branch_salary_sheet": "机构工资单",
    "headquarters_salary_sheet": "总部工资单",
    "digital_ops_salary_sheet": "数字化运营工资单",
    "advisor_salary_sheet": "投资顾问/理财经理/零售经理工资单",
}

GENERAL_TAX_TEMPLATE_COLUMNS = [
    "工号",
    "*姓名",
    "*证件类型",
    "*证件号码",
    "本期收入",
    "本期免税收入",
    "基本养老保险费",
    "基本医疗保险费",
    "失业保险费",
    "住房公积金",
    "累计子女教育",
    "累计继续教育",
    "累计住房贷款利息",
    "累计住房租金",
    "累计赡养老人",
    "累计3岁以下婴幼儿照护",
    "累计个人养老金",
    "企业(职业)年金",
    "商业健康保险",
    "税延养老保险",
    "公务交通费用",
    "通讯费用",
    "律师办案费用",
    "西藏附加减除费用",
    "其他",
    "准予扣除的捐赠额",
    "减免税额",
    "协定减免",
    "备注",
]


def first_existing(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    for column in candidates:
        if column in df.columns:
            return column
    return None


def number_series(df: pd.DataFrame, candidates: Iterable[str], default: float = 0) -> pd.Series:
    column = first_existing(df, candidates)
    if column is None:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[column].astype(str).str.replace(",", "", regex=False), errors="coerce").fillna(default)


def text_series(df: pd.DataFrame, candidates: Iterable[str], default: str = "") -> pd.Series:
    column = first_existing(df, candidates)
    if column is None:
        return pd.Series(default, index=df.index, dtype="object")
    return df[column].fillna(default).astype(str).str.strip()


def empty_series(df: pd.DataFrame, default: Any = "") -> pd.Series:
    return pd.Series(default, index=df.index)


def promote_header_row(df: pd.DataFrame, marker: str) -> pd.DataFrame:
    if marker in df.columns:
        return df
    matches = df.eq(marker)
    positions = matches.stack()[lambda values: values].index.tolist()
    if not positions:
        return df
    header_index = positions[0][0]
    promoted = df.iloc[header_index + 1 :].copy()
    promoted.columns = df.iloc[header_index].fillna("").astype(str).tolist()
    return promoted.reset_index(drop=True)


def normalize_org_code(value: Any) -> str:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return ""
    text = str(value).strip()
    try:
        number = int(float(text))
    except ValueError:
        return text
    if number > 9000:
        number = ORG_CODE_MAP.get(number, number)
    else:
        number = number + 10000
    return str(number)[:5]


def split_by_company(df: pd.DataFrame, org_col: str, drop_org: bool = True) -> Dict[str, pd.DataFrame]:
    if org_col not in df.columns:
        return {}
    result: Dict[str, pd.DataFrame] = {}
    for org, group in df.groupby(org_col, dropna=False):
        key = str(org or "未识别机构")
        result[key] = group.drop(columns=[org_col]) if drop_org else group.copy()
    return result


def merge_duplicate_invoice_lines(
    df: pd.DataFrame,
    key_cols: List[str],
    sum_cols: List[str],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    present_keys = [column for column in key_cols if column in df.columns]
    present_sum_cols = [column for column in sum_cols if column in df.columns]
    if not present_keys:
        return df.copy(), pd.DataFrame()
    work = df.copy()
    for column in present_sum_cols:
        work[column] = pd.to_numeric(work[column].astype(str).str.replace(",", "", regex=False), errors="coerce").fillna(0)
    duplicates = work[work.duplicated(subset=present_keys, keep=False)].copy()
    if duplicates.empty:
        return work, duplicates
    merged_duplicates = (
        duplicates.groupby(present_keys, dropna=False, as_index=False)
        .agg({**{column: "sum" for column in present_sum_cols}, **{column: "first" for column in work.columns if column not in present_keys + present_sum_cols}})
    )
    unique_rows = work.drop_duplicates(subset=present_keys, keep=False)
    return pd.concat([unique_rows, merged_duplicates], ignore_index=True), duplicates


def build_org_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["机构代码", "人数", "收入合计", "税额合计"])
    work = df.copy()
    org_col = first_existing(work, ["机构代码", "分支机构代码", "单位编号", "公司段"])
    work["机构代码"] = text_series(work, [org_col] if org_col else [], "未识别机构")
    work["收入"] = number_series(
        work,
        [
            "本期收入",
            "应发合计 SUM",
            "应发工资 I=A+B+D-F-G9+K",
            "应发工资 I=A+B+C+D+E-F-G+H+J+K+A10",
            "应发工资H=A+B+J",
            "应发工资(补足前)",
            "发放补贴数\n（元）",
            "年终奖发放",
            "*全年一次性奖金收入",
            "*收入",
        ],
    )
    work["税额"] = number_series(
        work,
        [
            "个人所得税",
            "本期应预扣预缴税额 SUM",
            "个人所得税 SUM",
            "本次扣税",
            "个人所得税(经纪人)",
            "限售股税费(申报表)",
            "利息税税费(申报表)",
            "税额",
            "年终奖计税",
        ],
    )
    return (
        work.groupby("机构代码", dropna=False)
        .agg(人数=("机构代码", "size"), 收入合计=("收入", "sum"), 税额合计=("税额", "sum"))
        .reset_index()
    )


def staff_change_analysis(staff_df: pd.DataFrame, payroll_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    staff = staff_df.copy()
    payroll = payroll_df.copy()
    staff["员工编号"] = text_series(staff, ["员工编号", "员工编码"]).map(normalize_emp_id)
    payroll["员工编号"] = text_series(payroll, ["员工编号", "员工编码"]).map(normalize_emp_id)
    staff["姓名"] = text_series(staff, ["*姓名", "姓名", "员工姓名"])
    payroll["姓名"] = text_series(payroll, ["*姓名", "姓名", "员工姓名"])
    staff["机构代码_人员信息表"] = text_series(staff, ["机构代码", "分支机构代码", "单位编号"])
    payroll["机构代码_工资表"] = text_series(payroll, ["机构代码", "分支机构代码", "单位编号"]).map(normalize_org_code)
    staff_keys = staff[["员工编号", "姓名", "机构代码_人员信息表"]].drop_duplicates()
    payroll_keys = payroll[["员工编号", "姓名", "机构代码_工资表"]].drop_duplicates()
    merged = staff_keys.merge(payroll_keys, on=["员工编号", "姓名"], how="outer", indicator=True)
    return {
        "本月新增人员": merged[merged["_merge"] == "right_only"].drop(columns=["_merge"]),
        "本月离职人员": merged[merged["_merge"] == "left_only"].drop(columns=["_merge"]),
        "本月人员变动": merged[
            (merged["_merge"] == "both")
            & (merged["机构代码_人员信息表"].fillna("") != merged["机构代码_工资表"].fillna(""))
        ].drop(columns=["_merge"]),
    }


def normalize_general_salary_frame(role: str, df: pd.DataFrame) -> pd.DataFrame:
    source = promote_header_row(df, "所在部门").copy() if role == "rank_salary_sheet" else df.copy()
    source["员工编号"] = text_series(source, ["员工编号", "员工编码"]).map(normalize_emp_id)
    source["*姓名"] = text_series(source, ["*姓名", "姓名", "员工姓名"])
    source["工资单类型"] = SALARY_ROLE_LABELS.get(role, "工资单")
    source["机构代码"] = text_series(source, ["机构代码", "单位编号", "分支机构代码"]).map(normalize_org_code)

    salary_base = number_series(
        source,
        [
            "本期收入",
            "应发合计 SUM",
            "应发工资 I=A+B+C+D+E-F-G+H+J+K+A10",
            "应发工资 I=A+B+D-F-G9+K",
            "应发工资H=A+B+J",
            "应发工资H=A+B+E+I+J+K-A8",
        ],
    )
    adjust = number_series(source, ["调增应纳税所得额", "调增应纳税所得额 SUM"])
    source["本期收入"] = salary_base + adjust
    source["本期免税收入"] = number_series(source, ["本期免税收入", "免税支出 SUM", "免税支出"])
    source["基本养老保险费"] = number_series(source, ["基本养老保险费", "养老(个人部分)", "养老保险金的员工部分 SUM", "养老保险金的员工部分"])
    source["基本医疗保险费"] = number_series(source, ["基本医疗保险费", "医疗(个人部分)", "医疗保险金的员工部分 SUM", "医疗保险金的员工部分"])
    source["失业保险费"] = number_series(source, ["失业保险费", "失业(个人部分)", "失业保险金的员工部分 SUM", "失业保险金的员工部分"])
    source["住房公积金"] = number_series(source, ["住房公积金", "公积金(个人部分)", "公积金（个人部分）", "住房公积金的员工部分 SUM", "住房公积金的员工部分"])
    source["企业(职业)年金"] = number_series(source, ["企业(职业)年金", "企业年金(个人部分)", "企业年金（个人部分）", "企业年金的员工部分 SUM", "企业年金的员工部分"])
    source["商业健康保险"] = number_series(source, ["商业健康保险", "商业保险扣除 SUM", "商业保险扣除", "累计商业保险扣除"])
    source["个人所得税 SUM"] = number_series(source, ["个人所得税 SUM", "个人所得税"])
    source["本期应预扣预缴税额 SUM"] = number_series(source, ["本期应预扣预缴税额 SUM"])
    source["个税差异"] = source["本期应预扣预缴税额 SUM"] - source["个人所得税 SUM"]

    deduction_cols = {
        "累计子女教育": ["累计子女教育", "累计当月子女教育附加扣除"],
        "累计继续教育": ["累计继续教育", "累计当月继续教育附加扣除"],
        "累计住房贷款利息": ["累计住房贷款利息", "累计当月住房贷款利息附加扣除"],
        "累计住房租金": ["累计住房租金", "累计当月住房租金附加扣除"],
        "累计赡养老人": ["累计赡养老人", "累计当月赡养老人附加扣除"],
        "累计3岁以下婴幼儿照护": ["累计3岁以下婴幼儿照护", "累计当月婴幼儿照护费用附加扣除"],
        "累计个人养老金": ["累计个人养老金"],
    }
    for target, candidates in deduction_cols.items():
        source[target] = number_series(source, candidates)

    for column in ["税延养老保险", "公务交通费用", "通讯费用", "律师办案费用", "西藏附加减除费用", "其他", "准予扣除的捐赠额", "减免税额", "协定减免"]:
        source[column] = number_series(source, [column])
    source["备注"] = text_series(source, ["备注"])
    source["工号"] = source["员工编号"]
    return source


def merge_staff_for_general_salary(salary: pd.DataFrame, staff_df: pd.DataFrame) -> pd.DataFrame:
    salary = salary.copy()
    salary["机构代码_工资单"] = salary["机构代码"]
    if staff_df.empty:
        salary["*证件类型"] = ""
        salary["*证件号码"] = ""
        return salary

    staff = staff_df.copy()
    staff["员工编号"] = text_series(staff, ["员工编号", "员工编码"]).map(normalize_emp_id)
    staff["*姓名"] = text_series(staff, ["*姓名", "姓名", "员工姓名"])
    staff["*证件类型"] = text_series(staff, ["*证件类型", "证件类型"])
    staff["*证件号码"] = text_series(staff, ["*证件号码", "证件号码"])
    staff["机构代码_人员信息表"] = text_series(staff, ["机构代码", "分支机构代码", "单位编号"]).map(normalize_org_code)
    active_col = first_existing(staff, ["人员状态"])
    if active_col:
        staff = staff[staff[active_col].astype(str).str.strip().isin(["正常", "姝ｅ父", ""])]

    staff_cols = ["员工编号", "*姓名", "*证件类型", "*证件号码", "机构代码_人员信息表"]
    optional_cols = [col for col in ["手机号码", "任职受雇从业日期"] if col in staff.columns]
    merged = salary.merge(staff[staff_cols + optional_cols].drop_duplicates(["员工编号", "*姓名"]), on=["员工编号", "*姓名"], how="left")
    merged["机构代码"] = merged["机构代码_人员信息表"].fillna("").where(
        merged["机构代码_人员信息表"].fillna("") != "",
        merged["机构代码_工资单"],
    )
    return merged


def general_salary_summary(salary: pd.DataFrame) -> pd.DataFrame:
    if salary.empty:
        return pd.DataFrame(columns=["机构代码", "人数", "收入合计", "个人所得税合计", "本期应预扣预缴税额合计", "个税差异合计"])
    return (
        salary.groupby("机构代码", dropna=False)
        .agg(
            人数=("员工编号", "size"),
            收入合计=("本期收入", "sum"),
            个人所得税合计=("个人所得税 SUM", "sum"),
            本期应预扣预缴税额合计=("本期应预扣预缴税额 SUM", "sum"),
            个税差异合计=("个税差异", "sum"),
        )
        .reset_index()
    )


def annual_bonus_transform(frames_by_role: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    bonus_frames: List[pd.DataFrame] = []
    for role in ["annual_bonus_sheet", "salary_sheet"]:
        if role not in frames_by_role:
            continue
        frame = frames_by_role[role].copy()
        for source, target in {
            "员工姓名": "*姓名",
            "年终奖汇总": "年终奖发放",
            "年终奖计税": "本次扣税",
        }.items():
            if source not in frame.columns:
                continue
            if target in frame.columns:
                frame[target] = frame[target].combine_first(frame[source])
                frame = frame.drop(columns=[source])
            else:
                frame = frame.rename(columns={source: target})
        if "员工编号" in frame.columns:
            frame["员工编号"] = frame["员工编号"].map(normalize_emp_id)
        bonus_frames.append(frame)
    bonus = pd.concat(bonus_frames, ignore_index=True) if bonus_frames else pd.DataFrame()
    staff = frames_by_role.get("staff_info", pd.DataFrame()).copy()
    if staff.empty or bonus.empty:
        final = bonus
        issues = [{"issue_type": "缺失输入", "message": "缺少年终奖表或人员信息表"}]
    else:
        staff = staff.rename(columns={"姓名": "*姓名"})
        staff["员工编号"] = staff["员工编号"].map(normalize_emp_id)
        active_col = first_existing(staff, ["人员状态"])
        if active_col:
            staff = staff[staff[active_col].astype(str).str.strip().isin(["正常", "姝ｅ父"])]
        final = staff.merge(bonus, on=["*姓名", "员工编号"], how="inner")
        amount_col = first_existing(final, ["年终奖发放", "*全年一次性奖金收入"])
        if amount_col:
            final = final[number_series(final, [amount_col]) > 0].copy()
        final["工号"] = final["员工编号"]
        final = final.rename(
            columns={
                "证件类型": "*证件类型",
                "证件号码": "*证件号码",
                "年终奖发放": "*全年一次性奖金收入",
            }
        )
        issues = []
    summary = build_org_summary(final)
    return {"detail": final, "summary": summary, "issues": issues}


BROKER_DECLARATION_COLUMNS = [
    "工号", "*姓名", "*证件类型", "*证件号码", "*所得项目", "本期收入", "本期免税收入",
    "累计个人养老金", "商业健康保险", "税延养老保险", "其他", "允许扣除的税费", "减免税额", "备注",
]

INTERN_DECLARATION_COLUMNS = ["*姓名", "*证件类型", "证件号码", "*所得项目", "本期收入"]
INTERN_ALLOWED_CERT_TYPES = {
    "居民身份证", "中国护照", "港澳居民来往内地通行证", "台湾居民来往大陆通行证", "外国护照",
}


def _clean_cell(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def broker_tax_transform(frames_by_role: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    broker = frames_by_role.get("broker_salary_sheet", pd.DataFrame()).copy()
    staff = frames_by_role.get("broker_staff_info", pd.DataFrame()).copy()
    issues: List[Dict[str, Any]] = []
    if broker.empty:
        return {
            "detail": broker,
            "summary": pd.DataFrame(),
            "issues": [{"issue_type": "缺失输入", "message": "缺少经纪人综合业绩指标表"}],
            "block_declarations": True,
        }

    broker["员工编号"] = text_series(broker, ["员工编号"]).map(normalize_emp_id)
    # 平台导出文件首行是汇总，不属于经纪人申报明细。
    broker = broker[broker["员工编号"].map(_clean_cell) != ""].copy()
    duplicate_payroll_ids = broker.loc[broker["员工编号"].duplicated(keep=False), "员工编号"].unique()
    issues.extend(
        {"issue_type": "经纪人业绩重复", "message": f"同一所属期间员工编号重复：{employee_id}"}
        for employee_id in duplicate_payroll_ids if _clean_cell(employee_id)
    )
    broker["经纪人本期收入"] = number_series(broker, ["应发工资(补足前)"]) - number_series(broker, ["增值税"])
    broker["个人所得税(经纪人)"] = number_series(broker, ["个人所得税(经纪人)"])
    zero_count = 0
    negative_count = 0
    for idx, row in broker.iterrows():
        employee_id = _clean_cell(row["员工编号"])
        if row["经纪人本期收入"] < 0:
            negative_count += 1
            issues.append({"issue_type": "经纪人负数收入提醒", "severity": "warning", "message": f"经纪人 {employee_id} 的本期收入为负数：{row['经纪人本期收入']:.2f}"})
        elif row["经纪人本期收入"] == 0:
            zero_count += 1
            issues.append({"issue_type": "经纪人零收入提醒", "severity": "warning", "message": f"经纪人 {employee_id} 的本期收入为0，仍将生成申报行"})

    if staff.empty:
        issues.append({"issue_type": "经纪人主数据提醒", "severity": "warning", "message": "缺少经纪人人员主数据，无法生成有证件信息的申报行"})
        detail = broker
    else:
        staff = staff.copy()
        staff["员工编号"] = text_series(staff, ["员工编号"]).map(normalize_emp_id)
        staff["*姓名"] = text_series(staff, ["*姓名", "姓名"])
        staff["*证件类型"] = text_series(staff, ["*证件类型", "证件类型"])
        staff["*证件号码"] = text_series(staff, ["*证件号码", "证件号码"])
        staff["分支机构代码"] = text_series(staff, ["分支机构代码", "机构代码", "机构代码(人员信息表)"])
        duplicate_ids = staff.loc[staff["员工编号"].duplicated(keep=False), "员工编号"].dropna().unique()
        issues.extend(
            {"issue_type": "经纪人主数据重复", "message": f"经纪人人员主数据员工编号重复：{employee_id}"}
            for employee_id in duplicate_ids if _clean_cell(employee_id)
        )
        staff_lookup = staff.drop_duplicates(subset=["员工编号"], keep="first")
        broker_ids = {employee_id for employee_id in broker["员工编号"] if _clean_cell(employee_id)}
        staff_ids = {employee_id for employee_id in staff_lookup["员工编号"] if _clean_cell(employee_id)}
        issues.extend(
            {"issue_type": "经纪人新增待维护", "severity": "warning", "message": f"经纪人工资表存在但人员主数据缺失，将跳过申报：{employee_id}"}
            for employee_id in sorted(broker_ids - staff_ids)
        )
        issues.extend(
            {"issue_type": "经纪人无本月收入提醒", "severity": "warning", "message": f"经纪人人员主数据存在但本月业绩表缺失：{employee_id}"}
            for employee_id in sorted(staff_ids - broker_ids)
        )
        detail = broker.merge(
            staff_lookup[["员工编号", "分支机构代码", "*姓名", "*证件类型", "*证件号码"]],
            on="员工编号",
            how="left",
        )

    for column in BROKER_DECLARATION_COLUMNS:
        if column not in detail.columns:
            detail[column] = ""
    detail["工号"] = ""
    detail["*所得项目"] = "证券经纪人佣金收入"
    detail["本期收入"] = detail["经纪人本期收入"]
    summary = (
        detail.groupby("分支机构代码", dropna=False)
        .agg(经纪人本期收入=("经纪人本期收入", "sum"), 个人所得税_经纪人=("个人所得税(经纪人)", "sum"))
        .reset_index()
        .rename(columns={"个人所得税_经纪人": "个人所得税(经纪人)"})
        if "分支机构代码" in detail.columns
        else pd.DataFrame(columns=["分支机构代码", "经纪人本期收入", "个人所得税(经纪人)"])
    )
    matched = detail["分支机构代码"].map(_clean_cell) != "" if "分支机构代码" in detail.columns else pd.Series(False, index=detail.index)
    metrics = {
        "broker_records": int(len(broker)),
        "broker_declared_records": int(matched.sum()),
        "broker_orgs": int(detail.loc[matched, "分支机构代码"].nunique()) if "分支机构代码" in detail.columns else 0,
        "broker_declared_amount": float(detail.loc[matched, "经纪人本期收入"].sum()),
        "broker_personal_tax": float(detail.loc[matched, "个人所得税(经纪人)"].sum()),
        "broker_missing_master": int((~matched).sum()),
        "broker_zero_income": zero_count,
        "broker_negative_income": negative_count,
    }
    blocking_types = {"经纪人业绩重复", "经纪人主数据重复"}
    return {
        "detail": detail,
        "summary": summary,
        "issues": issues,
        "metrics": metrics,
        "block_declarations": any(issue.get("issue_type") in blocking_types for issue in issues),
    }


def intern_tax_transform(frames_by_role: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    source = frames_by_role.get("intern_salary_sheet", pd.DataFrame()).copy()
    mapping_frame = frames_by_role.get("intern_org_mapping", pd.DataFrame()).copy()
    org_mapping = dict(INTERN_ORG_CODE_MAP)
    if not mapping_frame.empty and {"营业部名称", "机构代码"}.issubset(mapping_frame.columns):
        org_mapping = {
            _clean_cell(row["营业部名称"]): _clean_cell(row["机构代码"])
            for _, row in mapping_frame.iterrows()
            if _clean_cell(row["营业部名称"]) and _clean_cell(row["机构代码"])
        }
    issues: List[Dict[str, Any]] = []
    if source.empty:
        return {
            "detail": source,
            "summary": pd.DataFrame(),
            "issues": [{"issue_type": "缺失输入", "message": "缺少实习生补贴表"}],
            "block_declarations": True,
        }

    rows: list[dict[str, Any]] = []
    source_records = 0
    source_total_amount = 0.0
    for idx, row in source.iterrows():
        source_row = int(row.get("_source_row_number", idx + 2))
        name = _clean_cell(row.get("*姓名"))
        cert_type = _clean_cell(row.get("*证件类型"))
        # The source workbook includes an instruction row after its heading.
        if not name or name == "可任意填写":
            continue
        source_records += 1
        branch_name = _clean_cell(row.get("营业部名称", row.get("分支机构名称")))
        provided_org_code = _clean_cell(row.get("机构代码"))
        id_number = _clean_cell(row.get("*证件号码", row.get("证件号码")))
        income_raw = row.get("发放补贴数\n（元）", row.get("发放补贴数（元）", row.get("实习生本期收入")))
        income = pd.to_numeric(pd.Series([income_raw]), errors="coerce").dropna()
        income_value = float(income.iloc[0]) if not income.empty else 0.0
        source_total_amount += income_value
        missing = [
            field for field, value in {
                "证件类型": cert_type,
                "证件号码": id_number,
                "实习开始时间": _clean_cell(row.get("实习开始时间")),
                "发放补贴数": _clean_cell(income_raw),
            }.items() if not value
        ]
        if missing:
            issues.append({"issue_type": "实习生必填项缺失", "message": f"实习生第 {source_row} 行 {name} 缺少：{'、'.join(missing)}"})
            continue
        if cert_type not in INTERN_ALLOWED_CERT_TYPES:
            issues.append({"issue_type": "实习生证件类型不支持", "message": f"实习生第 {source_row} 行 {name} 的证件类型不支持：{cert_type}"})
            continue
        mapped_org_code = org_mapping.get(branch_name, "") if branch_name else ""
        if provided_org_code and (not provided_org_code.isdigit() or len(provided_org_code) != 5):
            issues.append({"issue_type": "实习生机构代码无效", "message": f"实习生第 {source_row} 行 {name} 的机构代码必须为5位数字：{provided_org_code}"})
            continue
        if provided_org_code and mapped_org_code and provided_org_code != mapped_org_code:
            issues.append({
                "issue_type": "实习生机构映射冲突",
                "message": f"实习生第 {source_row} 行 {name} 的机构代码 {provided_org_code} 与营业部 {branch_name} 映射代码 {mapped_org_code} 不一致",
            })
            continue
        org_code = provided_org_code or mapped_org_code
        if not org_code:
            issues.append({"issue_type": "实习生机构未匹配", "message": f"实习生第 {source_row} 行 {name} 未填写有效机构代码，营业部也未匹配：{branch_name or '未填营业部'}"})
            continue
        if cert_type != "居民身份证":
            foreign_missing = [
                field for field, value in {
                    "国籍(地区)": _clean_cell(row.get("*国籍(地区)")),
                    "性别": _clean_cell(row.get("*性别")),
                    "出生日期": _clean_cell(row.get("*出生日期")),
                }.items() if not value
            ]
            if foreign_missing:
                issues.append({"issue_type": "实习生外籍信息缺失", "message": f"实习生第 {source_row} 行 {name} 缺少：{'、'.join(foreign_missing)}"})
                continue
        rows.append({
            "分支机构代码": org_code,
            "*姓名": name,
            "*证件类型": cert_type,
            "证件号码": id_number,
            "*国籍(地区)": _clean_cell(row.get("*国籍(地区)")),
            "*性别": _clean_cell(row.get("*性别")),
            "*出生日期": _clean_cell(row.get("*出生日期")),
            "任职受雇从业日期": row.get("实习开始时间", ""),
            "手机号码": _clean_cell(row.get("联系方式", row.get("手机号码"))),
            "人员状态": "正常",
            "任职受雇从业类型": "实习学生（全日制学历教育）",
            "*所得项目": "其他连续劳务报酬",
            "本期收入": income_value,
            "实习生本期收入": income_value,
        })
    detail = pd.DataFrame(rows)
    summary = (
        detail.groupby("分支机构代码", dropna=False)["实习生本期收入"].sum().reset_index()
        if not detail.empty
        else pd.DataFrame(columns=["分支机构代码", "实习生本期收入"])
    )
    metrics = {
        "intern_records": source_records,
        "intern_valid_records": int(len(detail)),
        "intern_orgs": int(detail["分支机构代码"].nunique()) if not detail.empty else 0,
        "intern_total_amount": source_total_amount,
        "intern_valid_amount": float(detail["本期收入"].sum()) if not detail.empty else 0.0,
        "intern_issue_records": int(len(issues)),
    }
    return {
        "detail": detail,
        "summary": summary,
        "issues": issues,
        "metrics": metrics,
        "block_declarations": bool(issues),
    }


def restricted_stock_interest_transform(frames_by_role: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    xsg = frames_by_role.get("restricted_stock_sheet", pd.DataFrame()).copy()
    lxs = frames_by_role.get("interest_tax_sheet", pd.DataFrame()).copy()
    balance = frames_by_role.get("balance_sheet", pd.DataFrame()).copy()
    issues: List[Dict[str, Any]] = []
    interest_source_withheld_warnings = 0
    declaration_validation_issues = 0

    if not xsg.empty:
        xsg["机构代码"] = text_series(xsg, ["机构代码", "分支机构代码"]).map(normalize_org_code)
        xsg_name = text_series(xsg, ["客户姓名", "姓名", "*姓名"])
        xsg_cert_type = text_series(xsg, ["证件类型", "*证件类型"])
        xsg_cert_number = text_series(xsg, ["证件号码", "*证件号码", "身份证号码"])
        xsg_account = text_series(xsg, ["证券账号", "证券账户号", "*证券账户号", "资产账户"])
        xsg_stock_code = text_series(xsg, ["证券代码", "股票代码", "*股票代码"])
        xsg_stock_name = text_series(xsg, ["证券名称", "股票名称", "*股票名称"])
        xsg_price = number_series(xsg, ["成交价格", "*每股计税价格(元/股)"])
        xsg_quantity = number_series(xsg, ["成交数量", "*转让股数(股)"])
        for idx in xsg.index:
            missing = [
                label for label, value in [
                    ("机构代码", xsg.at[idx, "机构代码"]),
                    ("姓名", xsg_name.at[idx]),
                    ("证件类型", xsg_cert_type.at[idx]),
                    ("证件号码", xsg_cert_number.at[idx]),
                    ("证券账户号", xsg_account.at[idx]),
                    ("股票代码", xsg_stock_code.at[idx]),
                    ("股票名称", xsg_stock_name.at[idx]),
                ] if not str(value).strip()
            ]
            if xsg_price.at[idx] <= 0:
                missing.append("每股计税价格")
            if xsg_quantity.at[idx] <= 0:
                missing.append("转让股数")
            if missing:
                declaration_validation_issues += 1
                issues.append({
                    "issue_type": "限售股申报必填项异常",
                    "message": f"限售股源表第 {int(idx) + 2} 行 {xsg_name.at[idx] or '未填姓名'} 缺失或无效：{'、'.join(missing)}",
                    "row_number": int(idx) + 2,
                    "missing_fields": missing,
                })
        xsg["合理税费"] = (
            number_series(xsg, ["卖出经手费"])
            + number_series(xsg, ["卖出印花税"])
            + number_series(xsg, ["手续费"])
            + number_series(xsg, ["卖出过户费"])
        )
        xsg["限售股申报金额"] = (
            number_series(xsg, ["成交价格", "*每股计税价格(元/股)"])
            * number_series(xsg, ["成交数量", "*转让股数(股)"])
            - number_series(xsg, ["原值总金额", "限售股原值"])
            - xsg["合理税费"]
            - number_series(xsg, ["准予扣除的捐赠额"])
        ).round(2).clip(lower=0)
        xsg["限售股税费(申报表)"] = (xsg["限售股申报金额"] * 0.2).round(2)

    if not lxs.empty:
        lxs["机构代码"] = text_series(lxs, ["机构代码", "分支机构代码"]).map(normalize_org_code)
        rate = text_series(lxs, ["税率（%）", "*税率"], "0").str.rstrip("%")
        lxs["利息税申报金额"] = number_series(lxs, ["债券兑息", "*收入"])
        lxs_name = text_series(lxs, ["客户姓名", "姓名", "*姓名"])
        lxs_cert_type = text_series(lxs, ["证件类型", "*证件类型"])
        lxs_cert_number = text_series(lxs, ["证件号码", "*证件号码", "身份证号码"])
        numeric_rate = pd.to_numeric(rate, errors="coerce").fillna(0)
        for idx in lxs.index:
            missing = [
                label for label, value in [
                    ("机构代码", lxs.at[idx, "机构代码"]),
                    ("姓名", lxs_name.at[idx]),
                    ("证件类型", lxs_cert_type.at[idx]),
                    ("证件号码", lxs_cert_number.at[idx]),
                ] if not str(value).strip()
            ]
            if lxs.at[idx, "利息税申报金额"] <= 0:
                missing.append("收入")
            if numeric_rate.at[idx] <= 0 or numeric_rate.at[idx] > 100:
                missing.append("税率")
            if missing:
                declaration_validation_issues += 1
                issues.append({
                    "issue_type": "利息税申报必填项异常",
                    "message": f"利息税源表第 {int(idx) + 2} 行 {lxs_name.at[idx] or '未填姓名'} 缺失或无效：{'、'.join(missing)}",
                    "row_number": int(idx) + 2,
                    "missing_fields": missing,
                })
        lxs["利息税税费(申报表)"] = (
            lxs["利息税申报金额"] * numeric_rate / 100
        ).round(2)
        actual_withheld = number_series(lxs, ["兑息扣税"])
        source_withheld_present = text_series(lxs, ["兑息扣税"]) != ""
        source_withheld_mismatch = source_withheld_present & (
            (actual_withheld.abs() - lxs["利息税税费(申报表)"]).abs() > 0.01
        )
        if source_withheld_mismatch.any():
            interest_source_withheld_warnings = int(source_withheld_mismatch.sum())
            issues.append({
                "issue_type": "兑息扣税金额提示",
                "severity": "warning",
                "message": f"发现 {interest_source_withheld_warnings} 条债券兑息的源表扣税金额与按税率计算结果不一致",
            })

    xsg_summary = (
        xsg.pivot_table(index="机构代码", values="限售股税费(申报表)", aggfunc="sum").reset_index()
        if "限售股税费(申报表)" in xsg.columns
        else pd.DataFrame(columns=["机构代码", "限售股税费(申报表)"])
    )
    lxs_summary = (
        lxs.pivot_table(index="机构代码", values="利息税税费(申报表)", aggfunc="sum").reset_index()
        if "利息税税费(申报表)" in lxs.columns
        else pd.DataFrame(columns=["机构代码", "利息税税费(申报表)"])
    )

    if not balance.empty:
        balance["公司段"] = text_series(balance, ["公司段"])
        subject = text_series(balance, ["会计科目"])
        currency = text_series(balance, ["币种"])
        credit = number_series(balance, ["贷方金额(N)", "贷方金额"])
        bal = balance.assign(_subject=subject, _currency=currency, _credit=credit)
        xsg_balance = bal[(bal["_subject"].astype(str) == "21510009") & (bal["_currency"] == "CNY")][["公司段", "_credit"]].rename(columns={"_credit": "限售股税费(余额表)"})
        lxs_balance = bal[(bal["_subject"].astype(str) == "21510008") & (bal["_currency"] == "CNY")][["公司段", "_credit"]].rename(columns={"_credit": "利息税税费(余额表)"})
        companies = balance[["公司段"]].drop_duplicates()
        final = companies.merge(xsg_balance, on="公司段", how="left").merge(lxs_balance, on="公司段", how="left")
        final = final.merge(xsg_summary.rename(columns={"机构代码": "公司段"}), on="公司段", how="left")
        final = final.merge(lxs_summary.rename(columns={"机构代码": "公司段"}), on="公司段", how="left").fillna(0)
        final["限售股差额"] = (final["限售股税费(余额表)"] - final["限售股税费(申报表)"]).round(2)
        final["利息税差额"] = (final["利息税税费(余额表)"] - final["利息税税费(申报表)"]).round(2)
        mismatch = final[(final["限售股差额"] != 0) | (final["利息税差额"] != 0)]
        issues += [
            {"issue_type": "余额表差异", "message": f"{row['公司段']} 存在限售股/利息税差额"}
            for _, row in mismatch.iterrows()
        ]
    else:
        companies = pd.DataFrame({"公司段": pd.concat([xsg_summary["机构代码"], lxs_summary["机构代码"]], ignore_index=True).dropna().unique()})
        final = companies.merge(xsg_summary.rename(columns={"机构代码": "公司段"}), on="公司段", how="left")
        final = final.merge(lxs_summary.rename(columns={"机构代码": "公司段"}), on="公司段", how="left").fillna(0)
    reconciliation_rows = (
        json.loads(final[final["限售股差额"].ne(0) | final["利息税差额"].ne(0)].to_json(orient="records"))
        if not balance.empty
        else []
    )
    detail = pd.concat([xsg.assign(所得类型="限售股"), lxs.assign(所得类型="利息税")], ignore_index=True, sort=False)
    metrics = {
        "restricted_stock_records": int(len(xsg)),
        "restricted_stock_declared_amount": float(xsg.get("限售股申报金额", pd.Series(dtype=float)).sum()),
        "restricted_stock_withheld_tax": float(xsg.get("限售股税费(申报表)", pd.Series(dtype=float)).sum()),
        "interest_records": int(len(lxs)),
        "interest_declared_amount": float(lxs.get("利息税申报金额", pd.Series(dtype=float)).sum()),
        "interest_withheld_tax": float(lxs.get("利息税税费(申报表)", pd.Series(dtype=float)).sum()),
        "interest_source_withheld_warnings": interest_source_withheld_warnings,
    }
    metrics["total_records"] = metrics["restricted_stock_records"] + metrics["interest_records"]
    metrics["total_declared_amount"] = metrics["restricted_stock_declared_amount"] + metrics["interest_declared_amount"]
    metrics["total_withheld_tax"] = metrics["restricted_stock_withheld_tax"] + metrics["interest_withheld_tax"]
    return {
        "detail": detail,
        "summary": final,
        "issues": issues,
        "metrics": metrics,
        "reconciliation_rows": reconciliation_rows,
        "block_declarations": declaration_validation_issues > 0,
    }


def general_salary_tax_transform(frames_by_role: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    salary_frames = [
        normalize_general_salary_frame(role, df)
        for role, df in frames_by_role.items()
        if role in GENERAL_SALARY_ROLES
    ]
    salary = pd.concat(salary_frames, ignore_index=True, sort=False) if salary_frames else pd.DataFrame()
    staff = frames_by_role.get("staff_info", pd.DataFrame()).copy()
    issues: List[Dict[str, Any]] = []
    if salary.empty:
        return {"detail": salary, "summary": pd.DataFrame(), "issues": [{"issue_type": "缺失输入", "message": "缺少工资表"}]}
    tax_diff = salary[(salary["个税差异"] != 0) & (salary["本期应预扣预缴税额 SUM"] != 0)].copy()
    issues += [
        {"issue_type": "金额不一致", "message": f"{row.get('*姓名', '')} 个税差异 {row['个税差异']:.2f}"}
        for _, row in tax_diff.iterrows()
    ]
    changes = staff_change_analysis(staff, salary) if not staff.empty else {}
    for name, frame in changes.items():
        if not frame.empty:
            issues.append({"issue_type": "人员状态冲突", "message": f"{name} {len(frame)} 条"})
    detail = merge_staff_for_general_salary(salary, staff)
    missing_certificate = detail[detail["*证件号码"].fillna("").astype(str).str.strip() == ""].copy()
    if not missing_certificate.empty:
        issues.append({"issue_type": "人员状态冲突", "message": f"工资单存在 {len(missing_certificate)} 条人员信息未匹配，申报证件信息为空"})

    for column in GENERAL_TAX_TEMPLATE_COLUMNS:
        if column not in detail.columns:
            detail[column] = 0 if column not in {"工号", "*姓名", "*证件类型", "*证件号码", "备注"} else ""
    output_columns = GENERAL_TAX_TEMPLATE_COLUMNS + ["机构代码", "工资单类型"]
    detail_output = detail[output_columns].copy()
    summary = general_salary_summary(salary)
    extra_sheets = {
        "个税差异": tax_diff,
        "未匹配人员信息": missing_certificate,
        **changes,
    }
    return {"detail": detail_output, "summary": summary, "issues": issues, "extra_sheets": extra_sheets}
