# backend/app/schemas/tax.py
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    period_id: int


class SessionRead(BaseModel):
    id: int
    period_id: int
    status: str
    current_round: int
    confirmed_personnel: Optional[list] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PersonnelConfirmItem(BaseModel):
    name: str
    id_number: str = ""
    change_type: str
    cert_type: str = ""
    org_code_from: str = ""
    org_code_to: str = ""
    employee_id: str = ""
    phone: str = ""
    hire_date: str = ""
    leave_date: str = ""
    missing_fields: list[str] = Field(default_factory=list)
    confirmed: bool = True
    is_transfer_like: bool = False


class ConfirmRequest(BaseModel):
    confirmed_changes: list[PersonnelConfirmItem]


class GeneratedFile(BaseModel):
    name: str
    download_url: str
    file_type: str = ""


class GenerateResponse(BaseModel):
    status: str
    files: list[GeneratedFile]
