from __future__ import annotations

import httpx
from fastapi import FastAPI

import desktop


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
