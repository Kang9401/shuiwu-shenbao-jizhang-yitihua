<template>
  <div class="tax-page">
    <div class="step-indicator">
      <button
        type="button"
        class="step-item"
        :class="{ active: step === 1, done: step > 1, disabled: !canGoToStep(1) }"
        :disabled="!canGoToStep(1)"
        @click="goToStep(1)"
      >
        <span class="step-index">1</span>
        <span class="step-copy">
          <strong>上传核对</strong>
          <small>整理申报资料</small>
        </span>
      </button>
      <button
        type="button"
        class="step-item"
        :class="{ active: step === 2, done: step > 2, disabled: !canGoToStep(2) }"
        :disabled="!canGoToStep(2)"
        @click="goToStep(2)"
      >
        <span class="step-index">2</span>
        <span class="step-copy">
          <strong>人员确认</strong>
          <small>处理差异与变动</small>
        </span>
      </button>
      <button
        type="button"
        class="step-item"
        :class="{ active: step === 3, disabled: !canGoToStep(3) }"
        :disabled="!canGoToStep(3)"
        @click="goToStep(3)"
      >
        <span class="step-index">3</span>
        <span class="step-copy">
          <strong>生成申报</strong>
          <small>下载申报成果</small>
        </span>
      </button>
    </div>

    <section v-if="step === 1" class="card tax-card">
      <div class="card-header">
        <strong>上传申报资料</strong>
        <div class="header-actions">
          <button class="btn btn-sm btn-outline" @click="openFolderPicker">
            <el-icon><FolderOpened /></el-icon>
            选择月份文件夹
          </button>
          <input
            ref="folderInput"
            :key="`folder-${inputVersion}`"
            class="hidden-file-input"
            type="file"
            accept=".xlsx,.xls"
            multiple
            webkitdirectory
            @change="pickFolder"
          />
          <span class="tag tag-info">
            <el-icon><RefreshRight /></el-icon>
            第 {{ session?.current_round || 1 }} 轮核对
          </span>
          <span v-if="cachedFileCount > 0" class="tag tag-success" :title="cachedFileList">已缓存 {{ cachedFileCount }} 个文件</span>
        </div>
      </div>

      <div class="card-body">
        <div class="upload-grid">
          <div class="upload-section">
            <h4>必填资料</h4>
            <div v-for="item in requiredFiles" :key="item.role" class="upload-item" :class="{ 'has-file': files[item.role] }">
              <label>{{ item.label }}</label>
              <label class="btn btn-sm btn-outline file-picker-button">
                选择文件
                <input :key="`${item.role}-${inputVersion}`" class="hidden-file-input" type="file" accept=".xlsx,.xls" @change="pickFile(item.role, $event)" />
              </label>
              <span class="upload-status" :class="files[item.role] ? 'ready' : 'empty'">
                {{ files[item.role] || '未选择' }}
              </span>
              <button class="btn btn-xs btn-ghost" :disabled="!files[item.role]" @click="clearFile(item.role)">清除</button>
            </div>
          </div>

          <div class="upload-section">
            <h4>可选工资资料</h4>
            <div v-for="item in optionalFiles" :key="item.role" class="upload-item" :class="{ 'has-file': files[item.role] }">
              <label>{{ item.label }}</label>
              <label class="btn btn-sm btn-outline file-picker-button">
                选择文件
                <input :key="`${item.role}-${inputVersion}`" class="hidden-file-input" type="file" accept=".xlsx,.xls" @change="pickFile(item.role, $event)" />
              </label>
              <span class="upload-status" :class="files[item.role] ? 'ready' : 'empty'">
                {{ files[item.role] || '未选择' }}
              </span>
              <button class="btn btn-xs btn-ghost" :disabled="!files[item.role]" @click="clearFile(item.role)">清除</button>
            </div>
          </div>

          <div class="upload-section">
            <h4>专项附加扣除</h4>
            <div class="upload-item" :class="{ 'has-file': deductionFiles.length }">
              <label>专项附加扣除文件</label>
              <label class="btn btn-sm btn-outline file-picker-button">
                选择文件
                <input :key="`deductions-${inputVersion}`" class="hidden-file-input" type="file" accept=".xlsx,.xls" multiple @change="pickDeductionFiles" />
              </label>
              <span class="upload-status" :class="deductionFiles.length ? 'ready' : 'empty'">
                {{ deductionFiles.length ? `已选择 ${deductionFiles.length} 个文件` : '未选择' }}
              </span>
              <button class="btn btn-xs btn-ghost" :disabled="!deductionFiles.length" @click="clearDeductionFiles">清除</button>
            </div>
            <div v-if="deductionFiles.length" class="deduction-file-list">
              <span v-for="file in deductionFiles" :key="fileIdentity(file)">
                {{ file.name }}
                <button type="button" title="移除" @click="removeDeductionFile(file)">×</button>
              </span>
            </div>
          </div>
        </div>

        <div class="action-bar">
          <div v-if="missingRequiredLabels.length" class="action-hint">
            请先补齐：
            <span v-for="label in missingRequiredLabels" :key="label" class="missing-chip">{{ label }}</span>
          </div>
          <div v-else class="action-hint">
            本轮核对将使用上月人员主数据中的员工数据。
          </div>
          <button class="btn btn-primary btn-lg" :disabled="!canStartVerify" @click="runVerify">
            <span v-if="verifying" class="spinner"></span>
            <el-icon v-else><CircleCheck /></el-icon>
            {{ verifying ? '核对中...' : '开始核对' }}
          </button>
        </div>
      </div>
    </section>

    <section v-if="step === 2 && report" class="result-stack">
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-value">{{ report.summary.total_employees }}</div>
          <div class="stat-label">总人数</div>
        </div>
        <div class="stat-card" :class="report.tax_diff.has_issues ? 'danger' : 'success'">
          <div class="stat-value">{{ report.tax_diff.items.length }}</div>
          <div class="stat-label">个税差异</div>
        </div>
        <div class="stat-card" :class="report.personnel_changes.has_issues ? 'warn' : 'success'">
          <div class="stat-value">{{ report.personnel_changes.items.length }}</div>
          <div class="stat-label">人员变动</div>
        </div>
        <div class="stat-card" :class="report.missing_cert.has_issues ? 'danger' : 'success'">
          <div class="stat-value">{{ report.missing_cert.items.length }}</div>
          <div class="stat-label">证件缺失</div>
        </div>
      </div>

      <section class="card report-card">
        <div class="card-header">
          <strong>总体核对报告</strong>
          <div class="header-actions">
            <span class="tag" :class="hasBlockingIssues ? 'tag-danger' : report.summary.total_issues ? 'tag-warning' : 'tag-success'">
              {{ hasBlockingIssues ? `阻断 ${report.summary.blocking_issues || 0} 项` : report.summary.total_issues ? `提醒 ${report.summary.total_issues} 项` : '全部通过' }}
            </span>
            <a
              v-for="artifact in reconciliationReportArtifacts"
              :key="artifact.download_url"
              class="btn btn-sm btn-outline"
              :href="artifact.download_url"
              target="_blank"
            >
              <el-icon><Download /></el-icon>
              导出核对报告
            </a>
          </div>
        </div>
        <div class="card-body report-body">
          <div class="report-summary-grid">
            <div>
              <span>本期人数</span>
              <strong>{{ report.summary.total_employees }}</strong>
            </div>
            <div>
              <span>机构数</span>
              <strong>{{ report.summary.total_orgs }}</strong>
            </div>
            <div>
              <span>问题总数</span>
              <strong>{{ report.summary.total_issues }}</strong>
            </div>
            <div>
              <span>阻断项</span>
              <strong>{{ report.summary.blocking_issues || 0 }}</strong>
            </div>
          </div>
          <div class="report-check-grid">
            <article v-for="check in checkItems" :key="check.code" class="report-check" :class="check.status">
              <div>
                <strong>{{ check.title }}</strong>
                <p>{{ check.message }}</p>
              </div>
              <span>{{ check.issue_count }}</span>
            </article>
          </div>
        </div>
      </section>

      <section v-if="report.payroll_org_format?.has_issues" class="card">
        <div class="card-header">
          <strong>工资表异常</strong>
          <span class="tag tag-danger">{{ report.payroll_org_format.items.length }} 项机构代码异常</span>
        </div>
        <div class="card-body">
          <el-table :data="report.payroll_org_format.items" size="small" max-height="260">
            <el-table-column prop="payroll_type" label="工资单类型" min-width="160" />
            <el-table-column prop="name" label="姓名" width="100" />
            <el-table-column prop="employee_id" label="员工编号" width="120" />
            <el-table-column prop="org_code" label="机构代码" width="120" />
            <el-table-column prop="message" label="提示" min-width="220" />
          </el-table>
        </div>
      </section>

      <section v-if="report.taxpayer_org_mapping?.has_issues" class="card">
        <div class="card-header">
          <strong>工资机构识别号映射异常</strong>
          <span class="tag tag-danger">{{ report.taxpayer_org_mapping.items.length }} 项阻断</span>
        </div>
        <div class="card-body">
          <el-table :data="report.taxpayer_org_mapping.items" size="small" max-height="260">
            <el-table-column prop="payroll_type" label="工资单类型" min-width="150" />
            <el-table-column prop="name" label="姓名" width="100" />
            <el-table-column prop="employee_id" label="员工编号" width="120" />
            <el-table-column prop="taxpayer_id" label="扣缴义务人纳税人识别号" min-width="220" />
            <el-table-column prop="message" label="提示" min-width="260" />
          </el-table>
        </div>
      </section>

      <section v-if="hasDeductionWarnings" class="card">
        <div class="card-header">
          <strong>专项附加扣除异常</strong>
          <span class="tag tag-danger">
            重复人员 {{ report.deduction_warnings.duplicates.length }} 名，缺失机构 {{ report.deduction_warnings.missing_orgs.length }} 个，需补全证件号 {{ deductionMatchWarnings.length }} 人
          </span>
        </div>
        <div class="card-body">
          <el-table v-if="report.deduction_warnings.duplicates.length" :data="report.deduction_warnings.duplicates" size="small" max-height="260">
            <el-table-column type="expand">
              <template #default="{ row }">
                <el-table :data="row.details" size="small" style="width:100%">
                  <el-table-column prop="file_name" label="来源表" min-width="200" />
                  <el-table-column prop="deduction_summary" label="专项扣除明细" min-width="360" />
                </el-table>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="重复人员" width="120" />
            <el-table-column prop="id_number" label="证件号码" min-width="170" />
            <el-table-column prop="file_names" label="重复来源表" min-width="260" />
            <el-table-column prop="file_count" label="出现次数" width="100" />
          </el-table>
          <el-table v-if="deductionMissingOrgRows.length" :data="deductionMissingOrgRows" size="small" max-height="260" style="margin-top:16px">
            <el-table-column prop="org_code" label="机构代码" width="140" />
            <el-table-column prop="message" label="异常说明" min-width="280" />
          </el-table>
          <el-table v-if="deductionMatchWarnings.length" :data="deductionMatchWarnings" size="small" max-height="260" style="margin-top:16px">
            <el-table-column prop="name" label="专项表姓名" width="120" />
            <el-table-column prop="id_number" label="专项表证件号码" min-width="170" />
            <el-table-column prop="candidate_count" label="候选人数" width="100" />
            <el-table-column prop="candidate_id_numbers" label="工资人员候选证件号码" min-width="260" />
            <el-table-column prop="message" label="处理提示" min-width="360" />
          </el-table>
        </div>
      </section>

      <section class="card personnel-update-card">
        <div class="card-header">
          <strong>人员信息变动表-雇员</strong>
          <div class="header-actions">
            <span v-if="latestRound" class="tag tag-info">最新核对：第 {{ latestRound }} 轮</span>
          </div>
        </div>
        <div class="card-body">
          <div class="personnel-action-layout">
            <div class="personnel-action-copy">
              <p>下载后由 HR 补充或确认本月人员变动；上传更新表后，点击重新核对生成本月人员信息并刷新当前结果。</p>
              <p v-if="importedStaffChangeName" class="personnel-imported-file">待重新核对：{{ importedStaffChangeName }}</p>
            </div>
            <div class="personnel-action-buttons">
              <a
                v-for="artifact in personnelReviewArtifacts"
                :key="artifact.download_url"
                class="btn btn-sm btn-primary"
                :href="artifact.download_url"
                target="_blank"
              >
                <el-icon><Download /></el-icon>
                下载人员信息变动表-雇员
              </a>
              <button v-if="!personnelReviewArtifacts.length" class="btn btn-sm btn-outline" disabled>
                暂无可下载雇员表
              </button>
              <button class="btn btn-sm btn-primary" @click="openStaffReimport">
                <el-icon><UploadFilled /></el-icon>
                上传
              </button>
              <button class="btn btn-sm btn-outline" :disabled="verifying" @click="runVerify">
                <span v-if="verifying" class="spinner"></span>
                <el-icon v-else><RefreshRight /></el-icon>
                {{ verifying ? '重新核对中...' : '重新核对' }}
              </button>
              <input
                ref="staffReimportInput"
                class="hidden-file-input"
                type="file"
                accept=".xlsx,.xls"
                @change="pickUpdatedStaffChange"
              />
            </div>
          </div>
          <el-table v-if="personnelChangePreview.length" :data="personnelChangePreview" size="small" max-height="260" style="margin-top:16px">
            <el-table-column prop="*姓名" label="姓名" width="110" />
            <el-table-column prop="员工编号" label="员工编号" width="120" />
            <el-table-column prop="人员状态" label="人员状态" width="100" />
            <el-table-column prop="证件号码" label="证件号码" min-width="170" />
            <el-table-column prop="机构代码(人员信息表)" label="人员信息机构" min-width="145" />
            <el-table-column prop="机构代码(工资单)" label="工资机构" min-width="120" />
          </el-table>
          <div v-else class="empty-inline" style="margin-top:16px">本轮没有需要补充的雇员信息。</div>
        </div>
      </section>

      <section v-if="report.employee_id_changes?.items.length" class="card">
        <div class="card-header">
          <strong>员工编号自动更新</strong>
          <span class="tag tag-warning">{{ report.employee_id_changes.items.length }} 人，仅更新本月主数据</span>
        </div>
        <div class="card-body">
          <el-table :data="report.employee_id_changes.items" size="small" max-height="260">
            <el-table-column prop="name" label="姓名" width="110" />
            <el-table-column prop="org_code" label="机构代码" width="110" />
            <el-table-column prop="old_employee_id" label="原员工编号" width="130" />
            <el-table-column prop="new_employee_id" label="新员工编号" width="130" />
            <el-table-column prop="message" label="处理结果" min-width="260" />
          </el-table>
        </div>
      </section>

      <section class="card">
        <div class="card-header">
          <strong>核对要点</strong>
          <span class="tag" :class="report.summary.total_issues === 0 ? 'tag-success' : 'tag-warning'">
            {{ report.summary.total_issues === 0 ? '全部通过' : `共 ${report.summary.total_issues} 项问题` }}
          </span>
        </div>
        <div class="card-body">
          <div class="check-list">
            <div v-for="check in checkItems" :key="check.code" class="check-item" :class="check.status">
              <div class="check-main">
                <span class="check-dot"></span>
                <div>
                  <strong>{{ check.title }}</strong>
                  <p>{{ check.message }}</p>
                </div>
              </div>
              <span class="tag" :class="check.status === 'pass' ? 'tag-success' : 'tag-danger'">
                {{ check.status === 'pass' ? '通过' : `未通过 ${check.issue_count}` }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-header">
          <strong>核对详情</strong>
        </div>
        <div class="card-body detail-grid">
          <div v-if="report.tax_diff.has_issues" class="detail-panel">
            <h4>个税差异</h4>
            <el-table :data="report.tax_diff.items" size="small" max-height="260">
              <el-table-column prop="name" label="姓名" width="90" />
              <el-table-column prop="org_code" label="机构" width="90" />
              <el-table-column prop="payroll_tax" label="应预扣预缴" width="120" />
              <el-table-column prop="declared_tax" label="个人所得税" width="120" />
              <el-table-column prop="diff" label="差异" />
            </el-table>
          </div>

          <div v-if="report.missing_cert.has_issues" class="detail-panel">
            <h4>证件信息缺失</h4>
            <el-table :data="report.missing_cert.items" size="small" max-height="260">
              <el-table-column prop="name" label="姓名" width="100" />
              <el-table-column prop="org_code" label="机构" width="100" />
              <el-table-column prop="employee_id" label="员工编号" />
            </el-table>
          </div>

          <div v-if="report.summary.total_issues === 0" class="empty-inline">本轮核对全部通过。</div>
        </div>
      </section>

      <div class="action-bar">
        <button class="btn btn-outline btn-lg" @click="step = 1">继续上传/替换资料</button>
        <button class="btn btn-primary btn-lg" :disabled="hasBlockingIssues || generating" @click="runGenerate">
          <span v-if="generating" class="spinner"></span>
          <el-icon v-else><Finished /></el-icon>
          {{ generating ? '生成中...' : hasBlockingIssues ? '存在阻断项，暂不能生成' : '生成申报表' }}
        </button>
      </div>
    </section>

    <section v-if="step === 3" class="card tax-card">
      <div class="card-header">
        <strong>申报表下载</strong>
        <div class="header-actions">
          <span class="tag tag-success">生成完成 · 共 {{ generatedFiles.length }} 个文件</span>
          <button class="btn btn-sm btn-primary" :disabled="batchDownloading || !generatedFiles.length" @click="batchDownload">
            <span v-if="batchDownloading" class="spinner"></span>
            <el-icon v-else><Download /></el-icon>
            {{ batchDownloading ? `下载中 ${batchProgress}/${generatedFiles.length}` : '批量下载全部' }}
          </button>
          <button class="btn btn-sm btn-outline" :disabled="!generatedFiles.length" @click="clearGeneratedOutput">
            <el-icon><Delete /></el-icon>
            一键清空
          </button>
        </div>
      </div>
      <div class="card-body">
        <div class="download-grid">
          <a v-for="file in generatedFiles" :key="file.name" class="download-item" :href="file.download_url" target="_blank">
            <el-icon><Document /></el-icon>
            <span class="download-text">
              <strong>{{ file.name }}</strong>
              <small>{{ fileTypeLabel(file.file_type) }}</small>
            </span>
          </a>
        </div>
        <div class="action-bar">
          <button class="btn btn-outline btn-lg" @click="resetAll">
            <el-icon><RefreshRight /></el-icon>
            开始新的申报
          </button>
          <button class="btn btn-primary btn-lg" :disabled="!generatedFiles.length" @click="emit('open-rpa')">
            开始申报
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CircleCheck,
  Document,
  Delete,
  Download,
  Finished,
  FolderOpened,
  RefreshRight,
  UploadFilled,
} from '@element-plus/icons-vue'
import { currentCompanyHeaders, taxApi, type GeneratedFile, type TaxSession, type VerifyReport } from '../api'

