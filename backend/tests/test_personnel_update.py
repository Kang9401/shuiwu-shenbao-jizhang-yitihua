from pathlib import Path

import pandas as pd
import pytest

from app.services.personnel_update import (
    PersonnelUpdateValidationError,
    _headcount_reconciliation,
    apply_staff_info_update,
)


def test_apply_staff_info_update_generates_updated_staff_and_collection(tmp_path: Path):
    staff_path = tmp_path / "人员信息表.xlsx"
    change_path = tmp_path / "人员信息变动表.xlsx"

    pd.DataFrame([
        {
            "员工编号": "1001",
            "*姓名": "张三",
            "证件类型": "居民身份证",
            "证件号码": "110101199001010011",
            "机构代码": "10301",
            "人员状态": "正常",
            "手机号码": "13800000000",
            "任职受雇从业日期": "2025-01-01",
        }
    ]).to_excel(staff_path, index=False)

    pd.DataFrame([
        {
            "员工编号": "1002",
            "*姓名": "李四",
            "证件类型": "居民身份证",
            "证件号码": "110101199202020022",
            "机构代码(人员信息表)": "10302",
            "机构代码(工资单)": "10302",
            "人员状态": "正常",
            "手机号码": "13900000000",
            "任职受雇从业日期": "2025-02-01",
            "任职受雇从业类型": "雇员",
            "国籍(地区)": "中国",
            "性别": "男",
            "出生日期": "1992-02-02",
        }
    ]).to_excel(change_path, index=False)

    result = apply_staff_info_update(str(staff_path), str(change_path), str(tmp_path / "out"), 2025, 2)

    updated = pd.read_excel(result["updated_staff_path"], dtype=str)
    assert set(updated["员工编号"].astype(str)) == {"1001", "1002"}
    assert updated.loc[updated["员工编号"].astype(str) == "1002", "机构代码"].iloc[0] == "10302"
    assert result["collection_files"]


def test_apply_staff_info_update_reports_missing_columns(tmp_path: Path):
    staff_path = tmp_path / "人员信息表.xlsx"
    change_path = tmp_path / "人员信息变动表.xlsx"
    pd.DataFrame([{"员工编号": "1001"}]).to_excel(staff_path, index=False)
    pd.DataFrame([{"*姓名": "张三"}]).to_excel(change_path, index=False)

    with pytest.raises(PersonnelUpdateValidationError) as exc:
        apply_staff_info_update(str(staff_path), str(change_path), str(tmp_path / "out"), 2025, 2)

    assert exc.value.issues[0]["issue_type"] == "missing_columns"
    assert "证件类型" in exc.value.issues[0]["columns"]


def test_apply_staff_info_update_reports_row_level_missing_fields(tmp_path: Path):
    staff_path = tmp_path / "人员信息表.xlsx"
    change_path = tmp_path / "人员信息变动表.xlsx"
    pd.DataFrame([{"员工编号": "1001", "人员状态": "正常"}]).to_excel(staff_path, index=False)
    pd.DataFrame([
        {
            "员工编号": "",
            "*姓名": "张三",
            "证件类型": "",
            "证件号码": "110101199001010011",
            "机构代码(人员信息表)": "10301",
            "人员状态": "正常",
        }
    ]).to_excel(change_path, index=False)

    with pytest.raises(PersonnelUpdateValidationError) as exc:
        apply_staff_info_update(str(staff_path), str(change_path), str(tmp_path / "out"), 2025, 2)

    issue = exc.value.issues[0]
    assert issue["issue_type"] == "missing_required_fields"
    assert issue["row_number"] == 2
    assert set(issue["missing_fields"]) == {"证件类型", "员工编号"}


def test_apply_staff_info_update_requires_staff_org_for_new_hire(tmp_path: Path):
    staff_path = tmp_path / "人员信息表.xlsx"
    change_path = tmp_path / "人员信息变动表.xlsx"
    pd.DataFrame([
        {
            "员工编号": "1001",
            "*姓名": "张三",
            "证件号码": "110101199001010011",
            "机构代码": "10301",
            "人员状态": "正常",
        }
    ]).to_excel(staff_path, index=False)
    pd.DataFrame([
        {
            "员工编号": "1002",
            "*姓名": "李四",
            "证件类型": "居民身份证",
            "证件号码": "110101199202020022",
            "机构代码(人员信息表)": "",
            "机构代码(工资单)": "10302",
            "人员状态": "正常",
        }
    ]).to_excel(change_path, index=False)

    with pytest.raises(PersonnelUpdateValidationError) as exc:
        apply_staff_info_update(str(staff_path), str(change_path), str(tmp_path / "out"), 2025, 2)

    assert "机构代码(人员信息表)" in exc.value.issues[0]["missing_fields"]


def test_apply_staff_info_update_requires_foreign_personnel_details(tmp_path: Path):
    staff_path = tmp_path / "人员信息表.xlsx"
    change_path = tmp_path / "人员信息变动表.xlsx"
    pd.DataFrame([{"员工编号": "1001", "人员状态": "正常"}]).to_excel(staff_path, index=False)
    pd.DataFrame([{
        "员工编号": "1002",
        "*姓名": "Alex",
        "证件类型": "护照",
        "证件号码": "P12345678",
        "机构代码(人员信息表)": "10302",
        "人员状态": "正常",
    }]).to_excel(change_path, index=False)

    with pytest.raises(PersonnelUpdateValidationError) as exc:
        apply_staff_info_update(str(staff_path), str(change_path), str(tmp_path / "out"), 2025, 2)

    assert set(exc.value.issues[0]["missing_fields"]) == {"国籍(地区)", "性别", "出生日期"}


