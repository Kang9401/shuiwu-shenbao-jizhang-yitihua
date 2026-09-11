<template>
  <div class="guide-page">
    <section class="guide-overview">
      <div class="guide-overview-copy">
        <span class="guide-kicker">MONTHLY WORK GUIDE</span>
        <h2>本期操作指引</h2>
        <p>按顺序完成申报、RPA 上传和底稿核对。系统会自动识别已完成的步骤，人工确认项可自行标记。</p>
        <span class="guide-period">当前所属期：{{ periodLabel }}</span>
      </div>
      <div class="guide-progress-box">
        <div class="guide-progress-number"><strong>{{ doneCount }}</strong><span>/ {{ totalCount }} 步</span></div>
        <div class="guide-progress-track"><span :style="{ width: `${progressPercent}%` }" /></div>
        <small>{{ remainingCount ? `还有 ${remainingCount} 步待完成` : '本期清单已完成' }}</small>
      </div>
      <button class="btn btn-outline guide-refresh" :disabled="loading" @click="loadStatus">
        <el-icon><Refresh /></el-icon>{{ loading ? '刷新中' : '刷新状态' }}
      </button>
    </section>

    <div v-if="!periodId" class="guide-empty">请先选择所属期间，系统才能显示本期完成状态。</div>

    <div class="guide-section-grid">
      <section v-for="section in sections" :key="section.id" class="guide-section">
        <header class="guide-section-header">
          <div class="guide-section-title">
            <span class="guide-section-icon"><el-icon><component :is="section.icon" /></el-icon></span>
            <div><h3>{{ section.title }}</h3><p>{{ section.description }}</p></div>
          </div>
          <span class="guide-section-count">{{ sectionDoneCount(section) }}/{{ section.items.length }}</span>
        </header>

        <div class="guide-items">
          <article v-for="item in section.items" :key="item.id" class="guide-item" :class="{ done: itemDone(item) }">
            <button class="guide-check" type="button" :aria-label="itemDone(item) ? `取消标记${item.title}` : `标记${item.title}已完成`" @click="toggleItem(item)">
              <el-icon v-if="itemDone(item)"><CircleCheckFilled /></el-icon>
              <span v-else />
            </button>
            <div class="guide-item-copy">
              <strong>{{ item.title }}</strong>
              <p>{{ item.description }}</p>
              <small v-if="item.auto && autoDone[item.auto]">系统已识别完成</small>
              <small v-else-if="manualDone[item.id]">已由我标记完成</small>
            </div>
            <span class="guide-item-status" :class="itemDone(item) ? 'is-done' : 'is-pending'">{{ itemDone(item) ? '已完成' : '待完成' }}</span>
            <button class="guide-go" type="button" :title="`进入${item.title}`" @click="navigate(item.view)"><el-icon><ArrowRight /></el-icon></button>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight, CircleCheckFilled, Collection, DocumentChecked, Monitor, Refresh, Setting } from '@element-plus/icons-vue'
import { organizationMappingApi, pitReconciliationApi, reconciliationImportApi, rpaApi, systemApi, taxApi, workflowApi, type Job, type PitOverviewResponse, type RpaStatus, type TaxSession } from '../api'

type GuideView = 'tax_declaration' | 'etax_rpa' | 'reconciliation_imports' | 'pit_reconciliation' | 'personnel_masters' | 'system_maintenance'
type AutoKey = 'tax_upload' | 'tax_verify' | 'tax_generate' | 'rpa_config' | 'rpa_prepare' | 'rpa_run' | 'rpa_output' | 'pit_import' | 'pit_calculate' | 'system_company' | 'system_period'
type GuideItem = { id: string; title: string; description: string; view: GuideView; auto?: AutoKey }
type GuideSection = { id: string; title: string; description: string; icon: any; items: GuideItem[] }

const props = defineProps<{ companyId: number | null; periodId: number | null; periodLabel: string }>()
const emit = defineEmits<{ navigate: [view: GuideView] }>()
const loading = ref(false)
const manualDone = ref<Record<string, boolean>>({})
const autoDone = reactive<Record<AutoKey, boolean>>({
  tax_upload: false, tax_verify: false, tax_generate: false,
  rpa_config: false, rpa_prepare: false, rpa_run: false, rpa_output: false,
  pit_import: false, pit_calculate: false, system_company: false, system_period: false,
})