const props = defineProps<{
  session: TaxSession | null
  sessionId?: number
}>()

const emit = defineEmits<{
  (event: 'session-updated', session: TaxSession): void
  (event: 'open-rpa'): void
}>()

const step = ref(1)
const verifying = ref(false)
const generating = ref(false)
const batchDownloading = ref(false)
const batchProgress = ref(0)
const report = ref<VerifyReport | null>(null)
const latestRound = ref(0)
const generatedFiles = ref<GeneratedFile[]>([])
const reviewArtifacts = ref<GeneratedFile[]>([])
const folderInput = ref<HTMLInputElement | null>(null)
const staffReimportInput = ref<HTMLInputElement | null>(null)
const inputVersion = ref(0)
const importedStaffChangeName = ref('')

const files = reactive<Record<string, string>>({})
const fileData = reactive<Record<string, File>>({})
const deductionFiles = ref<File[]>([])

const requiredFiles = [
  { role: 'rank_salary', label: '职级工资单' },
  { role: 'marketing_salary', label: '营销工资单' },
]

const optionalFiles = [
  { role: 'headquarters_salary', label: '总部工资单' },
]

const requiredFileLabels: Record<string, string> = {
  rank_salary: '职级工资单',
  marketing_salary: '营销工资单',
}

const missingRequiredLabels = computed(() => {
  const missing: string[] = []
  if (!files.rank_salary) missing.push(requiredFileLabels.rank_salary)
  if (!files.marketing_salary) missing.push(requiredFileLabels.marketing_salary)
  return missing
})

