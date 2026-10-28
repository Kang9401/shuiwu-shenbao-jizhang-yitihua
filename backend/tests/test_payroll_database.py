from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.core import Company, Period
from app.models.payroll import PayrollEmployeeRecord, PayrollImportBatch, PayrollWorkpaper
from app.services.payroll_database import (
    _employee_id,
    load_payroll_frames_from_db,
    replace_payroll_imports,
    save_payroll_workpaper,
)
from app.services.pit_reconciliation.source_service import PitSourceService
from app.services.verification import _apply_previous_commercial_insurance
from app.services.verification import build_working_sheet, load_headquarters_payroll, verify


def _db():
    # Importing the payroll models above registers the new tables with Base.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _payroll_file(path, employee_no: str, insurance: float, org_code: str = "13248") -> str:
    pd.DataFrame([{
        "员工编号": employee_no,
        "姓名": "测试人员",
        "机构代码": org_code,
        "应发工资 I=A+B+C+D+E-F-G+H+J+K+A10": 10000,
        "个人所得税": 100,
        "累计预扣预缴应纳税所得额": 1000,
        "累计商业保险扣除": insurance,
    }]).to_excel(path, index=False)
    return str(path)


def test_import_replaces_only_same_period_role_and_org(tmp_path):
    db = _db()
    try:
        company = Company(name="工资测试", code="PAYROLL", operator_name="测试")
        db.add(company)
        db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        other_period = Period(company_id=company.id, year=2026, month=8, name="2026-08")
        db.add_all([period, other_period])
        db.flush()

        first = _payroll_file(tmp_path / "first.xlsx", "10001", 80)
        second = _payroll_file(tmp_path / "second.xlsx", "10002", 120)
        previous_month = _payroll_file(tmp_path / "previous.xlsx", "90001", 40)
        replace_payroll_imports(db, period=period, payroll_files=[("rank_salary", first)])
        replace_payroll_imports(db, period=other_period, payroll_files=[("rank_salary", previous_month)])
        db.commit()

        replace_payroll_imports(db, period=period, payroll_files=[("rank_salary", second)])
        db.commit()

        current = load_payroll_frames_from_db(db, company_id=company.id, period_id=period.id, roles={"rank_salary"})
        old_month = load_payroll_frames_from_db(db, company_id=company.id, period_id=other_period.id, roles={"rank_salary"})
        assert current[0][1].iloc[0]["员工编号"] == "10002"
        assert current[0][1].iloc[0]["工资单_累计商业保险扣除"] == pytest.approx(120)
        assert old_month[0][1].iloc[0]["员工编号"] == "90001"
        assert db.query(PayrollImportBatch).filter_by(period_id=period.id).count() == 1
        assert db.query(PayrollEmployeeRecord).filter_by(period_id=period.id).count() == 1
    finally:
        db.close()


def test_reimport_same_org_twice_before_commit_replaces_batch(tmp_path):
    db = _db()
    try:
        company = Company(name="工资同事务覆盖测试", code="PAYROLL_SAME_TX", operator_name="测试")
        db.add(company); db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add(period); db.flush()
        first = _payroll_file(tmp_path / "first.xlsx", "10001", 80, "11888")
        second = _payroll_file(tmp_path / "second.xlsx", "10002", 90, "11888")
        replace_payroll_imports(db, period=period, payroll_files=[("rank_salary", first)])
        replace_payroll_imports(db, period=period, payroll_files=[("rank_salary", second)])
        db.commit()
        rows = load_payroll_frames_from_db(
            db, company_id=company.id, period_id=period.id, roles={"rank_salary"},
        )
        assert rows[0][1].iloc[0]["员工编号"] == "10002"
        assert db.query(PayrollImportBatch).filter_by(
            company_id=company.id, period_id=period.id, salary_type="rank_salary", org_code="11888",
        ).count() == 1
    finally:
        db.close()


def test_reimport_replaces_complete_role_scope_and_keeps_other_roles(tmp_path):
    db = _db()
    try:
        company = Company(name="工资覆盖测试", code="PAYROLL_SCOPE", operator_name="测试")
        db.add(company); db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add(period); db.flush()
        first = _payroll_file(tmp_path / "first.xlsx", "10001", 80, "13248")
        second = _payroll_file(tmp_path / "second.xlsx", "10002", 90, "13266")
        marketing = _payroll_file(tmp_path / "marketing.xlsx", "1000001", 30, "13248")
        replace_payroll_imports(db, period=period, payroll_files=[
            ("rank_salary", first), ("marketing_salary", marketing),
        ])
        db.commit()
        replace_payroll_imports(db, period=period, payroll_files=[("rank_salary", second)])
        db.commit()
        rank = load_payroll_frames_from_db(db, company_id=company.id, period_id=period.id, roles={"rank_salary"})
        all_frames = load_payroll_frames_from_db(db, company_id=company.id, period_id=period.id)
        assert rank[0][1].iloc[0]["员工编号"] == "10002"
        assert rank[0][1].iloc[0]["机构代码"] == "13266"
        assert {role for role, _ in all_frames} == {"rank_salary", "marketing_salary"}
        assert all(frame.iloc[0]["员工编号"] != "10001" for role, frame in all_frames if role == "rank_salary")
    finally:
        db.close()


