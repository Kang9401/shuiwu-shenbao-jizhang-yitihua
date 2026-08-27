from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.accounting import OrganizationMapping, PersonnelMasterArtifact
from app.models.core import Job, Period
from app.services.part_time_tax import process_part_time
from app.models.core import UploadedFile
from app.core.config import settings
from app.workflows import get_workflow


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def _periods(db):
    previous = Period(year=2026, month=7, name="2026-07")
    current = Period(year=2026, month=8, name="2026-08")
    db.add_all([previous, current, OrganizationMapping(branch_name="营业部一", org_code="13208", active=1)])
    db.commit()
    db.refresh(previous)
    db.refresh(current)
    return previous, current


def _master(tmp_path, db, previous, rows):
    path = tmp_path / "part_time.xlsx"
    columns = [
        "姓名", "工号", "归属机构代码", "归属机构名称", "证件类型", "证件号码",
        "国籍（地区）", "性别", "出生日期", "手机号码", "任职/从业日期", "人员状态", "离职日期",
    ]
    pd.DataFrame(rows, columns=columns if not rows else None).to_excel(path, index=False)
    db.add(PersonnelMasterArtifact(
        period_id=previous.id, person_type="part_time", scope_type="month", scope_code="",
        file_name=path.name, stored_path=str(path), row_count=len(rows), validation_issues=[],
    ))
    db.commit()


def test_unique_name_without_payroll_id_matches_master(tmp_path):
    db = _db()
    previous, current = _periods(db)
    _master(tmp_path, db, previous, [{"姓名": "张三", "证件类型": "居民身份证", "证件号码": "110101199003072015", "归属机构代码": "13208", "人员状态": "正常"}])
    result = process_part_time(db, pd.DataFrame([{"姓名": "张三", "本期收入": 6500}]), None, period_id=current.id)
    assert not result["blocking"]
    assert result["rows"].iloc[0]["*证件号码"] == "110101199003072015"


def test_same_name_without_id_blocks(tmp_path):
    db = _db()
    previous, current = _periods(db)
    _master(tmp_path, db, previous, [
        {"姓名": "张伟", "证件号码": "110101199003072015", "归属机构代码": "13208", "人员状态": "正常"},
        {"姓名": "张伟", "证件号码": "110101199001010025", "归属机构代码": "13208", "人员状态": "正常"},
    ])
    result = process_part_time(db, pd.DataFrame([{"姓名": "张伟", "本期收入": 1000}]), None, period_id=current.id)
    assert any(issue["issue_type"] == "same_name_missing_id" for issue in result["blocking"])


def test_same_name_with_distinct_ids_matches_separately(tmp_path):
    db = _db()
    previous, current = _periods(db)
    _master(tmp_path, db, previous, [
        {"姓名": "张伟", "证件号码": "110101199003072015", "归属机构代码": "13208", "人员状态": "正常"},
        {"姓名": "张伟", "证件号码": "110101199001010025", "归属机构代码": "13208", "人员状态": "正常"},
    ])
    result = process_part_time(db, pd.DataFrame([
        {"姓名": "张伟", "证件号码": "110101199003072015", "本期收入": 1000},
        {"姓名": "张伟", "证件号码": "110101199001010025", "本期收入": 2000},
    ]), None, period_id=current.id)
    assert not result["blocking"]
    assert len(result["rows"]) == 2


def test_id_mismatch_is_warning_and_master_id_wins(tmp_path):
    db = _db()
    previous, current = _periods(db)
    _master(tmp_path, db, previous, [{"姓名": "张三", "证件类型": "居民身份证", "证件号码": "110101199003072015", "归属机构代码": "13208", "人员状态": "正常"}])
    result = process_part_time(db, pd.DataFrame([{"姓名": "张三", "证件号码": "110101199001010025", "本期收入": 6500}]), None, period_id=current.id)
    assert not result["blocking"]
    assert any(issue["issue_type"] == "id_mismatch" for issue in result["issues"])
    assert result["rows"].iloc[0]["*证件号码"] == "110101199003072015"


