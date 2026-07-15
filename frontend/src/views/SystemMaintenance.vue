<template>
  <div class="workflow-page">
    <section class="card workflow-card">
      <div class="card-header">
        <div><strong>系统维护</strong><p>版本、存储与备份</p></div>
        <a class="btn btn-outline" :href="systemApi.diagnosticsUrl()" target="_blank"><el-icon><Download /></el-icon>导出诊断包</a>
      </div>
      <div class="card-body">
        <div v-if="info" class="workflow-summary-grid">
          <div><span>程序版本</span><strong>{{ info.app_version }}</strong></div>
          <div><span>规则版本</span><strong>{{ info.ruleset_version }}</strong></div>
          <div><span>数据库版本</span><strong>{{ info.schema_version }}/{{ info.expected_schema_version }}</strong></div>
          <div><span>已用空间</span><strong>{{ formatBytes(info.storage_bytes) }}</strong></div>
          <div><span>可用空间</span><strong>{{ formatBytes(info.free_bytes) }}</strong></div>
        </div>
        <div v-if="info" class="system-paths">
          <div><span>数据目录</span><code>{{ info.data_root }}</code></div>
          <div><span>备份目录</span><code>{{ info.backup_root }}</code></div>
        </div>
      </div>
    </section>

    <section class="card workflow-card">
      <div class="card-header">
        <strong>数据备份</strong>
        <button class="btn btn-primary" :disabled="busy" @click="createBackup">立即备份</button>
      </div>
      <div class="card-body">
        <el-table :data="backups" size="small" style="width:100%" max-height="420">
          <el-table-column prop="file_name" label="备份文件" min-width="320" />
          <el-table-column label="大小" width="120"><template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template></el-table-column>
          <el-table-column label="时间" width="190"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
          <el-table-column label="操作" width="100"><template #default="{ row }"><a class="btn btn-xs btn-ghost" :href="systemApi.backupDownloadUrl(row.file_name)">下载</a></template></el-table-column>
        </el-table>
        <div v-if="!backups.length" class="empty-inline">暂无备份。</div>
      </div>
    </section>

    <section class="card workflow-card">
      <div class="card-header"><strong>恢复备份</strong></div>
      <div class="card-body">
        <div class="upload-item workflow-upload-item" :class="{ 'has-file': restoreFile }">
          <label>备份文件</label>
          <input type="file" accept=".zip" @change="pickRestoreFile" />
          <span class="upload-status" :class="restoreFile ? 'ready' : 'empty'">{{ restoreFile?.name || '请选择备份ZIP' }}</span>
          <button class="btn btn-danger" :disabled="!restoreFile || busy" @click="restoreBackup">恢复</button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { systemApi, type BackupInfo, type SystemInfo } from '../api'

const info = ref<SystemInfo | null>(null)
const backups = ref<BackupInfo[]>([])
const restoreFile = ref<File | null>(null)
const busy = ref(false)

onMounted(loadData)

async function loadData() {
  const [infoResponse, backupResponse] = await Promise.all([systemApi.info(), systemApi.backups()])
  info.value = infoResponse.data
  backups.value = backupResponse.data
}

async function createBackup() {
  busy.value = true
  try {
    await systemApi.createBackup()
    await loadData()
    ElMessage.success('备份已完成')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '备份失败')
  } finally {
    busy.value = false
  }
}

function pickRestoreFile(event: Event) {
  restoreFile.value = (event.target as HTMLInputElement).files?.[0] || null
}

async function restoreBackup() {
  if (!restoreFile.value) return
  await ElMessageBox.confirm('恢复将用备份数据替换当前数据库和业务文件，系统会先自动保存当前数据。', '确认恢复', { type: 'warning' })
  busy.value = true
  try {
    await systemApi.restore(restoreFile.value)
    ElMessage.success('恢复完成，正在重新加载')
    window.setTimeout(() => window.location.reload(), 800)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '恢复失败')
  } finally {
    busy.value = false
  }
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`
  return `${(value / 1024 ** 3).toFixed(1)} GB`
}

function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
</script>

