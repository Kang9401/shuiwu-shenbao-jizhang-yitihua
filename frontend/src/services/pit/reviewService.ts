import type { PageResult, PlatformAccount, ReviewDecisionRequest, ReviewDetail, ReviewListQuery, ReviewService, SubmittedWorkpaper } from '../../features/pit/contracts'
import { PitServiceNotIntegratedError } from '../../features/pit/contracts'
import { MockReviewService } from './mockReviewService'

class UnavailableReviewService implements ReviewService {
  async list(_query: ReviewListQuery, _account: PlatformAccount): Promise<PageResult<SubmittedWorkpaper>> { throw new PitServiceNotIntegratedError() }
  async getDetail(_submissionId: string, _account: PlatformAccount): Promise<ReviewDetail> { throw new PitServiceNotIntegratedError() }
  async decide(_request: ReviewDecisionRequest, _account: PlatformAccount): Promise<ReviewDetail> { throw new PitServiceNotIntegratedError() }
}

export const reviewService: ReviewService = import.meta.env.DEV ? new MockReviewService() : new UnavailableReviewService()
