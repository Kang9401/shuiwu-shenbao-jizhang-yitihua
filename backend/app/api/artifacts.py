from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.core import Artifact

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}/download")
def download_artifact(artifact_id: int, db: Session = Depends(get_db)) -> FileResponse:
    artifact = db.query(Artifact).filter(Artifact.id == artifact_id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = Path(artifact.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件已丢失")
    return FileResponse(path, filename=artifact.file_name)
