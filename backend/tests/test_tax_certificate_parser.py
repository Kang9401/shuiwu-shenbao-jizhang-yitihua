from decimal import Decimal
from pathlib import Path

from app.services.pit_reconciliation.parsers.tax_certificate_parser import parse_tax_certificate_pdf


def test_real_dot_period_certificate_and_multi_page_total():
    path = Path("个税测试/成都核对底稿测试/完税证明/13248-202607综合所得&分类所得.pdf")
    if not path.exists():
        return
    rows, issues = parse_tax_certificate_pdf(path)
    assert len(rows) == 6
    assert sum(row["amount"] for row in rows) == Decimal("315181.47")
    assert issues == []
    assert rows[0]["tax_period"] == "2026.07.01-2026.07.31"
