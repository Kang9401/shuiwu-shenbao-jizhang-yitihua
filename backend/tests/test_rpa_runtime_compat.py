from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.rpa.extensions.etax_runtime_compat import ensure_withholding_page


class CandidatePage:
    def __init__(self, url: str):
        self.url = url
        self.front = False

    def bring_to_front(self):
        self.front = True


class HiddenEntry:
    @property
    def first(self):
        return self

    def filter(self, **_kwargs):
        return SimpleNamespace(count=lambda: 0)

    def count(self):
        return 1


def test_compat_reuses_existing_withholding_tab():
    current = CandidatePage("https://etax.chinatax.gov.cn/")
    withholding = CandidatePage("https://etax.chinatax.gov.cn/withholding/index.html#/home")
    current.context = SimpleNamespace(pages=[current, withholding])

    assert ensure_withholding_page(current) is withholding
    assert withholding.front is True


def test_compat_explains_hidden_unit_tax_entry():
    current = CandidatePage("https://etax.chinatax.gov.cn/")
    current.context = SimpleNamespace(pages=[current])
    current.locator = lambda *_args, **_kwargs: HiddenEntry()

    with pytest.raises(RuntimeError, match="当前登录身份未开放.*单位办税"):
        ensure_withholding_page(current)
