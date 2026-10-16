from collections import defaultdict
from decimal import Decimal
from ..keys import identity_key_text, resolve_identity_keys
from ..money import has_difference


def salary_tax_details(salaries, declarations, identity_mappings=None):
    payroll=defaultdict(lambda: Decimal("0.00")); declared=defaultdict(lambda: Decimal("0.00")); metadata={}
    comparison_fields=(
        ("累计减除费用", "cumulative_basic_deduction"), ("专项扣除", "cumulative_special_deduction"),
        ("子女教育", "cumulative_child_education"), ("赡养老人", "cumulative_elderly_support"),
        ("住房贷款利息", "cumulative_housing_loan_interest"), ("住房租金", "cumulative_housing_rent"),
        ("继续教育", "cumulative_continuing_education"), ("3岁以下婴幼儿照护", "cumulative_infant_care"),
        ("个人养老金", "cumulative_personal_pension"), ("其他扣除", "cumulative_other_deduction"),
    )
    comparison=defaultdict(lambda: {key: [Decimal("0.00"), Decimal("0.00")] for _, key in comparison_fields})
    salary_matches, declaration_matches = resolve_identity_keys(salaries, [row for row in declarations if "工资薪金" in row.income_item and "证券经纪" not in row.income_item], identity_mappings)
    rates = defaultdict(set)
    mapped_sources = defaultdict(list)
    statuses = {}
    for row, match in zip(salaries, salary_matches):
        key=(match[0][1], match[0]); statuses[key] = match[1]; payroll[key]+=row.pit_tax or Decimal("0.00"); metadata[key]=row
        for _, field in comparison_fields: comparison[key][field][0] += getattr(row,field,None) or Decimal("0.00")
    for row, match in zip([row for row in declarations if "工资薪金" in row.income_item and "证券经纪" not in row.income_item], declaration_matches):
        key=(match[0][1], match[0]); declared[key]+=row.tax_amount or Decimal("0.00"); metadata.setdefault(key,row)
        if statuses.get(key) != "manual_confirmed": statuses[key] = match[1]
        if match[1] == "manual_confirmed":
            pay = metadata[key]
            mapped_sources[key].append({"payroll_org_code": pay.org_code, "payroll_name": pay.person_name,
                                       "declaration_org_code": row.org_code, "declaration_name": row.person_name,
                                       "declaration_id_number": row.id_number})
        if row.tax_rate not in (None, ""): rates[key].add(str(row.tax_rate))
        for _, field in comparison_fields: comparison[key][field][1] += getattr(row,field,None) or Decimal("0.00")
    output=[]
    for key in sorted(set(payroll)|set(declared)):
        difference=declared[key]-payroll[key]
        if has_difference(difference):
            row=metadata[key]
            items=[]
            for name, field in comparison_fields:
                payroll_amount, declaration_amount=comparison[key][field]
                items.append({"name":name,"payroll_amount":str(payroll_amount),"declaration_amount":str(declaration_amount),"difference":str(payroll_amount-declaration_amount),"tax_rate":" / ".join(sorted(rates[key])),"tax_effect":""})
            manual = statuses.get(key) == "manual_review"
            reason = f"工资个人所得税 {payroll[key]:.2f}，申报税额 {declared[key]:.2f}，差异 {difference:.2f}"
            if manual: reason += "；身份证脱敏且无法唯一确认，请人工判断"
            if mapped_sources[key]: reason += "；已按人工身份映射配对（保留双方原始机构及姓名）"
            output.append({"detail_type":"salary_tax","org_code":key[0],"name":getattr(row,"person_name","") or "","id_number":getattr(row,"id_number","") or "","identity_key":identity_key_text(key[1]),"source_amount":payroll[key],"target_amount":declared[key],"difference":difference,"auto_reason":reason,"detail_json":{"payroll_tax_amount":str(payroll[key]),"declared_tax_amount":str(declared[key]),"comparison_items":items,"identity_match_status":statuses.get(key, "confirmed"),"manual_identity_mappings":mapped_sources[key]}})
    return output
