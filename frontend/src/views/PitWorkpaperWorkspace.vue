<template>
  <div class="pit-preview-page">
    <el-alert v-if="isPreview" title="开发预览 / 模拟数据" type="warning" :closable="false" show-icon description="当前状态流转、重算与提交均为开发 Mock，不调用旧个税重算接口，也不代表服务端已完成双阶段持久化。" />
    <el-alert v-else title="尚未接入真实分阶段工作底稿服务" type="info" :closable="false" show-icon />
    <section class="card">
      <div class="card-header"><div><strong>个税核对底稿</strong><p>缴款前、缴款后是独立工作区，各自管理修订、提交版本与复核状态。</p></div><StageTabs v-model="stage" /></div>
      <div class="pit-preview-context"><span>本地机构：{{ companyName }}</span><span>所属期间：{{ periodLabel }}</span><span>当前阶段：{{ stageLabel(stage) }}</span><span>本地修订：{{ preview ? `r${preview.draftRevision}` : '—' }}</span></div>
      <div class="pit-preview-actions"><el-button type="primary" :loading="loading" @click="loadPreview">刷新</el-button><el-button :loading="recalculating" :disabled="!preview?.isEditable" @click="recalculate">重算</el-button><el-button :loading="editing" :disabled="!preview?.isEditable" @click="editDraft">修改数据</el-button><el-button type="success" :loading="submitting" :disabled="!canSubmit" @click="submit">提交</el-button></div>
      <el-alert v-if="preview?.calculationStatus === 'missing_sources'" type="warning" :closable="false" show-icon :title="`当前阶段仍处于数据准备：缺少${preview.missingSources.join('、')}`" />
      <div v-if="preview" class="pit-preview-status"><el-tag :type="lifecycleTagType(preview.lifecycleStatus)">当前状态：{{ lifecycleLabel(preview.lifecycleStatus) }}</el-tag><el-tag type="info">提交版本：{{ preview.submissionVersion ? `v${preview.submissionVersion}` : '未提交' }}</el-tag><el-tag :type="reviewTagType(preview.reviewStatus)">复核：{{ reviewLabel(preview.reviewStatus) }}</el-tag><span class="pit-preview-permission">{{ preview.isEditable ? '当前状态允许修改数据。' : '当前状态已锁定，不允许修改或重算。' }}</span></div>
      <el-empty v-else-if="!loading" description="请选择所属期间后点击刷新" />
    </section>
    <section v-if="preview" class="card"><div class="card-header"><div><strong>阶段工作表</strong><p>结果表与来源材料分区；来源材料为结构化只读预览。</p></div></div><el-tabs v-model="activeSheet"><el-tab-pane v-for="sheet in preview.sheets" :key="sheet.sheetCode" :name="sheet.sheetCode"><template #label><span>{{ sheet.group === 'result' ? '核对结果 · ' : '来源材料 · ' }}{{ sheet.sheetName }}</span></template><WorkpaperSheetViewer :sheet="sheet" /></el-tab-pane></el-tabs></section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import StageTabs from '../components/pit/StageTabs.vue'
import WorkpaperSheetViewer from '../components/pit/WorkpaperSheetViewer.vue'
import { stageLabel } from '../features/pit/stageConfig'
import type { LocalWorkpaperPreview, PaymentStage, ReviewStatus, WorkpaperLifecycleStatus } from '../features/pit/contracts'
import { PitServiceNotIntegratedError } from '../features/pit/contracts'
import { workpaperService } from '../services/pit/workpaperService'

const props = defineProps<{ companyId: number | null; companyName: string; periodId: number | null; periodLabel: string; taxPeriod: string }>()
const stage = ref<PaymentStage>('pre_payment')
const preview = ref<LocalWorkpaperPreview | null>(null)
const activeSheet = ref('pre_summary_tax')
const loading = ref(false); const recalculating = ref(false); const editing = ref(false); const submitting = ref(false)
const requestEpoch = ref(0)
const isPreview = import.meta.env.DEV
const context = computed(() => props.companyId && props.periodId ? { localCompanyId: props.companyId, localPeriodId: props.periodId, companyName: props.companyName, taxPeriod: props.taxPeriod, stage: stage.value } : null)
function reviewLabel(status: ReviewStatus | null) { return status === 'approved' ? '模拟已复核' : status === 'rejected' ? '模拟已退回' : status === 'pending_review' ? '模拟待复核' : '未提交' }
function reviewTagType(status: ReviewStatus | null) { return status === 'approved' ? 'success' : status === 'rejected' ? 'danger' : status === 'pending_review' ? 'warning' : 'info' }
function lifecycleLabel(status: WorkpaperLifecycleStatus) { return status === 'data_preparation' ? '数据准备' : status === 'pending_submission' ? '待提交' : status === 'submitted' ? '已提交' : status === 'rejected' ? '已退回' : '已复核' }
function lifecycleTagType(status: WorkpaperLifecycleStatus) { return status === 'data_preparation' ? 'info' : status === 'pending_submission' ? 'warning' : status === 'submitted' ? 'primary' : status === 'rejected' ? 'danger' : 'success' }
const canSubmit = computed(() => preview.value?.lifecycleStatus === 'pending_submission' || preview.value?.lifecycleStatus === 'rejected')
function reset() { requestEpoch.value += 1; preview.value = null; activeSheet.value = stage.value === 'pre_payment' ? 'pre_summary_tax' : 'post_payment_check' }
function showError(error: unknown) { ElMessage.error(error instanceof PitServiceNotIntegratedError ? error.message : '开发预览加载失败') }
async function loadPreview() { if (!context.value) return; const currentEpoch = requestEpoch.value; loading.value = true; try { const next = await workpaperService.getPreview(context.value); if (currentEpoch === requestEpoch.value && next.context.stage === stage.value) { preview.value = next; activeSheet.value = next.sheets[0]?.sheetCode || '' } } catch (error) { if ((error as Error).name !== 'AbortError') showError(error) } finally { if (currentEpoch === requestEpoch.value) loading.value = false } }
async function recalculate() { if (!context.value) return; recalculating.value = true; const currentEpoch = requestEpoch.value; try { const next = await workpaperService.recalculate(context.value); if (currentEpoch === requestEpoch.value) { preview.value = next; ElMessage.success('模拟重算完成，未调用正式计算接口') } } catch (error) { showError(error) } finally { recalculating.value = false } }
async function editDraft() { if (!context.value) return; editing.value = true; const currentEpoch = requestEpoch.value; try { const next = await workpaperService.editDraft(context.value); if (currentEpoch === requestEpoch.value) { preview.value = next; ElMessage.success('模拟修改已记录为本阶段待提交修订') } } catch (error) { showError(error) } finally { editing.value = false } }
async function submit() { if (!context.value) return; submitting.value = true; const currentEpoch = requestEpoch.value; try { const next = await workpaperService.submit(context.value); if (currentEpoch === requestEpoch.value) { preview.value = next; ElMessage.success('模拟提交已发送状态 submitted，不代表服务端正式提交成功') } } catch (error) { showError(error) } finally { submitting.value = false } }
watch([stage, () => props.companyId, () => props.periodId], reset)
</script>

<style scoped>
.pit-preview-page { display:grid; gap:16px; }.pit-preview-context,.pit-preview-status,.pit-preview-actions { display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center; }.pit-preview-context { margin:14px 0; color:var(--el-text-color-secondary); font-size:13px; }.pit-preview-actions { margin-bottom:14px; }.pit-preview-status { margin-top:14px; }.pit-preview-permission { color:var(--el-text-color-secondary); font-size:13px; }
</style>
