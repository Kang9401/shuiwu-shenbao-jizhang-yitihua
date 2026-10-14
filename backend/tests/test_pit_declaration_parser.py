from pathlib import Path
from decimal import Decimal

import pandas as pd
import pytest

from app.services.pit_reconciliation.parsers.declaration_parser import GENERAL_HEADERS, LEGACY_GENERAL_HEADERS, RESTRICTED_HEADERS, parse_declaration_file
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
        LEGACY_GENERAL_HEADERS,
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
        GENERAL_HEADERS,
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


def _official_fixture(path, headers):
    business = {"序号": 1, "姓名": "测试人员", "身份证件号码": "TEST-ID", "所得项目": "正常工资薪金",
                "收入": 300000, "住房公积金调整": 125, "住房公积金和年金调整": 125,
                "住房公积金\n和年金调整": 125, "已缴税额": 195892.09,
                "应补/退税额": 38006.59, "应补／退税额": 38006.59, "应补/退税\n额": 38006.59,
                "备注": "原备注"}
    data = [business.get(header, "") for header in headers]
    total = ["合计" if header == "序号" else business.get(header, "") if header in {"收入", "已缴税额", "应补/退税额", "应补／退税额", "应补/退税\n额"} else "" for header in headers]
    rows = [["个人所得税扣缴申报表"], ["税款所属期：2026年09月01日至2026年09月30日"],
            ["扣缴义务人名称：测试营业部"], headers, list(range(1, len(headers) + 1)), data, total]
    pd.DataFrame(rows).to_excel(path, header=False, index=False)
    return path


@pytest.mark.parametrize("adjustment", [None, "住房公积金调整", "住房公积金和年金调整", "住房公积金\n和年金调整"])
@pytest.mark.parametrize("tax_header", ["应补/退税额", "应补／退税额", "应补/退税\n额"])
def test_official_tax_is_located_by_header_for_old_and_new_templates(tmp_path, adjustment, tax_header):
    headers = list(LEGACY_GENERAL_HEADERS if adjustment is None else GENERAL_HEADERS)
    headers = [adjustment if h == "住房公积金调整" else tax_header if h == "应补退税额" else h for h in headers]
    path = _official_fixture(tmp_path / "official.xlsx", headers)
    rows, issues = parse_declaration_file(path)
    assert not issues
    assert len(rows) == 1
    assert rows[0]["已缴税额"] == 195892.09
    assert rows[0]["应补退税额"] == 38006.59
    assert rows[0]["备注"] == "原备注"
    if adjustment is not None:
        assert rows[0]["住房公积金调整"] == 125


def test_official_tax_header_survives_inserted_columns_and_deep_headers(tmp_path):
    headers = ["应补/退税额" if h == "应补退税额" else h for h in GENERAL_HEADERS]
    headers.insert(12, "新增技术列")
    headers.append("尾部空列")
    path = _official_fixture(tmp_path / "inserted.xlsx", headers)
    # Move the real header below the first eight rows without moving its columns.
    frame = pd.read_excel(path, header=None).fillna("")
    frame = pd.concat([frame.iloc[:3], pd.DataFrame([[""]] * 7), frame.iloc[3:]], ignore_index=True)
    frame.to_excel(path, index=False, header=False)
    rows, issues = parse_declaration_file(path)
    assert not issues
    assert rows[0]["收入"] == 300000
    assert rows[0]["应补退税额"] == 38006.59
    assert rows[0]["已缴税额"] == 195892.09
    assert rows[0]["备注"] == "原备注"


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_official_tax_header_must_be_unambiguous(tmp_path, mode):
    headers = ["应补/退税额" if h == "应补退税额" else h for h in GENERAL_HEADERS]
    if mode == "missing":
        headers[headers.index("应补/退税额")] = "未知税额"
    else:
        headers.append("应补/退税额")
    rows, issues = parse_declaration_file(_official_fixture(tmp_path / "invalid.xlsx", headers))
    assert not rows
    assert any(issue["issue_type"] == "declaration_tax_column_invalid" for issue in issues)


def test_header_located_tax_flows_through_import_to_reconciliation_summary(tmp_path, monkeypatch):
    from fastapi import UploadFile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.config import settings
    from app.core.company_context import set_company_id, reset_company_id
    from app.db.session import Base
    from app.models.core import Company, Period
    from app.models.accounting import OrganizationMapping, ReconciliationImportRow
    from app.services.reconciliation_import import import_pit_declaration_file
    from app.services.pit_reconciliation.source_service import PitSourceService
    from app.services.pit_reconciliation.domain import PitSourceBundle, SourceResult, OrganizationRow
    from app.services.pit_reconciliation.engine import PitReconciliationEngine

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    headers = ["住房公积金和年金调整" if h == "住房公积金调整" else "应补/退税额" if h == "应补退税额" else h for h in GENERAL_HEADERS]
    path = _official_fixture(tmp_path / "official.xlsx", headers)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(name="测试公司", code="TEST", operator_name="测试")
        db.add(company); db.flush()
        token = set_company_id(company.id)
        try:
            period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
            db.add(period); db.flush()
            db.add(OrganizationMapping(company_id=company.id, org_code="10501", branch_name="测试营业部"))
            db.commit()
            with path.open("rb") as stream:
                batch = import_pit_declaration_file(db, period_id=period.id, file=UploadFile(filename=path.name, file=stream))
            assert db.query(ReconciliationImportRow).filter_by(batch_id=batch.id).one().tax_amount == Decimal("38006.59")
            declarations = PitSourceService(db, company.id, period.id).load_declaration_source()
            empty = lambda name: SourceResult(name, "ready_empty", required=False)
            bundle = PitSourceBundle(SourceResult("organization_mapping", "ready", [OrganizationRow("10501")]),
                                     empty("salary"), declarations, empty("balance_sheet"), empty("broker"),
                                     empty("bond_interest"), empty("restricted_stock"), empty("tax_certificate"), empty("bank_statement"))
            result = PitReconciliationEngine().calculate(bundle)
            assert result["org_summaries"][0]["declared_tax_amount"] == Decimal("38006.59")
        finally:
            reset_company_id(token)
    engine.dispose()


