import io

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import app


def _client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db: Session = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _excel_bytes(rows: list[dict]) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    return buffer.getvalue()


def test_organization_mapping_crud_and_import():
    client = _client()
    try:
        created = client.post(
            "/api/organization-mappings",
            json={
                "branch_name": "测试营业部",
                "org_code": "12345",
                "taxpayer_id": " 9132 abcd ",
                "active": True,
                "rpa_enabled": True,
                "rpa_org_name": "测试证券营业部",
                "parent_branch": "测试分公司",
            },
        )
        assert created.status_code == 200
        mapping_id = created.json()["id"]

        updated = client.put(
            f"/api/organization-mappings/{mapping_id}",
            json={
                "branch_name": "测试营业部",
                "org_code": "54321",
                "taxpayer_id": "9132ABCD",
                "active": False,
                "rpa_enabled": True,
                "rpa_org_name": "测试证券营业部",
                "parent_branch": "测试分公司",
            },
        )
        assert updated.status_code == 200
        assert updated.json()["org_code"] == "54321"
        assert updated.json()["taxpayer_id"] == "9132ABCD"
        assert updated.json()["active"] is False
        assert updated.json()["rpa_enabled"] is True
        assert updated.json()["rpa_org_name"] == "测试证券营业部"
        assert updated.json()["parent_branch"] == "测试分公司"

        imported = client.post(
            "/api/organization-mappings/import",
            files={
                "file": (
                    "机构映射.xlsx",
                    _excel_bytes([{"营业部名称": "测试营业部", "机构代码": "10001"}]),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert imported.status_code == 200
        assert imported.json() == {"updated": 1}

        listed = client.get("/api/organization-mappings")
        assert listed.status_code == 200
        assert listed.json()[0]["org_code"] == "10001"
        assert listed.json()[0]["active"] is True
        assert listed.json()[0]["rpa_enabled"] is True
        assert listed.json()[0]["taxpayer_id"] == "9132ABCD"

        exported = client.get("/api/organization-mappings/export")
        frame = pd.read_excel(io.BytesIO(exported.content), dtype=str).fillna("")
        assert frame.loc[0, "是否启用RPA"] == "是"
        assert frame.loc[0, "营业部全称"] == "测试证券营业部"
        assert frame.loc[0, "所属分公司"] == "测试分公司"
        assert frame.loc[0, "机构纳税人识别号"] == "9132ABCD"
    finally:
        app.dependency_overrides.clear()


def test_taxpayer_id_must_be_unique_when_present():
    client = _client()
    try:
        first = client.post(
            "/api/organization-mappings",
            json={"branch_name": "第一营业部", "org_code": "10001", "taxpayer_id": "tax-001"},
        )
        second = client.post(
            "/api/organization-mappings",
            json={"branch_name": "第二营业部", "org_code": "10002", "taxpayer_id": " TAX-001 "},
        )
        assert first.status_code == 200
        assert second.status_code == 409
        assert "纳税人识别号" in second.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_org_code_is_unique_and_last_import_row_wins():
    client = _client()
    try:
        imported = client.post(
            "/api/organization-mappings/import",
            files={"file": ("机构名称维护表.xlsx", _excel_bytes([
                {"营业部名称": "旧名称", "机构代码": "10001"},
                {"营业部名称": "新名称", "机构代码": "10001"},
            ]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert imported.status_code == 200
        assert imported.json() == {"updated": 2}
        assert [(item["org_code"], item["branch_name"]) for item in client.get("/api/organization-mappings").json()] == [("10001", "新名称")]

        duplicate = client.post(
            "/api/organization-mappings",
            json={"branch_name": "另一营业部", "org_code": "10001"},
        )
        assert duplicate.status_code == 409
        assert "机构代码" in duplicate.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_rpa_mapping_requires_full_name_and_parent_branch():
    client = _client()
    try:
        response = client.post(
            "/api/organization-mappings",
            json={"branch_name": "测试营业部", "org_code": "12345", "active": True, "rpa_enabled": True},
        )
        assert response.status_code == 400
        assert "营业部全称" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_new_excel_columns_enable_rpa_mapping():
    client = _client()
    try:
        imported = client.post(
            "/api/organization-mappings/import",
            files={
                "file": (
                    "机构映射.xlsx",
                    _excel_bytes([{
                        "营业部名称": "测试营业部",
                        "机构代码": "10001",
                        "是否启用RPA": "是",
                        "营业部全称": "测试证券营业部",
                        "所属分公司": "测试分公司",
                    }]),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert imported.status_code == 200
        mapping = client.get("/api/organization-mappings").json()[0]
        assert mapping["rpa_enabled"] is True
        assert mapping["rpa_org_name"] == "测试证券营业部"
        assert mapping["parent_branch"] == "测试分公司"
    finally:
        app.dependency_overrides.clear()


def test_intern_template_contains_required_sheets_and_active_mapping():
    client = _client()
    try:
        client.post(
            "/api/organization-mappings",
            json={"branch_name": "模板营业部", "org_code": "12345", "active": True},
        )
        response = client.get("/api/workflows/intern-tax/template")
        assert response.status_code == 200

        workbook = pd.ExcelFile(io.BytesIO(response.content))
        assert workbook.sheet_names == ["实习生导入", "填写说明", "机构映射"]
        template = pd.read_excel(io.BytesIO(response.content), sheet_name="实习生导入")
        mapping = pd.read_excel(io.BytesIO(response.content), sheet_name="机构映射", dtype=str)
        assert {"机构代码", "营业部名称", "*姓名", "*证件号码", "发放补贴数（元）"}.issubset(template.columns)
        assert mapping.to_dict("records") == [{"机构代码": "12345", "营业部名称": "模板营业部"}]
    finally:
        app.dependency_overrides.clear()
