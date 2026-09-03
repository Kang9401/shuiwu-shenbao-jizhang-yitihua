from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path


_PERIOD = r"(?:\d{4}[年./-]\d{1,2}(?:月|[./-])\d{1,2}(?:日)?(?:至|-|—)\d{4}[年./-]\d{1,2}(?:月|[./-])\d{1,2}(?:日)?)"
_DETAIL = re.compile(rf"个人所得税\s+(?P<item>.+?)\s+(?P<period>{_PERIOD})\s+(?P<amount>[\d,]+(?:\.\d{{1,2}})?)")


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\u00a0", " ")).strip()


def parse_tax_certificate_pdf(path: str | Path) -> tuple[list[dict], list[dict]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError as exc:
            return [], [{"issue_type": "missing_pdf_library", "message": str(exc)}]
    try:
        reader = PdfReader(str(path))
        text = _text("\n".join(page.extract_text() or "" for page in reader.pages))
    except Exception as exc:
        return [], [{"issue_type": "pdf_read_error", "message": str(exc)}]

    taxpayer_match = re.search(r"纳税人名称\s*[：:]?\s*(.+?)(?=\s+(?:原凭证号|税种|品目名称|税款所属)|$)", text)
    taxpayer_name = taxpayer_match.group(1).strip() if taxpayer_match else ""
    org_match = re.match(r"(\d{5})[-_]", Path(path).name)
    org_code = org_match.group(1) if org_match else ""

    rows: list[dict] = []
    for match in _DETAIL.finditer(text):
        amount = Decimal(match.group("amount").replace(",", "")).quantize(Decimal("0.01"))
        rows.append({
            "org_code": org_code,
            "taxpayer_name": taxpayer_name,
            "tax_type": "个人所得税",
            "income_item": match.group("item").strip(),
            "tax_period": match.group("period").replace(" ", ""),
            "amount": amount,
        })
    if not rows:
        return [], [{"issue_type": "not_pit_certificate", "message": "未在完税证明中识别到个人所得税明细"}]

    issues: list[dict] = []
    total_matches = re.findall(r"金额合计[\s\S]{0,160}?[¥￥]\s*([\d,]+(?:\.\d{1,2})?)", text)
    if total_matches:
        declared_total = sum((Decimal(value.replace(",", "")).quantize(Decimal("0.01")) for value in total_matches), Decimal("0.00"))
        detail_total = sum((row["amount"] for row in rows), Decimal("0.00"))
        if abs(detail_total - declared_total) > Decimal("0.01"):
            issues.append({
                "issue_type": "certificate_total_mismatch",
                "message": f"完税凭证解析校验失败：明细合计 {detail_total:.2f} 与 PDF 总金额 {declared_total:.2f} 不一致（容差 0.01）",
            })
    return rows, issues
