export type PaymentStage = 'pre_payment' | 'post_payment'
export type ReviewStatus = 'pending_review' | 'approved' | 'rejected' | 'withdrawn'
export type WorkpaperLifecycleStatus = 'data_preparation' | 'pending_submission' | 'submitted' | 'rejected' | 'reviewed'
export type Money = string | null

export interface WorkpaperColumn {
  code: string
  label: string
  type: 'text' | 'money' | 'date' | 'integer'
}

export interface WorkpaperSheet {
  sheetCode: string
  sheetName: string
  group: 'result' | 'source'
  columns: WorkpaperColumn[]
  rows: Array<Record<string, string | number | null>>
  total: number
}

export interface LocalWorkpaperContext {
  localCompanyId: number
  localPeriodId: number
  companyName: string
  taxPeriod: string
  stage: PaymentStage
}

export interface LocalWorkpaperPreview {
  context: LocalWorkpaperContext
  draftRevision: number
  calculationStatus: 'idle' | 'ready' | 'missing_sources' | 'running'
  missingSources: string[]
  hasLocalChanges: boolean
  lifecycleStatus: WorkpaperLifecycleStatus
  isEditable: boolean
  submissionId: string | null
  submissionVersion: number | null
  reviewStatus: ReviewStatus | null
  sheets: WorkpaperSheet[]
}

export interface WorkpaperSubmissionRequest {
  localCompanyId: number
  localPeriodId: number
  stage: PaymentStage
  draftRevision: number
  status: 'submitted'
}

export interface SubmittedWorkpaper {
  submissionId: string
  platformOrgId: string
  platformOrgName: string
  taxPeriod: string
  stage: PaymentStage
  submissionVersion: number
  recordVersion: number
  schemaVersion: string
  contentHash: string
  reviewStatus: ReviewStatus
  submitterName: string
  submittedAt: string
  sheets: WorkpaperSheet[]
}

export interface ReviewHistoryItem {
  id: string
  action: 'submitted' | 'approved' | 'rejected'
  actorName: string
  occurredAt: string
  comment: string | null
}

export interface ReviewDetail extends SubmittedWorkpaper {
  history: ReviewHistoryItem[]
}

export interface ReviewDecisionRequest {
  submissionId: string
  decision: 'approved' | 'rejected'
  comment: string
  expectedRecordVersion: number
  idempotencyKey: string
}

export interface PlatformAccount {
  id: string
  displayName: string
  role: string
}

export interface ReviewListQuery {
  platformOrgId?: string
  taxPeriod?: string
  stage?: PaymentStage
  status?: ReviewStatus
  keyword?: string
  page: number
  pageSize: number
}

export interface PageResult<T> {
  items: T[]
  total: number
}

export interface WorkpaperService {
  getPreview(context: LocalWorkpaperContext, signal?: AbortSignal): Promise<LocalWorkpaperPreview>
  recalculate(context: LocalWorkpaperContext, signal?: AbortSignal): Promise<LocalWorkpaperPreview>
  editDraft(context: LocalWorkpaperContext, signal?: AbortSignal): Promise<LocalWorkpaperPreview>
  submit(context: LocalWorkpaperContext, signal?: AbortSignal): Promise<LocalWorkpaperPreview>
}

export interface ReviewService {
  list(query: ReviewListQuery, account: PlatformAccount, signal?: AbortSignal): Promise<PageResult<SubmittedWorkpaper>>
  getDetail(submissionId: string, account: PlatformAccount, signal?: AbortSignal): Promise<ReviewDetail>
  decide(request: ReviewDecisionRequest, account: PlatformAccount, signal?: AbortSignal): Promise<ReviewDetail>
}

export class PitServiceNotIntegratedError extends Error {
  constructor() {
    super('个税底稿分阶段与线上复核尚未接入真实服务')
    this.name = 'PitServiceNotIntegratedError'
  }
}
