from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.company_context import set_company_id, reset_company_id
from app.db.session import Base, get_db
from app.main import app
from app.models.accounting import OrganizationMapping, ReconciliationImportBatch, ReconciliationImportRow
from app.models.core import Company, Period
from app.models.pit_reconciliation import PitReconciliationOrgSummary, PitReconciliationWorkpaper
from app.services.pit_reconciliation.source_service import PitSourceService, declaration_snapshot_rows


@pytest.fixture
def context():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(name="成都分公司", code="17020", operator_name="测试")
        db.add(company); db.flush()
        token = set_company_id(company.id)
        try:
            period = Period(company_id=company.id, year=2026, month=7, name="2026-07")
            db.add(period); db.flush()
            db.add(OrganizationMapping(company_id=company.id, org_code="17020", branch_name="成都分公司", bank_account="6222"))
            db.commit()
            app.dependency_overrides[get_db] = lambda: db
            with TestClient(app, headers={"X-Company-ID": str(company.id)}) as client:
                yield db, SimpleNamespace(id=company.id), SimpleNamespace(id=period.id), client
        finally:
            app.dependency_overrides.clear()
            reset_company_id(token)
    engine.dispose()


def _declaration(db, company, period, amount):
    batch = ReconciliationImportBatch(company_id=company.id, period_id=period.id, import_type="pit_declaration",
                                      original_name="申报.xlsx", stored_path="", row_count=1)
    db.add(batch); db.flush()
    db.add(ReconciliationImportRow(company_id=company.id, period_id=period.id, batch_id=batch.id,
                                  import_type="pit_declaration", row_number=1, organization_code="17020",
                                  declaration_type="综合所得", tax_amount=Decimal(amount), income_amount=Decimal("500"),
                                  raw_data={"sheet_name": "综合所得", "org_code": "17020", "纳税人姓名": "张三",
                                            "所得项目": "正常工资薪金", "应补退税额": amount, "收入": "500"}))
    db.commit()
    return batch.id


def _payments(db, company, period, amount):
    for kind in ("tax_certificate", "bank_statement"):
        batch = ReconciliationImportBatch(company_id=company.id, period_id=period.id, import_type=kind,
                                          original_name=kind, stored_path="", row_count=1)
        db.add(batch); db.flush()
        raw = ({"taxpayer_name": "成都分公司", "tax_type": "个人所得税", "amount": amount}
               if kind == "tax_certificate" else {"本方户名": "成都分公司", "本方账号": "6222", "借方金额": amount})
        db.add(ReconciliationImportRow(company_id=company.id, period_id=period.id, batch_id=batch.id,
                                      import_type=kind, row_number=1, organization_code="17020", counterparty="成都分公司",
                                      amount=Decimal(amount), summary="个税扣款", raw_data=raw))
    db.commit()


def _recalculate(client, period, stage):
    response = client.post("/api/pit-reconciliations/recalculate", params={"period_id": period.id, "stage": stage})
    assert response.status_code == 200, response.text
    return response.json()["workpaper"]


def test_post_recalculates_with_unmatched_bank_rows(context):
    db, company, period, client = context
    _declaration(db, company, period, "100")
    _recalculate(client, period, "pre_payment")
    _payments(db, company, period, "100")
    batch = db.query(ReconciliationImportBatch).filter_by(import_type="bank_statement").one()
    batch.row_count = 3
    for number in (2, 3):
        db.add(ReconciliationImportRow(
            company_id=company.id, period_id=period.id, batch_id=batch.id,
            import_type="bank_statement", row_number=number, amount=Decimal("50"),
            summary="个税扣款", raw_data={"本方户名": "未知机构", "本方账号": "9999", "借方金额": "50"},
        ))
    db.commit()
    response = client.get("/api/pit-reconciliations/readiness", params={"period_id": period.id, "stage": "post_payment"})
    assert response.status_code == 200
    bank = next(item for item in response.json() if item["source_type"] == "bank_statement")
    assert bank["row_count"] == 3
    assert bank["source_status"] == "ready"
    assert len(bank["issues_json"]) == 1
    assert bank["issues_json"][0]["transaction_count"] == 2
    post = _recalculate(client, period, "post_payment")
    assert post["calculation_status"] == "success"
    assert post["data_status"] == "ready"
    summary = db.query(PitReconciliationOrgSummary).filter_by(workpaper_id=post["id"]).one()
    assert summary.bank_tax_amount == Decimal("100")


