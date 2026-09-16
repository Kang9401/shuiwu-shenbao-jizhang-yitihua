from pathlib import Path

import pandas as pd

from app.services.pit_reconciliation.parsers.declaration_parser import GENERAL_HEADERS, parse_declaration_file
from app.services.pit_reconciliation.rules.income_classification import income_category


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


def test_recognized_template_without_business_rows_has_a_validation_issue(tmp_path: Path):
    path = tmp_path / "blank_normal_salary.xlsx"
    pd.DataFrame([["工号", "*姓名", "*证件号码", "本期收入", "住房公积金调整"]]).to_excel(path, index=False, header=False)
    records, issues = parse_declaration_file(path)
    assert records == []
    assert [issue["issue_type"] for issue in issues] == ["no_declaration_rows"]


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


def test_classified_income_official_row_without_name_or_id_is_preserved_and_total_gap_is_reported(tmp_path: Path):
    path = tmp_path / "2026-08_11802_分类所得申报表.xlsx"
    data = [""] * len(GENERAL_HEADERS)
    data[0] = 17
    data[5] = "否"
    data[6] = "其他偶然所得"
    data[7] = "11738.00"
    data[43] = "11738.00"
    data[44] = "20%"
    data[46] = "2347.60"
    data[50] = "2347.60"
    total = [""] * len(GENERAL_HEADERS)
    total[0] = "合计"
    total[7] = "14180.62"
    total[50] = "2836.12"
    rows = [
        ["个人所得税扣缴申报表"],
        ["税款所属期：2026年08月01日至2026年08月31日"],
        ["扣缴义务人名称：测试营业部"],
        ["扣缴义务人纳税人识别号（统一社会信用代码）：914406056863884597"],
        ["住房公积金调整"],
        list(range(1, 53)),
        data,
        total,
    ]
    pd.DataFrame(rows).to_excel(path, index=False, header=False)
    records, issues = parse_declaration_file(path)
    assert len(records) == 1
    row = records[0]
    assert row["所得项目"] == "其他偶然所得"
    assert float(row["收入"]) == 11738.00
    assert float(row["应纳税所得额"]) == 11738.00
    assert row["税率/预扣率"] == "20%"
    assert float(row["应纳税额"]) == 2347.60
    assert float(row["应补退税额"]) == 2347.60
    assert row["姓名"] == ""
    assert row["身份证件号码"] == ""
    assert row["file_org_code"] == "11802"
    assert income_category(row["所得项目"], row["sheet_name"]) == "分类所得"
    mismatch = next(issue for issue in issues if issue["issue_type"] == "declaration_detail_total_mismatch")
    assert mismatch["visible_income_sum"] == "11738.00"
    assert mismatch["declared_total_income"] == "14180.62"
