<template>
  <div class="shell">
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

        <TaskCenter
          v-else-if="activeView === 'task_center'"
          :period-id="selectedPeriodId"
          :period-label="selectedPeriodLabel"
        />

        <SystemMaintenance v-else-if="activeView === 'system_maintenance'" />

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
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CircleCheck,
  Clock,
  Coin,
  DocumentChecked,
  Files,
  Memo,
  Plus,
  Setting,
  Tickets,
  TrendCharts,
  User,
  Wallet,
} from '@element-plus/icons-vue'
import TaxDeclaration from './views/TaxDeclaration.vue'
import GenericWorkflow from './views/GenericWorkflow.vue'
import PersonnelMasters from './views/PersonnelMasters.vue'
import ReconciliationImports from './views/ReconciliationImports.vue'
import SystemMaintenance from './views/SystemMaintenance.vue'
import TaskCenter from './views/TaskCenter.vue'
import { api, taxApi, workflowApi, type Period, type TaxSession, type Workflow } from './api'

type ViewKey =
  | 'work_guide'
  | 'task_center'
  | 'system_maintenance'
  | 'deduction_download'
  | 'personnel_masters'
  | 'tax_declaration'
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
      { key: 'annual_bonus_tax', label: '年终奖申报', icon: Wallet, workflowCode: 'annual_bonus_tax', kicker: 'Annual bonus', description: '全年一次性奖金个税申报数据处理。' },
      { key: 'broker_tax', label: '经纪人申报', icon: TrendCharts, workflowCode: 'broker_tax', kicker: 'Broker tax', description: '证券经纪人佣金收入个税申报。' },
      { key: 'intern_tax', label: '实习生申报', icon: User, workflowCode: 'intern_tax', kicker: 'Intern tax', description: '实习生补贴个税申报与人员采集。' },
      { key: 'restricted_stock_interest_tax', label: '限售股/利息税', icon: Coin, workflowCode: 'restricted_stock_interest_tax', kicker: 'Restricted stock', description: '限售股、债券利息及客户类个人所得申报。' },
      { key: 'reconciliation_imports', label: '核对数据导入', icon: Files, kicker: 'Reconciliation imports', description: '银行流水、申报结果和账务数据结构化入库。' },
    ],
  },
  {
    label: '专项附加扣除',
    items: [
      { key: 'deduction_download', label: '专项附加扣除', icon: CircleCheck, kicker: 'Special deductions', description: '专项附加扣除下载、合并和重复员工提示。', planned: true },
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
const workflows = ref<Workflow[]>([])
const selectedPeriodId = ref<number | null>(null)
const session = ref<TaxSession | null>(null)
const activeView = ref<ViewKey>('tax_declaration')
const periodDialogVisible = ref(false)
const newPeriodMonth = ref('')
const creatingPeriod = ref(false)

const flatItems = computed(() => navSections.flatMap((section) => section.items))
const activeItem = computed(() => flatItems.value.find((item) => item.key === activeView.value) || flatItems.value[0])
const sessionId = computed(() => session.value?.id)
const selectedPeriodLabel = computed(() => {
  const period = periods.value.find((item) => item.id === selectedPeriodId.value)
  return period ? `${period.year}年${String(period.month).padStart(2, '0')}月` : '未选择'
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
  await Promise.all([loadPeriods(), loadWorkflows()])
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
