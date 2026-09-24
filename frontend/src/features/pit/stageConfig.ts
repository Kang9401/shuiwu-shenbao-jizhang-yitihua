import type { PaymentStage, WorkpaperColumn, WorkpaperSheet } from './contracts'

export interface StageSheetDefinition extends Omit<WorkpaperSheet, 'rows' | 'total'> {}

const columns = (...items: Array<[string, string, WorkpaperColumn['type']]>) => items.map(([code, label, type]) => ({ code, label, type }))
const standard = columns(['org_code', '机构代码', 'text'], ['org_name', '营业部名称', 'text'], ['amount', '金额', 'money'], ['difference', '差异金额', 'money'], ['submitter_reason', '提交人差异原因', 'text'])
const source = columns(['source_reference', '来源标识', 'text'], ['source_name', '名称', 'text'], ['source_amount', '金额', 'money'], ['source_date', '日期', 'date'])

const preSheets: StageSheetDefinition[] = [
  { sheetCode: 'pre_summary_tax', sheetName: '汇总税额核对', group: 'result', columns: columns(['org_code', '机构代码', 'text'], ['org_name', '营业部简称', 'text'], ['tax_period', '税款所属期', 'text'], ['declared_tax', '申报表', 'money'], ['balance_tax', '科目余额表期末余额', 'money'], ['pre.declared_vs_balance', '申报表与余额表差异金额1', 'money'], ['reason_1', '差异原因1', 'text'], ['pre.declared_vs_business', '申报表与工资表、支撑平台差异金额2', 'money'], ['reason_2', '差异原因2', 'text'], ['pre.salary_taxable_income', '当期工资薪金累计应纳税所得额差异金额3', 'money'], ['reason_3', '差异原因3', 'text'], ['pre.broker_occurrence_vs_payroll', '经纪人支出当期发生额与工资表差异金额4', 'money'], ['reason_4', '差异原因4', 'text'], ['pre.other_income_occurrence', '部分税种发生额差异金额5', 'money'], ['reason_5', '差异原因5', 'text']) },
  { sheetCode: 'pre_declaration_summary', sheetName: '申报表汇总数', group: 'result', columns: columns(['org_code', '机构代码', 'text'], ['org_name', '营业部名称', 'text'], ['declaration_type', '申报类型', 'text'], ['income_item', '所得项目', 'text'], ['person_count', '填写人次', 'integer'], ['income_amount', '收入合计（元）', 'money'], ['tax_amount', '应补/退税额（元）', 'money']) },
  { sheetCode: 'pre_tax_amount_check', sheetName: '个税明细税额核对', group: 'result', columns: standard },
  { sheetCode: 'pre_occurrence_check', sheetName: '其他个税发生额核对', group: 'result', columns: standard },
  { sheetCode: 'pre_appendix_a1', sheetName: '附A1 工资薪金等个税差异', group: 'result', columns: standard },
  { sheetCode: 'pre_appendix_a2', sheetName: '附A2 累计应纳税所得额差异明细', group: 'result', columns: standard },
  { sheetCode: 'pre_appendix_a3', sheetName: '附A3 客户利息个税差异明细', group: 'result', columns: standard },
  { sheetCode: 'pre_appendix_a4', sheetName: '附A4 限售股个税差异明细', group: 'result', columns: standard },
  { sheetCode: 'pre_balance_sheet', sheetName: '科目余额表', group: 'source', columns: source },
  { sheetCode: 'pre_bond_interest', sheetName: '债券利息明细', group: 'source', columns: source },
  { sheetCode: 'pre_restricted_stock', sheetName: '限售股明细', group: 'source', columns: source },
  { sheetCode: 'pre_comprehensive_declaration', sheetName: '综合所得申报表', group: 'source', columns: source },
  { sheetCode: 'pre_classified_declaration', sheetName: '分类所得申报表', group: 'source', columns: source },
  { sheetCode: 'pre_restricted_declaration', sheetName: '限售股所得申报表', group: 'source', columns: source },
]

const postSheets: StageSheetDefinition[] = [
  { sheetCode: 'post_payment_check', sheetName: '缴税核对', group: 'result', columns: columns(['declared_tax', '申报表', 'money'], ['certificate_tax', '完税证明', 'money'], ['post.declared_vs_certificate', '申报表与完税证明差异金额11', 'money'], ['declared_vs_certificate_reason_11', '差异原因11', 'text'], ['bank_tax', '银行流水个税', 'money'], ['post.certificate_vs_bank', '完税证明与银行流水差异金额12', 'money'], ['certificate_vs_bank_reason_12', '差异原因12', 'text']) },
  { sheetCode: 'post_tax_certificate', sheetName: '个税完税凭证', group: 'source', columns: source },
  { sheetCode: 'post_bank_statement', sheetName: '银行流水', group: 'source', columns: source },
  { sheetCode: 'post_bank_tax_detail', sheetName: '银行流水个税税额明细', group: 'source', columns: source },
]

export const PIT_STAGE_CONFIG: Record<PaymentStage, { label: string; sheets: StageSheetDefinition[] }> = {
  pre_payment: { label: '缴款前', sheets: preSheets },
  post_payment: { label: '缴款后', sheets: postSheets },
}

export function stageLabel(stage: PaymentStage) { return PIT_STAGE_CONFIG[stage].label }
