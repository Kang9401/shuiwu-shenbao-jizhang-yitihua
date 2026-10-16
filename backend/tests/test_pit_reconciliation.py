from decimal import Decimal

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.accounting import OrganizationMapping, ReconciliationImportBatch, ReconciliationImportRow
from app.models.core import Company, Period
from app.models.tax import TaxMonthlyArtifact
from app.models.pit_reconciliation import PitReconciliationWorkpaper, PitTaxAmountCheck
from app.services.pit_reconciliation.domain import (BalanceRow, BankRow, BondInterestRow, BrokerRow, DeclarationRow, OrganizationRow, PitSourceBundle, RestrictedStockRow, SalaryRow, SourceResult, TaxCertificateRow)
from app.services.pit_reconciliation.engine import PitReconciliationEngine
from app.services.pit_reconciliation.money import has_difference, money_or_none
from app.services.pit_reconciliation.organization_resolver import PitOrganizationResolver
from app.services.pit_reconciliation.repository import PitReconciliationRepository
from app.services.pit_reconciliation.source_service import PitSourceService, _org_code
from app.services.reconciliation_import import _column_map
from app.services.pit_reconciliation.rules.occurrence import calc_vat
from app.services.pit_reconciliation.rules.payment import find_subset_sum
from app.services.pit_reconciliation.rules.bond_interest import bond_interest_details
from app.services.pit_reconciliation.rules.restricted_stock import restricted_stock_details
from app.services.pit_reconciliation.keys import preferred_id_number
from app.services.pit_reconciliation.rules.salary_tax import salary_tax_details
from app.services.pit_reconciliation.rules.salary_taxable_income import salary_taxable_income_details
from app.services.pit_reconciliation.exporter import _balance_display_rows
from app.services.verification import load_headquarters_payroll


def _db():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _bundle(salary_tax=Decimal("100.00")):
    empty=lambda name, required=True: SourceResult(name,"ready_empty",required=required)
    return PitSourceBundle(
        SourceResult("organization_mapping","ready",[OrganizationRow("10001","测试营业部","测试营业部全称")]),
        SourceResult("salary","ready",[SalaryRow("10001","张三",id_number="ID1",employee_no="E1",pit_tax=salary_tax,cumulative_taxable_income=Decimal("1000"))]),
        SourceResult("pit_declaration","ready",[DeclarationRow("10001","综合所得",person_name="张三",id_number="ID1",income_item="正常工资薪金",income_amount=Decimal("1000"),tax_amount=Decimal("180"),cumulative_taxable_income=Decimal("1200"))]),
        SourceResult("balance_sheet","ready",[BalanceRow("10001","21510006","21510006",credit_amount=Decimal("180"),closing_balance=Decimal("180"))]),
        empty("broker"),empty("bond_interest"),empty("restricted_stock"),empty("tax_certificate",False),empty("bank_statement",False),
    )


def test_money_distinguishes_missing_from_real_zero():
    assert money_or_none(None) is None
    assert money_or_none(0) == Decimal("0.00")


def test_manual_masked_identity_mapping_is_per_source_row_and_shared_by_a1_a2():
    from app.services.pit_reconciliation.keys import identity_mapping_rows
    salaries = [SalaryRow("10001", "同名", id_number=identity, pit_tax=Decimal(tax), cumulative_taxable_income=Decimal(income))
                for identity, tax, income in [("110101199001010011", "10", "100"), ("110101199001010021", "20", "200")]]
    declarations = [DeclarationRow("10001", "综合所得", person_name="同名", id_number="1****************1", income_item="正常工资薪金",
                                   tax_amount=Decimal(tax), cumulative_taxable_income=Decimal(income), tax_rate="10%",
                                   raw_data={"file_name": "申报.xlsx", "row_number": index})
                    for index, tax, income in [(1, "11", "110"), (2, "22", "220")]]
    rows = identity_mapping_rows(salaries, declarations)
    assert len({row["row_key"] for row in rows}) == 2
    assert all(row["status"] == "manual_review" for row in rows)
    mappings = {row["row_key"]: salary.id_number for row, salary in zip(rows, salaries)}
    a1 = salary_tax_details(salaries, declarations, mappings)
    a2 = salary_taxable_income_details(salaries, declarations, mappings)
    assert [(row["source_amount"], row["target_amount"]) for row in a1] == [(Decimal("10"), Decimal("11")), (Decimal("20"), Decimal("22"))]
    assert [row["identity_key"] for row in a1] == [row["identity_key"] for row in a2]
    assert all(row["detail_json"]["identity_match_status"] == "manual_confirmed" for row in a1 + a2)
    assert all(item["tax_rate"] == "10%" for row in a1 for item in row["detail_json"]["comparison_items"])
    # Clearing or stale/invalid choices must return to manual review, never force a join.
    assert any(row["detail_json"]["identity_match_status"] == "manual_review" for row in salary_tax_details(salaries, declarations, {}))
    assert all(row["status"] == "manual_review" for row in identity_mapping_rows(salaries, declarations, dict.fromkeys(mappings, "220101199001010011")))
    # Even identical source metadata must produce separate deterministic keys.
    duplicate = identity_mapping_rows(salaries, [declarations[0], declarations[0]])
    assert duplicate[0]["row_key"] != duplicate[1]["row_key"]
    assert duplicate == identity_mapping_rows(salaries, [declarations[0], declarations[0]])
    from dataclasses import replace
    assert identity_mapping_rows([replace(row, org_code="10002") for row in salaries], declarations)[0]["candidates"] == []
    assert identity_mapping_rows([replace(row, person_name="不同姓名") for row in salaries], declarations)[0]["candidates"] == []


