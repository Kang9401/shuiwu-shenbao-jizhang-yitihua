from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace

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


def test_certificate_parser_keeps_period_payment_date_amount_and_filename_org_code(monkeypatch, tmp_path):
    class Page:
        def extract_text(self):
            return "纳税人名称：测试营业部 原凭证号 税种 品目名称 税款所属时期 入（退）库日期 实缴（退）金额 个人所得税 限售股转让所得 2026.08.01-2026.08.31 2026.09.04 1,863.54"
    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=lambda _: SimpleNamespace(pages=[Page()])))
    path = tmp_path / "2026-08_10615_xxx.pdf"
    path.write_bytes(b"synthetic")
    rows, issues = parse_tax_certificate_pdf(path)
    assert issues == []
    assert rows == [{"org_code": "10615", "taxpayer_name": "测试营业部", "taxpayer_id": "", "tax_type": "个人所得税", "income_item": "限售股转让所得", "tax_period": "2026.08.01-2026.08.31", "payment_date": "2026.09.04", "amount": Decimal("1863.54")}]


def test_certificate_total_mismatch_does_not_return_rows(monkeypatch, tmp_path):
    class Page:
        def extract_text(self):
            return "个人所得税 其他偶然所得 2026.08.01-2026.08.31 2026.09.04 100.00 金额合计 ¥ 99.00"
    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=lambda _: SimpleNamespace(pages=[Page()])))
    path = tmp_path / "2026-08_10615_xxx.pdf"
    path.write_bytes(b"synthetic")
    rows, issues = parse_tax_certificate_pdf(path)
    assert rows == []
    assert [issue["issue_type"] for issue in issues] == ["certificate_total_mismatch"]


def test_certificate_parser_normalizes_wrapped_branch_name(monkeypatch, tmp_path):
    class Page:
        def extract_text(self):
            return "纳税人名称：广发证券股份有限公司佛山顺德大良保利国际金融中心证\n券营业部 原凭证号 税种 品目名称 税款所属时期 入（退）库日期 实缴（退）金额 个人所得税 限售股转让所得 2026.08.01-2026.08.31 2026.09.04 1,863.54"
    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=lambda _: SimpleNamespace(pages=[Page()])))
    path = tmp_path / "2026-08_10615_xxx.pdf"
    path.write_bytes(b"synthetic")
    rows, issues = parse_tax_certificate_pdf(path)
    assert issues == []
    assert rows[0]["taxpayer_name"] == "广发证券股份有限公司佛山顺德大良保利国际金融中心证券营业部"
