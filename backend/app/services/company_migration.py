from __future__ import annotations

import shutil
from pathlib import Path

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.accounting import (
    PersonnelMasterArtifact,
    PersonnelMasterImportBatch,
    ReconciliationImportBatch,
)
from app.models.core import Artifact, Company, Job, UploadedFile
from app.models.tax import TaxMonthlyArtifact, VerificationSession


def _copy_tree(source: Path, target: Path) -> None:
    if source.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, dirs_exist_ok=True)


def migrate_legacy_company_storage() -> None:
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.code == "DEFAULT").first()
        if company is None:
            return
        company_id = company.id
        artifact_root = settings.artifact_dir.resolve()
        upload_root = settings.upload_dir.resolve()

        job_ids = [row[0] for row in db.query(Job.id).filter(Job.company_id == company_id).all()]
        session_ids = [row[0] for row in db.query(VerificationSession.id).filter(VerificationSession.company_id == company_id).all()]
        copied_sources: set[Path] = set()
        for job_id in job_ids:
            source = artifact_root / str(job_id)
            if source.is_dir():
                _copy_tree(source, artifact_root / str(company_id) / "jobs" / str(job_id))
                copied_sources.add(source)
        for session_id in session_ids:
            source = artifact_root / str(session_id)
            if source.is_dir():
                _copy_tree(source, artifact_root / str(company_id) / "tax" / str(session_id))
                copied_sources.add(source)
        monthly = artifact_root / "monthly"
        if monthly.is_dir():
            _copy_tree(monthly, artifact_root / str(company_id) / "tax" / "monthly")
            copied_sources.add(monthly)

        rpa_root = settings.storage_root.resolve() / "rpa" / "etax"
        company_rpa = rpa_root / "companies" / str(company_id)
        for directory_name in ("state", "uploads"):
            source = rpa_root / directory_name
            if source.is_dir() and not (company_rpa / directory_name).exists():
                _copy_tree(source, company_rpa / directory_name)
        runtime_app = rpa_root / "app"
        for directory_name in ("input", "output"):
            source = runtime_app / directory_name
            if source.is_dir() and not (company_rpa / directory_name).exists():
                _copy_tree(source, company_rpa / directory_name)

        path_models = (
            (UploadedFile, upload_root, upload_root / str(company_id) / "legacy"),
            (PersonnelMasterArtifact, upload_root, upload_root / str(company_id) / "legacy"),
            (PersonnelMasterImportBatch, upload_root, upload_root / str(company_id) / "legacy"),
            (ReconciliationImportBatch, upload_root, upload_root / str(company_id) / "legacy"),
        )
        for model, root, legacy_root in path_models:
            for item in db.query(model).filter(model.company_id == company_id).all():
                source = Path(item.stored_path).resolve()
                company_root = root / str(company_id)
                if not source.is_file() or company_root == source or company_root in source.parents:
                    continue
                try:
                    relative = source.relative_to(root)
                except ValueError:
                    continue
                target = legacy_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(source, target)
                item.stored_path = str(target)

        for artifact in db.query(Artifact).filter(Artifact.company_id == company_id).all():
            source = Path(artifact.stored_path).resolve()
            target_root = artifact_root / str(company_id) / "jobs" / str(artifact.job_id)
            if source.is_file() and target_root not in source.parents:
                target = target_root / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(source, target)
                artifact.stored_path = str(target)

        for artifact in db.query(TaxMonthlyArtifact).filter(TaxMonthlyArtifact.company_id == company_id).all():
            source = Path(artifact.stored_path).resolve()
            target_root = artifact_root / str(company_id) / "tax" / "monthly" / str(artifact.period_id)
            if source.is_file() and target_root not in source.parents:
                target = target_root / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(source, target)
                artifact.stored_path = str(target)

        db.commit()
        for source in copied_sources:
            shutil.rmtree(source, ignore_errors=True)
    finally:
        db.close()
