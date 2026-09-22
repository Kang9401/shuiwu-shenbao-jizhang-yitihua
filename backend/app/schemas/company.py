from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CompanyPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=60)
    operator_name: str = Field(min_length=1, max_length=120)
    notes: str = Field(default="", max_length=500)
    fmss_branch_code: str | None = Field(default=None, max_length=60)
    fmss_branch_name: str | None = Field(default=None, max_length=255)

    @field_validator("name", "code", "operator_name", "notes", "fmss_branch_code", "fmss_branch_name")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("name", "code", "operator_name")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("不能为空")
        return value


class CompanyRead(CompanyPayload):
    model_config = ConfigDict(from_attributes=True)

    id: int
    active: bool
    created_at: datetime
    updated_at: datetime


class CompanyStatusUpdate(BaseModel):
    active: bool