def test_a1_shows_all_actual_declaration_rates_without_fabricating_missing_rate():
    salaries = [SalaryRow("10001", "张三", id_number="110101199001010011", pit_tax=Decimal("10"))]
    declarations = [DeclarationRow("10001", "综合所得", person_name="张三", id_number=salaries[0].id_number,
                                  income_item="正常工资薪金", tax_amount=Decimal("6"), tax_rate=rate) for rate in ("3%", "10%", "")]
    result = salary_tax_details(salaries, declarations)
    assert {item["tax_rate"] for item in result[0]["detail_json"]["comparison_items"]} == {"10% / 3%"}


def test_manual_mapping_supports_nonresident_documents_and_cross_org_names():
    from app.services.pit_reconciliation.keys import identity_mapping_rows, payroll_mapping_options
    salaries = [
        SalaryRow("17007", "胡启东", id_number="G04725198", pit_tax=Decimal("599.19"), cumulative_taxable_income=Decimal("62154.89")),
        SalaryRow("11968", "张见欢", id_number="330881199412194120", pit_tax=Decimal("627.81"), cumulative_taxable_income=Decimal("132805.72")),
    ]
    declarations = [
        DeclarationRow("17007", "综合所得", person_name="HU QIDONG", id_number="P*******D", income_item="正常工资薪金", tax_amount=Decimal("599.19"), cumulative_taxable_income=Decimal("62154.89"), raw_data={"row_number": 1}),
        DeclarationRow("17007", "综合所得", person_name="张见欢", id_number="3****************0", income_item="正常工资薪金", tax_amount=Decimal("627.81"), cumulative_taxable_income=Decimal("132805.72"), raw_data={"row_number": 2}),
    ]
    rows = identity_mapping_rows(salaries, declarations)
    options = payroll_mapping_options(salaries)
    by_name = {option["name"]: option["target_key"] for option in options}
    mapping = {row["row_key"]: by_name[name] for row, name in zip(rows, ("胡启东", "张见欢"))}
    a1 = salary_tax_details(salaries, declarations, mapping)
    a2 = salary_taxable_income_details(salaries, declarations, mapping)
    assert all(item["difference"] == Decimal("0") for item in a1 + a2)
    assert all(item["detail_json"]["identity_match_status"] == "manual_confirmed" for item in a1 + a2)
    assert all("manual_identity" in item["detail_json"] for item in a1 + a2)


def test_scoped_declaration_includes_general_labor_but_keeps_other_tax_in_total():
    from app.services.pit_reconciliation.rules.tax_amount import declared_by_subject
    rows = [DeclarationRow("10001", "综合所得", income_item=kind, tax_amount=Decimal("1"))
            for kind in ("正常工资薪金", "一般劳务报酬所得", "全年一次性奖金收入", "解除劳动合同一次性补偿收入")]
    values, scoped = declared_by_subject(rows, "10001")
    assert values["21510006"] == Decimal("4")
    assert scoped["21510006"] == Decimal("2")


def test_declaration_and_security_display_preserves_available_fields_and_zero():
    from app.services.pit_reconciliation.exporter import _declaration_display_rows, _security_display_rows, RESTRICTED_DECLARATION_COLUMNS, BOND_COLUMNS, RESTRICTED_COLUMNS
    source = {"file_name": "申报表.xlsx", "每股计税价格": 10, "转让股数": 100, "原值及合理税费小计": 500, "证件类型": "居民身份证", "扣缴税额": 0}
    row = _declaration_display_rows([source], RESTRICTED_DECLARATION_COLUMNS)[0]
    assert row["文件名"] == "申报表.xlsx"
    assert row["每股计税价格（元/股)"] == 10
    assert row["转让股数(股)"] == 100
    assert row["限售股原值及合理税费_小计"] == 500
    assert row["纳税人有效身份证件_证件类型"] == "居民身份证"
    assert row["扣缴税额"] == 0
    assert _declaration_display_rows([{"收入": 3, "本月（次）情况_收入额计算_收入": 0}])[0]["本月（次）情况_收入额计算_收入"] == 0
    security = {"机构代码": "10001", "营业部名称": "测试", "业务日期": "20260901", "资产账号": "001", "手机号码": "13800000000", "出生日期": "19900101", "成交金额": 0}
    assert _security_display_rows([security], BOND_COLUMNS)[0]["出生年月日"] == "19900101"
    row = _security_display_rows([security], RESTRICTED_COLUMNS)[0]
    assert row["资产账户"] == "001"
    assert row["客户手机号码"] == "13800000000"
    assert row["卖出金额"] == 0


