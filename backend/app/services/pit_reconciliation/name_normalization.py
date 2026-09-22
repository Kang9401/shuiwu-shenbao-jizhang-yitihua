from __future__ import annotations

import re


_INVISIBLE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_WHITESPACE = re.compile(r"[\s\u00a0\u3000]+")


def normalize_organization_name(value: object) -> str:
    """Create a matching key for organization names extracted from local data or PDFs."""
    text = "" if value is None else str(value)
    return _WHITESPACE.sub("", _INVISIBLE.sub("", text))
