from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import app
from app.models.core import Company, Period
from app.models.pit_reconciliation import PitReconciliationOrgSummary, PitReconciliationWorkpaper, PitTaxAmountCheck


def _client_with_stages():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    with session_local() as db:
        company = Company(name="阶段测试公司", code="PIT-STAGE", operator_name="测试")
        db.add(company)
        db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add(period)
        db.flush()
        pre = PitReconciliationWorkpaper(
            company_id=company.id, period_id=period.id, tax_type="pit", stage="pre_payment",
            workflow_status="pending_submission", data_status="ready", calculation_status="success", rule_version="test",
        )
        post = PitReconciliationWorkpaper(
            company_id=company.id, period_id=period.id, tax_type="pit", stage="post_payment",
            workflow_status="pending_submission", data_status="ready", calculation_status="success", rule_version="test",
        )
        db.add_all([pre, post])
        db.flush()
        db.add_all([
            PitTaxAmountCheck(workpaper_id=pre.id, company_id=company.id, period_id=period.id, org_code="10001", org_name="机构", subject_code="21510006", subject_name="个税", check_status="ok"),
            PitTaxAmountCheck(workpaper_id=post.id, company_id=company.id, period_id=period.id, org_code="10001", org_name="机构", subject_code="21510006", subject_name="个税", check_status="ok"),
        ])
        db.add(PitReconciliationOrgSummary(workpaper_id=post.id, company_id=company.id, period_id=period.id, org_code="10001", org_name="机构", org_full_name="机构全称", check_status="ok"))
        db.commit()
        period_id = period.id

    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, headers={"X-Company-ID": "1"}), session_local, period_id


def test_manual_reasons_are_isolated_by_stage_and_returned_becomes_pending_submission():
    client, session_local, period_id = _client_with_stages()
    try:
        pre_row = client.get("/api/pit-reconciliations/tax-amount-checks", params={"period_id": period_id, "stage": "pre_payment"}).json()[0]
        post_row = client.get("/api/pit-reconciliations/tax-amount-checks", params={"period_id": period_id, "stage": "post_payment"}).json()[0]
        with session_local() as db:
            db.query(PitReconciliationWorkpaper).filter_by(period_id=period_id, stage="pre_payment").one().workflow_status = "returned"
            db.commit()
        response = client.patch(
            f"/api/pit-reconciliations/tax-amount-checks/{pre_row['id']}",
            params={"period_id": period_id, "stage": "pre_payment"},
            json={"current_manual_reason": "补充说明"},
        )
        assert response.status_code == 200
        assert client.get("/api/pit-reconciliations/tax-amount-checks", params={"period_id": period_id, "stage": "post_payment"}).json()[0]["current_manual_reason"] is None
        with session_local() as db:
            assert db.query(PitReconciliationWorkpaper).filter_by(period_id=period_id, stage="pre_payment").one().workflow_status == "pending_submission"
            assert db.query(PitTaxAmountCheck).filter_by(id=post_row["id"]).one().current_manual_reason is None
    finally:
        app.dependency_overrides.clear()


def test_submitted_and_reviewed_workpapers_reject_patch_and_recalculate():
    client, session_local, period_id = _client_with_stages()
    try:
        row = client.get("/api/pit-reconciliations/tax-amount-checks", params={"period_id": period_id, "stage": "pre_payment"}).json()[0]
        for status in ("submitted", "reviewed"):
            with session_local() as db:
                db.query(PitReconciliationWorkpaper).filter_by(period_id=period_id, stage="pre_payment").one().workflow_status = status
                db.commit()
            patched = client.patch(
                f"/api/pit-reconciliations/tax-amount-checks/{row['id']}",
                params={"period_id": period_id, "stage": "pre_payment"}, json={"current_manual_reason": "不应保存"},
            )
            recalculated = client.post("/api/pit-reconciliations/recalculate", params={"period_id": period_id, "stage": "pre_payment"})
            assert patched.status_code == 409
            assert recalculated.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_post_payment_export_has_only_post_sheets_and_preserves_duplicate_visible_reason_header():
    client, _, period_id = _client_with_stages()
    try:
        response = client.get("/api/pit-reconciliations/export", params={"period_id": period_id, "stage": "post_payment"})
        assert response.status_code == 200
        import io
        import openpyxl
        from app.services.pit_reconciliation.exporter import POST_PAYMENT_SHEET_NAMES

        workbook = openpyxl.load_workbook(io.BytesIO(response.content), read_only=True)
        assert workbook.sheetnames == list(POST_PAYMENT_SHEET_NAMES)
        header = list(next(workbook["缴税核对"].values))
        assert header == ["机构代码", "营业部全称", "申报表", "完税证明", "申报表与完税证明差异金额11", "差异原因11", "银行流水个税", "完税证明与银行流水差异金额11", "差异原因11"]
    finally:
        app.dependency_overrides.clear()