def test_headquarters_cumulative_fields_reach_a2_only_when_present(tmp_path):
    input_path = tmp_path / "总部工资单.xlsx"
    pd.DataFrame([{"姓名": "总部员工", "员工编号": "H1", "机构代码": "10001", "个人所得税": 10,
                   "累计预扣预缴应纳税所得额": 200, "累计减除费用": 60000}]).to_excel(input_path, index=False)
    payroll = load_headquarters_payroll(str(input_path))
    assert payroll.iloc[0]["工资表_累计应纳税所得额"] == 200
    db = _db()
    try:
        company = Company(name="测试", code="TEST", operator_name="测试")
        db.add(company); db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add(period); db.flush()
        path = tmp_path / "working.xlsx"
        payroll["工资单类型"] = "总部工资单"
        payroll.to_excel(path, index=False)
        db.add(TaxMonthlyArtifact(company_id=company.id, period_id=period.id, artifact_type="working_sheet", file_name=path.name, stored_path=str(path)))
        db.flush()
        source = PitSourceService(db, company.id, period.id).load_salary_source()
        assert source.status == "ready"
        assert source.rows[0].cumulative_taxable_income == Decimal("200")
        details = salary_taxable_income_details(source.rows, [DeclarationRow("10001", "综合所得", person_name="总部员工", income_item="正常工资薪金", cumulative_taxable_income=Decimal("220"))])
        assert details[0]["difference"] == Decimal("-20")
    finally:
        db.close()


def test_securities_source_filters_other_income_rows_before_counting(tmp_path):
    from app.models.core import Artifact, Job
    db = _db()
    try:
        company = Company(name="测试", code="TEST", operator_name="测试")
        db.add(company); db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add(period); db.flush()
        db.add(OrganizationMapping(company_id=company.id, org_code="10001", branch_name="测试"))
        job = Job(company_id=company.id, period_id=period.id, workflow_code="restricted_stock_interest_tax", status="success", input_file_ids=[])
        db.add(job); db.flush()
        path = tmp_path / "security.xlsx"
        pd.DataFrame([
            {"所得类型": "利息税", "机构代码": "10001", "客户姓名": "甲", "证件号码": "A", "债券兑息": 100, "兑息扣税": 20},
            {"所得类型": "限售股", "机构代码": "10001", "客户姓名": "乙", "证件号码": "B", "成交金额": 200, "利息税": 40},
        ]).to_excel(path, index=False)
        db.add(Artifact(company_id=company.id, job_id=job.id, artifact_type="restricted_stock_interest_result", file_name=path.name, stored_path=str(path)))
        db.flush()
        source = PitSourceService(db, company.id, period.id)
        bonds, stocks = source.load_bond_source(), source.load_restricted_source()
        assert len(bonds.rows) == len(stocks.rows) == 1
        assert bonds.rows[0].customer_name == "甲" and bonds.rows[0].withheld_tax == Decimal("20")
        assert stocks.rows[0].customer_name == "乙" and stocks.rows[0].withheld_tax == Decimal("40")
    finally:
        db.close()


def test_artifact_organization_code_removes_excel_numeric_suffix():
    assert _org_code(13201.0) == "13201"
    assert _org_code("13201") == "13201"


def test_organization_resolver_matches_pdf_wrapped_name_after_normalization():
    db = _db()
    company = Company(name="机构匹配测试", code="ORG_MATCH", operator_name="测试")
    db.add(company); db.flush()
    db.add(OrganizationMapping(
        company_id=company.id, org_code="13301", branch_name="佛山顺德大良保利国际金融中心证券营业部",
        rpa_org_name="广发证券股份有限公司佛山顺德大良保利国际金融中心证券营业部",
    ))
    db.commit()
    resolver = PitOrganizationResolver(db, company.id)
    assert resolver.resolve_by_full_name("广发证券股份有限公司佛山顺德大良保利国际金融中心证\n券营业部").org_code == "13301"


def test_subset_sum_handles_large_no_solution_pool_without_combinatorial_search():
    values = [Decimal("1.01")] * 253
    assert find_subset_sum(values, Decimal("9999.99")) is None
    assert find_subset_sum(values, Decimal("3.03")) == [0, 1, 2]


def test_recalculate_keeps_single_workpaper_and_manual_reason():
    db=_db(); company=Company(name="测试公司",code="TEST",operator_name="测试"); db.add(company); db.flush(); period=Period(company_id=company.id,year=2026,month=8,name="2026-08"); db.add(period); db.commit()
    repository=PitReconciliationRepository(db,company.id,period.id,"pre_payment"); workpaper=repository.get_or_create_workpaper(); engine=PitReconciliationEngine()
    repository.replace(workpaper,engine.calculate(_bundle())); db.commit()
    check=db.query(PitTaxAmountCheck).filter_by(workpaper_id=workpaper.id,subject_code="21510006").one(); assert check.business_tax_amount==Decimal("100.00")
    check.business_declared_manual_reason="工资补发造成"; db.commit()
    repository.replace(repository.get_or_create_workpaper(),engine.calculate(_bundle(Decimal("120.00")))); db.commit()
    assert db.query(PitReconciliationWorkpaper).filter_by(company_id=company.id,period_id=period.id).count()==1
    revised=db.query(PitTaxAmountCheck).filter_by(workpaper_id=workpaper.id,subject_code="21510006").one()
    assert revised.business_tax_amount==Decimal("120.00")
    assert revised.business_declared_manual_reason=="工资补发造成"


