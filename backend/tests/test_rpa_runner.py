from __future__ import annotations

import sys
from pathlib import Path

from app.rpa import runner


def test_runner_dispatches_arguments_and_restores_process_state(tmp_path, monkeypatch):
    script = tmp_path / "etax_batch_import.py"
    script.write_text(
        "import sys\n"
        "def main():\n"
        "    return 0 if sys.argv[1:] == ['--month', '2026-06'] else 9\n",
        encoding="utf-8",
    )
    (tmp_path / "etax_batch_export.py").write_text("def ensure_withholding_page(page): return page\n", encoding="utf-8")
    compat = Path(__file__).parents[1] / "app" / "rpa" / "extensions" / "etax_runtime_compat.py"
    (tmp_path / "etax_runtime_compat.py").write_bytes(compat.read_bytes())
    original_argv = sys.argv
    original_path = list(sys.path)
    monkeypatch.setattr(runner, "application_dir", lambda: tmp_path)

    assert runner.main(["import", "--month", "2026-06"]) == 0
    assert sys.argv is original_argv
    assert sys.path == original_path


def test_runner_rejects_unknown_task_and_missing_script(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "application_dir", lambda: tmp_path)

    assert runner.main(["unknown"]) == 2
    assert runner.main(["import"]) == 2
