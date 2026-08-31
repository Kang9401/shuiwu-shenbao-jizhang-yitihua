from itertools import combinations
from decimal import Decimal

from ..constants import BANK_TOLERANCE


def find_subset_sum(values: list[Decimal], target: Decimal, tolerance: Decimal = BANK_TOLERANCE) -> list[int] | None:
    """Legacy-compatible deterministic subset search, bounded for desktop responsiveness."""
    for size in range(1, min(len(values), 12) + 1):
        for indexes in combinations(range(len(values)), size):
            if abs(sum((values[index] for index in indexes), Decimal("0.00")) - target) <= tolerance:
                return list(indexes)
    return None
