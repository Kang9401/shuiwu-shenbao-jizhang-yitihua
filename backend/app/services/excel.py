from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


def read_excel(path: str | Path, dtype: Any = str) -> pd.DataFrame:
    return pd.read_excel(path, dtype=dtype)


def dataframe_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    clean = df.copy()
    clean = clean.where(pd.notna(clean), None)
    return clean.to_dict(orient="records")


def normalize_emp_id(value: Any) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text or None


def to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or pd.isna(value) or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def pick_column(row: dict[str, Any], candidates: list[str]) -> Any:
    for key in candidates:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _text_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Serialize every cell as text for tax-bureau import templates."""
    result = df.copy()
    for column in result.columns:
        result[column] = result[column].map(
            lambda value: "" if value is None or pd.isna(value) else str(value)
        )
    return result


def write_workbook(
    path: str | Path,
    sheets: dict[str, pd.DataFrame],
    *,
    text_values: bool = False,
) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = sheet_name[:31] or "Sheet1"
            output = _text_frame(df) if text_values else df
            output.to_excel(writer, sheet_name=safe_name, index=False)
