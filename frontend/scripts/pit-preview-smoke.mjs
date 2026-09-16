import assert from 'node:assert/strict'
import { build } from 'esbuild'

globalThis.window ??= { setTimeout, clearTimeout }

async function loadEntry(source, development) {
  const result = await build({
    stdin: { contents: source, resolveDir: process.cwd(), sourcefile: 'pit-preview-test.ts', loader: 'ts' },
    bundle: true,
    format: 'esm',
    platform: 'node',
    write: false,
    define: { 'import.meta.env.DEV': development ? 'true' : 'false' },
  })
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].contents).toString('base64')}`)
}

const development = await loadEntry(`
  import { effectScope } from 'vue'
  import { PIT_STAGE_CONFIG } from './src/features/pit/stageConfig'
  import { MockWorkpaperService } from './src/services/pit/mockWorkpaperService'
  import { MockReviewService } from './src/services/pit/mockReviewService'
  import { latestMockSubmissionPayload } from './src/services/pit/mockWorkpaperState'
  import { usePlatformSessionCache } from './src/composables/usePlatformSessionCache'
  export { effectScope, PIT_STAGE_CONFIG, MockWorkpaperService, MockReviewService, latestMockSubmissionPayload, usePlatformSessionCache }
`, true)

assert.equal(development.PIT_STAGE_CONFIG.pre_payment.sheets.length, 14, '缴款前应包含 14 张表')
assert.equal(development.PIT_STAGE_CONFIG.post_payment.sheets.length, 4, '缴款后应包含 4 张表')
const postColumns = development.PIT_STAGE_CONFIG.post_payment.sheets[0].columns.map((column) => column.code)
assert.ok(postColumns.includes('post.declared_vs_certificate'))
assert.ok(postColumns.includes('post.certificate_vs_bank'))

const workpapers = new development.MockWorkpaperService()
const preContext = { localCompanyId: 1, localPeriodId: 1, companyName: '合成机构', taxPeriod: '2026-08', stage: 'pre_payment' }
const pre = await workpapers.getPreview(preContext)
const post = await workpapers.getPreview({ localCompanyId: 1, localPeriodId: 1, companyName: '合成机构', taxPeriod: '2026-08', stage: 'post_payment' })
assert.equal(pre.sheets.length, 14)
assert.equal(post.sheets.length, 4)
assert.equal(pre.lifecycleStatus, 'data_preparation')
assert.equal(pre.calculationStatus, 'idle')
assert.equal(post.calculationStatus, 'missing_sources')
const preSummary = pre.sheets[0].rows[0]
assert.equal(preSummary['pre.declared_vs_balance'], '0.00', '零值不能视作缺失')
assert.equal(preSummary['pre.salary_taxable_income'], null, '缺失金额必须保持 null')

const review = new development.MockReviewService()
const reviewerA = { id: 'reviewer-a', displayName: 'A', role: 'mock' }
await assert.rejects(() => review.decide({ submissionId: 'sub-pre-002', decision: 'rejected', comment: '', expectedRecordVersion: 1, idempotencyKey: 'reject-empty' }, reviewerA), /退回原因不能为空/)
const pending = await workpapers.recalculate(preContext)
assert.equal(pending.lifecycleStatus, 'pending_submission')
assert.equal(pending.isEditable, true)
const submitted = await workpapers.submit(preContext)
assert.equal(submitted.lifecycleStatus, 'submitted')
assert.equal(submitted.isEditable, false)
assert.deepEqual(development.latestMockSubmissionPayload(preContext), { localCompanyId: 1, localPeriodId: 1, stage: 'pre_payment', draftRevision: submitted.draftRevision, status: 'submitted' })
await assert.rejects(() => workpapers.editDraft(preContext), /当前状态已锁定/)
await review.decide({ submissionId: 'sub-pre-002', decision: 'rejected', comment: '合成退回原因', expectedRecordVersion: 1, idempotencyKey: 'reject-1' }, reviewerA)
const rejected = await workpapers.getPreview(preContext)
assert.equal(rejected.lifecycleStatus, 'rejected')
assert.equal(rejected.isEditable, true)
const resubmissionDraft = await workpapers.editDraft(preContext)
assert.equal(resubmissionDraft.lifecycleStatus, 'pending_submission')
const reviewedContext = { localCompanyId: 2, localPeriodId: 1, companyName: '另一合成机构', taxPeriod: '2026-08', stage: 'pre_payment' }
await workpapers.recalculate(reviewedContext)
await workpapers.submit(reviewedContext)
await review.decide({ submissionId: 'sub-pre-002', decision: 'approved', comment: '合成通过意见', expectedRecordVersion: 2, idempotencyKey: 'approve-1' }, reviewerA)
const reviewed = await workpapers.getPreview(reviewedContext)
assert.equal(reviewed.lifecycleStatus, 'reviewed')
assert.equal(reviewed.isEditable, false)

const scope = development.effectScope()
let platformSession
scope.run(() => { platformSession = development.usePlatformSessionCache() })
const oldRequest = platformSession.createRequest()
const lateResponse = review.list({ page: 1, pageSize: 10 }, reviewerA, oldRequest.controller.signal)
platformSession.switchAccount('reviewer-b')
assert.equal(platformSession.isCurrent(oldRequest), false, '切换账号后旧请求必须失效')
await assert.rejects(lateResponse, (error) => error?.name === 'AbortError')
const reviewerB = platformSession.account.value
const accountBPage = await review.list({ page: 1, pageSize: 10 }, reviewerB)
assert.ok(accountBPage.items.every((item) => item.platformOrgId === 'platform-org-south'), 'B 账号只能看到自己的模拟机构')
platformSession.clearOnlineCache()
assert.equal(platformSession.isCurrent(platformSession.createRequest()), true)
scope.stop()

const production = await loadEntry(`
  import { workpaperService } from './src/services/pit/workpaperService'
  import { reviewService } from './src/services/pit/reviewService'
  export { workpaperService, reviewService }
`, false)
await assert.rejects(() => production.workpaperService.getPreview({ localCompanyId: 1, localPeriodId: 1, companyName: '合成机构', taxPeriod: '2026-08', stage: 'pre_payment' }), (error) => error?.name === 'PitServiceNotIntegratedError')
await assert.rejects(() => production.reviewService.list({ page: 1, pageSize: 10 }, reviewerA), (error) => error?.name === 'PitServiceNotIntegratedError')

console.log('pit-preview smoke tests passed')
