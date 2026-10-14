import httpx
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.company_context import set_company_id, reset_company_id
from app.core.config import settings
from app.db.session import Base
from app.db.session import get_db
from app.integrations.fmss.client import FmssClient
from app.integrations.fmss.errors import FmssApiError, FmssNotAuthenticated
from app.integrations.fmss.session import FmssSession
from app.models.accounting import OrganizationMapping, ReconciliationImportBatch
from app.models.core import Company, Period, UploadedFile
from app.services.fmss_sources import balance_rows, fetch_balance_source, fetch_security_sources, security_frame
from app.services.formulas import restricted_stock_interest_transform
from app.workflows import get_workflow


def _client():
    session = FmssSession()
    session.connect("fake-memory-only-token")
    return FmssClient(session)


def _preview():
    values = {f"{col}1": label for col, label in zip("ABCDEF", ["会计科目", "描述", "期初金额", "借方发生额", "贷方发生额", "余额"])}
    for index, subject in enumerate(["21510008", "21510009"], 2):
        values.update({f"{col}{index}": value for col, value in zip("ABCDEF", [subject, "应交税费", "1.20", "2.30", "3.40", "2.30"])})
    return {"cells": [{"cellCode": key, "cellVal": value} for key, value in values.items()], "formulaErrors": []}