def test_post_keeps_pre_declarations_when_new_imports_change(context, monkeypatch):
    db, company, period, client = context
    old_batch = _declaration(db, company, period, "100")
    pre = _recalculate(client, period, "pre_payment")
    old_rows = pre["source_snapshot_json"]["pit_declaration"]["rows"]
    _declaration(db, company, period, "200")
    _payments(db, company, period, "90")
    pre_row = db.get(PitReconciliationWorkpaper, pre["id"])
    pre_row.workflow_status = "reviewed"
    db.commit()
    # POST must not even load current declarations/payroll/business sources.
    original = PitSourceService.load_bundle
    monkeypatch.setattr(PitSourceService, "load_bundle", lambda _: pytest.fail("POST read latest PRE sources"))
    post = _recalculate(client, period, "post_payment")
    summary = db.query(PitReconciliationOrgSummary).filter_by(workpaper_id=post["id"]).one()
    assert summary.declared_tax_amount == Decimal("100")
    assert summary.certificate_tax_amount == Decimal("90")
    assert summary.bank_tax_amount == Decimal("90")
    assert summary.difference_4 == Decimal("10")
    assert post["source_snapshot_json"]["pit_declaration"]["source_id"] == old_batch
    assert post["source_snapshot_json"]["pit_declaration"]["rows"] == old_rows
    assert post["source_snapshot_json"]["pre_payment_snapshot"] == {"workpaper_id": pre["id"], "draft_revision": pre["draft_revision"]}
    assert db.get(PitReconciliationWorkpaper, pre["id"]).workflow_status == "reviewed"
    reread = client.get("/api/pit-reconciliations/overview", params={"period_id": period.id, "stage": "post_payment"})
    assert reread.json()["workpaper"]["source_snapshot_json"]["pit_declaration"]["rows"] == old_rows

    # Only an explicit PRE recalculation can update the declaration baseline.
    monkeypatch.setattr(PitSourceService, "load_bundle", original)
    pre_row = db.get(PitReconciliationWorkpaper, pre["id"])
    pre_row.workflow_status = "returned"
    db.commit()
    updated_pre = _recalculate(client, period, "pre_payment")
    assert updated_pre["draft_revision"] > pre["draft_revision"]
    updated_post = _recalculate(client, period, "post_payment")
    assert db.query(PitReconciliationOrgSummary).filter_by(workpaper_id=updated_post["id"]).one().declared_tax_amount == Decimal("200")


def test_frozen_rows_survive_source_batch_removal_and_show_same_export(context):
    db, company, period, client = context
    batch_id = _declaration(db, company, period, "100")
    pre = _recalculate(client, period, "pre_payment")
    db.query(ReconciliationImportRow).filter_by(batch_id=batch_id).delete()
    db.query(ReconciliationImportBatch).filter_by(id=batch_id).delete()
    db.commit()
    _declaration(db, company, period, "999")
    rows = declaration_snapshot_rows(db, db.get(PitReconciliationWorkpaper, pre["id"]))
    assert rows[0]["应补退税额"] == "100"
    displayed = client.get("/api/pit-reconciliations/sheet-data", params={"period_id": period.id, "stage": "pre_payment", "sheet_name": "综合所得申报表"})
    assert displayed.status_code == 200
    assert '"100"' in displayed.text
    assert '"999"' not in displayed.text
    _payments(db, company, period, "100")
    post = _recalculate(client, period, "post_payment")
    assert post["source_snapshot_json"]["pit_declaration"]["rows"] == rows


def test_legacy_pre_uses_recorded_batch_and_never_latest(context):
    db, company, period, client = context
    batch_id = _declaration(db, company, period, "100")
    pre = _recalculate(client, period, "pre_payment")
    paper = db.get(PitReconciliationWorkpaper, pre["id"])
    snapshot = dict(paper.source_snapshot_json)
    snapshot["pit_declaration"] = {k: v for k, v in snapshot["pit_declaration"].items() if k != "rows"}
    paper.source_snapshot_json = snapshot
    db.commit()
    _declaration(db, company, period, "999")
    assert declaration_snapshot_rows(db, paper)[0]["应补退税额"] == "100"
    db.query(ReconciliationImportRow).filter_by(batch_id=batch_id).delete()
    db.query(ReconciliationImportBatch).filter_by(id=batch_id).delete()
    db.commit()
    with pytest.raises(ValueError, match="不能使用新导入数据替代"):
        declaration_snapshot_rows(db, paper)


def test_post_requires_same_company_pre_workpaper(context):
    db, company, period, client = context
    _payments(db, company, period, "100")
    response = client.post("/api/pit-reconciliations/recalculate", params={"period_id": period.id, "stage": "post_payment"})
    assert response.status_code == 400
    assert "先完成缴款前底稿重算" in response.json()["detail"]


def test_new_declarations_do_not_invalidate_post_snapshot(context):
    from app.api.reconciliation_imports import _mark_pit_workpapers_stale

    db, company, period, client = context
    _declaration(db, company, period, "100")
    pre = _recalculate(client, period, "pre_payment")
    _payments(db, company, period, "100")
    post = _recalculate(client, period, "post_payment")
    _declaration(db, company, period, "999")
    _mark_pit_workpapers_stale(db, period.id, "来源已更新", "pit_declaration")
    db.commit()
    assert db.get(PitReconciliationWorkpaper, pre["id"]).calculation_status == "stale"
    assert db.get(PitReconciliationWorkpaper, post["id"]).calculation_status == "success"
    response = client.get("/api/pit-reconciliations/sheet-data", params={
        "period_id": period.id, "stage": "post_payment", "sheet_name": "缴税核对",
    })
    assert response.status_code == 200
    assert response.json()["rows"][0]["declared_tax_amount"] == 100
