import re


def normalized_name(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def preferred_id_number(values) -> str:
    """Return a stable identity value, preferring an unmasked ID.

    The support platform can provide a masked ID in one source and the full
    ID in another.  Selecting from a set with ``next(iter(...))`` made the
    resulting natural key depend on hash iteration order and could produce
    duplicate rows across recalculations.  Keep the full value when it is
    available and otherwise choose the lexicographically first masked value.
    """
    candidates = sorted({str(value).strip() for value in values if value and str(value).strip()})
    if not candidates:
        return ""
    unmasked = [value for value in candidates if "*" not in value and "＊" not in value]
    return unmasked[0] if unmasked else candidates[0]


def employee_identity(employee_no: str | None, id_number: str | None, org_code: str, name: str, pair_index: int = 0) -> str:
    return (f"emp:{employee_no}" if employee_no else f"id:{id_number}" if id_number else f"name:{org_code}:{normalized_name(name)}:{pair_index}")


def customer_identity(id_number: str | None, org_code: str, name: str) -> str:
    return f"id:{id_number}" if id_number else f"customer:{org_code}:{normalized_name(name)}"
