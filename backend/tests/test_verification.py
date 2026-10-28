from pathlib import Path

import pandas as pd
import pytest

from app.services.verification import (
    RetirementWelfareColumnSelectionError,
    analyze_deduction_matches,
    apply_deduction_matches,
    build_working_sheet,
    build_reconciliation_report,
    check_deduction_issues,
    check_payroll_org_format,
    check_personnel_changes,
    verify,
    load_retirement_welfare,
    load_employee_payroll,
    load_headquarters_payroll,
    PayrollHeaderValidationError,
)
from app.services.salary_classifier import classify_salary_frame


def _retirement_welfare_file(path: Path, headers: list[str], rows: list[list[object]]) -> Path:
    values = [
        ["2026年法定退休员工慰问发放明细"],
        ["统计时点：2026年6月30日"],
        headers,
        *rows,
    ]
    pd.DataFrame(values).to_excel(path, index=False, header=False)
    return path


def _write_rank_payroll(path: Path, rows: list[dict]) -> None:
    normalized = []
    for row in rows:
        normalized.append({"累计预扣预缴应纳税所得额": 0, **row})
    pd.DataFrame(normalized).to_excel(path, index=False)


@pytest.mark.parametrize("legacy", [False, True])
def test_headquarters_payroll_social_insurance_accepts_new_and_legacy_headers(tmp_path, legacy):
    amounts = {"基本养老保险费": 1200.25, "基本医疗保险费": 300.50, "失业保险费": 60.75, "住房公积金": 1500.00}
    old_names = {"基本养老保险费": "养老保险金的员工部分", "基本医疗保险费": "医疗保险金的员工部分",
                 "失业保险费": "失业保险金的员工部分", "住房公积金": "住房公积金的员工部分"}
    row = {"员工编号": "00123", "姓名": "测试人员", "机构代码": "10501", "本期收入": 15000}
    row.update({old_names[k] if legacy else k: v for k, v in amounts.items()})
    path = tmp_path / "总部工资单.xlsx"
    pd.DataFrame([row]).to_excel(path, index=False)
    result = load_headquarters_payroll(str(path))
    assert result.iloc[0]["员工编号"] == "00123"
    for field, value in amounts.items():
        assert result.iloc[0][field] == pytest.approx(value)


def test_headquarters_payroll_prefers_explicit_new_zero_over_legacy_amount(tmp_path):
    path = tmp_path / "总部工资单.xlsx"
    pd.DataFrame([{"员工编号": "00123", "姓名": "测试人员", "基本养老保险费": 0,
                   "养老保险金的员工部分": 1200}]).to_excel(path, index=False)
    assert load_headquarters_payroll(str(path)).iloc[0]["基本养老保险费"] == 0


def test_headquarters_31_column_template_is_structural_even_when_blank():
    columns = [
        "薪资期间", "薪资方案", "个税申报地", "个税扣缴义务人纳税人识别号", "个税类型", "姓名", "員工编号",
        "证件类型", "证件号码", "本期收入", "本期免税收入", "基本养老保险费", "基本医疗保险费", "失业保险费",
        "住房公积金", "累计子女教育", "累计继续教育", "累计住房贷款利息", "累计住房租金", "累计赡养老人",
        "累计3岁以下婴幼儿照护", "累计个人养老金", "累计商业保险扣除", "企业(职业)年金", "商业健康保险",
        "税延养老保险", "其他", "准予扣除的捐赠额", "减免税额", "备注", "本期应预扣预缴税额",
    ]
    result = classify_salary_frame(pd.DataFrame(columns=columns), "任意文件名.xlsx")
    assert result.role == "headquarters_salary"


