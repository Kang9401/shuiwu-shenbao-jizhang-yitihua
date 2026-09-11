from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from app.models.accounting import ReconciliationImportBatch, ReconciliationImportRow
from app.models.core import Artifact, Job
from app.models.tax import TaxMonthlyArtifact
from .constants import BALANCE_FIELD_ALIASES
from .domain import (BalanceRow, BankRow, BondInterestRow, BrokerRow, DeclarationRow, PitSourceBundle, RestrictedStockRow, SalaryRow, SourceResult, TaxCertificateRow)
from .money import money_or_none
from .organization_resolver import PitOrganizationResolver


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _org_code(value: Any) -> str:
    text = _text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _pick(record: dict, *names: str) -> Any:
    normalized = {str(key).replace(" ", "").replace("_", ""): value for key, value in record.items()}
    for name in names:
        key = name.replace(" ", "").replace("_", "")
        if key in normalized and _text(normalized[key]): return normalized[key]
    return None


PAYROLL_KIND_BY_LABEL = {
    "职级工资单": "five_digit",
    "营销工资单": "seven_digit",
    "机构工资单": "seven_digit",
    "数字化运营工资单": "seven_digit",
    "投顾工资单": "seven_digit",
    "总部工资单": "headquarters",
    "退休福利工资单": "retirement_welfare",
}

PAYROLL_A2_WORKING_SHEET_FIELDS = (
    "工资表_累计应纳税所得额",
    "工资表_累计减除费用",
    "工资表_累计养老保险金员工部分",
    "工资表_累计医疗保险金员工部分",
    "工资表_累计失业保险金员工部分",
    "工资表_累计住房公积金员工部分",
    "工资单_累计子女教育扣除",
    "工资单_累计继续教育扣除",
    "工资单_累计住房贷款利息扣除",
    "工资单_累计住房租金扣除",
    "工资单_累计赡养老人扣除",
    "工资单_累计婴幼儿照护扣除",
    "工资单_累计个人养老金",
)


def _salary_kind(record: dict[str, Any]) -> str:
    label = _text(_pick(record, "工资单类型"))
    if label in PAYROLL_KIND_BY_LABEL:
        return PAYROLL_KIND_BY_LABEL[label]
    employee_no = _text(_pick(record, "员工编号", "工号"))
    if employee_no.endswith(".0"):
        employee_no = employee_no[:-2]
    if employee_no.isdigit() and len(employee_no) == 5:
        return "five_digit"
    if employee_no.isdigit() and len(employee_no) == 7:
        return "seven_digit"
    return "unknown"


def _sum_money_fields(record: dict[str, Any], names: tuple[str, ...]):
    values = [money_or_none(record[name]) for name in names]
    if any(value is None for value in values):
        return None
    return sum(values, start=Decimal("0.00"))


