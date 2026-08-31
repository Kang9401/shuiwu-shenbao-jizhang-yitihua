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
        remaining=list(payroll); pairs=[]
        # The exact-income first pass preserves legacy same-name pairing semantics.
        for declaration in declared:
            match=next((item for item in remaining if abs((item.cumulative_taxable_income or Decimal("0"))-(declaration.cumulative_taxable_income or Decimal("0")))<=Decimal("0.01")),None)
            if match is not None: remaining.remove(match); pairs.append((match,declaration))
            else: pairs.append((None,declaration))
        pairs.extend((item,None) for item in remaining)
        for index,(pay,dec) in enumerate(pairs):
            source=pay.cumulative_taxable_income if pay else Decimal("0.00"); target=dec.cumulative_taxable_income if dec else Decimal("0.00"); source=source or Decimal("0.00"); target=target or Decimal("0.00"); difference=source-target
            if has_difference(difference):
                reference=pay or dec; output.append({"detail_type":"salary_taxable_income","org_code":org,"name":name,"id_number":reference.id_number,"identity_key":employee_identity(getattr(reference,"employee_no","") or "",reference.id_number,org,name,index),"source_amount":source,"target_amount":target,"difference":difference,"auto_reason":f"累计应纳税所得额：工资 {source:.2f}，申报 {target:.2f}，差异 {difference:.2f}","detail_json":{"declared_taxable_income":str(target),"payroll_taxable_income":str(source),"taxable_income_difference":str(difference)}})
    return output
