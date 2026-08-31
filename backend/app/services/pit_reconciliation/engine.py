from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from .constants import OCCURRENCE_INCOME_TYPES, OCCURRENCE_SUBJECT_CODES, TAX_SUBJECT_CODES, TAX_SUBJECT_NAMES
from .money import add_nullable, has_difference, subtract_nullable
from .rules.bond_interest import bond_interest_details
from .rules.declaration_summary import summarize
from .rules.occurrence import calc_vat
from .rules.payment import find_subset_sum
from .rules.restricted_stock import restricted_stock_details
from .rules.salary_tax import salary_tax_details
from .rules.salary_taxable_income import salary_taxable_income_details
from .rules.tax_amount import declared_by_subject


class PitReconciliationEngine:
    """Pure PIT calculation engine. Its input and output contain no ORM objects."""
    def calculate(self, bundle):
        sources=[bundle.organizations,bundle.salary,bundle.declarations,bundle.balance,bundle.broker,bundle.bond_interest,bundle.restricted_stock,bundle.certificates,bundle.bank]
        source_map={source.source_type: source for source in sources}
        # Source adapters name their workflow internally; normalize public source names.
        source_map["broker"] = bundle.broker; source_map["bond_interest"] = bundle.bond_interest; source_map["restricted_stock"] = bundle.restricted_stock
        orgs={row.org_code: row for row in bundle.organizations.rows}
        for source in (bundle.salary,bundle.declarations,bundle.balance,bundle.broker,bundle.bond_interest,bundle.restricted_stock):
            for row in source.rows:
                code=getattr(row,"org_code","")
                if code and code not in orgs: orgs[code]=type("Org",(),{"org_code":code,"org_name":"","full_name":""})()
        balance=defaultdict(dict)
        for row in bundle.balance.rows: balance[row.org_code][row.subject_code]=row
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
                current=subtract_nullable(declared_value,item.credit_amount if item else Decimal("0.00")); cumulative=subtract_nullable(declared_value,item.closing_balance if item else Decimal("0.00")); business_diff=subtract_nullable(scoped_value,business_value)
                if status=="ok" and any(has_difference(value) for value in (current,cumulative,business_diff)): status="difference"
                tax_rows.append({"org_code":org_code,"org_name":org.org_name,"subject_code":subject,"subject_name":TAX_SUBJECT_NAMES[subject],"opening_balance":item.opening_balance if item else Decimal("0.00"),"debit_amount":item.debit_amount if item else Decimal("0.00"),"credit_amount":item.credit_amount if item else Decimal("0.00"),"closing_balance":item.closing_balance if item else Decimal("0.00"),"business_tax_amount":business_value,"declared_tax_amount":declared_value,"current_difference":current,"cumulative_difference":cumulative,"scoped_declared_tax_amount":scoped_value,"business_declared_difference":business_diff,"check_status":status})
            broker_gross=sum((item.gross_before_topup or Decimal("0.00") for item in bundle.broker.rows if item.org_code==org_code),Decimal("0.00")); broker_vat=sum((item.vat_amount or Decimal("0.00") for item in bundle.broker.rows if item.org_code==org_code),Decimal("0.00"))
            actual_by_item=defaultdict(lambda:Decimal("0.00"))
            for declaration in bundle.declarations.rows:
                if declaration.org_code==org_code: actual_by_item[declaration.income_item]+=declaration.income_amount or Decimal("0.00")
            for subject in OCCURRENCE_SUBJECT_CODES:
                item=balance[org_code].get(subject); occurrence=item.debit_amount if item else (None if bundle.balance.status in {"missing","invalid"} else Decimal("0.00")); income_type=OCCURRENCE_INCOME_TYPES[subject]
                broker_value=(broker_gross if subject=="45019006" else Decimal("0.00")) if bundle.broker.status not in {"missing","invalid"} else None
                broker_diff=subtract_nullable(broker_value,occurrence) if subject=="45019006" else Decimal("0.00")
                expected=occurrence if subject in {"21131042","21210012"} else subtract_nullable(broker_gross,broker_vat) if subject=="45019006" and broker_value is not None else subtract_nullable(occurrence,calc_vat(occurrence))
                actual=None if bundle.declarations.status in {"missing","invalid"} else actual_by_item[income_type]
                # Legacy repeats the broker declaration amount on both component rows.
                difference=subtract_nullable(actual,expected)
                status="invalid_source" if bundle.balance.status=="invalid" or bundle.declarations.status=="invalid" or (subject=="45019006" and bundle.broker.status=="invalid") else "missing_source" if bundle.balance.status=="missing" or bundle.declarations.status=="missing" or (subject=="45019006" and bundle.broker.status=="missing") else "difference" if has_difference(broker_diff) or has_difference(difference) else "ok"
                occurrence_rows.append({"org_code":org_code,"org_name":org.org_name,"subject_code":subject,"subject_name":subject,"income_type":income_type,"opening_balance":item.opening_balance if item else None,"debit_amount":item.debit_amount if item else None,"credit_amount":item.credit_amount if item else None,"closing_balance":item.closing_balance if item else None,"occurrence_amount":occurrence,"broker_payroll_amount":broker_value,"broker_occurrence_difference":broker_diff,"expected_declared_income":expected,"expected_income_description":income_type,"actual_declared_income":actual,"declared_income_difference":difference,"check_status":status})
        details=[]
        if bundle.salary.status=="ready" and bundle.declarations.status=="ready": details += salary_tax_details(bundle.salary.rows,bundle.declarations.rows)+salary_taxable_income_details(bundle.salary.rows,bundle.declarations.rows)
        if bundle.bond_interest.status=="ready" and bundle.declarations.status=="ready": details += bond_interest_details(bundle.bond_interest.rows,bundle.declarations.rows)
        if bundle.restricted_stock.status=="ready" and bundle.declarations.status=="ready": details += restricted_stock_details(bundle.restricted_stock.rows,bundle.declarations.rows)
        summaries=[]; bank_matches=[]; details_by_org=defaultdict(lambda:Decimal("0.00"))
        for detail in details:
            if detail["detail_type"]=="salary_taxable_income": details_by_org[detail["org_code"]]+=detail["difference"]
        certificate_by_org=defaultdict(lambda:Decimal("0.00"))
        if bundle.certificates.status in {"ready","ready_empty"}:
            for row in bundle.certificates.rows:
                if "个人所得税" in row.tax_type: certificate_by_org[row.org_code]+=row.amount or Decimal("0.00")
        used=set()
        bank_by_org=defaultdict(lambda:Decimal("0.00"))
        if bundle.bank.status in {"ready","ready_empty"}:
            candidates=[row for row in bundle.bank.rows if "税" in row.summary]
            candidates=candidates or bundle.bank.rows
            for org_code,target in certificate_by_org.items():
                indexes=find_subset_sum([abs(row.debit_amount or Decimal("0.00")) for row in candidates],target)
                if indexes:
                    for index in indexes:
                        if index in used: continue
                        used.add(index); row=candidates[index]; bank_by_org[org_code]+=abs(row.debit_amount or Decimal("0.00")); bank_matches.append({"org_code":org_code,"org_full_name":orgs.get(org_code).full_name if org_code in orgs else "","bank_account":row.bank_account,"transaction_time":row.transaction_time,"transaction_summary":row.summary,"debit_amount":abs(row.debit_amount or Decimal("0.00")),"source_batch_id":row.source_batch_id,"source_row_id":row.source_row_id})
        for org_code,org in sorted(orgs.items()):
            checks=[row for row in tax_rows if row["org_code"]==org_code]; occurrences=[row for row in occurrence_rows if row["org_code"]==org_code]
            declared_total=sum((row["declared_tax_amount"] or Decimal("0.00") for row in checks),Decimal("0.00")) if bundle.declarations.status not in {"missing","invalid"} else None
            balance_total=sum((row["credit_amount"] or Decimal("0.00") for row in checks),Decimal("0.00")) if bundle.balance.status not in {"missing","invalid"} else None
            scoped_total=sum((row["scoped_declared_tax_amount"] or Decimal("0.00") for row in checks),Decimal("0.00")) if bundle.declarations.status not in {"missing","invalid"} else None
            business_total=sum((row["business_tax_amount"] or Decimal("0.00") for row in checks),Decimal("0.00")) if all(row["business_tax_amount"] is not None for row in checks) else None
            certificate=None if bundle.certificates.status in {"missing","invalid"} else certificate_by_org[org_code]
            bank=None if bundle.bank.status in {"missing","invalid"} else bank_by_org[org_code]
            diff6=sum((row["broker_occurrence_difference"] or Decimal("0.00") for row in occurrences),Decimal("0.00")) if bundle.broker.status not in {"missing","invalid"} else None; diff7=sum((row["declared_income_difference"] or Decimal("0.00") for row in occurrences),Decimal("0.00")) if bundle.declarations.status not in {"missing","invalid"} else None
            diffs=[subtract_nullable(declared_total,balance_total),subtract_nullable(scoped_total,business_total),details_by_org[org_code],subtract_nullable(declared_total,certificate),subtract_nullable(certificate,bank),diff6,diff7]
            summaries.append({"org_code":org_code,"org_name":org.org_name,"org_full_name":org.full_name,"declared_tax_amount":declared_total,"balance_tax_amount":balance_total,"difference_1":diffs[0],"scoped_declared_tax_amount":scoped_total,"payroll_business_tax_amount":business_total,"difference_2":diffs[1],"taxable_income_difference":details_by_org[org_code],"certificate_tax_amount":certificate,"difference_4":diffs[3],"bank_tax_amount":bank,"difference_5":diffs[4],"broker_occurrence_difference":diff6,"other_income_difference":diff7,"check_status":"difference" if any(has_difference(value) for value in diffs) else "missing_source" if any(value is None for value in diffs[:2]) else "ok"})
        declaration_summaries=[]
        for (org_code,declaration_type,item),value in summarize(bundle.declarations.rows).items(): declaration_summaries.append({"org_code":org_code,"org_name":getattr(orgs.get(org_code),"org_name",""),"declaration_type":declaration_type,"income_item":item,"person_count":len(value["person_count"]),"income_amount":value["income_amount"],"tax_amount":value["tax_amount"]})
        snapshots=[{"source_type":source.source_type,"status":source.status,"required":source.required,"source_kind":source.source_kind,"source_id":source.source_id,"source_ref":source.source_ref,"row_count":len(source.rows),"issues_json":source.issues} for source in sources]
        return {"sources":snapshots,"declaration_summaries":declaration_summaries,"tax_checks":tax_rows,"occurrence_checks":occurrence_rows,"org_summaries":summaries,"details":details,"bank_matches":bank_matches,"missing_sources":[source.source_type for source in sources if source.required and source.status in {"missing","invalid"}],"stage":"post_payment" if bundle.certificates.status=="ready" and bundle.bank.status in {"ready","ready_empty"} else "pre_payment","data_status":"incomplete" if any(source.required and source.status in {"missing","invalid"} for source in sources) else "ready"}
