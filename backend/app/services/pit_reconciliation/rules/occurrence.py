from decimal import Decimal, ROUND_HALF_UP
from ..constants import VAT_RATE, VAT_THRESHOLD


def calc_vat(amount: Decimal | None) -> Decimal | None:
    if amount is None: return None
    if amount < VAT_THRESHOLD: return Decimal("0.00")
    return (amount / (Decimal("1.00") + VAT_RATE) * VAT_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