def test_apply_staff_info_update_reports_unmatched_leaver(tmp_path: Path):
    staff_path = tmp_path / "人员信息表.xlsx"
    change_path = tmp_path / "人员信息变动表.xlsx"
    pd.DataFrame([
        {
            "员工编号": "1001",
            "*姓名": "张三",
            "证件号码": "110101199001010011",
            "机构代码": "10301",
            "人员状态": "正常",
        }
    ]).to_excel(staff_path, index=False)
    pd.DataFrame([
        {
            "员工编号": "1002",
            "*姓名": "李四",
            "证件类型": "居民身份证",
            "证件号码": "110101199202020022",
            "机构代码(人员信息表)": "10302",
            "机构代码(工资单)": "",
            "人员状态": "非正常",
        }
    ]).to_excel(change_path, index=False)

    with pytest.raises(PersonnelUpdateValidationError) as exc:
        apply_staff_info_update(str(staff_path), str(change_path), str(tmp_path / "out"), 2025, 2)

    assert exc.value.issues[0]["issue_type"] == "leaver_not_matched"
    assert exc.value.issues[0]["name"] == "李四"


def test_apply_staff_info_update_warns_duplicate_addition_but_allows_rehire(tmp_path: Path):
    staff_path = tmp_path / "人员信息表.xlsx"
    change_path = tmp_path / "人员信息变动表.xlsx"
    pd.DataFrame([
        {
            "员工编号": "1001",
            "*姓名": "张三",
            "证件号码": "110101199001010011",
            "机构代码": "10301",
            "人员状态": "正常",
        }
    ]).to_excel(staff_path, index=False)
    pd.DataFrame([
        {
            "员工编号": "1002",
            "*姓名": "张三",
            "证件类型": "居民身份证",
            "证件号码": "110101199001010011",
            "机构代码(人员信息表)": "10302",
            "机构代码(工资单)": "10302",
            "人员状态": "正常",
        }
    ]).to_excel(change_path, index=False)

    result = apply_staff_info_update(str(staff_path), str(change_path), str(tmp_path / "out"), 2025, 2)
    updated = pd.read_excel(result["updated_staff_path"], dtype=str)

    assert result["report"]["duplicate_additions"][0]["issue_type"] == "duplicate_addition"
    assert len(updated) == 2


def test_apply_staff_info_update_reports_multiple_leaver_matches(tmp_path: Path):
    staff_path = tmp_path / "人员信息表.xlsx"
    change_path = tmp_path / "人员信息变动表.xlsx"
    pd.DataFrame([
        {
            "员工编号": "1001",
            "*姓名": "张三",
            "证件号码": "110101199001010011",
            "机构代码": "10301",
            "人员状态": "正常",
        },
        {
            "员工编号": "1001",
            "*姓名": "张三",
            "证件号码": "110101199001010011",
            "机构代码": "10301",
            "人员状态": "正常",
        },
    ]).to_excel(staff_path, index=False)
    pd.DataFrame([
        {
            "员工编号": "1001",
            "*姓名": "张三",
            "证件类型": "居民身份证",
            "证件号码": "110101199001010011",
            "机构代码(人员信息表)": "10301",
            "机构代码(工资单)": "",
            "人员状态": "非正常",
        }
    ]).to_excel(change_path, index=False)

    result = apply_staff_info_update(str(staff_path), str(change_path), str(tmp_path / "out"), 2025, 2)

    assert result["report"]["multiple_matches"][0]["issue_type"] == "leaver_multiple_matches"


def test_apply_staff_info_update_applies_declaration_org_transfer_as_leave_and_hire(tmp_path: Path):
    staff_path = tmp_path / "人员信息表.xlsx"
    change_path = tmp_path / "人员信息变动表.xlsx"
    pd.DataFrame([
        {
            "员工编号": "1001",
            "*姓名": "张三",
            "证件类型": "居民身份证",
            "证件号码": "110101199001010011",
            "机构代码": "10301",
            "人员状态": "正常",
            "手机号码": "13800000000",
        }
    ]).to_excel(staff_path, index=False)
    pd.DataFrame([
        {
            "员工编号": "1001",
            "*姓名": "张三",
            "证件类型": "居民身份证",
            "证件号码": "110101199001010011",
            "机构代码(人员信息表)": "10301",
            "机构代码(工资单)": "",
            "人员状态": "非正常",
            "离职日期": "2025/01/31",
        },
        {
            "员工编号": "1001",
            "*姓名": "张三",
            "证件类型": "居民身份证",
            "证件号码": "110101199001010011",
            "机构代码(人员信息表)": "10302",
            "机构代码(工资单)": "10302",
            "人员状态": "正常",
            "任职受雇从业日期": "2025/02/01",
        },
    ]).to_excel(change_path, index=False)

    result = apply_staff_info_update(str(staff_path), str(change_path), str(tmp_path / "out"), 2025, 2)
    updated = pd.read_excel(result["updated_staff_path"], dtype=str).fillna("")

    assert len(updated) == 2
    assert set(updated["人员状态"]) == {"正常", "非正常"}
    assert updated.loc[updated["人员状态"] == "正常", "机构代码"].iloc[0] == "10302"
    assert result["collection_files"]


def test_headcount_reconciliation_detects_mismatch():
    result = _headcount_reconciliation(before_count=10, additions=2, leavers=1, after_count=10)

    assert result["has_issues"] is True
    assert result["items"][0]["expected_after_count"] == 11
