from __future__ import annotations

from io import BytesIO
from decimal import Decimal, InvalidOperation
import re

import pandas as pd
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.company_context import current_company_id
from app.integrations.fmss.branch_code import to_fmss_branch_code
from app.integrations.fmss.client import FmssClient
from app.integrations.fmss.errors import FmssApiError
from app.models.accounting import OrganizationMapping
from app.models.core import Company, Period, UploadedFile
from app.services.formulas import normalize_org_code
from app.services.reconciliation_import import import_reconciliation_file
from app.services.storage import save_upload


COMMON_FIELDS = {
    "branchNo": "机构代码", "branchName": "营业部名称", "clientName": "客户姓名",
    "idKind": "证件类型", "idNo": "证件号码", "stockAccount": "证券账号",
    "stockCode": "证券代码", "stockName": "证券名称", "initDate": "业务日期",
    "clientId": "客户编号", "fundAccount": "资产账号", "mobileTel": "手机号码",
    "homePhone": "家庭电话", "address": "联系地址", "nationality": "国籍(地区)", "birthday": "出生日期",
    "clientGender": "性别",
}
SECURITY_FIELDS = {
    "interest_tax": {"businessBalance": "债券兑息", "totalTax": "兑息扣税", "taxRatio": "税率（%）", "remark": "备注"},
    "tax_sheet": {
        "businessAmount": "成交数量", "businessPrice": "成交价格", "sdsBalance": "成交金额",
        "originalBalance": "原值总金额", "taxFare": "利息税", "sellFare0": "卖出经手费",
        "sellFare1": "卖出印花税", "totalFare": "手续费", "sellFare2": "卖出过户费",
        "corpName": "企业名称", "uscc": "上市公司纳税人识别号", "tradeType": "交易类别",
        "seatNo": "席位编号", "dealNo": "成交编号", "assetType": "资产属性代码",
    },
}
BALANCE_COLUMNS = ["公司段", "会计科目", "描述", "币种", "期初余额", "借方金额", "贷方金额", "期末余额"]


def security_frame(kind: str, rows: list[dict]) -> pd.DataFrame:
    fields = {**COMMON_FIELDS, **SECURITY_FIELDS[kind]}
    # Keep identifiers as text, including stock codes and identity numbers.
    frame = pd.DataFrame([{label: row.get(key, "") for key, label in fields.items()} for row in rows], columns=list(fields.values()))
    frame["机构代码"] = frame["机构代码"].map(normalize_org_code)
    if kind == "interest_tax":
        # DSP stores withholding as a negative cash movement; imports use tax amounts.
        try:
            frame["兑息扣税"] = pd.to_numeric(frame["兑息扣税"], errors="raise").abs()
        except (ValueError, TypeError) as exc:
            raise FmssApiError("支撑平台利息税金额格式异常，未保存查询结果") from exc
    return frame


def balance_rows(preview: dict, org_code: str) -> list[dict]:
    if not isinstance(preview, dict) or preview.get("formulaErrors"):
        raise FmssApiError(f"机构{org_code}余额表公式计算失败，未保存查询结果")
    cells = preview.get("cells")
    if not isinstance(cells, list):
        raise FmssApiError("余额表响应缺少单元格数据")
    values = {cell["cellCode"]: cell.get("cellVal") for cell in cells if isinstance(cell, dict) and "cellCode" in cell}
    if [values.get(f"{col}1") for col in "ABCDEF"] != ["会计科目", "描述", "期初金额", "借方发生额", "贷方发生额", "余额"]:
        raise FmssApiError("支撑平台余额表列结构已变化，请检查报表794")
    result = []
    for address, subject in sorted(values.items()):
        if not re.fullmatch(r"A\d+", address) or not re.fullmatch(r"\d{8}", str(subject or "")):
            continue
        row = address[1:]
        amounts = []
        for col in "CDEF":
            try:
                amount = Decimal(str(values[f"{col}{row}"]).replace(",", ""))
                if not amount.is_finite():
                    raise InvalidOperation()
            except (KeyError, InvalidOperation, ValueError) as exc:
                raise FmssApiError(f"机构{org_code}科目{subject}余额数据无效，未保存查询结果") from exc
            amounts.append(str(amount))
        result.append(dict(zip(BALANCE_COLUMNS, [org_code, str(subject), values.get(f"B{row}", ""), "CNY", *amounts])))
    if not {"21510008", "21510009"}.issubset({row["会计科目"] for row in result}):
        raise FmssApiError("余额表缺少利息税或限售股科目，未保存查询结果")
    return result


def _excel_file(frame: pd.DataFrame, name: str) -> UploadFile:
    buffer = BytesIO()
    frame.to_excel(buffer, index=False)
    buffer.seek(0)
    return UploadFile(filename=name, file=buffer)


def fetch_security_sources(db: Session, company: Company, period: Period, client: FmssClient | None = None) -> dict:
    client = client or FmssClient()
    branch = company.fmss_branch_code or to_fmss_branch_code(company.code)
    # Fetch and validate both sources before publishing either new snapshot.
    frames = {kind: security_frame(kind, client.security_tax_rows(kind, branch, period.year, period.month)) for kind in SECURITY_FIELDS}
    files = []
    for kind, frame in frames.items():
        name = f"支撑平台_{'利息税' if kind == 'interest_tax' else '限售股'}_{period.name}.xlsx"
        with _excel_file(frame, name).file as stream:
            path, size = save_upload(UploadFile(filename=name, file=stream), period.id, kind)
        uploaded = UploadedFile(company_id=company.id, period_id=period.id, file_role=kind, original_name=name,
                                stored_path=str(path), size_bytes=size, validation_status="fmss_extracted", validation_issues=[])
        db.add(uploaded)
        db.flush()
        files.append({"id": uploaded.id, "file_role": kind, "original_name": name, "row_count": len(frame)})
    db.commit()
    return {"files": files, "branch_code": branch, "month": f"{period.year}-{period.month:02d}"}


def fetch_balance_source(db: Session, period: Period, client: FmssClient | None = None):
    client = client or FmssClient()
    mappings = db.query(OrganizationMapping).filter_by(company_id=current_company_id(), active=1).order_by(OrganizationMapping.org_code).all()
    if not mappings:
        raise FmssApiError("当前公司尚未维护机构主数据，无法提取余额表")
    rows = []
    for item in mappings:
        rows.extend(balance_rows(client.balance_preview(item.org_code, period.year, period.month), item.org_code))
    file = _excel_file(pd.DataFrame(rows, columns=BALANCE_COLUMNS), f"支撑平台_余额表_{period.name}.xlsx")
    try:
        return import_reconciliation_file(db, period_id=period.id, import_type="balance_sheet", file=file)
    finally:
        file.file.close()