def test_last_import_batch_is_visible_to_same_transaction_reader(tmp_path):
    """The final source must be readable before the request commits.

    The API replaces all uploaded roles and immediately rebuilds the working
    sheet in the same SQLAlchemy session.  With autoflush disabled, the last
    batch used to remain pending and disappear from that read (the common
    case was the headquarters payroll uploaded after rank/marketing files).
    """
    db = _db()
    try:
        company = Company(name="工资同事务读取测试", code="PAYROLL_FLUSH", operator_name="测试")
        db.add(company); db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add(period); db.flush()

        rank = _payroll_file(tmp_path / "rank.xlsx", "10001", 80)
        headquarters_path = tmp_path / "headquarters.xlsx"
        pd.DataFrame([{
            "薪资期间": "2026-09", "薪资方案": "总部方案A", "个税申报地": "成都",
            "个税类型": "工资薪金", "姓名": "总部员工", "员工编号": "H001",
            "机构代码": "17020", "本期收入": 10000, "个人所得税": 100,
            "累计预扣预缴应纳税所得额": 1000,
        }]).to_excel(headquarters_path, index=False)

        replace_payroll_imports(db, period=period, payroll_files=[
            ("rank_salary", rank), ("headquarters_salary", str(headquarters_path)),
        ])

        frames = load_payroll_frames_from_db(
            db, company_id=company.id, period_id=period.id,
        )
        assert {role for role, _ in frames} == {"rank_salary", "headquarters_salary"}
        assert len(next(frame for role, frame in frames if role == "headquarters_salary")) == 1
    finally:
        db.close()


def test_parse_failure_does_not_delete_existing_rows(tmp_path):
    db = _db()
    try:
        company = Company(name="工资失败测试", code="PAYROLL_FAIL", operator_name="测试")
        db.add(company)
        db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add(period)
        db.flush()
        good = _payroll_file(tmp_path / "good.xlsx", "10001", 80)
        replace_payroll_imports(db, period=period, payroll_files=[("rank_salary", good)])
        db.commit()

        bad_path = tmp_path / "bad.xlsx"
        pd.DataFrame([{"员工编号": "10001", "姓名": "测试人员"}]).to_excel(bad_path, index=False)
        with pytest.raises(ValueError):
            replace_payroll_imports(db, period=period, payroll_files=[("rank_salary", str(bad_path))])
        db.rollback()

        rows = load_payroll_frames_from_db(db, company_id=company.id, period_id=period.id, roles={"rank_salary"})
        assert rows[0][1].iloc[0]["员工编号"] == "10001"
        assert rows[0][1].iloc[0]["工资单_累计商业保险扣除"] == pytest.approx(80)
    finally:
        db.close()


def test_scalar_employee_id_normalization_does_not_call_dataframe_str_methods():
    assert _employee_id("00123.0") == "00123"
    assert _employee_id(123) == "123"


def test_database_personnel_snapshot_does_not_create_duplicate_merge_columns(tmp_path):
    db = _db()
    try:
        company = Company(name="工资合并列测试", code="PAYROLL_MERGE", operator_name="测试")
        db.add(company); db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add(period); db.flush()
        payroll_path = _payroll_file(tmp_path / "payroll.xlsx", "10001", 80)
        staff_path = tmp_path / "staff.xlsx"
        pd.DataFrame([{
            "员工编号": "10001", "*姓名": "测试人员", "证件类型": "居民身份证",
            "证件号码": "110101199001010011", "机构代码": "13248", "人员状态": "正常",
        }]).to_excel(staff_path, index=False)
        replace_payroll_imports(
            db,
            period=period,
            payroll_files=[("rank_salary", payroll_path)],
            staff_info_path=str(staff_path),
        )
        db.commit()
        frames = load_payroll_frames_from_db(
            db, company_id=company.id, period_id=period.id,
        )
        sheet, _ = build_working_sheet(
            [], str(staff_path), "", payroll_frames=[frame for _, frame in frames],
        )
        assert "机构代码_人员信息表" in sheet.columns
        assert not isinstance(sheet["机构代码_人员信息表"], pd.DataFrame)
        assert sheet.iloc[0]["证件类型"] == "居民身份证"
        assert sheet.iloc[0]["证件号码"] == "110101199001010011"
        assert verify(sheet)["missing_cert"]["items"] == []
    finally:
        db.close()


