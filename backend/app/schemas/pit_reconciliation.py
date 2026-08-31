from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class PitManualUpdate(BaseModel):
    manual_reason: Optional[str] = Field(default=None, max_length=4000)
    remark: Optional[str] = Field(default=None, max_length=4000)


class PitRecalculateRequest(BaseModel):
    force: bool = True
