from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Protocol, Tuple

from sqlalchemy.orm import Session

from app.models.core import UploadedFile


@dataclass(frozen=True)
class WorkflowInfo:
    code: str
    name: str
    domain: str
    description: str
    required_file_roles: List[str]


@dataclass
class WorkflowResult:
    status: str
    summary: dict[str, Any]
    artifact_paths: List[Tuple[str, str]]


class Workflow(Protocol):
    info: WorkflowInfo

    def run(
        self,
        db: Session,
        job_id: int,
        period_id: Optional[int],
        files: List[UploadedFile],
    ) -> WorkflowResult:
        ...
