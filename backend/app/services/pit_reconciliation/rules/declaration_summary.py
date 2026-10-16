from collections import defaultdict
from decimal import Decimal
from .income_classification import income_category


def summarize(rows):
    grouped = defaultdict(lambda: {"person_count": 0, "income_amount": Decimal("0.00"), "tax_amount": Decimal("0.00")})
    for row in rows:
        key=(row.org_code,income_category(row.income_item, row.declaration_type),row.income_item)
        # “填写人次” counts business declaration rows, not distinct people.
        grouped[key]["person_count"] += 1
        grouped[key]["income_amount"] += row.income_amount or Decimal("0.00")
        grouped[key]["tax_amount"] += row.tax_amount or Decimal("0.00")
    return grouped
