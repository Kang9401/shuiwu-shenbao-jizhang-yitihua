from pathlib import Path

import pandas as pd
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.session import Base
from app.models.accounting import OrganizationMapping, PersonnelMasterArtifact, PersonnelMasterImportBatch, ReconciliationImportBatch
from app.models.core import Period, UploadedFile as UploadedFileModel
from app.rpa.service import RpaService
from app.rpa.state_store import StateStore
from app.services.personnel_master import (
    PersonnelMasterResolver,
    PersonnelMasterValidationError,
    import_personnel_master,
    list_rpa_organizations,
)
from app.workflows import get_workflow


def _db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return testing_session_local()


def _upload(path: Path) -> UploadFile:
    return UploadFile(filename=path.name, file=path.open("rb"))


def test_personnel_master_imports_month_org_and_branch_then_exports(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db_session()
    period = Period(year=2025, month=2, name="2025-02")
    db.add(period)
    db.commit()
    db.refresh(period)

    month_file = tmp_path / "employee_month.xlsx"
    org_file = tmp_path / "intern_org.xlsx"
    branch_file = tmp_path / "broker_branch.xlsx"
    pd.DataFrame([{"姓名": "张三", "证件号码": "1"}]).to_excel(month_file, index=False)
    pd.DataFrame([{"姓名": "李四", "证件号码": "2", "机构代码": "10301"}]).to_excel(org_file, index=False)
    pd.DataFrame([{"姓名": "王五", "证件号码": "3", "分公司代码": "XA"}]).to_excel(branch_file, index=False)

    month = import_personnel_master(db, period_id=period.id, person_type="employee", scope_type="month", scope_code=None, file=_upload(month_file))
    org = import_personnel_master(db, period_id=period.id, person_type="intern", scope_type="org", scope_code="10301", file=_upload(org_file))
    branch = import_personnel_master(db, period_id=period.id, person_type="broker", scope_type="branch", scope_code="XA", file=_upload(branch_file))

    assert Path(month.stored_path).exists()
    assert pd.read_excel(month.stored_path).iloc[0]["姓名"] == "张三"
    assert org.scope_code == "10301"
    assert branch.scope_code == "XA"
    assert db.query(PersonnelMasterArtifact).count() == 3
    assert db.query(PersonnelMasterImportBatch).count() == 3
    db.close()


def test_personnel_master_reimport_overwrites_current_and_keeps_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db_session()
    period = Period(year=2025, month=2, name="2025-02")
    db.add(period)
    db.commit()
    db.refresh(period)

    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    pd.DataFrame([{"姓名": "张三", "证件号码": "1"}]).to_excel(first, index=False)
    pd.DataFrame([{"姓名": "李四", "证件号码": "2"}]).to_excel(second, index=False)

    import_personnel_master(db, period_id=period.id, person_type="employee", scope_type="month", scope_code=None, file=_upload(first))
    artifact = import_personnel_master(db, period_id=period.id, person_type="employee", scope_type="month", scope_code=None, file=_upload(second))

    assert db.query(PersonnelMasterArtifact).count() == 1
    assert db.query(PersonnelMasterImportBatch).count() == 2
    assert pd.read_excel(artifact.stored_path).iloc[0]["姓名"] == "李四"
    db.close()


def test_personnel_master_validation_blocks_missing_columns_without_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db_session()
    period = Period(year=2025, month=2, name="2025-02")
    db.add(period)
    db.commit()
    db.refresh(period)

    bad = tmp_path / "bad.xlsx"
    pd.DataFrame([{"姓名": "张三"}]).to_excel(bad, index=False)

    try:
        import_personnel_master(db, period_id=period.id, person_type="employee", scope_type="month", scope_code=None, file=_upload(bad))
    except PersonnelMasterValidationError as exc:
        assert exc.issues[0]["issue_type"] == "missing_column"
    else:
        raise AssertionError("expected validation error")
    assert db.query(PersonnelMasterArtifact).count() == 0
    assert db.query(PersonnelMasterImportBatch).count() == 0
    db.close()


def test_personnel_master_duplicate_validation_only_blocks_active_status(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db_session()
    period = Period(year=2025, month=2, name="2025-02")
    db.add(period)
    db.commit()
    db.refresh(period)

    resigned_duplicate = tmp_path / "resigned_duplicate.xlsx"
    pd.DataFrame([
        {"姓名": "张三", "证件号码": "1", "人员状态": "正常"},
        {"姓名": "张三", "证件号码": "1", "人员状态": "非正常"},
    ]).to_excel(resigned_duplicate, index=False)
    artifact = import_personnel_master(
        db,
        period_id=period.id,
        person_type="employee",
        scope_type="month",
        scope_code=None,
        file=_upload(resigned_duplicate),
    )
    assert artifact.row_count == 2

    active_duplicate = tmp_path / "active_duplicate.xlsx"
    pd.DataFrame([
        {"姓名": "李四", "证件号码": "2", "人员状态": "正常"},
        {"姓名": "李四", "证件号码": "2", "人员状态": "正常"},
    ]).to_excel(active_duplicate, index=False)
    try:
        import_personnel_master(
            db,
            period_id=period.id,
            person_type="employee",
            scope_type="month",
            scope_code=None,
            file=_upload(active_duplicate),
        )
    except PersonnelMasterValidationError as exc:
        assert {issue["issue_type"] for issue in exc.issues} == {"duplicate_id_number"}
        assert all(issue["status"] == "正常" for issue in exc.issues)
    else:
        raise AssertionError("expected validation error")
    db.close()


def test_rpa_organizations_use_mapping_metadata_and_exclude_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db_session()
    period = Period(year=2025, month=2, name="2025-02")
    db.add(period)
    db.commit()
    db.refresh(period)
    employee = tmp_path / "employee_rpa.xlsx"
    pd.DataFrame([
        {"姓名": "张三", "证件号码": "1", "机构代码": "10001"},
        {"姓名": "李四", "证件号码": "2", "机构代码": "10001"},
        {"姓名": "王五", "证件号码": "3", "机构代码": "10002"},
    ]).to_excel(employee, index=False)
    import_personnel_master(
        db, period_id=period.id, person_type="employee", scope_type="month", scope_code=None, file=_upload(employee)
    )
    db.add_all([
        OrganizationMapping(
            branch_name="营业部一", org_code="10001", active=1, rpa_enabled=1,
            rpa_org_name="第一证券营业部", parent_branch="华东分公司",
        ),
        OrganizationMapping(
            branch_name="营业部二", org_code="10002", active=1, rpa_enabled=0,
            rpa_org_name="第二证券营业部", parent_branch="华南分公司",
        ),
        OrganizationMapping(
            branch_name="营业部三", org_code="10003", active=1, rpa_enabled=1,
            rpa_org_name="第三证券营业部", parent_branch="华北分公司",
        ),
    ])
    db.commit()

    expected = [
        {
            "code": "10001",
            "name": "第一证券营业部",
            "parent_branch": "华东分公司",
            "employee_count": 2,
        },
        {
            "code": "10003",
            "name": "第三证券营业部",
            "parent_branch": "华北分公司",
            "employee_count": 0,
        },
    ]
    assert list_rpa_organizations(db, period_id=period.id) == expected

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    monkeypatch.setattr("app.rpa.service.ensure_runtime_app", lambda: runtime_dir)
    path, selected = RpaService(store=StateStore(tmp_path / "state.json")).prepare_runtime_org_excel(
        db, period_id=period.id
    )
    assert selected == expected
    assert pd.read_excel(path, dtype=str).to_dict("records") == [
        {"机构名称": "第一证券营业部", "机构代码": "10001"},
        {"机构名称": "第三证券营业部", "机构代码": "10003"},
    ]
    db.close()


def test_restricted_stock_uses_period_balance_without_personnel_master(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db_session()
    period = Period(year=2025, month=2, name="2025-02")
    db.add(period)
    db.commit()
    db.refresh(period)

    employee = tmp_path / "employee.xlsx"
    tax_sheet = tmp_path / "tax.xlsx"
    balance_sheet = tmp_path / "balance.xlsx"
    pd.DataFrame([{"姓名": "员工", "证件号码": "1"}]).to_excel(employee, index=False)
    pd.DataFrame().to_excel(tax_sheet, index=False)
    pd.DataFrame([{"公司段": "10301", "会计科目": "21510009", "币种": "CNY", "贷方金额(N)": 0}]).to_excel(balance_sheet, index=False)
    import_personnel_master(db, period_id=period.id, person_type="employee", scope_type="month", scope_code=None, file=_upload(employee))

    assert "employee" in PersonnelMasterResolver(db, period.id).resolve_path("employee")
    db.add(ReconciliationImportBatch(
        period_id=period.id,
        import_type="balance_sheet",
        original_name=balance_sheet.name,
        stored_path=str(balance_sheet),
        row_count=1,
        validation_issues=[],
    ))
    db.commit()

    uploaded = UploadedFileModel(
        period_id=period.id,
        file_role="tax_sheet",
        original_name="tax.xlsx",
        stored_path=str(tax_sheet),
        size_bytes=tax_sheet.stat().st_size,
        validation_status="uploaded",
        validation_issues=[],
    )
    result = get_workflow("restricted_stock_interest_tax").run(
        db, 9100, period.id, [uploaded], operation="reconcile",
    )
    assert result.summary["shared_staff_info"] is False
    assert result.summary["shared_balance_sheet"] is True
    db.close()