const canStartVerify = computed(() => Boolean(props.sessionId && !verifying.value && !missingRequiredLabels.value.length))

// 已缓存的文件数（跨步骤切换时保留在内存中，避免重复上传）
const cachedFileCount = computed(() => Object.keys(fileData).length + deductionFiles.value.length)
const cachedFileList = computed(() => {
  const names = [...Object.values(files).filter(Boolean), ...deductionFiles.value.map((file) => file.name)]
  return names.join('、')
})

const personnelReviewArtifacts = computed(() =>
  reviewArtifacts.value.filter((file) => file.file_type === 'personnel_change_review' || file.name.includes('人员信息变动表'))
)

const reconciliationReportArtifacts = computed(() =>
  reviewArtifacts.value.filter((file) => file.file_type === 'reconciliation_report' || file.name.includes('核对报告'))
)

const deductionMissingOrgRows = computed(() =>
  (report.value?.deduction_warnings.missing_orgs || []).map((orgCode) => ({
    org_code: orgCode,
    message: '该营业部未匹配到独立专项附加扣除数据，仅提醒，不影响生成',
  }))
)

const deductionMatchWarnings = computed(() =>
  report.value?.deduction_match_quality?.low_confidence || []
)

const personnelChangePreview = computed(() => report.value?.personnel_change_review || [])

