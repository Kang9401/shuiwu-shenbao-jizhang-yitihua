import type { LocalWorkpaperContext, LocalWorkpaperPreview, ReviewStatus, WorkpaperLifecycleStatus } from '../../features/pit/contracts'
import { createSheets } from './mockData'

type DraftState = {
  revision: number
  lifecycleStatus: WorkpaperLifecycleStatus
  calculationStatus: LocalWorkpaperPreview['calculationStatus']
  missingSources: string[]
  submissionVersion: number | null
  submissionId: string | null
  reviewStatus: ReviewStatus | null
  hasLocalChanges: boolean
}

const drafts = new Map<string, DraftState>()
const keyOf = (context: LocalWorkpaperContext) => `${context.localCompanyId}:${context.localPeriodId}:${context.stage}`
const submissionForStage = (stage: LocalWorkpaperContext['stage']) => stage === 'pre_payment' ? 'sub-pre-002' : 'sub-post-001'

function initialState(context: LocalWorkpaperContext): DraftState {
  const missingSources = context.stage === 'post_payment' ? ['个税完税凭证'] : []
  return { revision: 1, lifecycleStatus: 'data_preparation', calculationStatus: missingSources.length ? 'missing_sources' : 'idle', missingSources, submissionVersion: null, submissionId: null, reviewStatus: null, hasLocalChanges: false }
}

function stateFor(context: LocalWorkpaperContext) {
  const key = keyOf(context)
  let state = drafts.get(key)
  if (!state) { state = initialState(context); drafts.set(key, state) }
  return state
}

function preview(context: LocalWorkpaperContext, state: DraftState): LocalWorkpaperPreview {
  return { context, draftRevision: state.revision, calculationStatus: state.calculationStatus, missingSources: state.missingSources, hasLocalChanges: state.hasLocalChanges, lifecycleStatus: state.lifecycleStatus, isEditable: ['data_preparation', 'pending_submission', 'rejected'].includes(state.lifecycleStatus), submissionId: state.submissionId, submissionVersion: state.submissionVersion, reviewStatus: state.reviewStatus, sheets: createSheets(context.stage) }
}

export function getMockWorkpaper(context: LocalWorkpaperContext) { return preview(context, stateFor(context)) }

export function recalculateMockWorkpaper(context: LocalWorkpaperContext) {
  const state = stateFor(context)
  state.revision += 1
  state.hasLocalChanges = false
  if (state.missingSources.length) { state.lifecycleStatus = 'data_preparation'; state.calculationStatus = 'missing_sources' } else { state.lifecycleStatus = 'pending_submission'; state.calculationStatus = 'ready' }
  return preview(context, state)
}

export function editMockWorkpaper(context: LocalWorkpaperContext) {
  const state = stateFor(context)
  if (!['data_preparation', 'pending_submission', 'rejected'].includes(state.lifecycleStatus)) throw new Error('当前状态已锁定，不能修改数据')
  state.revision += 1
  state.hasLocalChanges = true
  if (!state.missingSources.length) state.lifecycleStatus = 'pending_submission'
  return preview(context, state)
}

export function submitMockWorkpaper(context: LocalWorkpaperContext) {
  const state = stateFor(context)
  if (!['pending_submission', 'rejected'].includes(state.lifecycleStatus)) throw new Error('仅待提交或已退回的底稿可以提交')
  state.lifecycleStatus = 'submitted'
  state.calculationStatus = 'ready'
  state.hasLocalChanges = false
  state.submissionVersion = (state.submissionVersion || 0) + 1
  state.submissionId = submissionForStage(context.stage)
  state.reviewStatus = 'pending_review'
  return preview(context, state)
}

export function applyMockReviewDecision(submissionId: string, reviewStatus: 'approved' | 'rejected') {
  drafts.forEach((state) => {
    if (state.submissionId !== submissionId) return
    state.reviewStatus = reviewStatus
    state.lifecycleStatus = reviewStatus === 'approved' ? 'reviewed' : 'rejected'
  })
}

export function latestMockSubmissionPayload(context: LocalWorkpaperContext) {
  const state = stateFor(context)
  return state.submissionId ? { localCompanyId: context.localCompanyId, localPeriodId: context.localPeriodId, stage: context.stage, draftRevision: state.revision, status: 'submitted' as const } : null
}
