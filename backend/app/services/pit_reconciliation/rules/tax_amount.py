from decimal import Decimal
from ..constants import TAX_SUBJECT_CODES


def declared_by_subject(rows, org_code):
    values={code: Decimal("0.00") for code in TAX_SUBJECT_CODES}; scoped=values.copy()
    for row in rows:
        if row.org_code != org_code: continue
        item=row.income_item or ""; kind=row.declaration_type or ""; tax=row.tax_amount or Decimal("0.00")
        if "证券经纪人佣金收入" in item: values["21510016"] += tax; scoped["21510016"] += tax
        elif "限售股" in item or "限售股" in kind: values["21510009"] += tax; scoped["21510009"] += tax
        elif "其他利息、股息、红利所得" in item: values["21510008"] += tax; scoped["21510008"] += tax
        elif "证券经纪" not in item: values["21510006"] += tax; scoped["21510006"] += tax
    return values, scoped
