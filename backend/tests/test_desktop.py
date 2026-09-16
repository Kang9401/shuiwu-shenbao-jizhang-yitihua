from __future__ import annotations

import desktop
import httpx
from fastapi import FastAPI
import pytest


class FakeWindow:
    def __init__(self):
        self.calls = []

    def show(self):
        self.calls.append("show")

    def restore(self):
        self.calls.append("restore")

    def hide(self):
        self.calls.append("hide")

    def destroy(self):
        self.calls.append("destroy")


def test_desktop_server_starts_without_uvicorn_console_logging():
    test_app = FastAPI()

    @test_app.get("/health")
    def health():
        return {"status": "ok"}

    @test_app.get("/")
    def index():
        return {"status": "ok"}

    server, thread, url = desktop._start_server(application=test_app)
    try:
        assert server.config.log_config is None
        assert server.config.access_log is False
        assert httpx.get(f"{url}/health", timeout=2.0).json() == {"status": "ok"}
        assert httpx.get(url, timeout=2.0).status_code == 200
    finally:
        desktop._stop_server(server, thread)

    assert not thread.is_alive()


def test_desktop_api_does_not_expose_native_window(monkeypatch):
    window = FakeWindow()
    monkeypatch.setattr(desktop, "_monitor_window", window)
    manager = desktop.DesktopWindowManager()

    assert vars(manager) == {}
    assert manager.open_rpa_monitor() == {"opened": True}
    assert manager.hide_rpa_monitor() == {"hidden": True}
    assert window.calls == ["show", "restore", "hide"]


def test_main_window_close_destroys_hidden_monitor(monkeypatch):
    window = FakeWindow()
    monkeypatch.setattr(desktop, "_monitor_window", window)
    monkeypatch.setattr(desktop, "_desktop_exiting", False)

    assert desktop._close_monitor_on_main_close() is True
    assert desktop._desktop_exiting is True
    assert window.calls == ["destroy"]
    assert desktop._hide_monitor_on_close(desktop.DesktopWindowManager()) is True


def test_frontend_validation_rejects_missing_asset(tmp_path):
    (tmp_path / "index.html").write_text('<div id="app"></div><script src="assets/app.js"></script>', encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        desktop._validate_frontend_dist(tmp_path)


def test_frontend_validation_accepts_complete_dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("", encoding="utf-8")
    (tmp_path / "index.html").write_text('<div id="app"></div><script src="assets/app.js"></script>', encoding="utf-8")
    assert desktop._validate_frontend_dist(tmp_path).name == "index.html"
