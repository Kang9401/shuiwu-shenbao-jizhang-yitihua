<template>
  <section class="card workflow-card">
    <div class="card-header">
      <div>
        <strong>运行记录</strong>
        <p>{{ periodLabel }}</p>
      </div>
      <button class="btn btn-outline" :disabled="loading" @click="loadJobs">刷新</button>
    </div>
    <div class="card-body">
      <el-table :data="jobs" size="small" style="width:100%" max-height="620">
        <el-table-column prop="id" label="任务" width="80" />
        <el-table-column label="流程" min-width="180"><template #default="{ row }">{{ workflowName(row.workflow_code) }}</template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="{ row }">{{ row.operation === 'reconcile' ? '核对' : '生成' }}</template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{ row }"><span class="tag" :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span></template></el-table-column>
        <el-table-column prop="app_version" label="程序版本" width="110" />
        <el-table-column prop="ruleset_version" label="规则版本" width="110" />
        <el-table-column label="完成时间" min-width="170"><template #default="{ row }">{{ formatDate(row.finished_at || row.created_at) }}</template></el-table-column>
      </el-table>
      <div v-if="!loading && !jobs.length" class="empty-inline">当前所属期间暂无运行记录。</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { workflowApi, type Job, type Workflow } from '../api'

const props = defineProps<{ periodId: number | null; periodLabel: string }>()
const jobs = ref<Job[]>([])
const workflows = ref<Workflow[]>([])
const loading = ref(false)

onMounted(async () => {
  const { data } = await workflowApi.list()
  workflows.value = data
  await loadJobs()
})

watch(() => props.periodId, () => void loadJobs())

async function loadJobs() {
  if (!props.periodId) return
  loading.value = true
  try {
    const { data } = await workflowApi.listJobs(props.periodId)
    jobs.value = data
  } catch {
    ElMessage.error('运行记录加载失败')
  } finally {
    loading.value = false
  }
}

function workflowName(code: string) {
  return workflows.value.find((item) => item.code === code)?.name || code
}

function statusLabel(status: string) {
  return ({ success: '完成', needs_review: '需复核', failed: '失败', running: '运行中', pending: '等待中' } as Record<string, string>)[status] || status
}

function statusClass(status: string) {
  if (status === 'success') return 'tag-success'
  if (status === 'needs_review') return 'tag-warning'
  if (status === 'failed') return 'tag-danger'
  return 'tag-info'
}

function formatDate(value: string) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
}
</script>

