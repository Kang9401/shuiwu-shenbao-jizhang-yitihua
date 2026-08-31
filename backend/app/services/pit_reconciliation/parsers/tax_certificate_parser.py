from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

def parse_tax_certificate_pdf(path: str | Path) -> tuple[list[dict], list[dict]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError as exc:
            return [], [{"issue_type": "missing_pdf_library", "message": str(exc)}]
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    except Exception as exc:
        return [], [{"issue_type": "pdf_read_error", "message": str(exc)}]
    taxpayer = re.search(r"纳税人名称[：:]?\s*([^\n]+)", text)
    period = re.search(r"税款所属期[：:]?\s*([0-9]{4}[\-年][0-9]{1,2}[^\s]*)", text)
    rows = []
    pattern = re.compile(r"(个人所得税)[\s\S]{0,100}?([0-9]{4}\s*[-年]\s*[0-9]{1,2}[^\s]*)[\s\S]{0,100}?([\d,]+\.\d{2})")
    for tax_type, tax_period, amount in pattern.findall(text):
        rows.append({"taxpayer_name": taxpayer.group(1).strip() if taxpayer else "", "tax_type": tax_type, "tax_period": tax_period, "amount": Decimal(amount.replace(",", ""))})
    if not rows:
        return [], [{"issue_type": "not_pit_certificate", "message": "未在完税证明中识别到个人所得税明细"}]
    return rows, []
