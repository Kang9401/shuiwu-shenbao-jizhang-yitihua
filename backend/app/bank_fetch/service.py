from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from fastapi import UploadFile

from app.db.session import SessionLocal
from app.services.reconciliation_import import import_reconciliation_file
from app.models.accounting import ReconciliationImportBatch


class BankFetchService:
    def __init__(self):
        self._lock = threading.RLock()
        self._process = None
        self._cancelled = False
        self._state = {"status": "idle", "period_id": None, "message": "", "events": [], "batch_id": None}

    def _source_root(self) -> Path:
        configured = os.environ.get("BANK_FETCHER_ROOT", "").strip()
        root = Path(configured).expanduser() if configured else Path.home() / "Documents" / "自动获取银行流水"
        if not (root / "server.cjs").is_file():
            raise RuntimeError("未找到真实银行流水获取程序，请配置 BANK_FETCHER_ROOT")
        return root.resolve()

    def _request(self, path: str, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(f"http://127.0.0.1:3177{path}", data=data, headers={"Content-Type": "application/json"}, method="POST" if data is not None else "GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _ensure_process(self):
        try:
            self._request("/api/status")
        except Exception:
            service_running = False
        else:
            service_running = True
        if service_running:
            if self._process is not None and self._process.poll() is None:
                return
            raise RuntimeError("检测到单独运行的银行流水工具，请先关闭后再由本工作台启动，以确保任务可安全停止")
        node = shutil.which("node")
        if not node:
            raise RuntimeError("未找到 Node.js，无法启动银行流水获取程序")
        root = self._source_root()
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen([node, "server.cjs"], cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                self._request("/api/status")
                return
            except Exception:
                time.sleep(0.25)
        raise RuntimeError("银行流水获取程序启动超时")

    def start(self, *, period_id: int, accounts: str, start_date: str, end_date: str) -> dict:
        with self._lock:
            if self._state["status"] in {"starting", "running", "waiting-login", "importing"}:
                raise RuntimeError("已有银行流水获取任务正在运行")
            self._state = {"status": "starting", "period_id": period_id, "message": "正在启动", "events": [], "batch_id": None}
            self._cancelled = False
        self._ensure_process()
        self._request("/api/query", {"accounts": accounts, "startDate": start_date, "endDate": end_date, "pageSize": 200})
        threading.Thread(target=self._monitor, daemon=True, name="bank-fetch-monitor").start()
        return self.status()

    def open_login(self) -> dict:
        self._ensure_process()
        return self._request("/api/open-login", {})

    def _monitor(self):
        while not self._cancelled:
            try:
                payload = self._request("/api/status")
                job = payload.get("job") or {}
                status = job.get("status") or "running"
                with self._lock:
                    self._state.update(status=status, message=job.get("message") or status, events=payload.get("events", [])[-100:])
                if status == "completed":
                    self._import_output(Path(job["outputFile"]))
                    return
                if status == "failed":
                    return
            except Exception as exc:
                with self._lock:
                    self._state.update(status="failed", message=str(exc))
                return
            time.sleep(1)

    def _import_output(self, output: Path):
        root = (self._source_root() / "exports").resolve()
        resolved = output.resolve()
        if root not in resolved.parents or not resolved.is_file():
            raise RuntimeError("银行流水输出文件超出允许目录")
        with self._lock:
            self._state.update(status="importing", message="流水已获取，正在导入")
            period_id = self._state["period_id"]
        db = SessionLocal()
        try:
            digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            for existing in db.query(ReconciliationImportBatch).filter(ReconciliationImportBatch.period_id == period_id, ReconciliationImportBatch.import_type == "bank_statement").all():
                existing_path = Path(existing.stored_path)
                if existing_path.is_file() and hashlib.sha256(existing_path.read_bytes()).hexdigest() == digest:
                    with self._lock:
                        self._state.update(status="succeeded", message="银行流水已存在，未重复导入", batch_id=existing.id)
                    return
            with resolved.open("rb") as handle:
                upload = UploadFile(filename=resolved.name, file=handle)
                batch = import_reconciliation_file(db, period_id=period_id, import_type="bank_statement", file=upload)
            with self._lock:
                self._state.update(status="succeeded", message="银行流水获取并导入完成", batch_id=batch.id)
        except Exception as exc:
            db.rollback()
            with self._lock:
                self._state.update(status="import_failed", message=f"流水已获取，但导入失败：{exc}")
        finally:
            db.close()

    def stop(self) -> dict:
        self._cancelled = True
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
        with self._lock:
            self._state.update(status="cancelled", message="任务已停止")
        return self.status()

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)


bank_fetch_service = BankFetchService()
