from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.integrations.fmss.errors import FmssTemplateChanged
from app.integrations.fmss.iit.schemas import FmssSheet
from app.models.core import Period
from app.models.pit_reconciliation import (
    PitDeclarationSummary, PitOccurrenceCheck, PitReconciliationDifferenceDetail,
    PitReconciliationOrgSummary, PitTaxAmountCheck,
)


PRE_SHEET_KEYS = (
    "iit_pre_tax_summary", "iit_pre_filing_summary", "iit_pre_tax_detail", "iit_pre_other_tax",
    "iit_pre_appendix_a1", "iit_pre_appendix_a2", "iit_pre_appendix_a3", "iit_pre_appendix_a4",
)

PRE_HEADERS: dict[str, tuple[str, ...]] = {
    "iit_pre_tax_summary": ("机构代码", "营业部简称", "税款所属期", "申报表", "科目余额表期末余额", "申报表与余额表差异金额1", "差异原因1", "申报表与工资表、支撑平台差异金额2", "差异原因2", "当期工资薪金累计应纳税所得额差异金额3", "差异原因3", "经纪人支出当期发生额与工资表差异金额6", "差异原因6", "部分税种发生额差异金额7", "差异原因7"),
    "iit_pre_filing_summary": ("机构代码", "营业部名称", "申报类型", "所得项目", "填写人次", "收入合计（元）", "应补/退税额（元）"),
    "iit_pre_tax_detail": ("机构代码", "营业部名称", "会计科目", "描述", "期初余额", "借方金额", "贷方金额", "期末余额", "申报表税额", "本期差异金额8（申报表-余额表贷方）", "差异原因8", "累计差异金额9（申报表-余额表期末余额）", "差异原因9", "工资表、支撑平台税额", "申报表税额（仅正常工资薪金、经纪人、限售股、利息税）", "差异金额10（申报表-工资表、支撑平台税额）", "差异原因10"),
    "iit_pre_other_tax": ("机构代码", "营业部名称", "会计科目", "描述", "对应税种", "期初余额", "借方金额", "贷方金额", "期末余额", "科目余额表当期发生额", "经纪人工资表应发", "差异金额11（工资表应发-余额表发生额）", "差异原因11", "发生额应申报收入", "发生额应申报收入说明", "申报表申报收入", "差异金额12（申报表申报收入-应申报收入）", "差异原因12"),
    "iit_pre_appendix_a1": ("机构代码", "机构简称", "期间", "姓名", "申报税额", "工资表税额", "差异金额", "差异原因"),
    "iit_pre_appendix_a2": ("机构代码", "姓名", "累计应纳税所得额差异（工资表-申报表）", "累计专项扣除差异（工资表-申报表）", "累计专项附加扣除差异（含个人养老金）（工资表-申报表）", "其它差异（工资表-申报表）", "申报表税率", "应纳税额差异（工资表-申报表）", "差异原因"),
    "iit_pre_appendix_a3": ("机构代码", "营业部名称", "客户姓名", "证件号码", "债券利息收入", "兑息扣税", "申报税额", "差异金额", "差异原因"),
    "iit_pre_appendix_a4": ("机构代码", "营业部名称", "客户姓名", "证件号码", "证券名称", "转让收入额", "利息税", "申报税额", "差异金额", "差异原因"),
}


