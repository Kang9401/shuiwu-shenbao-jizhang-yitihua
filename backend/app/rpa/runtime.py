from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from app.rpa.extension_files import EXTENSION_FILES, EXTENSION_SHA256
from app.rpa.paths import helper_resource_dir, runtime_app_dir, state_dir, uploads_dir, vendor_dir
from app.rpa.protected_files import PROTECTED_SHA256


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_runtime_app() -> Path:
    source_root = vendor_dir()
    if not source_root.is_dir():
        raise RuntimeError(f"RPA 只读源目录不存在：{source_root}")
    app_dir = runtime_app_dir()
    app_dir.mkdir(parents=True, exist_ok=True)
    state_dir().mkdir(parents=True, exist_ok=True)
    (uploads_dir() / "org_excel").mkdir(parents=True, exist_ok=True)
    (uploads_dir() / "import_files").mkdir(parents=True, exist_ok=True)
    (app_dir / "input").mkdir(exist_ok=True)
    (app_dir / "output").mkdir(exist_ok=True)

    for name, expected in PROTECTED_SHA256.items():
        source = source_root / name
        if not source.is_file() or sha256_file(source) != expected:
            raise RuntimeError(f"RPA 受保护源文件校验失败：{name}")
        target = app_dir / name
        if not target.is_file() or sha256_file(target) != expected:
            shutil.copy2(source, target)
        if sha256_file(target) != expected:
            raise RuntimeError(f"RPA 运行副本校验失败：{name}")

    extension_root = Path(__file__).with_name("extensions")
    for name in EXTENSION_FILES:
        source = extension_root / name
        if not source.is_file():
            raise RuntimeError(f"RPA 扩展源文件不存在：{name}")
        expected = EXTENSION_SHA256.get(name)
        if expected and sha256_file(source) != expected:
            raise RuntimeError(f"RPA 扩展源文件校验失败：{name}")
        target = app_dir / name
        if not target.is_file() or sha256_file(target) != sha256_file(source):
            shutil.copy2(source, target)
        if expected and sha256_file(target) != expected:
            raise RuntimeError(f"RPA 扩展运行副本校验失败：{name}")

    helpers = helper_resource_dir()
    if helpers.is_dir():
        for source in helpers.glob("etax_*.exe"):
            shutil.copy2(source, app_dir / source.name)
    return app_dir
