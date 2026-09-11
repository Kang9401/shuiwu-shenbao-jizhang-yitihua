from __future__ import annotations

import runpy
import sys
from pathlib import Path

# These imports make the shared dependencies available to scripts loaded from
# the runtime RPA directory and ensure PyInstaller collects their hooks.
import openpyxl  # noqa: F401
import playwright.sync_api  # noqa: F401


TASK_SCRIPTS = {
    "special_deduction": "etax_batch_export.py",
    "import": "etax_batch_import.py",
    "tax_certificate": "etax_tax_certificate_download.py",
    "income_report": "etax_tax_certificate_download.py",
    "extra_income_reports": "etax_extra_income_reports.py",
}


def configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def application_dir() -> Path:
    return Path(sys.executable).resolve().parent


def main(argv: list[str] | None = None) -> int:
    configure_utf8_output()
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in TASK_SCRIPTS:
        tasks = ", ".join(sorted(TASK_SCRIPTS))
        print(f"Usage: etax_rpa_runner.exe <task> [arguments]\nTasks: {tasks}", file=sys.stderr)
        return 2

    script = application_dir() / TASK_SCRIPTS[args[0]]
    if not script.is_file():
        print(f"RPA script is missing: {script.name}", file=sys.stderr)
        return 2

    original_argv = sys.argv
    original_path = list(sys.path)
    sys.argv = [str(script), *args[1:]]
    sys.path.insert(0, str(script.parent))
    try:
        try:
            from etax_runtime_compat import install

            install()
            namespace = runpy.run_path(str(script), run_name=f"_etax_rpa_{args[0]}")
            namespace["ensure_withholding_page"] = sys.modules["etax_batch_export"].ensure_withholding_page
            result = namespace["main"]()
            return int(result or 0)
        except SystemExit as exc:
            if exc.code is None:
                return 0
            if isinstance(exc.code, int):
                return exc.code
            print(str(exc.code), file=sys.stderr)
            return 1
    finally:
        sys.argv = original_argv
        sys.path[:] = original_path


if __name__ == "__main__":
    raise SystemExit(main())
