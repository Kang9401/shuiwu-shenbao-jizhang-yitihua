from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.core import Company, Period
from app.models.pit_reconciliation import PitReconciliationWorkpaper, PitTaxAmountCheck
from app.services.pit_reconciliation.domain import (BalanceRow, BankRow, BondInterestRow, BrokerRow, DeclarationRow, OrganizationRow, PitSourceBundle, RestrictedStockRow, SalaryRow, SourceResult, TaxCertificateRow)
from app.services.pit_reconciliation.engine import PitReconciliationEngine
from app.services.pit_reconciliation.money import money_or_none
from app.services.pit_reconciliation.repository import PitReconciliationRepository
from app.services.pit_reconciliation.rules.occurrence import calc_vat
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
    assert len(details) == 2
    assert {row["id_number"] for row in details} == {"B", "X"}
    assert all(row["id_number"] != "A" for row in details)
    assert {row["difference"] for row in details} == {Decimal("200"), Decimal("-250")}


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


def test_bank_prefers_tax_summary_pool_without_all_transaction_fallback():
    bundle = _bundle()
    bundle.certificates = SourceResult("tax_certificate", "ready", [TaxCertificateRow("10001", tax_type="个人所得税", amount=Decimal("100"))], required=False)
    bundle.bank = SourceResult("bank_statement", "ready", [BankRow(org_code="10001", summary="服务费", debit_amount=Decimal("100")), BankRow(org_code="10001", summary="缴纳个税", debit_amount=Decimal("100"))], required=False)
    result = PitReconciliationEngine().calculate(bundle)
    assert [row["transaction_summary"] for row in result["bank_matches"]] == ["缴纳个税"]
