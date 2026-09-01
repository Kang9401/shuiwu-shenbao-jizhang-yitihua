from collections import defaultdict
from decimal import Decimal
from ..keys import customer_identity
from ..money import has_difference


def restricted_stock_details(rows, declarations):
    business=defaultdict(lambda: Decimal("0.00")); declared=defaultdict(lambda: Decimal("0.00")); ids=defaultdict(set); sales=defaultdict(lambda: Decimal("0.00")); securities=defaultdict(set)
    for row in rows: business[(row.org_code,row.customer_name)]+=abs(row.withheld_tax or Decimal("0.00")); ids[(row.org_code,row.customer_name)].add(row.id_number); sales[(row.org_code,row.customer_name)]+=row.sale_amount or Decimal("0.00"); securities[(row.org_code,row.customer_name)].add(row.security_name)
    for row in declarations:
        if "限售股" in row.income_item or "限售股" in row.declaration_type: declared[(row.org_code,row.person_name)]+=row.tax_amount or Decimal("0.00"); ids[(row.org_code,row.person_name)].add(row.id_number)
    output=[]
    for org,name in sorted(set(business)|set(declared)):
        difference=declared[(org,name)]-business[(org,name)]
        if has_difference(difference): output.append({"detail_type":"restricted_stock_tax","org_code":org,"name":name,"id_number":next(iter(ids[(org,name)]),""),"identity_key":customer_identity(next(iter(ids[(org,name)]),""),org,name),"source_amount":business[(org,name)],"target_amount":declared[(org,name)],"difference":difference,"auto_reason":f"限售股个税：业务 {business[(org,name)]:.2f}，申报 {declared[(org,name)]:.2f}，差异 {difference:.2f}","detail_json":{"security_names":sorted(item for item in securities[(org,name)] if item),"sale_amount":str(sales[(org,name)]),"business_tax_amount":str(business[(org,name)]),"declared_tax_amount":str(declared[(org,name)]),"id_numbers":sorted(item for item in ids[(org,name)] if item)}})
    return output
