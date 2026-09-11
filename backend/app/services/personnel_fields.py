from __future__ import annotations

import pandas as pd


def text(value):
    if value is None or pd.isna(value):
        return ""
    value = str(value).strip()
    return "" if value.lower() in {"none", "nan", "nat"} else value


def with_foreign_defaults(record):
    result = dict(record)
    cert = text(result.get("证件类型"))
    if cert and cert not in {"居民身份证", "身份证"}:
        result["涉税事由"] = text(result.get("涉税事由")) or "其他"
        result["出生国家(地区)"] = text(result.get("出生国家(地区)")) or text(result.get("国籍(地区)"))
    return result


def missing_personnel_fields(record, *, employee=False):
    required = ["*姓名", "证件类型", "证件号码", "机构代码(人员信息表)"]
    if employee:
        required.append("员工编号")
    if text(record.get("人员状态")) in {"非正常", "离职"}:
        required += ["手机号码", "任职受雇从业日期"]
    if text(record.get("证件类型")) not in {"", "居民身份证", "身份证"}:
        required += ["国籍(地区)", "性别", "出生日期", "涉税事由", "出生国家(地区)"]
    return [column for column in required if not text(record.get(column))]
