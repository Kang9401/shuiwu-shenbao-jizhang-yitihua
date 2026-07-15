from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.core import Artifact, Job, Period
from app.services import job_runner
from app.workflows.base import WorkflowResult


class _SuccessfulWorkflow:
    def __init__(self, artifact_path: Path):
        self.artifact_path = artifact_path

    def run(self, db, job_id, period_id, files):
        self.artifact_path.write_text("new", encoding="utf-8")
        return WorkflowResult(
            status="success",
            summary={"generated_files": 1},
            artifact_paths=[("declaration", str(self.artifact_path))],
        )


def test_successful_generation_replaces_old_artifacts_for_same_period_and_workflow(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    db = session_local()

    period = Period(year=2026, month=6, name="2026年06月", status="open")
    db.add(period)
    db.commit()
    db.refresh(period)

    old_file = tmp_path / "old.xlsx"
    old_file.write_text("old", encoding="utf-8")
    old_job = Job(workflow_code="broker_tax", period_id=period.id, input_file_ids=[], status="success")
    db.add(old_job)
    db.commit()
    db.refresh(old_job)
    db.add(Artifact(job_id=old_job.id, artifact_type="declaration", file_name=old_file.name, stored_path=str(old_file)))

    new_job = Job(workflow_code="broker_tax", period_id=period.id, input_file_ids=[], status="pending")
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    new_file = tmp_path / "new.xlsx"
    monkeypatch.setattr(job_runner, "get_workflow", lambda code: _SuccessfulWorkflow(new_file))

    result = job_runner.run_job(db, new_job)

    artifacts = db.query(Artifact).all()
    assert result.status == "success"
    assert [(item.job_id, item.file_name) for item in artifacts] == [(new_job.id, new_file.name)]
    assert not old_file.exists()
    assert new_file.exists()
    db.close()
