from pathlib import Path

import pytest

from app.rpa import runtime
from app.rpa.protected_files import PROTECTED_SHA256


def test_protected_vendor_files_match_baseline():
    root = Path(__file__).parents[1] / "vendor" / "etax_rpa"
    assert set(path.name for path in root.iterdir() if path.is_file()) == set(PROTECTED_SHA256)
    for name, expected in PROTECTED_SHA256.items():
        assert runtime.sha256_file(root / name) == expected


def test_runtime_copy_repairs_protected_file_and_preserves_data(tmp_path, monkeypatch):
    vendor = Path(__file__).parents[1] / "vendor" / "etax_rpa"
    app = tmp_path / "app"
    state = tmp_path / "state"
    uploads = tmp_path / "uploads"
    app.mkdir()
    (app / "output").mkdir()
    (app / "output" / "keep.txt").write_text("keep", encoding="utf-8")
    (app / "etax_gui.py").write_text("damaged", encoding="utf-8")
    monkeypatch.setattr(runtime, "vendor_dir", lambda: vendor)
    monkeypatch.setattr(runtime, "runtime_app_dir", lambda: app)
    monkeypatch.setattr(runtime, "state_dir", lambda: state)
    monkeypatch.setattr(runtime, "uploads_dir", lambda: uploads)
    monkeypatch.setattr(runtime, "helper_resource_dir", lambda: tmp_path / "missing")

    assert runtime.ensure_runtime_app() == app
    assert runtime.sha256_file(app / "etax_gui.py") == PROTECTED_SHA256["etax_gui.py"]
    assert (app / "output" / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (app / "input").is_dir()
    assert (app / "etax_extra_income_reports.py").read_bytes() == (
        Path(runtime.__file__).with_name("extensions") / "etax_extra_income_reports.py"
    ).read_bytes()


def test_runtime_rejects_missing_extension(tmp_path, monkeypatch):
    vendor = Path(__file__).parents[1] / "vendor" / "etax_rpa"
    monkeypatch.setattr(runtime, "vendor_dir", lambda: vendor)
    monkeypatch.setattr(runtime, "runtime_app_dir", lambda: tmp_path / "app")
    monkeypatch.setattr(runtime, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(runtime, "uploads_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(runtime, "helper_resource_dir", lambda: tmp_path / "helpers")
    monkeypatch.setattr(runtime, "EXTENSION_FILES", ("missing_extension.py",))
    try:
        runtime.ensure_runtime_app()
    except RuntimeError as exc:
        assert "RPA 扩展源文件不存在" in str(exc)
    else:
        raise AssertionError("missing extension was accepted")


def test_runtime_rejects_extension_hash_mismatch(tmp_path, monkeypatch):
    vendor = Path(__file__).parents[1] / "vendor" / "etax_rpa"
    monkeypatch.setattr(runtime, "vendor_dir", lambda: vendor)
    monkeypatch.setattr(runtime, "runtime_app_dir", lambda: tmp_path / "app")
    monkeypatch.setattr(runtime, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(runtime, "uploads_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(runtime, "helper_resource_dir", lambda: tmp_path / "helpers")
    monkeypatch.setattr(runtime, "EXTENSION_SHA256", {"etax_extra_income_reports.py": "0" * 64})

    with pytest.raises(RuntimeError, match="RPA 扩展源文件校验失败"):
        runtime.ensure_runtime_app()
