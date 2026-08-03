from __future__ import annotations

from contextvars import ContextVar


_company_id: ContextVar[int | None] = ContextVar("company_id", default=None)


def current_company_id(*, default: int | None = 1) -> int | None:
    value = _company_id.get()
    return default if value is None else value


def set_company_id(company_id: int):
    return _company_id.set(company_id)


def reset_company_id(token) -> None:
    _company_id.reset(token)

