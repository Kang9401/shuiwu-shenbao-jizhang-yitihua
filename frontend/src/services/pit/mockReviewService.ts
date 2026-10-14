import type { PageResult, PlatformAccount, ReviewDecisionRequest, ReviewDetail, ReviewListQuery, ReviewService, SubmittedWorkpaper } from '../../features/pit/contracts'
import { detailFrom, mockDelay, mockSubmissions } from './mockData'
import { applyMockReviewDecision } from './mockWorkpaperState'

export class MockReviewService implements ReviewService {
  async list(query: ReviewListQuery, account: PlatformAccount, signal?: AbortSignal): Promise<PageResult<SubmittedWorkpaper>> {
    await mockDelay(signal, account.id === 'reviewer-a' ? 900 : 120)
    let items = mockSubmissions().filter((item) => !query.stage || item.stage === query.stage).filter((item) => !query.status || item.reviewStatus === query.status).filter((item) => !query.platformOrgId || item.platformOrgId === query.platformOrgId).filter((item) => !query.taxPeriod || item.taxPeriod === query.taxPeriod).filter((item) => !query.keyword || `${item.platformOrgName}${item.submitterName}`.includes(query.keyword))
    if (account.id === 'reviewer-b') items = items.filter((item) => item.platformOrgId === 'platform-org-south')
    const start = (query.page - 1) * query.pageSize
    return { items: items.slice(start, start + query.pageSize), total: items.length }
  }

  async getDetail(submissionId: string, account: PlatformAccount, signal?: AbortSignal): Promise<ReviewDetail> {
    await mockDelay(signal)
    const item = mockSubmissions().find((record) => record.submissionId === submissionId)
    if (!item || (account.id === 'reviewer-b' && item.platformOrgId !== 'platform-org-south')) throw new Error('无权访问该模拟提交版本')
    return detailFrom(item)
  }

  async decide(request: ReviewDecisionRequest, account: PlatformAccount, signal?: AbortSignal): Promise<ReviewDetail> {
    await mockDelay(signal, 600)
    if (request.decision === 'rejected' && !request.comment.trim()) throw new Error('退回原因不能为空')
    const item = mockSubmissions().find((record) => record.submissionId === request.submissionId)
    if (!item) throw new Error('模拟提交版本不存在')
    if (request.expectedRecordVersion !== item.recordVersion) throw new Error('提交版本已更新，请刷新后重试')
    item.reviewStatus = request.decision
    item.recordVersion += 1
    applyMockReviewDecision(item.submissionId, request.decision)
    const detail = detailFrom(item)
    detail.history.push({ id: `${item.submissionId}-${item.recordVersion}`, action: request.decision, actorName: account.displayName, occurredAt: new Date().toISOString(), comment: request.comment || null })
    return detail
  }
}
