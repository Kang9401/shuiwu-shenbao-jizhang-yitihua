from decimal import Decimal
from ..keys import employee_identity
from ..money import has_difference


def salary_taxable_income_details(salaries, declarations):
    grouped={}
    typed_payroll = any(getattr(row, "salary_kind", "") for row in salaries)
    supported_kinds = {"five_digit", "seven_digit"}
    excluded_keys = {
        (row.org_code, row.person_name)
        for row in salaries
        if typed_payroll and getattr(row, "salary_kind", "") not in supported_kinds
    }
    for row in salaries:
        if typed_payroll and getattr(row, "salary_kind", "") not in supported_kinds:
            continue
        grouped.setdefault((row.org_code,row.person_name), [[],[]])[0].append(row)
    for row in declarations:
        key = (row.org_code, row.person_name)
        if key in excluded_keys and key not in grouped:
            continue
        if "工资薪金" in row.income_item and "证券经纪" not in row.income_item: grouped.setdefault(key, [[],[]])[1].append(row)
    output=[]
    for (org,name),(payroll,declared) in sorted(grouped.items()):
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
                output.append({"detail_type":"salary_taxable_income","org_code":org,"name":name,"id_number":reference.id_number,"identity_key":employee_identity(getattr(reference,"employee_no","") or "",reference.id_number,org,name,index),"source_amount":source_value,"target_amount":target_value,"difference":difference,"auto_reason":f"累计应纳税所得额：工资 {source:.2f}，申报 {target:.2f}，差异 {difference:.2f}","detail_json":{"declared_taxable_income":str(target_value) if target_value is not None else None,"payroll_taxable_income":str(source_value) if source_value is not None else None,"taxable_income_difference":str(difference),"specific_deduction_difference":str(payroll_special-declared_special),"special_additional_deduction_difference":str(additional_difference),"other_deduction_difference":str(payroll_other-declared_other),"housing_fund_adjustment":str(dec.housing_fund_adjustment) if dec and dec.housing_fund_adjustment is not None else None,"declaration_rate":dec.tax_rate if dec else "","payroll_tax":str(payroll_tax),"declared_tax":str(declared_tax),"tax_difference":str(payroll_tax-declared_tax)}})
    return output
