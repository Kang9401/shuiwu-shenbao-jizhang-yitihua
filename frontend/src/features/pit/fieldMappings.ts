export const PIT_FIELD_MAPPINGS = [
  { code: 'pre.declared_vs_balance', label: '缴款前汇总差异1', legacyField: 'difference_1' },
  { code: 'pre.declared_vs_business', label: '缴款前汇总差异2', legacyField: 'difference_2' },
  { code: 'pre.salary_taxable_income', label: '缴款前汇总差异3', legacyField: 'taxable_income_difference' },
  { code: 'pre.broker_occurrence_vs_payroll', label: '缴款前汇总差异4', legacyField: 'broker_occurrence_difference' },
  { code: 'pre.other_income_occurrence', label: '缴款前汇总差异5', legacyField: 'other_income_difference' },
  { code: 'pre.current_declared_vs_credit', label: '缴款前明细差异6', legacyField: 'current_difference' },
  { code: 'pre.cumulative_declared_vs_closing', label: '缴款前明细差异7', legacyField: 'cumulative_difference' },
  { code: 'pre.declared_vs_business_detail', label: '缴款前明细差异8', legacyField: 'business_declared_difference' },
  { code: 'pre.broker_payroll_vs_occurrence_detail', label: '缴款前发生额差异9', legacyField: 'broker_occurrence_difference' },
  { code: 'pre.declared_income_vs_expected', label: '缴款前发生额差异10', legacyField: 'declared_income_difference' },
  { code: 'post.declared_vs_certificate', label: '申报表与完税证明差异金额11', legacyField: 'difference_4' },
  { code: 'post.certificate_vs_bank', label: '完税证明与银行流水差异金额12', legacyField: 'difference_5' },
] as const

export const POST_PAYMENT_DIFFERENCE_CODES = {
  declaredVsCertificate: 'post.declared_vs_certificate',
  certificateVsBank: 'post.certificate_vs_bank',
} as const
