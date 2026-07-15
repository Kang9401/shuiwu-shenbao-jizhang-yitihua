from __future__ import annotations

import ctypes
import json
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


os.environ.setdefault("APP_RUNTIME_MODE", "desktop")

import httpx
import uvicorn

from app.core.config import settings
from app.core.version import APP_SLUG, PRODUCT_NAME
from app.main import app


_mutex_handle = None


def _message(title: str, content: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, content, title, 0x10)
    else:
        print(f"{title}: {content}", file=sys.stderr)


def _acquire_single_instance() -> bool:
    global _mutex_handle
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.windll.kernel32
    _mutex_handle = kernel32.CreateMutexW(None, False, f"Local\\{APP_SLUG}-Desktop")
    return bool(_mutex_handle) and kernel32.GetLastError() != 183


def _find_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _prepare_runtime() -> None:
    for path in (settings.storage_root, settings.upload_dir, settings.artifact_dir, settings.log_dir, settings.temp_dir):
        path.mkdir(parents=True, exist_ok=True)
    probe = settings.storage_root / ".write-test"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)


def _create_server(port: int, application=app) -> uvicorn.Server:
    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None,
    )
    return uvicorn.Server(config)


def _wait_for_server(url: str, timeout: float = 20.0, thread: threading.Thread | None = None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if thread is not None and not thread.is_alive():
            raise RuntimeError("本地服务启动失败")
        try:
            response = httpx.get(f"{url}/health", timeout=1.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("本地服务启动超时")


def _start_server(port: int | None = None, application=app) -> tuple[uvicorn.Server, threading.Thread, str]:
    selected_port = port if port is not None else _find_port()
    url = f"http://127.0.0.1:{selected_port}"
    server = _create_server(selected_port, application)
    thread = threading.Thread(target=server.run, name="taxworkbench-api", daemon=True)
    thread.start()
    try:
        _wait_for_server(url, thread=thread)
    except Exception:
        _stop_server(server, thread)
        raise
    return server, thread, url


def _stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=5)


def _verify_frontend(url: str) -> None:
    response = httpx.get(url, timeout=5.0, follow_redirects=True)
    response.raise_for_status()
    if '<div id="app"></div>' not in response.text:
        raise RuntimeError("前端首页内容校验失败")


def _verify_webview_backend(url: str, timeout: float = 20.0) -> None:
    import webview

    loaded = threading.Event()
    window = webview.create_window(
        "TaxWorkbench Self Test",
        url,
        hidden=True,
    )
    if window is None:
        raise RuntimeError("WebView 窗口创建失败")

    def close_after_load() -> None:
        loaded.set()
        window.destroy()

    window.events.loaded += close_after_load
    timer = threading.Timer(timeout, window.destroy)
    timer.daemon = True
    timer.start()
    try:
        webview.start(debug=False, private_mode=True)
    finally:
        timer.cancel()
    if not loaded.is_set():
        raise RuntimeError("WebView2 页面加载超时")


def main() -> int:
    if "--self-test" in sys.argv:
        server = None
        thread = None
        try:
            _prepare_runtime()
            from app.db.init_db import init_db
            import webview
            import webview.platforms.winforms

            init_db()
            index_file = settings.frontend_dist_dir / "index.html"
            if not index_file.is_file():
                raise FileNotFoundError(f"前端资源不存在：{index_file}")
            server, thread, url = _start_server()
            _verify_frontend(url)
            _verify_webview_backend(url)
            print(json.dumps({
                "status": "ok",
                "data_root": str(settings.storage_root),
                "frontend": str(index_file),
                "server": url,
                "desktop_backend": "webview.platforms.winforms",
            }, ensure_ascii=False))
            return 0
        except Exception as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1
        finally:
            if server is not None and thread is not None:
                _stop_server(server, thread)
    if not _acquire_single_instance():
        _message(PRODUCT_NAME, "程序已经在运行，请勿重复打开。")
        return 0
    try:
        _prepare_runtime()
        server, thread, url = _start_server()
        try:
            import webview

            webview.create_window(
                PRODUCT_NAME,
                url,
                width=1440,
                height=900,
                min_size=(1080, 680),
                text_select=True,
            )
            webview.start(
                debug=False,
                private_mode=False,
                storage_path=str(settings.storage_root / "webview"),
            )
        except ImportError:
            webbrowser.open(url)
            while thread.is_alive():
                time.sleep(0.5)
        finally:
            _stop_server(server, thread)
        return 0
    except Exception as exc:
        logging.getLogger(__name__).exception("Desktop startup failed")
        _message(PRODUCT_NAME, f"程序启动失败：{exc}\n\n请保留日志目录并联系维护人员。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
