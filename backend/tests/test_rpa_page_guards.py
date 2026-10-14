from pathlib import Path
import sys


VENDOR_DIR = Path(__file__).parents[1] / "vendor" / "etax_rpa"
sys.path.insert(0, str(VENDOR_DIR))

from etax_batch_export import COMMON_POPUP_TITLES, POPUP_CLOSE_SELECTOR, WORKFLOW_DIALOG_MARKERS  # noqa: E402
import etax_tax_certificate_download as certificate_download  # noqa: E402
from etax_batch_export import TaxOrg  # noqa: E402
from etax_tax_certificate_download import (  # noqa: E402
    is_comprehensive_income_overview_url,
    visible_comprehensive_income_status,
)


class FakeStatusLocator:
    def __init__(self, visible):
        self.visible = visible

    def filter(self, **_kwargs):
        return self

    def count(self):
        return int(self.visible)


class FakeStatusPage:
    def __init__(self, status):
        self.status = status

    def get_by_text(self, text, exact=True):
        return FakeStatusLocator(text == self.status)


def test_common_popups_include_unregistered_app_reminder():
    assert "未注册个税APP提醒" in COMMON_POPUP_TITLES


def test_common_popups_include_natural_person_invoice_reminder_and_close_button():
    assert "自然人代开发票提醒" in COMMON_POPUP_TITLES
    assert ".el-message-box__headerbtn" in POPUP_CLOSE_SELECTOR


def test_required_workflow_dialogs_are_not_treated_as_generic_reminders():
    assert {"请选择为哪个单位办税", "安全验证", "导出报表文件", "文件导入"} <= set(WORKFLOW_DIALOG_MARKERS)


def test_comprehensive_income_overview_rejects_salary_child_page():
    overview = "https://etax.chinatax.gov.cn/withholding/index.html?token=x#/withholding/income_declaration"
    salary = f"{overview}/salary?incomeTypeCode=0101"

    assert is_comprehensive_income_overview_url(overview)
    assert not is_comprehensive_income_overview_url(salary)


def test_comprehensive_income_status_reports_unfiled_period():
    assert visible_comprehensive_income_status(FakeStatusPage("未申报")) == "未申报"


def test_comprehensive_income_download_skips_when_no_successful_report(monkeypatch):
    page = type("FakePage", (), {"wait_for_timeout": lambda self, _timeout: None})()
    monkeypatch.setattr(certificate_download, "enter_comprehensive_income_page", lambda *_args: None)
    monkeypatch.setattr(certificate_download, "visible_comprehensive_income_status", lambda *_args: "未申报")
    monkeypatch.setattr(
        certificate_download,
        "open_withholding_report_export",
        lambda *_args: (_ for _ in ()).throw(AssertionError("export flow must not run")),
    )
    monkeypatch.setattr(
        certificate_download,
        "solve_report_export_security",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("security flow must not run")),
    )

    assert certificate_download.download_comprehensive_income_report(page, TaxOrg("机构A", "10001"), "2026-07") is None
