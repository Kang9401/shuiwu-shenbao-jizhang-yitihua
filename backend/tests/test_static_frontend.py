from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app


def test_production_app_serves_frontend_and_keeps_api_routes(tmp_path, monkeypatch):
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html><body>TaxWorkbench</body></html>", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist_dir", frontend)
    app = create_app()
    client = TestClient(app)

    root = client.get("/")
    system = client.get("/api/system/info")

    assert root.status_code == 200
    assert "TaxWorkbench" in root.text
    assert system.status_code == 200
    assert system.json()["app_version"] == "0.9.0"

