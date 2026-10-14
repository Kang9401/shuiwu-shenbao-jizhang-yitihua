from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.services import finance_ai


router = APIRouter(prefix="/finance-ai", tags=["finance-ai"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息不能为空")
        return value


class ChatRequest(BaseModel):
    skill: str = "general"
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)
    period_context: str | None = Field(default=None, max_length=30)


@router.get("/status")
def get_status() -> dict:
    return finance_ai.status()


@router.post("/chat")
def create_chat(payload: ChatRequest) -> dict:
    try:
        return finance_ai.chat(
            [message.model_dump() for message in payload.messages],
            payload.skill,
            payload.period_context,
        )
    except finance_ai.FinanceAIError as exc:
        status_code = 503 if "尚未配置" in str(exc) or "无法连接" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
