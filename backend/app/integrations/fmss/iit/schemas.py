from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FmssSheet:
    key: str
    title: str
    headers: tuple[str, ...]

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> "FmssSheet":
        headers = value.get("headers")
        if not isinstance(headers, list) or not all(isinstance(header, str) for header in headers):
            raise ValueError("FMSS工作表表头格式异常")
        return cls(str(value.get("key", "")), str(value.get("title", "")), tuple(headers))
