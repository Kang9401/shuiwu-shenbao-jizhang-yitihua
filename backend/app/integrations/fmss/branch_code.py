from __future__ import annotations


def to_fmss_branch_code(code: str) -> str:
    """Translate a local branch code to the corresponding FMSS code."""
    value = str(code or "").strip()
    return f"19{value[2:]}" if value.startswith("17") else value
