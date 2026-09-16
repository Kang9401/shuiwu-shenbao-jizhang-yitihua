from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.core import Company, Period
from app.models.pit_reconciliation import (
    PitOccurrenceCheck,
    PitReconciliationDifferenceDetail,
    PitReconciliationOrgSummary,
    PitReconciliationWorkpaper,
    PitTaxAmountCheck,
)
from app.services.pit_reconciliation.reason_aggregation import AUTO_PREFIX, MAX_REASON_LENGTH, _render, aggregate_reasons


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _workpaper(db):
    company = Company(name="测试公司", code="PIT", operator_name="测试")
    db.add(company); db.flush()
    period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
    db.add(period); db.flush()
    workpaper = PitReconciliationWorkpaper(company_id=company.id, period_id=period.id, stage="pre_payment", workflow_status="returned", calculation_status="success")
    db.add(workpaper); db.flush()
    for org_code in ("10001", "10002"):
        db.add(PitReconciliationOrgSummary(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, org_code=org_code, org_name=f"机构{org_code}", check_status="ok"))
    db.add_all([
        PitTaxAmountCheck(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, org_code="10001", org_name="机构1", subject_code="21510006", subject_name="工资薪金", current_manual_reason="本期差异", cumulative_manual_reason="累计差异", check_status="ok"),
        PitTaxAmountCheck(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, org_code="10001", org_name="机构1", subject_code="21510008", subject_name="债券利息", check_status="ok"),
        PitTaxAmountCheck(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, org_code="10001", org_name="机构1", subject_code="21510009", subject_name="限售股", check_status="ok"),
        PitTaxAmountCheck(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, org_code="10002", org_name="机构2", subject_code="21510006", subject_name="工资薪金", check_status="ok"),
        PitOccurrenceCheck(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, org_code="10001", org_name="机构1", subject_code="45019006", subject_name="证券经纪人", income_type="证券经纪人佣金收入", broker_occurrence_manual_reason="经纪人差异", declared_income_manual_reason="申报收入差异", check_status="ok"),
    ])
    db.add_all([
        PitReconciliationDifferenceDetail(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, detail_type="salary_tax", org_code="10001", org_name="机构1", identity_key="A", person_or_customer_name="张三", manual_reason="工资资料待补"),
        PitReconciliationDifferenceDetail(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, detail_type="salary_tax", org_code="10001", org_name="机构1", identity_key="B", person_or_customer_name="李四", manual_reason="工资资料待补"),
        PitReconciliationDifferenceDetail(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, detail_type="bond_interest_tax", org_code="10001", org_name="机构1", identity_key="C", person_or_customer_name="王五", manual_reason="利息凭证待补"),
        PitReconciliationDifferenceDetail(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, detail_type="restricted_stock_tax", org_code="10001", org_name="机构1", identity_key="D", person_or_customer_name="赵六", manual_reason="限售股资料待补"),
        PitReconciliationDifferenceDetail(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, detail_type="salary_taxable_income", org_code="10001", org_name="机构1", identity_key="E", person_or_customer_name="钱七", manual_reason="累计口径待核"),
        PitReconciliationDifferenceDetail(workpaper_id=workpaper.id, company_id=company.id, period_id=period.id, detail_type="salary_tax", org_code="10002", org_name="机构2", identity_key="F", person_or_customer_name="孙八", manual_reason="机构二原因"),
    ])
    db.commit()
    return workpaper


def test_aggregate_reasons_maps_details_and_keeps_organizations_isolated():
    db = _db(); workpaper = _workpaper(db)

    result = aggregate_reasons(db, workpaper, "fill_empty")

    checks = {(row.org_code, row.subject_code): row for row in db.query(PitTaxAmountCheck).all()}
    summaries = {row.org_code: row for row in db.query(PitReconciliationOrgSummary).all()}
    assert result.changed is True
    assert checks[("10001", "21510006")].business_declared_manual_reason.count("工资资料待补") == 1
    assert "利息凭证待补" in checks[("10001", "21510008")].business_declared_manual_reason
    assert "限售股资料待补" in checks[("10001", "21510009")].business_declared_manual_reason
    assert "累计口径待核" in summaries["10001"].difference_3_manual_reason
    assert "本期差异" in summaries["10001"].difference_1_manual_reason
    assert "工资资料待补" in summaries["10001"].difference_2_manual_reason
    assert "经纪人差异" in summaries["10001"].difference_6_manual_reason
    assert "申报收入差异" in summaries["10001"].difference_7_manual_reason
    assert "机构二原因" in checks[("10002", "21510006")].business_declared_manual_reason
    assert "机构二原因" not in checks[("10001", "21510006")].business_declared_manual_reason


def test_aggregate_reasons_protects_manual_values_and_refreshes_generated_values():
    db = _db(); workpaper = _workpaper(db)
    check = db.query(PitTaxAmountCheck).filter_by(org_code="10001", subject_code="21510006").one()
    check.business_declared_manual_reason = "手工保留"
    db.commit()

    fill = aggregate_reasons(db, workpaper, "fill_empty")
    assert check.business_declared_manual_reason == "手工保留"
    assert fill.skipped_manual_fields >= 1
    check.business_declared_manual_reason = f"{AUTO_PREFIX}\n1、旧内容"
    refreshed = aggregate_reasons(db, workpaper, "refresh_generated")
    assert refreshed.changed is True
    assert "工资资料待补" in check.business_declared_manual_reason


def test_aggregation_render_never_silently_truncates():
    rendered = _render([f"人员{index}：{'X' * 1000}{index}" for index in range(8)])
    assert rendered is not None
    assert len(rendered) <= MAX_REASON_LENGTH
    assert "另有" in rendered