const sections: GuideSection[] = [
  {
    id: 'pit', title: '个税申报', description: '完成本期工资资料核对和申报文件生成。', icon: DocumentChecked,
    items: [
      { id: 'tax-upload', title: '上传本期工资资料', description: '上传工资单及需要参与核对的人员资料。', view: 'tax_declaration', auto: 'tax_upload' },
      { id: 'tax-verify', title: '完成核对并处理人员变动', description: '查看核对结果，补录缺失信息并确认人员变动。', view: 'tax_declaration', auto: 'tax_verify' },
      { id: 'tax-generate', title: '生成个税申报文件', description: '确认无阻断问题后生成本期申报文件。', view: 'tax_declaration', auto: 'tax_generate' },
    ],
  },
  {
    id: 'rpa', title: 'RPA 上传', description: '将申报文件上传到自然人电子税务局并检查结果。', icon: Monitor,
    items: [
      { id: 'rpa-config', title: '检查 RPA 环境配置', description: '确认 Chrome、INPUT 和 OUTPUT 路径可用。', view: 'etax_rpa', auto: 'rpa_config' },
      { id: 'rpa-prepare', title: '准备本期上传文件', description: '将已生成的申报文件放入 RPA 的 INPUT 文件夹。', view: 'etax_rpa', auto: 'rpa_prepare' },
      { id: 'rpa-run', title: '执行预申报任务', description: '初始化浏览器后按机构执行本期预申报。', view: 'etax_rpa', auto: 'rpa_run' },
      { id: 'rpa-output', title: '检查并下载处理结果', description: '确认结果文件和失败提示，保留必要的输出文件。', view: 'etax_rpa', auto: 'rpa_output' },
    ],
  },
  {
    id: 'workpaper', title: '底稿核对', description: '导入来源数据，计算并复核个税核对底稿。', icon: Collection,
    items: [
      { id: 'pit-import', title: '导入底稿来源数据', description: '导入银行流水、个税申报 Excel、余额表和完税证明。', view: 'reconciliation_imports', auto: 'pit_import' },
      { id: 'pit-calculate', title: '计算本期核对底稿', description: '确认来源数据齐全后重新计算底稿。', view: 'pit_reconciliation', auto: 'pit_calculate' },
      { id: 'pit-review', title: '复核差异并完成处理', description: '逐项查看差异，填写原因或备注后确认完成。', view: 'pit_reconciliation' },
    ],
  },
  {
    id: 'system', title: '系统设置', description: '首次使用或新增期间时完成基础配置。', icon: Setting,
    items: [
      { id: 'system-company', title: '维护分公司和银行账号', description: '确认分公司、机构名称及银行账号信息准确。', view: 'system_maintenance', auto: 'system_company' },
      { id: 'system-personnel', title: '准备人员主数据', description: '导入或维护本期员工、实习生、经纪人等人员信息。', view: 'personnel_masters' },
      { id: 'system-period', title: '确认所属期间', description: '选择当前申报月份，所有数据将按期间隔离保存。', view: 'system_maintenance', auto: 'system_period' },
      { id: 'system-backup', title: '完成本期备份', description: '重要操作前在系统维护中创建一份数据备份。', view: 'system_maintenance' },
    ],
  },
]

const allItems = computed(() => sections.flatMap((section) => section.items))
const doneCount = computed(() => allItems.value.filter(itemDone).length)
const totalCount = computed(() => allItems.value.length)
const remainingCount = computed(() => totalCount.value - doneCount.value)
const progressPercent = computed(() => totalCount.value ? Math.round((doneCount.value / totalCount.value) * 100) : 0)

onMounted(loadStatus)
watch(() => [props.companyId, props.periodId], loadStatus)

function storageKey() { return `tax-workbench-guide:${props.companyId || 'none'}:${props.periodId || 'none'}` }

function loadManualState() {
  try { manualDone.value = JSON.parse(window.localStorage.getItem(storageKey()) || '{}') } catch { manualDone.value = {} }
}

function persistManualState() { window.localStorage.setItem(storageKey(), JSON.stringify(manualDone.value)) }

function itemDone(item: GuideItem) { return Boolean((item.auto && autoDone[item.auto]) || manualDone.value[item.id]) }
function sectionDoneCount(section: GuideSection) { return section.items.filter(itemDone).length }
function toggleItem(item: GuideItem) {
  if (item.auto && autoDone[item.auto]) {
    ElMessage.info('该步骤已由系统识别完成')
    return
  }
  manualDone.value[item.id] = !manualDone.value[item.id]
  persistManualState()
}
function navigate(view: GuideView) { emit('navigate', view) }

async function loadStatus() {
  loadManualState()
  Object.keys(autoDone).forEach((key) => { autoDone[key as AutoKey] = false })
  if (!props.periodId) return
  loading.value = true
  try {
    const results = await Promise.allSettled([
      taxApi.listSessions(props.periodId),
      workflowApi.listJobs(props.periodId),
      rpaApi.getStatus(),
      rpaApi.listFiles(),
      reconciliationImportApi.list(props.periodId),
      pitReconciliationApi.getOverview(props.periodId),
      organizationMappingApi.list(),
      systemApi.info(),
    ])
    const data = <T>(index: number): T | null => results[index].status === 'fulfilled' ? (results[index] as PromiseFulfilledResult<any>).value.data : null
    const sessions = data<TaxSession[]>(0) || []
    const session = sessions[0]
    const sessionStatus = session?.status || ''
    autoDone.tax_upload = ['verifying', 'needs_review', 'ready_to_generate', 'generating', 'done'].includes(sessionStatus)
    autoDone.tax_verify = ['needs_review', 'ready_to_generate', 'generating', 'done'].includes(sessionStatus)
    autoDone.tax_generate = sessionStatus === 'done'

    const rpa = data<RpaStatus>(2)
    const rpaFiles = data<Array<{ name: string }>>(3) || []
    autoDone.rpa_config = Boolean(rpa?.config?.chrome_path && rpa.config.input_path && rpa.config.output_path)
    autoDone.rpa_prepare = Boolean(rpa?.import_files?.length)
    autoDone.rpa_run = rpa?.current_run?.period_id === props.periodId && rpa.current_run.status === 'succeeded'
    autoDone.rpa_output = rpaFiles.length > 0

    const imports = data<Array<{ row_count: number }>>(4) || []
    const overview = data<PitOverviewResponse>(5)
    autoDone.pit_import = imports.some((batch) => batch.row_count > 0)
    autoDone.pit_calculate = overview?.exists === true && overview.workpaper?.calculation_status === 'success'

    const mappings = data<Array<{ active: boolean }>>(6) || []
    autoDone.system_company = mappings.some((mapping) => mapping.active !== false)
    autoDone.system_period = Boolean(props.periodId)
  } catch {
    ElMessage.warning('部分步骤状态暂时无法读取，可稍后刷新')
  } finally {
    loading.value = false
  }
}
</script>