def test_restricted_declaration_uses_actual_headers_and_keeps_taxable_income(tmp_path: Path):
    headers = [
        "序号", "纳税人姓名", "纳税人有效身份证件_证件类型", "证件号码", "Col_5", "证券账户号",
        "股票代码", "股票名称", "每股计税价格（元/股)", "转让股数(股)", "Col_11", "转让收入额",
        "限售股原值及合理税费_小计", "原值", "合理税费", "Col_16", "准予扣除的捐赠额", "应纳税所得额",
        "税率", "协定减免", "扣缴税额",
    ]
    row = [1, "测试人员", "居民身份证", "ID1", "", "A", "S", "股票", 10, 100, "", 1000, 500, 450, 50, "", 0, 500, "20%", 0, 100]
    path = tmp_path / "限售股.xlsx"
    pd.DataFrame([["限售股转让所得个人所得税扣缴报告表"], headers, row]).to_excel(path, index=False, header=False)
    records, issues = parse_declaration_file(path)
    assert not issues
    assert records[0]["应纳税所得额"] == 500
    assert records[0]["扣缴税额"] == 100


def test_restricted_declaration_header_change_does_not_shift_tax(tmp_path: Path):
    headers = list(RESTRICTED_HEADERS)
    headers.insert(8, "新增技术列")
    row = [1, "测试人员", "居民身份证", "ID1", "", "A", "S", "股票", "新增", 10, 100, "", 1000, 500, 450, 50, "", 0, 500, "20%", 0, 100]
    path = tmp_path / "限售股插列.xlsx"
    pd.DataFrame([["限售股转让所得个人所得税扣缴报告表"], headers, row]).to_excel(path, index=False, header=False)
    records, issues = parse_declaration_file(path)
    assert not issues
    assert records[0]["扣缴税额"] == 100


@pytest.mark.parametrize("batch_import", [False, True])
def test_official_restricted_multilevel_headers_and_income_reach_summary(tmp_path, monkeypatch, batch_import):
    from fastapi import UploadFile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.config import settings
    from app.core.company_context import set_company_id, reset_company_id
    from app.db.session import Base
    from app.models.core import Company, Period
    from app.models.accounting import OrganizationMapping, ReconciliationImportRow
    from app.services.reconciliation_import import import_pit_declaration_file, import_pit_declaration_files
    from app.services.pit_reconciliation.source_service import PitSourceService
    from app.services.pit_reconciliation.rules.declaration_summary import summarize

    headers = list(RESTRICTED_HEADERS)
    headers[2:5] = ["纳税人有效身份证件", "", ""]
    headers[12:15] = ["限售股原值及合理税费", "", ""]
    leaf = [""] * len(headers)
    for index, value in {2: "证件类型", 3: "证件号码", 12: "小计", 13: "原值", 14: "合理税费"}.items():
        leaf[index] = value
    data = [1, "测试客户", "居民身份证", "ID1", "", "A", "S", "股票", 10, 100, "", 1000, 500, 450, 50, "", 0, 500, "20%", 0, 100]
    path = tmp_path / "10501_限售股.xlsx"
    pd.DataFrame([
        ["限售股转让所得个人所得税扣缴报告表"], headers,
        [""] * len(headers), leaf, list(range(1, 22)), data,
    ]).to_excel(path, index=False, header=False)
    records, issues = parse_declaration_file(path)
    assert not issues
    assert len(records) == 1
    assert records[0]["证件号码"] == "ID1"
    assert records[0]["原值及合理税费小计"] == 500
    assert records[0]["转让收入额"] == 1000
    assert records[0]["扣缴税额"] == 100

    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(name="测试公司", code="TEST", operator_name="测试")
        db.add(company); db.flush()
        token = set_company_id(company.id)
        try:
            period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
            db.add(period); db.flush()
            db.add(OrganizationMapping(company_id=company.id, org_code="10501", branch_name="测试营业部"))
            db.commit()
            with path.open("rb") as stream:
                upload = UploadFile(filename=path.name, file=stream)
                batch = (import_pit_declaration_files(db, period_id=period.id, files=[upload])
                         if batch_import else import_pit_declaration_file(db, period_id=period.id, file=upload))
            stored = db.query(ReconciliationImportRow).filter_by(batch_id=batch.id).one()
            assert stored.income_amount == Decimal("1000.00")
            assert stored.tax_amount == Decimal("100.00")
            # Legacy imports may have a null standard income but keep the raw value.
            stored.income_amount = None
            db.flush()
            source = PitSourceService(db, company.id, period.id).load_declaration_source()
            summary = next(iter(summarize(source.rows).values()))
            assert summary["person_count"] == 1
            assert summary["income_amount"] == Decimal("1000.00")
            assert summary["tax_amount"] == Decimal("100.00")
        finally:
            reset_company_id(token)
    engine.dispose()


def test_zero_tax_value_does_not_fall_back_to_another_tax_column():
    from app.services.reconciliation_import import _first_present

    assert _first_present({"应补退税额": 0, "扣缴税额": 100}, "应补退税额", "扣缴税额") == 0
