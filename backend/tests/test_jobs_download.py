import io
import zipfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import jobs as jobs_api
from app.db.session import Base
from app.models.core import Artifact, Job


def _db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return testing_session_local()


def test_batch_download_contains_only_declaration_and_personnel_collection(tmp_path: Path):
    db = _db_session()
    job = Job(workflow_code="restricted_stock_interest_tax", input_file_ids=[], status="success")
    db.add(job)
    db.commit()
    db.refresh(job)
    declaration = tmp_path / "10301_限售股利息税申报表.xlsx"
    collection = tmp_path / "10301_1-人员信息采集_其他.xls"
    result = tmp_path / "处理结果.xlsx"
    declaration.write_text("declaration", encoding="utf-8")
    collection.write_text("collection", encoding="utf-8")
    result.write_text("result", encoding="utf-8")
    db.add_all([
        Artifact(job_id=job.id, artifact_type="declaration", file_name=declaration.name, stored_path=str(declaration)),
        Artifact(job_id=job.id, artifact_type="personnel_collection", file_name=collection.name, stored_path=str(collection)),
        Artifact(job_id=job.id, artifact_type="restricted_stock_interest_result", file_name=result.name, stored_path=str(result)),
    ])
    db.commit()

    response = jobs_api.download_job_declarations(job.id, db)
    archive = zipfile.ZipFile(io.BytesIO(response.body))

    assert archive.namelist() == [
        f"申报文件/{declaration.name}",
        f"申报文件/{collection.name}",
    ]
    db.close()