def test_new_person_blocks_until_change_is_supplied(tmp_path):
    db = _db()
    _, current = _periods(db)
    result = process_part_time(db, pd.DataFrame([{"姓名": "赵六", "证件号码": "110101199001010018", "本期收入": 1000}]), None, period_id=current.id)
    assert any(issue["issue_type"] == "new_part_time_person" for issue in result["blocking"])
    assert not result["pending"].empty


def test_initial_recheck_applies_new_person_only_after_change_data(tmp_path):
    db = _db()
    previous, current = _periods(db)
    _master(tmp_path, db, previous, [])
    payroll = pd.DataFrame([{"姓名": "赵六", "证件号码": "110101199003072017", "本期收入": 1000}])
    initial = process_part_time(db, payroll, None, period_id=current.id, stage="initial")
    assert initial["blocking"]
    assert initial["master"].empty

    changes = pd.DataFrame([{
        "变更类型": "新增", "姓名": "赵六", "归属机构代码": "13208", "证件类型": "居民身份证",
        "证件号码": "110101199003072017", "国籍（地区）": "中国", "性别": "男",
        "出生日期": "1990-01-01", "手机号码": "13800138000", "任职/从业日期": "2026-08-01",
    }])
    recheck = process_part_time(db, payroll, changes, period_id=current.id, stage="recheck")
    assert not recheck["blocking"]
    assert recheck["rows"].iloc[0]["*姓名"] == "赵六"


def test_initial_rehire_requires_change_then_recheck_restores_person(tmp_path):
    db = _db()
    previous, current = _periods(db)
    _master(tmp_path, db, previous, [{"姓名": "张三", "证件号码": "110101199003072015", "归属机构代码": "13208", "人员状态": "非正常", "离职日期": "2026-07-31"}])
    payroll = pd.DataFrame([{"姓名": "张三", "本期收入": 1000}])
    initial = process_part_time(db, payroll, None, period_id=current.id, stage="initial")
    assert any(issue["issue_type"] == "rehire_requires_change" for issue in initial["blocking"])

    changes = pd.DataFrame([{
        "变更类型": "重新任职", "姓名": "张三", "归属机构代码": "13208", "证件类型": "居民身份证",
        "证件号码": "110101199003072017", "国籍（地区）": "中国", "性别": "男",
        "出生日期": "1990-01-01", "手机号码": "13800138000", "任职/从业日期": "2026-08-01",
    }])
    recheck = process_part_time(db, payroll, changes, period_id=current.id, stage="recheck")
    assert not recheck["blocking"]
    assert recheck["master"].iloc[0]["人员状态"] == "正常"


def test_initial_workflow_generates_review_only_and_recheck_generates_final_files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db()
    previous, current = _periods(db)
    _master(tmp_path, db, previous, [])
    payroll_path = tmp_path / "payroll.xlsx"
    changes_path = tmp_path / "changes.xlsx"
    pd.DataFrame([{"姓名": "赵六", "证件号码": "110101199003072017", "本期收入": 1000}]).to_excel(payroll_path, index=False)
    pd.DataFrame([{
        "变更类型": "新增", "姓名": "赵六", "归属机构代码": "13208", "证件类型": "居民身份证",
        "证件号码": "110101199003072017", "国籍（地区）": "中国", "性别": "男",
        "出生日期": "1990-01-01", "手机号码": "13800138000", "任职/从业日期": "2026-08-01",
    }]).to_excel(changes_path, index=False)
    payroll = UploadedFile(period_id=current.id, file_role="payroll", original_name=payroll_path.name, stored_path=str(payroll_path), size_bytes=payroll_path.stat().st_size, validation_status="uploaded", validation_issues=[])
    changes = UploadedFile(period_id=current.id, file_role="personnel_changes", original_name=changes_path.name, stored_path=str(changes_path), size_bytes=changes_path.stat().st_size, validation_status="uploaded", validation_issues=[])
    workflow = get_workflow("part_time_tax")
    initial = workflow.run(db, 9201, current.id, [payroll], operation="initial")
    assert initial.status == "needs_review"
    assert not any(kind in {"declaration", "personnel_collection", "part_time_master"} for kind, _ in initial.artifact_paths)
    final = workflow.run(db, 9202, current.id, [payroll, changes], operation="recheck")
    assert final.status == "success"
    assert {kind for kind, _ in final.artifact_paths} >= {"declaration", "part_time_master"}


