from __future__ import annotations

import httpx
import pytest

from app.integrations.fmss.browser_auth import FmssBrowserAuthBridge, allowed_fmss_business_page, allowed_fmss_host, bearer_token, capture_script
from app.integrations.fmss.client import FmssClient
from app.integrations.fmss.errors import FmssApiError
from app.integrations.fmss.session import FmssSession


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
    assert "Content-Type" not in captured["headers"]


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


def test_browser_bridge_only_accepts_configured_fmss_host():
    assert allowed_fmss_host("https://fmssdev.gf.com.cn/fmss/trip/iitDeclaration/preReview")
    assert allowed_fmss_business_page("https://fmssdev.gf.com.cn/fmss/trip/iitDeclaration/preReview")
    assert not allowed_fmss_business_page("https://fmssdev.gf.com.cn/fmss/login")
    assert not allowed_fmss_host("https://testoauth2.gf.com.cn/login")
    assert bearer_token("Bearer abc123") == "abc123"
    assert bearer_token("Cookie abc123") is None
    session = FmssSession()
    bridge = FmssBrowserAuthBridge(session)
    with pytest.raises(ValueError):
        bridge.set_fmss_token("abc123", "https://testoauth2.gf.com.cn/login")
    with pytest.raises(ValueError):
        bridge.set_fmss_token("abc123", "https://fmssdev.gf.com.cn/fmss/login")


def test_capture_script_scopes_fetch_and_xhr_to_configured_api_path():
    script = capture_script()
    assert "parsed.origin === location.origin" in script
    assert "parsed.pathname.startsWith(apiPath)" in script
    assert "const requestUrl = typeof input === 'string' ? input : input?.url" in script
    assert "window.prompt" not in script
    assert "restore();" in script
    assert "location.pathname.startsWith(apiPath)" not in script
