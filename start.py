"""
一键启动前后端服务

用法:
    python start.py                  # 同时启动前后端
    python start.py backend          # 仅启动后端
    python start.py frontend         # 仅启动前端
"""
import subprocess
import sys
import os
import time

ROOT = os.path.dirname(os.path.abspath(__file__))

# 默认使用启动本脚本的 Python；开发者可以通过环境变量覆盖。
PYTHON = os.environ.get("TAX_WORKBENCH_PYTHON", sys.executable)


def run_backend():
    """启动 FastAPI 后端 (port 8000)"""
    backend_dir = os.path.join(ROOT, "backend")

    # 先初始化数据库
    print("[后端] 初始化数据库...")
    init_cmd = [PYTHON, "-m", "app.db.init_db"]
    subprocess.run(init_cmd, cwd=backend_dir, capture_output=True)

    cmd = [
        PYTHON, "-m", "uvicorn", "app.main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
        "--reload",
    ]
    print(f"[后端] 启动中... http://127.0.0.1:8000")
    print(f"[后端] API 文档: http://127.0.0.1:8000/docs")
    return subprocess.Popen(cmd, cwd=backend_dir)


def run_frontend():
    """启动 Vite 前端 (port 5173)"""
    frontend_dir = os.path.join(ROOT, "frontend")
    # 使用 npx 确保能找到 vite
    cmd = ["npx.cmd" if os.name == "nt" else "npx", "vite", "--host", "127.0.0.1", "--port", "5173"]
    print(f"[前端] 启动中... http://127.0.0.1:5173")
    return subprocess.Popen(cmd, cwd=frontend_dir)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    processes = []

    try:
        if mode in ("all", "backend"):
            processes.append(("后端", run_backend()))

        if mode in ("all", "frontend"):
            time.sleep(1)  # 等后端先启动
            processes.append(("前端", run_frontend()))

        if not processes:
            print("用法: python start.py [backend|frontend|all]")
            return

        print(f"\n{'=' * 50}")
        if mode == "all":
            print("前后端已启动!")
            print("  前端: http://127.0.0.1:5173")
            print("  后端: http://127.0.0.1:8000")
            print("  API:  http://127.0.0.1:8000/docs")
        print("按 Ctrl+C 停止所有服务")
        print(f"{'=' * 50}\n")

        # 等待进程结束
        for _, proc in processes:
            proc.wait()

    except KeyboardInterrupt:
        print("\n正在停止服务...")
        for name, proc in processes:
            print(f"  停止 {name}...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("已停止所有服务")


if __name__ == "__main__":
    main()