def test_headquarters_31_column_new_amounts_are_preserved(tmp_path):
    path = tmp_path / "任意文件名.xlsx"
    pd.DataFrame([{
        "薪资期间": "2026-08", "个税申报地": "成都", "个税扣缴义务人纳税人识别号": "T",
        "个税类型": "工资薪金", "姓名": "测试人员", "員工编号": "00123", "本期收入": 10000,
        "企业(职业)年金": 111, "商业健康保险": 222, "本期免税收入": 333, "本期应预扣预缴税额": 444,
        "机构代码": "10501",
    }]).to_excel(path, index=False)
    result = load_headquarters_payroll(str(path)).iloc[0]
    assert result["员工编号"] == "00123"
    assert result["企业(职业)年金"] == 111
    assert result["商业健康保险"] == 222
    assert result["本期免税收入"] == 333
    assert result["本期应预扣预缴税额 SUM"] == 444
    assert result["个人所得税 SUM"] == 444


def test_headquarters_payroll_maps_org_from_taxpayer_id_when_org_column_is_absent(tmp_path):
    path = tmp_path / "headquarters_without_org_column.xlsx"
    pd.DataFrame([{
        "薪资期间": "2026-09",
        "个税扣缴义务人纳税人识别号": "915101006909438061",
        "姓名": "总部员工",
        "員工编号": "16082",
        "证件类型": "居民身份证",
        "证件号码": "513901198402136424",
        "本期收入": 10000,
    }]).to_excel(path, index=False)

    result = load_headquarters_payroll(
        str(path),
        taxpayer_org_map={"915101006909438061": "17020"},
    )

    assert result.iloc[0]["机构代码"] == "17020"
    assert result.iloc[0]["机构映射异常"] == ""


def test_headquarters_payroll_preserves_explicit_zero_tax_with_new_header(tmp_path):
    path = tmp_path / "headquarters.xlsx"
    pd.DataFrame([{
        "员工编号": "00123", "姓名": "测试人员", "机构代码": "10501", "本期收入": 10000,
        "个人所得税": 0, "本期应预扣预缴税额": 444,
    }]).to_excel(path, index=False)
    assert load_headquarters_payroll(str(path)).iloc[0]["个人所得税 SUM"] == 0


def test_real_five_and_seven_digit_payroll_headers_map_appendix_a2_fields(tmp_path: Path):
    source_row = {
        "员工编号": "10001",
        "姓名": "张三",
        "机构代码": "13248",
        "个人所得税": 88.66,
        "累计预扣预缴应纳税所得额": 123456.78,
        "累计减除费用": 35000,
        "累计养老保险金的员工部分": 100,
        "累计医疗保险金的员工部分": 200,
        "累计失业保险金的员工部分": 30,
        "累计住房公积金的员工部分": 400,
        "累计企业年金的员工部分": 50,
        "累计商业保险扣除": 20,
        "累计当月子女教育附加扣除": 1000,
        "累计当月继续教育附加扣除": 2000,
        "累计当月住房贷款利息附加扣除": 3000,
        "累计当月住房租金附加扣除": 4000,
        "累计当月赡养老人附加扣除": 5000,
        "累计当月婴幼儿照护费用附加扣除": 6000,
        "累计个人养老金": 700,
    }
    for role, employee_no in (("rank_salary", "10001"), ("marketing_salary", "1000001")):
        path = tmp_path / f"{role}.xlsx"
        pd.DataFrame([{**source_row, "员工编号": employee_no}]).to_excel(path, index=False)

        result = load_employee_payroll(str(path), payroll_role=role)

        row = result.iloc[0]
        assert row["工资表_累计应纳税所得额"] == pytest.approx(123456.78)
        assert row["工资表_累计减除费用"] == pytest.approx(35000)
        assert row["工资表_累计养老保险金员工部分"] == pytest.approx(100)
        assert row["工资表_累计医疗保险金员工部分"] == pytest.approx(200)
        assert row["工资表_累计失业保险金员工部分"] == pytest.approx(30)
        assert row["工资表_累计住房公积金员工部分"] == pytest.approx(400)
        assert row["工资单_累计子女教育扣除"] == pytest.approx(1000)
        assert row["工资单_累计婴幼儿照护扣除"] == pytest.approx(6000)
        assert row["个人所得税 SUM"] == pytest.approx(88.66)