class PitSourceService:
    def __init__(self, db, company_id: int, period_id: int):
        self.db, self.company_id, self.period_id = db, company_id, period_id
        self.resolver = PitOrganizationResolver(db, company_id)

    def _latest_batch(self, import_type: str):
        return self.db.query(ReconciliationImportBatch).filter(ReconciliationImportBatch.company_id == self.company_id, ReconciliationImportBatch.period_id == self.period_id, ReconciliationImportBatch.import_type == import_type).order_by(ReconciliationImportBatch.created_at.desc(), ReconciliationImportBatch.id.desc()).first()

    def _batch_rows(self, import_type: str) -> tuple[ReconciliationImportBatch | None, list[ReconciliationImportRow]]:
        batch = self._latest_batch(import_type)
        return batch, ([] if batch is None else self.db.query(ReconciliationImportRow).filter(ReconciliationImportRow.company_id == self.company_id, ReconciliationImportRow.batch_id == batch.id).order_by(ReconciliationImportRow.row_number).all())

    def _source_from_artifact(self, workflow: str, artifact_type: str, mapper):
        artifact = self.db.query(Artifact).join(Job).filter(Artifact.company_id == self.company_id, Job.company_id == self.company_id, Job.period_id == self.period_id, Job.workflow_code == workflow, Job.status == "success", Artifact.artifact_type == artifact_type).order_by(Artifact.created_at.desc()).first()
        if artifact is None: return SourceResult(workflow, "missing")
        try:
            frame = pd.read_excel(artifact.stored_path).fillna("")
            mapped_rows = [mapper(record) for record in frame.to_dict(orient="records")]
            allowed_codes = set(self.resolver.items)
            rows = [row for row in mapped_rows if not getattr(row, "org_code", "") or row.org_code in allowed_codes]
            issues = []
            if mapped_rows and not rows:
                issues.append({"issue_type": "out_of_scope_artifact_rows", "message": f"工件共 {len(mapped_rows)} 行，但没有当前公司机构范围内的数据，已排除"})
            return SourceResult(workflow, "ready_empty" if not rows else "ready", rows, source_kind="artifact", source_id=artifact.id, source_ref=artifact.stored_path, issues=issues)
        except Exception as exc: return SourceResult(workflow, "invalid", source_kind="artifact", source_id=artifact.id, source_ref=artifact.stored_path, issues=[{"issue_type": "artifact_parse_error", "message": str(exc)}])

    def load_balance_source(self) -> SourceResult:
        batch, rows = self._batch_rows("balance_sheet")
        if batch is None: return SourceResult("balance_sheet", "missing")
        result=[]
        for row in rows:
            raw=row.raw_data or {}; full=_text(_pick(raw, "会计科目", "科目编码") or row.account_code); subject="45019006" if "45019006" in full else next((code for code in ("21510006","21510008","21510009","21510016","21131042","21210037","21210038","21210012") if code in full), full.split(".")[0])
            org=_text(_pick(raw, "公司段", "机构代码", "分支机构代码") or row.organization_code); result.append(BalanceRow(org, full, subject, _text(_pick(raw, "描述", "会计科目名称") or row.account_name), *[money_or_none(_pick(raw, *aliases)) for aliases in BALANCE_FIELD_ALIASES.values()], raw))
        return SourceResult("balance_sheet", "ready_empty" if not result else "ready", result, source_kind="reconciliation_import_batch", source_id=batch.id, source_ref=batch.stored_path)

    def load_declaration_source(self) -> SourceResult:
        batch, rows = self._batch_rows("pit_declaration")
        if batch is None: return SourceResult("pit_declaration", "missing")
        result=[]
        for row in rows:
            raw=row.raw_data or {}; org=_text(_pick(raw,"机构代码","分支机构代码") or row.organization_code); agent=_text(_pick(raw,"agent_name","扣缴义务人名称","withholding_agent_name")); agent_id=_text(_pick(raw,"agent_id","扣缴义务人纳税人识别号（统一社会信用代码）","扣缴义务人编码")); resolved=self.resolver.resolve_by_taxpayer_id(agent_id) or self.resolver.resolve_by_full_name(agent) or self.resolver.resolve_by_branch_name(agent)
            org=org or (resolved.org_code if resolved else "")
            result.append(DeclarationRow(org, _text(_pick(raw,"sheet_name","申报类型","申报表类型") or row.declaration_type), agent, agent_id, _text(_pick(raw,"纳税人姓名","姓名","*姓名") or row.taxpayer_name), _text(_pick(raw,"证件号码","身份证号码","*证件号码")), _text(_pick(raw,"所得项目","*所得项目") or row.declaration_type), money_or_none(_pick(raw,"收入额","本期收入","收入") or row.income_amount), money_or_none(_pick(raw,"应补退税额","扣缴税额","税额") or row.tax_amount), _text(_pick(raw,"税率/预扣率","税率","预扣率")), money_or_none(_pick(raw,"累计应纳税所得额")), money_or_none(_pick(raw,"累计减除费用")), money_or_none(_pick(raw,"累计专项扣除")), money_or_none(_pick(raw,"子女教育")), money_or_none(_pick(raw,"赡养老人")), money_or_none(_pick(raw,"住房贷款利息")), money_or_none(_pick(raw,"住房租金")), money_or_none(_pick(raw,"继续教育")), money_or_none(_pick(raw,"婴幼儿照护","3岁以下婴幼儿照护","3岁以下婴幼儿")), money_or_none(_pick(raw,"累计个人养老金","个人养老金")), money_or_none(_pick(raw,"累计其他扣除","其他扣除")), money_or_none(_pick(raw,"住房公积金调整")), _text(_pick(raw,"tax_period","税款所属期") or row.tax_period), raw))
        return SourceResult("pit_declaration", "ready_empty" if not result else "ready", result, source_kind="reconciliation_import_batch", source_id=batch.id, source_ref=batch.stored_path)

    def load_salary_source(self) -> SourceResult:
        artifact=self.db.query(TaxMonthlyArtifact).filter(TaxMonthlyArtifact.company_id == self.company_id, TaxMonthlyArtifact.period_id == self.period_id, TaxMonthlyArtifact.artifact_type == "working_sheet").first()
        if artifact is None:return SourceResult("salary","missing")
        try:
            frame=pd.read_excel(artifact.stored_path).fillna(""); rows=[]
            records = frame.to_dict(orient="records")
            has_a2_payroll = any(_salary_kind(record) in {"five_digit", "seven_digit"} for record in records)
            missing_headers = [name for name in PAYROLL_A2_WORKING_SHEET_FIELDS if name not in frame.columns]
            if has_a2_payroll and missing_headers:
                headers = [str(column) for column in frame.columns]
                message = (
                    f"工资底稿缺少附A2字段：{'、'.join(missing_headers)}；"
                    f"实际工资表表头：{headers}"
                )
                return SourceResult(
                    "salary", "invalid", source_kind="tax_monthly_artifact",
                    source_id=artifact.id, source_ref=artifact.stored_path,
                    issues=[{"issue_type": "payroll_header_missing", "message": message, "headers": headers}],
                )
            for record in records:
                org=_text(_pick(record,"机构代码","机构代码_工资单","机构代码_人员信息表","分支机构代码")); kind=_salary_kind(record)
                is_a2_payroll = kind in {"five_digit", "seven_digit"}
                special_deduction = _sum_money_fields(record, (
                    "工资表_累计养老保险金员工部分", "工资表_累计医疗保险金员工部分",
                    "工资表_累计失业保险金员工部分", "工资表_累计住房公积金员工部分",
                )) if is_a2_payroll else None
                other_deduction = _sum_money_fields(record, (
                    "工资表_累计企业年金员工部分", "工资表_累计商业保险扣除",
                )) if is_a2_payroll and all(name in record for name in ("工资表_累计企业年金员工部分", "工资表_累计商业保险扣除")) else None
                rows.append(SalaryRow(
                    org,
                    _text(_pick(record,"姓名","*姓名")),
                    _text(_pick(record,"证件号码","身份证号码","*证件号码")),
                    _text(_pick(record,"员工编号","工号")),
                    kind,
                    money_or_none(_pick(record,"个人所得税 SUM","个人所得税")),
                    money_or_none(record["工资表_累计应纳税所得额"]) if is_a2_payroll else None,
                    money_or_none(record["工资表_累计减除费用"]) if is_a2_payroll else None,
                    special_deduction,
                    money_or_none(record["工资单_累计子女教育扣除"]) if is_a2_payroll else None,
                    money_or_none(record["工资单_累计赡养老人扣除"]) if is_a2_payroll else None,
                    money_or_none(record["工资单_累计住房贷款利息扣除"]) if is_a2_payroll else None,
                    money_or_none(record["工资单_累计住房租金扣除"]) if is_a2_payroll else None,
                    money_or_none(record["工资单_累计继续教育扣除"]) if is_a2_payroll else None,
                    money_or_none(record["工资单_累计婴幼儿照护扣除"]) if is_a2_payroll else None,
                    money_or_none(record["工资单_累计个人养老金"]) if is_a2_payroll else None,
                    other_deduction,
                ))
            return SourceResult("salary","ready_empty" if not rows else "ready",rows,source_kind="tax_monthly_artifact",source_id=artifact.id,source_ref=artifact.stored_path)
        except Exception as exc:return SourceResult("salary","invalid",source_kind="tax_monthly_artifact",source_id=artifact.id,source_ref=artifact.stored_path,issues=[{"issue_type":"artifact_parse_error","message":str(exc)}])

    def load_broker_source(self):
        result=self._source_from_artifact("broker_tax", "broker_tax_result", lambda r: BrokerRow(_org_code(_pick(r,"分支机构代码","机构代码")), _text(_pick(r,"姓名","*姓名")), money_or_none(_pick(r,"个人所得税(经纪人)","个人所得税")), money_or_none(_pick(r,"应发合计（补足前）","经纪人本期收入","本期收入")), money_or_none(_pick(r,"增值税"))))
        result.source_type="broker"; return result
    def load_bond_source(self):
        result=self._source_from_artifact("restricted_stock_interest_tax", "restricted_stock_interest_result", lambda r: BondInterestRow(_text(_pick(r,"机构代码","分支机构代码")),_text(_pick(r,"客户姓名","姓名","*姓名")),_text(_pick(r,"证件号码","身份证号码")),money_or_none(_pick(r,"债券兑息","利息税原始收入")),money_or_none(_pick(r,"兑息扣税","实际扣缴税额","利息税税费(申报表)"))))
        result.source_type="bond_interest"; return result
    def load_restricted_source(self):
        result=self._source_from_artifact("restricted_stock_interest_tax", "restricted_stock_interest_result", lambda r: RestrictedStockRow(_text(_pick(r,"机构代码","分支机构代码")),_text(_pick(r,"客户姓名","姓名","*姓名")),_text(_pick(r,"证件号码","身份证号码")),_text(_pick(r,"证券名称","股票名称")),money_or_none(_pick(r,"限售股申报金额","成交金额")),money_or_none(_pick(r,"利息税","限售股税费(申报表)","扣缴税额"))))
        result.source_type="restricted_stock"; return result

    def load_certificate_source(self) -> SourceResult:
        batch, rows=self._batch_rows("tax_certificate")
        if batch is None:return SourceResult("tax_certificate","missing",required=False)
        result=[]
        for row in rows:
            raw=row.raw_data or {}; name=_text(_pick(raw,"纳税人名称","扣缴义务人名称") or row.counterparty); org=self.resolver.resolve_by_full_name(name) or self.resolver.resolve_by_branch_name(name); result.append(TaxCertificateRow(org.org_code if org else _text(row.organization_code),name,_text(_pick(raw,"税种","tax_type")),_text(_pick(raw,"税款所属期","tax_period")),money_or_none(_pick(raw,"实缴（退）金额","amount") or row.amount),row.id))
        # A batch with usable rows remains available even when individual files
        # reported parse/validation issues; only an all-failed batch is invalid.
        status = "invalid" if not result and batch.validation_issues else ("ready_empty" if not result else "ready")
        return SourceResult("tax_certificate",status,result,False,"reconciliation_import_batch",batch.id,batch.stored_path, batch.validation_issues or [])

    def load_bank_source(self) -> SourceResult:
        batch, rows=self._batch_rows("bank_statement")
        if batch is None:return SourceResult("bank_statement","missing",required=False)
        result=[]; issues=[]
        for row in rows:
            raw=row.raw_data or {}; account=_text(_pick(raw,"本方账号","账号","银行账号") or row.account_code); name=_text(_pick(raw,"本方户名","账户名称","户名")); resolved=self.resolver.resolve_by_bank_account(account) or self.resolver.resolve_by_full_name(name) or self.resolver.resolve_by_branch_name(name)
            org=(resolved.org_code if resolved else "") or _text(row.organization_code)
            if not org: issues.append({"issue_type":"unresolved_bank_organization","message":"银行流水未识别本方机构，已排除自动匹配","row_id":row.id,"bank_account":account})
            result.append(BankRow(org,account,_text(row.transaction_date),_text(row.summary),money_or_none(_pick(raw,"借方金额") or row.amount),batch.id,row.id))
        return SourceResult("bank_statement","ready_empty" if not rows else "ready",result,False,"reconciliation_import_batch",batch.id,batch.stored_path,issues)

    def load_bundle(self) -> PitSourceBundle:
        orgs=SourceResult("organization_mapping","ready_empty" if not self.resolver.items else "ready",list(self.resolver.items.values()),source_kind="organization_mappings")
        return PitSourceBundle(orgs,self.load_salary_source(),self.load_declaration_source(),self.load_balance_source(),self.load_broker_source(),self.load_bond_source(),self.load_restricted_source(),self.load_certificate_source(),self.load_bank_source())
