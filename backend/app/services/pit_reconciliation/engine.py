from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
import json

from .constants import OCCURRENCE_INCOME_TYPES, OCCURRENCE_SUBJECT_CODES, SUBJECT_DESCRIPTIONS, TAX_SUBJECT_CODES
from .money import add_nullable, has_difference, subtract_nullable
from .rules.bond_interest import bond_interest_details
from .rules.declaration_summary import summarize
from .rules.occurrence import expected_income
from .rules.payment import find_subset_sum
from .rules.restricted_stock import restricted_stock_details
from .rules.salary_tax import salary_tax_details
from .rules.salary_taxable_income import salary_taxable_income_details
from .rules.tax_amount import declared_by_subject


def _stabilize_detail_identity_keys(details):
    """Keep duplicate source identities as separate, deterministic detail rows.

    The detail table has a natural-key uniqueness constraint.  Source systems
    can nevertheless emit the same complete identity more than once (for
    example, after a duplicate customer/name grouping).  Do not drop the
    second discrepancy; add a stable ordinal suffix and record why it was
    needed in the row payload.
    """
    used: set[str] = set()
    counts: dict[str, int] = {}
    for detail in details:
        base = str(detail.get("identity_key") or "")
        ordinal = counts.get(base, 0)
        candidate = base
        if candidate in used:
            ordinal += 1
            candidate = f"{base}:duplicate-{ordinal}"
            while candidate in used:
                ordinal += 1
                candidate = f"{base}:duplicate-{ordinal}"
            detail["identity_key"] = candidate
            detail["auto_reason"] = f"{detail.get('auto_reason', '')}（重复身份键，已稳定区分）"
            payload = dict(detail.get("detail_json") or {})
            payload["identity_key_collision"] = True
            payload["identity_key_base"] = base
            payload["identity_key_duplicate_index"] = ordinal
            detail["detail_json"] = payload
        counts[base] = ordinal
        used.add(candidate)
    return details


def _payment_totals(orgs, certificates, bank):
    certificate_by_org = defaultdict(lambda: Decimal("0.00"))
    if certificates.status in {"ready", "ready_empty"}:
        for row in certificates.rows:
            if "个人所得税" in row.tax_type:
                certificate_by_org[row.org_code] += row.amount or Decimal("0.00")
    bank_by_org = defaultdict(lambda: Decimal("0.00"))
    matches = []
    if bank.status in {"ready", "ready_empty"}:
        bank_rows_by_org = defaultdict(list)
        for row in bank.rows:
            if row.org_code in orgs and (row.debit_amount or Decimal("0.00")) > 0:
                bank_rows_by_org[row.org_code].append(row)
        for org_code, target in certificate_by_org.items():
            org_rows = bank_rows_by_org.get(org_code, [])
            candidates = [row for row in org_rows if "税" in row.summary] or org_rows
            indexes = find_subset_sum([abs(row.debit_amount or Decimal("0.00")) for row in candidates], target)
            if indexes:
                for index in indexes:
                    row = candidates[index]
                    bank_by_org[org_code] += abs(row.debit_amount or Decimal("0.00"))
                    matches.append({"org_code": org_code, "org_full_name": orgs.get(org_code, ""),
                                    "bank_account": row.bank_account, "transaction_time": row.transaction_time,
                                    "transaction_summary": row.summary, "debit_amount": abs(row.debit_amount or Decimal("0.00")),
                                    "source_batch_id": row.source_batch_id, "source_row_id": row.source_row_id})
    return certificate_by_org, bank_by_org, matches


