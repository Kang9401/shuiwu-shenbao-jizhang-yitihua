from __future__ import annotations

from .rules.income_classification import income_category
from .workpaper_layout import HEADERS

import io
from collections.abc import Iterable
from collections import OrderedDict

import pandas as pd

from app.models.accounting import ReconciliationImportBatch, ReconciliationImportRow
from app.models.core import Artifact, Job, Period
from app.models.tax import TaxMonthlyArtifact


SHEET_NAMES = (
    "汇总税额核对", "申报表汇总数", "个税明细税额核对", "其他个税发生额核对",
    "附A1 工资薪金等个税差异", "附A2 累计应纳税所得额差异明细", "附A3 客户利息个税差异明细", "附A4 限售股个税差异明细",
    "科目余额", "债券信息明细", "限售股明细", "个税完税凭证", "综合所得个税申报", "分类所得个税申报", "限售股所得申报", "银行流水", "银行流水个税税额明细",
)


def _frame(rows: Iterable[dict], columns: list[str] | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows))
    if columns:
        for column in columns:
            if column not in frame:
                frame[column] = None
        frame = frame[columns]
    return frame


def _income_description(value) -> str:
    """Keep only the formula explanation for legacy rows with a subject prefix."""
    text = "" if value is None else str(value)
    return text.split("：", 1)[-1].split(":", 1)[-1].strip()


BALANCE_COLUMNS = ["币种", "会计科目", "描述", "期初余额(N)", "借方金额(N)", "贷方金额(N)", "期末余额(N)", "公司段"]
BOND_COLUMNS = ["序列号", "分支机构代码", "分支机构名称", "市场", "客户编号", "资产账号", "客户姓名", "证件号码", "手机号码", "家庭电话", "联系地址", "交易日期", "证券账号", "证券代码", "证券名称", "席位编号", "债券兑息", "兑息扣税", "税率（%）", "备注", "性别", "国籍", "出生年月日", "证件类型", "数据时间"]
RESTRICTED_COLUMNS = ["交易日期", "交易类别", "机构代码", "席位编号", "成交编号", "客户姓名", "证件号码", "客户编号", "资产账户", "证券账号", "证券代码", "证券名称", "成交数量", "成交价格", "卖出金额", "成交金额", "原值总金额", "利息税", "ads类型", "卖出经手费", "卖出印花税", "手续费", "卖出过户费", "客户性别", "国籍", "生日", "证件类型", "资产属性代码", "客户手机号码", "上市公司纳税人识别号", "源表", "分支机构名称", "企业名称", "注册地址"]
CERTIFICATE_COLUMNS = ["证明类型", "文件名", "纳税人名称", "纳税人识别号", "税种", "品目", "税款所属时期", "入(退)库日期", "实缴（退）金额"]
BANK_COLUMNS = ["查询账号", "查询开始日期", "查询结束日期", "来源页码", "账户名称", "账户币种", "币种名称", "银行代码", "本方账号", "本方户名", "交易时间", "借贷标志", "交易金额", "借方金额", "贷方金额", "交易摘要", "交易流水号", "余额", "币种", "对方账号", "对方户名", "手续费", "交易状态", "回单流水号", "序号", "日期", "时间", "sourceAccountNum", "sourceAreaCode"]
DECLARATION_COLUMNS = ["序号", "姓名", "身份证件类型", "身份证件号码", "纳税人识别号", "是否为非居民个人", "所得项目", "本月（次）情况_收入额计算_收入", "费用", "免税收入", "减除费用", "专项扣除_基本养老保险费", "基本医疗保险费", "失业保险费", "住房公积金", "其他扣除_年金", "商业健康保险", "税延养老保险", "财产原值", "允许扣除的税费", "公务交通费用", "通讯费用", "律师办案费用", "展业成本", "西藏附加减除费用", "修缮费用", "向出租方支付的租金", "有关合理费用", "其他", "累计情况_累计收入额", "累计减除费用", "累计专项扣除", "累计专项附加扣除_子女教育", "赡养老人", "住房贷款利息", "住房租金", "继续教育", "3岁以下婴幼儿照护", "累计个人养老金", "累计其他扣除", "减按计税比例", "准予扣除的捐赠额", "税款计算_应纳税所得额", "税率/预扣率", "速算扣除数", "应纳税额", "减免税额", "协定减免", "已缴税额", "应补/退税额", "备注", "税款所属期", "扣缴义务人名称", "扣缴义务人纳税人识别号（统一社会信用代码）", "文件名"]
COMPREHENSIVE_DECLARATION_COLUMNS = DECLARATION_COLUMNS[:DECLARATION_COLUMNS.index("税款所属期")] + ["Col_52"] + DECLARATION_COLUMNS[DECLARATION_COLUMNS.index("税款所属期"):]
RESTRICTED_DECLARATION_COLUMNS = ["序号", "纳税人姓名", "纳税人有效身份证件_证件类型", "证件号码", "Col_5", "证券账户号", "股票代码", "股票名称", "每股计税价格（元/股)", "转让股数(股)", "Col_11", "转让收入额", "限售股原值及合理税费_小计", "原值", "合理税费", "Col_16", "准予扣除的捐赠额", "应纳税所得额", "税率", "协定减免", "扣缴税额", "税款所属期", "扣缴义务人名称", "扣缴义务人纳税人识别号（统一社会信用代码）", "文件名"]


