import io
import subprocess

import pytest

from app.rpa import process_manager


class FakeProcess:
    pid = 123

    def __init__(self, *args, **kwargs):
        self.stdout = io.StringIO("out\n")
        self.stderr = io.StringIO("err\n")
        self.code = None
        self.terminated = False

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        if timeout and self.code is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        if self.code is None:
            self.code = 0
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15

    def kill(self):
        self.code = -9


def test_duplicate_start_is_rejected(monkeypatch, tmp_path):
    manager = process_manager.ProcessManager()
    fake = FakeProcess()
    manager._process = fake
    with pytest.raises(RuntimeError, match="正在运行"):
        manager.start(["fake"], tmp_path, lambda line: None, lambda code, cancelled: None)


def test_stop_sets_cancel_marker_then_terminates_process(monkeypatch, tmp_path):
    monkeypatch.setattr(process_manager.os, "name", "posix")
    manager = process_manager.ProcessManager()
    fake = FakeProcess()
    manager._process = fake
    manager._cancel_file = tmp_path / "cancel"
    assert manager.stop() is True
    assert manager._cancel_file.read_text(encoding="ascii") == "cancelled\n"
    assert fake.terminated is True
    assert manager._cancelled is True
