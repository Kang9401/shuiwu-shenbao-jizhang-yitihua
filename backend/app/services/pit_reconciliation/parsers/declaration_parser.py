from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


def _text(value) -> str:
    return "" if value is None or pd.isna(value) else str(value).strip()


def _find_start(sheet: pd.DataFrame) -> int | None:
    for index, row in sheet.iterrows():
        if _text(row.iloc[0]) in {"1", "1.0"} and len(row) > 1 and _text(row.iloc[1]):
            return int(index)
    return None


def _metadata(values: list[str]) -> dict[str, str]:
    text = " ".join(values)
    result = {}
    for key, pattern in (("tax_period", r"税款所属期[：:]\s*([^\s]+)"), ("agent_name", r"扣缴义务人名称[：:]\s*([^\s]+)"), ("agent_id", r"(?:纳税人识别号|扣缴义务人编码)[^：:]*[：:]\s*([^\s]+)")):
        match = re.search(pattern, text)
        result[key] = match.group(1).strip() if match else ""
    return result


def parse_declaration_file(path: str | Path) -> tuple[list[dict], list[dict]]:
    """Flatten the official multi-row declaration exports without losing source columns."""
    workbook = pd.ExcelFile(path)
    records: list[dict] = []; issues: list[dict] = []
    for sheet_name in workbook.sheet_names:
        raw = pd.read_excel(path, sheet_name=sheet_name, header=None, dtype=object).fillna("")
        start = _find_start(raw)
        if start is None:
            continue
        metadata = _metadata([_text(value) for value in raw.iloc[:start].to_numpy().flatten()])
        headers = []
        for column in range(raw.shape[1]):
            parts = []
            for row in range(min(4, start)):
                value = _text(raw.iat[row, column])
                if value and value not in parts and not re.fullmatch(r"[\d⑴-⑿]+", value): parts.append(value)
            headers.append("_".join(parts) or f"Col_{column + 1}")
        for _, values in raw.iloc[start:].iterrows():
            if "合计" in _text(values.iloc[0]): break
            if not any(_text(value) for value in values): continue
            row = {headers[index]: value for index, value in enumerate(values)}
            row.update(metadata); row["sheet_name"] = sheet_name
            records.append(row)
    if not records: issues.append({"issue_type": "no_declaration_rows", "message": "未识别到个税申报明细行"})
    return records, issues