def _declaration_display_rows(rows: list[dict], columns: list[str] = DECLARATION_COLUMNS) -> list[dict]:
    aliases = {
        "本月（次）情况_收入额计算_收入": "收入", "专项扣除_基本养老保险费": "基本养老保险费",
        "其他扣除_年金": "年金", "累计情况_累计收入额": "累计收入额",
        "累计专项附加扣除_子女教育": "子女教育", "税款计算_应纳税所得额": "累计应纳税所得额",
        "应补/退税额": "应补退税额", "税款所属期": "tax_period", "扣缴义务人名称": "agent_name",
        "扣缴义务人纳税人识别号（统一社会信用代码）": "agent_id",
    }
    return [{column: row.get(aliases.get(column, column)) for column in columns} for row in rows]


def _certificate_display_rows(rows: list[dict]) -> list[dict]:
    return [{
        "证明类型": row.get("proof_type") or "税收完税证明", "文件名": row.get("file_name"),
        "纳税人名称": row.get("taxpayer_name"), "纳税人识别号": row.get("taxpayer_id") or row.get("org_code"),
        "税种": row.get("tax_type"), "品目": row.get("income_item"), "税款所属时期": row.get("tax_period"),
        "入(退)库日期": row.get("payment_date"), "实缴（退）金额": row.get("amount"),
    } for row in rows]


def _batch_rows(db, company_id: int, period_id: int, import_type: str) -> list[dict]:
    batch = (
        db.query(ReconciliationImportBatch)
        .filter_by(company_id=company_id, period_id=period_id, import_type=import_type)
        .order_by(ReconciliationImportBatch.created_at.desc(), ReconciliationImportBatch.id.desc())
        .first()
    )
    if batch is None:
        return []
    return [row.raw_data or {} for row in db.query(ReconciliationImportRow).filter_by(batch_id=batch.id).order_by(ReconciliationImportRow.row_number).all()]


def _artifact_rows(db, company_id: int, period_id: int, workflow: str, artifact_type: str) -> list[dict]:
    artifact = (
        db.query(Artifact).join(Job)
        .filter(Artifact.company_id == company_id, Job.company_id == company_id, Job.period_id == period_id,
                Job.workflow_code == workflow, Job.status == "success", Artifact.artifact_type == artifact_type)
        .order_by(Artifact.created_at.desc()).first()
    )
    if artifact is None:
        return []
    try:
        return pd.read_excel(artifact.stored_path).fillna("").to_dict(orient="records")
    except Exception:
        return []


def _working_sheet_rows(db, company_id: int, period_id: int) -> list[dict]:
    artifact = db.query(TaxMonthlyArtifact).filter_by(company_id=company_id, period_id=period_id, artifact_type="working_sheet").first()
    if artifact is None:
        return []
    try:
        return pd.read_excel(artifact.stored_path).fillna("").to_dict(orient="records")
    except Exception:
        return []


