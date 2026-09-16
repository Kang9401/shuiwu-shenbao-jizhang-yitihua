"""Start the local API and Vite server on verified available ports."""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
PYTHON = os.environ.get("TAX_WORKBENCH_PYTHON", sys.executable)


def find_available_port(preferred: int, fallback_range: range) -> int:
    for port in (preferred, *fallback_range):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
    raise RuntimeError(f"{preferred}-{fallback_range.stop - 1}端口均不可用，请检查Windows保留端口、防火墙或残留进程。")


def backend_command(port: int, reload_enabled: bool) -> list[str]:
    command = [PYTHON, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
    if reload_enabled:
        command.append("--reload")
    return command


def frontend_command(port: int) -> list[str]:
    return ["npx.cmd" if os.name == "nt" else "npx", "vite", "--host", "127.0.0.1", "--port", str(port)]


def wait_for_health(port: int, process: subprocess.Popen, timeout_seconds: float = 20) -> None:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("后端进程在健康检查前退出")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, OSError):
            time.sleep(0.25)
    raise RuntimeError(f"后端未在 {timeout_seconds:g} 秒内通过健康检查：{url}")


def initialize_database() -> None:
    result = subprocess.run([PYTHON, "-m", "app.db.init_db"], cwd=ROOT / "backend")
    if result.returncode:
        raise RuntimeError("数据库初始化失败")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=("all", "backend", "frontend"), default="all")
    parser.add_argument("--reload", action="store_true", help="启用 Uvicorn 热重载")
    args = parser.parse_args()
    reload_enabled = args.reload or os.environ.get("TAX_WORKBENCH_RELOAD") == "1"
    processes: list[tuple[str, subprocess.Popen]] = []
    backend_port: int | None = None
    frontend_port: int | None = None

    try:
        if args.mode in ("all", "backend"):
            print("[后端] 初始化数据库...")
            initialize_database()
            backend_port = find_available_port(8000, range(8001, 8011))
            backend = subprocess.Popen(backend_command(backend_port, reload_enabled), cwd=ROOT / "backend")
            processes.append(("后端", backend))
            print(f"[后端] 启动中... http://127.0.0.1:{backend_port}")
            wait_for_health(backend_port, backend)

        if args.mode in ("all", "frontend"):
            frontend_port = find_available_port(5173, range(5174, 5176))
            environment = os.environ.copy()
            if backend_port is not None:
                environment["TAX_WORKBENCH_BACKEND_URL"] = f"http://127.0.0.1:{backend_port}"
            frontend = subprocess.Popen(frontend_command(frontend_port), cwd=ROOT / "frontend", env=environment)
            processes.append(("前端", frontend))
            print(f"[前端] 启动中... http://127.0.0.1:{frontend_port}")

        print("\n" + "=" * 50)
        if frontend_port is not None:
            print(f"前端: http://127.0.0.1:{frontend_port}")
        if backend_port is not None:
            print(f"后端: http://127.0.0.1:{backend_port}")
            print(f"API:  http://127.0.0.1:{backend_port}/docs")
        print("按 Ctrl+C 停止本次启动的服务")
        print("=" * 50 + "\n")
        for _, process in processes:
            process.wait()
    except KeyboardInterrupt:
        print("\n正在停止本次启动的服务...")
    except RuntimeError as error:
        print(f"启动失败：{error}", file=sys.stderr)
    finally:
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    main()
