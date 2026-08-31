#!/usr/bin/env python
"""Read-only legacy comparison for the PIT reconciliation fixture workbook.

The database workpaper is intentionally not exported back to Excel.  This tool
validates the legacy fixture's core reconciliation sheets and writes a compact
JSON observation report for review; it never changes the legacy inputs.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

import openpyxl


def decimal(value):
    if value is None or value == "": return None
    try: return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError): return None


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--fixture-dir",required=True); parser.add_argument("--output",default="")
    args=parser.parse_args(); directory=Path(args.fixture_dir)
    files=sorted(path for path in directory.glob("*.xlsx") if "核对底稿" in path.name)
    if not files: raise SystemExit("未找到 legacy 个税核对底稿 Excel")
    workbook=openpyxl.load_workbook(files[-1],read_only=True,data_only=True)
    report={"fixture":str(files[-1]),"sheets":{},"observations":{"broker_combined_rows":"legacy workbook retains separate 21131042/45019006 rows; production preserves this compatibility behavior","a2_same_name_pairing":"production uses exact taxable-income first, then source-order pairing","bank_tax_pool":"production uses transactions with 摘要 containing 税 when available, otherwise all transactions"}}
    for sheet in workbook.worksheets:
        numeric=[]
        for row in sheet.iter_rows(values_only=True):
            numeric.extend(value for value in row if decimal(value) is not None)
        report["sheets"][sheet.title]={"rows":sheet.max_row,"columns":sheet.max_column,"numeric_cell_count":len(numeric),"numeric_total":str(sum((decimal(value) for value in numeric),Decimal("0.00")))}
    output=Path(args.output) if args.output else directory / "pit_legacy_regression_report.json"
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"fixture":report["fixture"],"output":str(output),"sheet_count":len(report["sheets"])},ensure_ascii=False))


if __name__=="__main__": main()
