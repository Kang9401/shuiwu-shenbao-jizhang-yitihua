<template>
  <div class="pit-review-page">
    <el-alert v-if="isPreview" title="开发预览 / 模拟线上会话数据" type="warning" :closable="false" show-icon description="模拟账号与复核结果只存在当前页面内存，不代表平台正式复核成功。" />
    <el-alert v-else title="线上复核服务尚未接入" type="info" :closable="false" show-icon />
    <section class="card"><div class="card-header"><div><strong>个税底稿复核</strong><p>独立线上上下文，不使用当前本地分公司 ID 或所属期 ID 作为复核身份。</p></div><div class="pit-review-session"><el-select :model-value="account?.id" :disabled="!loggedIn" placeholder="模拟账号" @update:model-value="switchAccount"><el-option v-for="item in accounts" :key="item.id" :label="`${item.displayName} · ${item.role}`" :value="item.id" /></el-select><el-button :disabled="!loggedIn" @click="logout">模拟注销</el-button><el-button :disabled="!loggedIn" @click="expire">模拟认证失效</el-button><el-button type="warning" @click="clearCache">清除线上缓存</el-button></div></div>
      <div v-if="loggedIn" class="pit-review-account">当前线上账号：<strong>{{ account?.displayName }}</strong>（{{ account?.role }}） · 会话世代 {{ epoch }}</div><el-empty v-else description="模拟会话已清理，请选择账号重新进入" />
    </section>
    <section v-if="loggedIn" class="card"><div class="pit-review-filters"><el-select v-model="filters.stage" clearable placeholder="全部阶段"><el-option label="缴款前" value="pre_payment" /><el-option label="缴款后" value="post_payment" /></el-select><el-select v-model="filters.status" clearable placeholder="全部状态"><el-option label="待复核" value="pending_review" /><el-option label="已通过" value="approved" /><el-option label="已退回" value="rejected" /></el-select><el-input v-model="filters.keyword" clearable placeholder="机构或提交人" /><el-button type="primary" :loading="loading" @click="refresh">刷新</el-button></div>
      <el-alert v-if="cacheCleared" title="线上缓存已清理" type="info" :closable="false" description="不会自动重新加载；点击“刷新”按当前账号重新获取。" />
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-table v-if="items.length" :data="items" border size="small" @row-click="openDetail"><el-table-column prop="platformOrgName" label="线上归属机构" min-width="160" /><el-table-column prop="taxPeriod" label="税款所属期" width="110" /><el-table-column label="阶段" width="90"><template #default="{ row }">{{ stageLabel(row.stage) }}</template></el-table-column><el-table-column label="提交版本" width="95"><template #default="{ row }">v{{ row.submissionVersion }}</template></el-table-column><el-table-column prop="submitterName" label="提交人" width="100" /><el-table-column prop="submittedAt" label="提交时间" min-width="165" /><el-table-column label="复核状态" width="100"><template #default="{ row }"><el-tag :type="statusType(row.reviewStatus)">{{ statusLabel(row.reviewStatus) }}</el-tag></template></el-table-column><el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click.stop="openDetail(row)">查看</el-button></template></el-table-column></el-table>
      <el-empty v-else-if="!loading && !error && !cacheCleared" description="暂无可查看的模拟提交版本" />
      <div class="pit-review-pagination"><el-pagination v-if="total" v-model:current-page="filters.page" :page-size="filters.pageSize" layout="total, prev, pager, next" :total="total" @current-change="refresh" /></div>
    </section>
    <el-drawer v-model="drawerVisible" size="82%" :close-on-click-modal="false" @closed="closeDetail"><template #header><div><strong>固定提交版本复核</strong><p v-if="detail">{{ detail.platformOrgName }} · {{ detail.taxPeriod }} · {{ stageLabel(detail.stage) }} · v{{ detail.submissionVersion }} · {{ detail.submitterName }}</p></div></template><template v-if="detail"><el-alert title="只读提交快照" type="info" :closable="false" description="金额和提交人的差异原因不可在复核页修改；本页没有重算、导出、下载或打印功能。" /><el-tabs v-model="activeSheet"><el-tab-pane v-for="sheet in detail.sheets" :key="sheet.sheetCode" :name="sheet.sheetCode" :label="sheet.sheetName"><WorkpaperSheetViewer :sheet="sheet" /></el-tab-pane></el-tabs><section class="pit-review-history"><strong>复核历史</strong><el-timeline><el-timeline-item v-for="entry in detail.history" :key="entry.id" :timestamp="entry.occurredAt">{{ historyLabel(entry.action) }} · {{ entry.actorName }}<span v-if="entry.comment">：{{ entry.comment }}</span></el-timeline-item></el-timeline></section><ReviewDecisionPanel v-if="detail.reviewStatus === 'pending_review'" :loading="decisionLoading" @decide="decide" /></template></el-drawer>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import WorkpaperSheetViewer from '../components/pit/WorkpaperSheetViewer.vue'
