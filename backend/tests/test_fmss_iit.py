from __future__ import annotations

import pytest
from types import SimpleNamespace

from app.api import fmss_iit
from app.integrations.fmss.branch_code import to_fmss_branch_code
from app.integrations.fmss.errors import FmssStateConflict, FmssTemplateChanged
from app.integrations.fmss.iit.schemas import FmssSheet
from app.integrations.fmss.session import fmss_session
from app.services.pit_fmss_mapper import PRE_HEADERS, PitFmssMapper
from app.services.pit_online_service import PitOnlineService


def _pre_sheets() -> list[FmssSheet]:
    return [FmssSheet(key=key, title=key, headers=headers) for key, headers in PRE_HEADERS.items()]


def test_pre_template_requires_all_eight_exact_ordered_headers():
    assert set(PitFmssMapper().validate_pre_template(_pre_sheets())) == set(PRE_HEADERS)
    invalid = _pre_sheets()
    invalid[0] = FmssSheet(key=invalid[0].key, title=invalid[0].title, headers=invalid[0].headers[:-1])
    with pytest.raises(FmssTemplateChanged):
        PitFmssMapper().validate_pre_template(invalid)


def test_local_branch_code_maps_to_fmss_without_changing_business_code():
    assert to_fmss_branch_code("17020") == "19020"
    assert to_fmss_branch_code("19020") == "19020"
    assert to_fmss_branch_code(" 17020 ") == "19020"


def test_online_declaration_uses_translated_fmss_branch_code(monkeypatch):
    calls = []

    class FakeClient:
        def declaration(self, branch_code, month, stage):
            calls.append((branch_code, month, stage))
            return {"document": {"id": 2, "status": "DRAFT"}}

    service = PitOnlineService(None, FakeClient())  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_context", lambda *_: (SimpleNamespace(code="17020"), SimpleNamespace(year=2026, month=7)))
    payload, status = service.query_declaration(1, 2, "pre_payment")
    assert status == "DRAFT"
    assert payload["document"]["id"] == 2
    assert calls == [("19020", "2026-07", "PRE")]


@pytest.mark.parametrize("state", ["NOT_SUBMITTED", "DRAFT", "RETURNED"])
def test_online_editable_states_allow_local_changes(monkeypatch, state):
    service = PitOnlineService(None)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "sync_workpaper", lambda _workpaper: {"status": state})
    service.enforce_editable(SimpleNamespace(platform_submission_id=None if state == "NOT_SUBMITTED" else "2"))


@pytest.mark.parametrize("state", ["REVIEWING", "APPROVED"])
def test_online_reviewed_states_lock_local_changes(monkeypatch, state):
    service = PitOnlineService(None)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "sync_workpaper", lambda _workpaper: {"status": state})
    with pytest.raises(FmssStateConflict, match="不能修改"):
        service.enforce_editable(SimpleNamespace(platform_submission_id="2"))


def test_missing_remote_state_keeps_linked_workpaper_locked(monkeypatch):
    service = PitOnlineService(None)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "sync_workpaper", lambda _workpaper: {"status": "NOT_SUBMITTED"})
    with pytest.raises(FmssStateConflict, match="保守锁定"):
        service.enforce_editable(SimpleNamespace(platform_submission_id="2"))


def test_withdraw_rechecks_draft_before_syncing(monkeypatch):
    calls = []

    class Client:
        def withdraw_iit_declaration(self, declaration_id):
            calls.append(declaration_id)

    service = PitOnlineService(None, Client())  # type: ignore[arg-type]
    workpaper = SimpleNamespace(platform_submission_id="19", company_id=1, period_id=2, stage="pre_payment")
    monkeypatch.setattr(service, "_assert_write_enabled", lambda _stage: None)
    monkeypatch.setattr(service, "query_declaration", lambda *_args: ({"document": {"status": "DRAFT"}}, "DRAFT"))
    monkeypatch.setattr(service, "sync_workpaper", lambda _workpaper: {"status": "DRAFT"})

    assert service.withdraw_workpaper(workpaper) == {"status": "DRAFT"}
    assert calls == ["19"]


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
