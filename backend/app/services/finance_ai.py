from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


SKILLS: dict[str, dict[str, str]] = {
    "general": {
        "name": "综合财务分析",
        "instruction": "从财务影响、会计口径、税务影响和风险事项四个角度分析。",
    },
    "accounting": {
        "name": "会计处理",
        "instruction": "聚焦会计确认、计量、列报和分录建议，明确适用准则及仍需核实的凭证。",
    },
    "tax": {
        "name": "税务判断",
        "instruction": "聚焦中国税务处理、申报口径和资料留存；不确定的政策时点必须明确提示核验。",
    },
    "review": {
        "name": "风险复核",
        "instruction": "以复核人员视角识别数据矛盾、合规风险、内控缺口和后续检查步骤。",
    },
}

SYSTEM_PROMPT = """你是企业内部财务工作台中的财务 SKILL，服务中国境内企业财税人员。
回答要求：
1. 先给结论，再列依据、计算过程或处理步骤；信息不足时列出需要补充的关键事实。
2. 严格区分已知事实、合理假设和待核实事项，不编造法规文号、税率、日期或业务数据。
3. 涉及法规政策时说明适用期间和地区；无法确认现行有效性时明确要求通过官方渠道复核。
4. 涉及金额计算时展示公式、口径、单位和舍入方式。
5. 不输出或重复完整身份证号、银行卡号等敏感信息，必要时使用脱敏形式。
6. 你的输出是专业工作建议，不能替代有权限人员的审批、正式申报或法定鉴证。
使用简洁、专业的中文回答。"""


class FinanceAIError(RuntimeError):
    pass


def status() -> dict[str, Any]:
    configured = bool(
        settings.finance_ai_base_url.strip()
        and settings.finance_ai_api_key.strip()
        and settings.finance_ai_model.strip()
    )
    return {
        "configured": configured,
        "model": settings.finance_ai_model.strip() if configured else None,
        "skills": [{"key": key, "name": value["name"]} for key, value in SKILLS.items()],
    }


def chat(messages: list[dict[str, str]], skill: str, period_context: str | None = None) -> dict[str, Any]:
    if not status()["configured"]:
        raise FinanceAIError("财务 SKILL 尚未配置模型服务")
    if skill not in SKILLS:
        raise FinanceAIError("不支持的财务能力")

    context = f"当前工作台所属期间：{period_context}。" if period_context else ""
    system_message = f"{SYSTEM_PROMPT}\n当前能力：{SKILLS[skill]['name']}。{SKILLS[skill]['instruction']}\n{context}"
    payload = {
        "model": settings.finance_ai_model.strip(),
        "messages": [{"role": "system", "content": system_message}, *messages],
        "temperature": 0.2,
    }
    url = f"{settings.finance_ai_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.finance_ai_api_key.strip()}",
        "Content-Type": "application/json",
    }
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=settings.finance_ai_timeout_seconds)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise FinanceAIError("模型响应超时，请稍后重试") from exc
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in {401, 403}:
            message = "模型服务认证失败，请检查 API Key"
        elif code == 429:
            message = "模型服务请求过于频繁，请稍后重试"
        else:
            message = f"模型服务调用失败（HTTP {code}）"
        raise FinanceAIError(message) from exc
    except httpx.HTTPError as exc:
        raise FinanceAIError("无法连接模型服务，请检查地址和网络") from exc

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty content")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise FinanceAIError("模型返回了无法识别的响应") from exc
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
    return {"content": content.strip(), "model": data.get("model") or settings.finance_ai_model, "usage": usage}
