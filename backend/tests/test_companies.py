from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.session import Base, get_db
from app.main import app
from app.models.accounting import OrganizationMapping
from app.models.core import Artifact, Job, UploadedFile


def _client(tmp_path: Path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")

    def override_get_db():
        db: Session = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), session_local


def test_company_crud_and_business_data_are_isolated(tmp_path, monkeypatch):
    client, session_local = _client(tmp_path, monkeypatch)
    try:
        first = client.post("/api/companies", json={"name": "第一分公司", "code": "C01", "operator_name": "张三", "notes": ""})
        second = client.post("/api/companies", json={"name": "第二分公司", "code": "C02", "operator_name": "李四", "notes": ""})
        assert first.status_code == second.status_code == 201
        first_id, second_id = first.json()["id"], second.json()["id"]
        first_headers, second_headers = {"X-Company-ID": str(first_id)}, {"X-Company-ID": str(second_id)}

        assert client.get("/api/periods").status_code == 400
        first_period = client.post("/api/periods", headers=first_headers, json={"year": 2026, "month": 7})
        second_period = client.post("/api/periods", headers=second_headers, json={"year": 2026, "month": 7})
        assert first_period.status_code == second_period.status_code == 200
        assert first_period.json()["id"] != second_period.json()["id"]
        assert len(client.get("/api/periods", headers=first_headers).json()) == 1
        assert len(client.get("/api/periods", headers=second_headers).json()) == 1

        for headers, name in ((first_headers, "甲营业部"), (second_headers, "乙营业部")):
            response = client.post(
                "/api/organization-mappings",
                headers=headers,
                json={"branch_name": name, "org_code": "10001", "active": True},
            )
            assert response.status_code == 200

        upload = client.post(
            "/api/files",
            headers=first_headers,
            data={"file_role": "tax_sheet", "period_id": first_period.json()["id"]},
            files={"file": ("input.xlsx", b"content", "application/octet-stream")},
        )
        assert upload.status_code == 200
        assert client.get("/api/files", headers=second_headers).json() == []
        cross_period = client.post(
            "/api/files",
            headers=second_headers,
            data={"file_role": "tax_sheet", "period_id": first_period.json()["id"]},
            files={"file": ("cross.xlsx", b"content", "application/octet-stream")},
        )
        assert cross_period.status_code == 404

        with session_local() as db:
            stored = db.query(UploadedFile).filter(UploadedFile.id == upload.json()["id"]).one()
            assert Path(stored.stored_path).is_file()
            assert str(first_id) in Path(stored.stored_path).parts
            assert db.query(OrganizationMapping).count() == 2
    finally:
        app.dependency_overrides.clear()


def test_cross_company_artifact_download_returns_not_found(tmp_path, monkeypatch):
    client, session_local = _client(tmp_path, monkeypatch)
    try:
        first = client.post("/api/companies", json={"name": "第一分公司", "code": "C01", "operator_name": "张三"}).json()
        second = client.post("/api/companies", json={"name": "第二分公司", "code": "C02", "operator_name": "李四"}).json()
        file_path = tmp_path / "result.xlsx"
        file_path.write_bytes(b"result")
        with session_local() as db:
            job = Job(company_id=first["id"], workflow_code="broker_tax", input_file_ids=[], status="success")
            db.add(job)
            db.commit()
            artifact = Artifact(company_id=first["id"], job_id=job.id, artifact_type="declaration", file_name=file_path.name, stored_path=str(file_path))
            db.add(artifact)
            db.commit()
            artifact_id = artifact.id

        assert client.get(f"/api/artifacts/{artifact_id}/download", headers={"X-Company-ID": str(second["id"])}).status_code == 404
        assert client.get(f"/api/artifacts/{artifact_id}/download", headers={"X-Company-ID": str(first["id"])}).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_last_active_company_cannot_be_disabled(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    try:
        company = client.post("/api/companies", json={"name": "唯一分公司", "code": "ONLY", "operator_name": "使用人"}).json()
        response = client.patch(f"/api/companies/{company['id']}/status", json={"active": False})
        assert response.status_code == 409
    finally:
        app.dependency_overrides.clear()
