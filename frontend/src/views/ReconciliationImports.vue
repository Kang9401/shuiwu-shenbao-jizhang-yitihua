<template>
  <div class="workflow-page">
    <section v-if="importType === 'bank_statement'" class="card workflow-card">
      <div class="card-header"><div><strong>自动获取银行流水</strong><p>使用独立浏览器登录态查询，获取成功后自动进入银行流水导入批次。</p></div><span class="tag tag-info">{{ fetchStatus.message || '未启动' }}</span></div>
      <div class="card-body bank-fetch-grid">
        <label><span>银行账号</span><textarea v-model="accounts" rows="4" placeholder="每行一个账号" /></label>
        <label><span>开始日期</span><input v-model="startDate" type="date" /></label>
        <label><span>结束日期</span><input v-model="endDate" type="date" /></label>
        <div class="action-bar"><el-button @click="openBankLogin">打开登录页</el-button><el-button type="primary" :disabled="!periodId || !accounts.trim() || fetchRunning" @click="startBankFetch">自动获取</el-button><el-button type="danger" :disabled="!fetchRunning" @click="stopBankFetch">停止</el-button></div>
      </div>
    </section>
    <section class="card workflow-card">
      <div class="card-header">
        <div>
          <strong>核对数据导入</strong>
          <p>导入银行流水、申报结果和账务数据，先结构化入库，供后续核对底稿使用。</p>
        </div>
        <span class="tag tag-info">{{ importTypeLabel }}</span>
      </div>
      <div class="card-body">
        <div class="master-controls">
          <label>
            <span>导入类型</span>
            <select v-model="importType" class="period-native-select">
              <option value="bank_statement">银行流水</option>
              <option value="declaration_result">申报结果</option>
              <option value="accounting_ledger">账务数据</option>
              <option value="balance_sheet">余额表</option>
            </select>
          </label>
        </div>

        <div class="upload-item workflow-upload-item" :class="{ 'has-file': selectedFile }">
          <label>{{ importTypeLabel }}</label>
          <input type="file" accept=".xls,.xlsx,.csv" @change="onFilePicked" />
          <span class="upload-status" :class="selectedFile ? 'ready' : 'empty'">
            {{ selectedFile?.name || '未选择' }}
          </span>
          <button class="btn btn-xs btn-ghost" :disabled="!selectedFile" @click="selectedFile = null">清除</button>
        </div>

        <div v-if="errorText" class="personnel-error-panel">
          <strong>导入失败</strong>
          <p>{{ errorText }}</p>
        </div>

        <div class="action-bar">
          <div class="action-hint">
            <span>本轮只做标准导入和归档，不自动生成三方核对差异。</span>
          </div>
          <button class="btn btn-primary btn-lg" :disabled="!canImport || loading" @click="importFile">
            <span v-if="loading" class="spinner"></span>
            <el-icon v-else><Upload /></el-icon>
            导入
          </button>
        </div>
      </div>
    </section>

    <section class="card workflow-card">
      <div class="card-header">
        <strong>导入批次</strong>
        <button class="btn btn-sm btn-outline" @click="loadBatches">刷新</button>
      </div>
      <div class="card-body">
        <div v-if="!batches.length" class="empty-inline">当前月份尚未导入该类数据。</div>
        <div v-else class="download-grid">
          <a v-for="batch in batches" :key="batch.id" class="download-item" :href="batch.download_url" target="_blank">
            <el-icon><Download /></el-icon>
            <span class="download-text">
              <strong>{{ batch.original_name }}</strong>
              <small>{{ typeLabel(batch.import_type) }} · {{ batch.row_count }} 行 · {{ batch.created_at }}</small>
            </span>
          </a>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Upload } from '@element-plus/icons-vue'
import {
  bankFetchApi,
  reconciliationImportApi,
  type ReconciliationImportBatch,
  type ReconciliationImportType,
} from '../api'

const props = defineProps<{ periodId: number | null }>()

const importType = ref<ReconciliationImportType>('bank_statement')
const selectedFile = ref<File | null>(null)
const batches = ref<ReconciliationImportBatch[]>([])
const loading = ref(false)
const errorText = ref('')
const accounts = ref('')
const today = new Date().toISOString().slice(0, 10)
const startDate = ref(`${today.slice(0, 7)}-01`)
const endDate = ref(today)
const fetchStatus = ref({ status: 'idle', message: '', batch_id: null as number | null })
let fetchTimer: number | undefined
const fetchRunning = computed(() => ['starting', 'running', 'waiting-login', 'importing'].includes(fetchStatus.value.status))

const importTypeLabel = computed(() => typeLabel(importType.value))
const canImport = computed(() => !!props.periodId && !!selectedFile.value)

onMounted(() => { loadBatches(); pollBankFetch(); fetchTimer = window.setInterval(pollBankFetch, 1500) })
onBeforeUnmount(() => window.clearInterval(fetchTimer))
watch(() => props.periodId, loadBatches)
watch(importType, loadBatches)

function typeLabel(type: ReconciliationImportType) {
  return {
    bank_statement: '银行流水',
    declaration_result: '申报结果',
    accounting_ledger: '账务数据',
    balance_sheet: '余额表',
  }[type]
}

function onFilePicked(event: Event) {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] || null
  errorText.value = ''
}

function formatError(error: any) {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) return detail.map((item) => item.message || JSON.stringify(item)).join('；')
  return detail || '导入失败，请检查文件格式'
}

async function loadBatches() {
  if (!props.periodId) return
  const { data } = await reconciliationImportApi.list(props.periodId, importType.value)
  batches.value = data
}

async function importFile() {
  if (!props.periodId || !selectedFile.value) return
  loading.value = true
  errorText.value = ''
  try {
    await reconciliationImportApi.importFile(selectedFile.value, props.periodId, importType.value)
    selectedFile.value = null
    ElMessage.success('导入完成')
    await loadBatches()
  } catch (error: any) {
    errorText.value = formatError(error)
    ElMessage.error('导入失败')
  } finally {
    loading.value = false
  }
}

async function pollBankFetch() { try { const { data } = await bankFetchApi.status(); const previous = fetchStatus.value.status; fetchStatus.value = data; if (previous !== 'succeeded' && data.status === 'succeeded') { ElMessage.success('银行流水已自动获取并导入'); await loadBatches() } } catch {} }
async function openBankLogin() { try { await bankFetchApi.openLogin(); ElMessage.info('请在打开的银行页面完成登录') } catch (error: any) { ElMessage.error(formatError(error)) } }
async function startBankFetch() { if (!props.periodId) return; try { fetchStatus.value = (await bankFetchApi.start({ period_id: props.periodId, accounts: accounts.value, start_date: startDate.value, end_date: endDate.value })).data } catch (error: any) { ElMessage.error(formatError(error)) } }
async function stopBankFetch() { fetchStatus.value = (await bankFetchApi.stop()).data }
</script>

<style scoped>
.bank-fetch-grid{display:grid;grid-template-columns:minmax(260px,1fr) 180px 180px;gap:12px;align-items:end}.bank-fetch-grid label{display:flex;flex-direction:column;gap:6px}.bank-fetch-grid textarea,.bank-fetch-grid input{box-sizing:border-box;width:100%;padding:8px;border:1px solid #d0d5dd;border-radius:4px;font:inherit}.bank-fetch-grid .action-bar{grid-column:1/-1}@media(max-width:800px){.bank-fetch-grid{grid-template-columns:1fr}}
</style>