const hasDeductionWarnings = computed(() => Boolean(
  report.value && (
    report.value.deduction_warnings.has_issues
    || deductionMatchWarnings.value.length
  )
))

// 离职人员数量（用于 Step 2 顶部警示横幅）
const checkItems = computed(() => {
  if (!report.value) return []
  return report.value.checks || []
})

const hasBlockingIssues = computed(() => Boolean(report.value?.summary.has_blocking_issues))

watch(
  () => props.sessionId,
  (sessionId) => {
    clearDisplayedResult()
    if (sessionId) void restoreLatestResult(sessionId)
  },
  { immediate: true }
)

function clearDisplayedResult() {
  step.value = 1
  report.value = null
  latestRound.value = 0
  generatedFiles.value = []
  reviewArtifacts.value = []
}

async function restoreLatestResult(sessionId: number) {
  try {
    const { data } = await taxApi.latestResult(sessionId)
    if (props.sessionId !== sessionId || !data.report) return
    report.value = data.report
    latestRound.value = data.round_number || 0
    reviewArtifacts.value = data.artifacts || []
    generatedFiles.value = data.generated_files || []
    step.value = generatedFiles.value.length ? 3 : 2
  } catch {
    // A newly created period has no saved verification result yet.
  }
}

function pickFile(role: string, event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  files[role] = file.name
  fileData[role] = file
}