class PitReconciliationEngine:
    """Pure PIT calculation engine. Its input and output contain no ORM objects."""
    def calculate_post(self, pre_result, certificates, bank):
        result = pre_result
        orgs = {row["org_code"]: row.get("org_full_name") or row.get("org_name", "") for row in result["org_summaries"]}
        certificate_totals, bank_totals, matches = _payment_totals(orgs, certificates, bank)
        for row in result["org_summaries"]:
            certificate = None if certificates.status in {"missing", "invalid"} else certificate_totals[row["org_code"]]
            bank_amount = None if bank.status in {"missing", "invalid"} else bank_totals[row["org_code"]]
            row.update(certificate_tax_amount=certificate, bank_tax_amount=bank_amount,
                       difference_4=subtract_nullable(row["declared_tax_amount"], certificate),
                       difference_5=subtract_nullable(certificate, bank_amount))
            row["check_status"] = "missing_source" if row["difference_4"] is None or row["difference_5"] is None else (
                "difference" if has_difference(row["difference_4"]) or has_difference(row["difference_5"]) else "ok")
        result["bank_matches"] = matches
        result["stage"] = "post_payment"
        result["sources"] += [{"source_type": source.source_type, "status": source.status, "required": True,
                              "source_kind": source.source_kind, "source_id": source.source_id, "source_ref": source.source_ref,
                              "row_count": len(source.rows), "issues_json": source.issues} for source in (certificates, bank)]
        return result

    def calculate(self, bundle):
        sources=[bundle.organizations,bundle.salary,bundle.declarations,bundle.balance,bundle.broker,bundle.bond_interest,bundle.restricted_stock,bundle.certificates,bundle.bank]
        source_map={source.source_type: source for source in sources}
        # Source adapters name their workflow internally; normalize public source names.
        source_map["broker"] = bundle.broker; source_map["bond_interest"] = bundle.bond_interest; source_map["restricted_stock"] = bundle.restricted_stock
        orgs={row.org_code: row for row in bundle.organizations.rows}
        allowed_org_codes = set(orgs)
        for source in (bundle.salary,bundle.declarations,bundle.balance,bundle.broker,bundle.bond_interest,bundle.restricted_stock):
            for row in source.rows:
                code=getattr(row,"org_code","")
                if code and code not in allowed_org_codes:
                    continue
        balance=defaultdict(dict)
        subject_description_by_code = {}
        for row in bundle.balance.rows:
            balance[row.org_code][row.subject_code]=row
            if row.description and row.subject_code not in subject_description_by_code:
                subject_description_by_code[row.subject_code] = row.description

        def subject_description(subject, item):
            return (item.description if item and item.description else None) or subject_description_by_code.get(subject) or SUBJECT_DESCRIPTIONS[subject]
        tax_rows=[]; occurrence_rows=[]
        for org_code,org in sorted(orgs.items()):
            declared,scoped=declared_by_subject(bundle.declarations.rows,org_code)
            business={
                "21510006": sum((item.pit_tax or Decimal("0.00") for item in bundle.salary.rows if item.org_code == org_code),Decimal("0.00")),
                "21510008": sum((abs(item.withheld_tax or Decimal("0.00")) for item in bundle.bond_interest.rows if item.org_code == org_code),Decimal("0.00")),
                "21510009": sum((abs(item.withheld_tax or Decimal("0.00")) for item in bundle.restricted_stock.rows if item.org_code == org_code),Decimal("0.00")),
                "21510016": sum((item.pit_tax or Decimal("0.00") for item in bundle.broker.rows if item.org_code == org_code),Decimal("0.00")),
            }
            required={"21510006":"salary","21510008":"bond_interest","21510009":"restricted_stock","21510016":"broker"}
            for subject in TAX_SUBJECT_CODES:
                item=balance[org_code].get(subject); source=source_map[required[subject]]; declared_missing=bundle.declarations.status in {"missing","invalid"}; business_value=None if source.status in {"missing","invalid"} else business[subject]; declared_value=None if declared_missing else declared[subject]; scoped_value=None if declared_missing else scoped[subject]
                status="invalid_source" if source.status=="invalid" or bundle.declarations.status=="invalid" or bundle.balance.status=="invalid" else "missing_source" if source.status=="missing" or bundle.declarations.status=="missing" or bundle.balance.status=="missing" else "ok"
                current=subtract_nullable(declared_value,item.closing_balance if item else Decimal("0.00")); cumulative=subtract_nullable(declared_value,item.closing_balance if item else Decimal("0.00")); business_diff=subtract_nullable(scoped_value,business_value)
                if status=="ok" and any(has_difference(value) for value in (current,cumulative,business_diff)): status="difference"
                tax_rows.append({"org_code":org_code,"org_name":org.org_name,"subject_code":subject,"subject_name":subject_description(subject, item),"opening_balance":item.opening_balance if item else Decimal("0.00"),"debit_amount":item.debit_amount if item else Decimal("0.00"),"credit_amount":item.credit_amount if item else Decimal("0.00"),"closing_balance":item.closing_balance if item else Decimal("0.00"),"business_tax_amount":business_value,"declared_tax_amount":declared_value,"current_difference":current,"cumulative_difference":cumulative,"scoped_declared_tax_amount":scoped_value,"business_declared_difference":business_diff,"check_status":status})
            broker_gross=sum((item.gross_before_topup or Decimal("0.00") for item in bundle.broker.rows if item.org_code==org_code),Decimal("0.00")); broker_vat=sum((item.vat_amount or Decimal("0.00") for item in bundle.broker.rows if item.org_code==org_code),Decimal("0.00"))
            actual_by_item=defaultdict(lambda:Decimal("0.00"))
            for declaration in bundle.declarations.rows:
                if declaration.org_code==org_code: actual_by_item[declaration.income_item]+=declaration.income_amount or Decimal("0.00")
            expected_by_subject={}
            occurrence_context={}
            for subject in OCCURRENCE_SUBJECT_CODES:
                item=balance[org_code].get(subject); occurrence=item.debit_amount if item else (None if bundle.balance.status in {"missing","invalid"} else Decimal("0.00")); income_type=OCCURRENCE_INCOME_TYPES[subject]
                broker_value=(broker_gross if subject=="45019006" else Decimal("0.00")) if bundle.broker.status not in {"missing","invalid"} else None
                broker_diff=subtract_nullable(broker_value,occurrence) if subject=="45019006" else Decimal("0.00")
                expected, _ = expected_income(subject, occurrence, broker_value, broker_vat if broker_value is not None else None)
                expected_by_subject[subject]=expected
                occurrence_context[subject]=(item,occurrence,income_type,broker_value,broker_diff)
            expected_by_income_type=defaultdict(lambda:Decimal("0.00"))
            for subject, expected in expected_by_subject.items():
                expected_by_income_type[OCCURRENCE_INCOME_TYPES[subject]] += expected or Decimal("0.00")
            emitted_income_types=set()
            for subject in OCCURRENCE_SUBJECT_CODES:
                item,occurrence,income_type,broker_value,broker_diff=occurrence_context[subject]
                is_group_first = income_type not in emitted_income_types
                emitted_income_types.add(income_type)
                expected=expected_by_income_type[income_type] if is_group_first else None
                actual=None if bundle.declarations.status in {"missing","invalid"} or not is_group_first else actual_by_item[income_type]
                difference=subtract_nullable(actual,expected) if is_group_first else None
                status="invalid_source" if bundle.balance.status=="invalid" or bundle.declarations.status=="invalid" or (subject=="45019006" and bundle.broker.status=="invalid") else "missing_source" if bundle.balance.status=="missing" or bundle.declarations.status=="missing" or (subject=="45019006" and bundle.broker.status=="missing") else "difference" if has_difference(broker_diff) or has_difference(difference) else "ok"
                occurrence_rows.append({"org_code":org_code,"org_name":org.org_name,"subject_code":subject,"subject_name":subject_description(subject, item),"income_type":income_type,"opening_balance":item.opening_balance if item else None,"debit_amount":item.debit_amount if item else None,"credit_amount":item.credit_amount if item else None,"closing_balance":item.closing_balance if item else None,"occurrence_amount":occurrence,"broker_payroll_amount":broker_value,"broker_occurrence_difference":broker_diff,"expected_declared_income":expected,"expected_income_description":expected_income(subject, occurrence, broker_value, broker_vat)[1],"actual_declared_income":actual,"declared_income_difference":difference,"check_status":status})
        details=[]
        if bundle.salary.status=="ready" and bundle.declarations.status=="ready": details += salary_tax_details(bundle.salary.rows,bundle.declarations.rows)+salary_taxable_income_details(bundle.salary.rows,bundle.declarations.rows)
        if bundle.bond_interest.status=="ready" and bundle.declarations.status=="ready": details += bond_interest_details(bundle.bond_interest.rows,bundle.declarations.rows)
        if bundle.restricted_stock.status=="ready" and bundle.declarations.status=="ready": details += restricted_stock_details(bundle.restricted_stock.rows,bundle.declarations.rows)
        details = _stabilize_detail_identity_keys(details)
        # Detail rules deliberately stay data-source focused. Apply the canonical
        # organization name once here so every attachment has a consistent branch name.
        for detail in details:
            org = orgs.get(detail["org_code"])
            detail["org_name"] = org.org_name if org else ""
        summaries=[]; bank_matches=[]; details_by_org=defaultdict(lambda:Decimal("0.00"))
        for detail in details:
            if detail["detail_type"]=="salary_taxable_income": details_by_org[detail["org_code"]]+=detail["difference"]
        certificate_by_org, bank_by_org, bank_matches = _payment_totals(
            {code: org.full_name for code, org in orgs.items()}, bundle.certificates, bundle.bank)
        for org_code,org in sorted(orgs.items()):
            checks=[row for row in tax_rows if row["org_code"]==org_code]; occurrences=[row for row in occurrence_rows if row["org_code"]==org_code]
            declared_total=sum((row["declared_tax_amount"] or Decimal("0.00") for row in checks),Decimal("0.00")) if bundle.declarations.status not in {"missing","invalid"} else None
            balance_total=sum((row["closing_balance"] or Decimal("0.00") for row in checks),Decimal("0.00")) if bundle.balance.status not in {"missing","invalid"} else None
            scoped_total=sum((row["scoped_declared_tax_amount"] or Decimal("0.00") for row in checks),Decimal("0.00")) if bundle.declarations.status not in {"missing","invalid"} else None
            known_business = [row["business_tax_amount"] for row in checks if row["business_tax_amount"] is not None]
            business_total=sum(known_business, Decimal("0.00")) if known_business else None
            certificate=None if bundle.certificates.status in {"missing","invalid"} else certificate_by_org[org_code]
            bank=None if bundle.bank.status in {"missing","invalid"} else bank_by_org[org_code]
            diff6=sum((row["broker_occurrence_difference"] or Decimal("0.00") for row in occurrences),Decimal("0.00")) if bundle.broker.status not in {"missing","invalid"} else None; diff7=sum((row["declared_income_difference"] or Decimal("0.00") for row in occurrences),Decimal("0.00")) if bundle.declarations.status not in {"missing","invalid"} else None
            diffs=[subtract_nullable(declared_total,balance_total),subtract_nullable(scoped_total,business_total),details_by_org[org_code],subtract_nullable(declared_total,certificate),subtract_nullable(certificate,bank),diff6,diff7]
            summaries.append({"org_code":org_code,"org_name":org.org_name,"org_full_name":org.full_name,"declared_tax_amount":declared_total,"balance_tax_amount":balance_total,"difference_1":diffs[0],"scoped_declared_tax_amount":scoped_total,"payroll_business_tax_amount":business_total,"difference_2":diffs[1],"taxable_income_difference":details_by_org[org_code],"certificate_tax_amount":certificate,"difference_4":diffs[3],"bank_tax_amount":bank,"difference_5":diffs[4],"broker_occurrence_difference":diff6,"other_income_difference":diff7,"check_status":"difference" if any(has_difference(value) for value in diffs) else "missing_source" if any(value is None for value in diffs[:2]) else "ok"})
        declaration_summaries=[]
        for (org_code,declaration_type,item),value in summarize(bundle.declarations.rows).items(): declaration_summaries.append({"org_code":org_code,"org_name":getattr(orgs.get(org_code),"org_name",""),"declaration_type":declaration_type,"income_item":item,"person_count":len(value["person_count"]),"income_amount":value["income_amount"],"tax_amount":value["tax_amount"]})
        snapshots=[{"source_type":source.source_type,"status":source.status,"required":source.required,"source_kind":source.source_kind,"source_id":source.source_id,"source_ref":source.source_ref,"row_count":len(source.rows),"issues_json":source.issues} for source in sources]
        declaration_rows = json.loads(json.dumps([
            {"纳税人姓名": row.person_name, "身份证件号码": row.id_number, "所得项目": row.income_item,
             "收入": row.income_amount, "应补退税额": row.tax_amount, **row.raw_data,
             "org_code": row.org_code, "sheet_name": row.declaration_type, "tax_period": row.tax_period,
             "agent_name": row.withholding_agent_name, "agent_id": row.withholding_agent_taxpayer_id}
            for row in bundle.declarations.rows
        ], default=str))
        return {"sources":snapshots,"declaration_rows":declaration_rows,"declaration_summaries":declaration_summaries,"tax_checks":tax_rows,"occurrence_checks":occurrence_rows,"org_summaries":summaries,"details":details,"bank_matches":bank_matches,"missing_sources":[source.source_type for source in sources if source.required and source.status in {"missing","invalid"}],"stage":"post_payment" if bundle.certificates.status=="ready" and bundle.bank.status in {"ready","ready_empty"} else "pre_payment","data_status":"incomplete" if any(source.required and source.status in {"missing","invalid"} for source in sources) else "ready"}
