#!/usr/bin/env python
"""Audit the real PIT source adapters without changing business data."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.company_context import reset_company_id, set_company_id
from app.db.session import SessionLocal
from app.services.pit_reconciliation.source_service import PitSourceService


SOURCE_FIELDS = {
    "salary": ("person_name", "pit_tax", "cumulative_taxable_income", "cumulative_basic_deduction", "cumulative_special_deduction", "cumulative_child_education", "cumulative_elderly_support", "cumulative_housing_loan_interest", "cumulative_housing_rent", "cumulative_continuing_education", "cumulative_infant_care", "cumulative_personal_pension", "cumulative_other_deduction"),
    "broker": ("pit_tax", "gross_before_topup", "vat_amount", "org_code"),
    "bond_interest": ("customer_name", "id_number", "interest_amount", "withheld_tax", "org_code"),
    "restricted_stock": ("customer_name", "id_number", "security_name", "sale_amount", "withheld_tax", "org_code"),
}


def audit_fields(rows, fields):
    total = len(rows)
    return [(field, sum(getattr(row, field, None) is not None and getattr(row, field, None) != "" for row in rows), total) for field in fields]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-id", required=True, type=int)
    parser.add_argument("--period-id", required=True, type=int)
    parser.add_argument("--output", default="outputs/pit_source_validation.md")
    args = parser.parse_args()
    token = set_company_id(args.company_id)
    db = SessionLocal()
    try:
        bundle = PitSourceService(db, args.company_id, args.period_id).load_bundle()
        sources = (bundle.organizations, bundle.salary, bundle.declarations, bundle.balance, bundle.broker, bundle.bond_interest, bundle.restricted_stock, bundle.certificates, bundle.bank)
        lines = ["# PIT Source Validation", "", f"- Company: `{args.company_id}`", f"- Period: `{args.period_id}`", ""]
        for source in sources:
            lines += [f"## {source.source_type}", "", f"- Status: `{source.status}`", f"- Required: `{source.required}`", f"- Row count: `{len(source.rows)}`", f"- Source: `{source.source_kind or '—'}` / `{source.source_id or '—'}`", f"- Reference: `{source.source_ref or '—'}`"]
            if source.issues:
                lines += ["- Issues:"] + [f"  - {item.get('message', item)}" for item in source.issues]
            fields = SOURCE_FIELDS.get(source.source_type)
            if fields:
                lines += ["", "| Field | Non-null | Total | Result |", "| --- | ---: | ---: | --- |"]
                for field, present, total in audit_fields(source.rows, fields):
                    result = "PASS" if total == 0 or present else "FAIL"
                    lines.append(f"| {field} | {present} | {total} | {result} |")
            lines.append("")
        output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True); output.write_text("\n".join(lines), encoding="utf-8")
        print(output)
    finally:
        db.close(); reset_company_id(token)


if __name__ == "__main__":
    main()
