from pathlib import Path

import pandas as pd
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.session import Base
from app.models.accounting import ReconciliationImportBatch, ReconciliationImportRow
from app.models.core import Period
from app.services.reconciliation_import import (
    ReconciliationImportValidationError,
    import_reconciliation_file,
)


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


def _period(db):
    period = Period(year=2025, month=2, name="2025-02")
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


def test_imports_bank_statement_declaration_result_and_accounting_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db_session()
    period = _period(db)

    bank = tmp_path / "bank.xlsx"
    declaration = tmp_path / "declaration.xlsx"
    ledger = tmp_path / "ledger.xlsx"
    pd.DataFrame([{"交易日期": "2025-02-10", "摘要": "缴税", "金额": "100.50", "流水号": "B1"}]).to_excel(bank, index=False)
    pd.DataFrame([{"纳税人姓名": "张三", "税额": "100", "申报类型": "工资薪金"}]).to_excel(declaration, index=False)
    pd.DataFrame([{"科目编码": "2221", "金额": "100", "凭证号": "V1"}]).to_excel(ledger, index=False)

    import_reconciliation_file(db, period_id=period.id, import_type="bank_statement", file=_upload(bank))
    import_reconciliation_file(db, period_id=period.id, import_type="declaration_result", file=_upload(declaration))
    import_reconciliation_file(db, period_id=period.id, import_type="accounting_ledger", file=_upload(ledger))

    assert db.query(ReconciliationImportBatch).count() == 3
    assert db.query(ReconciliationImportRow).count() == 3
    row = db.query(ReconciliationImportRow).filter(ReconciliationImportRow.import_type == "bank_statement").first()
    assert row.amount == 100.50
    assert row.serial_no == "B1"
    db.close()


def test_import_missing_required_columns_does_not_create_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db_session()
    period = _period(db)
    bad = tmp_path / "bad.xlsx"
    pd.DataFrame([{"摘要": "缴税"}]).to_excel(bad, index=False)

    try:
        import_reconciliation_file(db, period_id=period.id, import_type="bank_statement", file=_upload(bad))
    except ReconciliationImportValidationError as exc:
        assert exc.issues[0]["issue_type"] == "missing_column"
    else:
        raise AssertionError("expected validation error")

    assert db.query(ReconciliationImportBatch).count() == 0
    assert db.query(ReconciliationImportRow).count() == 0
    db.close()


def test_imports_balance_sheet_for_period_reuse(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db_session()
    period = _period(db)
    balance = tmp_path / "balance.xlsx"
    pd.DataFrame([
        {"公司段": "10301", "会计科目": "21510009", "币种": "CNY", "贷方金额(N)": "100.00"},
    ]).to_excel(balance, index=False)

    batch = import_reconciliation_file(
        db, period_id=period.id, import_type="balance_sheet", file=_upload(balance),
    )

    assert batch.import_type == "balance_sheet"
    assert batch.row_count == 1
    assert Path(batch.stored_path).exists()
    db.close()


def test_imports_balance_sheet_with_report_metadata_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    db = _db_session()
    period = _period(db)
    balance = tmp_path / "balance_with_metadata.xlsx"
    metadata = pd.DataFrame([
        ["账套范围：", "2022", "本位币：", "CNY"],
        ["截止日期：", "2025-02-28"],
        ["币种：", "ALL"],
    ])
    data = pd.DataFrame([
        {"币种": "CNY", "会计科目": "21510009", "描述": "应交税费", "借方金额(N)": "10", "贷方金额(N)": "100", "公司段": "10301"},
    ])
    with pd.ExcelWriter(balance, engine="openpyxl") as writer:
        metadata.to_excel(writer, index=False, header=False)
        data.to_excel(writer, index=False, startrow=12)

    batch = import_reconciliation_file(
        db, period_id=period.id, import_type="balance_sheet", file=_upload(balance),
    )

    row = db.query(ReconciliationImportRow).filter(ReconciliationImportRow.batch_id == batch.id).first()
    assert batch.row_count == 1
    assert row.account_code == "21510009"
    assert row.organization_code == "10301"
    assert row.amount == 100
    db.close()
