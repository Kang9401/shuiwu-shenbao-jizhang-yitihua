from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Callable

from app.rpa.paths import state_dir


def default_state() -> dict:
    return {
        "config": {"chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe", "org_excel_path": None, "org_excel_name": None},
        "chrome": {"status": "stopped", "last_checked_at": None, "message": ""},
        "current_run": {"run_id": None, "task_key": None, "display_name": None, "month": None, "backend_month": None, "all_orgs": True, "org_code": None, "current_org_code": None, "current_org_name": None, "status": "idle", "pid": None, "started_at": None, "finished_at": None, "exit_code": None, "error_message": None, "log_path": None},
        "results": {}, "history": [],
        "last_failure": {"task_key": None, "org_code": None, "month": None},
    }


class StateStore:
    def __init__(self, path: Path | None = None):
        self.path = path or state_dir() / "rpa_state.json"
        self._lock = threading.RLock()

    def read(self) -> dict:
        with self._lock:
            if not self.path.is_file():
                return default_state()
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return default_state()
            base = default_state()
            for key, value in data.items():
                if key in base:
                    base[key] = value
            return copy.deepcopy(base)

    def write(self, data: dict) -> dict:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(self.path)
            return copy.deepcopy(data)

    def update(self, callback: Callable[[dict], None]) -> dict:
        with self._lock:
            data = self.read()
            callback(data)
            return self.write(data)

    def recover_interrupted(self) -> None:
        def change(data: dict) -> None:
            run = data["current_run"]
            if run.get("status") in {"starting", "running"}:
                run.update(status="failed", finished_at=None, pid=None, error_message="应用退出导致任务中断")
                data["last_failure"] = {"task_key": run.get("task_key"), "org_code": run.get("current_org_code"), "month": run.get("month")}
        self.update(change)