def test_recheck_reuses_latest_initial_payroll(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db()
    previous, current = _periods(db)
    _master(tmp_path, db, previous, [])
    payroll_path = tmp_path / "payroll.xlsx"
    changes_path = tmp_path / "changes.xlsx"
    pd.DataFrame([{"姓名": "赵六", "证件号码": "110101199003072017", "本期收入": 1000}]).to_excel(payroll_path, index=False)
    pd.DataFrame([{
        "变更类型": "新增", "姓名": "赵六", "归属机构代码": "13208", "证件类型": "居民身份证",
        "证件号码": "110101199003072017", "国籍（地区）": "中国", "性别": "男",
        "出生日期": "1990-01-01", "手机号码": "13800138000", "任职/从业日期": "2026-08-01",
    }]).to_excel(changes_path, index=False)
    payroll = UploadedFile(period_id=current.id, file_role="payroll", original_name=payroll_path.name, stored_path=str(payroll_path), size_bytes=payroll_path.stat().st_size, validation_status="uploaded", validation_issues=[])
    changes = UploadedFile(period_id=current.id, file_role="personnel_changes", original_name=changes_path.name, stored_path=str(changes_path), size_bytes=changes_path.stat().st_size, validation_status="uploaded", validation_issues=[])
    db.add_all([payroll, changes])
    db.flush()
    db.add(Job(workflow_code="part_time_tax", period_id=current.id, operation="initial", input_file_ids=[payroll.id], status="needs_review"))
    db.commit()
    result = get_workflow("part_time_tax").run(db, 9203, current.id, [changes], operation="recheck")
    assert result.status == "success"
    assert {kind for kind, _ in result.artifact_paths} >= {"declaration", "part_time_master"}


def test_missing_payroll_people_are_auto_leavers(tmp_path):
    db = _db()
    previous, current = _periods(db)
    _master(tmp_path, db, previous, [{"姓名": "王五", "证件号码": "110101199003072015", "归属机构代码": "13208", "人员状态": "正常"}])
    result = process_part_time(db, pd.DataFrame([], columns=["姓名", "本期收入"]), None, period_id=current.id)
    assert result["master"].iloc[0]["人员状态"] == "非正常"
    assert result["master"].iloc[0]["离职日期"] == "2026-07-31"


def test_starred_source_headers_are_normalized_for_payroll_master_and_changes(tmp_path):
    db = _db()
    previous, current = _periods(db)
    master_path = tmp_path / "人员信息表202607.xlsx"
    pd.DataFrame([
        {
            "*姓名": "张三", "工号": "PT001", "*归属机构代码": "13208", "*归属机构名称": "营业部一",
            "*证件类型": "居民身份证", "*证件号码": "110101199003072017", "*国籍（地区）": "中国",
            "*性别": "男", "*出生日期": "1990-01-01", "*手机号码": "13800010001",
            "*任职/从业日期": "2026-05-01", "人员状态": "正常",
        },
    ]).to_excel(master_path, index=False)
    db.add(PersonnelMasterArtifact(
        period_id=previous.id, person_type="part_time", scope_type="month", scope_code="",
        file_name=master_path.name, stored_path=str(master_path), row_count=1, validation_issues=[],
    ))
    db.commit()
    payroll = pd.DataFrame([
        {"*姓名": "张三", "*证件号码（同名必填）": "", "*本期收入": "6500"},
        {"*姓名": "赵六", "*证件号码（同名必填）": "110101199001010023", "*本期收入": "5100"},
    ])
    initial = process_part_time(db, payroll, None, period_id=current.id, stage="initial")
    assert not any(issue["issue_type"] in {"invalid_income", "missing_org_code"} for issue in initial["issues"])
    assert any(issue["issue_type"] == "new_part_time_person" for issue in initial["blocking"])

    changes = pd.DataFrame([{
        "*变更类型": "新增", "*姓名": "赵六", "*归属机构代码": "13208", "*归属机构名称": "营业部一",
        "*证件类型": "居民身份证", "*证件号码": "110101199001010023", "*国籍（地区）": "中国",
        "*性别": "女", "*出生日期": "1999-01-03", "*手机号码": "13800010006",
        "*任职/从业日期": "2026-08-01",
    }])
    recheck = process_part_time(db, payroll, changes, period_id=current.id, stage="recheck")
    assert not recheck["blocking"]
    assert recheck["summary"]["income_total"] == 11600.0
    assert recheck["master"].loc[recheck["master"]["姓名"] == "赵六", "归属机构代码"].iloc[0] == "13208"


def test_current_master_is_replaced_by_previous_baseline_and_materialized(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db()
    previous, current = _periods(db)
    previous_path = tmp_path / "人员信息表202607.xlsx"
    current_path = tmp_path / "人员信息表202608旧数据.xlsx"
    row = {"姓名": "张三", "工号": "PT001", "归属机构代码": "13208", "证件类型": "居民身份证", "证件号码": "110101199003072017", "人员状态": "正常"}
    pd.DataFrame([row]).to_excel(previous_path, index=False)
    pd.DataFrame([{**row, "归属机构代码": "99999"}]).to_excel(current_path, index=False)
    db.add_all([
        PersonnelMasterArtifact(period_id=previous.id, person_type="part_time", scope_type="month", scope_code="", file_name=previous_path.name, stored_path=str(previous_path), row_count=1, validation_issues=[]),
        PersonnelMasterArtifact(period_id=current.id, person_type="part_time", scope_type="month", scope_code="", file_name=current_path.name, stored_path=str(current_path), row_count=1, validation_issues=[]),
    ])
    db.commit()
    payroll_path = tmp_path / "payroll.xlsx"
    pd.DataFrame([{"姓名": "张三", "本期收入": 6500}]).to_excel(payroll_path, index=False)
    payroll = UploadedFile(period_id=current.id, file_role="payroll", original_name=payroll_path.name, stored_path=str(payroll_path), size_bytes=payroll_path.stat().st_size, validation_status="uploaded", validation_issues=[])
    result = get_workflow("part_time_tax").run(db, 9301, current.id, [payroll], operation="initial")
    assert result.status == "success"
    assert result.summary["master_source_period"] == "202607"
    assert result.summary["master_source_materialized"] is True
    current_artifact = db.query(PersonnelMasterArtifact).filter(
        PersonnelMasterArtifact.period_id == current.id,
        PersonnelMasterArtifact.person_type == "part_time",
        PersonnelMasterArtifact.scope_type == "month",
    ).first()
    assert current_artifact is not None
    assert str(pd.read_excel(current_artifact.stored_path).iloc[0]["归属机构代码"]) == "13208"


def test_previous_master_filename_month_mismatch_is_non_blocking_warning(tmp_path):
    db = _db()
    previous, current = _periods(db)
    source = tmp_path / "part_time_202606.xlsx"
    pd.DataFrame([{"姓名": "张三", "归属机构代码": "13208", "证件类型": "居民身份证", "证件号码": "110101199003072017", "人员状态": "正常"}]).to_excel(source, index=False)
    db.add(PersonnelMasterArtifact(period_id=previous.id, person_type="part_time", scope_type="month", scope_code="", file_name=source.name, stored_path=str(source), row_count=1, validation_issues=[]))
    db.commit()
    result = process_part_time(db, pd.DataFrame([{"姓名": "张三", "本期收入": 1000}]), None, period_id=current.id)
    assert not result["blocking"]
    assert any(issue["issue_type"] == "master_month_mismatch" for issue in result["issues"])


def test_missing_previous_master_blocks_processing(tmp_path):
    db = _db()
    _, current = _periods(db)
    result = process_part_time(db, pd.DataFrame([{"姓名": "张三", "本期收入": 1000}]), None, period_id=current.id)
    assert any(issue["issue_type"] == "missing_previous_master" for issue in result["blocking"])
