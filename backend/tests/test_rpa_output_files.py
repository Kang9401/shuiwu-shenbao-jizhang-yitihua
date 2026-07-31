import io
import zipfile

import pytest

from app.rpa import service as service_module
from app.rpa.service import RpaService


class FakeManager:
    def __init__(self, running=False):
        self.running = running


def test_rpa_output_archive_and_clear_only_top_level_files(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    output = app_dir / "output"
    output.mkdir(parents=True)
    (output / "a.xlsx").write_bytes(b"a")
    (output / "b.pdf").write_bytes(b"b")
    nested = output / "nested"
    nested.mkdir()
    (nested / "keep.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(service_module, "ensure_runtime_app", lambda: app_dir)
    service = RpaService(store=object(), manager=FakeManager())

    filename, content = service.build_output_archive()
    assert filename.startswith("RPA输出文件_")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.namelist() == ["a.xlsx", "b.pdf"]

    assert service.clear_output_files() == []
    assert not (output / "a.xlsx").exists()
    assert (nested / "keep.txt").is_file()


def test_rpa_output_actions_are_rejected_while_running(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    (app_dir / "output").mkdir(parents=True)
    (app_dir / "output" / "result.xlsx").write_bytes(b"result")
    monkeypatch.setattr(service_module, "ensure_runtime_app", lambda: app_dir)
    service = RpaService(store=object(), manager=FakeManager(running=True))

    with pytest.raises(RuntimeError, match="运行中"):
        service.build_output_archive()
    with pytest.raises(RuntimeError, match="运行中"):
        service.clear_output_files()
