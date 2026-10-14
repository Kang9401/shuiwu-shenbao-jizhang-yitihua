<template>
  <section class="card workflow-card fmss-workpaper">
    <div class="card-header">
      <div>
        <strong>个税核对底稿</strong>
        <p>提交版本，只读展示。</p>
      </div>
      <div class="fmss-workpaper__meta">
        <el-tag effect="plain">{{ stageLabel(sheetStage) }}</el-tag>
        <el-tag :type="statusType" effect="light">{{ statusLabel }}</el-tag>
      </div>
    </div>
    <div class="card-body">
      <el-tabs v-model="activeSheet">
        <el-tab-pane v-for="sheet in sheets" :key="sheet.sheetCode" :name="sheet.sheetCode" :label="sheet.sheetName">
          <WorkpaperSheetViewer :sheet="sheet" />
        </el-tab-pane>
      </el-tabs>
      <el-empty v-if="!sheets.length" description="未返回可展示的工作表数据" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import WorkpaperSheetViewer from './WorkpaperSheetViewer.vue'
import { stageLabel } from '../../features/pit/stageConfig'
import type { PaymentStage, WorkpaperSheet } from '../../features/pit/contracts'

const props = defineProps<{ sheets: WorkpaperSheet[]; stage: PaymentStage; status: string }>()
const activeSheet = ref('')
const sheetStage = computed(() => props.stage)
const statusLabel = computed(() => ({ REVIEWING: '审核中', APPROVED: '已通过', RETURNED: '已退回', DRAFT: '草稿' }[props.status] || props.status))
const statusType = computed(() => ({ REVIEWING: 'warning', APPROVED: 'success', RETURNED: 'danger' }[props.status] || 'info') as 'warning' | 'success' | 'danger' | 'info')

watch(() => props.sheets, (sheets) => {
  activeSheet.value = sheets[0]?.sheetCode || ''
}, { immediate: true })
</script>

<style scoped>
.fmss-workpaper { margin-top: 12px; }.card-header { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }.card-header p { margin:6px 0 0; color:var(--el-text-color-secondary); font-size:13px; }.fmss-workpaper__meta { display:flex; gap:8px; flex-wrap:wrap; }
</style>
