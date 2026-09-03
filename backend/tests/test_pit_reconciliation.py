from decimal import Decimal

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
from app.services.pit_reconciliation.money import money_or_none
from app.services.pit_reconciliation.repository import PitReconciliationRepository
from app.services.pit_reconciliation.source_service import PitSourceService, _org_code
from app.services.pit_reconciliation.rules.occurrence import calc_vat
from app.services.pit_reconciliation.rules.payment import find_subset_sum
from app.services.pit_reconciliation.rules.bond_interest import bond_interest_details
from app.services.pit_reconciliation.rules.restricted_stock import restricted_stock_details
from app.services.pit_reconciliation.rules.salary_tax import salary_tax_details
from app.services.pit_reconciliation.rules.salary_taxable_income import salary_taxable_income_details


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


def test_artifact_organization_code_removes_excel_numeric_suffix():
    assert _org_code(13201.0) == "13201"
    assert _org_code("13201") == "13201"


def test_subset_sum_handles_large_no_solution_pool_without_combinatorial_search():
    values = [Decimal("1.01")] * 253
    assert find_subset_sum(values, Decimal("9999.99")) is None
    assert find_subset_sum(values, Decimal("3.03")) == [0, 1, 2]


def test_recalculate_keeps_single_workpaper_and_manual_reason():
    db=_db(); company=Company(name="测试公司",code="TEST",operator_name="测试"); db.add(company); db.flush(); period=Period(company_id=company.id,year=2026,month=8,name="2026-08"); db.add(period); db.commit()
    repository=PitReconciliationRepository(db,company.id,period.id); workpaper=repository.get_or_create_workpaper(); engine=PitReconciliationEngine()
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


def test_tax_and_summary_balance_amount_use_closing_balance_not_credit_movement():
    bundle = _bundle()
    bundle.balance.rows[0] = BalanceRow(
        "10001", "21510006", "21510006",
        credit_amount=Decimal("999.00"), closing_balance=Decimal("175.00"),
    )

    result = PitReconciliationEngine().calculate(bundle)

    tax = next(row for row in result["tax_checks"] if row["subject_code"] == "21510006")
    assert tax["current_difference"] == Decimal("5.00")
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


def test_vat_boundaries_match_legacy_threshold():
    assert [calc_vat(Decimal(value)) for value in ("0", "1000", "1009.99", "1010", "1010.01", "10000")] == [
        Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("10.00"), Decimal("10.00"), Decimal("99.01"),
    ]


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
    batch = ReconciliationImportBatch(company_id=company.id, period_id=period.id, import_type="bank_statement", original_name="bank.xlsx", stored_path="bank.xlsx", row_count=2)
    db.add(batch); db.flush()
    db.add_all([
        ReconciliationImportRow(company_id=company.id, batch_id=batch.id, period_id=period.id, import_type="bank_statement", row_number=1, transaction_date="2026-07-10", summary="缴税", amount=Decimal("100"), raw_data={"本方户名": "测试营业部全称", "本方账号": "001.02", "借方金额": "100"}),
        ReconciliationImportRow(company_id=company.id, batch_id=batch.id, period_id=period.id, import_type="bank_statement", row_number=2, transaction_date="2026-07-11", summary="缴税", amount=Decimal("100"), raw_data={"本方户名": "未知机构", "本方账号": "999.99", "借方金额": "100"}),
    ])
    db.commit()

    source = PitSourceService(db, company.id, period.id).load_bank_source()

    assert [row.org_code for row in source.rows] == ["10001", ""]
    assert source.issues == [{
        "issue_type": "unresolved_bank_organization",
        "message": "银行流水未识别本方机构，已排除自动匹配",
        "row_id": source.rows[1].source_row_id,
        "bank_account": "999.99",
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