function clearFile(role: string) {
  delete files[role]
  delete fileData[role]
  inputVersion.value += 1
}

function pickDeductionFiles(event: Event) {
  const picked = Array.from((event.target as HTMLInputElement).files || [])
  deductionFiles.value = mergeUniqueFiles(deductionFiles.value, picked)
}

function clearDeductionFiles() {
  deductionFiles.value = []
  inputVersion.value += 1
}

function removeDeductionFile(file: File) {
  const identity = fileIdentity(file)
  deductionFiles.value = deductionFiles.value.filter((item) => fileIdentity(item) !== identity)
}

function mergeUniqueFiles(current: File[], incoming: File[]) {
  const merged = new Map(current.map((file) => [fileIdentity(file), file]))
  incoming.forEach((file) => merged.set(fileIdentity(file), file))
  return Array.from(merged.values())
}

function openFolderPicker() {
  folderInput.value?.click()
}

function pickFolder(event: Event) {
  const picked = Array.from((event.target as HTMLInputElement).files || [])
    .filter((file) => /\.(xlsx|xls)$/i.test(file.name) && !file.name.startsWith('~$'))
  let classified
  try {
    classified = classifyFolderFiles(picked)
  } catch (error: any) {
    ;(event.target as HTMLInputElement).value = ''
    ElMessage.error(error.message)
    return
  }
  let count = 0

  for (const [role, file] of Object.entries(classified.roles)) {
    files[role] = file.name
    fileData[role] = file
    count += 1
  }
  deductionFiles.value = mergeUniqueFiles(deductionFiles.value, classified.deductionFiles)
  count += classified.deductionFiles.length
  const artifactCount = classified.knownArtifacts.length

  inputVersion.value += 1
  ;(event.target as HTMLInputElement).value = ''
  if (count) {
    const artifactText = artifactCount ? `，另识别 ${artifactCount} 个已生成申报产物（无需上传）` : ''
    ElMessage.success(`已从文件夹识别 ${count} 个可上传文件${artifactText}`)
  } else if (artifactCount) {
    ElMessage.success(`已识别 ${artifactCount} 个已生成申报产物（无需上传），其中包含人员信息采集_员工`)
  } else {
    ElMessage.warning('未识别到可用申报文件')
  }
}

