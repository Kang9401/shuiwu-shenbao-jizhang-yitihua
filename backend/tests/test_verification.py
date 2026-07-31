from pathlib import Path

import pandas as pd

from app.services.verification import (
    analyze_deduction_matches,
    apply_deduction_matches,
    build_reconciliation_report,
    check_deduction_issues,
    check_payroll_org_format,
    check_personnel_changes,
    verify,
)


def test_deduction_duplicates_include_source_file_details(tmp_path: Path):
    first = tmp_path / "专项扣除A.xlsx"
    second = tmp_path / "专项扣除B.xlsx"
    pd.DataFrame([{"姓名": "张三", "证件号码": "110101199001010011", "累计子女教育": 1000}]).to_excel(first, index=False)
    pd.DataFrame([{"姓名": "张三", "证件号码": "110101199001010011", "累计住房租金": 1500}]).to_excel(second, index=False)

    result = check_deduction_issues(str(tmp_path))

    assert result["has_issues"] is True
    duplicate = result["duplicates"][0]
    assert duplicate["file_count"] == 2
    assert duplicate["file_names"] == "专项扣除A.xlsx、专项扣除B.xlsx"
    assert duplicate["details"][0]["deduction_summary"] == "子女教育 1000.00"


def test_payroll_org_code_requires_five_digits():
    sheet = pd.DataFrame([
        {"工资单类型": "职级工资单", "*姓名": "张三", "员工编号": "1001", "机构代码_工资单": "1030"},
        {"工资单类型": "职级工资单", "*姓名": "李四", "员工编号": "1002", "机构代码_工资单": "10301"},
    ])

    result = check_payroll_org_format(sheet)

    assert result["has_issues"] is True
    assert result["items"] == [{
        "payroll_type": "职级工资单",
        "name": "张三",
        "employee_id": "1001",
        "org_code": "1030",
        "message": "工资人员归属机构代码必须为 5 位数字",
    }]


def test_new_hire_missing_required_fields_cannot_be_confirmed_away():
    sheet = pd.DataFrame(
        [
            {
                "员工编号": "1001",
                "*姓名": "张三",
                "机构代码_工资单": "10301",
                "证件类型": "",
                "证件号码": "",
                "手机号码": "",
                "任职受雇从业日期": "",
            }
        ]
    )

    report = check_personnel_changes(
        sheet,
        confirmed_personnel=[
            {"name": "张三", "id_number": "", "change_type": "入职", "confirmed": True}
        ],
    )

    assert report["has_issues"] is True
    item = report["items"][0]
    assert item["change_type"] == "入职"
    assert item["can_confirm"] is False
    assert set(item["missing_fields"]) >= {"证件类型", "证件号码", "手机号码", "任职受雇从业日期"}


def test_complete_new_hire_can_be_confirmed_online():
    sheet = pd.DataFrame(
        [
            {
                "员工编号": "1001",
                "*姓名": "张三",
                "机构代码_工资单": "10301",
                "证件类型": "居民身份证",
                "证件号码": "",
                "手机号码": "13800000000",
                "任职受雇从业日期": "2025/04/01",
            }
        ]
    )

    report = check_personnel_changes(sheet)

    item = report["items"][0]
    assert item["change_type"] == "入职"
    assert item["missing_fields"] == ["证件号码"]
    assert item["can_confirm"] is False

    sheet.loc[0, "证件号码"] = "110101199001010011"
    report = check_personnel_changes(sheet)
    item = report["items"][0]
    assert item["missing_fields"] == []
    assert item["can_confirm"] is True

    confirmed = check_personnel_changes(
        sheet,
        confirmed_personnel=[
            {
                "name": "张三",
                "id_number": "110101199001010011",
                "change_type": "入职",
                "confirmed": True,
                "applied": True,
            }
        ],
    )
    assert confirmed["items"] == []


def test_complete_departure_can_be_confirmed_online_with_default_leave_date():
    sheet = pd.DataFrame(columns=["员工编号", "*姓名"])
    staff_df = pd.DataFrame(
        [
            {
                "员工编号": "1001",
                "*姓名": "李四",
                "证件号码": "110101199001010022",
                "机构代码": "10301",
                "手机号码": "13800000000",
                "离职日期": "",
            }
        ]
    )

    report = check_personnel_changes(sheet, staff_df=staff_df, year=2025, month=4)

    item = report["items"][0]
    assert item["change_type"] == "离职"
    assert item["leave_date"] == "2025/03/31"
    assert item["missing_fields"] == []
    assert item["can_confirm"] is True

    confirmed = check_personnel_changes(
        sheet,
        confirmed_personnel=[
            {
                "name": "李四",
                "id_number": "110101199001010022",
                "change_type": "离职",
                "confirmed": True,
                "applied": True,
            }
        ],
        staff_df=staff_df,
        year=2025,
        month=4,
    )
    assert confirmed["items"] == []