def test_missing_salary_does_not_become_zero():
    result=PitReconciliationEngine().calculate(_bundle())
    result["sources"][1]["status"]="missing"
    missing=_bundle(); missing.salary=SourceResult("salary","missing")
    result=PitReconciliationEngine().calculate(missing)
    tax=next(row for row in result["tax_checks"] if row["subject_code"]=="21510006")
    assert tax["business_tax_amount"] is None
    assert tax["business_declared_difference"] is None


def test_duplicate_customer_identity_keys_get_stable_suffixes():
    bundle = _bundle()
    bundle.bond_interest = SourceResult(
        "bond_interest", "ready", [
            BondInterestRow("10001", "甲", "ID1", Decimal("100"), Decimal("10")),
        ],
    )
    bundle.declarations.rows.append(
        DeclarationRow(
            "10001", "利息", person_name="乙", id_number="ID1",
            income_item="其他利息、股息、红利所得", income_amount=Decimal("100"), tax_amount=Decimal("20"),
        )
    )
    result = PitReconciliationEngine().calculate(bundle)
    details = [row for row in result["details"] if row["detail_type"] == "bond_interest_tax"]
    assert len(details) == 2
    assert len({row["identity_key"] for row in details}) == 2
    assert any(row.get("detail_json", {}).get("identity_key_collision") for row in details)


def test_masked_and_full_customer_ids_prefer_full_id_deterministically():
    assert preferred_id_number({"4****************7", "440204196604284717"}) == "440204196604284717"
    details = bond_interest_details(
        [BondInterestRow("10001", "甲", "4****************7", Decimal("100"), Decimal("10"))],
        [DeclarationRow("10001", "利息", person_name="甲", id_number="440204196604284717", income_item="其他利息、股息、红利所得", income_amount=Decimal("100"), tax_amount=Decimal("20"))],
    )
    assert details[0]["id_number"] == "440204196604284717"
    assert details[0]["identity_key"] == "id:440204196604284717"


def test_tax_difference8_uses_credit_movement_and_summary_balance_uses_closing_balance():
    bundle = _bundle()
    bundle.balance.rows[0] = BalanceRow(
        "10001", "21510006", "21510006",
        credit_amount=Decimal("999.00"), closing_balance=Decimal("175.00"),
    )

    result = PitReconciliationEngine().calculate(bundle)

    tax = next(row for row in result["tax_checks"] if row["subject_code"] == "21510006")
    assert tax["current_difference"] == Decimal("-819.00")
    assert tax["cumulative_difference"] == Decimal("5.00")
    assert result["org_summaries"][0]["balance_tax_amount"] == Decimal("175.00")
    assert result["org_summaries"][0]["difference_1"] == Decimal("5.00")


def test_summary_keeps_available_business_tax_when_another_business_source_is_missing():
    bundle = _bundle()
    bundle.salary = SourceResult("salary", "ready", [SalaryRow("10001", "张三", pit_tax=Decimal("100"))])
    bundle.broker = SourceResult("broker", "missing")
    result = PitReconciliationEngine().calculate(bundle)
    summary = result["org_summaries"][0]
    assert summary["payroll_business_tax_amount"] == Decimal("100.00")


def test_occurrence_declaration_difference_is_counted_once_per_income_type():
    bundle = _bundle()
    bundle.declarations = SourceResult("pit_declaration", "ready", [
        DeclarationRow("10001", "综合所得", income_item="证券经纪人佣金收入", income_amount=Decimal("645.87")),
    ])
    bundle.balance = SourceResult("balance_sheet", "ready", [
        BalanceRow("10001", "21131042", "21131042", debit_amount=Decimal("500.00")),
        BalanceRow("10001", "45019006", "45019006", debit_amount=Decimal("552.91")),
    ])
    bundle.broker = SourceResult("broker", "ready", [
        BrokerRow("10001", gross_before_topup=Decimal("558.49"), vat_amount=Decimal("5.58")),
    ])
    result = PitReconciliationEngine().calculate(bundle)
    rows = [row for row in result["occurrence_checks"] if row["income_type"] == "证券经纪人佣金收入"]
    assert sum((row["expected_declared_income"] or Decimal("0.00") for row in rows), Decimal("0.00")) == Decimal("1052.91")
    assert sum((row["actual_declared_income"] or Decimal("0.00") for row in rows), Decimal("0.00")) == Decimal("645.87")
    assert sum((row["declared_income_difference"] or Decimal("0.00") for row in rows), Decimal("0.00")) == Decimal("-407.04")
    assert result["org_summaries"][0]["other_income_difference"] == Decimal("-407.04")


def test_vat_boundaries_match_legacy_threshold():
    assert [calc_vat(Decimal(value)) for value in ("0", "1000", "1009.99", "1010", "1010.01", "10000")] == [
        Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("10.00"), Decimal("10.00"), Decimal("99.01"),
    ]


def test_one_cent_is_reported_as_difference():
    assert has_difference(Decimal("0.01"))
    assert has_difference(Decimal("-0.01"))
    assert not has_difference(Decimal("0.00"))