@pytest.mark.parametrize(
    ("current_value", "previous_value", "expected"),
    [(100, 80, 20), (80, 100, 80), (100, None, 100), (100, 100, 100)],
)
def test_commercial_insurance_uses_employee_increment_from_previous_payroll(
    tmp_path: Path, current_value: float, previous_value: float | None, expected: float
):
    current_path = tmp_path / "current.xlsx"
    previous_path = tmp_path / "previous.xlsx"
    row = {
        "员工编号": "00123.0",
        "姓名": "测试人员",
        "机构代码": "13248",
        "累计预扣预缴应纳税所得额": 1000,
        "累计商业保险扣除": current_value,
    }
    pd.DataFrame([row]).to_excel(current_path, index=False)
    previous_files = []
    if previous_value is not None:
        pd.DataFrame([{**row, "员工编号": "00123", "累计商业保险扣除": previous_value}]).to_excel(previous_path, index=False)
        previous_files = [("rank_salary", str(previous_path))]

    staff_path = tmp_path / "staff.xlsx"
    pd.DataFrame([{
        "员工编号": "00123", "*姓名": "测试人员", "机构代码": "13248",
        "人员状态": "正常", "证件类型": "居民身份证", "证件号码": "110101199001010011",
    }]).to_excel(staff_path, index=False)

    sheet, _ = build_working_sheet(
        [("rank_salary", str(current_path))], str(staff_path), "",
        previous_payroll_files=previous_files,
    )
    result = sheet.iloc[0]
    assert result["商业健康保险"] == pytest.approx(expected)
    assert result["工资单_累计商业保险扣除"] == pytest.approx(expected)
    # A2 专用字段仍保持工资单原始累计值。
    assert result["工资表_累计商业保险扣除"] == pytest.approx(current_value)


def test_missing_payroll_taxable_income_header_reports_all_actual_headers(tmp_path: Path):
    path = tmp_path / "缺字段的5位工资表.xlsx"
    pd.DataFrame([{"员工编号": "10001", "姓名": "张三", "个人所得税": 10}]).to_excel(path, index=False)

    with pytest.raises(PayrollHeaderValidationError) as captured:
        load_employee_payroll(str(path), payroll_role="rank_salary")

    message = str(captured.value)
    assert "工资表_累计应纳税所得额" in message
    assert "员工编号" in message
    assert "姓名" in message
    assert "个人所得税" in message
    assert captured.value.headers == ["员工编号", "姓名", "个人所得税"]


def test_retirement_welfare_detects_variable_header_and_requires_choice_for_multiple_columns(tmp_path: Path):
    source = _retirement_welfare_file(
        tmp_path / "退休福利.xlsx",
        ["序号", "姓名", "机构段（5位代码）", "春节慰问，2500元/人", "体检慰问，2000元/人"],
        [[1, "张三", "13248", 2500, 2000]],
    )

    try:
        load_retirement_welfare(str(source))
    except RetirementWelfareColumnSelectionError as exc:
        assert exc.columns == ["春节慰问，2500元/人", "体检慰问，2000元/人"]
    else:
        raise AssertionError("expected manual column selection")

    result = load_retirement_welfare(str(source), "体检慰问，2000元/人")
    assert result.to_dict(orient="records") == [{
        "姓名": "张三", "机构代码": "13248", "慰问金额": 2000.0,
        "慰问列": "体检慰问，2000元/人", "身份证号": "",
    }]


