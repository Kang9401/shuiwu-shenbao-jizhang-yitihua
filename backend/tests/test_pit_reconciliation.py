from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.core import Company, Period
from app.models.pit_reconciliation import PitReconciliationWorkpaper, PitTaxAmountCheck
from app.services.pit_reconciliation.domain import (BalanceRow, DeclarationRow, OrganizationRow, PitSourceBundle, SalaryRow, SourceResult)
from app.services.pit_reconciliation.engine import PitReconciliationEngine
from app.services.pit_reconciliation.money import money_or_none
from app.services.pit_reconciliation.repository import PitReconciliationRepository


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
