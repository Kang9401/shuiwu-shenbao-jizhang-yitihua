from __future__ import annotations

import re
import sys
import os
from pathlib import Path

TASK_SCRIPTS = {
    "special_deduction": "etax_batch_export.py",
    "import": "etax_batch_import.py",
    "tax_certificate": "etax_tax_certificate_download.py",
    "income_report": "etax_tax_certificate_download.py",
    "extra_income_reports": "etax_extra_income_reports.py",
}
CDP_URL = "http://127.0.0.1:9222"


def validate_month(month: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("申报月份必须使用 YYYY-MM 格式")
    return month


def add_month(month: str) -> str:
    validate_month(month)
    year, value = map(int, month.split("-"))
    return f"{year + (value == 12)}-{1 if value == 12 else value + 1:02d}"


def _launcher(app_dir: Path, task_key: str, script_name: str, frozen: bool | None) -> list[str]:
    use_exe = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if use_exe:
        executable = app_dir / "etax_rpa_runner.exe"
        if not executable.is_file():
            raise RuntimeError(f"RPA 后台程序不存在：{executable.name}")
        return [str(executable), task_key]
    return [sys.executable, str(app_dir / script_name)]


def build_task_command(
    app_dir: Path,
    task_key: str,
    month: str,
    all_orgs: bool = True,
    org_code: str | None = None,
    resume_mode: str | None = None,
    start_org_code: str | None = None,
    frozen: bool | None = None,
    input_root: Path | None = None,
) -> tuple[list[str], str]:
    if task_key not in TASK_SCRIPTS:
        raise ValueError("未知 RPA 任务")
    validate_month(month)
    if not all_orgs and not org_code:
        raise ValueError("指定机构不能为空")
    backend_month = add_month(month) if task_key == "tax_certificate" else month
    args = _launcher(app_dir, task_key, TASK_SCRIPTS[task_key], frozen)
    args += ["--cdp", CDP_URL, "--month", backend_month, "--org-excel", str(app_dir / "机构信息表.xlsx")]
    if task_key == "import":
        args += ["--input-root", str(input_root or app_dir / "input")]
    args.append("--yes")
    if not all_orgs:
        args += ["--org-code", str(org_code)]
    if start_org_code:
        args += ["--start-org-code", start_org_code]
    if task_key == "import" and resume_mode == "resume":
        args.append("--resume")
    elif task_key == "import" and resume_mode == "reset":
        args.append("--reset-progress")
    if task_key in {"tax_certificate", "income_report"}:
        args += ["--task", task_key]
    return args, backend_month


def build_chrome_command(app_dir: Path, chrome_path: str = "") -> list[str]:
    candidates = [
        chrome_path.strip(),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ]
    executable = next((Path(item) for item in candidates if item and Path(item).is_file()), None)
    if executable is None:
        attempted = "; ".join(item for item in candidates if item)
        raise RuntimeError(f"找不到 Chrome。请填写 chrome.exe 完整路径。已尝试：{attempted}")
    profile = app_dir / ".chrome-debug-profile"
    return [
        str(executable),
        "--remote-debugging-address=127.0.0.1",
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        "--new-window",
        "https://etax.chinatax.gov.cn/",
    ]
