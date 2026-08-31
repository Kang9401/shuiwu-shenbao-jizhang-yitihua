from collections import defaultdict
from decimal import Decimal
from ..keys import employee_identity
from ..money import has_difference


def salary_tax_details(salaries, declarations):
    payroll=defaultdict(lambda: Decimal("0.00")); declared=defaultdict(lambda: Decimal("0.00")); metadata={}
    for row in salaries:
        key=(row.org_code,row.person_name); payroll[key]+=row.pit_tax or Decimal("0.00"); metadata[key]=row
    for row in declarations:
        if "工资薪金" in row.income_item and "证券经纪" not in row.income_item:
            key=(row.org_code,row.person_name); declared[key]+=row.tax_amount or Decimal("0.00"); metadata.setdefault(key,row)
    output=[]
    for index,key in enumerate(sorted(set(payroll)|set(declared))):
        difference=declared[key]-payroll[key]
        if has_difference(difference):
            row=metadata[key]; output.append({"detail_type":"salary_tax","org_code":key[0],"name":key[1],"id_number":getattr(row,"id_number","") or "","identity_key":employee_identity(getattr(row,"employee_no","") or "",getattr(row,"id_number","") or "",key[0],key[1],index),"source_amount":payroll[key],"target_amount":declared[key],"difference":difference,"auto_reason":f"工资个人所得税 {payroll[key]:.2f}，申报税额 {declared[key]:.2f}，差异 {difference:.2f}"})
    return output
