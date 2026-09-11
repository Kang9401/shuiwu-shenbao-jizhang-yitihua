from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Callable

from app.rpa.paths import state_dir
from app.rpa.popup_rules import default_popup_rules


def default_state() -> dict:
    return {
        "state_version": 2,
        "config": {"chrome_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe", "input_path": "", "output_path": "", "org_excel_path": None, "org_excel_name": None},
        "chrome": {"status": "stopped", "last_checked_at": None, "message": ""},
        "current_run": {"run_id": None, "task_key": None, "subtask_key": None, "subtask_index": None, "subtask_count": None, "display_name": None, "period_id": None, "declaration_month": None, "month": None, "backend_month": None, "month_manually_overridden": False, "all_orgs": True, "org_codes": [], "org_code": None, "current_org_code": None, "current_org_name": None, "status": "idle", "pid": None, "started_at": None, "finished_at": None, "exit_code": None, "error_message": None, "log_path": None},
        "results": {}, "history": [],
        "last_failure": {"task_key": None, "org_code": None, "month": None},
        "popup_rules": default_popup_rules(),
    }


def result_cell(status: str = "pending", count=None, reason=None, error_message=None) -> dict:
    labels = {"pending": "待处理", "running": "处理中", "success": "成功", "failed": "失败", "skipped": "无需处理", "cancelled": "已取消"}
    label = labels[status]
    if status == "success" and count is not None:
        label = f"成功 {count}笔"
    return {"status": status, "count": count, "label": label, "reason": reason, "started_at": None, "finished_at": None, "error_message": error_message}


def _legacy_cell(value) -> dict:
    if isinstance(value, dict) and value.get("status"):
        return value
    text = str(value or "待处理")
    if text.startswith("成功"):
        import re
        match = re.search(r"(\d+)", text)
        count = int(match.group(1)) if match else None
        return result_cell("skipped" if count == 0 else "success", count=0 if count == 0 else count, reason="历史结果迁移" if count == 0 else None)
    mapping = {"处理中": "running", "失败": "failed", "已取消": "cancelled", "无需处理": "skipped"}
    return result_cell(mapping.get(text, "pending"), error_message=text if text not in mapping and text != "待处理" else None)


def migrate_state(data: dict) -> dict:
    migrated = copy.deepcopy(data or {})
    if migrated.get("state_version") == 2:
        base = default_state()
        for key, value in migrated.items():
            if key in base:
                base[key] = value
        for key, value in default_state()["current_run"].items():
            base["current_run"].setdefault(key, value)
        for key, value in default_state()["config"].items():
            base["config"].setdefault(key, value)
        return base
    for orgs in migrated.get("results", {}).values():
        for row in orgs.values():
            row["special_deduction"] = _legacy_cell(row.get("special_deduction"))
            row["import"] = _legacy_cell(row.get("import"))
            row["tax_certificate"] = _legacy_cell(row.get("tax_certificate"))
            row["comprehensive_income_report"] = _legacy_cell(row.pop("income_report", None))
            if "extra_income_reports" in row:
                row["legacy_extra_income_reports"] = row.pop("extra_income_reports")
            reason = "历史数据未拆分"
            row["classified_income_report"] = result_cell("pending", reason=reason)
            row["restricted_stock_report"] = result_cell("pending", reason=reason)
    migrated["state_version"] = 2
    return migrate_state(migrated)


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
            return copy.deepcopy(migrate_state(data))

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
