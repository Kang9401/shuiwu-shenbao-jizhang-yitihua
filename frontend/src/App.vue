<template>
  <RpaMonitor v-if="isRpaMonitor" />
  <div v-else-if="initializingCompanies" class="company-entry company-entry-loading">
    <el-icon class="company-entry-spinner"><Loading /></el-icon>
    <strong>正在加载分公司</strong>
  </div>
  <div v-else-if="!selectedCompany" class="company-entry">
    <header class="company-entry-header">
      <span class="brand-mark"><el-icon><Tickets /></el-icon></span>
      <div><h1>税务申报核对工作台</h1><p>选择已有分公司，或创建一个新的核算主体。</p></div>
    </header>
    <div class="company-entry-grid">
      <section class="company-entry-list">
        <div class="company-entry-section-title"><strong>选择分公司</strong><span>{{ companies.length }} 个可用主体</span></div>
        <button v-for="company in companies" :key="company.id" class="company-choice" @click="selectCompany(company.id)">
          <span class="company-choice-icon"><el-icon><OfficeBuilding /></el-icon></span>
          <span><strong>{{ company.name }}</strong><small>{{ company.code }} · 使用人：{{ company.operator_name }}</small></span>
          <el-icon><ArrowRight /></el-icon>
        </button>
        <div v-if="!companies.length" class="company-empty">尚未创建分公司，请填写右侧资料创建第一个主体。</div>
      </section>
      <section class="company-create-panel">
        <div class="company-entry-section-title"><strong>新建分公司</strong><span>创建后进入独立工作区</span></div>
        <label>分公司名称<input v-model.trim="companyDraft.name" maxlength="120" placeholder="例如：广州分公司" /></label>
        <label>分公司编码<input v-model.trim="companyDraft.code" maxlength="60" placeholder="例如：17001" /></label>
        <label>使用人<input v-model.trim="companyDraft.operator_name" maxlength="120" placeholder="请输入使用人" /></label>
        <label>补充信息<textarea v-model.trim="companyDraft.notes" maxlength="500" rows="3" placeholder="选填" /></label>
        <el-button type="primary" :loading="savingCompany" @click="saveCompany(true)">创建并进入</el-button>
      </section>
    </div>
  </div>
  <div v-else class="shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">
          <el-icon><Tickets /></el-icon>
        </span>
        <div class="brand-text">
          <strong>税务申报核对</strong>
          <small>工作台</small>
        </div>
      </div>

      <nav v-for="section in navSections" :key="section.label" class="nav-section">
        <div class="nav-label">{{ section.label }}</div>
        <button
          v-for="item in section.items"
          :key="item.key"
          class="nav-item"
          :class="{ active: activeView === item.key }"
          @click="activeView = item.key"
        >
          <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
          <small v-if="item.planned" class="nav-badge">筹备中</small>
        </button>
      </nav>
    </aside>

    <main class="main-container">
      <header class="topbar">
        <div class="topbar-left">
          <span class="page-kicker">{{ activeMeta.kicker }}</span>
          <h1>{{ activeMeta.title }}</h1>
          <p>{{ activeMeta.description }}</p>
        </div>
        <div class="topbar-right">
          <div class="company-control">
            <span>当前分公司</span>
            <div class="company-picker-actions">
              <select :value="selectedCompany.id" class="period-native-select" aria-label="当前分公司" @change="switchCompany">
                <option v-for="company in companies" :key="company.id" :value="company.id">{{ company.name }}（{{ company.code }}）</option>
              </select>
              <el-tooltip content="管理分公司" placement="bottom">
                <button class="period-add-button" type="button" aria-label="管理分公司" @click="openCompanyManager"><el-icon><Setting /></el-icon></button>
              </el-tooltip>
            </div>
          </div>
          <div v-if="activeView === 'personnel_masters'" class="period-control period-control-editable">
            <span>所属期间</span>
            <div class="period-picker-actions">
              <select v-model.number="selectedPeriodId" class="period-native-select" aria-label="所属期间">
                <option v-for="period in periods" :key="period.id" :value="period.id">
                  {{ period.year }}年{{ String(period.month).padStart(2, '0') }}月
                </option>
              </select>
              <el-tooltip content="新增所属期间" placement="bottom">
                <button class="period-add-button" type="button" aria-label="新增所属期间" @click="openPeriodDialog">
                  <el-icon><Plus /></el-icon>
                </button>
              </el-tooltip>
            </div>
          </div>
          <div v-else class="period-control period-display">
            <span>所属期间</span>
            <strong>{{ selectedPeriodLabel }}</strong>
          </div>
        </div>
      </header>

      <section class="content">
        <template v-if="activeView === 'tax_declaration'">
          <div v-if="!sessionId" class="diagnostic-card">
            <div>
              <strong>核对会话未就绪</strong>
              <p>请选择所属期间，或检查后端服务是否正常。</p>
            </div>
            <span class="tag tag-danger">不可核对</span>
          </div>
          <TaxDeclaration
            v-else
            :session="session"
            :session-id="sessionId"
            @session-updated="session = $event"
            @open-rpa="activeView = 'etax_rpa'"
          />
        </template>

        <PersonnelMasters
          v-else-if="activeView === 'personnel_masters'"
          :period-id="selectedPeriodId"
        />

        <ReconciliationImports
          v-else-if="activeView === 'reconciliation_imports'"
          :period-id="selectedPeriodId"
        />

        <EtaxRpa
          v-else-if="activeView === 'etax_rpa'"
          :period-id="selectedPeriodId"
          :initial-month="selectedPeriodMonth"
        />

        <TaskCenter
          v-else-if="activeView === 'task_center'"
          :period-id="selectedPeriodId"
          :period-label="selectedPeriodLabel"
        />

        <SystemMaintenance v-else-if="activeView === 'system_maintenance'" />

        <FinanceSkill
          v-else-if="activeView === 'finance_skill'"
          :period-label="selectedPeriodLabel"
        />

        <GenericWorkflow
          v-else-if="activeWorkflow"
          :workflow="activeWorkflow"
          :period-id="selectedPeriodId"
        />

        <section v-else class="card workflow-card placeholder-card">
          <div class="card-header">
            <strong>{{ activeMeta.title }}</strong>
            <span class="tag tag-warning">规划中</span>
          </div>
          <div class="card-body">
            <p>{{ activeMeta.description }}</p>
            <p>该模块已按附件纳入工作台导航，后续会分阶段接入自动下载、结果导入、差异底稿和风险提示。</p>
          </div>
        </section>
      </section>
    </main>

    <el-dialog
      v-model="periodDialogVisible"
      title="新增所属期间"
      width="420px"
      :close-on-click-modal="!creatingPeriod"
      :close-on-press-escape="!creatingPeriod"
    >
      <div class="period-create-form">
        <label for="new-period-month">所属月份</label>
        <el-date-picker
          id="new-period-month"
          v-model="newPeriodMonth"
          class="period-month-picker"
          type="month"
          format="YYYY年MM月"
          value-format="YYYY-MM"
          :clearable="false"
          :disabled="creatingPeriod"
          placeholder="选择月份"
        />
      </div>
      <template #footer>
        <el-button :disabled="creatingPeriod" @click="periodDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creatingPeriod" @click="createPeriod">新增</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="companyManagerVisible" title="分公司管理" width="760px">
      <div class="company-manager-toolbar"><span>停用后不会出现在日常选择列表中，历史数据仍会保留。</span><el-button type="primary" @click="openCompanyEditor()"><el-icon><Plus /></el-icon>新建分公司</el-button></div>
      <el-table :data="allCompanies" size="small" max-height="420">
        <el-table-column prop="name" label="分公司" min-width="150" />
        <el-table-column prop="code" label="编码" width="110" />
        <el-table-column prop="operator_name" label="使用人" width="120" />
        <el-table-column label="状态" width="80"><template #default="{ row }"><span class="tag" :class="row.active ? 'tag-success' : 'tag-info'">{{ row.active ? '启用' : '停用' }}</span></template></el-table-column>
        <el-table-column label="操作" width="180"><template #default="{ row }"><el-button link type="primary" @click="openCompanyEditor(row)">编辑</el-button><el-button link :type="row.active ? 'danger' : 'success'" @click="toggleCompany(row)">{{ row.active ? '停用' : '启用' }}</el-button></template></el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="companyEditorVisible" :title="editingCompanyId ? '编辑分公司' : '新建分公司'" width="480px">
      <div class="company-editor-form">
        <label>分公司名称<input v-model.trim="companyDraft.name" maxlength="120" /></label>
        <label>分公司编码<input v-model.trim="companyDraft.code" maxlength="60" /></label>
        <label>使用人<input v-model.trim="companyDraft.operator_name" maxlength="120" /></label>
        <label>补充信息<textarea v-model.trim="companyDraft.notes" maxlength="500" rows="3" /></label>
      </div>
      <template #footer><el-button @click="companyEditorVisible = false">取消</el-button><el-button type="primary" :loading="savingCompany" @click="saveCompany(false)">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ArrowRight,
  ChatDotRound,
  CircleCheck,
  Clock,
  Coin,
  DocumentChecked,
  Files,
  Loading,
  Memo,
  Monitor,
  OfficeBuilding,
  Plus,
  Setting,
  Tickets,
  TrendCharts,
  User,
  Wallet,
} from '@element-plus/icons-vue'
import TaxDeclaration from './views/TaxDeclaration.vue'
import GenericWorkflow from './views/GenericWorkflow.vue'
import EtaxRpa from './views/EtaxRpa.vue'
import PersonnelMasters from './views/PersonnelMasters.vue'
import ReconciliationImports from './views/ReconciliationImports.vue'
import SystemMaintenance from './views/SystemMaintenance.vue'
import FinanceSkill from './views/FinanceSkill.vue'
import TaskCenter from './views/TaskCenter.vue'
import RpaMonitor from './views/RpaMonitor.vue'
import { api, COMPANY_STORAGE_KEY, companyApi, taxApi, workflowApi, type Company, type Period, type TaxSession, type Workflow } from './api'

