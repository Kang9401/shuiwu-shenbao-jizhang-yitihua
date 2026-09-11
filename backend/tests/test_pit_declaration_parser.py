from pathlib import Path

import pandas as pd

from app.services.pit_reconciliation.parsers.declaration_parser import parse_declaration_file


def test_normal_salary_template_preserves_housing_fund_adjustment(tmp_path: Path):
    path = tmp_path / "normal_salary.xlsx"
    frame = pd.DataFrame([
        ["工号", "*姓名", "*证件类型", "*证件号码", "本期收入", "本期免税收入", "住房公积金调整", "备注"],
        [1, "张三", "居民身份证", "ID1", 1000, 0, 12.5, "ok"],
    ])
    frame.to_excel(path, index=False, header=False)
    records, issues = parse_declaration_file(path)
    assert not issues
    assert records[0]["住房公积金调整"] == 12.5
    assert records[0]["备注"] == "ok"


def test_blank_normal_salary_template_is_a_valid_empty_import(tmp_path: Path):
    path = tmp_path / "blank_normal_salary.xlsx"
    pd.DataFrame([["工号", "*姓名", "*证件号码", "本期收入", "住房公积金调整"]]).to_excel(path, index=False, header=False)
    records, issues = parse_declaration_file(path)
    assert records == []
    assert issues == []


def test_official_declaration_export_uses_real_rows_and_metadata():
    path = Path("storage/uploads/2/5/pit_declaration/0b46fc1128284a948f2d9398e4e59819.xlsx")
    if not path.exists():
        return
    records, issues = parse_declaration_file(path)
    assert not issues
    assert len(records) == 45
    assert records[0]["agent_id"]
    assert records[0]["agent_name"]
    assert records[0]["tax_period"].startswith("2026年07月")
    assert records[0]["姓名"]
    assert records[0]["应补退税额"] is not None


def test_official_declaration_export_rejects_numbering_and_footer_rows(tmp_path: Path):
    path = tmp_path / "official.xlsx"
    rows = [
        ["个人所得税扣缴申报表"],
        ["税款所属期：2026年07月01日至2026年07月31日"],
        ["扣缴义务人名称：测试机构"],
        ["扣缴义务人纳税人识别号（统一社会信用代码）：91350000000000000X"],
        ["序号", "姓名"] + [""] * 49,
        list(range(1, 52)),
        [1, "张三"] + [""] * 49,
        ["合计"] + [""] * 50,
    ]
    pd.DataFrame(rows).to_excel(path, index=False, header=False)
    records, _ = parse_declaration_file(path)
    assert len(records) == 1
    assert records[0]["姓名"] == "张三"
