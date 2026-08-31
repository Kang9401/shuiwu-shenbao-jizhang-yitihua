from __future__ import annotations

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


def _pick(record: dict, *names: str) -> Any:
    normalized = {str(key).replace(" ", "").replace("_", ""): value for key, value in record.items()}
    for name in names:
        key = name.replace(" ", "").replace("_", "")
        if key in normalized and _text(normalized[key]): return normalized[key]
    return None


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
            rows = [mapper(record) for record in frame.to_dict(orient="records")]
            return SourceResult(workflow, "ready_empty" if not rows else "ready", rows, source_kind="artifact", source_id=artifact.id, source_ref=artifact.stored_path)
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
            raw=row.raw_data or {}; org=_text(_pick(raw,"机构代码","分支机构代码") or row.organization_code); agent=_text(_pick(raw,"扣缴义务人名称","withholding_agent_name")); resolved=self.resolver.resolve_by_taxpayer_id(_text(_pick(raw,"扣缴义务人纳税人识别号（统一社会信用代码）","扣缴义务人编码"))) or self.resolver.resolve_by_full_name(agent) or self.resolver.resolve_by_branch_name(agent)
            org=org or (resolved.org_code if resolved else "")
            result.append(DeclarationRow(org, _text(_pick(raw,"sheet_name","申报类型","申报表类型") or row.declaration_type), agent, _text(_pick(raw,"扣缴义务人纳税人识别号（统一社会信用代码）","扣缴义务人编码")), _text(_pick(raw,"纳税人姓名","姓名","*姓名") or row.taxpayer_name), _text(_pick(raw,"证件号码","身份证号码","*证件号码")), _text(_pick(raw,"所得项目","*所得项目") or row.declaration_type), money_or_none(_pick(raw,"收入额","本期收入","收入") or row.income_amount), money_or_none(_pick(raw,"应补退税额","扣缴税额","税额") or row.tax_amount), _text(_pick(raw,"税率","预扣率")), money_or_none(_pick(raw,"累计应纳税所得额")), money_or_none(_pick(raw,"累计减除费用")), money_or_none(_pick(raw,"累计专项扣除")), money_or_none(_pick(raw,"子女教育")), money_or_none(_pick(raw,"赡养老人")), money_or_none(_pick(raw,"住房贷款利息")), money_or_none(_pick(raw,"住房租金")), money_or_none(_pick(raw,"继续教育")), money_or_none(_pick(raw,"婴幼儿照护","3岁以下婴幼儿")), money_or_none(_pick(raw,"累计个人养老金","个人养老金")), money_or_none(_pick(raw,"累计其他扣除","其他扣除")), _text(_pick(raw,"tax_period","税款所属期") or row.tax_period), raw))
        return SourceResult("pit_declaration", "ready_empty" if not result else "ready", result, source_kind="reconciliation_import_batch", source_id=batch.id, source_ref=batch.stored_path)

    def load_salary_source(self) -> SourceResult:
        artifact=self.db.query(TaxMonthlyArtifact).filter(TaxMonthlyArtifact.company_id == self.company_id, TaxMonthlyArtifact.period_id == self.period_id, TaxMonthlyArtifact.artifact_type == "working_sheet").first()
        if artifact is None:return SourceResult("salary","missing")
        try:
            frame=pd.read_excel(artifact.stored_path).fillna(""); rows=[]
            for record in frame.to_dict(orient="records"):
                org=_text(_pick(record,"机构代码","分支机构代码")); kind="five_digit" if "5位" in _text(_pick(record,"薪资套","工资类型")) else "seven_digit"
                rows.append(SalaryRow(org,_text(_pick(record,"姓名","*姓名")),_text(_pick(record,"证件号码","身份证号码","*证件号码")),_text(_pick(record,"员工编号","工号")),kind,money_or_none(_pick(record,"个人所得税 SUM","个人所得税")),money_or_none(_pick(record,"累计预扣预缴应纳税所得额","累计应纳税所得额")),money_or_none(_pick(record,"累计减除费用")),money_or_none(_pick(record,"累计专项扣除")),money_or_none(_pick(record,"累计子女教育")),money_or_none(_pick(record,"累计赡养老人")),money_or_none(_pick(record,"累计住房贷款利息")),money_or_none(_pick(record,"累计住房租金")),money_or_none(_pick(record,"累计继续教育")),money_or_none(_pick(record,"累计婴幼儿照护")),money_or_none(_pick(record,"累计个人养老金")),money_or_none(_pick(record,"累计企业年金","累计其他扣除"))))
            return SourceResult("salary","ready_empty" if not rows else "ready",rows,source_kind="tax_monthly_artifact",source_id=artifact.id,source_ref=artifact.stored_path)
        except Exception as exc:return SourceResult("salary","invalid",source_kind="tax_monthly_artifact",source_id=artifact.id,source_ref=artifact.stored_path,issues=[{"issue_type":"artifact_parse_error","message":str(exc)}])

    def load_broker_source(self):
        result=self._source_from_artifact("broker_tax", "broker_tax_result", lambda r: BrokerRow(_text(_pick(r,"分支机构代码","机构代码")), _text(_pick(r,"姓名","*姓名")), money_or_none(_pick(r,"个人所得税(经纪人)","个人所得税")), money_or_none(_pick(r,"应发合计（补足前）","经纪人本期收入","本期收入")), money_or_none(_pick(r,"增值税"))))
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
        return SourceResult("tax_certificate","ready_empty" if not result else "ready",result,False,"reconciliation_import_batch",batch.id,batch.stored_path)

    def load_bank_source(self) -> SourceResult:
        batch, rows=self._batch_rows("bank_statement")
        if batch is None:return SourceResult("bank_statement","missing",required=False)
        return SourceResult("bank_statement","ready_empty" if not rows else "ready",[BankRow(_text(row.organization_code),_text(_pick(row.raw_data or {},"账号","银行账号")),_text(row.transaction_date),_text(row.summary),money_or_none(row.amount),batch.id,row.id) for row in rows],False,"reconciliation_import_batch",batch.id,batch.stored_path)

    def load_bundle(self) -> PitSourceBundle:
        orgs=SourceResult("organization_mapping","ready_empty" if not self.resolver.items else "ready",list(self.resolver.items.values()),source_kind="organization_mappings")
        return PitSourceBundle(orgs,self.load_salary_source(),self.load_declaration_source(),self.load_balance_source(),self.load_broker_source(),self.load_bond_source(),self.load_restricted_source(),self.load_certificate_source(),self.load_bank_source())
