from pathlib import Path

import pytest

from app.rpa.commands import add_month, build_chrome_command, build_task_command


@pytest.fixture
def app_dir(tmp_path: Path) -> Path:
    for name in ("etax_batch_export.exe", "etax_batch_import.exe", "etax_tax_certificate_download.exe"):
        (tmp_path / name).touch()
    return tmp_path


def test_special_deduction_all_and_single_org_commands(app_dir):
    all_command, month = build_task_command(app_dir, "special_deduction", "2026-06", frozen=False)
    one_command, _ = build_task_command(app_dir, "special_deduction", "2026-06", False, "11818", frozen=False)
    assert month == "2026-06"
    assert all_command[:2][-1].endswith("etax_batch_export.py")
    assert "--org-code" not in all_command
    assert one_command[-2:] == ["--org-code", "11818"]
    assert all(isinstance(item, str) for item in one_command)


def test_resume_and_reset_import_commands(app_dir):
    resume, _ = build_task_command(app_dir, "import", "2026-06", True, None, "resume", "11818", frozen=False)
    reset, _ = build_task_command(app_dir, "import", "2026-06", True, None, "reset", frozen=False)
    assert "--input-root" in resume
    assert resume[-3:] == ["--start-org-code", "11818", "--resume"]
    assert reset[-1] == "--reset-progress"


def test_tax_certificate_adds_month_and_income_report_does_not(app_dir):
    tax, tax_month = build_task_command(app_dir, "tax_certificate", "2026-12", frozen=False)
    income, income_month = build_task_command(app_dir, "income_report", "2026-12", frozen=False)
    assert add_month("2026-12") == "2027-01"
    assert tax_month == "2027-01" and tax[tax.index("--month") + 1] == "2027-01"
    assert income_month == "2026-12" and income[income.index("--month") + 1] == "2026-12"
    assert tax[-2:] == ["--task", "tax_certificate"]
    assert income[-2:] == ["--task", "income_report"]


def test_frozen_command_uses_helper_and_chrome_is_argument_list(app_dir):
    command, _ = build_task_command(app_dir, "import", "2026-06", frozen=True)
    chrome = build_chrome_command(Path("D:/中文 路径"), "C:/Program Files/Google/Chrome/Application/chrome.exe")
    assert command[0].endswith("etax_batch_import.exe")
    assert chrome[-2] == "-ChromePath"
    assert isinstance(chrome, list)
