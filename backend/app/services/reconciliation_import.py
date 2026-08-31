from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models.accounting import ReconciliationImportBatch, ReconciliationImportRow
from app.services.excel import dataframe_records, read_excel
from app.services.storage import save_upload


IMPORT_TYPES = {"bank_statement", "declaration_result", "accounting_ledger", "balance_sheet", "pit_declaration", "tax_certificate"}


class ReconciliationImportValidationError(ValueError):
    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = issues
        super().__init__("；".join(issue["message"] for issue in issues))


def _clean(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _first_existing(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    return None


def _to_decimal(value: Any) -> Optional[Decimal]:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def read_balance_sheet(path: str | Path) -> pd.DataFrame:
    """Read balance exports whose account header may follow report metadata rows."""
    raw = pd.read_excel(path, header=None, dtype=object).fillna("")
    for header_index, row in raw.iterrows():
        headers = [_clean(value) for value in row.tolist()]
        if "会计科目" not in headers or "公司段" not in headers:
            continue
        data = raw.iloc[header_index + 1:].copy()
        data.columns = headers
        data = data.loc[:, [column for column in data.columns if column]]
        data = data[~data.apply(lambda item: all(not _clean(value) for value in item), axis=1)]
        return data.reset_index(drop=True)
    return read_excel(path).fillna("")


def _column_map(import_type: str, df: pd.DataFrame) -> dict[str, Optional[str]]:
    columns = df.columns
    common = {
        "organization_code": _first_existing(columns, ["机构代码", "分支机构代码", "单位编号", "公司段"]),
        "branch_code": _first_existing(columns, ["分公司代码", "分公司", "分支机构代码"]),
    }
    if import_type == "bank_statement":
        return {
            **common,
            "transaction_date": _first_existing(columns, ["交易日期", "交易时间", "记账日期", "发生日期", "日期"]),
            "summary": _first_existing(columns, ["摘要", "用途", "交易摘要", "备注"]),
            "counterparty": _first_existing(columns, ["对方户名", "对方账户名称", "对方名称", "付款方", "收款方"]),
            "amount": _first_existing(columns, ["金额", "交易金额", "发生额", "收入", "支出"]),
            "serial_no": _first_existing(columns, ["流水号", "交易流水号", "银行流水号", "凭证号"]),
        }
    if import_type == "declaration_result":
        return {
            **common,
            "declaration_type": _first_existing(columns, ["申报类型", "所得项目", "税种", "申报表类型"]),
            "taxpayer_name": _first_existing(columns, ["纳税人姓名", "姓名", "*姓名", "人员姓名"]),
            "income_amount": _first_existing(columns, ["收入", "收入额", "本期收入", "全年一次性奖金收入"]),
            "tax_amount": _first_existing(columns, ["税额", "应纳税额", "应补退税额", "本期应预扣预缴税额"]),
            "declaration_status": _first_existing(columns, ["申报状态", "状态", "处理状态"]),
            "tax_period": _first_existing(columns, ["税款所属期", "所属期", "申报月份"]),
        }
    return {
        **common,
        "transaction_date": _first_existing(columns, ["日期", "凭证日期", "记账日期", "业务日期"]),
        "summary": _first_existing(columns, ["摘要", "凭证摘要", "说明"]),
        "amount": _first_existing(columns, ["金额", "本位币金额", "借方金额", "贷方金额", "贷方金额(N)", "发生额"]),
        "account_code": _first_existing(columns, ["科目编码", "会计科目", "科目代码"]),
        "account_name": _first_existing(columns, ["科目名称", "会计科目名称", "科目"]),
        "auxiliary": _first_existing(columns, ["辅助核算", "辅助项", "往来单位"]),
        "debit_credit": _first_existing(columns, ["借贷方向", "方向", "借贷"]),
        "voucher_no": _first_existing(columns, ["凭证号", "凭证编号", "单据号"]),
    }


def _validate(import_type: str, mapping: dict[str, Optional[str]]) -> list[dict[str, Any]]:
    required = {
        "bank_statement": ["transaction_date", "amount"],
        "declaration_result": ["taxpayer_name", "tax_amount"],
        "accounting_ledger": ["account_code", "amount"],
        "balance_sheet": ["account_code", "amount"],
    }[import_type]
    issues = []
    for key in required:
        if mapping.get(key) is None:
            issues.append({
                "issue_type": "missing_column",
                "message": f"{import_type} 导入缺少关键列：{key}",
                "field": key,
            })
    return issues


def import_reconciliation_file(
    db: Session,
    *,
    period_id: int,
    import_type: str,
    file: UploadFile,
) -> ReconciliationImportBatch:
    if import_type not in IMPORT_TYPES:
        raise ReconciliationImportValidationError([{"issue_type": "invalid_import_type", "message": "导入类型不合法"}])
    source_path, _ = save_upload(file, period_id, f"reconciliation_{import_type}")
    df = read_balance_sheet(source_path) if import_type == "balance_sheet" else read_excel(source_path).fillna("")
    mapping = _column_map(import_type, df)
    issues = _validate(import_type, mapping)
    if issues:
        raise ReconciliationImportValidationError(issues)

    batch = ReconciliationImportBatch(
        period_id=period_id,
        import_type=import_type,
        original_name=file.filename or f"{import_type}.xlsx",
        stored_path=str(source_path),
        row_count=int(len(df)),
        validation_issues=[],
    )
    db.add(batch)
    db.flush()

    for idx, row in enumerate(dataframe_records(df), start=2):
        db.add(
            ReconciliationImportRow(
                batch_id=batch.id,
                period_id=period_id,
                import_type=import_type,
                row_number=idx,
                organization_code=_clean(row.get(mapping.get("organization_code"))) if mapping.get("organization_code") else None,
                branch_code=_clean(row.get(mapping.get("branch_code"))) if mapping.get("branch_code") else None,
                transaction_date=_clean(row.get(mapping.get("transaction_date"))) if mapping.get("transaction_date") else None,
                summary=_clean(row.get(mapping.get("summary"))) if mapping.get("summary") else None,
                counterparty=_clean(row.get(mapping.get("counterparty"))) if mapping.get("counterparty") else None,
                amount=_to_decimal(row.get(mapping.get("amount"))) if mapping.get("amount") else None,
                serial_no=_clean(row.get(mapping.get("serial_no"))) if mapping.get("serial_no") else None,
                declaration_type=_clean(row.get(mapping.get("declaration_type"))) if mapping.get("declaration_type") else None,
                taxpayer_name=_clean(row.get(mapping.get("taxpayer_name"))) if mapping.get("taxpayer_name") else None,
                income_amount=_to_decimal(row.get(mapping.get("income_amount"))) if mapping.get("income_amount") else None,
                tax_amount=_to_decimal(row.get(mapping.get("tax_amount"))) if mapping.get("tax_amount") else None,
                declaration_status=_clean(row.get(mapping.get("declaration_status"))) if mapping.get("declaration_status") else None,
                tax_period=_clean(row.get(mapping.get("tax_period"))) if mapping.get("tax_period") else None,
                account_code=_clean(row.get(mapping.get("account_code"))) if mapping.get("account_code") else None,
                account_name=_clean(row.get(mapping.get("account_name"))) if mapping.get("account_name") else None,
                auxiliary=_clean(row.get(mapping.get("auxiliary"))) if mapping.get("auxiliary") else None,
                debit_credit=_clean(row.get(mapping.get("debit_credit"))) if mapping.get("debit_credit") else None,
                voucher_no=_clean(row.get(mapping.get("voucher_no"))) if mapping.get("voucher_no") else None,
                raw_data=row,
            )
        )
    db.commit()
    db.refresh(batch)
    return batch


def import_pit_declaration_file(db: Session, *, period_id: int, file: UploadFile) -> ReconciliationImportBatch:
    """Import official PIT declaration exports with their multi-row headers preserved."""
    from app.services.pit_reconciliation.parsers.declaration_parser import parse_declaration_file
    source_path, _ = save_upload(file, period_id, "pit_declaration")
    records, issues = parse_declaration_file(source_path)
    if issues and not records:
        raise ReconciliationImportValidationError(issues)
    batch = ReconciliationImportBatch(period_id=period_id, import_type="pit_declaration", original_name=file.filename or "pit_declaration.xlsx", stored_path=str(source_path), row_count=len(records), validation_issues=issues)
    db.add(batch); db.flush()
    for number, raw in enumerate(records, start=1):
        db.add(ReconciliationImportRow(batch_id=batch.id, period_id=period_id, import_type="pit_declaration", row_number=number, organization_code=_clean(raw.get("机构代码")), declaration_type=_clean(raw.get("sheet_name")), taxpayer_name=_clean(raw.get("纳税人姓名") or raw.get("姓名")), income_amount=_to_decimal(raw.get("收入额") or raw.get("本期收入") or raw.get("收入")), tax_amount=_to_decimal(raw.get("应补退税额") or raw.get("扣缴税额") or raw.get("税额")), tax_period=_clean(raw.get("tax_period")), raw_data=raw))
    db.commit(); db.refresh(batch); return batch


def import_tax_certificate_files(db: Session, *, period_id: int, files: list[UploadFile]) -> ReconciliationImportBatch:
    from app.services.pit_reconciliation.parsers.tax_certificate_parser import parse_tax_certificate_pdf
    if not files:
        raise ReconciliationImportValidationError([{"issue_type": "missing_file", "message": "请至少上传一份完税证明 PDF"}])
    batch = ReconciliationImportBatch(period_id=period_id, import_type="tax_certificate", original_name="完税证明批量导入", stored_path="", row_count=0, validation_issues=[])
    db.add(batch); db.flush(); all_issues=[]; count=0; paths=[]
    for file in files:
        path, _ = save_upload(file, period_id, "tax_certificate")
        paths.append(str(path)); records, issues = parse_tax_certificate_pdf(path); all_issues.extend([{**issue, "file_name": file.filename} for issue in issues])
        for raw in records:
            count += 1
            db.add(ReconciliationImportRow(batch_id=batch.id, period_id=period_id, import_type="tax_certificate", row_number=count, organization_code=_clean(raw.get("org_code")), counterparty=_clean(raw.get("taxpayer_name")), amount=_to_decimal(raw.get("amount")), tax_period=_clean(raw.get("tax_period")), raw_data={**raw, "file_name": file.filename}))
    batch.stored_path=";".join(paths); batch.row_count=count; batch.validation_issues=all_issues
    db.commit(); db.refresh(batch); return batch


def list_reconciliation_batches(
    db: Session,
    *,
    period_id: Optional[int] = None,
    import_type: Optional[str] = None,
) -> list[ReconciliationImportBatch]:
    from app.core.company_context import current_company_id
    query = db.query(ReconciliationImportBatch).filter(ReconciliationImportBatch.company_id == current_company_id())
    if period_id is not None:
        query = query.filter(ReconciliationImportBatch.period_id == period_id)
    if import_type:
        query = query.filter(ReconciliationImportBatch.import_type == import_type)
    return query.order_by(ReconciliationImportBatch.created_at.desc()).limit(200).all()
