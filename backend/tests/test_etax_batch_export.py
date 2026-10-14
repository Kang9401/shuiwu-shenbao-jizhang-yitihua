import sys
from pathlib import Path


VENDOR_DIR = Path(__file__).parents[1] / "vendor" / "etax_rpa"
if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

import etax_batch_export as module


class FakeLocator:
    def __init__(self, page, kind="generic"):
        self.page = page
        self.kind = kind
        self.first = self

    def filter(self, **_kwargs):
        return self

    def wait_for(self, **_kwargs):
        return None

    def input_value(self, **_kwargs):
        return self.page.current_value

    def click(self, **_kwargs):
        if self.kind == "month":
            self.page.current_value = "2026年10月"

    def locator(self, selector, **_kwargs):
        return FakeLocator(self.page, "month" if ".el-month-table" in selector else "generic")


class FakePage:
    def __init__(self):
        self.current_value = "2026年9月"
        self.waits = []

    def locator(self, selector, **_kwargs):
        return FakeLocator(self, "input" if "input" in selector else "generic")

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)


def test_set_tax_month_closes_immediate_and_delayed_previous_period_popup(monkeypatch):
    page = FakePage()
    closes = []
    monkeypatch.setattr(module, "close_common_popups", lambda value: closes.append(value))

    module.set_tax_month(page, "2026-10")

    assert page.current_value == "2026年10月"
    assert page.waits == [1200, 2200]
    assert closes == [page, page, page]


def test_previous_period_popup_marker_matches_tax_site_wording():
    assert "上一属期未申报" in module.TAX_REMINDER_MARKERS


def test_known_popup_marker_matches_spaced_tax_site_title():
    assert module._known_popup_marker("自 然 人 代 开 发 票 提 醒 尊敬的扣缴义务人") == "自然人代开发票提醒"