def test_transfer_like_change_is_enriched_for_frontend_report():
    sheet = pd.DataFrame(
        [
            {
                "员工编号": "",
                "*姓名": "张三",
                "机构代码_工资单": "10302",
                "证件类型": "",
                "证件号码": "",
                "手机号码": "",
                "任职受雇从业日期": "",
                "离职日期": "",
            }
        ]
    )
    staff_df = pd.DataFrame(
        [
            {
                "员工编号": "1001",
                "*姓名": "张三",
                "证件号码": "110101199001010011",
                "机构代码": "10301",
                "手机号码": "13800000000",
                "离职日期": "",
            }
        ]
    )

    report = check_personnel_changes(sheet, staff_df=staff_df, year=2025, month=4)
    hire = next(item for item in report["items"] if item["change_type"] == "入职")
    departure = next(item for item in report["items"] if item["change_type"] == "离职")

    assert hire["is_transfer_like"] is True
    assert hire["id_number"] == "110101199001010011"
    assert hire["employee_id"] == "1001"
    assert hire["phone"] == "13800000000"
    assert hire["hire_date"] == "2025/04/01"
    assert hire["leave_date"] == ""
    assert hire["missing_fields"] == []
    assert hire["can_confirm"] is True
    assert departure["leave_date"] == "2025/03/31"

    confirmed = check_personnel_changes(
        sheet,
        confirmed_personnel=[
            {
                "name": "张三",
                "id_number": "110101199001010011",
                "change_type": "入职",
                "is_transfer_like": True,
                "confirmed": True,
                "applied": True,
            }
        ],
        staff_df=staff_df,
        year=2025,
        month=4,
    )
    assert confirmed["items"] == []


def test_org_code_mismatch_is_reported_as_declaration_org_change():
    sheet = pd.DataFrame(
        [
            {
                "员工编号": "1001",
                "*姓名": "张三",
                "机构代码_工资单": "10302",
                "机构代码_人员信息表": "10301",
                "证件类型": "居民身份证",
                "证件号码": "110101199001010011",
                "手机号码": "13800000000",
                "任职受雇从业日期": "2025/04/01",
                "离职日期": "",
            }
        ]
    )

    report = check_personnel_changes(sheet, year=2025, month=4)

    assert report["has_issues"] is True
    assert len(report["items"]) == 2
    departure = next(item for item in report["items"] if item["change_type"] == "离职")
    hire = next(item for item in report["items"] if item["change_type"] == "入职")
    assert departure["is_transfer_like"] is True
    assert hire["is_transfer_like"] is True
    assert departure["org_code_from"] == "10301"
    assert hire["org_code_to"] == "10302"


def test_verify_returns_four_frontend_checks():
    sheet = pd.DataFrame(
        [
            {
                "员工编号": "1001",
                "*姓名": "张三",
                "机构代码_工资单": "10301",
                "机构代码_人员信息表": "",
                "证件类型": "",
                "证件号码": "",
                "手机号码": "",
                "任职受雇从业日期": "",
                "本期应预扣预缴税额 SUM": 100,
                "个人所得税 SUM": 90,
                "个税差异": 10,
            }
        ]
    )

    report = verify(sheet)

    checks = {item["code"]: item for item in report["checks"]}
    assert set(checks) == {
        "tax_diff", "personnel_changes", "missing_cert", "taxpayer_org_mapping", "deduction_warnings",
    }
    assert checks["tax_diff"]["status"] == "fail"
    assert checks["personnel_changes"]["status"] == "fail"
    assert checks["missing_cert"]["status"] == "pass"
    assert checks["deduction_warnings"]["status"] == "pass"


def test_deduction_match_reports_name_mismatch_and_ambiguous_masked_id():
    sheet = pd.DataFrame([
        {"*姓名": "张三", "证件号码": "110101199001010011", "机构代码_工资单": "10301"},
        {"*姓名": "李四", "证件号码": "220101199001010022", "机构代码_工资单": "10302"},
        {"*姓名": "李四", "证件号码": "230101199001010032", "机构代码_工资单": "10302"},
    ])
    deductions = pd.DataFrame([
        {"*姓名": "王五", "证件号码": "110101199001010011"},
        {"*姓名": "李四", "证件号码": "2****************2"},
    ])

    quality = analyze_deduction_matches(sheet, deductions)

    assert quality["name_mismatches"][0]["issue"] == "证件号码相同但姓名不一致"
    assert quality["low_confidence"][0]["match_rule"] == "姓名和证件号码首尾匹配到多名工资人员，未自动带入"
    assert "录入完整证件号码" in quality["low_confidence"][0]["message"]


def test_masked_deduction_id_with_one_name_and_first_last_candidate_is_applied():
    sheet = pd.DataFrame([
        {"*姓名": "张三", "证件号码": "410101199001010010", "机构代码_工资单": "11801"},
    ])
    deductions = pd.DataFrame([
        {"*姓名": "张三", "证件号码": "4****************0", "累计子女教育": 12000},
    ])

    matched, quality = apply_deduction_matches(sheet, deductions)

    assert matched.loc[0, "累计子女教育"] == 12000
    assert quality["low_confidence"] == []


def test_reconciliation_report_contains_required_sheets():
    sheet = pd.DataFrame(
        [
            {
                "员工编号": "1001",
                "*姓名": "张三",
                "机构代码_工资单": "10301",
                "机构代码_人员信息表": "",
                "证件类型": "",
                "证件号码": "",
                "手机号码": "",
                "任职受雇从业日期": "",
                "本期应预扣预缴税额 SUM": 100,
                "个人所得税 SUM": 90,
                "个税差异": 10,
            }
        ]
    )

    report = verify(sheet)
    sheets = build_reconciliation_report(report)

    assert {"00_汇总", "01_新增人员候选", "05_个税差异", "08_专项附加扣除低置信度匹配"}.issubset(sheets)
