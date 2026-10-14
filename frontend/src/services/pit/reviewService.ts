import type { PageResult, PlatformAccount, ReviewDecisionRequest, ReviewDetail, ReviewListQuery, ReviewService, SubmittedWorkpaper, WorkpaperSheet } from '../../features/pit/contracts'
import { PitServiceNotIntegratedError } from '../../features/pit/contracts'
import { fmssApi } from '../../api'

function normal(value: unknown) { return String(value ?? '').trim().normalize('NFC') }
function stage(value: unknown) { return String(value).toUpperCase() === 'POST' ? 'post_payment' as const : 'pre_payment' as const }
function reviewStatus(value: unknown) {
  const status = String(value ?? '').toUpperCase()
  if (status === 'APPROVED') return 'approved' as const
  if (status === 'RETURNED') return 'rejected' as const
  return 'pending_review' as const
}
function columnType(label: string) {
  if (/金额|税额|收入|余额|扣除|发生额|税款/.test(label)) return 'money' as const
  if (/日期|时间|期间/.test(label)) return 'date' as const
  if (/人次|数量/.test(label)) return 'integer' as const
  return 'text' as const
}
function sheetRows(raw: any, headers: string[]): Array<Record<string, string | number | null>> {
  const values = Array.isArray(raw) ? raw : raw?.rows ?? raw?.data ?? raw?.values ?? []
  if (!Array.isArray(values)) return []
  return values.map((row: unknown) => {
    if (Array.isArray(row)) {
      return Object.fromEntries(row.map((value, index) => [`c${index}`, value ?? null]))
    }
    if (row && typeof row === 'object') {
      const source = row as Record<string, unknown>
      return Object.fromEntries(headers.map((header, index) => [
        `c${index}`,
        source[`c${index}`] ?? source[header] ?? source[String(index)] ?? null,
      ]))
    }
    return {}
  })
}

class FmssReviewService implements ReviewService {
  async list(query: ReviewListQuery, account: PlatformAccount): Promise<PageResult<SubmittedWorkpaper>> {
    const periodId = Number(query.taxPeriod)
    if (!Number.isInteger(periodId)) return { items: [], total: 0 }
    const { data } = await fmssApi.approvalLog(periodId)
    const rows = Array.isArray(data?.rows) ? data.rows : []
    const deduped = new Map<string, any>()
    for (const row of rows) {
      const key = `${row.declarationId}:${row.stage}`
      const previous = deduped.get(key)
      if (!previous || String(row.submittedAt || row.reviewedAt || row.createdAt || '') > String(previous.submittedAt || previous.reviewedAt || previous.createdAt || '')) deduped.set(key, row)
    }
    const items = [...deduped.values()].map((row): SubmittedWorkpaper => ({
      submissionId: String(row.declarationId), platformOrgId: String(row.branchCode ?? ''), platformOrgName: String(row.branchName ?? row.branchCode ?? ''), taxPeriod: String(row.taxMonth ?? row.tax_month ?? ''), stage: stage(row.stage), submissionVersion: 1, recordVersion: 0, schemaVersion: 'fmss-live', contentHash: '', reviewStatus: reviewStatus(row.approvalStatus), submitterName: String(row.submittedBy ?? row.submitter ?? row.creator ?? ''), submittedAt: String(row.submittedAt ?? row.createdAt ?? ''), sheets: [], reviewerName: String(row.reviewer ?? ''), canReview: row.approvalStatus === 'REVIEWING' && (!account.id || normal(row.reviewer) === normal(account.id)), canWithdraw: row.approvalStatus === 'REVIEWING',
    }))
    return { items, total: items.length }
  }

  async getDetail(submissionId: string, _account: PlatformAccount): Promise<ReviewDetail> {
    const { data } = await fmssApi.review(submissionId)
    const document = data?.document ?? data?.declaration ?? data ?? {}
    const localStage = stage(document.stage)
    const [sheetDefinitions] = await Promise.all([fmssApi.sheets(localStage === 'post_payment' ? 'POST' : 'PRE')])
    const rawPayload = data?.sheets ?? document?.sheets
    const rawSheets = Array.isArray(rawPayload)
      ? rawPayload.reduce((map: Record<string, any>, sheet: any) => { map[String(sheet.key ?? sheet.sheetKey ?? sheet.title ?? '')] = sheet; return map }, {})
      : (rawPayload && typeof rawPayload === 'object' ? rawPayload : {})
    const definitions = Array.isArray(sheetDefinitions.data) ? sheetDefinitions.data : []
    const keys = [...new Set([
      ...definitions.map((item) => item.key),
      ...Object.keys(rawSheets).map((key) => definitions.find((item) => item.title === key)?.key ?? key),
    ])]
    const sheets: WorkpaperSheet[] = keys.map((key) => {
      const definition = definitions.find((item) => item.key === key || item.title === key)
      const raw = rawSheets[key] ?? (definition ? rawSheets[definition.title] : undefined)
      const headers = Array.isArray(raw?.headers) ? raw.headers : definition?.headers || []
      const rows = sheetRows(raw, headers)
      return {
        sheetCode: String(definition?.key ?? key),
        sheetName: String(raw?.title ?? definition?.title ?? key),
        group: 'result' as const,
        columns: headers.map((label: string, index: number) => ({ code: `c${index}`, label, type: columnType(label) })),
        rows,
        total: rows.length,
      }
    })
    return { submissionId, platformOrgId: String(document.branchCode ?? document.branch_code ?? ''), platformOrgName: String(document.branchName ?? document.branch_name ?? document.branchCode ?? ''), taxPeriod: String(document.month ?? document.taxMonth ?? document.tax_month ?? ''), stage: stage(document.stage), submissionVersion: 1, recordVersion: 0, schemaVersion: 'fmss-live', contentHash: '', reviewStatus: document.status === 'APPROVED' ? 'approved' : document.status === 'RETURNED' ? 'rejected' : 'pending_review', submitterName: String(document.submittedBy ?? document.submitter ?? ''), submittedAt: String(document.submittedAt ?? document.createdAt ?? ''), sheets, history: [] }
  }

  async decide(request: ReviewDecisionRequest, account: PlatformAccount): Promise<ReviewDetail> {
    await fmssApi.decision(request.submissionId, request.decision === 'approved', request.comment)
    return this.getDetail(request.submissionId, account)
  }
}

export const reviewService: ReviewService = new FmssReviewService()
