import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.core import Company, Period
from app.models.income import IncomeImportBatch, IncomeRecord, IncomeWorkpaper
from app.services.income_database import load_income_frames, replace_income_sources, save_income_workpaper
from app.core.config import settings
from app.workflows import get_workflow


def _db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(engine)()
    company = Company(name="测试公司", code="income-test", operator_name="测试")
    db.add(company)
    db.flush()
    period = Period(company_id=company.id, year=2026, month=9, name="2026年09月")
    db.add(period)
    db.commit()
    return db, period


def test_income_source_replacement_removes_old_organisations_and_round_trips():
    db, period = _db()
    replace_income_sources(
        db,
        period=period,
        workflow_code="broker_tax",
        frames={"broker_income": pd.DataFrame([
            {"员工编号": "1", "姓名": "甲", "机构代码": "10001", "收入": 10},
            {"员工编号": "2", "姓名": "乙", "机构代码": "10002", "收入": 20},
        ])},
    )
    db.commit()
    replace_income_sources(
        db,
        period=period,
        workflow_code="broker_tax",
        frames={"broker_income": pd.DataFrame([
            {"员工编号": "3", "姓名": "丙", "机构代码": "10001", "收入": 30},
        ])},
    )
    db.commit()
    assert db.query(IncomeImportBatch).count() == 1
    assert db.query(IncomeRecord).count() == 1
    frame = load_income_frames(
        db,
        company_id=period.company_id,
        period_id=period.id,
        workflow_code="broker_tax",
    )["broker_income"]
    assert frame.iloc[0]["员工编号"] == "3"
    assert "10002" not in frame["机构代码"].tolist()


def test_invalid_income_workpaper_is_stored_as_invalid():
    db, period = _db()
    workpaper = save_income_workpaper(
        db,
        period=period,
        workflow_code="intern_tax",
        detail=pd.DataFrame([{"*姓名": "甲", "本期收入": 100}]),
        summary=pd.DataFrame([{"分支机构代码": "10001", "金额": 100}]),
        issues=[{"issue_type": "missing_id", "message": "缺少证件号码"}],
        status="invalid",
    )
    db.commit()
    assert workpaper.status == "invalid"
    loaded = db.query(IncomeWorkpaper).one()
    assert loaded.detail_json[0]["*姓名"] == "甲"
    assert loaded.issues_json[0]["issue_type"] == "missing_id"


def test_annual_bonus_workflow_can_rerun_from_structured_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db, period = _db()
    replace_income_sources(
        db,
        period=period,
        workflow_code="annual_bonus_tax",
        frames={
            "annual_bonus_sheet": pd.DataFrame([{"员工编号": "1", "员工姓名": "甲", "年终奖汇总": 12000}]),
            "staff_info": pd.DataFrame([{
                "员工编号": "1", "姓名": "甲", "证件类型": "居民身份证",
                "证件号码": "110101199001010011", "人员状态": "正常", "机构代码": "10001",
            }]),
        },
    )
    db.commit()
    result = get_workflow("annual_bonus_tax").run(db, 10001, period.id, [])
    assert result.status == "success", result.summary
    assert result.summary["rows"] == 1
    stored = db.query(IncomeWorkpaper).filter_by(workflow_code="annual_bonus_tax").one()
    assert stored.status == "valid"
    assert stored.detail_json[0]["*全年一次性奖金收入"] == 12000
