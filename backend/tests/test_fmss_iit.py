from __future__ import annotations

import pytest

from app.api import fmss_iit
from app.integrations.fmss.errors import FmssTemplateChanged
from app.integrations.fmss.iit.schemas import FmssSheet
from app.integrations.fmss.session import fmss_session
from app.services.pit_fmss_mapper import PRE_HEADERS, PitFmssMapper


def _pre_sheets() -> list[FmssSheet]:
    return [FmssSheet(key=key, title=key, headers=headers) for key, headers in PRE_HEADERS.items()]


def test_pre_template_requires_all_eight_exact_ordered_headers():
    assert set(PitFmssMapper().validate_pre_template(_pre_sheets())) == set(PRE_HEADERS)
    invalid = _pre_sheets()
    invalid[0] = FmssSheet(key=invalid[0].key, title=invalid[0].title, headers=invalid[0].headers[:-1])
    with pytest.raises(FmssTemplateChanged):
        PitFmssMapper().validate_pre_template(invalid)


def test_sheet_rows_are_ordered_not_header_keyed_for_duplicate_post_headers():
    headers = ("机构代码", "差异原因11", "差异原因11")
    row = ["17020", "申报表原因", "银行流水原因"]
    assert list(enumerate(zip(headers, row))) == [
        (0, ("机构代码", "17020")),
        (1, ("差异原因11", "申报表原因")),
        (2, ("差异原因11", "银行流水原因")),
    ]


def test_fmss_session_validation_reads_sheets_without_exposing_token(monkeypatch):
    calls: list[str] = []

    class FakeClient:
        def sheets(self, stage: str):
            calls.append(f"sheets:{stage}")
            return [{"key": "iit_pre_tax_summary"}]

    fmss_session.connect("token-for-test-only", "test-user")
    monkeypatch.setattr(fmss_iit, "FmssClient", FakeClient)
    try:
        result = fmss_iit.session_state(validate=True)
    finally:
        fmss_session.clear()

    assert result == {
        "connected": True,
        "environment": "dev",
        "username": None,
        "displayName": None,
    }
    assert calls == ["sheets:PRE"]


def test_fmss_session_without_token_never_exposes_secret_fields():
    fmss_session.clear()
    assert fmss_iit.session_state() == {
        "connected": False,
        "environment": "dev",
        "username": None,
        "displayName": None,
    }
