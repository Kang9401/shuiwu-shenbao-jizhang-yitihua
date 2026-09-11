from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ValidationIssue(BaseModel):
    issue_type: str
    message: str
    field: Optional[str] = None
    row: Optional[int] = None
    severity: str = "error"
    meta: Optional[Dict[str, Any]] = None


class ArtifactRead(ORMModel):
    id: int
    job_id: int
    artifact_type: str
    file_name: str
    created_at: datetime