def test_a2_same_name_exact_income_pairing_is_preserved():
    salary = [
        SalaryRow("10001", "李四", id_number="A", employee_no="1", cumulative_taxable_income=Decimal("100")),
        SalaryRow("10001", "李四", id_number="B", employee_no="2", cumulative_taxable_income=Decimal("200")),
    ]
    declarations = [
        DeclarationRow("10001", "综合所得", person_name="李四", id_number="X", income_item="正常工资薪金", cumulative_taxable_income=Decimal("250")),
        DeclarationRow("10001", "综合所得", person_name="李四", id_number="Y", income_item="正常工资薪金", cumulative_taxable_income=Decimal("100")),
    ]
    details = salary_taxable_income_details(salary, declarations)
    assert len(details) == 1
    assert details[0]["id_number"] == "B"
    assert details[0]["difference"] == Decimal("-50")


def test_a2_remaining_records_pair_in_original_order_and_keep_null_side():
    salary = [SalaryRow("10001", "同名", id_number="P1", cumulative_taxable_income=Decimal("100")), SalaryRow("10001", "同名", id_number="P2", cumulative_taxable_income=Decimal("200"))]
    declarations = [DeclarationRow("10001", "综合所得", person_name="同名", id_number="D1", income_item="正常工资薪金", cumulative_taxable_income=Decimal("150")), DeclarationRow("10001", "综合所得", person_name="同名", id_number="D2", income_item="正常工资薪金", cumulative_taxable_income=Decimal("300"))]
    details = salary_taxable_income_details(salary, declarations)
    assert [(item["id_number"], item["source_amount"], item["target_amount"]) for item in details] == [("P1", Decimal("100"), Decimal("150")), ("P2", Decimal("200"), Decimal("300"))]


def test_a2_declaration_extra_exposes_missing_payroll_as_null():
    details = salary_taxable_income_details([], [DeclarationRow("10001", "综合所得", person_name="缺工资", income_item="正常工资薪金", cumulative_taxable_income=Decimal("50"))])
    assert details[0]["source_amount"] is None
    assert details[0]["target_amount"] == Decimal("50")
    assert details[0]["detail_json"]["payroll_taxable_income"] is None


def test_same_name_with_distinct_full_ids_is_not_merged():
    salary = [
        SalaryRow("10001", "同名", id_number="110101199001010011", pit_tax=Decimal("10")),
        SalaryRow("10001", "同名", id_number="110101199001010022", pit_tax=Decimal("20")),
    ]
    declarations = [
        DeclarationRow("10001", "综合所得", person_name="同名", id_number="110101199001010011", income_item="正常工资薪金", tax_amount=Decimal("10")),
        DeclarationRow("10001", "综合所得", person_name="同名", id_number="110101199001010022", income_item="正常工资薪金", tax_amount=Decimal("30")),
    ]
    details = salary_tax_details(salary, declarations)
    assert len(details) == 1
    assert details[0]["id_number"] == "110101199001010022"
    assert details[0]["difference"] == Decimal("10")


def test_masked_identity_matches_only_when_org_name_and_edges_are_unique():
    salary = [SalaryRow("19020", "张三", id_number="440204196604284717", pit_tax=Decimal("10"))]
    declarations = [DeclarationRow("19020", "综合所得", person_name="张三", id_number="4****************7", income_item="正常工资薪金", tax_amount=Decimal("11"))]
    details = salary_tax_details(salary, declarations)
    assert details[0]["identity_key"] == "id:440204196604284717"
    assert details[0]["detail_json"]["identity_match_status"] == "confirmed"

    salary.append(SalaryRow("19020", "张三", id_number="440204196604284727", pit_tax=Decimal("20")))
    details = salary_tax_details(salary, declarations)
    assert any(row["detail_json"]["identity_match_status"] == "manual_review" for row in details)


def test_a2_excludes_headquarters_rows_without_cumulative_payroll_fields():
    salary = [SalaryRow("10001", "总部人员", salary_kind="headquarters", pit_tax=Decimal("100"))]
    declarations = [DeclarationRow(
        "10001", "综合所得", person_name="总部人员", income_item="正常工资薪金",
        tax_amount=Decimal("100"), cumulative_taxable_income=Decimal("50000"),
    )]

    assert salary_taxable_income_details(salary, declarations) == []


def test_engine_emits_all_tax_and_occurrence_subjects():
    bundle = _bundle()
    bundle.balance.rows.extend([
        BalanceRow("10001", code, code, debit_amount=Decimal("200"), credit_amount=Decimal("100"), closing_balance=Decimal("100"))
        for code in ("21510008", "21510009", "21510016", "21131042", "45019006", "21210037", "21210038", "21210012")
    ])
    bundle.broker = SourceResult("broker", "ready", [BrokerRow("10001", pit_tax=Decimal("10"), gross_before_topup=Decimal("200"), vat_amount=Decimal("2"))])
    bundle.bond_interest = SourceResult("bond_interest", "ready", [BondInterestRow("10001", "王五", withheld_tax=Decimal("8"), interest_amount=Decimal("40"))])
    bundle.restricted_stock = SourceResult("restricted_stock", "ready", [RestrictedStockRow("10001", "赵六", withheld_tax=Decimal("9"), sale_amount=Decimal("90"))])
    result = PitReconciliationEngine().calculate(bundle)
    assert {row["subject_code"] for row in result["tax_checks"]} == {"21510006", "21510008", "21510009", "21510016"}
    assert {row["subject_code"] for row in result["occurrence_checks"]} == {"21131042", "45019006", "21210037", "21210038", "21210012"}
    names = {row["detail_type"]: row["org_name"] for row in result["details"]}
    assert names["salary_tax"] == "测试营业部"
    assert names["bond_interest_tax"] == "测试营业部"
    assert names["restricted_stock_tax"] == "测试营业部"