function classifyFolderFiles(fileList: File[]) {
  const roles: Record<string, File> = {}
  const knownArtifacts: File[] = []
  const deductionFiles: File[] = []
  for (const file of fileList) {
    const text = normalizeFileText(file)
    const role = detectFileRole(text)
    if (role === 'salary_role_conflict') throw new Error(`文件名同时包含5位和7位标记，无法判断工资类型：${file.name}`)
    if (role === 'deduction_files') deductionFiles.push(file)
    else if (role === 'personnel_collection' || role === 'updated_staff' || role === 'working_sheet' || role === 'reconciliation_report') knownArtifacts.push(file)
    else if (role) {
      const normalizedRole = ['branch_salary', 'digital_ops_salary', 'advisor_salary'].includes(role) ? 'marketing_salary' : role
      if (roles[normalizedRole]) throw new Error(`检测到多份${normalizedRole === 'marketing_salary' ? '营销' : ''}工资文件，请确认已合并后再上传`)
      roles[normalizedRole] = file
    }
  }
  return { roles, knownArtifacts, deductionFiles }
}

function normalizeFileText(file: File) {
  const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
  return `${relativePath}/${file.name}`.toLowerCase().replace(/\s+/g, '')
}

function compactFileText(text: string) {
  return text.replace(/[_\-—–·.（）()【】\[\]{}、，,：:;；/\\]/g, '')
}