def _value(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def _reason(row: Any) -> str | None:
    return row.manual_reason or row.auto_reason


class PitFmssMapper:
    """Maps calculated local rows into ordered FMSS rows, never via header dicts."""

    def validate_pre_template(self, sheets: list[FmssSheet]) -> dict[str, FmssSheet]:
        by_key = {sheet.key: sheet for sheet in sheets}
        if set(by_key) != set(PRE_SHEET_KEYS):
            raise FmssTemplateChanged()
        for key, expected in PRE_HEADERS.items():
            if by_key[key].headers != expected:
                raise FmssTemplateChanged()
        return by_key

    def map_pre(self, db: Session, company_id: int, period_id: int, workpaper_id: int, sheets: list[FmssSheet]) -> dict[str, list[list[Any]]]:
        self.validate_pre_template(sheets)
        period = db.query(Period).filter_by(id=period_id, company_id=company_id).one()
        month = f"{period.year}-{period.month:02d}"
        summaries = db.query(PitReconciliationOrgSummary).filter_by(workpaper_id=workpaper_id, company_id=company_id).all()
        declarations = db.query(PitDeclarationSummary).filter_by(workpaper_id=workpaper_id, company_id=company_id).all()
        taxes = db.query(PitTaxAmountCheck).filter_by(workpaper_id=workpaper_id, company_id=company_id).all()
        occurrences = db.query(PitOccurrenceCheck).filter_by(workpaper_id=workpaper_id, company_id=company_id).all()
        details = db.query(PitReconciliationDifferenceDetail).filter_by(workpaper_id=workpaper_id, company_id=company_id).all()
        rows: dict[str, list[list[Any]]] = {key: [] for key in PRE_SHEET_KEYS}
        for row in summaries:
            rows["iit_pre_tax_summary"].append([row.org_code, row.org_name, month, _value(row.declared_tax_amount), _value(row.balance_tax_amount), _value(row.difference_1), row.difference_1_manual_reason, _value(row.difference_2), row.difference_2_manual_reason, _value(row.taxable_income_difference), row.difference_3_manual_reason, _value(row.broker_occurrence_difference), row.difference_6_manual_reason, _value(row.other_income_difference), row.difference_7_manual_reason])
        for row in declarations:
            rows["iit_pre_filing_summary"].append([row.org_code, row.org_name, row.declaration_type, row.income_item, row.person_count, _value(row.income_amount), _value(row.tax_amount)])
        for row in taxes:
            rows["iit_pre_tax_detail"].append([row.org_code, row.org_name, row.subject_code, row.subject_name, _value(row.opening_balance), _value(row.debit_amount), _value(row.credit_amount), _value(row.closing_balance), _value(row.declared_tax_amount), _value(row.current_difference), row.current_manual_reason, _value(row.cumulative_difference), row.cumulative_manual_reason, _value(row.business_tax_amount), _value(row.scoped_declared_tax_amount), _value(row.business_declared_difference), row.business_declared_manual_reason])
        for row in occurrences:
            rows["iit_pre_other_tax"].append([row.org_code, row.org_name, row.subject_code, row.subject_name, row.income_type, _value(row.opening_balance), _value(row.debit_amount), _value(row.credit_amount), _value(row.closing_balance), _value(row.occurrence_amount), _value(row.broker_payroll_amount), _value(row.broker_occurrence_difference), row.broker_occurrence_manual_reason, _value(row.expected_declared_income), row.expected_income_description, _value(row.actual_declared_income), _value(row.declared_income_difference), row.declared_income_manual_reason])
        detail_specs: dict[str, tuple[str, Callable[[PitReconciliationDifferenceDetail], list[Any]]]] = {
            "salary_tax": ("iit_pre_appendix_a1", lambda row: [row.org_code, row.org_name, month, row.person_or_customer_name, _value(row.target_amount), _value(row.source_amount), _value(row.difference), _reason(row)]),
            "salary_taxable_income": ("iit_pre_appendix_a2", lambda row: [row.org_code, row.person_or_customer_name, (row.detail_json or {}).get("taxable_income_difference"), (row.detail_json or {}).get("specific_deduction_difference"), (row.detail_json or {}).get("special_additional_deduction_difference"), (row.detail_json or {}).get("other_deduction_difference"), (row.detail_json or {}).get("declaration_rate"), (row.detail_json or {}).get("tax_difference"), _reason(row)]),
            "bond_interest_tax": ("iit_pre_appendix_a3", lambda row: [row.org_code, row.org_name, row.person_or_customer_name, row.id_number, (row.detail_json or {}).get("interest_amount"), (row.detail_json or {}).get("business_tax_amount"), (row.detail_json or {}).get("declared_tax_amount"), _value(row.difference), _reason(row)]),
            "restricted_stock_tax": ("iit_pre_appendix_a4", lambda row: [row.org_code, row.org_name, row.person_or_customer_name, row.id_number, "、".join((row.detail_json or {}).get("security_names", [])), (row.detail_json or {}).get("sale_amount"), (row.detail_json or {}).get("business_tax_amount"), (row.detail_json or {}).get("declared_tax_amount"), _value(row.difference), _reason(row)]),
        }
        for row in details:
            spec = detail_specs.get(row.detail_type)
            if spec:
                rows[spec[0]].append(spec[1](row))
        return rows
