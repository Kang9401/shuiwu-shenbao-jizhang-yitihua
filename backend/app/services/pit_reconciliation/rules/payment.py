from decimal import Decimal

from ..constants import BANK_TOLERANCE


def find_subset_sum(values: list[Decimal], target: Decimal, tolerance: Decimal = BANK_TOLERANCE) -> list[int] | None:
    """Find a deterministic non-negative payment subset without combinatorial blowup.

    Bank amounts are represented in cents, so a dynamic-programming sum table
    is exact and preserves the legacy tolerance while remaining responsive for
    large statements and no-solution organizations.
    """
    if target < 0:
        return None
    scale = Decimal("0.01")
    cents = [int((value or Decimal("0.00")).quantize(scale) * 100) for value in values]
    target_cents = int(target.quantize(scale) * 100)
    tolerance_cents = max(0, int(tolerance.quantize(scale) * 100))
    if target_cents == 0:
        return []
    sums: dict[int, list[int]] = {0: []}
    upper = target_cents + tolerance_cents
    for index, amount in enumerate(cents):
        if amount <= 0:
            continue
        for subtotal, indexes in list(sums.items()):
            candidate = subtotal + amount
            if candidate > upper or candidate in sums:
                continue
            sums[candidate] = [*indexes, index]
        for candidate in range(max(0, target_cents - tolerance_cents), upper + 1):
            if candidate in sums:
                return sums[candidate]
    return None
