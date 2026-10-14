from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from app.services import finance_ai


def test_status_does_not_expose_api_key(monkeypatch):
    monkeypatch.setattr(settings, "finance_ai_base_url", "https://model.example/v1")
    monkeypatch.setattr(settings, "finance_ai_api_key", "secret-value")
    monkeypatch.setattr(settings, "finance_ai_model", "finance-model")

    result = TestClient(create_app()).get("/api/finance-ai/status")

    assert result.status_code == 200
    assert result.json()["configured"] is True
    assert result.json()["model"] == "finance-model"
    assert "secret-value" not in result.text
    assert len(result.json()["skills"]) == 4


def test_chat_injects_finance_prompt_and_returns_content(monkeypatch):
    monkeypatch.setattr(settings, "finance_ai_base_url", "https://model.example/v1")
    monkeypatch.setattr(settings, "finance_ai_api_key", "secret-value")
    monkeypatch.setattr(settings, "finance_ai_model", "finance-model")
    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"model": "finance-model", "choices": [{"message": {"content": "先核实业务实质。"}}]},
        )

    monkeypatch.setattr(finance_ai.httpx, "post", fake_post)
    result = TestClient(create_app()).post(
        "/api/finance-ai/chat",
        json={
            "skill": "accounting",
            "period_context": "2026年06月",
            "messages": [{"role": "user", "content": "这笔费用如何入账？"}],
        },
    )

    assert result.status_code == 200
    assert result.json()["content"] == "先核实业务实质。"
    assert captured["url"] == "https://model.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-value"
    assert "会计处理" in captured["json"]["messages"][0]["content"]
    assert "2026年06月" in captured["json"]["messages"][0]["content"]


def test_chat_requires_model_configuration(monkeypatch):
    monkeypatch.setattr(settings, "finance_ai_base_url", "")
    monkeypatch.setattr(settings, "finance_ai_api_key", "")
    monkeypatch.setattr(settings, "finance_ai_model", "")

    result = TestClient(create_app()).post(
        "/api/finance-ai/chat",
        json={"skill": "general", "messages": [{"role": "user", "content": "分析毛利变化"}]},
    )

    assert result.status_code == 503
    assert result.json()["detail"] == "财务 SKILL 尚未配置模型服务"
