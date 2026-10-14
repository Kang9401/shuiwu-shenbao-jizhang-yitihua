from collections import defaultdict
from decimal import Decimal
from .income_classification import income_category


def summarize(rows):
    grouped = defaultdict(lambda: {"person_count": set(), "income_amount": Decimal("0.00"), "tax_amount": Decimal("0.00")})
    for row in rows:
        key=(row.org_code,income_category(row.income_item, row.declaration_type),row.income_item)
        grouped[key]["person_count"].add(row.id_number or row.person_name)
        grouped[key]["income_amount"] += row.income_amount or Decimal("0.00")
        grouped[key]["tax_amount"] += row.tax_amount or Decimal("0.00")
    return grouped
