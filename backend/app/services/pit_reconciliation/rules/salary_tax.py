from collections import defaultdict
from decimal import Decimal
from ..keys import employee_identity
from ..money import has_difference


def salary_tax_details(salaries, declarations):
    payroll=defaultdict(lambda: Decimal("0.00")); declared=defaultdict(lambda: Decimal("0.00")); metadata={}
    comparison_fields=(
        ("累计减除费用", "cumulative_basic_deduction"), ("专项扣除", "cumulative_special_deduction"),
        ("子女教育", "cumulative_child_education"), ("赡养老人", "cumulative_elderly_support"),
        ("住房贷款利息", "cumulative_housing_loan_interest"), ("住房租金", "cumulative_housing_rent"),
        ("继续教育", "cumulative_continuing_education"), ("3岁以下婴幼儿照护", "cumulative_infant_care"),
        ("个人养老金", "cumulative_personal_pension"), ("其他扣除", "cumulative_other_deduction"),
    )
    comparison=defaultdict(lambda: {key: [Decimal("0.00"), Decimal("0.00")] for _, key in comparison_fields})
    for row in salaries:
        key=(row.org_code,row.person_name); payroll[key]+=row.pit_tax or Decimal("0.00"); metadata[key]=row
        for _, field in comparison_fields: comparison[key][field][0] += getattr(row,field,None) or Decimal("0.00")
    for row in declarations:
        if "工资薪金" in row.income_item and "证券经纪" not in row.income_item:
            key=(row.org_code,row.person_name); declared[key]+=row.tax_amount or Decimal("0.00"); metadata.setdefault(key,row)
            for _, field in comparison_fields: comparison[key][field][1] += getattr(row,field,None) or Decimal("0.00")
    output=[]
    for index,key in enumerate(sorted(set(payroll)|set(declared))):
        difference=declared[key]-payroll[key]
        if has_difference(difference):
            row=metadata[key]
            items=[]
            for name, field in comparison_fields:
                payroll_amount, declaration_amount=comparison[key][field]
                items.append({"name":name,"payroll_amount":str(payroll_amount),"declaration_amount":str(declaration_amount),"difference":str(payroll_amount-declaration_amount),"tax_rate":"","tax_effect":""})
            output.append({"detail_type":"salary_tax","org_code":key[0],"name":key[1],"id_number":getattr(row,"id_number","") or "","identity_key":employee_identity(getattr(row,"employee_no","") or "",getattr(row,"id_number","") or "",key[0],key[1],index),"source_amount":payroll[key],"target_amount":declared[key],"difference":difference,"auto_reason":f"工资个人所得税 {payroll[key]:.2f}，申报税额 {declared[key]:.2f}，差异 {difference:.2f}","detail_json":{"payroll_tax_amount":str(payroll[key]),"declared_tax_amount":str(declared[key]),"comparison_items":items}})
    return output