type ViewKey =
  | 'work_guide'
  | 'task_center'
  | 'system_maintenance'
  | 'finance_skill'
  | 'personnel_masters'
  | 'tax_declaration'
  | 'etax_rpa'
  | 'annual_bonus_tax'
  | 'broker_tax'
  | 'intern_tax'
  | 'restricted_stock_interest_tax'
  | 'reconciliation_imports'
  | 'vat_deduction'
  | 'invoice_booking'
  | 'voucher_draft'
  | 'risk_monitor'
  | 'policy_learning'

type NavItem = {
  key: ViewKey
  label: string
  icon: any
  workflowCode?: string
  kicker: string
  description: string
  planned?: boolean
}

const navSections: { label: string; items: NavItem[] }[] = [
  {
    label: '工作清单',
    items: [
      { key: 'work_guide', label: '操作指引', icon: Memo, kicker: 'Work guide', description: '税务岗每月工作清单和操作指引。', planned: true },
      { key: 'task_center', label: '运行记录', icon: Clock, kicker: 'Task history', description: '查看当前所属期间各申报流程的运行状态和版本。' },
      { key: 'system_maintenance', label: '系统维护', icon: Setting, kicker: 'System', description: '程序版本、数据备份、恢复和诊断。' },
    ],
  },
  {
    label: '个人所得税申报',
    items: [
      { key: 'personnel_masters', label: '人员主数据', icon: User, kicker: 'Personnel master', description: '员工、经纪人人员主数据初始化与导出。' },
      { key: 'tax_declaration', label: '工资薪金申报', icon: DocumentChecked, kicker: 'Individual income tax', description: '工资资料上传、差异核对、人员确认与申报表生成。' },
      { key: 'etax_rpa', label: '个税 RPA', icon: Monitor, kicker: 'Etax automation', description: '自然人电子税务局批量自动化。' },
      { key: 'annual_bonus_tax', label: '年终奖申报', icon: Wallet, workflowCode: 'annual_bonus_tax', kicker: 'Annual bonus', description: '全年一次性奖金个税申报数据处理。' },
      { key: 'broker_tax', label: '经纪人申报', icon: TrendCharts, workflowCode: 'broker_tax', kicker: 'Broker tax', description: '证券经纪人佣金收入个税申报。' },
      { key: 'intern_tax', label: '实习生申报', icon: User, workflowCode: 'intern_tax', kicker: 'Intern tax', description: '实习生补贴个税申报与人员采集。' },
      { key: 'restricted_stock_interest_tax', label: '限售股/利息税', icon: Coin, workflowCode: 'restricted_stock_interest_tax', kicker: 'Restricted stock', description: '限售股、债券利息及客户类个人所得申报。' },
      { key: 'reconciliation_imports', label: '核对数据导入', icon: Files, kicker: 'Reconciliation imports', description: '银行流水、申报结果和账务数据结构化入库。' },
    ],
  },
  {
    label: '智能能力',
    items: [
      { key: 'finance_skill', label: '财务 SKILL', icon: ChatDotRound, kicker: 'Finance AI', description: '面向财务分析、会计处理、税务判断与风险复核的大模型助手。' },
    ],
  },
  {
    label: '进项税与发票',
    items: [
      { key: 'vat_deduction', label: '进项税勾选认证', icon: CircleCheck, workflowCode: 'vat_deduction', kicker: 'VAT deduction', description: '未勾选专票、入账专票、拟勾选数据与勾选核对底稿。' },
      { key: 'invoice_booking', label: '发票记账标志', icon: Files, workflowCode: 'invoice_booking', kicker: 'Invoice marking', description: '普通发票入账记录、拟标记文件和标记结果差异底稿。' },
    ],
  },
  {
    label: '凭证与风险',
    items: [
      { key: 'voucher_draft', label: '凭证制作', icon: Memo, workflowCode: 'voucher_draft', kicker: 'Voucher draft', description: '依据完税证明、银行流水和账务数据生成凭证模板。' },
      { key: 'risk_monitor', label: '逻辑与风险监控', icon: TrendCharts, kicker: 'Risk monitor', description: '涉税科目发生额、余额和发票风险监控。', planned: true },
      { key: 'policy_learning', label: '政策查询与学习', icon: Tickets, kicker: 'Policy learning', description: '政策文件和 12366 问答抓取、学习与查询。', planned: true },
    ],
  },
]

