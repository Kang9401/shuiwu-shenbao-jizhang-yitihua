from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .constants import TOLERANCE

ZERO = Decimal("0.00")


def to_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    result = money_or_none(value)
    return default if result is None else result


def money_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    try:
        return Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def subtract_nullable(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return None if left is None or right is None else (left - right).quantize(Decimal("0.01"))


def add_nullable(*values: Decimal | None) -> Decimal | None:
    return None if any(value is None for value in values) else sum(values, ZERO).quantize(Decimal("0.01"))


def is_zero(value: Decimal | None, tolerance: Decimal = TOLERANCE) -> bool:
    return value is not None and abs(value) <= tolerance


def has_difference(value: Decimal | None, tolerance: Decimal = TOLERANCE) -> bool:
    return value is not None and abs(value) > tolerance
