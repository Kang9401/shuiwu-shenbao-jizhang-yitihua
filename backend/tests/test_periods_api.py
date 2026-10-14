from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db.session import Base, get_db
from app.main import app
from app.models.core import Company


def test_periods_auto_create_current_period_when_empty():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        db.add(Company(id=1, name="测试分公司", code="TEST", operator_name="测试人"))
        db.commit()

    def override_get_db():
        db: Session = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app, headers={"X-Company-ID": "1"})
        response = client.get("/api/periods")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"].endswith("月")
    finally:
        app.dependency_overrides.clear()


def test_periods_can_be_created_and_duplicate_is_rejected():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        db.add(Company(id=1, name="测试分公司", code="TEST", operator_name="测试人"))
        db.commit()

    def override_get_db():
        db: Session = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app, headers={"X-Company-ID": "1"})
        created = client.post("/api/periods", json={"year": 2026, "month": 7})
        duplicate = client.post("/api/periods", json={"year": 2026, "month": 7})
        periods = client.get("/api/periods")

        assert created.status_code == 200
        assert created.json()["name"] == "2026年07月"
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "该所属期间已存在"
        assert [(row["year"], row["month"]) for row in periods.json()] == [(2026, 7)]
    finally:
        app.dependency_overrides.clear()
