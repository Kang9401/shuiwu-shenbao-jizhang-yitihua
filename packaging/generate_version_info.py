from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_SOURCE = ROOT / "backend" / "app" / "core" / "version.py"


def load_product_values() -> dict:
    values: dict = {}
    exec(VERSION_SOURCE.read_text(encoding="utf-8"), values)
    return values


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in version.split(".")]
    if len(parts) > 4:
        raise ValueError("Windows file version supports at most four numeric parts")
    return tuple((parts + [0] * 4)[:4])


def render(values: dict) -> str:
    version = values["APP_VERSION"]
    product_name = values["PRODUCT_NAME"]
    numbers = version_tuple(version)
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numbers!r},
    prodvers={numbers!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'080404B0',
        [StringStruct(u'CompanyName', u'财税数字化工具组'),
         StringStruct(u'FileDescription', u'{product_name}'),
         StringStruct(u'FileVersion', u'{version}'),
         StringStruct(u'InternalName', u'TaxWorkbench'),
         StringStruct(u'LegalCopyright', u'Internal Use'),
         StringStruct(u'OriginalFilename', u'TaxWorkbench.exe'),
         StringStruct(u'ProductName', u'{product_name}'),
         StringStruct(u'ProductVersion', u'{version}')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "packaging" / "generated-version-info.txt")
    args = parser.parse_args()
    args.output.write_text(render(load_product_values()), encoding="utf-8")


if __name__ == "__main__":
    main()