def test_retirement_welfare_existing_payroll_only_reconciles(tmp_path: Path):
    payroll_path = tmp_path / "职级工资.xlsx"
    _write_rank_payroll(payroll_path, [
        {"员工编号": "1001", "姓名": "张三", "机构代码": "13248", "应发工资": 10000, "福利费": 2000, "调增应纳税所得额": 1000},
    ])
    staff_path = tmp_path / "人员信息.xlsx"
    pd.DataFrame([
        {"员工编号": "1001", "*姓名": "张三", "机构代码": "13248", "人员状态": "正常", "证件类型": "居民身份证", "证件号码": "110101199001010011"},
    ]).to_excel(staff_path, index=False)
    welfare_path = _retirement_welfare_file(
        tmp_path / "退休福利.xlsx",
        ["姓名", "机构段（5位代码）", "体检慰问，2000元/人"],
        [["张三", "13248", 2000]],
    )

    sheet, _ = build_working_sheet(
        [("rank_salary", str(payroll_path))], str(staff_path), "",
        retirement_welfare_path=str(welfare_path),
    )

    retirement_rows = sheet.attrs["retirement_welfare"]
    normal = next(item for item in retirement_rows if item["name"] == "张三")
    assert normal["status"] == "福利费待核对"
    assert normal["payroll_exists"] is True
    assert normal["payroll_taxable_adjustment"] == 1000.0
    assert len(sheet) == 1


def test_retirement_welfare_existing_payroll_does_not_block_on_ambiguous_staff(tmp_path: Path):
    payroll_path = tmp_path / "职级工资.xlsx"
    _write_rank_payroll(payroll_path, [{"员工编号": "1001", "姓名": "李四", "机构代码": "13248", "应发工资": 10000, "福利费": 0, "调增应纳税所得额": 2000}])
    staff_path = tmp_path / "人员信息.xlsx"
    pd.DataFrame([
        {"员工编号": "1001", "*姓名": "李四", "机构代码": "13248", "人员状态": "非正常"},
        {"员工编号": "2002", "*姓名": "李四", "机构代码": "13248", "人员状态": "正常"},
    ]).to_excel(staff_path, index=False)
    welfare_path = _retirement_welfare_file(
        tmp_path / "退休福利.xlsx",
        ["姓名", "机构段（5位代码）", "体检慰问，2000元/人"],
        [["李四", "13248", 2000]],
    )

    sheet, _ = build_working_sheet(
        [("rank_salary", str(payroll_path))], str(staff_path), "",
        retirement_welfare_path=str(welfare_path),
    )

    item = sheet.attrs["retirement_welfare"][0]
    assert item["payroll_exists"] is True
    assert item["status"] == "金额一致"
    assert item["blocking"] is False
    assert len(sheet) == 1


def test_retirement_welfare_normal_staff_without_payroll_is_added_without_departure(tmp_path: Path):
    payroll_path = tmp_path / "职级工资.xlsx"
    _write_rank_payroll(payroll_path, [{"员工编号": "1001", "姓名": "张三", "机构代码": "13248", "应发工资": 10000}])
    staff_path = tmp_path / "人员信息.xlsx"
    pd.DataFrame([
        {"员工编号": "1001", "*姓名": "张三", "机构代码": "13248", "人员状态": "正常", "证件类型": "居民身份证", "证件号码": "110101199001010011"},
        {"员工编号": "1002", "*姓名": "李四", "机构代码": "13248", "人员状态": "正常", "证件类型": "居民身份证", "证件号码": "110101199001010022"},
    ]).to_excel(staff_path, index=False)
    welfare_path = _retirement_welfare_file(
        tmp_path / "退休福利.xlsx",
        ["姓名", "机构段（5位代码）", "体检慰问，2000元/人"],
        [["李四", "13248", 2000]],
    )

    sheet, staff = build_working_sheet(
        [("rank_salary", str(payroll_path))], str(staff_path), "",
        retirement_welfare_path=str(welfare_path),
    )

    added = sheet[sheet["*姓名"] == "李四"].iloc[0]
    item = sheet.attrs["retirement_welfare"][0]
    changes = check_personnel_changes(sheet, staff_df=staff)["items"]
    assert item["status"] == "正常人员补入工资"
    assert item["payroll_exists"] is False
    assert added["福利费"] == 2000
    assert added["本期收入"] == 2000
    assert not any(change["name"] == "李四" for change in changes)


