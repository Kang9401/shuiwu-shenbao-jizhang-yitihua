import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import tax as tax_api
from app.core.config import settings
from app.db.session import Base
from app.models.accounting import PersonnelMasterArtifact
from app.models.core import Period
from app.models.tax import TaxMonthlyArtifact, VerificationRound, VerificationSession


def _db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return TestingSessionLocal()


def test_monthly_working_sheet_is_overwritten_per_period(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(tax_api, "ARTIFACT_DIR", tmp_path / "artifacts")
    db = _db_session()
    period = Period(year=2025, month=2, name="2025年02月")
    db.add(period)
    db.commit()
    db.refresh(period)

    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    pd.DataFrame([{"value": "first"}]).to_excel(first, index=False)
    pd.DataFrame([{"value": "second"}]).to_excel(second, index=False)

    tax_api._upsert_monthly_working_sheet(
        db,
        period_id=period.id,
        period=period,
        source_path=first,
        session_id=1,
        round_number=1,
    )
    db.commit()
    tax_api._upsert_monthly_working_sheet(
        db,
        period_id=period.id,
        period=period,
        source_path=second,
        session_id=1,
        round_number=2,
    )
    db.commit()

    artifacts = db.query(TaxMonthlyArtifact).all()
    assert len(artifacts) == 1
    assert artifacts[0].source_round_number == 2
    assert artifacts[0].file_content == second.read_bytes()
    assert artifacts[0].content_sha256
    saved = pd.read_excel(artifacts[0].stored_path)
    assert saved.iloc[0]["value"] == "second"
    db.close()


def test_download_all_zip_contains_declaration_and_personnel_collection_files(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(tax_api, "ARTIFACT_DIR", tmp_path / "artifacts")
    output_dir = tax_api.ARTIFACT_DIR / "1" / "output"
    output_dir.mkdir(parents=True)
    declaration_name = "11801_3-个税申报表(2025年02月).xls"
    collection_name = "11801_1-人员信息采集_员工(2025年02月).xls"
    (output_dir / declaration_name).write_text("declaration", encoding="utf-8")
    (output_dir / collection_name).write_text("personnel-collection", encoding="utf-8")
    (output_dir / "个税汇总一览表.xls").write_text("summary", encoding="utf-8")

    db = _db_session()
    period = Period(year=2025, month=2, name="2025年02月")
    db.add(period)
    db.commit()
    db.refresh(period)
    session = VerificationSession(id=1, period_id=period.id, status="done")
    db.add(session)
    monthly = tax_api.ARTIFACT_DIR / "monthly" / str(period.id) / "2025年02月_底稿.xlsx"
    monthly.parent.mkdir(parents=True)
    monthly.write_text("working-sheet", encoding="utf-8")
    db.add(TaxMonthlyArtifact(
        period_id=period.id,
        artifact_type="working_sheet",
        file_name=monthly.name,
        stored_path=str(monthly),
        source_session_id=1,
        source_round_number=1,
    ))
    db.commit()

    class SessionFactory:
        def __call__(self):
            return db

    monkeypatch.setattr("app.db.session.SessionLocal", SessionFactory())
    response = tax_api.download_all(1)
    archive = zipfile.ZipFile(io.BytesIO(response.body))

    assert archive.namelist() == [
        f"申报文件/{collection_name}",
        f"申报文件/{declaration_name}",
    ]
    db.close()


def test_successful_recheck_keeps_only_latest_session_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(tax_api, "ARTIFACT_DIR", tmp_path / "artifacts")
    db = _db_session()
    period = Period(year=2025, month=2, name="2025年2月")
    db.add(period)
    db.commit()
    session = VerificationSession(period_id=period.id, status="needs_review")
    db.add(session)
    db.commit()
    db.refresh(session)
    old_round = VerificationRound(session_id=session.id, round_number=1, uploaded_files=[], report_data={}, status="done")
    new_round = VerificationRound(session_id=session.id, round_number=2, uploaded_files=[], report_data={}, status="done")
    db.add_all([old_round, new_round])
    db.flush()
    for round_number in (1, 2):
        directory = tax_api.ARTIFACT_DIR / str(session.id) / f"round_{round_number}"
        directory.mkdir(parents=True)
        (directory / "result.xlsx").write_text(str(round_number), encoding="utf-8")
    output_dir = tax_api.ARTIFACT_DIR / str(session.id) / "output"
    output_dir.mkdir()
    (output_dir / "old.xls").write_text("old", encoding="utf-8")

    tax_api._remove_previous_session_results(db, session.id, new_round.id, new_round.round_number)
    db.commit()

    assert [row.id for row in db.query(VerificationRound).all()] == [new_round.id]
    assert not (tax_api.ARTIFACT_DIR / str(session.id) / "round_1").exists()
    assert (tax_api.ARTIFACT_DIR / str(session.id) / "round_2" / "result.xlsx").exists()
    assert not output_dir.exists()
    db.close()


def test_resolves_previous_month_employee_personnel_master(tmp_path: Path):
    db = _db_session()
    previous_period = Period(year=2025, month=1, name="2025年01月")
    current_period = Period(year=2025, month=2, name="2025年02月")
    db.add_all([previous_period, current_period])
    db.commit()
    master_path = tmp_path / "2025年01月_员工人员主数据.xlsx"
    pd.DataFrame([{"姓名": "张三", "证件号码": "110101199001010011"}]).to_excel(master_path, index=False)
    db.add(PersonnelMasterArtifact(
        period_id=previous_period.id,
        person_type="employee",
        scope_type="month",
        scope_code="",
        file_name=master_path.name,
        stored_path=str(master_path),
        row_count=1,
        validation_issues=[],
    ))
    db.commit()

    assert tax_api._resolve_previous_month_employee_master_path(db, current_period) == str(master_path)
    db.close()


def test_previous_month_employee_personnel_master_is_required():
    db = _db_session()
    previous_period = Period(year=2025, month=1, name="2025年01月")
    current_period = Period(year=2025, month=2, name="2025年02月")
    db.add_all([previous_period, current_period])
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        tax_api._resolve_previous_month_employee_master_path(db, current_period)
    assert exc_info.value.detail == "请先导入2025年01月的人员主数据（人员类型：员工）"
    db.close()


def test_initial_verification_always_uses_previous_month_employee_master(tmp_path: Path):
    db = _db_session()
    previous_period = Period(year=2025, month=1, name="2025年01月")
    current_period = Period(year=2025, month=2, name="2025年02月")
    db.add_all([previous_period, current_period])
    db.commit()

    previous_path = tmp_path / "previous.xlsx"
    current_path = tmp_path / "current.xlsx"
    pd.DataFrame([{"姓名": "上月人员", "证件号码": "1"}]).to_excel(previous_path, index=False)
    pd.DataFrame([{"姓名": "本月人员", "证件号码": "2"}]).to_excel(current_path, index=False)
    for period, path in [(previous_period, previous_path), (current_period, current_path)]:
        db.add(PersonnelMasterArtifact(
            period_id=period.id,
            person_type="employee",
            scope_type="month",
            scope_code="",
            file_name=path.name,
            stored_path=str(path),
            row_count=1,
            validation_issues=[],
        ))
    db.commit()

    resolved = tax_api._resolve_staff_path_for_verification(
        db, current_period, session_id=1, verification_stage="initial", has_staff_change=False,
    )

    assert resolved == str(previous_path)
    db.close()


def test_recheck_without_changes_materializes_current_employee_master(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db_session()
    previous_period = Period(year=2025, month=1, name="2025年01月")
    current_period = Period(year=2025, month=2, name="2025年02月")
    db.add_all([previous_period, current_period])
    db.commit()

    previous_path = tmp_path / "previous.xlsx"
    pd.DataFrame([{"姓名": "张三", "证件号码": "110101199001010011"}]).to_excel(previous_path, index=False)
    db.add(PersonnelMasterArtifact(
        period_id=previous_period.id,
        person_type="employee",
        scope_type="month",
        scope_code="",
        file_name=previous_path.name,
        stored_path=str(previous_path),
        row_count=1,
        validation_issues=[],
    ))
    db.commit()

    resolved = tax_api._resolve_staff_path_for_verification(
        db, current_period, session_id=1, verification_stage="recheck", has_staff_change=False,
    )

    current_artifact = db.query(PersonnelMasterArtifact).filter(
        PersonnelMasterArtifact.period_id == current_period.id,
        PersonnelMasterArtifact.person_type == "employee",
        PersonnelMasterArtifact.scope_type == "month",
    ).one()
    assert resolved == current_artifact.stored_path
    assert pd.read_excel(resolved).iloc[0]["姓名"] == "张三"
    db.close()


def test_recheck_with_staff_change_uses_previous_employee_master(tmp_path: Path):
    db = _db_session()
    previous_period = Period(year=2025, month=1, name="2025年01月")
    current_period = Period(year=2025, month=2, name="2025年02月")
    db.add_all([previous_period, current_period])
    db.commit()

    previous_path = tmp_path / "previous.xlsx"
    current_path = tmp_path / "current.xlsx"
    pd.DataFrame([{"姓名": "上月人员", "证件号码": "1"}]).to_excel(previous_path, index=False)
    pd.DataFrame([{"姓名": "已生成本月人员", "证件号码": "2"}]).to_excel(current_path, index=False)
    for period, path in [(previous_period, previous_path), (current_period, current_path)]:
        db.add(PersonnelMasterArtifact(
            period_id=period.id,
            person_type="employee",
            scope_type="month",
            scope_code="",
            file_name=path.name,
            stored_path=str(path),
            row_count=1,
            validation_issues=[],
        ))
    db.commit()

    resolved = tax_api._resolve_staff_path_for_verification(
        db, current_period, session_id=1, verification_stage="recheck", has_staff_change=True,
    )

    assert resolved == str(previous_path)
    db.close()


def test_employee_id_update_after_staff_change_removes_old_id_departure(tmp_path: Path):
    from app.services.personnel_master import materialize_employee_id_updates
    from app.services.verification import (
        build_working_sheet,
        check_personnel_changes,
        detect_employee_id_only_changes,
    )

    active_path = tmp_path / "updated_staff.xlsx"
    history_path = tmp_path / "updated_staff_history.xlsx"
    payroll_path = tmp_path / "payroll.xlsx"
    active = pd.DataFrame([{
        "员工编号": "3357654",
        "*姓名": "温玉玲",
        "证件号码": "360724199009034568",
        "机构代码": "12106",
        "人员状态": "正常",
    }])
    history = pd.concat([
        active,
        pd.DataFrame([{
            "员工编号": "10001",
            "*姓名": "历史人员",
            "证件号码": "360724198001010011",
            "机构代码": "12106",
            "人员状态": "非正常",
        }]),
    ], ignore_index=True)
    payroll = pd.DataFrame([{
        "员工编号": "46203",
        "*姓名": "温玉玲",
        "机构代码": "12106",
        "应发工资": 1000,
        "本期应预扣预缴税额SUM": 0,
        "个人所得税 SUM": 0,
    }])
    active.to_excel(active_path, index=False)
    history.to_excel(history_path, index=False)
    payroll.to_excel(payroll_path, index=False)

    review_sheet, review_staff = build_working_sheet(
        [("rank_salary", str(payroll_path))], str(active_path), ""
    )
    changes = detect_employee_id_only_changes(review_sheet, review_staff)
    assert [(item["old_employee_id"], item["new_employee_id"]) for item in changes] == [("3357654", "46203")]

    result = materialize_employee_id_updates(history_path, changes, tmp_path / "employee_id_updates", 2025, 2)
    sheet, staff = build_working_sheet(
        [("rank_salary", str(payroll_path))], result["updated_staff_path"], ""
    )

    assert check_personnel_changes(sheet, staff_df=staff, year=2025, month=2)["items"] == []
    saved_history = pd.read_excel(result["full_staff_path"], dtype=str).fillna("")
    assert saved_history.loc[saved_history["*姓名"] == "温玉玲", "员工编号"].iloc[0] == "46203"
    assert saved_history.loc[saved_history["*姓名"] == "历史人员", "人员状态"].iloc[0] == "非正常"


def test_latest_result_restores_saved_report_and_declarations(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(tax_api, "ARTIFACT_DIR", tmp_path / "artifacts")
    db = _db_session()
    period = Period(year=2025, month=2, name="2025年02月")
    db.add(period)
    db.commit()
    session = VerificationSession(period_id=period.id, status="done", current_round=2)
    db.add(session)
    db.commit()
    db.refresh(session)
    db.add(VerificationRound(
        session_id=session.id,
        round_number=1,
        uploaded_files=[],
        report_data={"summary": {"total_employees": 1}},
        status="done",
    ))
    output_dir = tax_api.ARTIFACT_DIR / str(session.id) / "output"
    output_dir.mkdir(parents=True)
    declaration = output_dir / "11801_3-个税申报表(2025年02月).xls"
    declaration.write_text("declaration", encoding="utf-8")
    collection = output_dir / "11801_1-人员信息采集_员工(2025年2月).xls"
    collection.write_text("personnel-collection", encoding="utf-8")
    db.commit()

    result = tax_api.get_latest_result(session.id, db)

    assert result["round_number"] == 1
    assert result["report"]["summary"]["total_employees"] == 1
    assert {item["name"] for item in result["generated_files"]} == {declaration.name, collection.name}
    assert {item["file_type"] for item in result["generated_files"]} == {"declaration", "personnel_collection"}

    session.status = "ready_to_generate"
    db.commit()
    result = tax_api.get_latest_result(session.id, db)
    assert result["generated_files"] == []
    db.close()


def test_generate_uses_saved_monthly_personnel_changes_without_new_upload(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(tax_api, "ARTIFACT_DIR", tmp_path / "artifacts")
    db = _db_session()
    period = Period(year=2025, month=2, name="2025年2月")
    db.add(period)
    db.commit()
    session = VerificationSession(period_id=period.id, status="ready_to_generate", current_round=2)
    db.add(session)
    db.commit()
    db.refresh(session)
    db.add(VerificationRound(
        session_id=session.id,
        round_number=1,
        uploaded_files=[],
        report_data={
            "monthly_personnel_changes": [{
                "*姓名": "李四",
                "证件类型": "居民身份证",
                "证件号码": "110101199202020022",
                "国籍(地区)": "中国",
                "性别": "女",
                "出生日期": "1992-02-02",
                "人员状态": "正常",
                "任职受雇从业类型": "雇员",
                "手机号码": "13900000000",
                "任职受雇从业日期": "2025/02/01",
                "离职日期": "",
                "机构代码(人员信息表)": "11801",
                "机构代码(工资单)": "11801",
                "员工编号": "1002",
            }],
        },
        status="done",
    ))
    round_dir = tax_api.ARTIFACT_DIR / str(session.id) / "round_1"
    round_dir.mkdir(parents=True)
    pd.DataFrame([{"机构代码_工资单": "11801"}]).to_excel(round_dir / "底稿.xlsx", index=False)

    def fake_generate_declarations(sheet, output_dir, year, month, staff_df=None):
        path = Path(output_dir) / "11801_3-个税申报表(2025年02月).xls"
        path.write_text("declaration", encoding="utf-8")
        return [str(path)]

    monkeypatch.setattr(tax_api, "generate_declarations", fake_generate_declarations)
    db.commit()

    result = tax_api.generate(session.id, db)

    assert {file.file_type for file in result.files} == {"declaration", "personnel_collection"}
    assert any("_1-人员信息采集_员工" in file.name for file in result.files)
    db.close()