def build_pit_workpaper_sheets(db, company_id: int, period_id: int, workpaper) -> OrderedDict[str, pd.DataFrame]:
    from app.models.pit_reconciliation import (
        PitBankTaxMatch, PitDeclarationSummary, PitOccurrenceCheck,
        PitReconciliationDifferenceDetail, PitReconciliationOrgSummary, PitTaxAmountCheck,
    )

    payload = lambda model: [{column.name: getattr(row, column.name) for column in model.__table__.columns}
                             for row in db.query(model).filter_by(workpaper_id=workpaper.id, company_id=company_id).all()]
    summaries = payload(PitReconciliationOrgSummary)
    tax_checks = payload(PitTaxAmountCheck)
    occurrence_checks = payload(PitOccurrenceCheck)
    declaration_summaries = payload(PitDeclarationSummary)
    details = payload(PitReconciliationDifferenceDetail)
    bank_matches = payload(PitBankTaxMatch)

    summary_columns = [
        "机构代码", "营业部全称", "税款所属期", "申报表税额", "科目余额表期末余额税额", "申报表与余额表税额差额1", "差异原因1",
        "申报表税额（仅正常工资薪金、经纪人、限售股、利息税）", "工资表、支撑平台税额", "申报表与工资表、支撑平台税额差额2", "差异原因2",
        "当期工资薪金累计应纳税所得额差异3", "差异原因3", "完税证明税额", "申报表与完税证明税额差额4", "差异原因4",
        "银行流水个税税额", "完税证明与银行流水税额差额5", "差异原因5", "科目余额表经纪人支出当期发生额与经纪人工资应发金额差异6", "差异原因6", "部分税种发生额差异7", "差异原因7",
    ]
    period = db.query(Period).filter_by(id=period_id, company_id=company_id).first()
    tax_period = f"{period.year}.{period.month:02d}.01-{period.year}.{period.month:02d}.{pd.Timestamp(period.year, period.month, 1).days_in_month:02d}" if period else str(period_id)
    summary_rows = []
    for row in summaries:
        summary_rows.append({
            "机构代码": row["org_code"], "营业部全称": row.get("org_full_name") or row.get("org_name", ""), "税款所属期": tax_period,
            "申报表税额": row.get("declared_tax_amount"), "科目余额表期末余额税额": row.get("balance_tax_amount"), "申报表与余额表税额差额1": row.get("difference_1"), "差异原因1": row.get("difference_1_manual_reason"),
            "申报表税额（仅正常工资薪金、经纪人、限售股、利息税）": row.get("scoped_declared_tax_amount"), "工资表、支撑平台税额": row.get("payroll_business_tax_amount"), "申报表与工资表、支撑平台税额差额2": row.get("difference_2"), "差异原因2": row.get("difference_2_manual_reason"),
            "当期工资薪金累计应纳税所得额差异3": row.get("taxable_income_difference"), "差异原因3": row.get("difference_3_manual_reason"), "完税证明税额": row.get("certificate_tax_amount"), "申报表与完税证明税额差额4": row.get("difference_4"), "差异原因4": row.get("difference_4_manual_reason"),
            "银行流水个税税额": row.get("bank_tax_amount"), "完税证明与银行流水税额差额5": row.get("difference_5"), "差异原因5": row.get("difference_5_manual_reason"), "科目余额表经纪人支出当期发生额与经纪人工资应发金额差异6": row.get("broker_occurrence_difference"), "差异原因6": row.get("difference_6_manual_reason"), "部分税种发生额差异7": row.get("other_income_difference"), "差异原因7": row.get("difference_7_manual_reason"),
        })

    def detail_rows(detail_type: str, columns: list[str]) -> list[dict]:
        rows = []
        for row in details:
            if row.get("detail_type") != detail_type:
                continue
            extra = row.get("detail_json") or {}
            rows.append({**row, **extra})
        return rows

    declarations = _batch_rows(db, company_id, period_id, "pit_declaration")
    certificates = _batch_rows(db, company_id, period_id, "tax_certificate")
    banks = _batch_rows(db, company_id, period_id, "bank_statement")
    balances = _batch_rows(db, company_id, period_id, "balance_sheet")
    working = _working_sheet_rows(db, company_id, period_id)
    securities = _artifact_rows(db, company_id, period_id, "restricted_stock_interest_tax", "restricted_stock_interest_result")
    allowed = {row["机构代码"] for row in summary_rows if row.get("机构代码")}
    securities = [row for row in securities if not row.get("机构代码") or str(row.get("机构代码")) in allowed]

    def category(row):
        return income_category(str(row.get("所得项目", "")), str(row.get("sheet_name", "")))
    declaration_rows = [row for row in declarations if category(row) == "综合所得"]
    classification_rows = [row for row in declarations if category(row) == "分类所得"]
    restricted_declaration_rows = [row for row in declarations if category(row) == "限售股所得"]

    bond_keys = ("债券兑息", "债券利息", "兑息扣税", "利息税原始收入", "利息税申报金额", "利息税税费(申报表)")
    bond_rows = [row for row in securities if any(row.get(key) not in (None, "") for key in bond_keys)]
    restricted_rows = [row for row in securities if row not in bond_rows]
    declaration_summary_columns = ["机构代码", "营业部名称", "申报类型", "所得项目", "填写人次", "收入合计（元）", "应补/退税额（元）"]
    declaration_summary_rows = [{"机构代码": row.get("org_code"), "营业部名称": row.get("org_name"), "申报类型": row.get("declaration_type"), "所得项目": row.get("income_item"), "填写人次": row.get("person_count"), "收入合计（元）": row.get("income_amount"), "应补/退税额（元）": row.get("tax_amount")} for row in declaration_summaries]
    tax_columns = ["机构代码", "营业部名称", "会计科目", "描述", "期初余额", "借方金额", "贷方金额", "期末余额", "工资表、支撑平台税额", "申报表税额", "本期差异8", "差异原因8", "累计差异9", "差异原因9", "申报表税额（仅正常工资薪金、经纪人、限售股、利息税）", "差异10", "差异原因10"]
    tax_rows = [{"机构代码": row.get("org_code"), "营业部名称": row.get("org_name"), "会计科目": row.get("subject_code"), "描述": row.get("subject_name"), "期初余额": row.get("opening_balance"), "借方金额": row.get("debit_amount"), "贷方金额": row.get("credit_amount"), "期末余额": row.get("closing_balance"), "工资表、支撑平台税额": row.get("business_tax_amount"), "申报表税额": row.get("declared_tax_amount"), "本期差异8": row.get("current_difference"), "差异原因8": row.get("current_manual_reason"), "累计差异9": row.get("cumulative_difference"), "差异原因9": row.get("cumulative_manual_reason"), "申报表税额（仅正常工资薪金、经纪人、限售股、利息税）": row.get("scoped_declared_tax_amount"), "差异10": row.get("business_declared_difference"), "差异原因10": row.get("business_declared_manual_reason")} for row in tax_checks]
    occurrence_columns = ["机构代码", "营业部名称", "会计科目", "描述", "对应税种", "期初余额", "借方金额", "贷方金额", "期末余额", "科目余额表当期发生额", "经纪人工资表应发", "差异11", "差异原因11", "发生额应申报收入", "发生额应申报收入说明", "申报表申报收入", "差异12", "差异原因12"]
    occurrence_rows = [{"机构代码": row.get("org_code"), "营业部名称": row.get("org_name"), "会计科目": row.get("subject_code"), "描述": row.get("subject_name"), "对应税种": row.get("income_type"), "期初余额": row.get("opening_balance"), "借方金额": row.get("debit_amount"), "贷方金额": row.get("credit_amount"), "期末余额": row.get("closing_balance"), "科目余额表当期发生额": row.get("occurrence_amount"), "经纪人工资表应发": row.get("broker_payroll_amount"), "差异11": row.get("broker_occurrence_difference"), "差异原因11": row.get("broker_occurrence_manual_reason"), "发生额应申报收入": row.get("expected_declared_income"), "发生额应申报收入说明": _income_description(row.get("expected_income_description")), "申报表申报收入": row.get("actual_declared_income"), "差异12": row.get("declared_income_difference"), "差异原因12": row.get("declared_income_manual_reason")} for row in occurrence_checks]
    a1_columns = ["机构代码", "机构简称", "期间", "姓名", "申报税额", "工资表税额", "差异", "差异原因"]
    a2_columns = ["机构代码", "姓名", "（工资表-申报表）累计应纳税所得额差异", "（工资表-申报表）累计专项扣除差异", "（工资表-申报表）累计专项附加扣除差异（含个人养老金）", "（工资表-申报表）其它差异", "申报表税率", "（工资表-申报表）应纳税额差异", "差异原因"]
    a3_columns = ["机构代码", "营业部名称", "客户姓名", "证件号码", "债券利息收入", "兑息扣税", "申报税额", "差异", "差异原因"]
    a4_columns = ["机构代码", "营业部名称", "客户姓名", "证件号码", "证券名称", "转让收入额", "利息税", "申报税额", "差异", "差异原因"]
    sheets = OrderedDict({
        "汇总税额核对": _frame(summary_rows, summary_columns),
        "申报表汇总数": _frame(declaration_summary_rows, declaration_summary_columns),
        "个税明细税额核对": _frame(tax_rows, tax_columns), "其他个税发生额核对": _frame(occurrence_rows, occurrence_columns),
        "附A1 工资薪金等个税差异": _frame([{"机构代码": row.get("org_code"), "机构简称": row.get("org_name"), "期间": tax_period, "姓名": row.get("person_or_customer_name"), "申报税额": row.get("target_amount"), "工资表税额": row.get("source_amount"), "差异": row.get("difference"), "差异原因": row.get("manual_reason") or row.get("auto_reason")} for row in detail_rows("salary_tax", [])], a1_columns),
        "附A2 累计应纳税所得额差异明细": _frame([{"机构代码": row.get("org_code"), "姓名": row.get("person_or_customer_name"), "（工资表-申报表）累计应纳税所得额差异": (row.get("detail_json") or {}).get("taxable_income_difference"), "（工资表-申报表）累计专项扣除差异": (row.get("detail_json") or {}).get("specific_deduction_difference"), "（工资表-申报表）累计专项附加扣除差异（含个人养老金）": (row.get("detail_json") or {}).get("special_additional_deduction_difference"), "（工资表-申报表）其它差异": (row.get("detail_json") or {}).get("other_deduction_difference"), "申报表税率": (row.get("detail_json") or {}).get("declaration_rate"), "（工资表-申报表）应纳税额差异": (row.get("detail_json") or {}).get("tax_difference"), "差异原因": row.get("manual_reason") or row.get("auto_reason")} for row in detail_rows("salary_taxable_income", [])], a2_columns),
        "附A3 客户利息个税差异明细": _frame([{"机构代码": row.get("org_code"), "营业部名称": row.get("org_name"), "客户姓名": row.get("person_or_customer_name"), "证件号码": row.get("id_number"), "债券利息收入": (row.get("detail_json") or {}).get("interest_amount"), "兑息扣税": (row.get("detail_json") or {}).get("business_tax_amount"), "申报税额": (row.get("detail_json") or {}).get("declared_tax_amount"), "差异": row.get("difference"), "差异原因": row.get("manual_reason") or row.get("auto_reason")} for row in detail_rows("bond_interest_tax", [])], a3_columns),
        "附A4 限售股个税差异明细": _frame([{"机构代码": row.get("org_code"), "营业部名称": row.get("org_name"), "客户姓名": row.get("person_or_customer_name"), "证件号码": row.get("id_number"), "证券名称": "、".join((row.get("detail_json") or {}).get("security_names", [])), "转让收入额": (row.get("detail_json") or {}).get("sale_amount"), "利息税": (row.get("detail_json") or {}).get("business_tax_amount"), "申报税额": (row.get("detail_json") or {}).get("declared_tax_amount"), "差异": row.get("difference"), "差异原因": row.get("manual_reason") or row.get("auto_reason")} for row in detail_rows("restricted_stock_tax", [])], a4_columns),
        "科目余额": _frame(balances, BALANCE_COLUMNS), "债券信息明细": _frame(bond_rows, BOND_COLUMNS), "限售股明细": _frame(restricted_rows, RESTRICTED_COLUMNS),
        "个税完税凭证": _frame(_certificate_display_rows(certificates), CERTIFICATE_COLUMNS), "综合所得个税申报": _frame(_declaration_display_rows(declaration_rows, COMPREHENSIVE_DECLARATION_COLUMNS), COMPREHENSIVE_DECLARATION_COLUMNS), "分类所得个税申报": _frame(_declaration_display_rows(classification_rows), DECLARATION_COLUMNS), "限售股所得申报": _frame(restricted_declaration_rows, RESTRICTED_DECLARATION_COLUMNS),
        "银行流水": _frame(banks, BANK_COLUMNS), "银行流水个税税额明细": _frame([{"机构代码": row.get("org_code"), "营业部全称": row.get("org_full_name"), "本方账号": row.get("bank_account"), "交易时间": row.get("transaction_time"), "交易摘要": row.get("transaction_summary"), "借方金额": row.get("debit_amount")} for row in bank_matches], ["机构代码", "营业部全称", "本方账号", "交易时间", "交易摘要", "借方金额"]),
    })
    summary_renames = {'营业部全称': '营业部简称', '申报表税额': '申报表', '科目余额表期末余额税额': '科目余额表期末余额', '申报表与余额表税额差额1': '申报表与余额表差异金额1', '申报表与工资表、支撑平台税额差额2': '申报表与工资表、支撑平台差异金额2', '当期工资薪金累计应纳税所得额差异3': '当期工资薪金累计应纳税所得额差异金额3', '完税证明税额': '完税证明', '申报表与完税证明税额差额4': '申报表与完税证明差异金额4', '银行流水个税税额': '银行流水个税', '完税证明与银行流水税额差额5': '完税证明与银行流水差异金额5', '科目余额表经纪人支出当期发生额与经纪人工资应发金额差异6': '经纪人支出当期发生额与工资表差异金额6', '部分税种发生额差异7': '部分税种发生额差异金额7'}
    detail_renames = {'本期差异8': '本期差异金额8（申报表-余额表贷方）', '累计差异9': '累计差异金额9（申报表-余额表期末余额）', '差异10': '差异金额10（申报表-工资表、支撑平台税额）', '差异11': '差异金额11（工资表应发-余额表发生额）', '差异12': '差异金额12（申报表申报收入-应申报收入）', '差异': '差异金额', '（工资表-申报表）累计应纳税所得额差异': '累计应纳税所得额差异（工资表-申报表）', '（工资表-申报表）累计专项扣除差异': '累计专项扣除差异（工资表-申报表）', '（工资表-申报表）累计专项附加扣除差异（含个人养老金）': '累计专项附加扣除差异（含个人养老金）（工资表-申报表）', '（工资表-申报表）其它差异': '其它差异（工资表-申报表）', '（工资表-申报表）应纳税额差异': '应纳税额差异（工资表-申报表）'}
    for name, columns in HEADERS.items():
        sheets[name] = sheets[name].rename(columns=summary_renames if name == "汇总税额核对" else detail_renames).reindex(columns=columns)
    if not sheets["汇总税额核对"].empty:
        sheets["汇总税额核对"]["营业部简称"] = [row.get("org_name", "") for row in summaries]
    if not sheets["附A1 工资薪金等个税差异"].empty:
        sheets["附A1 工资薪金等个税差异"]["期间"] = f"{period.year}年{period.month:02d}月" if period else str(period_id)
    return sheets


def build_pit_workpaper_xlsx(db, company_id: int, period_id: int, workpaper) -> bytes:
    sheets = build_pit_workpaper_sheets(db, company_id, period_id, workpaper)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name in SHEET_NAMES:
            sheets[sheet_name].to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return output.getvalue()
