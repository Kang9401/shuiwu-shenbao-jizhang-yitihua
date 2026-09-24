from __future__ import annotations

import httpx
import pytest

from app.integrations.fmss.browser_auth import FmssBrowserAuth
from app.integrations.fmss.client import FmssClient
from app.integrations.fmss.errors import FmssApiError
from app.integrations.fmss.session import FmssSession, fmss_session


def _client() -> FmssClient:
    session = FmssSession()
    session.connect("token-for-test-only", "reviewer-test")
    return FmssClient(session)


def test_import_uses_real_multipart_fields_and_post_stage(tmp_path, monkeypatch):
    file_path = tmp_path / "fmss.xlsx"
    file_path.write_bytes(b"xlsx")
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return httpx.Response(200, json={"code": 200, "msg": "操作成功", "data": {"documents": [], "sheets": {}, "totalImported": 0}}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    _client().import_iit_workbook("19020", "2026-07", "POST", file_path)
    assert captured["method"] == "POST"
    assert captured["data"] == {"branchCode": "19020", "month": "2026-07", "stage": "POST"}
    assert "file" in captured["files"]


def test_attachment_upload_can_preserve_original_filename(tmp_path, monkeypatch):
    file_path = tmp_path / "stored-uuid.pdf"
    file_path.write_bytes(b"pdf")
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200, json={"code": 200, "msg": "操作成功", "data": {"fileId": 26}}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    _client().upload_iit_attachment("19020", "2026-07", "POST", file_path, file_name="17020-202607综合所得.pdf")
    assert captured["files"]["file"][0] == "17020-202607综合所得.pdf"
    assert "Content-Type" not in captured["headers"]


def test_attachment_upload_uses_post_multipart_fields(tmp_path, monkeypatch):
    file_path = tmp_path / "certificate.pdf"
    file_path.write_bytes(b"pdf")
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return httpx.Response(200, json={"code": 200, "msg": "操作成功", "data": {"fileId": 26}}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    assert _client().upload_iit_attachment("19020", "2026-07", "POST", file_path)["fileId"] == 26
    assert captured["method"] == "POST"
    assert captured["data"] == {"branchCode": "19020", "month": "2026-07", "stage": "POST"}
    assert "file" in captured["files"]


def test_submit_and_decision_use_json_and_post_is_not_retried(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, kwargs))
        if method == "POST":
            return httpx.Response(200, json={"code": 200, "msg": "操作成功", "data": 8}, request=httpx.Request(method, url))
        return httpx.Response(200, json={"code": 200, "msg": "操作成功", "data": {}}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    client = _client()
    client.submit_iit_declaration(2, "LIUWT")
    client.decide_iit_declaration(2, False, "退回原因")
    assert calls[0][1]["json"] == {"id": 2, "reviewer": "LIUWT"}
    assert calls[1][1]["json"] == {"id": 2, "pass": False, "comment": "退回原因"}

    def timeout_request(*_args, **_kwargs):
        raise httpx.ReadTimeout("unknown result")

    monkeypatch.setattr(httpx, "request", timeout_request)
    with pytest.raises(FmssApiError):
        client.submit_iit_declaration(2, "LIUWT")


def test_withdraw_uses_single_post_without_retry(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, json={"code": 200, "msg": "操作成功", "data": {}}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", fake_request)
    _client().withdraw_iit_declaration(19)
    assert len(calls) == 1
    assert calls[0][0] == "POST"
    assert calls[0][1].endswith("/iit/withdraw/19")


def test_fmss_browser_reads_only_matching_admin_token():
    class FakeContext:
        def cookies(self, _url):
            return [
                {"name": "Other", "domain": "fmssdev.gf.com.cn", "value": "ignored"},
                {"name": "Admin-Token", "domain": "testoauth2.gf.com.cn", "value": "wrong-host"},
                {"name": "Admin-Token", "domain": ".fmssdev.gf.com.cn", "value": "fake-admin-token"},
            ]

    assert FmssBrowserAuth()._read_admin_token(FakeContext()) == "fake-admin-token"


def test_fmss_browser_open_is_idempotent():
    auth = FmssBrowserAuth()

    class ActiveThread:
        def is_alive(self):
            return True

    auth._status = "waiting_login"
    auth._watch_thread = ActiveThread()
    assert auth.open() == {"status": "waiting_login", "message": None}


def test_fmss_browser_status_never_returns_token():
    auth = FmssBrowserAuth()
    auth._last_checked_token = "fake-token-never-returned"
    payload = auth.status()
    assert payload == {"status": "idle", "message": None}
    assert "token" not in str(payload).lower()


def test_fmss_browser_close_is_idempotent():
    auth = FmssBrowserAuth()
    assert auth.close() == {"status": "closed", "message": None}
    assert auth.close() == {"status": "closed", "message": None}


def test_session_not_connected_before_validation(monkeypatch):
    class FakeClient:
        def __init__(self, session):
            self.session = session

        def sheets(self, stage):
            raise FmssApiError("fake validation failure")

    monkeypatch.setattr("app.integrations.fmss.client.FmssClient", FakeClient)
    fmss_session.clear()
    assert FmssBrowserAuth()._validate_token("fake-admin-token") is False
    assert fmss_session.snapshot().connected is False


def test_session_connected_after_validation(monkeypatch):
    class FakeClient:
        def __init__(self, session):
            self.session = session

        def sheets(self, stage):
            assert stage == "PRE"
            assert self.session.snapshot().connected is True
            return []

    monkeypatch.setattr("app.integrations.fmss.client.FmssClient", FakeClient)
    auth = FmssBrowserAuth()
    fmss_session.clear()
    try:
        assert auth._validate_token("fake-admin-token") is True
        assert fmss_session.snapshot().connected is False
        fmss_session.connect("fake-admin-token")
        assert fmss_session.snapshot().connected is True
    finally:
        fmss_session.clear()