const periods = ref<Period[]>([])
const isRpaMonitor = new URLSearchParams(window.location.search).get('window') === 'rpa-monitor'
const workflows = ref<Workflow[]>([])
const selectedPeriodId = ref<number | null>(null)
const session = ref<TaxSession | null>(null)
const activeView = ref<ViewKey>('tax_declaration')
const periodDialogVisible = ref(false)
const newPeriodMonth = ref('')
const creatingPeriod = ref(false)
const companies = ref<Company[]>([])
const allCompanies = ref<Company[]>([])
const selectedCompany = ref<Company | null>(null)
const initializingCompanies = ref(!isRpaMonitor)
const companyManagerVisible = ref(false)
const companyEditorVisible = ref(false)
const editingCompanyId = ref<number | null>(null)
const savingCompany = ref(false)
const emptyCompanyDraft = () => ({ name: '', code: '', operator_name: '', notes: '' })
const companyDraft = reactive(emptyCompanyDraft())

const flatItems = computed(() => navSections.flatMap((section) => section.items))
const activeItem = computed(() => flatItems.value.find((item) => item.key === activeView.value) || flatItems.value[0])
const sessionId = computed(() => session.value?.id)
const selectedPeriodLabel = computed(() => {
  const period = periods.value.find((item) => item.id === selectedPeriodId.value)
  return period ? `${period.year}年${String(period.month).padStart(2, '0')}月` : '未选择'
})
const selectedPeriodMonth = computed(() => {
  const period = periods.value.find((item) => item.id === selectedPeriodId.value)
  if (period) return `${period.year}-${String(period.month).padStart(2, '0')}`
  const date = new Date()
  date.setMonth(date.getMonth() - 1)
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
})

