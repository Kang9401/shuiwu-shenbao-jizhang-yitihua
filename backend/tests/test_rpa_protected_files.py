from pathlib import Path
import shutil

import pytest

from app.rpa import runtime
from app.rpa.protected_files import PROTECTED_SHA256, UNPROTECTED_DOCUMENTATION


def test_protected_vendor_files_match_baseline():
    root = Path(__file__).parents[1] / "vendor" / "etax_rpa"
    vendor_files = {path.name for path in root.iterdir() if path.is_file()}
    assert UNPROTECTED_DOCUMENTATION <= vendor_files
    assert vendor_files - UNPROTECTED_DOCUMENTATION == set(PROTECTED_SHA256)
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
    assert (app / "etax_runtime_compat.py").is_file()


def test_runtime_ignores_documentation_changes(tmp_path, monkeypatch):
    source_vendor = Path(__file__).parents[1] / "vendor" / "etax_rpa"
    vendor = tmp_path / "vendor"
    shutil.copytree(source_vendor, vendor)
    (vendor / "用户操作说明.md").write_text("updated documentation", encoding="utf-8")

    monkeypatch.setattr(runtime, "vendor_dir", lambda: vendor)
    monkeypatch.setattr(runtime, "runtime_app_dir", lambda: tmp_path / "app")
    monkeypatch.setattr(runtime, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(runtime, "uploads_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(runtime, "helper_resource_dir", lambda: tmp_path / "helpers")

    assert runtime.ensure_runtime_app() == tmp_path / "app"


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


def test_runtime_installs_runner_once_and_removes_legacy_helpers(tmp_path, monkeypatch):
    vendor = Path(__file__).parents[1] / "vendor" / "etax_rpa"
    app = tmp_path / "app"
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    runner_source = helpers / runtime.RUNNER_NAME
    runner_source.write_bytes(b"shared-rpa-runner")
    expected = runtime.sha256_file(runner_source)
    (helpers / runtime.RUNNER_HASH_NAME).write_text(expected, encoding="ascii")
    app.mkdir()
    for name in runtime.LEGACY_HELPERS:
        (app / name).write_bytes(b"legacy")

    monkeypatch.setattr(runtime, "vendor_dir", lambda: vendor)
    monkeypatch.setattr(runtime, "runtime_app_dir", lambda: app)
    monkeypatch.setattr(runtime, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(runtime, "uploads_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(runtime, "helper_resource_dir", lambda: helpers)

    runtime.ensure_runtime_app()
    assert (app / runtime.RUNNER_NAME).read_bytes() == b"shared-rpa-runner"
    assert (app / runtime.RUNNER_HASH_NAME).read_text(encoding="utf-8") == expected
    assert all(not (app / name).exists() for name in runtime.LEGACY_HELPERS)

    copied = []
    original_copy = runtime.shutil.copy2

    def record_copy(source, target):
        copied.append((Path(source).name, Path(target).name))
        return original_copy(source, target)

    monkeypatch.setattr(runtime.shutil, "copy2", record_copy)
    runtime.ensure_runtime_app()
    assert (runtime.RUNNER_NAME, runtime.RUNNER_NAME) not in copied
