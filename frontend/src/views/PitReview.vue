<template>
  <div class="pit-review-page">
    <section class="card workflow-card">
      <div class="card-header"><div><strong>个税底稿复核</strong><p>复核内容直接来自 FMSS 固定申报单，不读取本地工作底稿替代。</p></div><div><el-button v-if="!session.connected" type="primary" @click="openLogin">登录 FMSS</el-button><el-button v-else @click="refresh">刷新</el-button></div></div>
      <div class="pit-review-account">FMSS账号：<strong>{{ session.username || '未登录' }}</strong> · 当前所属期：{{ periodLabel || '未选择' }}</div>
    </section>
    <section v-if="session.connected" class="card workflow-card">
      <div class="pit-review-filters"><el-select v-model="filters.stage" clearable placeholder="全部阶段"><el-option label="缴款前" value="pre_payment" /><el-option label="缴款后" value="post_payment" /></el-select><el-select v-model="filters.status" placeholder="待我复核"><el-option label="待我复核" value="pending_review" /></el-select><el-input v-model="filters.keyword" clearable placeholder="申报单、分公司或提交人" /><el-button type="primary" :loading="loading" @click="refresh">查询</el-button></div>
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-table v-else :data="filteredItems" v-loading="loading" border size="small" @row-click="openDetail"><el-table-column prop="submissionId" label="申报单ID" width="100" /><el-table-column prop="platformOrgName" label="FMSS分公司" min-width="140" /><el-table-column prop="taxPeriod" label="所属期" width="110" /><el-table-column label="阶段" width="90"><template #default="{ row }">{{ stageLabel(row.stage) }}</template></el-table-column><el-table-column prop="submitterName" label="提交人" width="110" /><el-table-column prop="submittedAt" label="提交时间" min-width="160" /><el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="primary" @click.stop="openDetail(row)">查看</el-button></template></el-table-column></el-table>
      <el-empty v-if="!loading && !error && !items.length" description="暂无待我复核的FMSS申报单" />
    </section>
    <el-drawer v-model="drawerVisible" size="82%"><template #header><div><strong>FMSS申报单复核</strong><p v-if="detail">{{ detail.platformOrgName }} · {{ detail.taxPeriod }} · {{ stageLabel(detail.stage) }}</p></div></template><template v-if="detail"><el-tabs v-model="activeSheet"><el-tab-pane v-for="sheet in detail.sheets" :key="sheet.sheetCode" :name="sheet.sheetCode" :label="sheet.sheetName"><WorkpaperSheetViewer :sheet="sheet" /></el-tab-pane></el-tabs><el-empty v-if="!detail.sheets.length" description="FMSS未返回可展示的工作表数据" /><ReviewDecisionPanel v-if="detail.reviewStatus === 'pending_review'" :loading="decisionLoading" @decide="decide" /></template></el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import WorkpaperSheetViewer from '../components/pit/WorkpaperSheetViewer.vue'
import ReviewDecisionPanel from '../components/pit/ReviewDecisionPanel.vue'
import { fmssApi } from '../api'
import { stageLabel } from '../features/pit/stageConfig'
import type { PlatformAccount, ReviewDetail, SubmittedWorkpaper } from '../features/pit/contracts'
import { reviewService } from '../services/pit/reviewService'

const props = defineProps<{ periodId?: number | null; periodLabel?: string }>()
const session = reactive({ connected: false, username: null as string | null })
const filters = reactive<{ stage?: 'pre_payment' | 'post_payment'; status: 'pending_review'; keyword: string }>({ status: 'pending_review', keyword: '' })
const items = ref<SubmittedWorkpaper[]>([]); const loading = ref(false); const decisionLoading = ref(false); const error = ref(''); const drawerVisible = ref(false); const detail = ref<ReviewDetail | null>(null); const activeSheet = ref('')
const account = computed<PlatformAccount | null>(() => session.username ? { id: session.username, displayName: session.username, role: 'FMSS用户' } : null)
const filteredItems = computed(() => items.value.filter((item) => (!filters.stage || item.stage === filters.stage) && (!filters.keyword || JSON.stringify(item).includes(filters.keyword))))
async function loadSession() { try { const { data } = await fmssApi.session(); session.connected = data.connected; session.username = data.username } catch { session.connected = false; session.username = null } }
async function openLogin() { try { const bridge = (window as any).pywebview?.api; if (bridge?.open_fmss_login) await bridge.open_fmss_login(); else await fmssApi.openLogin(); ElMessage.info('已打开FMSS登录页；请手工完成登录后刷新。') } catch { ElMessage.error('FMSS登录页无法打开') } }
async function refresh() { if (!props.periodId || !account.value) return; loading.value = true; error.value = ''; try { const result = await reviewService.list({ taxPeriod: String(props.periodId), page: 1, pageSize: 100 }, account.value); items.value = result.items } catch (err: any) { error.value = err?.response?.data?.detail || 'FMSS复核列表加载失败' } finally { loading.value = false } }
async function openDetail(row: SubmittedWorkpaper) { if (!account.value) return; try { detail.value = await reviewService.getDetail(row.submissionId, account.value); activeSheet.value = detail.value.sheets[0]?.sheetCode || ''; drawerVisible.value = true } catch (err: any) { ElMessage.error(err?.response?.data?.detail || 'FMSS复核详情加载失败') } }
async function decide(decision: 'approved' | 'rejected', comment: string) { if (!detail.value || !account.value || decisionLoading.value) return; decisionLoading.value = true; try { detail.value = await reviewService.decide({ submissionId: detail.value.submissionId, decision, comment, expectedRecordVersion: detail.value.recordVersion, idempotencyKey: crypto.randomUUID() }, account.value); ElMessage.success(decision === 'approved' ? 'FMSS已复核通过' : 'FMSS已退回'); await refresh() } catch (err: any) { ElMessage.error(err?.response?.data?.detail || 'FMSS审核操作失败') } finally { decisionLoading.value = false } }
onMounted(async () => { await loadSession(); await refresh() })
watch(() => props.periodId, refresh)
</script>

<style scoped>
.pit-review-page { display:grid; gap:16px; }.card-header,.pit-review-filters { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; flex-wrap:wrap; }.card-header p { margin:6px 0 0; color:var(--el-text-color-secondary); font-size:13px; }.pit-review-account { margin-top:12px; color:var(--el-text-color-secondary); font-size:13px; }.pit-review-filters { justify-content:flex-start; align-items:center; }.pit-review-filters .el-select { width:130px; }.pit-review-filters .el-input { width:min(280px,100%); }
</style>
