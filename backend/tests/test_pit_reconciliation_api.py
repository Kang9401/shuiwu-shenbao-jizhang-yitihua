from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import app
from app.models.core import Company, Period
from app.services.pit_reconciliation.domain import BalanceRow, DeclarationRow, OrganizationRow, PitSourceBundle, SalaryRow, SourceResult
from app.services.pit_reconciliation.engine import PitReconciliationEngine
from app.services.pit_reconciliation.repository import PitReconciliationRepository


def _client_with_workpaper():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    with session_local() as db:
        company = Company(name="测试公司", code="PIT", operator_name="测试")
        db.add(company); db.flush()
        period = Period(company_id=company.id, year=2026, month=8, name="2026-08")
        db.add(period); db.flush()
        empty = lambda name, required=True: SourceResult(name, "ready_empty", required=required)
        bundle = PitSourceBundle(
            SourceResult("organization_mapping", "ready", [OrganizationRow("10001", "测试营业部", "测试营业部")]),
            SourceResult("salary", "ready", [SalaryRow("10001", "张三", pit_tax=Decimal("100"))]),
            SourceResult("pit_declaration", "ready", [DeclarationRow("10001", "综合所得", person_name="张三", income_item="正常工资薪金", tax_amount=Decimal("180"))]),
            SourceResult("balance_sheet", "ready", [BalanceRow("10001", "21510006", "21510006", credit_amount=Decimal("180"), closing_balance=Decimal("180"))]),
            empty("broker"), empty("bond_interest"), empty("restricted_stock"), empty("tax_certificate", False), empty("bank_statement", False),
        )
        repository = PitReconciliationRepository(db, company.id, period.id)
        repository.replace(repository.get_or_create_workpaper(), PitReconciliationEngine().calculate(bundle))
        db.commit()

    def override_get_db():
        db: Session = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, headers={"X-Company-ID": "1"}), period.id


def test_pit_filters_and_patch_whitelist():
    client, period_id = _client_with_workpaper()
    try:
        response = client.get("/api/pit-reconciliations/tax-amount-checks", params={"period_id": period_id, "org_code": "10001", "subject_code": "21510006", "only_differences": "true"})
        assert response.status_code == 200
        assert len(response.json()) == 1
        row = response.json()[0]
        patched = client.patch(f"/api/pit-reconciliations/tax-amount-checks/{row['id']}", json={"business_declared_manual_reason": "工资补发", "calculation_status": "tampered"})
        assert patched.status_code == 200
        assert patched.json()["business_declared_manual_reason"] == "工资补发"
        assert "calculation_status" not in patched.json()
        no_match = client.get("/api/pit-reconciliations/tax-amount-checks", params={"period_id": period_id, "subject_code": "21510008", "only_differences": "true"})
        assert no_match.status_code == 200
        assert no_match.json() == []
    finally:
        app.dependency_overrides.clear()
