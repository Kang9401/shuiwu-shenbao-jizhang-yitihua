from pathlib import Path

import pandas as pd

from app.rpa.log_parser import parse_log_line
from app.rpa.state_store import migrate_state
from app.services.generation import DECLARATION_OUTPUT_FIELDS, SALARY_RECONCILIATION_ONLY_FIELDS
from app.services.salary_classifier import classify_salary_frame, normalize_payroll_files, normalize_salary_role
from app.services.verification import check_taxpayer_org_mapping, load_rank_payroll


def test_salary_roles_are_normalized_without_silent_overwrite():
    assert normalize_salary_role("branch_salary") == "marketing_salary"
    assert normalize_salary_role("digital_ops_salary") == "marketing_salary"
    assert normalize_salary_role("advisor_salary") == "marketing_salary"
    try:
        normalize_payroll_files([("marketing_salary", "a.xlsx"), ("branch_salary", "b.xlsx")])
    except ValueError as exc:
        assert "多份" in str(exc)
    else:
        raise AssertionError("duplicate marketing payrolls must be rejected")


def test_salary_classifier_uses_employee_id_and_keeps_broker_independent():
    assert classify_salary_frame(pd.DataFrame({"员工编号": ["00123.0", "12345"]})).role == "rank_salary"
    assert classify_salary_frame(pd.DataFrame({"员工编号": ["0123456", "1234567"]})).role == "marketing_salary"
    assert classify_salary_frame(pd.DataFrame(columns=[f"c{i}" for i in range(27)])).role == "broker_salary"


def test_payroll_cumulative_deductions_are_retained_but_excluded_from_declaration(tmp_path: Path):
    source = tmp_path / "rank.xlsx"
    pd.DataFrame({
        "员工编号": ["00123"], "姓名": ["测试员工"], "机构代码": ["10001"], "应发合计": [100],
        "累计当月子女教育附加扣除": [1200], "累计个人养老金": [300],
    }).to_excel(source, index=False)
    result = load_rank_payroll(str(source))
    assert result.loc[0, "工资单_累计子女教育扣除"] == 1200
    assert result.loc[0, "工资单_累计个人养老金"] == 300
    assert DECLARATION_OUTPUT_FIELDS.isdisjoint(SALARY_RECONCILIATION_ONLY_FIELDS)


def test_payroll_org_code_is_mapped_from_withholding_taxpayer_id(tmp_path: Path):
    source = tmp_path / "rank-taxpayer.xlsx"
    pd.DataFrame({
        "员工编号": ["00123"],
        "姓名": ["测试员工"],
        "个税扣缴义务人纳税人识别号": [" 9132 abcd "],
        "应发合计": [100],
    }).to_excel(source, index=False)

    result = load_rank_payroll(str(source), {"9132ABCD": "10001"})
    assert result.loc[0, "机构代码"] == "10001"
    assert result.loc[0, "个税扣缴义务人纳税人识别号"] == "9132ABCD"
    assert check_taxpayer_org_mapping(result) == {"has_issues": False, "items": []}


def test_payroll_unknown_taxpayer_id_is_blocking_and_legacy_org_code_is_compatible(tmp_path: Path):
    source = tmp_path / "rank-unknown.xlsx"
    pd.DataFrame({
        "员工编号": ["00123", "00124"],
        "姓名": ["映射失败", "旧格式"],
        "机构代码": ["", "10002"],
        "个税扣缴义务人纳税人识别号": ["UNKNOWN", ""],
        "应发合计": [100, 200],
    }).to_excel(source, index=False)

    result = load_rank_payroll(str(source), {"KNOWN": "10001"})
    report = check_taxpayer_org_mapping(result)
    assert result.loc[1, "机构代码"] == "10002"
    assert report["has_issues"] is True
    assert report["items"][0]["name"] == "映射失败"
    assert "找不到" in report["items"][0]["message"]


def test_rpa_v1_state_migration_is_idempotent_and_does_not_fabricate_split_results():
    legacy = {"results": {"2026-06": {"10001": {"name": "测试营业部", "income_report": "成功 1笔", "extra_income_reports": "成功 2笔"}}}}
    migrated = migrate_state(legacy)
    row = migrated["results"]["2026-06"]["10001"]
    assert migrated["state_version"] == 2
    assert row["comprehensive_income_report"]["status"] == "success"
    assert row["classified_income_report"]["status"] == "pending"
    assert row["restricted_stock_report"]["reason"] == "历史数据未拆分"
    assert migrate_state(migrated) == migrated


def test_structured_extra_income_result_marker_distinguishes_skipped_from_failed():
    events = parse_log_line("[RPA_RESULT] org_code=10001 category=classified_income status=skipped count=0 reason=no_records", "extra_income_reports")
    assert events[0].category == "classified_income"
    assert events[0].status == "skipped"
    assert events[0].reason == "no_records"
