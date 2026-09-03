from collections import defaultdict
from decimal import Decimal
from ..keys import customer_identity
from ..money import has_difference


def bond_interest_details(rows, declarations):
    business=defaultdict(lambda: Decimal("0.00")); interest=defaultdict(lambda: Decimal("0.00")); declared=defaultdict(lambda: Decimal("0.00")); ids=defaultdict(set)
    for row in rows:
        key=(row.org_code,row.customer_name)
        business[key] += abs(row.withheld_tax) if row.withheld_tax is not None else Decimal("0.00")
        interest[key] += row.interest_amount if row.interest_amount is not None else Decimal("0.00")
        ids[key].add(row.id_number)
    for row in declarations:
        if "其他利息、股息、红利所得" in row.income_item: declared[(row.org_code,row.person_name)]+=row.tax_amount or Decimal("0.00"); ids[(row.org_code,row.person_name)].add(row.id_number)
    output=[]
    for org,name in sorted(set(business)|set(declared)):
        difference=declared[(org,name)]-business[(org,name)]
        if has_difference(difference): output.append({"detail_type":"bond_interest_tax","org_code":org,"name":name,"id_number":next(iter(ids[(org,name)]),""),"identity_key":customer_identity(next(iter(ids[(org,name)]),""),org,name),"source_amount":business[(org,name)],"target_amount":declared[(org,name)],"difference":difference,"auto_reason":f"客户利息个税：业务 {business[(org,name)]:.2f}，申报 {declared[(org,name)]:.2f}，差异 {difference:.2f}","detail_json":{"interest_amount":str(interest[(org,name)]),"business_tax_amount":str(business[(org,name)]),"declared_tax_amount":str(declared[(org,name)]),"id_numbers":sorted(item for item in ids[(org,name)] if item),"same_name_merged":len(ids[(org,name)])>1}})
    return output