import ReviewDecisionPanel from '../components/pit/ReviewDecisionPanel.vue'
import { stageLabel } from '../features/pit/stageConfig'
import type { ReviewDetail, ReviewStatus, SubmittedWorkpaper } from '../features/pit/contracts'
import { PitServiceNotIntegratedError } from '../features/pit/contracts'
import { reviewService } from '../services/pit/reviewService'
import { MOCK_PLATFORM_ACCOUNTS, usePlatformSessionCache } from '../composables/usePlatformSessionCache'

const isPreview = import.meta.env.DEV
const { account, epoch, loggedIn, createRequest, isCurrent, clearOnlineCache, switchAccount: updateAccount, logout: sessionLogout, expire: sessionExpire } = usePlatformSessionCache()
const accounts = MOCK_PLATFORM_ACCOUNTS
const items = ref<SubmittedWorkpaper[]>([]); const total = ref(0); const loading = ref(false); const decisionLoading = ref(false); const error = ref(''); const cacheCleared = ref(false); const drawerVisible = ref(false); const detail = ref<ReviewDetail | null>(null); const activeSheet = ref('')
const filters = reactive<{ stage?: 'pre_payment' | 'post_payment'; status?: ReviewStatus; keyword?: string; page: number; pageSize: number }>({ page: 1, pageSize: 10 })
function clearDisplay() { items.value = []; total.value = 0; detail.value = null; drawerVisible.value = false; error.value = '' }
function clearCache() { clearOnlineCache(); clearDisplay(); cacheCleared.value = true; ElMessage.info('线上复核缓存已清理；本地机构、工作稿和文件未受影响') }
function switchAccount(id: string) { updateAccount(id); clearDisplay(); cacheCleared.value = true; ElMessage.info('已切换模拟账号，旧账号请求结果将被丢弃') }
function logout() { sessionLogout(); clearDisplay(); cacheCleared.value = true; ElMessage.info('模拟注销已清理线上会话数据') }
function expire() { sessionExpire(); clearDisplay(); cacheCleared.value = true; ElMessage.warning('模拟认证已失效，线上会话数据已清理') }
function statusLabel(status: ReviewStatus) { return status === 'pending_review' ? '待复核' : status === 'approved' ? '已复核' : status === 'rejected' ? '已退回' : '已撤回' }
function statusType(status: ReviewStatus) { return status === 'approved' ? 'success' : status === 'rejected' ? 'danger' : status === 'pending_review' ? 'warning' : 'info' }
function historyLabel(action: string) { return action === 'submitted' ? '已提交' : action === 'approved' ? '已复核' : '已退回' }
function message(errorValue: unknown) { return errorValue instanceof PitServiceNotIntegratedError ? errorValue.message : errorValue instanceof Error ? errorValue.message : '线上复核请求失败' }
async function refresh() { if (!account.value) return; const request = createRequest(); loading.value = true; error.value = ''; cacheCleared.value = false; try { const page = await reviewService.list({ ...filters }, account.value, request.controller.signal); if (isCurrent(request)) { items.value = page.items; total.value = page.total } } catch (reason) { if ((reason as Error).name !== 'AbortError' && isCurrent(request)) error.value = message(reason) } finally { if (isCurrent(request)) loading.value = false } }
async function openDetail(row: SubmittedWorkpaper) { if (!account.value) return; const request = createRequest(); try { const next = await reviewService.getDetail(row.submissionId, account.value, request.controller.signal); if (isCurrent(request)) { detail.value = next; activeSheet.value = next.sheets[0]?.sheetCode || ''; drawerVisible.value = true } } catch (reason) { if ((reason as Error).name !== 'AbortError' && isCurrent(request)) { error.value = message(reason); ElMessage.error(error.value) } } }
function closeDetail() { detail.value = null; activeSheet.value = '' }
async function decide(decision: 'approved' | 'rejected', comment: string) { if (!detail.value || !account.value || decisionLoading.value) return; const request = createRequest(); decisionLoading.value = true; try { const next = await reviewService.decide({ submissionId: detail.value.submissionId, decision, comment, expectedRecordVersion: detail.value.recordVersion, idempotencyKey: crypto.randomUUID() }, account.value, request.controller.signal); if (isCurrent(request)) { detail.value = next; await refresh(); ElMessage.success('模拟复核结论已更新，不代表平台正式复核成功') } } catch (reason) { if (isCurrent(request)) ElMessage.error(message(reason)) } finally { if (isCurrent(request)) decisionLoading.value = false } }
watch(() => [filters.stage, filters.status, filters.keyword], () => { filters.page = 1 })
</script>

<style scoped>
.pit-review-page { display:grid; gap:16px; }.pit-review-session,.pit-review-filters { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }.pit-review-session .el-select { width:220px; }.pit-review-account { margin-top:14px; color:var(--el-text-color-secondary); font-size:13px; }.pit-review-filters { margin-bottom:14px; }.pit-review-filters .el-select,.pit-review-filters .el-input { width:180px; }.pit-review-pagination { display:flex; justify-content:flex-end; margin-top:14px; }.pit-review-history { margin:20px 0; }.pit-review-history > strong { display:block; margin-bottom:12px; }.el-drawer__header p { margin:5px 0 0; color:var(--el-text-color-secondary); font-size:13px; }
</style>
