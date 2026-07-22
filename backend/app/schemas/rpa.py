from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

RpaTaskKey = Literal["special_deduction", "import", "tax_certificate", "income_report", "extra_income_reports"]


class RpaConfigUpdate(BaseModel):
    chrome_path: str = Field(default="", max_length=500)


class RpaChromeStart(RpaConfigUpdate):
    pass


class RpaOrgPreviewRequest(BaseModel):
    all_orgs: bool = True
    org_code: str | None = Field(default=None, max_length=50)
    start_org_code: str | None = Field(default=None, max_length=50)


class RpaTaskStartRequest(BaseModel):
    task_key: RpaTaskKey
    month: str
    all_orgs: bool = True
    org_code: str | None = Field(default=None, max_length=50)
    resume_mode: Literal["resume", "reset"] | None = None

    @field_validator("month")
    @classmethod
    def month_format(cls, value: str) -> str:
        import re
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            raise ValueError("月份必须使用 YYYY-MM 格式")
        return value


class RpaDeleteFilesRequest(BaseModel):
    names: list[str] = Field(min_length=1, max_length=200)


class RpaPreparePeriodRequest(BaseModel):
    period_id: int = Field(gt=0)
    overwrite: bool = False