def test_previous_database_rows_keep_cumulative_value_and_apply_existing_delta(tmp_path):
    db = _db()
    try:
        company = Company(name="工资累计测试", code="PAYROLL_DELTA", operator_name="测试")
        db.add(company)
        db.flush()
        previous = Period(company_id=company.id, year=2026, month=8, name="2026-08")
        current = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add_all([previous, current])
        db.flush()
        replace_payroll_imports(db, period=previous, payroll_files=[("rank_salary", _payroll_file(tmp_path / "p.xlsx", "10001", 80))])
        replace_payroll_imports(db, period=current, payroll_files=[("rank_salary", _payroll_file(tmp_path / "c.xlsx", "10001", 100))])
        db.commit()
        previous_frame = load_payroll_frames_from_db(db, company_id=company.id, period_id=previous.id, roles={"rank_salary"})[0][1]
        current_frame = load_payroll_frames_from_db(db, company_id=company.id, period_id=current.id, roles={"rank_salary"})[0][1]
        assert previous_frame.iloc[0]["工资单_累计商业保险扣除"] == pytest.approx(80)
        _apply_previous_commercial_insurance(current_frame, [previous_frame])
        assert current_frame.iloc[0]["工资单_累计商业保险扣除"] == pytest.approx(20)
        assert current_frame.iloc[0]["商业健康保险"] == pytest.approx(20)
    finally:
        db.close()


def test_pit_salary_source_prefers_database_workpaper(tmp_path):
    db = _db()
    try:
        company = Company(name="工资底稿测试", code="PAYROLL_PIT", operator_name="测试")
        db.add(company)
        db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add(period)
        db.flush()
        frame = pd.DataFrame([{
            "机构代码_工资单": "13248",
            "*姓名": "测试人员",
            "员工编号": "10001",
            "证件号码": "ID-1",
            "工资单类型": "职级工资单",
            "个人所得税 SUM": 100,
            "工资表_累计应纳税所得额": 1000,
            "工资表_累计减除费用": 5000,
            "工资表_累计养老保险金员工部分": 10,
            "工资表_累计医疗保险金员工部分": 10,
            "工资表_累计失业保险金员工部分": 10,
            "工资表_累计住房公积金员工部分": 10,
            "工资单_累计子女教育扣除": 0,
            "工资单_累计继续教育扣除": 0,
            "工资单_累计住房贷款利息扣除": 0,
            "工资单_累计住房租金扣除": 0,
            "工资单_累计赡养老人扣除": 0,
            "工资单_累计婴幼儿照护扣除": 0,
            "工资单_累计个人养老金": 0,
            "工资表_累计企业年金员工部分": 0,
            "工资表_累计商业保险扣除": 0,
        }])
        db.add(PayrollWorkpaper(
            company_id=company.id,
            period_id=period.id,
            sheet_rows_json=frame.to_dict(orient="records"),
            report_json={},
            manual_json={},
        ))
        db.commit()
        source = PitSourceService(db, company.id, period.id).load_salary_source()
        assert source.status == "ready"
        assert source.source_kind == "payroll_workpaper"
        assert source.rows[0].cumulative_taxable_income == 1000
    finally:
        db.close()


def test_invalid_workpaper_is_not_treated_as_a_valid_salary_source():
    db = _db()
    try:
        company = Company(name="工资失效测试", code="PAYROLL_INVALID", operator_name="测试")
        db.add(company); db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add(period); db.flush()
        save_payroll_workpaper(
            db,
            period=period,
            sheet=pd.DataFrame([{"员工编号": "10001", "工资单类型": "职级工资单"}]),
            report={"summary": {"has_blocking_issues": True}},
            status="invalid",
        )
        db.commit()
        assert db.query(PayrollWorkpaper).filter_by(period_id=period.id).one().status == "invalid"
        source = PitSourceService(db, company.id, period.id).load_salary_source()
        assert source.status == "invalid"
        assert source.source_kind == "payroll_workpaper"
        assert source.issues[0]["issue_type"] == "payroll_workpaper_invalid"
    finally:
        db.close()


def test_headquarters_original_context_fields_survive_normalization_and_db(tmp_path):
    path = tmp_path / "headquarters.xlsx"
    pd.DataFrame([{
        "薪资期间": "2026-09", "薪资方案": "总部方案A", "个税申报地": "成都",
        "个税类型": "工资薪金", "姓名": "总部员工", "员工编号": "H001",
        "机构代码": "13248", "本期收入": 10000, "个人所得税": 100,
        "累计预扣预缴应纳税所得额": 1000,
    }]).to_excel(path, index=False)
    frame = load_headquarters_payroll(str(path))
    assert frame.iloc[0]["薪资期间"] == "2026-09"
    assert frame.iloc[0]["薪资方案"] == "总部方案A"
    assert frame.iloc[0]["个税申报地"] == "成都"
    assert frame.iloc[0]["个税类型"] == "工资薪金"
    assert frame.iloc[0]["总部原始字段"]["薪资方案"] == "总部方案A"

    db = _db()
    try:
        company = Company(name="总部字段测试", code="PAYROLL_HQ", operator_name="测试")
        db.add(company); db.flush()
        period = Period(company_id=company.id, year=2026, month=9, name="2026-09")
        db.add(period); db.flush()
        replace_payroll_imports(db, period=period, payroll_files=[("headquarters_salary", str(path))])
        db.commit()
        restored = load_payroll_frames_from_db(db, company_id=company.id, period_id=period.id)[0][1].iloc[0]
        assert restored["薪资期间"] == "2026-09"
        assert restored["薪资方案"] == "总部方案A"
        assert restored["个税申报地"] == "成都"
        assert restored["个税类型"] == "工资薪金"
        assert restored["总部原始字段"]["薪资期间"] == "2026-09"
    finally:
        db.close()
