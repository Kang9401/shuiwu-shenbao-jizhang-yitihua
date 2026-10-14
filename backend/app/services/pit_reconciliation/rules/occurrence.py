from decimal import Decimal, ROUND_HALF_UP
from ..constants import VAT_RATE, VAT_THRESHOLD
from ..money import subtract_nullable


def expected_income(subject, occurrence, broker_gross, broker_vat):
    if subject in {"21131042", "21210012"}:
        return occurrence, "科目余额表当期发生额"
    if subject == "45019006":
        return subtract_nullable(broker_gross, broker_vat), "经纪人工资表应发金额（补足前） - 增值税"
    return subtract_nullable(occurrence, calc_vat(occurrence)), "科目余额表当期发生额 - 增值税"


def calc_vat(amount: Decimal | None) -> Decimal | None:
    if amount is None: return None
    if amount < VAT_THRESHOLD: return Decimal("0.00")
    return (amount / (Decimal("1.00") + VAT_RATE) * VAT_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
