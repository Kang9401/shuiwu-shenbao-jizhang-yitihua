from pathlib import Path

import pandas as pd

from app.services.personnel_declaration import build_monthly_personnel_change_table
from app.services.personnel_update import PERSONNEL_COLLECTION_COLUMNS, build_personnel_collection_files


def _master_row(name: str, id_number: str, org_code: str, status: str, **extra: str) -> dict[str, str]:
    return {
        "员工编号": extra.get("employee_id", id_number[-4:]),
        "*姓名": name,
        "证件类型": "居民身份证",
        "证件号码": id_number,
        "机构代码": org_code,
        "人员状态": status,
        "手机号码": extra.get("phone", "13800000000"),
        "任职受雇从业日期": extra.get("hire_date", "2025/01/01"),
        "离职日期": extra.get("leave_date", ""),
    }


def test_monthly_personnel_declaration_compares_masters_not_payroll(tmp_path: Path):
    previous_path = tmp_path / "previous.xlsx"
    current_path = tmp_path / "current.xlsx"
    pd.DataFrame([
        _master_row("张三", "110101199001010011", "10001", "正常"),
        _master_row("李四", "110101199202020022", "10002", "正常"),
    ]).to_excel(previous_path, index=False)
    pd.DataFrame([
        _master_row("张三", "110101199001010011", "10001", "非正常", leave_date="2025/07/15"),
        _master_row("李四", "110101199202020022", "10003", "正常"),
        _master_row("王五", "110101199303030033", "10004", "正常", hire_date="2025/07/10"),
    ]).to_excel(current_path, index=False)

    changes = build_monthly_personnel_change_table(previous_path, current_path, 2025, 7)

    assert len(changes) == 4
    assert set(changes.loc[changes["人员状态"] == "非正常", "机构代码(人员信息表)"]) == {"10001", "10002"}
    assert set(changes.loc[changes["人员状态"] == "正常", "机构代码(人员信息表)"]) == {"10003", "10004"}
    assert changes.loc[changes["*姓名"] == "张三", "离职日期"].iloc[0] == "2025/07/15"

    files = build_personnel_collection_files(changes, tmp_path / "declarations", 2025, 7)
    assert {Path(path).name[:5] for path in files} == {"10001", "10002", "10003", "10004"}
    assert all("_1-人员信息采集_员工" in Path(path).name for path in files)


def test_personnel_collection_preserves_hire_date_alias_in_tax_format(tmp_path: Path):
    previous_path = tmp_path / "previous.xlsx"
    current_path = tmp_path / "current.xlsx"
    pd.DataFrame([_master_row("张三", "110101199001010011", "10001", "正常")]).to_excel(previous_path, index=False)
    current = _master_row("李四", "110101199202020022", "10001", "正常")
    current["入职时间"] = "2026-08-07 10:30:00"
    current.pop("任职受雇从业日期", None)
    pd.DataFrame([current]).to_excel(current_path, index=False)

    changes = build_monthly_personnel_change_table(previous_path, current_path, 2026, 8)
    files = build_personnel_collection_files(changes, tmp_path / "declarations", 2026, 8)
    output = pd.read_excel(files[0], dtype=str).fillna("")

    assert output.loc[output["*姓名"] == "李四", "任职受雇从业日期"].iloc[0] == "2026-08-07"


def test_personnel_collection_drops_declaration_only_columns_for_all_person_types(tmp_path: Path):
    changes = pd.DataFrame([{
        "机构代码(人员信息表)": "10001",
        "*姓名": "实习生甲",
        "证件类型": "居民身份证",
        "证件号码": "110101199001010011",
        "国籍(地区)": "中国",
        "性别": "男",
        "出生日期": "2005/01/01",
        "任职受雇从业类型": "实习学生（全日制学历教育）",
        "人员状态": "正常",
        "*所得项目": "其他连续劳务报酬",
        "本期收入": 500,
        "实习生本期收入": 500,
    }])

    files = build_personnel_collection_files(
        changes, tmp_path / "declarations", 2026, 8, person_type_label="实习生"
    )
    output = pd.read_excel(files[0], dtype=str).fillna("")

    expected_columns = [column for column in PERSONNEL_COLLECTION_COLUMNS if column != "人员状态"]
    assert list(output.columns) == expected_columns
    assert not {"*所得项目", "本期收入", "实习生本期收入"}.intersection(output.columns)