def test_dsp_pages_are_all_fetched_with_month_and_branch_filter(monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        body = kwargs["json"]
        calls.append(body)
        assert method == "POST" and url.endswith("/dspapi/fin_rstk_tax")
        assert kwargs["timeout"] == 30
        return httpx.Response(200, json={"retcode": "0000", "response_body": [{"branchNo": "3248", "businessId": body["pageNum"]}], "totalrecords": 2, "pageindex": body["pageNum"]}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", request)
    rows = _client().security_tax_rows("tax_sheet", "19020", 2026, 9)
    assert [r["businessId"] for r in rows] == [1, 2]
    assert calls[0]["branchNos"] == ["19020"]
    assert calls[0]["initDate"] == ["20260901", "20260930"]
    assert calls[0]["beginDate"] == "20260901" and calls[0]["endDate"] == "20260930"


@pytest.mark.parametrize("response", [
    {"retcode": "9999", "retmsg": "查询失败"},
    {"retcode": "0000", "response_body": [], "totalrecords": 1, "pageindex": 1},
    {"retcode": "0000", "response_body": [], "totalrecords": 0, "pageindex": 2},
    [],
])
def test_dsp_invalid_or_incomplete_response_stops_without_retry(monkeypatch, response):
    calls = []
    def request(method, url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json=response, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx, "request", request)
    with pytest.raises(FmssApiError):
        _client().security_tax_rows("interest_tax", "19020", 2026, 2)
    assert len(calls) == 1


def test_dsp_401_clears_session_and_stops(monkeypatch):
    client = _client()
    monkeypatch.setattr(httpx, "request", lambda method, url, **kw: httpx.Response(200, json={"code": 401}, request=httpx.Request(method, url)))
    with pytest.raises(FmssNotAuthenticated):
        client.security_tax_rows("interest_tax", "19020", 2026, 9)
    assert not client.session.snapshot().connected


def test_live_field_mapping_preserves_current_tax_calculation():
    interest = security_frame("interest_tax", [{"branchNo": "3248", "clientName": "测试客户", "idKind": "居民身份证", "idNo": "00001234", "stockCode": "001234", "businessBalance": "450.00", "totalTax": "-90", "taxRatio": 20}])
    stock = security_frame("tax_sheet", [{"branchNo": "3248", "clientName": "测试客户", "idKind": "身份证", "idNo": "00001234", "stockAccount": "00123", "stockCode": "001234", "stockName": "测试股票", "businessAmount": 100, "businessPrice": 10, "originalBalance": 100, "sellFare0": 1, "sellFare1": 2, "totalFare": 3, "sellFare2": 4, "taxFare": 178}])
    assert interest.iloc[0]["机构代码"] == "13248"
    assert interest.iloc[0]["兑息扣税"] == 90
    assert stock.iloc[0]["证券账号"] == "00123"
    result = restricted_stock_interest_transform({"restricted_stock_sheet": stock, "interest_tax_sheet": interest})
    assert result["metrics"]["interest_withheld_tax"] == 90
    assert result["metrics"]["restricted_stock_declared_amount"] == 890
    assert result["metrics"]["restricted_stock_withheld_tax"] == 178
    assert result["issues"] == []


def test_balance_parser_maps_four_amounts_and_rejects_formula_errors():
    rows = balance_rows(_preview(), "13248")
    assert len(rows) == 2
    assert rows[0]["公司段"] == "13248"
    assert rows[0]["贷方金额"] == "3.40"
    assert rows[0]["期末余额"] == "2.30"
    broken = _preview()
    broken["cells"] = [c for c in broken["cells"] if c["cellCode"] != "E2"]
    with pytest.raises(FmssApiError):
        balance_rows(broken, "13248")
    with pytest.raises(FmssApiError):
        balance_rows({**_preview(), "formulaErrors": ["#VALUE!"]}, "13248")


@pytest.mark.parametrize("wrong_scope", [False, True])
def test_balance_uses_live_schema_parameters_and_checks_effective_scope(monkeypatch, wrong_scope):
    schema = {"report": {},
              "workbook": {"fmssReportParams": [{"refKey": "segment1", "value": "19000-08"}, {"refKey": "busiDate", "value": "2026-08"}]}}
    calls = []
    def request(method, url, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            data = {"schema": schema}
        else:
            for group in [kwargs["json"]["schema"]["report"]["reportParams"], kwargs["json"]["schema"]["workbook"]["fmssReportParams"]]:
                assert [p["value"] for p in group] == ["13248", "2026-09"]
            data = {**_preview(), "queryTrace": [{"segment1": "19000-08" if wrong_scope else "13248", "period": "2026-09"}]}
        return httpx.Response(200, json={"code": 200, "data": data}, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx, "request", request)
    client = _client()
    if wrong_scope:
        with pytest.raises(FmssApiError, match="机构或期间不匹配"):
            client.balance_preview("13248", 2026, 9)
    else:
        assert len(balance_rows(client.balance_preview("13248", 2026, 9), "13248")) == 2
        client.balance_preview("13248", 2026, 9)
        assert len(calls) == 3  # Template loaded once for the extraction operation.
    assert schema["workbook"]["fmssReportParams"][0]["value"] == "19000-08"


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(name="成都分公司", code="17020", operator_name="测试")
        other = Company(name="其他分公司", code="17021", operator_name="测试")
        db.add_all([company, other]); db.flush()
        token = set_company_id(company.id)
        try:
            period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
            db.add(period); db.flush()
            db.add_all([OrganizationMapping(company_id=company.id, org_code="13248", branch_name="成都"), OrganizationMapping(company_id=other.id, org_code="10001", branch_name="其他")])
            db.commit()
            yield db, company, period
        finally:
            reset_company_id(token)
    engine.dispose()


def test_sources_are_archived_for_existing_workflow_and_empty_month_is_valid(context):
    db, company, period = context
    class Client:
        def security_tax_rows(self, kind, branch, year, month):
            assert (branch, year, month) == ("19020", 2026, 9)
            return []
    result = fetch_security_sources(db, company, period, Client())
    assert [item["row_count"] for item in result["files"]] == [0, 0]
    files = db.query(UploadedFile).all()
    generated = get_workflow("restricted_stock_interest_tax").run(db, 9001, period.id, files)
    assert generated.status == "success"
    assert generated.summary["total_records"] == 0


def test_failed_second_source_does_not_publish_partial_snapshot(context):
    db, company, period = context
    class Client:
        def security_tax_rows(self, kind, *args):
            if kind == "tax_sheet":
                raise FmssApiError("查询失败")
            return []
    with pytest.raises(FmssApiError):
        fetch_security_sources(db, company, period, Client())
    assert db.query(UploadedFile).count() == 0


def test_balance_extraction_only_queries_current_company_and_uses_existing_import(context):
    db, company, period = context
    calls = []
    class Client:
        def balance_preview(self, code, year, month):
            calls.append((code, year, month))
            return _preview()
    batch = fetch_balance_source(db, period, Client())
    assert calls == [("13248", 2026, 9)]
    assert batch.row_count == 2
    assert db.query(ReconciliationImportBatch).count() == 1
    assert pd.read_excel(batch.stored_path, dtype=str).iloc[0]["公司段"] == "13248"


def test_extraction_routes_use_period_context_and_keep_existing_archive_contract(context, monkeypatch):
    from app.api.workflows import router as workflows_router
    from app.api.reconciliation_imports import router as imports_router
    from app.services import fmss_sources
    db, company, period = context
    class Client:
        def security_tax_rows(self, kind, branch, year, month):
            assert (branch, year, month) == ("19020", 2026, 9)
            return []
        def balance_preview(self, org, year, month):
            assert (org, year, month) == ("13248", 2026, 9)
            return _preview()
    monkeypatch.setattr(fmss_sources, "FmssClient", Client)
    app = FastAPI()
    app.include_router(workflows_router)
    app.include_router(imports_router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        headers = {"X-Company-ID": str(company.id)}
        for url in ["/workflows/restricted-stock-interest/fmss-sources", "/reconciliation-imports/balance-sheet/fmss"]:
            assert client.post(url, params={"period_id": 999999}, headers=headers).status_code == 404
        securities = client.post("/workflows/restricted-stock-interest/fmss-sources", params={"period_id": period.id}, headers=headers)
        assert securities.status_code == 200
        assert len(securities.json()["files"]) == 2
        balances = client.post("/reconciliation-imports/balance-sheet/fmss", params={"period_id": period.id}, headers=headers)
        assert balances.status_code == 200
        assert balances.json()["import_type"] == "balance_sheet"
        assert balances.json()["row_count"] == 2
        assert balances.json()["download_url"].endswith("/download")