const activeWorkflow = computed(() => {
  const code = activeItem.value.workflowCode
  if (!code) return null
  return workflows.value.find((workflow) => workflow.code === code) || null
})

const activeMeta = computed(() => ({
  kicker: activeItem.value.kicker,
  title: activeItem.value.label,
  description: activeWorkflow.value?.description || activeItem.value.description,
}))

onMounted(async () => {
  if (isRpaMonitor) return
  await loadCompanies()
  const storedId = Number(window.localStorage.getItem(COMPANY_STORAGE_KEY))
  if (companies.value.some((item) => item.id === storedId)) await selectCompany(storedId, false)
  initializingCompanies.value = false
})

watch(selectedPeriodId, async (periodId) => {
  if (periodId) await createSession(periodId)
})

async function loadPeriods() {
  try {
    const { data } = await api.get<Period[]>('/periods')
    periods.value = data
    if (selectedPeriodId.value) return

    const today = new Date()
    const targetDate = new Date(today.getFullYear(), today.getMonth() - 1, 1)
    const targetYear = targetDate.getFullYear()
    const targetMonth = targetDate.getMonth() + 1
    let target = data.find((item) => item.year === targetYear && item.month === targetMonth)
    if (!target) {
      try {
        const { data: created } = await api.post<Period>('/periods', { year: targetYear, month: targetMonth })
        periods.value = [created, ...data]
        target = created
      } catch (error: any) {
        if (error?.response?.status !== 409) throw error
        const { data: refreshed } = await api.get<Period[]>('/periods')
        periods.value = refreshed
        target = refreshed.find((item) => item.year === targetYear && item.month === targetMonth)
      }
    }
    if (target) selectedPeriodId.value = target.id
  } catch (error) {
    ElMessage.error('所属期间加载失败，请检查后端服务')
  }
}

async function loadCompanies(includeInactive = false) {
  try {
    const { data } = await companyApi.list(includeInactive)
    if (includeInactive) allCompanies.value = data
    else companies.value = data
  } catch (error) {
    ElMessage.error('分公司加载失败，请检查后端服务')
  }
}