function detectFileRole(text: string) {
  const compact = compactFileText(text)
  if (compact.includes('人员信息采集员工') || compact.includes('人员信息采集表')) return 'personnel_collection'
  if (compact.includes('核对报告')) return 'reconciliation_report'
  if (compact.includes('平台底稿') || compact.includes('核对底稿') || compact.includes('底稿xlsx')) return 'working_sheet'
  if (compact.includes('当月人员信息表') || compact.includes('更新后人员信息表')) return 'updated_staff'
  if (compact.includes('专项附加扣除') || compact.includes('专项扣除')) return 'deduction_files'
  if (compact.includes('人员信息变动表雇员') || compact.includes('变动表雇员')) return 'staff_change'
  if (compact.includes('经纪人') || compact.includes('证券经纪')) return 'broker_salary'
  if (compact.includes('总部代发') || compact.includes('总部工资')) return 'headquarters_salary'
  const rankByName = compact.includes('5位') || compact.includes('五位')
  const marketingByName = compact.includes('7位') || compact.includes('七位')
  if (rankByName && marketingByName) return 'salary_role_conflict'
  if (rankByName) return 'rank_salary'
  if (marketingByName) return 'marketing_salary'
  if (compact.includes('投资顾问') || compact.includes('理财经理') || compact.includes('投顾')) return 'advisor_salary'
  if (compact.includes('机构业务人员') || compact.includes('机构工资')) return 'branch_salary'
  if (compact.includes('数字化运营')) return 'digital_ops_salary'
  if (compact.includes('营销人员') || compact.includes('营销工资')) return 'marketing_salary'
  if (compact.includes('工资横表') || compact.includes('职级工资') || compact.includes('薪资')) return 'rank_salary'
  return ''
}

function fileIdentity(file: File) {
  return `${file.name}-${file.size}-${file.lastModified}`
}

async function runVerify() {
  if (!props.sessionId) {
    ElMessage.error('核对会话未就绪，请重新选择所属期间')
    return
  }
  if (missingRequiredLabels.value.length) {
    ElMessage.warning(`请先补齐：${missingRequiredLabels.value.join('、')}`)
    return
  }

  verifying.value = true
  try {
    const form = new FormData()
    form.append('verification_stage', step.value === 1 ? 'initial' : 'recheck')
    for (const [role, file] of Object.entries(fileData)) {
      if (role === 'staff_change' && step.value !== 2) continue
      form.append(role, file)
    }
    deductionFiles.value.forEach((file) => form.append('deduction_files', file))

    const { data } = await taxApi.verify(props.sessionId, form)
    report.value = data.report
    latestRound.value = data.round_number
    reviewArtifacts.value = data.artifacts || []
    generatedFiles.value = []
    step.value = 2
    if (props.session) emit('session-updated', { ...props.session, status: data.status, current_round: data.round_number + 1 })

    if (data.status === 'ready_to_generate') {
      const totalIssues = data.report.summary.total_issues || 0
      ElMessage.success(totalIssues ? `核对完成，有 ${totalIssues} 项提醒，可继续生成` : '核对完成，全部通过')
    } else {
      ElMessage.warning(`核对完成，发现 ${data.report.summary.total_issues} 项问题`)
    }
  } catch (error: any) {
    step.value = 2
    ElMessage.error('核对失败：' + getErrorMessage(error))
  } finally {
    verifying.value = false
  }
}

