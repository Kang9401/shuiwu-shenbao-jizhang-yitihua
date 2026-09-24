import { PIT_STAGE_CONFIG } from '../../features/pit/stageConfig'
import type { LocalWorkpaperContext, LocalWorkpaperPreview, PaymentStage, ReviewDetail, ReviewStatus, SubmittedWorkpaper, WorkpaperSheet } from '../../features/pit/contracts'

const DELAY_MS = 450
const pause = (signal?: AbortSignal, duration = DELAY_MS) => new Promise<void>((resolve, reject) => {
  const timer = window.setTimeout(resolve, duration)
  signal?.addEventListener('abort', () => { window.clearTimeout(timer); reject(new DOMException('Request aborted', 'AbortError')) }, { once: true })
})

export async function mockDelay(signal?: AbortSignal, duration?: number) { await pause(signal, duration) }

function money(value: string | null) { return value }

function rowsFor(stage: PaymentStage, sheetCode: string): WorkpaperSheet['rows'] {
  if (sheetCode === 'pre_summary_tax') return [{ org_code: 'MOCK-01', org_name: '北方示例营业部', tax_period: '2026-08', declared_tax: money('12800.00'), balance_tax: money('12800.00'), 'pre.declared_vs_balance': money('0.00'), reason_1: '已核对', 'pre.declared_vs_business': money('150.25'), reason_2: '待提交人说明', 'pre.salary_taxable_income': money(null), reason_3: '来源暂缺', 'pre.broker_occurrence_vs_payroll': money('-80.00'), reason_4: '口径待确认', 'pre.other_income_occurrence': money('0.00'), reason_5: '已核对' }]
  if (sheetCode === 'post_payment_check') return [{ declared_tax: money('12800.00'), certificate_tax: money('12800.00'), 'post.declared_vs_certificate': money('0.00'), declared_vs_certificate_reason: '已核对', bank_tax: money('12750.00'), 'post.certificate_vs_bank': money('50.00'), certificate_vs_bank_reason: '付款时间差' }]
  if (sheetCode.includes('source') || sheetCode.includes('balance') || sheetCode.includes('bond') || sheetCode.includes('restricted') || sheetCode.includes('declaration') || sheetCode.includes('certificate') || sheetCode.includes('bank')) return [{ source_reference: `${sheetCode}-001`, source_name: stage === 'pre_payment' ? '合成来源材料' : '合成缴款后来源', source_amount: money('100.00'), source_date: '2026-08-31' }]
  return [{ org_code: 'MOCK-01', org_name: '北方示例营业部', amount: money('100.00'), difference: money('0.00'), submitter_reason: '合成示例原因，仅用于开发预览' }]
}

export function createSheets(stage: PaymentStage): WorkpaperSheet[] {
  return PIT_STAGE_CONFIG[stage].sheets.map((definition) => ({ ...definition, rows: rowsFor(stage, definition.sheetCode), total: 1 }))
}

export function createPreview(context: LocalWorkpaperContext, revision = 3, hasLocalChanges = true): LocalWorkpaperPreview {
  const post = context.stage === 'post_payment'
  return {
    context,
    draftRevision: revision,
    calculationStatus: post ? 'missing_sources' : 'ready',
    missingSources: post ? ['个税完税凭证'] : [],
    hasLocalChanges,
    lifecycleStatus: post ? 'data_preparation' : 'pending_submission',
    isEditable: true,
    submissionId: null,
    submissionVersion: post ? 1 : 2,
    reviewStatus: post ? 'pending_review' : 'approved',
    sheets: createSheets(context.stage),
  }
}

function submission(id: string, org: string, orgName: string, stage: PaymentStage, status: ReviewStatus, version: number, submitterName: string): SubmittedWorkpaper {
  return { submissionId: id, platformOrgId: org, platformOrgName: orgName, taxPeriod: '2026-08', stage, submissionVersion: version, recordVersion: 1, schemaVersion: 'pit-preview-v1', contentHash: `mock-${id}`, reviewStatus: status, submitterName, submittedAt: '2026-09-16T09:30:00+08:00', sheets: createSheets(stage) }
}

const records = [
  submission('sub-pre-002', 'platform-org-north', '北方示例机构', 'pre_payment', 'pending_review', 2, '提交人甲'),
  submission('sub-post-001', 'platform-org-north', '北方示例机构', 'post_payment', 'pending_review', 1, '提交人甲'),
  submission('sub-pre-001', 'platform-org-south', '南方示例机构', 'pre_payment', 'approved', 1, '提交人乙'),
  submission('sub-post-003', 'platform-org-south', '南方示例机构', 'post_payment', 'rejected', 3, '提交人乙'),
]

export function mockSubmissions() { return records }

export function detailFrom(item: SubmittedWorkpaper): ReviewDetail {
  return { ...item, history: [{ id: `${item.submissionId}-submitted`, action: 'submitted', actorName: item.submitterName, occurredAt: item.submittedAt, comment: null }] }
}
