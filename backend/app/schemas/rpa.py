from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

RpaTaskKey = Literal["special_deduction", "import", "tax_certificate", "income_report", "extra_income_reports", "declaration_reports"]


class RpaConfigUpdate(BaseModel):
    chrome_path: str = Field(default="", max_length=500)


class RpaChromeStart(RpaConfigUpdate):
    pass


class RpaOrgPreviewRequest(BaseModel):
    period_id: Optional[int] = Field(default=None, gt=0)
    all_orgs: bool = True
    org_codes: List[str] = Field(default_factory=list, max_length=500)
    org_code: Optional[str] = Field(default=None, max_length=50)
    start_org_code: Optional[str] = Field(default=None, max_length=50)


class RpaTaskStartRequest(BaseModel):
    task_key: RpaTaskKey
    period_id: Optional[int] = Field(default=None, gt=0)
    declaration_month: Optional[str] = None
    month: Optional[str] = None
    all_orgs: bool = True
    org_codes: List[str] = Field(default_factory=list, max_length=500)
    org_code: Optional[str] = Field(default=None, max_length=50)
    resume_mode: Optional[Literal["resume", "reset"]] = None
    start_org_code: Optional[str] = Field(default=None, max_length=50)

    @field_validator("declaration_month", "month")
    @classmethod
    def month_format(cls, value: Optional[str]) -> Optional[str]:
        import re
        if value is None:
            return value
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
            raise ValueError("月份必须使用 YYYY-MM 格式")
        return value

    def resolved_month(self) -> str:
        value = self.declaration_month or self.month
        if not value:
            raise ValueError("申报月份不能为空")
        return value


class RpaDeleteFilesRequest(BaseModel):
    names: list[str] = Field(min_length=1, max_length=200)


class RpaPreparePeriodRequest(BaseModel):
    period_id: int = Field(gt=0)
    overwrite: bool = False
