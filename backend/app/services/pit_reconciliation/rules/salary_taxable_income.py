from decimal import Decimal
from ..keys import employee_identity
from ..money import has_difference


def salary_taxable_income_details(salaries, declarations):
    grouped={}
    for row in salaries: grouped.setdefault((row.org_code,row.person_name), [[],[]])[0].append(row)
    for row in declarations:
        if "工资薪金" in row.income_item and "证券经纪" not in row.income_item: grouped.setdefault((row.org_code,row.person_name), [[],[]])[1].append(row)
    output=[]
    for (org,name),(payroll,declared) in sorted(grouped.items()):
        remaining=list(payroll); pairs=[]; unmatched_declarations=[]
        # Pair all exact taxable-income matches before processing any unmatched
        # declaration.  This prevents input row order from consuming a payroll
        # row that has an exact same-name match later in the declaration file.
        for declaration in declared:
            match=next((item for item in remaining if abs((item.cumulative_taxable_income or Decimal("0"))-(declaration.cumulative_taxable_income or Decimal("0")))<=Decimal("0.01")),None)
            if match is not None:
                remaining.remove(match)
                pairs.append((match,declaration))
            else:
                unmatched_declarations.append(declaration)
        pairs.extend((None,declaration) for declaration in unmatched_declarations)
        pairs.extend((item,None) for item in remaining)
        for index,(pay,dec) in enumerate(pairs):
            source=(pay.cumulative_taxable_income if pay else None) or Decimal("0.00")
            target=(dec.cumulative_taxable_income if dec else None) or Decimal("0.00")
            difference=source-target
            if has_difference(difference):
                reference=pay or dec
                payroll_special=(pay.cumulative_special_deduction if pay else None) or Decimal("0.00")
                declared_special=(dec.cumulative_special_deduction if dec else None) or Decimal("0.00")
                additional_fields=("cumulative_child_education","cumulative_elderly_support","cumulative_housing_loan_interest","cumulative_housing_rent","cumulative_continuing_education","cumulative_infant_care")
                additional_difference=sum(((getattr(pay, field, None) if pay else None) or Decimal("0.00")) - ((getattr(dec, field, None) if dec else None) or Decimal("0.00")) for field in additional_fields)
                payroll_other=(pay.cumulative_other_deduction if pay else None) or Decimal("0.00")
                declared_other=(dec.cumulative_other_deduction if dec else None) or Decimal("0.00")
                payroll_tax=(pay.pit_tax if pay else None) or Decimal("0.00")
                declared_tax=(dec.tax_amount if dec else None) or Decimal("0.00")
                output.append({"detail_type":"salary_taxable_income","org_code":org,"name":name,"id_number":reference.id_number,"identity_key":employee_identity(getattr(reference,"employee_no","") or "",reference.id_number,org,name,index),"source_amount":source,"target_amount":target,"difference":difference,"auto_reason":f"累计应纳税所得额：工资 {source:.2f}，申报 {target:.2f}，差异 {difference:.2f}","detail_json":{"declared_taxable_income":str(target),"payroll_taxable_income":str(source),"taxable_income_difference":str(difference),"specific_deduction_difference":str(payroll_special-declared_special),"special_additional_deduction_difference":str(additional_difference),"other_deduction_difference":str(payroll_other-declared_other),"declaration_rate":dec.tax_rate if dec else "","payroll_tax":str(payroll_tax),"declared_tax":str(declared_tax),"tax_difference":str(declared_tax-payroll_tax)}})
    return output
