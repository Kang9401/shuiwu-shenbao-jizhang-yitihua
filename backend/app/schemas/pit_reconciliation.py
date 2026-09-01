from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional
from pydantic import BaseModel, Field


class PitManualUpdate(BaseModel):
    manual_reason: Optional[str] = Field(default=None, max_length=4000)
    remark: Optional[str] = Field(default=None, max_length=4000)


class PitSummaryUpdate(BaseModel):
    difference_1_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    difference_2_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    difference_3_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    difference_4_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    difference_5_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    difference_6_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    difference_7_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    remark: Optional[str] = Field(default=None, max_length=4000)


class PitTaxAmountCheckUpdate(BaseModel):
    current_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    cumulative_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    business_declared_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    remark: Optional[str] = Field(default=None, max_length=4000)


class PitOccurrenceCheckUpdate(BaseModel):
    broker_occurrence_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    declared_income_manual_reason: Optional[str] = Field(default=None, max_length=4000)
    remark: Optional[str] = Field(default=None, max_length=4000)


class PitOrgSummaryRead(BaseModel):
    id: int; public_id: str; org_code: str; org_name: str; org_full_name: str
    declared_tax_amount: Decimal | None = None; balance_tax_amount: Decimal | None = None; difference_1: Decimal | None = None; difference_1_manual_reason: str | None = None
    scoped_declared_tax_amount: Decimal | None = None; payroll_business_tax_amount: Decimal | None = None; difference_2: Decimal | None = None; difference_2_manual_reason: str | None = None
    taxable_income_difference: Decimal | None = None; difference_3_manual_reason: str | None = None; certificate_tax_amount: Decimal | None = None; difference_4: Decimal | None = None; difference_4_manual_reason: str | None = None
    bank_tax_amount: Decimal | None = None; difference_5: Decimal | None = None; difference_5_manual_reason: str | None = None; broker_occurrence_difference: Decimal | None = None; difference_6_manual_reason: str | None = None; other_income_difference: Decimal | None = None; difference_7_manual_reason: str | None = None; remark: str | None = None; check_status: str
    model_config = {"from_attributes": True}


class PitDifferenceDetailRead(BaseModel):
    id: int; public_id: str; detail_type: str; org_code: str; org_name: str; subject_code: str | None = None; identity_key: str; person_or_customer_name: str; id_number: str | None = None
    source_amount: Decimal | None = None; target_amount: Decimal | None = None; difference: Decimal | None = None; auto_reason: str | None = None; manual_reason: str | None = None; remark: str | None = None; detail_json: dict[str, Any] | None = None
    model_config = {"from_attributes": True}


class PitRecalculateRequest(BaseModel):
    force: bool = True
