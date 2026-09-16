from __future__ import annotations

import ctypes
import json
import logging
import os
import re
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
from app.core.paths import resource_root
from app.main import app


_mutex_handle = None
_monitor_window = None
_desktop_exiting = False


class DesktopWindowManager:
    def open_rpa_monitor(self) -> dict:
        if _monitor_window is None:
            return {"opened": False, "message": "监控窗口尚未初始化"}
        _monitor_window.show()
        _monitor_window.restore()
        return {"opened": True}

    def hide_rpa_monitor(self) -> dict:
        if _monitor_window is not None:
            _monitor_window.hide()
        return {"hidden": True}

    def choose_directory(self, initial_path: str = "") -> dict:
        import webview

        window = webview.windows[0] if webview.windows else None
        if window is None:
            return {"path": ""}
        result = window.create_file_dialog(
            webview.FOLDER_DIALOG,
            directory=initial_path if initial_path and Path(initial_path).is_dir() else "",
            allow_multiple=False,
        )
        return {"path": str(result[0]) if result else ""}


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


def resource_path(relative: str | os.PathLike[str]) -> Path:
    """Resolve a bundled resource in both source and frozen execution."""
    return resource_root() / Path(relative)


def _validate_frontend_dist(frontend_dir: Path | None = None) -> Path:
    root = (frontend_dir or settings.frontend_dist_dir).resolve()
    index_file = root / "index.html"
    if not index_file.is_file():
        raise FileNotFoundError(f"前端首页不存在：{index_file}")
    text = index_file.read_text(encoding="utf-8", errors="replace")
    if '<div id="app"></div>' not in text:
        raise RuntimeError("前端首页缺少应用挂载节点")
    for asset in re.findall(r"(?:src|href)=\"([^\"]+)\"", text):
        if asset.startswith(("http://", "https://", "data:", "#")):
            continue
        asset_path = (root / asset.lstrip("/")).resolve()
        if not asset_path.is_file() or not str(asset_path).lower().startswith(str(root).lower()):
            raise FileNotFoundError(f"前端静态资源不存在：{asset}")
    return index_file


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


def _wait_for_server(url: str, timeout: float = 60.0, thread: threading.Thread | None = None) -> None:
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
    if thread.is_alive():
        server.force_exit = True
        thread.join(timeout=5)


def _hide_monitor_on_close(manager: DesktopWindowManager) -> bool:
    if _desktop_exiting:
        return True
    manager.hide_rpa_monitor()
    return False


def _close_monitor_on_main_close() -> bool:
    global _desktop_exiting
    _desktop_exiting = True
    if _monitor_window is not None:
        _monitor_window.destroy()
    return True


def _verify_frontend(url: str) -> None:
    _validate_frontend_dist()
    response = httpx.get(url, timeout=5.0, follow_redirects=True)
    response.raise_for_status()
    if '<div id="app"></div>' not in response.text:
        raise RuntimeError("前端首页内容校验失败")


def _verify_webview_backend() -> None:
    import webview
    import webview.platforms.winforms

    if not callable(getattr(webview, "create_window", None)):
        raise RuntimeError("WebView backend is unavailable")


def main() -> int:
    if "--self-test" in sys.argv:
        server = None
        thread = None
        try:
            logging.getLogger(__name__).info("Desktop self-test starting; resource_root=%s frontend=%s", resource_root(), settings.frontend_dist_dir)
            _prepare_runtime()
            from app.db.init_db import init_db
            from app.rpa.runtime import ensure_runtime_app
            import webview
            import webview.platforms.winforms

            init_db()
            rpa_runtime = ensure_runtime_app()
            expected_helpers = (
                "etax_rpa_runner.exe",
            )
            missing_helpers = [name for name in expected_helpers if not (rpa_runtime / name).is_file()]
            if missing_helpers:
                raise FileNotFoundError(f"RPA helper executables are missing: {', '.join(missing_helpers)}")
            index_file = _validate_frontend_dist()
            server, thread, url = _start_server()
            _verify_frontend(url)
            _verify_webview_backend()
            print(json.dumps({
                "status": "ok",
                "data_root": str(settings.storage_root),
                "frontend": str(index_file),
                "server": url,
                "desktop_backend": "webview.platforms.winforms",
                "rpa_runtime": str(rpa_runtime),
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
        global _monitor_window, _desktop_exiting
        _desktop_exiting = False
        _prepare_runtime()
        logging.getLogger(__name__).info("Desktop startup: resource_root=%s frontend=%s log_dir=%s", resource_root(), settings.frontend_dist_dir, settings.log_dir)
        server, thread, url = _start_server()
        try:
            import webview

            manager = DesktopWindowManager()
            main_window = webview.create_window(
                PRODUCT_NAME,
                url,
                width=1440,
                height=900,
                min_size=(1080, 680),
                text_select=True,
                js_api=manager,
            )
            _monitor_window = webview.create_window(
                "RPA 任务监控",
                f"{url}/?window=rpa-monitor",
                width=460,
                height=640,
                min_size=(380, 420),
                hidden=True,
                text_select=True,
                js_api=manager,
            )
            _monitor_window.events.closing += lambda: _hide_monitor_on_close(manager)
            main_window.events.closing += _close_monitor_on_main_close
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
