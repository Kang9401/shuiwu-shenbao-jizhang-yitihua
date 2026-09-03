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
from app.api import pit_reconciliations as pit_api


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
        patched = client.patch(f"/api/pit-reconciliations/tax-amount-checks/{row['id']}", params={"period_id": period_id}, json={"business_declared_manual_reason": "工资补发", "calculation_status": "tampered"})
        assert patched.status_code == 200
        assert patched.json()["business_declared_manual_reason"] == "工资补发"
        assert "calculation_status" not in patched.json()
        no_match = client.get("/api/pit-reconciliations/tax-amount-checks", params={"period_id": period_id, "subject_code": "21510008", "only_differences": "true"})
        assert no_match.status_code == 200
        assert no_match.json() == []
    finally:
        app.dependency_overrides.clear()


def test_pit_patch_requires_matching_period():
    client, period_id = _client_with_workpaper()
    try:
        row = client.get("/api/pit-reconciliations/tax-amount-checks", params={"period_id": period_id}).json()[0]
        missing = client.patch(f"/api/pit-reconciliations/tax-amount-checks/{row['id']}", json={"business_declared_manual_reason": "x"})
        assert missing.status_code == 422
        wrong = client.patch(f"/api/pit-reconciliations/tax-amount-checks/{row['id']}", params={"period_id": period_id + 999}, json={"business_declared_manual_reason": "x"})
        assert wrong.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_recalculate_replaces_existing_workpaper_successfully(monkeypatch):
    client, period_id = _client_with_workpaper()
    bundle = PitSourceBundle(
        SourceResult("organization_mapping", "ready", [OrganizationRow("10001", "测试营业部", "测试营业部")]),
        SourceResult("salary", "ready", [SalaryRow("10001", "张三", pit_tax=Decimal("120"))]),
        SourceResult("pit_declaration", "ready", [DeclarationRow("10001", "综合所得", person_name="张三", income_item="正常工资薪金", tax_amount=Decimal("180"))]),
        SourceResult("balance_sheet", "ready", [BalanceRow("10001", "21510006", "21510006", credit_amount=Decimal("180"), closing_balance=Decimal("180"))]),
        SourceResult("broker", "ready_empty"), SourceResult("bond_interest", "ready_empty"), SourceResult("restricted_stock", "ready_empty"), SourceResult("tax_certificate", "ready_empty", required=False), SourceResult("bank_statement", "ready_empty", required=False),
    )
    monkeypatch.setattr(pit_api.PitSourceService, "load_bundle", lambda _self: bundle)
    try:
        before = client.get("/api/pit-reconciliations/overview", params={"period_id": period_id}).json()["workpaper"]
        response = client.post("/api/pit-reconciliations/recalculate", params={"period_id": period_id, "stage": "pre_payment"})
        assert response.status_code == 200
        assert response.json()["workpaper"]["id"] == before["id"]
        assert response.json()["workpaper"]["stage"] == "pre_payment"
        assert response.json()["workpaper"]["calculation_status"] == "success"
    finally:
        app.dependency_overrides.clear()


def test_recalculate_reports_invalid_payroll_headers(monkeypatch):
    client, period_id = _client_with_workpaper()
    bundle = PitSourceBundle(
        SourceResult("organization_mapping", "ready", [OrganizationRow("10001")]),
        SourceResult("salary", "invalid", issues=[{
            "issue_type": "payroll_header_missing",
            "message": "职级工资单缺少附A2必填字段：工资表_累计应纳税所得额；实际工资表表头：['员工编号', '个人所得税']",
        }]),
        SourceResult("pit_declaration", "ready_empty"),
        SourceResult("balance_sheet", "ready_empty"),
        SourceResult("broker", "ready_empty"), SourceResult("bond_interest", "ready_empty"),
        SourceResult("restricted_stock", "ready_empty"),
        SourceResult("tax_certificate", "ready_empty", required=False),
        SourceResult("bank_statement", "ready_empty", required=False),
    )
    monkeypatch.setattr(pit_api.PitSourceService, "load_bundle", lambda _self: bundle)
    try:
        response = client.post("/api/pit-reconciliations/recalculate", params={"period_id": period_id})
        assert response.status_code == 400
        assert "工资表_累计应纳税所得额" in response.json()["detail"]
        assert "实际工资表表头" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_pit_workpaper_export_contains_reference_template_sheets():
    client, period_id = _client_with_workpaper()
    try:
        response = client.get("/api/pit-reconciliations/export", params={"period_id": period_id})
        assert response.status_code == 200
        import io
        import openpyxl
        workbook = openpyxl.load_workbook(io.BytesIO(response.content), read_only=True)
        assert workbook.sheetnames == [
            "汇总税额核对", "自然人电子税务局申报数据", "个税明细税额核对", "其他个税发生额核对",
            "附A1 工资薪金等个税差异", "附A2 当期工资薪金累计应纳税所得额差异明细", "附A3 客户利息个税差异明细", "附A4 限售股个税差异明细",
            "科目余额表", "债券利息明细", "限售股明细", "个税完税凭证", "综合所得个税申报表", "分类所得申报表", "限售股所得申报表", "银行流水", "银行流水个税税额明细",
        ]
    finally:
        app.dependency_overrides.clear()


def test_pit_sheet_data_exposes_reference_columns_and_pagination():
    client, period_id = _client_with_workpaper()
    try:
        response = client.get("/api/pit-reconciliations/sheet-data", params={
            "period_id": period_id, "sheet_name": "个税明细税额核对", "page": 1, "page_size": 2,
        })
        assert response.status_code == 200
        payload = response.json()
        assert payload["columns"] == [
            "机构代码", "营业部名称", "会计科目", "描述", "期初余额", "借方金额", "贷方金额", "期末余额",
            "工资表、支撑平台税额", "申报表税额", "本期差异8", "差异原因8", "累计差异9", "差异原因9",
            "申报表税额（仅正常工资薪金、经纪人、限售股、利息税）", "差异10", "差异原因10",
        ]
        assert payload["total"] == 4
        assert len(payload["rows"]) == 2
        assert payload["rows"][0]["描述"] == "工资薪金个人所得税"
    finally:
        app.dependency_overrides.clear()


def test_failed_recalculation_keeps_previous_detail_rows(monkeypatch):
    client, period_id = _client_with_workpaper()
    original_replace = PitReconciliationRepository.replace

    def fail_after_replace(self, workpaper, result):
        original_replace(self, workpaper, result)
        raise RuntimeError("simulated replacement failure")

    monkeypatch.setattr(pit_api.PitReconciliationRepository, "replace", fail_after_replace)
    try:
        before = client.get("/api/pit-reconciliations/tax-amount-checks", params={"period_id": period_id}).json()
        response = client.post("/api/pit-reconciliations/recalculate", params={"period_id": period_id})
        after = client.get("/api/pit-reconciliations/tax-amount-checks", params={"period_id": period_id}).json()
        assert response.status_code == 400
        assert [(row["subject_code"], row["business_tax_amount"]) for row in after] == [(row["subject_code"], row["business_tax_amount"]) for row in before]
    finally:
        app.dependency_overrides.clear()
