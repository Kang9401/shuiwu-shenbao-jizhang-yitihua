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
            json={"branch_name": "测试营业部", "org_code": "12345", "active": True},
        )
        assert created.status_code == 200
        mapping_id = created.json()["id"]

        updated = client.put(
            f"/api/organization-mappings/{mapping_id}",
            json={"branch_name": "测试营业部", "org_code": "54321", "active": False},
        )
        assert updated.status_code == 200
        assert updated.json()["org_code"] == "54321"
        assert updated.json()["active"] is False

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
