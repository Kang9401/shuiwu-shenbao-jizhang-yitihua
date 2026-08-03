from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import rpa as rpa_api
from app.rpa.state_store import StateStore


class StubService:
    def get_status(self):
        return {"chrome": {"status": "ready"}, "can_start": True}

    def upload_org_excel(self, filename, content):
        if not filename.endswith(".xlsx"):
            raise ValueError("机构信息表只支持 .xlsx")
        return {"name": filename, "count": 1}

    def read_logs(self, offset):
        return {"text": "日志", "next_offset": offset + 6, "finished": True}

    def resolve_output(self, name):
        raise ValueError("输出文件不存在")


def client(monkeypatch):
    monkeypatch.setattr(rpa_api, "rpa_service", StubService())
    app = FastAPI()
    app.include_router(rpa_api.router, prefix="/api")
    app.dependency_overrides[rpa_api.activate_rpa_company] = lambda: None
    return TestClient(app)


def test_status_and_log_offset(monkeypatch):
    test_client = client(monkeypatch)
    assert test_client.get("/api/rpa/status").json()["can_start"] is True
    assert test_client.get("/api/rpa/logs", params={"offset": 10}).json()["next_offset"] == 16


def test_org_excel_validation(monkeypatch):
    test_client = client(monkeypatch)
    valid = test_client.post("/api/rpa/org-excel", files={"file": ("机构.xlsx", b"data")})
    invalid = test_client.post("/api/rpa/org-excel", files={"file": ("机构.xls", b"data")})
    assert valid.status_code == 200
    assert invalid.status_code == 400


def test_missing_output_is_rejected(monkeypatch):
    assert client(monkeypatch).get("/api/rpa/files/download", params={"name": "../secret.txt"}).status_code == 400


def test_state_store_recovers_interrupted_run(tmp_path):
    store = StateStore(tmp_path / "state.json")
    state = store.read()
    state["current_run"].update(status="running", task_key="import", month="2026-06", current_org_code="11818")
    store.write(state)

    store.recover_interrupted()

    recovered = store.read()
    assert recovered["current_run"]["status"] == "failed"
    assert recovered["last_failure"] == {"task_key": "import", "org_code": "11818", "month": "2026-06"}
