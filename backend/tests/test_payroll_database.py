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
    load_payroll_frames_from_db,
    replace_payroll_imports,
)
from app.services.pit_reconciliation.source_service import PitSourceService
from app.services.verification import _apply_previous_commercial_insurance


def _db():
    # Importing the payroll models above registers the new tables with Base.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _payroll_file(path, employee_no: str, insurance: float) -> str:
    pd.DataFrame([{
        "员工编号": employee_no,
        "姓名": "测试人员",
        "机构代码": "13248",
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
