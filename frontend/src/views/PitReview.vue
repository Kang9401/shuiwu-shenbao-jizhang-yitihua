<template>
  <div class="pit-review-page">
    <section class="card workflow-card">
      <div class="card-header"><div><strong>个税底稿复核</strong><p>查询当前所属期的个税审批记录；待当前账号复核时才可执行通过或退回。</p></div><div><el-button v-if="!session.connected" type="primary" @click="openLogin">登录 FMSS</el-button><el-button v-else @click="refresh">刷新</el-button></div></div>
      <div class="pit-review-account">FMSS账号：<strong>{{ session.username || (session.connected ? '已登录（账号信息未获取）' : '未登录') }}</strong> · 当前所属期：{{ periodLabel || '未选择' }}</div>
    </section>
    <section v-if="session.connected" class="card workflow-card">
      <div class="pit-review-filters"><el-select v-model="filters.stage" clearable placeholder="全部阶段"><el-option label="缴款前" value="pre_payment" /><el-option label="缴款后" value="post_payment" /></el-select><el-select v-model="filters.status" clearable placeholder="全部状态"><el-option label="审核中" value="pending_review" /><el-option label="已通过" value="approved" /><el-option label="已退回" value="rejected" /></el-select><el-input v-model="filters.keyword" clearable placeholder="申报单、分公司、提交人或复核人" /><el-button type="primary" :loading="loading" @click="refresh">查询</el-button></div>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-table v-else :data="filteredItems" v-loading="loading" border size="small" @row-click="openDetail"><el-table-column prop="submissionId" label="申报单ID" width="100" /><el-table-column prop="platformOrgName" label="FMSS分公司" min-width="140" /><el-table-column prop="taxPeriod" label="所属期" width="110" /><el-table-column label="阶段" width="90"><template #default="{ row }">{{ stageLabel(row.stage) }}</template></el-table-column><el-table-column prop="submitterName" label="提交人" width="110" /><el-table-column prop="reviewerName" label="复核人" width="110" /><el-table-column label="状态" width="90"><template #default="{ row }">{{ reviewStatusLabel(row.reviewStatus) }}</template></el-table-column><el-table-column prop="submittedAt" label="提交时间" min-width="160" /><el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click.stop="openDetail(row)">查看</el-button></template></el-table-column></el-table>
      <el-empty v-if="!loading && !error && !items.length" description="当前所属期暂无FMSS个税审批记录" />
    </section>
    <el-drawer v-model="drawerVisible" size="92%">
      <template #header>
        <div><strong>FMSS申报单复核</strong><p v-if="detail">{{ detail.platformOrgName }} · {{ detail.taxPeriod }} · {{ stageLabel(detail.stage) }}</p></div>
      </template>
      <template v-if="detail">
        <FmssPitWorkpaperViewer :sheets="detail.sheets" :stage="detail.stage" :status="detail.reviewStatus === 'approved' ? 'APPROVED' : detail.reviewStatus === 'rejected' ? 'RETURNED' : 'REVIEWING'" />
        <ReviewDecisionPanel :allow-review="Boolean(detail.canReview)" :allow-withdraw="Boolean(detail.canWithdraw)" :loading="decisionLoading" @decide="decide" @withdraw="withdraw" />
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import ReviewDecisionPanel from '../components/pit/ReviewDecisionPanel.vue'
import FmssPitWorkpaperViewer from '../components/pit/FmssPitWorkpaperViewer.vue'
import { fmssApi } from '../api'
import { stageLabel } from '../features/pit/stageConfig'
import type { PlatformAccount, ReviewDetail, SubmittedWorkpaper } from '../features/pit/contracts'
import { reviewService } from '../services/pit/reviewService'

