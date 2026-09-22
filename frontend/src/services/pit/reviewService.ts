import type { PageResult, PlatformAccount, ReviewDecisionRequest, ReviewDetail, ReviewListQuery, ReviewService, SubmittedWorkpaper, WorkpaperSheet } from '../../features/pit/contracts'
import { PitServiceNotIntegratedError } from '../../features/pit/contracts'
import { fmssApi } from '../../api'

function normal(value: unknown) { return String(value ?? '').trim().normalize('NFC') }
function stage(value: unknown) { return String(value).toUpperCase() === 'POST' ? 'post_payment' as const : 'pre_payment' as const }

class FmssReviewService implements ReviewService {
  async list(query: ReviewListQuery, account: PlatformAccount): Promise<PageResult<SubmittedWorkpaper>> {
    const periodId = Number(query.taxPeriod)
    if (!Number.isInteger(periodId)) return { items: [], total: 0 }
    const { data } = await fmssApi.approvalLog(periodId)
    const rows = Array.isArray(data?.rows) ? data.rows : []
    const deduped = new Map<string, any>()
    for (const row of rows) {
      if (row.approvalStatus !== 'REVIEWING' || normal(row.reviewer) !== normal(account.id)) continue
      const key = `${row.declarationId}:${row.stage}`
      const previous = deduped.get(key)
      if (!previous || String(row.reviewedAt || row.createdAt || '') > String(previous.reviewedAt || previous.createdAt || '')) deduped.set(key, row)
    }
    const items = [...deduped.values()].map((row): SubmittedWorkpaper => ({
      submissionId: String(row.declarationId), platformOrgId: String(row.branchCode ?? ''), platformOrgName: String(row.branchName ?? row.branchCode ?? ''), taxPeriod: String(row.taxMonth ?? ''), stage: stage(row.stage), submissionVersion: 1, recordVersion: 0, schemaVersion: 'fmss-live', contentHash: '', reviewStatus: 'pending_review', submitterName: String(row.submitter ?? row.creator ?? ''), submittedAt: String(row.createdAt ?? ''), sheets: [],
    }))
    return { items, total: items.length }
  }

  async getDetail(submissionId: string, _account: PlatformAccount): Promise<ReviewDetail> {
    const { data } = await fmssApi.review(submissionId)
    const document = data?.document ?? data?.declaration ?? data ?? {}
    const localStage = stage(document.stage)
    const [sheetDefinitions] = await Promise.all([fmssApi.sheets(localStage === 'post_payment' ? 'POST' : 'PRE')])
    const rawSheets = Array.isArray(data?.sheets) ? data.sheets : Array.isArray(document?.sheets) ? document.sheets : []
    const sheets: WorkpaperSheet[] = rawSheets.map((sheet: any) => {
      const definition = sheetDefinitions.data.find((item) => item.key === sheet.key || item.title === sheet.title)
      const headers = Array.isArray(sheet.headers) ? sheet.headers : definition?.headers || []
      const rows = Array.isArray(sheet.rows) ? sheet.rows : []
      return {
        sheetCode: String(sheet.key ?? sheet.sheetKey ?? sheet.title ?? ''),
        sheetName: String(sheet.title ?? sheet.key ?? ''),
        group: 'result' as const,
        columns: headers.map((label: string, index: number) => ({ code: `c${index}`, label, type: 'text' as const })),
        rows: rows.map((row: unknown[]) => Object.fromEntries((row ?? []).map((value, index) => [`c${index}`, value]))),
        total: rows.length,
      }
    })
    return { submissionId, platformOrgId: String(document.branchCode ?? ''), platformOrgName: String(document.branchName ?? document.branchCode ?? ''), taxPeriod: String(document.month ?? document.taxMonth ?? ''), stage: stage(document.stage), submissionVersion: 1, recordVersion: 0, schemaVersion: 'fmss-live', contentHash: '', reviewStatus: document.status === 'APPROVED' ? 'approved' : document.status === 'RETURNED' ? 'rejected' : 'pending_review', submitterName: String(document.submitter ?? ''), submittedAt: String(document.createdAt ?? ''), sheets, history: [] }
  }

  async decide(request: ReviewDecisionRequest, account: PlatformAccount): Promise<ReviewDetail> {
    await fmssApi.decision(request.submissionId, request.decision === 'approved', request.comment)
    return this.getDetail(request.submissionId, account)
  }
}

export const reviewService: ReviewService = new FmssReviewService()
