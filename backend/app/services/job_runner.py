from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.core import Artifact, Job, UploadedFile
from app.workflows import get_workflow


def run_job(db: Session, job: Job, operation: str = "generate") -> Job:
    workflow = get_workflow(job.workflow_code)
    job.operation = operation
    job.status = "running"
    job.started_at = datetime.utcnow()
    db.add(job)
    db.flush()

    try:
        files = (
            db.query(UploadedFile)
            .filter(UploadedFile.id.in_(job.input_file_ids))
            .order_by(UploadedFile.id)
            .all()
        )
        if job.workflow_code == "restricted_stock_interest_tax":
            result = workflow.run(db, job.id, job.period_id, files, operation=operation)
        else:
            result = workflow.run(db, job.id, job.period_id, files)
        job.status = result.status
        job.result_summary = result.summary
        job.finished_at = datetime.utcnow()
        replaces_current = job.period_id is not None and any(
            artifact_type == "declaration" for artifact_type, _ in result.artifact_paths
        )
        if replaces_current:
            previous_artifacts = (
                db.query(Artifact)
                .join(Job, Artifact.job_id == Job.id)
                .filter(
                    Job.workflow_code == job.workflow_code,
                    Job.period_id == job.period_id,
                    Job.id != job.id,
                )
                .all()
            )
            for artifact in previous_artifacts:
                try:
                    Path(artifact.stored_path).unlink(missing_ok=True)
                except OSError:
                    pass
                db.delete(artifact)
        for artifact_type, stored_path in result.artifact_paths:
            db.add(
                Artifact(
                    job_id=job.id,
                    artifact_type=artifact_type,
                    file_name=Path(stored_path).name,
                    stored_path=stored_path,
                )
            )
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = datetime.utcnow()
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
