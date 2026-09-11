import re


def normalized_name(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "").upper()


def employee_identity(employee_no: str | None, id_number: str | None, org_code: str, name: str, pair_index: int = 0) -> str:
    return (f"emp:{employee_no}" if employee_no else f"id:{id_number}" if id_number else f"name:{org_code}:{normalized_name(name)}:{pair_index}")


def customer_identity(id_number: str | None, org_code: str, name: str) -> str:
    return f"id:{id_number}" if id_number else f"customer:{org_code}:{normalized_name(name)}"