def test_retirement_welfare_non_normal_staff_without_payroll_is_new_hire(tmp_path: Path):
    payroll_path = tmp_path / "职级工资.xlsx"
    _write_rank_payroll(payroll_path, [{"员工编号": "1001", "姓名": "张三", "机构代码": "13248", "应发工资": 10000}])
    staff_path = tmp_path / "人员信息.xlsx"
    pd.DataFrame([
        {"员工编号": "1001", "*姓名": "张三", "机构代码": "13248", "人员状态": "正常", "证件类型": "居民身份证", "证件号码": "110101199001010011"},
        {"员工编号": "2001", "*姓名": "李四", "机构代码": "13248", "人员状态": "非正常", "证件类型": "居民身份证", "证件号码": "110101199001010022", "手机号码": "13800000000", "任职受雇从业日期": "2020-01-01"},
    ]).to_excel(staff_path, index=False)
    welfare_path = _retirement_welfare_file(
        tmp_path / "退休福利.xlsx",
        ["姓名", "机构段（5位代码）", "体检慰问，2000元/人"],
        [["李四", "13248", 2000]],
    )

    sheet, staff = build_working_sheet(
        [("rank_salary", str(payroll_path))], str(staff_path), "",
        retirement_welfare_path=str(welfare_path),
    )

    item = sheet.attrs["retirement_welfare"][0]
    changes = check_personnel_changes(sheet, staff_df=staff)["items"]
    assert item["status"] == "非正常人员入职"
    assert any(change["name"] == "李四" and change["change_type"] == "入职" for change in changes)


def test_retirement_welfare_missing_staff_is_new_hire_with_required_data(tmp_path: Path):
    payroll_path = tmp_path / "职级工资.xlsx"
    _write_rank_payroll(payroll_path, [{"员工编号": "1001", "姓名": "张三", "机构代码": "13248", "应发工资": 10000}])
    staff_path = tmp_path / "人员信息.xlsx"
    pd.DataFrame([{"员工编号": "1001", "*姓名": "张三", "机构代码": "13248", "人员状态": "正常"}]).to_excel(staff_path, index=False)
    welfare_path = _retirement_welfare_file(
        tmp_path / "退休福利.xlsx",
        ["姓名", "机构段（5位代码）", "身份证号", "体检慰问，2000元/人"],
        [["王五", "13248", "110101199001010033", 2000]],
    )

    sheet, staff = build_working_sheet(
        [("rank_salary", str(payroll_path))], str(staff_path), "",
        retirement_welfare_path=str(welfare_path),
    )

    item = sheet.attrs["retirement_welfare"][0]
    changes = check_personnel_changes(sheet, staff_df=staff)["items"]
    hire = next(change for change in changes if change["name"] == "王五")
    assert item["status"] == "无人员信息待补"
    assert item["id_number"] == "110101199001010033"
    assert item["blocking"] is True
    assert "员工编号" in hire["missing_fields"]


def test_retirement_welfare_duplicate_history_requires_manual_confirmation(tmp_path: Path):
    payroll_path = tmp_path / "职级工资.xlsx"
    _write_rank_payroll(payroll_path, [{"员工编号": "1001", "姓名": "张三", "机构代码": "13248", "应发工资": 10000}])
    staff_path = tmp_path / "人员信息.xlsx"
    pd.DataFrame([
        {"员工编号": "2001", "*姓名": "李四", "机构代码": "13248", "人员状态": "非正常"},
        {"员工编号": "2002", "*姓名": "李四", "机构代码": "13248", "人员状态": "非正常"},
    ]).to_excel(staff_path, index=False)
    welfare_path = _retirement_welfare_file(
        tmp_path / "退休福利.xlsx",
        ["姓名", "机构段（5位代码）", "慰问金额"],
        [["李四", "13248", 2000]],
    )

    sheet, _ = build_working_sheet(
        [("rank_salary", str(payroll_path))], str(staff_path), "",
        retirement_welfare_path=str(welfare_path),
    )

    item = sheet.attrs["retirement_welfare"][0]
    assert item["status"] == "人员信息待确认"
    assert item["blocking"] is True
    assert "李四" not in set(sheet["*姓名"])


