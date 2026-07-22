from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook
from pydantic import ValidationError

from app.rpa.extensions.etax_extra_income_reports import (
    REPORT_SPECS,
    export_record_matches,
    load_site_config,
    report_path,
    resolve_orgs,
    validate_report_xlsx,
)
from app.schemas.rpa import RpaTaskStartRequest


def write_report(path: Path, keyword: str, month: str = "2026-06", org_code: str = "11818", org_name: str = "机构A") -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([keyword, "个人所得税扣缴申报表"])
    sheet.append(["税款所属月份", month, "机构代码", org_code])
    sheet.append(["机构名称", org_name])
    for row in range(80):
        sheet.append([f"测试数据 {row}", "x" * 50])
    workbook.save(path)


def test_captured_selector_config_is_available_without_runtime_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ETAX_EXTRA_INCOME_REPORTS_CONFIG", raising=False)
    config = load_site_config(tmp_path / "missing.json")
    assert config["current_org_scope"] == ".company-name"
    assert config["status_value"] == ".declare-status .dstatus"
    assert config["export_dialog"] == ".export-result-list-message-dialog:visible"


def test_xlsx_validation_accepts_expected_report_and_rejects_invalid_inputs(tmp_path):
    spec = REPORT_SPECS[0]
    valid = tmp_path / "valid.xlsx"
    wrong_report = tmp_path / "wrong_report.xlsx"
    wrong_month = tmp_path / "wrong_month.xlsx"
    not_xlsx = tmp_path / "not.xlsx"
    write_report(valid, "分类所得")
    write_report(wrong_report, "限售股")
    write_report(wrong_month, "分类所得", month="2026-05")
    not_xlsx.write_bytes(b"x" * 2048)

    assert validate_report_xlsx(valid, spec, "2026-06", "11818", "机构A")[0] is True
    assert validate_report_xlsx(wrong_report, spec, "2026-06", "11818", "机构A")[0] is False
    assert validate_report_xlsx(wrong_month, spec, "2026-06", "11818", "机构A")[0] is False
    assert validate_report_xlsx(not_xlsx, spec, "2026-06", "11818", "机构A")[0] is False


def test_fixed_output_name_and_org_selection(tmp_path, monkeypatch):
    monkeypatch.setattr("app.rpa.extensions.etax_extra_income_reports.OUTPUT_DIR", tmp_path)
    orgs = [SimpleNamespace(name="机构 A", code="11818"), SimpleNamespace(name="机构B", code="11831")]
    assert report_path(REPORT_SPECS[1], "2026-12", orgs[0]).name == "2026-12_11818_机构 A_限售股所得申报表.xlsx"
    assert [item.code for item in resolve_orgs(orgs, None, None, "11831")] == ["11831"]
    assert [item.code for item in resolve_orgs(orgs, "11818", None, None)] == ["11818"]


def test_schema_accepts_extension_task_and_rejects_unknown_key():
    request = RpaTaskStartRequest(task_key="extra_income_reports", month="2026-06")
    assert request.task_key == "extra_income_reports"
    with pytest.raises(ValidationError):
        RpaTaskStartRequest(task_key="unknown", month="2026-06")


def test_export_record_match_requires_org_report_month_success_and_download():
    spec = REPORT_SPECS[0]
    valid = "机构A_分类所得申报_202606.xlsx 2026-07-06 处理成功 下载"
    assert export_record_matches(valid, "机构A", "2026-06", spec)
    assert not export_record_matches(valid, "机构B", "2026-06", spec)
    assert not export_record_matches(valid, "机构A", "2026-05", spec)
    assert not export_record_matches(valid.replace("处理成功", "处理中"), "机构A", "2026-06", spec)