def test_subject_descriptions_use_real_balance_description_then_standard_fallback():
    bundle = _bundle()
    bundle.balance.rows[0] = BalanceRow("10001", "21510006", "21510006", description="某真实描述", credit_amount=Decimal("180"), closing_balance=Decimal("180"))

    result = PitReconciliationEngine().calculate(bundle)

    tax_rows = {row["subject_code"]: row for row in result["tax_checks"]}
    occurrence_rows = {row["subject_code"]: row for row in result["occurrence_checks"]}
    assert tax_rows["21510006"]["subject_name"] == "某真实描述"
    assert tax_rows["21510008"]["subject_name"]
    assert occurrence_rows["21131042"]["subject_name"]


def test_balance_sheet_import_recognizes_description_as_account_name():
    mapping = _column_map("balance_sheet", pd.DataFrame(columns=["会计科目", "公司段", "金额", "描述"]))
    assert mapping["account_name"] == "描述"


def test_detail_json_contains_a1_a2_a3_a4_display_values():
    declarations = [
        DeclarationRow("10001", "综合所得", person_name="张三", income_item="正常工资薪金", tax_amount=Decimal("60"), cumulative_taxable_income=Decimal("120")),
        DeclarationRow("10001", "分类所得", person_name="王五", income_item="其他利息、股息、红利所得", tax_amount=Decimal("12")),
        DeclarationRow("10001", "限售股所得", person_name="赵六", income_item="限售股转让所得", tax_amount=Decimal("15")),
    ]
    salary = SalaryRow("10001", "张三", pit_tax=Decimal("50"), cumulative_taxable_income=Decimal("100"))
    a1 = salary_tax_details([salary], declarations)[0]["detail_json"]
    a2 = salary_taxable_income_details([salary], declarations)[0]["detail_json"]
    a3 = bond_interest_details([BondInterestRow("10001", "王五", id_number="I1", interest_amount=Decimal("100"), withheld_tax=Decimal("10"))], declarations)[0]["detail_json"]
    a4 = restricted_stock_details([RestrictedStockRow("10001", "赵六", id_number="I2", security_name="证券A", sale_amount=Decimal("300"), withheld_tax=Decimal("12"))], declarations)[0]["detail_json"]
    assert {"payroll_tax_amount", "declared_tax_amount", "comparison_items"}.issubset(a1)
    assert len(a1["comparison_items"]) == 10
    assert {"payroll_taxable_income", "declared_taxable_income", "specific_deduction_difference", "tax_difference"}.issubset(a2)
    assert {"interest_amount", "business_tax_amount", "declared_tax_amount", "id_numbers", "same_name_merged"}.issubset(a3)
    assert {"security_names", "sale_amount", "business_tax_amount", "declared_tax_amount"}.issubset(a4)


def test_bond_interest_uses_actual_interest_and_withheld_tax_separately():
    declaration = DeclarationRow("10001", "分类所得", person_name="王五", income_item="其他利息、股息、红利所得", tax_amount=Decimal("210"))
    detail = bond_interest_details([BondInterestRow("10001", "王五", interest_amount=Decimal("1000"), withheld_tax=Decimal("200"))], [declaration])[0]
    assert detail["difference"] == Decimal("10")
    assert detail["detail_json"]["interest_amount"] == "1000.00"
    assert detail["detail_json"]["business_tax_amount"] == "200.00"
    assert detail["detail_json"]["declared_tax_amount"] == "210.00"


def test_bank_prefers_tax_summary_pool_without_all_transaction_fallback():
    bundle = _bundle()
    bundle.certificates = SourceResult("tax_certificate", "ready", [TaxCertificateRow("10001", tax_type="个人所得税", amount=Decimal("100"))], required=False)
    bundle.bank = SourceResult("bank_statement", "ready", [BankRow(org_code="10001", summary="服务费", debit_amount=Decimal("100")), BankRow(org_code="10001", summary="缴纳个税", debit_amount=Decimal("100"))], required=False)
    result = PitReconciliationEngine().calculate(bundle)
    assert [row["transaction_summary"] for row in result["bank_matches"]] == ["缴纳个税"]


def test_bank_subset_matching_is_scoped_to_each_organization():
    bundle = _bundle()
    bundle.organizations.rows.append(OrganizationRow("10002", "二部", "二部全称"))
    bundle.certificates = SourceResult("tax_certificate", "ready", [
        TaxCertificateRow("10001", tax_type="个人所得税", amount=Decimal("100")),
        TaxCertificateRow("10002", tax_type="个人所得税", amount=Decimal("200")),
    ], required=False)
    bundle.bank = SourceResult("bank_statement", "ready", [
        BankRow(org_code="10001", summary="缴税", debit_amount=Decimal("100")),
        BankRow(org_code="10002", summary="缴税", debit_amount=Decimal("200")),
    ], required=False)
    result = PitReconciliationEngine().calculate(bundle)
    assert {(row["org_code"], row["debit_amount"]) for row in result["bank_matches"]} == {
        ("10001", Decimal("100")), ("10002", Decimal("200"))
    }