function getErrorMessage(error: any) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  if (Array.isArray(detail)) return detail.map((item) => item?.msg || JSON.stringify(item)).join('；')
  return error?.message || '未知错误'
}

function openStaffReimport() {
  staffReimportInput.value?.click()
}

function pickUpdatedStaffChange(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  files.staff_change = file.name
  fileData.staff_change = file
  importedStaffChangeName.value = file.name
  ;(event.target as HTMLInputElement).value = ''
  ElMessage.success(`已选择更新后的雇员表：${file.name}，请点击“重新核对”提交`)
}

async function runGenerate() {
  if (!props.sessionId) return
  generating.value = true
  try {
    const { data } = await taxApi.generate(props.sessionId)
    generatedFiles.value = data.files
    step.value = 3
    ElMessage.success(`申报表生成完成，共 ${data.files.length} 个文件`)
  } catch (error: any) {
    ElMessage.error('生成失败：' + getErrorMessage(error))
  } finally {
    generating.value = false
  }
}

function fileTypeLabel(type?: string) {
  const labels: Record<string, string> = {
    declaration: '个税申报表',
    personnel_collection: '人员信息采集表',
    updated_staff: '更新后人员信息表',
    summary: '汇总/核对表',
    reconciliation_report: '统一核对报告',
    working_sheet: '当月底稿',
    monthly_working_sheet: '当月底稿',
  }
  return labels[type || ''] || '申报产物'
}

// 步骤切换：1 永远可去；2 需已核对过；3 需已生成
function canGoToStep(target: number): boolean {
  if (target === 1) return true
  if (target === 2) return !!report.value
  if (target === 3) return generatedFiles.value.length > 0
  return false
}

function goToStep(target: number) {
  if (!canGoToStep(target)) {
    ElMessage.warning(target === 2 ? '请先完成核对' : '请先生成申报表')
    return
  }
  step.value = target
}

// 批量下载：通过后端打包 zip，浏览器弹出"另存为"对话框让用户选保存路径
async function batchDownload() {
  if (!props.sessionId || !generatedFiles.value.length) return
  batchDownloading.value = true
  batchProgress.value = 0
  try {
    const response = await fetch(`/api/tax/sessions/${props.sessionId}/download-all`, { headers: currentCompanyHeaders() })
    if (!response.ok) throw new Error('下载失败')
    const blob = await response.blob()
    const fileName = `申报文件_${props.sessionId}.zip`
    const savePicker = (window as any).showSaveFilePicker
    if (savePicker) {
      const handle = await savePicker({
        suggestedName: fileName,
        types: [{ description: 'ZIP 压缩包', accept: { 'application/zip': ['.zip'] } }],
      })
      const writable = await handle.createWritable()
      await writable.write(blob)
      await writable.close()
    } else {
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = fileName
      anchor.style.display = 'none'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 3000)
    }
    const total = generatedFiles.value.length
    for (let i = 0; i < total; i++) {
      await new Promise((resolve) => setTimeout(resolve, 150))
      batchProgress.value = i + 1
    }
    ElMessage.success(`已保存 ${total} 个申报文件`)
  } catch (e) {
    ElMessage.error('批量下载失败，请逐个点击下载')
  } finally {
    batchDownloading.value = false
    batchProgress.value = 0
  }
}

async function clearGeneratedOutput() {
  if (!props.sessionId) return
  try {
    await ElMessageBox.confirm(
      '确认清空本次生成的全部申报文件？核对报告和人员主数据会保留。',
      '一键清空',
      { type: 'warning', confirmButtonText: '确认清空' },
    )
    const { data } = await taxApi.clearGeneratedFiles(props.sessionId)
    generatedFiles.value = []
    step.value = 2
    if (props.session) emit('session-updated', { ...props.session, status: data.status })
    ElMessage.success('生成的申报文件已清空')
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('清空失败：' + getErrorMessage(error))
  }
}

function resetAll() {
  clearDisplayedResult()
  importedStaffChangeName.value = ''
  Object.keys(files).forEach((key) => delete files[key])
  Object.keys(fileData).forEach((key) => delete fileData[key])
  deductionFiles.value = []
  inputVersion.value += 1
}
</script>
