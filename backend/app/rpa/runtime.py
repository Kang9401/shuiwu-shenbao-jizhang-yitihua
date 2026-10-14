from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from app.rpa.extension_files import EXTENSION_FILES, EXTENSION_SHA256
from app.rpa.paths import helper_resource_dir, runtime_app_dir, state_dir, uploads_dir, vendor_dir
from app.rpa.protected_files import PROTECTED_SHA256


RUNNER_NAME = "etax_rpa_runner.exe"
RUNNER_HASH_NAME = "etax_rpa_runner.sha256"
LEGACY_HELPERS = (
    "etax_batch_import.exe",
    "etax_batch_export.exe",
    "etax_tax_certificate_download.exe",
    "etax_extra_income_reports.exe",
)


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
    runner_source = helpers / RUNNER_NAME
    hash_source = helpers / RUNNER_HASH_NAME
    if helpers.is_dir() and runner_source.is_file() and hash_source.is_file():
        expected = hash_source.read_text(encoding="utf-8-sig").strip().split()[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise RuntimeError("RPA runner 哈希清单格式无效")
        runner_target = app_dir / RUNNER_NAME
        marker = app_dir / RUNNER_HASH_NAME
        installed_hash = marker.read_text(encoding="utf-8-sig").strip().lower() if marker.is_file() else ""
        if (
            not runner_target.is_file()
            or installed_hash != expected
            or runner_target.stat().st_size != runner_source.stat().st_size
        ):
            shutil.copy2(runner_source, runner_target)
            if sha256_file(runner_target) != expected:
                raise RuntimeError("RPA runner 运行副本校验失败")
            marker.write_text(expected, encoding="utf-8")
        for name in LEGACY_HELPERS:
            (app_dir / name).unlink(missing_ok=True)
    return app_dir
