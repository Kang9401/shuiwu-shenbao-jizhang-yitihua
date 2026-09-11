<template>
  <div class="workflow-page">
    <section class="card workflow-card">
      <div class="card-header">
        <div>
          <strong>{{ workflow.name }}</strong>
          <p>{{ workflow.description }}</p>
        </div>
        <span class="tag tag-info">{{ workflow.domain }}</span>
      </div>

      <div class="card-body">
        <div v-if="!isRestrictedStockInterest || restrictedStep === 1" class="workflow-grid">
          <div v-if="usesSharedStaffInfo" class="shared-staff-note">
            <strong>人员主数据已共享</strong>
            <p>本流程自动使用当前所属期间维护的人员主数据；需要调整时请到“人员主数据”页面更新。</p>
          </div>
          <div
            v-for="role in displayRoleEntries"
            :key="role"
            class="upload-item workflow-upload-item"
            :class="{ 'has-file': selectedFiles[role] }"
          >
            <label>{{ roleLabel(role) }}</label>
            <input type="file" accept=".xls,.xlsx,.csv" :multiple="(isBroker && role === 'broker_income') || (isAnnualBonus && role === 'bonus_sheet')" @change="onFilePicked(role, $event)" />
            <span class="upload-status" :class="selectedFiles[role] ? 'ready' : 'empty'">
              {{ roleFileSummary(role) }}
            </span>
            <button class="btn btn-xs btn-ghost" :disabled="!selectedFiles[role]" @click="clearFile(role)">清除</button>
          </div>
        </div>

        <input
          v-if="isRestrictedStockInterest && restrictedStep === 1"
          ref="folderInput"
          type="file"
          webkitdirectory
          multiple
          style="display:none"
          @change="onFolderPicked"
        />

        <div v-if="isRestrictedStockInterest" class="workflow-stepbar">
          <span class="tag" :class="restrictedStep >= 1 ? 'tag-success' : 'tag-info'">1 上传并生成</span>
          <span class="tag" :class="restrictedStep >= 2 ? 'tag-success' : 'tag-info'">2 核对或跳过</span>
          <span class="tag" :class="restrictedStep >= 3 ? 'tag-success' : 'tag-info'">3 批量下载</span>
        </div>

        <div v-if="isPartTime" class="workflow-stepbar">
          <span class="tag" :class="partTimeStep >= 1 ? 'tag-success' : 'tag-info'">1 工资单核对</span>
          <span class="tag" :class="partTimeStep >= 2 ? 'tag-success' : 'tag-info'">2 上传变更并生成</span>
        </div>

        <div v-if="isRestrictedStockInterest && restrictedStep === 2" class="workflow-grid">
          <div class="upload-item workflow-upload-item" :class="{ 'has-file': selectedFiles.balance_sheet }">
            <label>{{ roleLabel('balance_sheet') }}</label>
            <input type="file" accept=".xls,.xlsx,.csv" @change="onFilePicked('balance_sheet', $event)" />
            <span class="upload-status" :class="selectedFiles.balance_sheet ? 'ready' : 'empty'">
              {{ selectedFiles.balance_sheet?.name || '可选' }}
            </span>
            <button class="btn btn-xs btn-ghost" :disabled="!selectedFiles.balance_sheet" @click="clearFile('balance_sheet')">清除</button>
          </div>
        </div>

        <div class="action-bar">
          <div class="action-hint">
            <span v-if="isRestrictedStockInterest">{{ restrictedActionHint }}</span>
            <span v-else-if="isPartTime">{{ partTimeStep === 1 ? '上传工资单后执行人员核对。' : '首轮工资单已复用，请上传人员信息变更表后生成申报文件。' }}</span>
            <span v-else-if="missingRequired.length">缺少：{{ missingRequired.map(roleLabel).join('、') }}</span>
            <span v-else>文件已就绪，可以运行迁移后的处理流程。</span>
          </div>
          <button
            v-if="isRestrictedStockInterest && restrictedStep === 1"
            class="btn btn-outline btn-lg"
            :disabled="running"
            @click="openFolderPicker"
          >
            选择文件夹
          </button>
          <button v-if="isRestrictedStockInterest && restrictedStep === 1" class="btn btn-primary btn-lg" :disabled="running || !hasRestrictedSource" @click="runRestrictedGeneration">
            <span v-if="running" class="spinner"></span>
            <el-icon v-else><VideoPlay /></el-icon>
            运行并生成申报
          </button>
          <button
            v-if="isRestrictedStockInterest && restrictedStep === 2"
            class="btn btn-outline btn-lg"
            :disabled="running"
            @click="returnToRestrictedUpload"
          >
            上一步
          </button>
          <button
            v-if="isRestrictedStockInterest && restrictedStep === 3"
            class="btn btn-primary btn-lg"
            :disabled="running"
            @click="returnToRestrictedReconciliation"
          >
            上一步
          </button>
          <button
            v-if="isRestrictedStockInterest && restrictedStep === 3"
            class="btn btn-outline btn-lg"
            :disabled="!generationJob"
            @click="batchDownloadRestricted"
          >
            <el-icon><Download /></el-icon>
            批量下载
          </button>
          <button v-if="isRestrictedStockInterest && restrictedStep === 2" class="btn btn-primary btn-lg" :disabled="running" @click="runRestrictedWorkflow('reconcile')">
            <span v-if="running" class="spinner"></span>
            <el-icon v-else><VideoPlay /></el-icon>
            核对余额表
          </button>
          <button v-if="isRestrictedStockInterest && restrictedStep === 2" class="btn btn-outline btn-lg" :disabled="running" @click="skipReconciliation">
            跳过核对
          </button>
          <a v-if="isIntern" class="btn btn-outline btn-lg" :href="workflowApi.internTemplateUrl()" target="_blank">
            <el-icon><Download /></el-icon>
            下载导入模板
          </a>
          <a v-if="isPartTime" class="btn btn-outline btn-lg" :href="workflowApi.partTimeTemplateUrl()" target="_blank">
            <el-icon><Download /></el-icon>
            下载导入模板
          </a>
          <button v-if="!isRestrictedStockInterest && !isAutoGenerateWorkflow && !isPartTime" class="btn btn-primary btn-lg" :disabled="running || missingRequired.length > 0" @click="runWorkflow()">
            <span v-if="running" class="spinner"></span>
            <el-icon v-else><VideoPlay /></el-icon>
            运行
          </button>
          <button v-if="isPartTime && partTimeStep === 1" class="btn btn-primary btn-lg" :disabled="running || !selectedFiles.payroll" @click="runPartTimeInitial">
            <span v-if="running" class="spinner"></span><el-icon v-else><VideoPlay /></el-icon>执行工资单核对
          </button>
          <button v-if="isPartTime && partTimeStep === 2" class="btn btn-outline btn-lg" :disabled="running" @click="partTimeStep = 1">上一步</button>
          <button v-if="isPartTime && partTimeStep === 2" class="btn btn-primary btn-lg" :disabled="running || !selectedFiles.personnel_changes" @click="runPartTimeRecheck">
            <span v-if="running" class="spinner"></span><el-icon v-else><VideoPlay /></el-icon>重新执行并生成申报
          </button>
        </div>
      </div>
    </section>

    <section v-if="job" class="card workflow-card">
      <div class="card-header">
        <strong>运行结果</strong>
        <span class="tag" :class="jobTagClass">{{ jobStatusLabel }}</span>
      </div>
      <div class="card-body">
        <template v-if="isRestrictedStockInterest">
          <div v-if="job.error_message" class="personnel-error-panel">
            <strong>处理失败</strong>
            <p>{{ job.error_message }}</p>
          </div>

          <div v-if="generationJob" class="restricted-summary-panel">
            <div class="workflow-summary-grid">
              <div><span>生成文件</span><strong>{{ generationMetrics.generated_files || 0 }}</strong></div>
              <div><span>总记录数</span><strong>{{ generationMetrics.total_records || 0 }}</strong></div>
              <div><span>总申报金额</span><strong>{{ formatAmount(generationMetrics.total_declared_amount) }}</strong></div>
              <div><span>总扣税金额</span><strong>{{ formatAmount(generationMetrics.total_withheld_tax) }}</strong></div>
            </div>
            <table class="restricted-metric-table">
              <thead><tr><th>类型</th><th>记录数</th><th>申报金额</th><th>扣税金额</th></tr></thead>
              <tbody>
                <tr><td>限售股</td><td>{{ generationMetrics.restricted_stock_records || 0 }}</td><td>{{ formatAmount(generationMetrics.restricted_stock_declared_amount) }}</td><td>{{ formatAmount(generationMetrics.restricted_stock_withheld_tax) }}</td></tr>
                <tr><td>利息/股息红利</td><td>{{ generationMetrics.interest_records || 0 }}</td><td>{{ formatAmount(generationMetrics.interest_declared_amount) }}</td><td>{{ formatAmount(generationMetrics.interest_withheld_tax) }}</td></tr>
                <tr><td>合计</td><td>{{ generationMetrics.total_records || 0 }}</td><td>{{ formatAmount(generationMetrics.total_declared_amount) }}</td><td>{{ formatAmount(generationMetrics.total_withheld_tax) }}</td></tr>
              </tbody>
            </table>
            <div v-if="generationMetrics.interest_source_withheld_warnings" class="restricted-warning">
              债券兑息源表扣税金额提示 {{ generationMetrics.interest_source_withheld_warnings }} 条
            </div>
          </div>

          <div v-if="reconciliationJob" class="restricted-reconciliation-panel">
            <div class="card-header compact-header">
              <strong>余额表核对结果</strong>
              <span class="tag" :class="reconciliationJob.status === 'success' ? 'tag-success' : 'tag-danger'">{{ reconciliationJob.status === 'success' ? '核对通过' : '存在差异' }}</span>
            </div>
            <div v-if="!reconciliationRows.length" class="empty-inline">全部机构核对通过。</div>
            <div v-else class="table-wrap">
              <table class="restricted-metric-table">
                <thead><tr><th>机构代码</th><th>限售股余额</th><th>限售股申报</th><th>限售股差额</th><th>利息税余额</th><th>利息税申报</th><th>利息税差额</th></tr></thead>
                <tbody>
                  <tr v-for="row in reconciliationRows" :key="row['公司段']">
                    <td>{{ row['公司段'] }}</td><td>{{ formatAmount(row['限售股税费(余额表)']) }}</td><td>{{ formatAmount(row['限售股税费(申报表)']) }}</td><td>{{ formatAmount(row['限售股差额']) }}</td><td>{{ formatAmount(row['利息税税费(余额表)']) }}</td><td>{{ formatAmount(row['利息税税费(申报表)']) }}</td><td>{{ formatAmount(row['利息税差额']) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div v-else-if="restrictedStep === 2" class="empty-inline">余额表尚未核对，可上传余额表核对或选择跳过。</div>
          <div v-else-if="restrictedStep === 3 && !reconciliationJob" class="empty-inline">已跳过余额表核对。</div>

          <div v-if="generationArtifacts.length" class="download-grid workflow-downloads">
            <a
              v-for="artifact in generationArtifacts"
              :key="artifact.id"
              class="download-item"
              :href="workflowApi.artifactDownloadUrl(artifact.id)"
              target="_blank"
            >
              <el-icon><Download /></el-icon>
              <span class="download-text">
                <strong>{{ artifact.file_name }}</strong>
                <small>{{ artifactTypeLabel(artifact.artifact_type) }}</small>
              </span>
            </a>
          </div>
        </template>

        <template v-else-if="isPartTime">
          <div v-if="job.error_message" class="personnel-error-panel"><strong>处理失败</strong><p>{{ job.error_message }}</p></div>
          <div class="workflow-summary-grid">
            <div><span>主数据来源</span><strong>{{ autoMetrics.master_source_period_label || '未找到' }}</strong></div>
            <div><span>工资人数</span><strong>{{ autoMetrics.payroll_count || 0 }}</strong></div>
            <div><span>正常匹配</span><strong>{{ autoMetrics.matched_count || 0 }}</strong></div>
            <div><span>新增人员</span><strong>{{ autoMetrics.new_count || 0 }}</strong></div>
            <div><span>重新任职</span><strong>{{ autoMetrics.rehire_count || 0 }}</strong></div>
            <div><span>自动离职</span><strong>{{ autoMetrics.leaver_count || 0 }}</strong></div>
            <div><span>资料修改</span><strong>{{ autoMetrics.modified_count || 0 }}</strong></div>
            <div><span>同名冲突</span><strong>{{ autoMetrics.same_name_conflict_count || 0 }}</strong></div>
            <div><span>收入合计</span><strong>{{ formatAmount(autoMetrics.income_total) }}</strong></div>
            <div><span>机构数量</span><strong>{{ autoMetrics.org_count || 0 }}</strong></div>
          </div>
          <div v-if="autoMetrics.master_source_materialized" class="source-note">已将上月劳务报酬人员主数据复制为本月基准。</div>
          <div v-if="!autoMetrics.part_time_finalized" class="restricted-warning">收入核对完成。请下载待补充人员变更表，补齐后上传并重新执行生成申报文件。</div>
          <div v-if="issueDetails.length" class="restricted-warning-list"><strong>核对问题</strong><div v-for="(issue, index) in issueDetails" :key="index" class="restricted-warning">{{ issue.message }}</div></div>
          <div v-if="job.artifacts?.length" class="download-grid workflow-downloads">
            <a v-for="artifact in job.artifacts" :key="artifact.id" class="download-item" :href="workflowApi.artifactDownloadUrl(artifact.id)" target="_blank"><el-icon><Download /></el-icon><span class="download-text"><strong>{{ artifact.file_name }}</strong><small>{{ artifactTypeLabel(artifact.artifact_type) }}</small></span></a>
          </div>
        </template>

        <template v-else-if="isAutoGenerateWorkflow">
          <div v-if="job.error_message" class="personnel-error-panel"><strong>处理失败</strong><p>{{ job.error_message }}</p></div>
          <div class="workflow-summary-grid">
            <template v-if="isIntern">
              <div><span>导入人数</span><strong>{{ autoMetrics.intern_records || 0 }}</strong></div>
              <div><span>有效人数</span><strong>{{ autoMetrics.intern_valid_records || 0 }}</strong></div>
              <div><span>机构数</span><strong>{{ autoMetrics.intern_orgs || 0 }}</strong></div>
              <div><span>补贴合计</span><strong>{{ formatAmount(autoMetrics.intern_total_amount) }}</strong></div>
              <div><span>异常数</span><strong>{{ autoMetrics.intern_issue_records || 0 }}</strong></div>
            </template>
            <template v-else>
              <div><span>业绩人数</span><strong>{{ autoMetrics.broker_records || 0 }}</strong></div>
              <div><span>申报人数</span><strong>{{ autoMetrics.broker_declared_records || 0 }}</strong></div>
              <div><span>申报收入</span><strong>{{ formatAmount(autoMetrics.broker_declared_amount) }}</strong></div>
              <div><span>个人所得税</span><strong>{{ formatAmount(autoMetrics.broker_personal_tax) }}</strong></div>
            </template>
          </div>
          <div v-if="issueDetails.length" class="restricted-warning-list">
            <strong>{{ isIntern ? '导入异常' : '处理提醒' }}</strong>
            <div v-for="(issue, index) in issueDetails" :key="index" class="restricted-warning">{{ issue.message }}</div>
          </div>
          <div v-if="job.artifacts?.length" class="download-grid workflow-downloads">
            <a v-for="artifact in job.artifacts" :key="artifact.id" class="download-item" :href="workflowApi.artifactDownloadUrl(artifact.id)" target="_blank">
              <el-icon><Download /></el-icon><span class="download-text"><strong>{{ artifact.file_name }}</strong><small>{{ artifactTypeLabel(artifact.artifact_type) }}</small></span>
            </a>
          </div>
          <div v-if="autoDownloadArtifacts.length" class="action-bar compact-actions">
            <button class="btn btn-primary" @click="batchDownloadAuto"><el-icon><Download /></el-icon>批量下载</button>
          </div>
        </template>

        <template v-else>
          <div v-if="job.error_message" class="personnel-error-panel">
            <strong>处理失败</strong>
            <p>{{ job.error_message }}</p>
          </div>

          <div v-if="job.result_summary" class="workflow-summary-grid">
            <div v-for="(value, key) in job.result_summary" :key="key">
              <span>{{ summaryLabel(String(key)) }}</span>
              <strong>{{ value }}</strong>
            </div>
          </div>

          <div v-if="job.artifacts?.length" class="download-grid workflow-downloads">
            <a
              v-for="artifact in job.artifacts"
              :key="artifact.id"
              class="download-item"
              :href="workflowApi.artifactDownloadUrl(artifact.id)"
              target="_blank"
            >
              <el-icon><Download /></el-icon>
              <span class="download-text">
                <strong>{{ artifact.file_name }}</strong>
                <small>{{ artifactTypeLabel(artifact.artifact_type) }}</small>
              </span>
            </a>
          </div>
        </template>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, VideoPlay } from '@element-plus/icons-vue'
import { workflowApi, type Job, type Workflow } from '../api'

const props = defineProps<{
  workflow: Workflow
  periodId: number | null
}>()

const selectedFiles = reactive<Record<string, File | null>>({})
const job = ref<Job | null>(null)
const running = ref(false)
const folderInput = ref<HTMLInputElement | null>(null)
const restrictedStep = ref(1)
const partTimeStep = ref(1)
const generationJob = ref<Job | null>(null)
const reconciliationJob = ref<Job | null>(null)
const restrictedUploadIds = reactive<Record<string, number>>({})
const brokerIncomeFiles = ref<File[]>([])
const annualBonusFiles = ref<File[]>([])

const sharedStaffWorkflows = new Set([
  'staff_info_update',
  'annual_bonus_tax',
  'broker_tax',
])

const optionalRolesByWorkflow: Record<string, string[]> = {
  staff_info_update: ['staff_info'],
  part_time_tax: ['personnel_changes'],
  restricted_stock_interest_tax: ['tax_sheet', 'interest_tax', 'balance_sheet'],
}

const roleLabels: Record<string, string> = {
  salary_sheet: '工资单',
  staff_info: '人员信息表',
  staff_change: '人员信息变动表',
  bonus_sheet: '年终奖表',
  tax_sheet: '限售股申报表',
  interest_tax: '利息税申报表',
  balance_sheet: '余额表',
  intern_salary: '实习生补贴表',
  broker_income: '经纪人收入表',
  payroll: '劳务报酬收入表',
  personnel_changes: '人员信息变更表（选传）',
  invoice_detail: '电子发票明细',
  certification_sheet: '认证抵扣表',
  booking_sheet: '入账台账',
  ledger_export: '记账导出',
}

const roleEntries = computed(() => {
  const roles = effectiveRequiredRoles.value.slice()
  for (const role of optionalRolesByWorkflow[props.workflow.code] || []) {
    if (!roles.includes(role)) roles.push(role)
  }
  return roles
})
const displayRoleEntries = computed(() => {
  if (!isPartTime.value) return roleEntries.value
  return partTimeStep.value === 1 ? ['payroll'] : ['personnel_changes']
})

const effectiveRequiredRoles = computed(() =>
  props.workflow.required_file_roles.filter((role) => !(role === 'staff_info' && sharedStaffWorkflows.has(props.workflow.code)))
)

const usesSharedStaffInfo = computed(() => sharedStaffWorkflows.has(props.workflow.code))
const isRestrictedStockInterest = computed(() => props.workflow.code === 'restricted_stock_interest_tax')
const isIntern = computed(() => props.workflow.code === 'intern_tax')
const isBroker = computed(() => props.workflow.code === 'broker_tax')
const isAnnualBonus = computed(() => props.workflow.code === 'annual_bonus_tax')
const isPartTime = computed(() => props.workflow.code === 'part_time_tax')
const isAutoGenerateWorkflow = computed(() => isIntern.value || isBroker.value)
const hasRestrictedSource = computed(() => Boolean(selectedFiles.tax_sheet || selectedFiles.interest_tax))
const restrictedActionHint = computed(() => {
  if (restrictedStep.value === 1) return hasRestrictedSource.value
    ? '已识别申报源文件，可直接运行并生成申报表。余额表可选。'
    : '请至少选择限售股申报表或利息税申报表。'
  if (restrictedStep.value === 2) return '可上传余额表进行核对，也可跳过核对后下载。'
  return '申报文件已就绪，可批量下载。'
})
const generationMetrics = computed(() => generationJob.value?.result_summary || {})
const generationArtifacts = computed(() =>
  (generationJob.value?.artifacts || []).filter((artifact) =>
    artifact.artifact_type === 'declaration' || artifact.artifact_type === 'personnel_collection'
  )
)
const reconciliationRows = computed(() => {
  const rows = reconciliationJob.value?.result_summary?.reconciliation_rows
  return Array.isArray(rows) ? rows : []
})
const autoMetrics = computed(() => job.value?.result_summary || {})
const issueDetails = computed<any[]>(() => {
  const items = job.value?.result_summary?.issue_details
  return Array.isArray(items) ? items : []
})
const autoDownloadArtifacts = computed(() =>
  (job.value?.artifacts || []).filter((artifact) => ['declaration', 'personnel_collection'].includes(artifact.artifact_type))
)
const missingRequired = computed(() =>
  effectiveRequiredRoles.value.filter((role) => !selectedFiles[role])
)

const jobStatusLabel = computed(() => {
  if (!job.value) return ''
  const labels: Record<string, string> = {
    success: '完成',
    needs_review: '需复核',
    failed: '失败',
    running: '运行中',
    pending: '等待中',
  }
  return labels[job.value.status] || job.value.status
})

const jobTagClass = computed(() => {
  if (!job.value) return 'tag-info'
  if (job.value.status === 'success') return 'tag-success'
  if (job.value.status === 'needs_review') return 'tag-warning'
  if (job.value.status === 'failed') return 'tag-danger'
  return 'tag-info'
})

watch(
  () => [props.workflow.code, props.periodId] as const,
  () => {
    Object.keys(selectedFiles).forEach((key) => delete selectedFiles[key])
    job.value = null
    restrictedStep.value = 1
    partTimeStep.value = 1
    generationJob.value = null
    reconciliationJob.value = null
    Object.keys(restrictedUploadIds).forEach((key) => delete restrictedUploadIds[key])
    brokerIncomeFiles.value = []
    annualBonusFiles.value = []
    void restoreLatestJobs()
  },
  { immediate: true }
)

async function restoreLatestJobs() {
  if (!props.periodId) return
  try {
    if (isRestrictedStockInterest.value) {
      const [generation, reconciliation] = await Promise.all([
        workflowApi.latestJob(props.workflow.code, props.periodId, 'generate').then(({ data }) => data).catch((error) => error?.response?.status === 404 ? null : Promise.reject(error)),
        workflowApi.latestJob(props.workflow.code, props.periodId, 'reconcile').then(({ data }) => data).catch((error) => error?.response?.status === 404 ? null : Promise.reject(error)),
      ])
      generationJob.value = generation
      reconciliationJob.value = reconciliation
      job.value = reconciliation || generation
      if (reconciliation?.status === 'success') restrictedStep.value = 3
      else if (generation) restrictedStep.value = 2
      return
    }
    if (isPartTime.value) {
      const [initial, recheck] = await Promise.all([
        workflowApi.latestJob(props.workflow.code, props.periodId, 'initial').then(({ data }) => data).catch((error) => error?.response?.status === 404 ? null : Promise.reject(error)),
        workflowApi.latestJob(props.workflow.code, props.periodId, 'recheck').then(({ data }) => data).catch((error) => error?.response?.status === 404 ? null : Promise.reject(error)),
      ])
      job.value = recheck || initial
      if (initial) partTimeStep.value = 2
      return
    }
    const { data } = await workflowApi.latestJob(props.workflow.code, props.periodId, 'generate')
    job.value = data
  } catch (error: any) {
    if (error?.response?.status !== 404) ElMessage.warning('历史运行结果恢复失败')
  }
}

function roleLabel(role: string) {
  return roleLabels[role] || role
}

function isRequired(role: string) {
  return effectiveRequiredRoles.value.includes(role)
}

function onFilePicked(role: string, event: Event) {
  const files = Array.from((event.target as HTMLInputElement).files || [])
  const file = files[0] || null
  if (isBroker.value && role === 'broker_income') brokerIncomeFiles.value = files
  if (isAnnualBonus.value && role === 'bonus_sheet') annualBonusFiles.value = files
  selectedFiles[role] = file
  delete restrictedUploadIds[role]
  if (file && isAutoGenerateWorkflow.value) window.setTimeout(() => runWorkflow(), 0)
}

function clearFile(role: string) {
  selectedFiles[role] = null
  if (role === 'broker_income') brokerIncomeFiles.value = []
  if (role === 'bonus_sheet') annualBonusFiles.value = []
  delete restrictedUploadIds[role]
}

function roleFileSummary(role: string) {
  if (isBroker.value && role === 'broker_income' && brokerIncomeFiles.value.length) return `已选择 ${brokerIncomeFiles.value.length} 个文件`
  if (isAnnualBonus.value && role === 'bonus_sheet' && annualBonusFiles.value.length) return `已选择 ${annualBonusFiles.value.length} 个文件`
  return selectedFiles[role]?.name || (isRequired(role) ? '必传' : '可选')
}

function openFolderPicker() {
  folderInput.value?.click()
}

function onFolderPicked(event: Event) {
  const files = Array.from((event.target as HTMLInputElement).files || [])
  for (const file of files) {
    const name = file.name.replace(/\s/g, '')
    if (name.includes('限售股')) selectedFiles.tax_sheet = file
    else if (name.includes('债券兑息') || name.includes('利息税')) selectedFiles.interest_tax = file
    else if (name.includes('余额表')) selectedFiles.balance_sheet = file
  }
  Object.keys(restrictedUploadIds).forEach((key) => delete restrictedUploadIds[key])
  ;(event.target as HTMLInputElement).value = ''
}

function skipReconciliation() {
  restrictedStep.value = 3
}

function returnToRestrictedUpload() {
  restrictedStep.value = 1
}

function returnToRestrictedReconciliation() {
  restrictedStep.value = 2
}

async function batchDownloadRestricted() {
  if (!generationJob.value) return
  await downloadArtifactsToFolder(generationArtifacts.value, generationJob.value.id)
}

async function downloadArtifactsToFolder(artifacts: any[], jobId: number) {
  const browserWindow = window as any
  if (!artifacts.length) {
    ElMessage.warning('没有可下载的申报文件')
    return
  }
  if (!browserWindow.showDirectoryPicker) {
    window.location.href = workflowApi.batchDownloadUrl(jobId)
    return
  }
  try {
    const directory = await browserWindow.showDirectoryPicker()
    for (const artifact of artifacts) {
      const response = await workflowApi.downloadArtifact(artifact.id)
      const file = await directory.getFileHandle(artifact.file_name, { create: true })
      const writable = await file.createWritable()
      await writable.write(response.data)
      await writable.close()
    }
    ElMessage.success(`已保存 ${artifacts.length} 个文件`)
  } catch (error: any) {
    if (error?.name !== 'AbortError') ElMessage.error('批量下载失败，请重试')
  }
}

async function uploadRestrictedFiles() {
  if (!hasRestrictedSource.value) return
  for (const role of ['tax_sheet', 'interest_tax', 'balance_sheet']) {
    if (restrictedUploadIds[role] && selectedFiles[role]) continue
    const file = selectedFiles[role]
    if (!file) continue
    const { data } = await workflowApi.uploadFile(file, role, props.periodId)
    restrictedUploadIds[role] = data.id
  }
}

async function runRestrictedGeneration() {
  running.value = true
  try {
    await uploadRestrictedFiles()
    await runRestrictedWorkflow('generate')
  } catch {
    ElMessage.error('文件上传或申报生成失败，请检查文件后重试')
  } finally {
    running.value = false
  }
}

async function runPartTimeInitial() {
  const payroll = selectedFiles.payroll
  if (!payroll) return
  await runPartTimeWorkflow('initial', [['payroll', payroll]])
  if (job.value) partTimeStep.value = 2
}

async function runPartTimeRecheck() {
  const changes = selectedFiles.personnel_changes
  if (!changes) return
  await runPartTimeWorkflow('recheck', [['personnel_changes', changes]])
}

async function runPartTimeWorkflow(operation: 'initial' | 'recheck', files: Array<[string, File]>) {
  running.value = true
  try {
    const inputIds: number[] = []
    for (const [role, file] of files) {
      const { data } = await workflowApi.uploadFile(file, role, props.periodId)
      inputIds.push(data.id)
    }
    const { data } = await workflowApi.createJob(props.workflow.code, inputIds, props.periodId, operation)
    job.value = data
    if (data.status === 'failed') ElMessage.error('流程运行失败')
    else if (data.status === 'needs_review') ElMessage.warning(operation === 'initial' ? '核对完成，请处理问题后上传人员变更表' : '变更表仍有问题，请修正后重试')
    else ElMessage.success('申报文件生成完成')
  } catch {
    ElMessage.error('流程运行失败，请检查上传文件或后端服务')
  } finally {
    running.value = false
  }
}

async function runRestrictedWorkflow(operation: 'generate' | 'reconcile') {
  const sourceIds = ['tax_sheet', 'interest_tax']
    .map((role) => restrictedUploadIds[role])
    .filter((id): id is number => Boolean(id))
  if (!sourceIds.length) {
    ElMessage.error('请至少上传限售股申报表或利息税申报表')
    return
  }
  running.value = true
  job.value = null
  try {
    if (operation === 'reconcile' && selectedFiles.balance_sheet && !restrictedUploadIds.balance_sheet) {
      await uploadRestrictedFiles()
    }
    const inputIds = operation === 'reconcile' && restrictedUploadIds.balance_sheet
      ? [...sourceIds, restrictedUploadIds.balance_sheet]
      : sourceIds
    const { data } = await workflowApi.createJob(props.workflow.code, inputIds, props.periodId, operation)
    job.value = data
    if (operation === 'generate') {
      generationJob.value = data
      restrictedStep.value = 2
    } else {
      reconciliationJob.value = data
      if (data.status === 'success') restrictedStep.value = 3
    }
    if (data.status === 'failed') ElMessage.error('流程运行失败')
    else if (data.status === 'needs_review') ElMessage.warning('核对发现问题，请处理后重新核对')
    else ElMessage.success(operation === 'generate' ? '申报文件生成完成' : '余额表核对完成')
  } catch {
    ElMessage.error('流程运行失败，请检查后端服务或上传文件')
  } finally {
    running.value = false
  }
}

function summaryLabel(key: string) {
  const labels: Record<string, string> = {
    input_files: '输入文件',
    rows: '明细行数',
    summary_rows: '汇总行数',
    issues: '问题数',
    artifacts: '产物数',
    collection_files: '采集文件',
  }
  return labels[key] || key
}

function formatAmount(value: unknown) {
  const amount = Number(value || 0)
  return Number.isFinite(amount) ? amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '0.00'
}

function artifactTypeLabel(type: string) {
  const labels: Record<string, string> = {
    working_sheet: '底稿',
    tax_result: '处理结果',
    declaration: '申报文件',
    annual_bonus_result: '年终奖结果',
    restricted_stock_interest_result: '限售股利息税结果',
    intern_tax_result: '实习生结果',
    broker_tax_result: '经纪人结果',
    part_time_master: '本月劳务报酬人员信息表',
    part_time_pending_changes: '待补充人员信息变更表',
    part_time_workpaper: '劳务报酬申报处理底稿',
    invoice_ledger: '发票台账',
    certification_ledger: '认证核对',
    voucher_draft: '凭证草稿',
    staff_info_current: '更新后人员信息表',
    personnel_collection: '人员采集文件',
    validation_issues: '校验问题',
    update_report: '更新报告',
  }
  return labels[type] || type
}

async function runWorkflow(operation = 'generate') {
  if (missingRequired.value.length) return
  running.value = true
  job.value = null
  try {
    const uploadedIds: number[] = []
    for (const role of roleEntries.value) {
      if (role === 'balance_sheet' && operation !== 'reconcile') continue
      const files = isBroker.value && role === 'broker_income'
        ? brokerIncomeFiles.value
        : isAnnualBonus.value && role === 'bonus_sheet'
          ? annualBonusFiles.value
          : [selectedFiles[role]].filter((file): file is File => Boolean(file))
      for (const file of files) {
        const { data } = await workflowApi.uploadFile(file, role, props.periodId)
        uploadedIds.push(data.id)
      }
    }
    const { data } = await workflowApi.createJob(props.workflow.code, uploadedIds, props.periodId, operation)
    job.value = data
    if (data.status === 'failed') {
      ElMessage.error('流程运行失败')
    } else if (data.status === 'needs_review') {
      ElMessage.warning('流程已完成，请下载校验问题复核')
    } else {
      ElMessage.success('流程运行完成')
    }
  } catch (error) {
    ElMessage.error('流程运行失败，请检查后端服务或上传文件')
  } finally {
    running.value = false
  }
}

async function batchDownloadAuto() {
  if (job.value) await downloadArtifactsToFolder(autoDownloadArtifacts.value, job.value.id)
}
</script>
