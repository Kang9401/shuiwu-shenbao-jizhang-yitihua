from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path


def _module():
    if "playwright.sync_api" not in sys.modules:
        playwright = types.ModuleType("playwright")
        sync_api = types.ModuleType("playwright.sync_api")
        sync_api.Page = type("Page", (), {})
        sync_api.TimeoutError = TimeoutError
        sync_api.sync_playwright = lambda: None
        playwright.sync_api = sync_api
        sys.modules["playwright"] = playwright
        sys.modules["playwright.sync_api"] = sync_api
    vendor = Path(__file__).parents[1] / "vendor" / "etax_rpa"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    return importlib.import_module("etax_tax_certificate_download")


def test_certificate_filename_uses_declaration_month_and_label():
    module = _module()
    org = module.TaxOrg(code="10001", name="测试营业部")
    item = {"report_type": "综合所得个人所得税扣缴申报表", "ticket_suffix": "1234"}

    assert module.certificate_filename(org, "2026-08", item) == (
        "2026-07_10001_测试营业部_个税完税证明_综合所得个人所得税扣缴申报表_1234.pdf"
    )
    assert module.previous_month("2026-01") == "2025-12"


def test_comprehensive_report_filename_removes_duplicate_org_identity():
    module = _module()
    org = module.TaxOrg(code="10001", name="测试营业部")

    assert module.comprehensive_report_filename(
        org,
        "2026-07",
        "测试营业部_个人所得税扣缴申报表_10001.xlsx",
    ) == "2026-07_10001_测试营业部_个人所得税扣缴申报表.xlsx"