def test_bank_source_reports_unresolved_rows_and_engine_excludes_them():
    db = _db()
    company = Company(name="测试公司", code="TEST", operator_name="测试")
    db.add(company); db.flush()
    period = Period(company_id=company.id, year=2026, month=7, name="2026-07")
    db.add(period); db.flush()
    db.add(OrganizationMapping(company_id=company.id, branch_name="测试营业部全称", org_code="10001", bank_subaccount="001.02"))
    db.add(OrganizationMapping(company_id=company.id, branch_name="另一营业部", org_code="10002", bank_account="002.03"))
    batch = ReconciliationImportBatch(company_id=company.id, period_id=period.id, import_type="bank_statement", original_name="bank.xlsx", stored_path="bank.xlsx", row_count=4)
    db.add(batch); db.flush()
    db.add_all([
        ReconciliationImportRow(company_id=company.id, batch_id=batch.id, period_id=period.id, import_type="bank_statement", row_number=1, transaction_date="2026-07-10", summary="缴税", amount=Decimal("100"), raw_data={"本方户名": "另一营业部", "本方账号": " 001.02 ", "借方金额": "100"}),
        ReconciliationImportRow(company_id=company.id, batch_id=batch.id, period_id=period.id, import_type="bank_statement", row_number=2, transaction_date="2026-07-11", summary="缴税", amount=Decimal("100"), raw_data={"本方户名": "未知机构", "本方账号": "999.99", "借方金额": "100"}),
        ReconciliationImportRow(company_id=company.id, batch_id=batch.id, period_id=period.id, import_type="bank_statement", row_number=3, amount=Decimal("200"), raw_data={"本方户名": "未知机构", "本方账号": "９９９.９９", "借方金额": "200"}),
        ReconciliationImportRow(company_id=company.id, batch_id=batch.id, period_id=period.id, import_type="bank_statement", row_number=4, amount=Decimal("50"), raw_data={"本方户名": "另一未知机构", "本方账号": "888.88", "借方金额": "50"}),
    ])
    db.commit()

    source = PitSourceService(db, company.id, period.id).load_bank_source()

    # The account wins even when the holder name resolves to a different branch.
    assert source.status == "ready"
    assert [row.org_code for row in source.rows] == ["10001", "", "", ""]
    assert source.issues == [{
        "issue_type": "unresolved_bank_organization",
        "message": "银行账号：999.99；户名：未知机构；流水共 2 条",
        "row_id": source.rows[1].source_row_id,
        "bank_account": "999.99",
        "account_name": "未知机构",
        "transaction_count": 2,
    }, {
        "issue_type": "unresolved_bank_organization",
        "message": "银行账号：888.88；户名：另一未知机构；流水共 1 条",
        "row_id": source.rows[3].source_row_id,
        "bank_account": "888.88",
        "account_name": "另一未知机构",
        "transaction_count": 1,
    }]


def test_salary_source_accepts_generated_working_sheet_org_columns(tmp_path):
    db = _db()
    company = Company(name="测试公司", code="TEST", operator_name="测试")
    db.add(company); db.flush()
    period = Period(company_id=company.id, year=2026, month=7, name="2026-07")
    db.add(period); db.flush()
    path = tmp_path / "working_sheet.xlsx"
    import pandas as pd
    pd.DataFrame([{
        "机构代码_工资单": "10001", "*姓名": "张三", "证件号码": "ID1",
        "员工编号": "1000001", "工资单类型": "营销工资单", "个人所得税 SUM": "12.34",
        "工资表_累计应纳税所得额": "1234.56", "工资表_累计减除费用": "5000",
        "工资表_累计养老保险金员工部分": "100", "工资表_累计医疗保险金员工部分": "20",
        "工资表_累计失业保险金员工部分": "10", "工资表_累计住房公积金员工部分": "200",
        "工资单_累计子女教育扣除": "1000", "工资单_累计继续教育扣除": "0",
        "工资单_累计住房贷款利息扣除": "0", "工资单_累计住房租金扣除": "0",
        "工资单_累计赡养老人扣除": "0", "工资单_累计婴幼儿照护扣除": "0",
        "工资单_累计个人养老金": "0", "工资表_累计企业年金员工部分": "30",
        "工资表_累计商业保险扣除": "0",
    }]).to_excel(path, index=False)
    db.add(TaxMonthlyArtifact(company_id=company.id, period_id=period.id, artifact_type="working_sheet", file_name=path.name, stored_path=str(path)))
    db.commit()

    source = PitSourceService(db, company.id, period.id).load_salary_source()

    assert source.status == "ready"
    assert source.rows[0].org_code == "10001"
    assert source.rows[0].pit_tax == Decimal("12.34")
    assert source.rows[0].salary_kind == "seven_digit"
    assert source.rows[0].cumulative_taxable_income == Decimal("1234.56")
    assert source.rows[0].cumulative_special_deduction == Decimal("330")
    assert source.rows[0].cumulative_child_education == Decimal("1000")


