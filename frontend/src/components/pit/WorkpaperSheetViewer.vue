<template>
  <div class="sheet-viewer">
    <div class="sheet-viewer__filters">
      <el-input v-model="keyword" placeholder="筛选当前工作表" clearable />
      <el-checkbox v-model="differencesOnly">仅看差异</el-checkbox>
    </div>
    <el-table :data="filteredRows" border size="small" max-height="420" class="sheet-viewer__table">
      <el-table-column v-for="column in sheet.columns" :key="column.code" :prop="column.code" :label="column.label" :min-width="column.type === 'text' ? 170 : 140" show-overflow-tooltip>
        <template #default="{ row }">
          <span :class="column.type === 'money' && isDifference(row[column.code]) ? 'sheet-viewer__difference' : ''">{{ formatValue(row[column.code], column.type) }}</span>
        </template>
      </el-table-column>
    </el-table>
    <p v-if="!filteredRows.length" class="sheet-viewer__empty">没有符合当前筛选条件的数据。</p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { WorkpaperSheet } from '../../features/pit/contracts'

const props = defineProps<{ sheet: WorkpaperSheet }>()
const keyword = ref('')
const differencesOnly = ref(false)
function isDifference(value: unknown) { return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) && Math.abs(Number(value)) > 0.01 }
function formatValue(value: unknown, type: string) {
  if (value === null || value === undefined || value === '') return '—'
  if (type === 'money') return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return String(value)
}
const filteredRows = computed(() => props.sheet.rows.filter((row) => {
  if (keyword.value && !Object.values(row).some((value) => String(value ?? '').includes(keyword.value))) return false
  return !differencesOnly.value || props.sheet.columns.some((column) => column.type === 'money' && isDifference(row[column.code]))
}))
</script>

<style scoped>
.sheet-viewer { display: grid; gap: 12px; }.sheet-viewer__filters { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }.sheet-viewer__filters .el-input { width:260px; }.sheet-viewer__difference { color:var(--el-color-danger); font-weight:600; }.sheet-viewer__empty { margin:0; color:var(--el-text-color-secondary); font-size:13px; }
</style>