async function selectCompany(companyId: number, notify = true) {
  try {
    const { data } = await companyApi.select(companyId)
    window.localStorage.setItem(COMPANY_STORAGE_KEY, String(companyId))
    selectedCompany.value = data
    periods.value = []
    selectedPeriodId.value = null
    session.value = null
    await Promise.all([loadPeriods(), loadWorkflows()])
    if (notify) ElMessage.success(`已切换到${data.name}`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '分公司切换失败')
  }
}

async function switchCompany(event: Event) {
  const companyId = Number((event.target as HTMLSelectElement).value)
  if (companyId !== selectedCompany.value?.id) await selectCompany(companyId)
}

function resetCompanyDraft() {
  Object.assign(companyDraft, emptyCompanyDraft())
  editingCompanyId.value = null
}

async function openCompanyManager() {
  await loadCompanies(true)
  companyManagerVisible.value = true
}

function openCompanyEditor(company?: Company) {
  resetCompanyDraft()
  if (company) {
    editingCompanyId.value = company.id
    Object.assign(companyDraft, { name: company.name, code: company.code, operator_name: company.operator_name, notes: company.notes })
  }
  companyEditorVisible.value = true
}

async function saveCompany(enterAfterCreate: boolean) {
  if (!companyDraft.name || !companyDraft.code || !companyDraft.operator_name) {
    ElMessage.warning('请填写分公司名称、编码和使用人')
    return
  }
  savingCompany.value = true
  try {
    const response = editingCompanyId.value
      ? await companyApi.update(editingCompanyId.value, companyDraft)
      : await companyApi.create(companyDraft)
    companyEditorVisible.value = false
    resetCompanyDraft()
    await Promise.all([loadCompanies(), loadCompanies(true)])
    if (selectedCompany.value?.id === response.data.id) selectedCompany.value = response.data
    if (enterAfterCreate || !selectedCompany.value) await selectCompany(response.data.id)
    else ElMessage.success('分公司资料已保存')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '分公司保存失败')
  } finally {
    savingCompany.value = false
  }
}

async function toggleCompany(company: Company) {
  try {
    await companyApi.updateStatus(company.id, !company.active)
    await Promise.all([loadCompanies(), loadCompanies(true)])
    if (company.active && selectedCompany.value?.id === company.id) {
      const replacement = companies.value[0]
      if (replacement) await selectCompany(replacement.id)
    }
    ElMessage.success(company.active ? '分公司已停用' : '分公司已启用')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '状态更新失败')
  }
}

function sortPeriods(items: Period[]) {
  return [...items].sort((left, right) => right.year - left.year || right.month - left.month)
}

function openPeriodDialog() {
  const latest = sortPeriods(periods.value)[0]
  const nextDate = latest
    ? new Date(latest.year, latest.month, 1)
    : new Date(new Date().getFullYear(), new Date().getMonth() - 1, 1)
  newPeriodMonth.value = `${nextDate.getFullYear()}-${String(nextDate.getMonth() + 1).padStart(2, '0')}`
  periodDialogVisible.value = true
}

async function createPeriod() {
  const match = /^(\d{4})-(\d{2})$/.exec(newPeriodMonth.value)
  if (!match) {
    ElMessage.warning('请选择所属月份')
    return
  }

  const year = Number(match[1])
  const month = Number(match[2])
  creatingPeriod.value = true
  try {
    const { data: created } = await api.post<Period>('/periods', { year, month })
    periods.value = sortPeriods([...periods.value, created])
    selectedPeriodId.value = created.id
    periodDialogVisible.value = false
    ElMessage.success(`已新增${created.name}`)
  } catch (error: any) {
    if (error?.response?.status === 409) {
      const { data } = await api.get<Period[]>('/periods')
      periods.value = sortPeriods(data)
      const existing = periods.value.find((item) => item.year === year && item.month === month)
      if (existing) selectedPeriodId.value = existing.id
      periodDialogVisible.value = false
      ElMessage.info('该所属期间已存在，已切换到对应期间')
    } else {
      ElMessage.error(error?.response?.data?.detail || '所属期间新增失败')
    }
  } finally {
    creatingPeriod.value = false
  }
}

async function loadWorkflows() {
  try {
    const { data } = await workflowApi.list()
    workflows.value = data
  } catch (error) {
    workflows.value = []
    ElMessage.warning('流程列表加载失败，已显示可用模块导航')
  }
}

async function createSession(periodId: number) {
  try {
    const { data } = await taxApi.createSession(periodId)
    session.value = data
  } catch (error) {
    session.value = null
    ElMessage.error('个税核对会话创建失败，请检查后端服务')
  }
}

</script>