def test_salary_source_uses_headquarters_withheld_tax_when_personal_tax_is_absent(tmp_path):
    db = _db()
    company = Company(name="测试公司", code="TEST", operator_name="测试")
    db.add(company); db.flush()
    period = Period(company_id=company.id, year=2026, month=7, name="2026-07")
    db.add(period); db.flush()
    path = tmp_path / "working_sheet.xlsx"
    input_path = tmp_path / "headquarters.xlsx"
    pd.DataFrame([{
        "机构代码": "10001", "姓名": "总部员工", "员工编号": "总部001",
        "本期收入": "1000", "本期应预扣预缴税额": "88.66",
    }]).to_excel(input_path, index=False)
    payroll = load_headquarters_payroll(str(input_path))
    payroll["工资单类型"] = "总部工资单"
    payroll.to_excel(path, index=False)
    db.add(TaxMonthlyArtifact(company_id=company.id, period_id=period.id, artifact_type="working_sheet", file_name=path.name, stored_path=str(path)))
    db.commit()

    source = PitSourceService(db, company.id, period.id).load_salary_source()

    assert source.status == "ready"
    assert source.rows[0].pit_tax == Decimal("88.66")


def test_salary_source_keeps_zero_headquarters_personal_tax(tmp_path):
    db = _db()
    company = Company(name="测试公司", code="TEST", operator_name="测试")
    db.add(company); db.flush()
    period = Period(company_id=company.id, year=2026, month=7, name="2026-07")
    db.add(period); db.flush()
    path = tmp_path / "working_sheet.xlsx"
    pd.DataFrame([{
        "机构代码_工资单": "10001", "*姓名": "总部员工", "证件号码": "ID1",
        "员工编号": "总部001", "工资单类型": "总部工资单", "个人所得税": 0,
        "本期应预扣预缴税额": "88.66",
    }]).to_excel(path, index=False)
    db.add(TaxMonthlyArtifact(company_id=company.id, period_id=period.id, artifact_type="working_sheet", file_name=path.name, stored_path=str(path)))
    db.commit()

    source = PitSourceService(db, company.id, period.id).load_salary_source()

    assert source.rows[0].pit_tax == Decimal("0.00")


def test_balance_display_maps_current_import_headers():
    rows = _balance_display_rows([{
        "公司段": "17020", "会计科目": "21510008", "描述": "利息税",
        "期初余额": "1.00", "借方金额": "2.00", "贷方金额": "3.00", "期末余额": "4.00",
    }])
    assert rows[0]["期初余额(N)"] == "1.00"
    assert rows[0]["借方金额(N)"] == "2.00"
    assert rows[0]["贷方金额(N)"] == "3.00"
    assert rows[0]["期末余额(N)"] == "4.00"


def test_declaration_summary_counts_filing_records_without_changing_amounts():
    bundle = _bundle()
    bundle.declarations.rows = [
        DeclarationRow("10001", "分类所得", person_name="同一客户", id_number="ID1", income_item="其他利息、股息、红利所得", income_amount=Decimal("100"), tax_amount=Decimal("20")),
        DeclarationRow("10001", "分类所得", person_name="同一客户", id_number="ID1", income_item="其他利息、股息、红利所得", income_amount=Decimal("200"), tax_amount=Decimal("40")),
        DeclarationRow("10001", "分类所得", income_item="其他利息、股息、红利所得", income_amount=Decimal("50"), tax_amount=Decimal("10")),
        DeclarationRow("10001", "分类所得", income_item="其他利息、股息、红利所得", income_amount=Decimal("30"), tax_amount=Decimal("6")),
    ]
    summary = PitReconciliationEngine().calculate(bundle)["declaration_summaries"][0]
    assert summary["person_count"] == 4
    assert summary["income_amount"] == Decimal("380.00")
    assert summary["tax_amount"] == Decimal("76.00")


def test_salary_source_missing_a2_columns_reports_actual_working_sheet_headers(tmp_path):
    db = _db()
    company = Company(name="测试公司", code="TEST", operator_name="测试")
    db.add(company); db.flush()
    period = Period(company_id=company.id, year=2026, month=7, name="2026-07")
    db.add(period); db.flush()
    path = tmp_path / "working_sheet.xlsx"
    import pandas as pd
    pd.DataFrame([{
        "员工编号": "10001", "*姓名": "张三", "工资单类型": "职级工资单",
        "个人所得税 SUM": "12.34",
    }]).to_excel(path, index=False)
    db.add(TaxMonthlyArtifact(
        company_id=company.id, period_id=period.id, artifact_type="working_sheet",
        file_name=path.name, stored_path=str(path),
    ))
    db.commit()

    source = PitSourceService(db, company.id, period.id).load_salary_source()

    assert source.status == "invalid"
    assert source.issues[0]["issue_type"] == "payroll_header_missing"
    assert "工资表_累计应纳税所得额" in source.issues[0]["message"]
    assert "员工编号" in source.issues[0]["message"]
    assert "个人所得税 SUM" in source.issues[0]["message"]
