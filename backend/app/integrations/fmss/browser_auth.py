from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings

logger = logging.getLogger(__name__)


class FmssBrowserAuth:
    """Own one isolated Playwright Chrome session for FMSS login."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._status = "idle"
        self._context = None
        self._page = None
        self._playwright = None
        self._watch_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_error: str | None = None
        self._last_checked_token: str | None = None

    def open(self) -> dict[str, str | None]:
        with self._lock:
            if self._status in {"opening", "waiting_login", "validating"} and self._watch_thread and self._watch_thread.is_alive():
                return self._status_payload()
            self._stop_event = threading.Event()
            self._last_error = None
            self._last_checked_token = None
            self._status = "opening"
            self._watch_thread = threading.Thread(target=self._watch_login, name="fmss-browser-watch", daemon=True)
            self._watch_thread.start()
            return self._status_payload()

    def status(self) -> dict[str, str | None]:
        with self._lock:
            return self._status_payload()

    def close(self) -> dict[str, str | None]:
        with self._lock:
            self._stop_event.set()
            thread = self._watch_thread
            if thread is None or not thread.is_alive():
                self._status = "closed"
        if thread and thread.is_alive():
            thread.join(timeout=3)
        with self._lock:
            self._status = "closed"
            self._context = None
            self._page = None
            self._watch_thread = None
            return self._status_payload()

    def _status_payload(self) -> dict[str, str | None]:
        return {"status": self._status, "message": self._last_error}

    def _watch_login(self) -> None:
        context = None
        playwright = None
        try:
            from playwright.sync_api import sync_playwright

            executable = self._find_browser_executable()
            if executable is None:
                raise RuntimeError("找不到 Chrome，请安装 Google Chrome 或配置 BROWSER_PATH")
            profile = self._profile_dir()
            profile.mkdir(parents=True, exist_ok=True)
            logger.info("FMSS browser opening")
            playwright = sync_playwright().start()
            context = playwright.chromium.launch_persistent_context(
                str(profile),
                headless=False,
                executable_path=str(executable),
                viewport={"width": 1366, "height": 860},
                ignore_https_errors=True,
                args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--no-default-browser-check"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            with self._lock:
                if self._stop_event.is_set():
                    return
                self._playwright = playwright
                self._context = context
                self._page = page
                self._status = "waiting_login"
            logger.info("FMSS browser opened")
            page.goto(settings.fmss_login_url, wait_until="domcontentloaded", timeout=30000)
            page.bring_to_front()

            deadline = time.monotonic() + 180
            while time.monotonic() < deadline and not self._stop_event.is_set():
                if context.is_closed():
                    with self._lock:
                        self._status = "closed"
                    return
                token = self._read_admin_token(context)
                if not token or token == self._last_checked_token:
                    time.sleep(1)
                    continue
                self._last_checked_token = token
                with self._lock:
                    self._status = "validating"
                logger.info("FMSS Admin-Token detected")
                if self._validate_token(token):
                    logger.info("FMSS bearer validation succeeded")
                    with self._lock:
                        from app.integrations.fmss.session import fmss_session

                        fmss_session.connect(token)
                        self._status = "connected"
                    return
                with self._lock:
                    self._status = "waiting_login"
                time.sleep(1)
            if not self._stop_event.is_set():
                with self._lock:
                    self._status = "error"
                    self._last_error = "FMSS登录超时，请重新登录"
        except Exception as exc:
            with self._lock:
                self._status = "error"
                self._last_error = f"FMSS浏览器启动失败：{type(exc).__name__}"
            logger.warning("FMSS browser failed: %s", type(exc).__name__)
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass
            logger.info("FMSS browser closed")
            with self._lock:
                self._context = None
                self._page = None
                self._playwright = None
                if self._status == "opening":
                    self._status = "closed"

    def _read_admin_token(self, context) -> str | None:
        host = urlparse(settings.fmss_login_url).hostname
        for cookie in context.cookies(settings.fmss_login_url):
            if cookie.get("name") != "Admin-Token":
                continue
            domain = str(cookie.get("domain") or "").lstrip(".").lower()
            value = str(cookie.get("value") or "").strip()
            if domain == (host or "").lower() and value:
                return value
        return None

    def _validate_token(self, token: str) -> bool:
        from app.integrations.fmss.client import FmssClient
        from app.integrations.fmss.session import FmssSession

        candidate = FmssSession()
        candidate.connect(token)
        try:
            FmssClient(candidate).sheets("PRE")
        except Exception as exc:
            logger.warning("FMSS bearer validation failed: %s", type(exc).__name__)
            return False
        return True

    def _profile_dir(self) -> Path:
        return settings.storage_root / "fmss-browser-profile"

    def _find_browser_executable(self) -> Path | None:
        candidates: list[str] = []
        for key in ("BROWSER_PATH", "CHROME_PATH"):
            value = os.environ.get(key, "").strip()
            if value:
                candidates.append(value)
        bank_root = Path(os.environ.get("BANK_FETCHER_ROOT", "").strip() or (Path.home() / "Documents" / "自动获取银行流水"))
        try:
            candidates.extend(
                line.strip().strip('"')
                for line in (bank_root / "browser-path.txt").read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            )
        except OSError:
            pass
        candidates.extend([
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"),
            str(Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe"),
            str(Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe"),
        ])
        for candidate in dict.fromkeys(candidates):
            path = Path(candidate)
            if path.is_file():
                return path
        found = shutil.which("chrome")
        return Path(found) if found else None


fmss_browser_auth = FmssBrowserAuth()
