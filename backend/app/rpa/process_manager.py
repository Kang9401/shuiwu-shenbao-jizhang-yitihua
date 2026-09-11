from __future__ import annotations

import os
import subprocess
import threading
import uuid
from collections.abc import Callable
from pathlib import Path


class ProcessManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._cancelled = False
        self._cancel_file: Path | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def start(self, command: list[str], cwd: Path, on_line: Callable[[str, bool], None], on_exit: Callable[[int, bool], None]) -> int:
        with self._lock:
            if self.running:
                raise RuntimeError("已有 RPA 任务正在运行")
            env = os.environ.copy()
            env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
            cancel_file = cwd / f".rpa-cancel-{uuid.uuid4().hex}"
            cancel_file.unlink(missing_ok=True)
            env["ETAX_RPA_CANCEL_FILE"] = str(cancel_file)
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            self._cancelled = False
            self._cancel_file = cancel_file
            self._process = subprocess.Popen(
                command, cwd=str(cwd), env=env, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=flags,
            )
            process = self._process
        for stream, is_stderr in ((process.stdout, False), (process.stderr, True)):
            threading.Thread(target=self._read_stream, args=(stream, is_stderr, on_line), daemon=True).start()
        threading.Thread(target=self._wait, args=(process, on_exit), daemon=True).start()
        return process.pid

    @staticmethod
    def _read_stream(stream, is_stderr: bool, on_line: Callable[[str, bool], None]) -> None:
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            on_line(line.rstrip("\r\n"), is_stderr)
        stream.close()

    def _wait(self, process: subprocess.Popen[str], on_exit: Callable[[int, bool], None]) -> None:
        code = process.wait()
        with self._lock:
            cancelled = self._cancelled
            if self._process is process:
                self._process = None
            cancel_file = self._cancel_file
            self._cancel_file = None
        try:
            on_exit(code, cancelled)
        finally:
            if cancel_file:
                cancel_file.unlink(missing_ok=True)

    def stop(self) -> bool:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                return False
            self._cancelled = True
            cancel_file = self._cancel_file
            if cancel_file:
                cancel_file.write_text("cancelled\n", encoding="ascii")
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True, shell=False)
            else:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"RPA 进程树未能停止，残留 PID：{process.pid}") from exc
        if process.poll() is None:
            raise RuntimeError(f"RPA 进程仍在运行，残留 PID：{process.pid}")
        return True
