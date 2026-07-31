<template>
  <div class="workflow-page">
    <OrganizationMappings />

    <section class="card workflow-card">
      <div class="card-header">
        <div>
          <strong>人员主数据初始化/维护</strong>
          <p>按月份维护员工和经纪人人员主数据，支持按月、机构、分公司导入和导出。</p>
        </div>
        <span class="tag tag-info">{{ personTypeLabel }}</span>
      </div>

      <div class="card-body">
        <div class="master-controls">
          <label>
            <span>人员类型</span>
            <select v-model="personType" class="period-native-select">
              <option value="employee">员工</option>
              <option value="broker">经纪人</option>
            </select>
          </label>
          <label>
            <span>导入口径</span>
            <select v-model="scopeType" class="period-native-select">
              <option value="month">月度全量</option>
              <option value="org">按机构</option>
              <option value="branch">按分公司</option>
            </select>
          </label>
          <label v-if="scopeType !== 'month'">
            <span>{{ scopeType === 'org' ? '机构代码' : '分公司代码' }}</span>
            <input v-model.trim="scopeCode" class="text-input" placeholder="请输入代码" />
          </label>
        </div>

        <div class="upload-item workflow-upload-item" :class="{ 'has-file': selectedFile }">
          <label>人员信息表</label>
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
            <span>工资薪金和年终奖使用员工主数据；经纪人申报使用经纪人主数据。</span>
          </div>
          <button class="btn btn-primary btn-lg" :disabled="!canImport || loading" @click="importFile">
            <span v-if="loading" class="spinner"></span>
            <el-icon v-else><Upload /></el-icon>
            导入/覆盖当前版本
          </button>
        </div>
      </div>
    </section>

    <section class="card workflow-card">
      <div class="card-header">
        <strong>当前版本</strong>
        <button class="btn btn-sm btn-outline" @click="loadData">刷新</button>
      </div>
      <div class="card-body">
        <div v-if="!artifacts.length" class="empty-inline">当前月份尚未初始化该类人员主数据。</div>
        <div v-else class="download-grid">
          <a v-for="item in artifacts" :key="item.id" class="download-item" :href="item.download_url" target="_blank">
            <el-icon><Download /></el-icon>
            <span class="download-text">
              <strong>{{ displayFileName(item) }}</strong>
              <small>{{ scopeLabel(item.scope_type, item.scope_code) }} · {{ item.row_count }} 行</small>
            </span>
          </a>
        </div>
      </div>
    </section>

    <section class="card workflow-card">
      <div class="card-header">
        <strong>导入历史</strong>
      </div>
      <div class="card-body">
        <el-table :data="batches" size="small" style="width: 100%">
          <el-table-column prop="created_at" label="时间" min-width="170" />
          <el-table-column prop="original_name" label="文件" min-width="220" />
          <el-table-column label="范围" min-width="130">
            <template #default="{ row }">{{ scopeLabel(row.scope_type, row.scope_code) }}</template>
          </el-table-column>
          <el-table-column prop="row_count" label="行数" width="90" />
        </el-table>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Upload } from '@element-plus/icons-vue'
import OrganizationMappings from './OrganizationMappings.vue'
import {
  personnelMasterApi,
  type PersonType,
  type PersonnelMasterArtifact,
  type PersonnelMasterBatch,
  type PersonnelScopeType,
} from '../api'

const props = defineProps<{ periodId: number | null }>()

const personType = ref<PersonType>('employee')
const scopeType = ref<PersonnelScopeType>('month')
const scopeCode = ref('')
const selectedFile = ref<File | null>(null)
const artifacts = ref<PersonnelMasterArtifact[]>([])
const batches = ref<PersonnelMasterBatch[]>([])
const loading = ref(false)
const errorText = ref('')

const personTypeLabel = computed(() => ({
  employee: '员工',
  broker: '经纪人',
}[personType.value]))

const canImport = computed(() =>
  !!props.periodId && !!selectedFile.value && (scopeType.value === 'month' || !!scopeCode.value)
)

onMounted(loadData)
watch(() => props.periodId, loadData)
watch(personType, loadData)

function onFilePicked(event: Event) {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] || null
  errorText.value = ''
}

function scopeLabel(type: PersonnelScopeType, code: string) {
  if (type === 'month') return '月度全量'
  if (type === 'org') return `机构 ${code}`
  return `分公司 ${code}`
}

function displayFileName(item: PersonnelMasterArtifact) {
  if (item.person_type !== 'employee' || item.scope_type !== 'month') return item.file_name
  const match = item.file_name.match(/^(\d{4})(\d{2})_employee_month_all\.xlsx$/i)
  return match ? `人员信息表(${match[1]}年${match[2]}月).xlsx` : item.file_name
}

function formatError(error: any) {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) return detail.map((item) => item.message || JSON.stringify(item)).join('；')
  return detail || '导入失败，请检查文件格式'
}

async function loadData() {
  if (!props.periodId) return
  const [{ data: status }, { data: history }] = await Promise.all([
    personnelMasterApi.status(props.periodId, personType.value),
    personnelMasterApi.batches(props.periodId, personType.value),
  ])
  artifacts.value = status
  batches.value = history
}

async function importFile() {
  if (!props.periodId || !selectedFile.value) return
  loading.value = true
  errorText.value = ''
  try {
    await personnelMasterApi.importFile(selectedFile.value, props.periodId, personType.value, scopeType.value, scopeCode.value)
    ElMessage.success('人员主数据已保存')
    selectedFile.value = null
    await loadData()
  } catch (error: any) {
    errorText.value = formatError(error)
    ElMessage.error('人员主数据导入失败')
  } finally {
    loading.value = false
  }
}
</script>
