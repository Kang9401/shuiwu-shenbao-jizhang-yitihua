from decimal import Decimal
from ..keys import identity_key_text, resolve_identity_keys
from ..money import has_difference


def salary_taxable_income_details(salaries, declarations, identity_mappings=None):
    declaration_rows = [row for row in declarations if "工资薪金" in row.income_item and "证券经纪" not in row.income_item]
    salary_matches, declaration_matches = resolve_identity_keys(salaries, declaration_rows, identity_mappings)
    salary_key_map = {id(row): (row.org_code, match[0], match[1]) for row, match in zip(salaries, salary_matches)}
    declaration_key_map = {id(row): (row.org_code, match[0], match[1]) for row, match in zip(declaration_rows, declaration_matches)}
    def key_for(row):
        match = salary_key_map.get(id(row)) or declaration_key_map.get(id(row))
        return (match[1][1], match[1]) if match else (row.org_code, ("name", row.org_code, getattr(row, "person_name", ""), id(row)))

    grouped={}
    typed_payroll = any(getattr(row, "salary_kind", "") for row in salaries)
    supported_kinds = {"five_digit", "seven_digit", "headquarters"}
    def supported(row):
        return (not typed_payroll or row.salary_kind in supported_kinds) and not (
            row.salary_kind == "headquarters" and row.cumulative_taxable_income is None)
    excluded_keys = {
        key_for(row)
        for row in salaries
        if not supported(row)
    }
    for row in salaries:
        if not supported(row):
            continue
        grouped.setdefault(key_for(row), [[],[]])[0].append(row)
    for row in declarations:
        key = key_for(row)
        if key in excluded_keys and key not in grouped:
            continue
        if "工资薪金" in row.income_item and "证券经纪" not in row.income_item: grouped.setdefault(key, [[],[]])[1].append(row)
    output=[]
    for (org,identity),(payroll,declared) in sorted(grouped.items()):
        remaining=list(payroll); pairs=[]; unmatched_declarations=[]
        # Legacy pairing: consume all exact taxable-income matches first, then
        # pair the remaining records by their original order.
        for declaration in declared:
            match=next((item for item in remaining if abs((item.cumulative_taxable_income or Decimal("0"))-(declaration.cumulative_taxable_income or Decimal("0")))<=Decimal("0.01")),None)
            if match is not None:
                remaining.remove(match)
                pairs.append((match,declaration))
            else:
                unmatched_declarations.append(declaration)
        remaining_payroll = remaining
        remaining_declarations = unmatched_declarations
        pairs.extend((remaining_payroll[i], remaining_declarations[i]) for i in range(min(len(remaining_payroll), len(remaining_declarations))))
        pairs.extend((None, declaration) for declaration in remaining_declarations[len(remaining_payroll):])
        pairs.extend((item, None) for item in remaining_payroll[len(remaining_declarations):])
        for index,(pay,dec) in enumerate(pairs):
            source_value=pay.cumulative_taxable_income if pay else None
            target_value=dec.cumulative_taxable_income if dec else None
            source=source_value if source_value is not None else Decimal("0.00")
            target=target_value if target_value is not None else Decimal("0.00")
            difference=source-target
            if has_difference(difference):
                reference=pay or dec
                payroll_special=(pay.cumulative_special_deduction if pay else None) or Decimal("0.00")
                declared_special=(dec.cumulative_special_deduction if dec else None) or Decimal("0.00")
                additional_fields=("cumulative_child_education","cumulative_elderly_support","cumulative_housing_loan_interest","cumulative_housing_rent","cumulative_continuing_education","cumulative_infant_care","cumulative_personal_pension")
                additional_difference=sum(((getattr(pay, field, None) if pay else None) or Decimal("0.00")) - ((getattr(dec, field, None) if dec else None) or Decimal("0.00")) for field in additional_fields)
                payroll_other=(pay.cumulative_other_deduction if pay else None) or Decimal("0.00")
                declared_other=(dec.cumulative_other_deduction if dec else None) or Decimal("0.00")
                payroll_tax=(pay.pit_tax if pay else None) or Decimal("0.00")
                declared_tax=(dec.tax_amount if dec else None) or Decimal("0.00")
                match_status = next((value[2] for value in [declaration_key_map.get(id(dec)), salary_key_map.get(id(pay))] if value), "confirmed")
                reason = f"累计应纳税所得额：工资 {source:.2f}，申报 {target:.2f}，差异 {difference:.2f}"
                if match_status == "manual_review": reason += "；身份证脱敏且无法唯一确认，请人工判断"
                identity_mapping = None
                if match_status == "manual_confirmed" and pay and dec:
                    identity_mapping = {"payroll_org_code": pay.org_code, "payroll_name": pay.person_name,
                                        "declaration_org_code": dec.org_code, "declaration_name": dec.person_name,
                                        "declaration_id_number": dec.id_number}
                    reason += "；已按人工身份映射配对（保留双方原始机构及姓名）"
                output.append({"detail_type":"salary_taxable_income","org_code":org,"name":getattr(reference,"person_name","") or "","id_number":reference.id_number,"identity_key":identity_key_text(identity) + (f":pair-{index}" if index else ""),"source_amount":source_value,"target_amount":target_value,"difference":difference,"auto_reason":reason,"detail_json":{"declared_taxable_income":str(target_value) if target_value is not None else None,"payroll_taxable_income":str(source_value) if source_value is not None else None,"taxable_income_difference":str(difference),"specific_deduction_difference":str(payroll_special-declared_special),"special_additional_deduction_difference":str(additional_difference),"other_deduction_difference":str(payroll_other-declared_other),"housing_fund_adjustment":str(dec.housing_fund_adjustment) if dec and dec.housing_fund_adjustment is not None else None,"declaration_rate":dec.tax_rate if dec else "","payroll_tax":str(payroll_tax),"declared_tax":str(declared_tax),"tax_difference":str(payroll_tax-declared_tax),"identity_match_status":match_status,"manual_identity_mapping":identity_mapping}})
    return output
