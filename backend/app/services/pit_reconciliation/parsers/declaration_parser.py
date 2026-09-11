from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd


GENERAL_HEADERS = [
    "序号", "姓名", "身份证件类型", "身份证件号码", "纳税人识别号", "是否为非居民个人", "所得项目",
    "收入", "费用", "免税收入", "减除费用", "基本养老保险费", "基本医疗保险费", "失业保险费",
    "住房公积金", "年金", "商业健康保险", "税延养老保险", "财产原值", "允许扣除的税费",
    "公务交通费用", "通讯费用", "律师办案费用", "住房公积金调整", "展业成本", "西藏附加减除费用", "修缮费用",
    "向出租方支付的租金", "有关合理费用", "其他", "累计收入额", "累计减除费用", "累计专项扣除",
    "子女教育", "赡养老人", "住房贷款利息", "住房租金", "继续教育", "3岁以下婴幼儿照护",
    "累计个人养老金", "累计其他扣除", "减按计税比例", "准予扣除的捐赠额", "累计应纳税所得额",
    "税率/预扣率", "速算扣除数", "应纳税额", "减免税额", "协定减免", "已缴税额", "应补退税额", "备注",
]
LEGACY_GENERAL_HEADERS = [header for header in GENERAL_HEADERS if header != "住房公积金调整"]

RESTRICTED_HEADERS = [
    "序号", "纳税人姓名", "证件类型", "证件号码", "Col_5", "证券账户号", "股票代码", "股票名称",
    "每股计税价格", "转让股数", "Col_11", "转让收入额", "原值及合理税费小计", "原值", "合理税费",
    "Col_16", "准予扣除的捐赠额", "应纳税所得额", "税率", "协定减免", "扣缴税额",
]


def _text(value: Any) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _is_sequence(value: Any) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.0)?", _text(value)))


def _metadata(sheet: pd.DataFrame) -> dict[str, str]:
    rows = [[_text(value) for value in row.tolist()] for _, row in sheet.iloc[:12].iterrows()]
    flat_text = " ".join(value for row in rows for value in row if value)

    def find(pattern: str) -> str:
        match = re.search(pattern, flat_text)
        return match.group(1).strip() if match else ""

    result = {
        "tax_period": find(r"税款所属期\s*[：:]\s*([^\s]+)"),
        "agent_id": find(r"(?:扣缴义务人纳税人识别号(?:（统一社会信用代码）)?|扣缴义务人编码|纳税人识别号)\s*[：:]\s*([0-9A-Z]+)"),
        "agent_name": find(r"扣缴义务人名称\s*[：:]\s*([^\s]+)"),
    }
    if not result["agent_name"]:
        for row in rows:
            for index, value in enumerate(row):
                if value.replace("：", "").replace(":", "").strip() != "扣缴义务人名称":
                    continue
                result["agent_name"] = next((item for item in row[index + 1:] if item), "")
                break
            if result["agent_name"]:
                break
    return result


def _record(headers: list[str], values: pd.Series, metadata: dict[str, str], sheet_name: str) -> dict[str, Any]:
    row = {headers[index]: value for index, value in enumerate(values.iloc[:len(headers)])}
    row.update(metadata)
    row["sheet_name"] = sheet_name
    return row


def _parse_official_general(sheet: pd.DataFrame, sheet_name: str) -> tuple[list[dict], bool]:
    header_text = " ".join(_text(value) for value in sheet.iloc[:8].to_numpy().flatten())
    if "个人所得税扣缴申报表" not in header_text or sheet.shape[1] < 50:
        return [], False
    numbering_row = next(
        (int(index) for index, row in sheet.iterrows() if len(row) >= 10 and all(_is_sequence(row.iloc[column]) for column in range(10))),
        None,
    )
    if numbering_row is None:
        return [], True
    metadata = _metadata(sheet)
    headers = GENERAL_HEADERS if "住房公积金调整" in header_text else LEGACY_GENERAL_HEADERS
    records = []
    for _, values in sheet.iloc[numbering_row + 1:].iterrows():
        if not _is_sequence(values.iloc[0]) or not (_text(values.iloc[1]) or _text(values.iloc[3])):
            continue
        records.append(_record(headers, values, metadata, sheet_name))
    return records, True


def _parse_official_restricted(sheet: pd.DataFrame, sheet_name: str) -> tuple[list[dict], bool]:
    header_text = " ".join(_text(value) for value in sheet.iloc[:10].to_numpy().flatten())
    if "限售股转让所得个人所得税扣缴报告表" not in header_text or sheet.shape[1] < 20:
        return [], False
    metadata = _metadata(sheet)
    records = []
    for _, values in sheet.iterrows():
        if not _is_sequence(values.iloc[0]) or not (_text(values.iloc[1]) or _text(values.iloc[3])):
            continue
        row = _record(RESTRICTED_HEADERS, values, metadata, sheet_name)
        row["所得项目"] = "限售股转让所得"
        records.append(row)
    return records, True


def _looks_like_simple_template(sheet: pd.DataFrame) -> bool:
    known = {"工号", "*姓名", "*证件号码", "本期收入", "住房公积金调整"}
    return any(len({_text(value) for value in row.tolist()} & known) >= 3 for _, row in sheet.iterrows())


def _parse_simple_template(sheet: pd.DataFrame, sheet_name: str) -> tuple[list[dict], bool]:
    if not _looks_like_simple_template(sheet):
        return [], False
    known = {"工号", "*姓名", "*证件号码", "本期收入", "住房公积金调整"}
    header_row = next(
        int(index) for index, row in sheet.iterrows()
        if len({_text(value) for value in row.tolist()} & known) >= 3
    )
    headers = [_text(value) or f"Col_{column + 1}" for column, value in enumerate(sheet.iloc[header_row].tolist())]
    records = []
    for _, values in sheet.iloc[header_row + 1:].iterrows():
        if not any(_text(value) for value in values):
            continue
        row = {headers[index]: value for index, value in enumerate(values)}
        row.update(_metadata(sheet))
        row["sheet_name"] = sheet_name
        records.append(row)
    return records, True


def parse_declaration_file(path: str | Path) -> tuple[list[dict], list[dict]]:
    """Parse supported official PIT exports into stable, source-compatible fields."""
    workbook = pd.ExcelFile(path)
    records: list[dict] = []
    recognized_template = False
    for sheet_name in workbook.sheet_names:
        sheet = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=object).fillna("")
        for parser in (_parse_official_restricted, _parse_official_general, _parse_simple_template):
            parsed, recognized = parser(sheet, sheet_name)
            if not recognized:
                continue
            recognized_template = True
            records.extend(parsed)
            break
    issues = [] if records or recognized_template else [{"issue_type": "no_declaration_rows", "message": "未识别到个税申报明细行"}]
    return records, issues