const props = defineProps<{ companyId?: number | null; periodId?: number | null; periodLabel?: string }>()
const session = reactive({ connected: false, username: null as string | null })
const filters = reactive<{ stage?: 'pre_payment' | 'post_payment'; status?: 'pending_review' | 'approved' | 'rejected'; keyword: string }>({ keyword: '' })
const items = ref<SubmittedWorkpaper[]>([]); const loading = ref(false); const decisionLoading = ref(false); const error = ref(''); const drawerVisible = ref(false); const detail = ref<ReviewDetail | null>(null)
const account = computed<PlatformAccount | null>(() => session.connected ? { id: session.username || '', displayName: session.username || 'FMSS用户', role: 'FMSS用户' } : null)
const filteredItems = computed(() => items.value.filter((item) => (!filters.stage || item.stage === filters.stage) && (!filters.status || item.reviewStatus === filters.status) && (!filters.keyword || JSON.stringify(item).includes(filters.keyword))))
function reviewStatusLabel(status: string) { return ({ pending_review: '审核中', approved: '已通过', rejected: '已退回', withdrawn: '已撤回' } as Record<string, string>)[status] || status }
async function loadSession() { try { const { data } = await fmssApi.session(); session.connected = data.connected; session.username = data.username } catch { session.connected = false; session.username = null } }
async function openLogin() { try { await fmssApi.openBrowserLogin(); ElMessage.info('已打开独立FMSS登录窗口，请完成OA登录。') } catch (error: any) { ElMessage.error(error?.response?.data?.detail || 'FMSS登录页无法打开') } }
async function refresh() { if (!props.periodId || !account.value) return; loading.value = true; error.value = ''; try { const result = await reviewService.list({ taxPeriod: String(props.periodId), page: 1, pageSize: 100 }, account.value); items.value = result.items } catch (err: any) { error.value = err?.response?.data?.detail || 'FMSS复核列表加载失败' } finally { loading.value = false } }
async function openDetail(row: SubmittedWorkpaper) { if (!account.value) return; try { const loaded = await reviewService.getDetail(row.submissionId, account.value); detail.value = { ...loaded, reviewStatus: row.reviewStatus, reviewerName: row.reviewerName, canReview: row.canReview, canWithdraw: row.canWithdraw }; drawerVisible.value = true } catch (err: any) { ElMessage.error(err?.response?.data?.detail || 'FMSS复核详情加载失败') } }
async function decide(decision: 'approved' | 'rejected', comment: string) { if (!detail.value || !account.value || decisionLoading.value) return; decisionLoading.value = true; try { detail.value = await reviewService.decide({ submissionId: detail.value.submissionId, decision, comment, expectedRecordVersion: detail.value.recordVersion, idempotencyKey: crypto.randomUUID() }, account.value); ElMessage.success(decision === 'approved' ? 'FMSS已复核通过' : 'FMSS已退回'); await refresh() } catch (err: any) { ElMessage.error(err?.response?.data?.detail || 'FMSS审核操作失败') } finally { decisionLoading.value = false } }
async function withdraw() { if (!detail.value || decisionLoading.value) return; decisionLoading.value = true; try { await fmssApi.withdraw(detail.value.submissionId); detail.value = { ...detail.value, reviewStatus: 'withdrawn', canReview: false, canWithdraw: false }; ElMessage.success('FMSS申报单已撤回'); await refresh() } catch (err: any) { ElMessage.error(err?.response?.data?.detail || 'FMSS撤回失败') } finally { decisionLoading.value = false } }
onMounted(async () => { await loadSession(); await refresh() })
watch(() => props.periodId, refresh)
</script>

<style scoped>
.pit-review-page { display:grid; gap:16px; }.card-header,.pit-review-filters { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; flex-wrap:wrap; }.card-header p { margin:6px 0 0; color:var(--el-text-color-secondary); font-size:13px; }.pit-review-account { margin-top:12px; color:var(--el-text-color-secondary); font-size:13px; }.pit-review-filters { justify-content:flex-start; align-items:center; }.pit-review-filters .el-select { width:130px; }.pit-review-filters .el-input { width:min(280px,100%); }
</style>
