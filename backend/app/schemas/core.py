from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.common import ArtifactRead, ORMModel


class PeriodCreate(BaseModel):
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)


class PeriodRead(ORMModel):
    id: int
    year: int
    month: int
    name: str
    status: str
    created_at: datetime


class UploadedFileRead(ORMModel):
    id: int
    period_id: Optional[int]
    file_role: str
    original_name: str
    size_bytes: int
    validation_status: str
    validation_issues: Optional[List[Any]]
    created_at: datetime


class JobCreate(BaseModel):
    workflow_code: str
    period_id: Optional[int] = None
    input_file_ids: List[int]
    operation: Literal["generate", "reconcile", "initial", "recheck"] = "generate"


class JobRead(ORMModel):
    id: int
    workflow_code: str
    period_id: Optional[int]
    operation: str
    app_version: str
    ruleset_version: str
    status: str
    input_file_ids: List[int]
    result_summary: Optional[Dict[str, Any]]
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class JobDetail(JobRead):
    artifacts: List[ArtifactRead] = []
