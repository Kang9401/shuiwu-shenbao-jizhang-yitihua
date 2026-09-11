from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import app
from app.models.core import Company, Job, Period


def test_latest_job_is_filtered_by_period_workflow_and_operation():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    db = session_local()
    db.add(Company(id=1, name="测试分公司", code="TEST", operator_name="测试人"))
    period = Period(company_id=1, year=2026, month=6, name="2026年06月", status="open")
    db.add(period)
    db.commit()
    db.refresh(period)
    db.add_all([
        Job(workflow_code="restricted_stock_interest_tax", period_id=period.id, operation="generate", input_file_ids=[], status="success"),
        Job(workflow_code="restricted_stock_interest_tax", period_id=period.id, operation="reconcile", input_file_ids=[], status="needs_review"),
    ])
    db.commit()
    period_id = period.id
    db.close()

    def override_get_db():
        session: Session = session_local()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app, headers={"X-Company-ID": "1"})
        generated = client.get(
            "/api/jobs/latest",
            params={
                "workflow_code": "restricted_stock_interest_tax",
                "period_id": period_id,
                "operation": "generate",
            },
        )
        reconciled = client.get(
            "/api/jobs/latest",
            params={
                "workflow_code": "restricted_stock_interest_tax",
                "period_id": period_id,
                "operation": "reconcile",
            },
        )
        assert generated.status_code == 200
        assert generated.json()["operation"] == "generate"
        assert reconciled.status_code == 200
        assert reconciled.json()["operation"] == "reconcile"
    finally:
        app.dependency_overrides.clear()