def test_retirement_welfare_duplicate_rows_use_id_number_for_precise_matching(tmp_path: Path):
    payroll_path = tmp_path / "职级工资.xlsx"
    _write_rank_payroll(payroll_path, [{"员工编号": "1001", "姓名": "张三", "机构代码": "13248", "应发工资": 10000}])
    staff_path = tmp_path / "人员信息.xlsx"
    pd.DataFrame([
        {"员工编号": "1001", "*姓名": "张三", "机构代码": "13248", "人员状态": "正常"},
        {"员工编号": "2001", "*姓名": "李四", "机构代码": "13248", "人员状态": "非正常", "证件号码": "110101199001010021"},
        {"员工编号": "2002", "*姓名": "李四", "机构代码": "13248", "人员状态": "非正常", "证件号码": "110101199001010022"},
    ]).to_excel(staff_path, index=False)
    welfare_path = _retirement_welfare_file(
        tmp_path / "退休福利.xlsx",
        ["姓名", "机构段（5位代码）", "身份证号", "体检慰问，2000元/人"],
        [["李四", "13248", "110101199001010021", 2000], ["李四", "13248", "110101199001010022", 2000]],
    )

    sheet, _ = build_working_sheet(
        [("rank_salary", str(payroll_path))], str(staff_path), "",
        retirement_welfare_path=str(welfare_path),
    )

    items = sheet.attrs["retirement_welfare"]
    added = sheet[sheet["*姓名"] == "李四"]
    assert len(added) == 2
    assert {item["match_method"] for item in items} == {"机构+身份证号"}
    assert {item["status"] for item in items} == {"非正常人员入职"}


def test_retirement_welfare_duplicate_rows_with_same_or_missing_id_require_confirmation(tmp_path: Path):
    payroll_path = tmp_path / "职级工资.xlsx"
    _write_rank_payroll(payroll_path, [{"员工编号": "1001", "姓名": "张三", "机构代码": "13248", "应发工资": 10000}])
    staff_path = tmp_path / "人员信息.xlsx"
    pd.DataFrame([{"员工编号": "1001", "*姓名": "张三", "机构代码": "13248", "人员状态": "正常"}]).to_excel(staff_path, index=False)
    welfare_path = _retirement_welfare_file(
        tmp_path / "退休福利.xlsx",
        ["姓名", "机构段（5位代码）", "身份证号", "体检慰问，2000元/人"],
        [["李四", "13248", "110101199001010021", 2000], ["李四", "13248", "110101199001010021", 2000]],
    )

    sheet, _ = build_working_sheet(
        [("rank_salary", str(payroll_path))], str(staff_path), "",
        retirement_welfare_path=str(welfare_path),
    )

    items = sheet.attrs["retirement_welfare"]
    assert len(items) == 2
    assert all(item["status"] == "重复退休记录待确认" and item["blocking"] for item in items)
    assert "李四" not in set(sheet["*姓名"])


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


def test_departure_change_uses_payroll_org_when_employee_id_still_has_wage_row():
    # A name mismatch can make the personnel left-join report a departure
    # even though the current payroll still contains the employee number.
    sheet = pd.DataFrame([
        {
            "员工编号": "16082",
            "*姓名": "总部人员（工资单）",
            "机构代码_工资单": "17020",
            "机构代码_人员信息表": "",
            "证件类型": "居民身份证",
            "证件号码": "110101199001010011",
        }
    ])
    staff_df = pd.DataFrame([
        {
            "员工编号": "16082",
            "*姓名": "总部人员",
            "人员状态": "正常",
            "机构代码": "17020",
            "证件类型": "居民身份证",
            "证件号码": "110101199001010011",
        }
    ])

    report = check_personnel_changes(sheet, staff_df=staff_df, year=2026, month=9)

    departure = next(item for item in report["items"] if item["change_type"] == "离职")
    assert departure["payroll_org_code"] == "17020"


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
