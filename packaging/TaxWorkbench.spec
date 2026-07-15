from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


ROOT = Path(SPECPATH).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND_DIST = ROOT / "frontend" / "dist"
ICON = ROOT / "packaging" / "assets" / "app.ico"
VERSION_INFO = ROOT / "packaging" / "generated-version-info.txt"

hiddenimports = sorted(set(
    collect_submodules("uvicorn")
    + collect_submodules("sqlalchemy.dialects.sqlite")
    + [
        "greenlet",
        "openpyxl",
        "xlrd",
        "webview.platforms.edgechromium",
        "webview.platforms.mshtml",
        "webview.platforms.win32",
        "webview.platforms.winforms",
    ]
))

a = Analysis(
    [str(BACKEND / "desktop.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=[(str(FRONTEND_DIST), "frontend_dist"), *copy_metadata("pywebview")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "bottleneck",
        "cefpython3",
        "cryptography",
        "fsspec",
        "gi",
        "jedi",
        "jinja2",
        "jupyter",
        "jupyter_client",
        "jupyter_core",
        "llvmlite",
        "matplotlib",
        "nbformat",
        "notebook",
        "numba",
        "numexpr",
        "orjson",
        "psutil",
        "pyarrow",
        "pygments",
        "pytest",
        "rich",
        "scipy",
        "sklearn",
        "tables",
        "tkinter",
        "torch",
        "urllib3",
        "websockets",
        "zmq",
        "webview.platforms.android",
        "webview.platforms.cocoa",
        "webview.platforms.gtk",
        "webview.platforms.qt",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TaxWorkbench",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ICON),
    version=str(VERSION_INFO),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TaxWorkbench",
)
