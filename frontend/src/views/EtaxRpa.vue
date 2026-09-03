<template>
  <section class="rpa-page">
    <div class="rpa-heading">
      <div>
        <h2>自然人电子税务局自动化工具</h2>
        <p>当前浏览器状态：<span :class="['rpa-state', `is-${status?.chrome.status || 'stopped'}`]">{{ chromeLabel }}</span></p>
      </div>
      <div class="rpa-heading-actions">
        <el-button :icon="Setting" @click="openPopupDrawer">弹窗规则详情</el-button>
        <el-button :icon="Refresh" :loading="loading" circle title="刷新" @click="refreshAll" />
      </div>
    </div>

    <div class="rpa-layout">
      <div class="rpa-left">
        <section class="rpa-panel">
          <h3>操作参数</h3>
          <div class="rpa-form">
            <label>申报月份</label>
            <div class="rpa-file-row"><el-date-picker v-model="month" type="month" value-format="YYYY-MM" format="YYYY-MM" :clearable="false" :disabled="running" @change="monthManuallyOverridden = true" /><el-button :disabled="running || !monthManuallyOverridden" @click="restoreMonth">恢复同步</el-button></div>
            <label>申报机构</label>
            <el-select v-model="selectedOrgCodes" multiple filterable collapse-tags collapse-tags-tooltip clearable :disabled="running || allOrgs" placeholder="不选择表示全部机构"><el-option v-for="org in organizations" :key="org.code" :label="[org.code, org.name, org.parent_branch].filter(Boolean).join('｜')" :value="org.code" /></el-select>
            <label>处理全部</label>
            <el-radio-group v-model="allOrgs" :disabled="running"><el-radio :value="true">是</el-radio><el-radio :value="false">否</el-radio></el-radio-group>
            <label>已选机构</label><span>{{ allOrgs ? `全部 ${organizations.length} 个` : `${selectedOrgCodes.length} 个` }}</span>
            <label>Chrome地址</label>
            <el-input v-model="chromePath" :disabled="running" @change="saveChromePath" />
            <label>INPUT路径</label>
            <div class="rpa-file-row"><el-input v-model="inputPath" :disabled="running" @change="savePaths" /><el-button :disabled="running" @click="chooseDirectory('input')">选择</el-button></div>
            <label>OUTPUT路径</label>
            <div class="rpa-file-row"><el-input v-model="outputPath" :disabled="running" @change="savePaths" /><el-button :disabled="running" @click="chooseDirectory('output')">选择</el-button></div>
          </div>
          <p class="rpa-hint">如果浏览器初始化失败，请粘贴本机 chrome.exe 的完整路径，重新初始化。</p>
        </section>

        <section class="rpa-panel rpa-steps">
          <h3>执行任务</h3>
          <div v-for="item in steps" :key="item.key" class="rpa-step">
            <span class="rpa-step-no">{{ item.step }}</span>
            <div><strong>{{ item.title }}</strong><p>{{ item.description }}</p></div>
            <el-button v-if="item.key === 'chrome'" type="primary" :disabled="running" @click="initializeChrome">初始化</el-button>
            <el-button v-else type="primary" :disabled="running" @click="confirmTask(item.key as RpaTaskKey)">开始</el-button>
          </div>
          <div class="rpa-input-actions">
            <el-button :icon="DocumentAdd" :disabled="running || !periodId" @click="preparePeriodFiles(false)">从本期已生成文件准备 input</el-button>
            <el-button :icon="Upload" :disabled="running" @click="importInput?.click()">选择导入文件</el-button>
            <el-button :icon="Delete" type="danger" plain :disabled="running || !status?.import_files.length" @click="clearImports">一键清空</el-button>
            <input ref="importInput" class="hidden-file-input" type="file" accept=".xls,.xlsx" multiple @change="uploadImports" />
          </div>
          <div v-if="status?.import_files.length" class="rpa-file-list">
            <span v-for="file in status.import_files" :key="file.name">{{ file.name }}<button title="删除" :disabled="running" @click="removeImport(file.name)">×</button></span>
          </div>
        </section>

        <section class="rpa-panel">
          <h3>执行历史</h3>
          <el-table :data="status?.history || []" size="small" max-height="220">
            <el-table-column prop="task" label="任务" min-width="120" />
            <el-table-column prop="started_at" label="开始时间" min-width="155" />
            <el-table-column prop="finished_at" label="结束时间" min-width="155" />
            <el-table-column label="耗时" width="85"><template #default="scope">{{ duration(scope.row) }}</template></el-table-column>
          </el-table>
        </section>
      </div>

      <div class="rpa-right">
        <section class="rpa-panel">
          <div class="rpa-panel-title rpa-result-title"><h3>任务处理结果表</h3><el-button size="small" :icon="RefreshRight" :disabled="running || !monthResults.length" @click="resetResults">重置</el-button></div>
          <div class="rpa-summary">
            <span>任务 <strong>{{ resultSummary.total }}</strong></span><span>已处理 <strong>{{ resultSummary.processed }}</strong></span><span>待处理 <strong>{{ resultSummary.pending }}</strong></span><span class="success">成功 <strong>{{ resultSummary.success }}</strong></span><span class="failed">失败 <strong>{{ resultSummary.failed }}</strong></span>
          </div>
          <el-table :data="monthResults" max-height="310">
            <el-table-column prop="code" label="机构代码" width="110" />
            <el-table-column prop="name" label="机构名称" min-width="150" />
            <el-table-column v-for="column in resultColumns" :key="column.key" :prop="column.key" :label="column.label" min-width="115">
              <template #default="scope"><span :class="statusClass(scope.row[column.key])" :title="resultTitle(scope.row[column.key])">{{ resultLabel(scope.row[column.key]) }}</span></template>
            </el-table-column>
          </el-table>
        </section>

        <section class="rpa-panel rpa-log-panel">
          <div class="rpa-panel-title"><h3>日志展示</h3><span>{{ currentRunText }}</span></div>
          <div class="rpa-toolbar">
            <el-button :icon="Monitor" @click="openRpaMonitor">打开监控窗口</el-button>
            <el-button :icon="RefreshRight" :disabled="running || !status?.can_resume" @click="confirmResume">从失败继续</el-button>
            <el-button :icon="VideoPause" type="danger" :disabled="!status?.can_stop" :loading="status?.current_run.status === 'stopping'" @click="stopTask">停止任务</el-button>
            <el-button :icon="CopyDocument" @click="copyLog">复制</el-button>
            <el-button :icon="Delete" @click="clearLog">清空</el-button>
          </div>
          <pre ref="logBox" class="rpa-log" @scroll="trackLogScroll">{{ logText }}</pre>
        </section>

        <section class="rpa-panel">
          <div class="rpa-panel-title rpa-output-title">
            <h3>输出文件</h3>
            <div>
              <el-button size="small" :icon="Download" :disabled="running || !outputFiles.length" @click="downloadOutputArchive">下载 ZIP</el-button>
              <el-button size="small" :icon="Delete" type="danger" plain :disabled="running || !outputFiles.length" @click="clearOutputFiles">一键清空</el-button>
            </div>
          </div>
          <div v-if="outputFiles.length" class="rpa-output-list">
            <button v-for="file in outputFiles" :key="file.name" @click="downloadOutput(file)"><span>{{ file.name }}</span><small>{{ formatSize(file.size) }} · {{ file.modified_at }}</small><el-icon><Download /></el-icon></button>
          </div>
          <el-empty v-else description="暂无输出文件" :image-size="56" />
        </section>
      </div>
    </div>

    <el-drawer v-model="popupDrawerVisible" title="弹窗规则详情" size="min(1120px, 94vw)" append-to-body>
      <div class="rpa-popup-drawer">
        <section class="rpa-popup-section">
          <div class="rpa-panel-title rpa-output-title">
            <div>
              <h3>提醒弹窗规则</h3>
              <p class="rpa-panel-note">仅处理原有 RPA 流程未处理的提醒弹窗。安全验证滑块、导出记录下载、文件导入、生成零工资和清空确认等业务窗口不可配置。</p>
            </div>
            <div>
              <el-button :disabled="running" @click="addPopupRule()">新增规则</el-button>
              <el-button :disabled="running" @click="resetPopupRules">恢复默认</el-button>
              <el-button type="primary" :loading="savingPopupRules" :disabled="running" @click="savePopupRules">保存</el-button>
            </div>
          </div>
          <div class="rpa-popup-table-wrap">
            <el-table :data="popupRules" row-key="id" empty-text="暂无提醒规则">
              <el-table-column label="启用" width="70"><template #default="{ row }"><el-switch v-model="row.enabled" :disabled="running" /></template></el-table-column>
              <el-table-column label="匹配关键字" min-width="210"><template #default="{ row }"><el-input v-model="row.keyword" :disabled="running" placeholder="弹窗标题或正文中的稳定文字" /></template></el-table-column>
              <el-table-column label="适用任务" width="155"><template #default="{ row }"><el-select v-model="row.task" :disabled="running"><el-option v-for="item in popupTaskOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></template></el-table-column>
              <el-table-column label="动作" width="145"><template #default="{ row }"><el-select v-model="row.action" :disabled="running"><el-option v-for="item in popupActionOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></template></el-table-column>
              <el-table-column label="按钮文字" width="145"><template #default="{ row }"><el-input v-model="row.button_text" :disabled="running || row.action !== 'click'" placeholder="如：我知道了" /></template></el-table-column>
              <el-table-column label="延迟（毫秒）" width="155"><template #default="{ row }"><el-input-number v-model="row.delay_ms" :disabled="running" :min="0" :max="10000" :step="500" controls-position="right" /></template></el-table-column>
              <el-table-column label="操作" width="70" fixed="right"><template #default="{ $index }"><el-button :icon="Delete" text type="danger" title="删除规则" :disabled="running" @click="popupRules.splice($index, 1)" /></template></el-table-column>
            </el-table>
          </div>
        </section>

        <section class="rpa-popup-section">
          <div class="rpa-panel-title rpa-output-title">
            <div><h3>最近弹窗记录</h3><p class="rpa-panel-note">未配置弹窗会记录内容并暂停任务；确认稳定关键字和处理按钮后可加入上方规则。</p></div>
            <el-button size="small" :icon="Refresh" @click="loadPopupEvents">刷新记录</el-button>
          </div>
          <el-table :data="popupEvents" max-height="320" empty-text="暂无弹窗记录">
            <el-table-column prop="captured_at" label="时间" min-width="175" />
            <el-table-column prop="org_code" label="机构" width="95" />
            <el-table-column label="任务" width="130"><template #default="{ row }">{{ popupTaskLabel(row.task) }}</template></el-table-column>
            <el-table-column prop="content" label="弹窗内容" min-width="360" show-overflow-tooltip />
            <el-table-column prop="close_action" label="处理结果" width="145" />
            <el-table-column label="操作" width="105" fixed="right"><template #default="{ row }"><el-button size="small" :disabled="running" @click="addPopupRule(row)">新增规则</el-button></template></el-table-column>
          </el-table>
        </section>
      </div>
    </el-drawer>

    <el-dialog v-model="previewVisible" title="确认执行机构" width="620px">
      <p>请确认本次将处理以下 {{ previewOrgs.length }} 个机构。确认后程序开始执行。</p>
      <el-table :data="previewOrgs" max-height="360"><el-table-column prop="code" label="机构代码" width="150" /><el-table-column prop="name" label="机构名称" /></el-table>
      <template #footer><el-button @click="previewVisible = false">取消</el-button><el-button type="primary" @click="startConfirmed">确认执行</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, DocumentAdd, Download, Monitor, Refresh, RefreshRight, Setting, Upload, VideoPause } from '@element-plus/icons-vue'
import { rpaApi, type RpaFile, type RpaOrg, type RpaPopupEvent, type RpaPopupRule, type RpaPopupTask, type RpaStatus, type RpaTaskKey } from '../api'

const props = defineProps<{ periodId: number | null; initialMonth: string }>()
const status = ref<RpaStatus | null>(null)
const outputFiles = ref<RpaFile[]>([])
const month = ref(props.initialMonth)
const allOrgs = ref(true)
const selectedOrgCodes = ref<string[]>([])
const organizations = ref<RpaOrg[]>([])
const monthManuallyOverridden = ref(false)
const chromePath = ref('')
const inputPath = ref('')
const outputPath = ref('')
const loading = ref(false)
const logText = ref('')
const logOffset = ref(0)
const logBox = ref<HTMLElement | null>(null)
const autoScroll = ref(true)
const importInput = ref<HTMLInputElement | null>(null)
const previewVisible = ref(false)
const previewOrgs = ref<RpaOrg[]>([])
const pendingTask = ref<RpaTaskKey | null>(null)
const pendingResume = ref(false)
const popupRules = ref<RpaPopupRule[]>([])
const popupEvents = ref<RpaPopupEvent[]>([])
const savingPopupRules = ref(false)
const popupDrawerVisible = ref(false)
let timer: number | undefined

const running = computed(() => ['starting', 'running', 'stopping'].includes(status.value?.current_run.status || ''))
const monthResults = computed(() => (status.value?.results || []).filter((item) => item.month === month.value))
const resultSummary = computed(() => {
  const values = monthResults.value.flatMap((row) => resultColumns.map((column) => (row as any)[column.key]))
  const states = values.map(resultState)
  return {
    total: values.length,
    processed: states.filter((state) => state !== 'pending').length,
    pending: states.filter((state) => state === 'pending').length,
    success: states.filter((state) => state === 'success' || state === 'skipped').length,
    failed: states.filter((state) => state === 'failed' || state === 'cancelled').length,
  }
})
const chromeLabel = computed(() => ({ ready: 'CDP 已连接', starting: '正在启动', unavailable: '不可用', stopped: '未启动' }[status.value?.chrome.status || 'stopped']))
const currentRunText = computed(() => running.value ? `${status.value?.current_run.current_org_code || ''} ${status.value?.current_run.current_org_name || '任务启动中'}` : '')
const resultColumns = [
  { key: 'special_deduction', label: '专项申报' }, { key: 'import', label: '个税申报导入' },
  { key: 'tax_certificate', label: '完税证明' }, { key: 'comprehensive_income_report', label: '综合所得申报' },
  { key: 'classified_income_report', label: '分类所得申报' }, { key: 'restricted_stock_report', label: '限售股申报' },
]
const steps = [
  { step: '步骤 1', key: 'chrome', title: '浏览器初始化', description: '启动可接管的 Chrome。启动后请在该窗口手工登录自然人电子税务局。' },
  { step: '步骤 2', key: 'special_deduction', title: '专项附加导出', description: '批量导出专项附加扣除文件。机构范围由所属期间人员主数据自动生成。' },
  { step: '步骤 3', key: 'import', title: '导入数据', description: '从 input 目录按机构代码前缀匹配文件，批量导入人员信息、工资薪金、劳务报酬、奖金等文件。' },
  { step: '步骤 4', key: 'tax_certificate', title: '完税证明下载', description: '按机构查询缴款记录并下载完税证明 PDF。默认查询申报月份的次月缴款记录。' },
  { step: '步骤 5', key: 'declaration_reports', title: '下载申报结果', description: '依次下载综合所得、分类所得和限售股申报结果。' },
]
const popupTaskOptions: Array<{ value: RpaPopupTask; label: string }> = [
  { value: 'all', label: '全部任务' },
  { value: 'special_deduction', label: '专项附加导出' },
  { value: 'import', label: '导入数据' },
  { value: 'tax_certificate', label: '完税证明下载' },
  { value: 'declaration_reports', label: '下载申报结果' },
  { value: 'income_report', label: '综合所得申报' },
  { value: 'extra_income_reports', label: '分类/限售股申报' },
  { value: 'tax_certificate_or_income_report', label: '完税及申报下载' },
]
const popupActionOptions = [
  { value: 'keep', label: '保留（不处理）' },
  { value: 'close', label: '关闭弹窗' },
  { value: 'click', label: '点击按钮' },
]

watch(() => props.initialMonth, (value) => { if (value && !running.value) { month.value = value; monthManuallyOverridden.value = false } })
watch(() => props.periodId, async () => { selectedOrgCodes.value = []; await loadOrganizations() })
onMounted(async () => { await Promise.all([refreshAll(), loadOrganizations(), loadPopupRules(), loadPopupEvents()]); timer = window.setInterval(poll, 1500) })
onBeforeUnmount(() => window.clearInterval(timer))

async function refreshAll() {
  loading.value = true
  try {
    const [state, files] = await Promise.all([rpaApi.getStatus(), rpaApi.listFiles()])
    status.value = state.data; outputFiles.value = files.data; chromePath.value = state.data.config.chrome_path; inputPath.value = state.data.config.input_path; outputPath.value = state.data.config.output_path
    await pollLog()
  } catch (error: any) { ElMessage.error(detail(error, 'RPA 状态加载失败')) } finally { loading.value = false }
}
async function poll() { try { const { data } = await rpaApi.getStatus(); status.value = data; await pollLog(); if (!running.value) outputFiles.value = (await rpaApi.listFiles()).data } catch {} }
async function pollLog() { const { data } = await rpaApi.getLogs(logOffset.value); if (data.text) { logText.value += data.text; logOffset.value = data.next_offset; if (autoScroll.value) await nextTick(() => { if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight }) } }
async function saveChromePath() { try { await rpaApi.saveConfig(chromePath.value, inputPath.value, outputPath.value) } catch (error: any) { ElMessage.error(detail(error, 'Chrome 地址保存失败')) } }
async function savePaths() { try { const { data } = await rpaApi.saveConfig(chromePath.value, inputPath.value, outputPath.value); inputPath.value = data.input_path; outputPath.value = data.output_path; await refreshAll() } catch (error: any) { ElMessage.error(detail(error, '路径保存失败')) } }
async function chooseDirectory(kind: 'input' | 'output') { const api = (window as any).pywebview?.api; if (!api?.choose_directory) { ElMessage.info('浏览器模式下请直接输入完整路径'); return } const current = kind === 'input' ? inputPath.value : outputPath.value; const result = await api.choose_directory(current); if (!result?.path) return; if (kind === 'input') inputPath.value = result.path; else outputPath.value = result.path; await savePaths() }
async function initializeChrome() { try { await saveChromePath(); const { data } = await rpaApi.startChrome(chromePath.value); ElMessage.success(data.message); window.setTimeout(refreshAll, 1800) } catch (error: any) { ElMessage.error(detail(error, '浏览器初始化失败')) } }
async function loadOrganizations() { if (!props.periodId) { organizations.value = []; return } try { organizations.value = (await rpaApi.organizations(props.periodId)).data.items } catch (error: any) { organizations.value = []; ElMessage.error(detail(error, '机构列表加载失败')) } }
async function loadPopupRules() { try { popupRules.value = (await rpaApi.getPopupRules()).data.map((rule) => ({ ...rule })) } catch (error: any) { ElMessage.error(detail(error, '提醒弹窗规则加载失败')) } }
async function loadPopupEvents() { try { popupEvents.value = (await rpaApi.getPopupEvents()).data } catch (error: any) { ElMessage.error(detail(error, '弹窗记录加载失败')) } }
async function openPopupDrawer() { popupDrawerVisible.value = true; await Promise.all([loadPopupRules(), loadPopupEvents()]) }
function addPopupRule(event?: RpaPopupEvent) {
  const eventTask = popupTaskOptions.some((item) => item.value === event?.task) ? event?.task as RpaPopupTask : 'all'
  popupRules.value.push({
    id: `popup-${Date.now()}-${popupRules.value.length + 1}`,
    keyword: String(event?.content || '').slice(0, 120),
    task: eventTask,
    action: 'close',
    button_text: '',
    delay_ms: 4000,
    enabled: true,
  })
}
async function savePopupRules() { savingPopupRules.value = true; try { popupRules.value = (await rpaApi.savePopupRules(popupRules.value)).data; ElMessage.success('提醒弹窗规则已保存') } catch (error: any) { ElMessage.error(detail(error, '提醒弹窗规则保存失败')) } finally { savingPopupRules.value = false } }
async function resetPopupRules() { try { await ElMessageBox.confirm('确认恢复系统内置的提醒弹窗规则？', '恢复默认规则'); popupRules.value = (await rpaApi.resetPopupRules()).data; ElMessage.success('已恢复默认提醒规则') } catch (error: any) { if (error !== 'cancel' && error !== 'close') ElMessage.error(detail(error, '恢复默认规则失败')) } }
function popupTaskLabel(task: string) { return popupTaskOptions.find((item) => item.value === task)?.label || task || '未知' }
async function uploadImports(event: Event) { const input = event.target as HTMLInputElement; const files = Array.from(input.files || []); if (!files.length) return; try { await rpaApi.uploadImportFiles(files); ElMessage.success('导入文件已准备'); await refreshAll() } catch (error: any) { if (error?.response?.status === 409 && await confirmOverwrite()) { await rpaApi.uploadImportFiles(files, true); ElMessage.success('同名文件已覆盖'); await refreshAll() } else if (error?.response?.status !== 409) ElMessage.error(detail(error, '导入文件上传失败')) } finally { input.value = '' } }
async function preparePeriodFiles(overwrite: boolean) { if (!props.periodId) return; try { await rpaApi.prepareFromPeriod(props.periodId, overwrite); ElMessage.success('本期申报文件已准备'); await refreshAll() } catch (error: any) { if (error?.response?.status === 409 && await confirmOverwrite()) await preparePeriodFiles(true); else if (error?.response?.status !== 409) ElMessage.error(detail(error, '准备本期文件失败')) } }
async function removeImport(name: string) { try { await ElMessageBox.confirm(`确认从 input 删除“${name}”？`, '删除导入文件', { type: 'warning' }); await rpaApi.clearImportFiles([name]); await refreshAll() } catch (error: any) { if (error !== 'cancel' && error !== 'close') ElMessage.error(detail(error, '删除失败')) } }
async function clearImports() { try { await ElMessageBox.confirm('确认清空 INPUT 目录中的全部导入文件？', '一键清空', { type: 'warning', confirmButtonText: '确认清空' }); await rpaApi.clearImportFiles((status.value?.import_files || []).map((file) => file.name)); await refreshAll(); ElMessage.success('导入文件已清空') } catch (error: any) { if (error !== 'cancel' && error !== 'close') ElMessage.error(detail(error, '清空失败')) } }
async function resetResults() { try { await ElMessageBox.confirm(`确认重置 ${month.value} 的任务处理结果？`, '重置结果', { type: 'warning' }); status.value = (await rpaApi.resetResults(month.value)).data; ElMessage.success('任务处理结果已重置') } catch (error: any) { if (error !== 'cancel' && error !== 'close') ElMessage.error(detail(error, '重置失败')) } }
async function confirmTask(task: RpaTaskKey) { try { validate(); const { data } = await rpaApi.previewOrganizations({ period_id: props.periodId!, all_orgs: allOrgs.value, org_codes: allOrgs.value ? [] : selectedOrgCodes.value }); previewOrgs.value = data.items; pendingTask.value = task; pendingResume.value = false; previewVisible.value = true } catch (error: any) { ElMessage.error(detail(error, '无法开始任务')) } }
async function startConfirmed() { if (!pendingTask.value && !pendingResume.value) return; try { if (pendingResume.value) { await rpaApi.resumeTask() } else { await rpaApi.startPeriodTask({ task_key: pendingTask.value!, period_id: props.periodId!, declaration_month: month.value, all_orgs: allOrgs.value, org_codes: allOrgs.value ? [] : selectedOrgCodes.value }) } previewVisible.value = false; logText.value = ''; logOffset.value = 0; await openRpaMonitor(); await refreshAll() } catch (error: any) { if (error !== 'cancel' && error !== 'close') ElMessage.error(detail(error, pendingResume.value ? '续跑失败' : '任务启动失败')) } }
async function confirmResume() { try { const failure = status.value?.last_failure; if (!failure?.org_code) throw new Error('当前没有可续跑的失败机构'); const { data } = await rpaApi.previewOrgs({ all_orgs: true, org_code: null, start_org_code: failure.org_code }); previewOrgs.value = data.items; pendingTask.value = null; pendingResume.value = true; previewVisible.value = true } catch (error: any) { ElMessage.error(detail(error, '续跑预览失败')) } }
async function stopTask() { try { const { data } = await rpaApi.stopTask(); ElMessage.info(data.message); await refreshAll() } catch (error: any) { ElMessage.error(detail(error, '停止任务失败')) } }
async function copyLog() { await navigator.clipboard.writeText(logText.value); ElMessage.success('日志内容已复制到剪贴板') }
function clearLog() { logText.value = ''; logOffset.value = status.value?.current_run.run_id ? logOffset.value : 0 }
function trackLogScroll() { if (logBox.value) autoScroll.value = logBox.value.scrollHeight - logBox.value.scrollTop - logBox.value.clientHeight < 24 }
async function saveBlob(blob: Blob, fileName: string) {
  if (!blob.size) throw new Error('下载文件为空')
  const savePicker = (window as any).showSaveFilePicker
  if (savePicker) {
    const handle = await savePicker({
      suggestedName: fileName,
      types: [{ description: fileName.endsWith('.zip') ? 'ZIP 压缩包' : '下载文件', accept: { [blob.type || 'application/octet-stream']: [`.${fileName.split('.').pop()}`] } }],
    })
    const writable = await handle.createWritable()
    await writable.write(blob)
    await writable.close()
    return
  }
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 60000)
}
async function downloadOutput(file: RpaFile) { try { const response = await rpaApi.downloadFile(file.name); await saveBlob(response.data instanceof Blob ? response.data : new Blob([response.data]), file.name) } catch (error: any) { if (error?.name !== 'AbortError') ElMessage.error(detail(error, '下载失败')) } }
async function downloadOutputArchive() { try { const response = await rpaApi.downloadArchive(); const disposition = response.headers['content-disposition'] || ''; const match = disposition.match(/filename\*=UTF-8''([^;]+)/i); const fileName = match ? decodeURIComponent(match[1]) : 'RPA输出文件.zip'; const blob = response.data instanceof Blob ? response.data : new Blob([response.data], { type: 'application/zip' }); await saveBlob(blob, fileName) } catch (error: any) { if (error?.name !== 'AbortError') ElMessage.error(detail(error, 'ZIP 下载失败')) } }
async function clearOutputFiles() { try { await ElMessageBox.confirm('确认删除全部 RPA 输出文件？该操作无法撤销。', '一键清空', { type: 'warning', confirmButtonText: '确认清空' }); outputFiles.value = (await rpaApi.clearOutputFiles()).data; ElMessage.success('RPA 输出文件已清空') } catch (error: any) { if (error !== 'cancel' && error !== 'close') ElMessage.error(detail(error, '清空失败')) } }
function validate() { if (!props.periodId) throw new Error('请选择所属期间'); if (!month.value) throw new Error('请选择申报月份'); if (!organizations.value.length) throw new Error('当前期间没有可用机构'); if (!allOrgs.value && !selectedOrgCodes.value.length) throw new Error('请选择至少一个机构'); if (status.value?.chrome.status !== 'ready') throw new Error('请先初始化 Chrome 并完成手工登录') }
function restoreMonth() { month.value = props.initialMonth; monthManuallyOverridden.value = false }
function resultLabel(value: any) { return value?.label || value || '待处理' }
function resultState(value: any) { if (value?.status) return value.status; const text = String(value || '待处理'); if (text.startsWith('成功')) return 'success'; if (text === '失败') return 'failed'; if (text === '处理中') return 'running'; if (text === '已取消') return 'cancelled'; if (text === '无需处理') return 'skipped'; return 'pending' }
function resultTitle(value: any) { return value?.error_message || value?.reason || '' }
function statusClass(value: any) { const state = value?.status || (String(value || '').startsWith('成功') ? 'success' : value === '失败' ? 'failed' : value === '处理中' ? 'running' : 'pending'); return ['rpa-result', state] }
async function openRpaMonitor() { const desktopApi = (window as any).pywebview?.api; if (desktopApi?.open_rpa_monitor) { await desktopApi.open_rpa_monitor(); return } const popup = window.open('/?window=rpa-monitor', 'rpa-monitor', 'popup=yes,width=460,height=640,resizable=yes,scrollbars=no'); if (!popup) ElMessage.warning('浏览器阻止了监控窗口，请允许本站弹出窗口后重试') }
function duration(row: any) { const seconds = Math.max(0, Math.round((new Date(row.finished_at).getTime() - new Date(row.started_at).getTime()) / 1000)); return `${Math.floor(seconds / 60)}分${seconds % 60}秒` }
function formatSize(value: number) { return value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${Math.ceil(value / 1024)} KB` }
function detail(error: any, fallback: string) { return error?.response?.data?.detail || error?.message || fallback }
async function confirmOverwrite() { try { await ElMessageBox.confirm('发现同名文件，确认覆盖？', '覆盖确认', { type: 'warning' }); return true } catch { return false } }
</script>

<style scoped>
.rpa-page{display:flex;flex-direction:column;gap:14px}.rpa-heading{display:flex;align-items:center;justify-content:space-between}.rpa-heading h2{margin:0;font-size:20px;letter-spacing:0}.rpa-heading p{margin:5px 0 0;color:#667085}.rpa-state{font-weight:700}.is-ready{color:#15803d}.is-starting,.is-unavailable{color:#b45309}.is-stopped{color:#667085}.rpa-layout{display:grid;grid-template-columns:minmax(380px,440px) minmax(0,1fr);gap:14px;align-items:start}.rpa-left,.rpa-right{display:flex;flex-direction:column;gap:14px;min-width:0}.rpa-panel{border:1px solid #e3e7ee;border-radius:6px;background:#fff;padding:14px}.rpa-panel h3{margin:0 0 12px;font-size:15px;letter-spacing:0}.rpa-form{display:grid;grid-template-columns:82px minmax(0,1fr);align-items:center;gap:10px}.rpa-form label{color:#475467;font-size:13px}.rpa-file-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px}.rpa-hint{margin:10px 0 0 92px;color:#7b8494;font-size:12px}.rpa-step{display:grid;grid-template-columns:52px minmax(0,1fr) 64px;gap:10px;align-items:center;padding:11px 0;border-top:1px solid #eef1f5}.rpa-step:first-of-type{border-top:0}.rpa-step-no{color:#667085;font-size:12px}.rpa-step strong{font-size:14px}.rpa-step p{margin:3px 0 0;color:#7b8494;font-size:12px;line-height:1.45}.rpa-input-actions{display:flex;flex-wrap:wrap;gap:8px;padding-top:10px;border-top:1px solid #eef1f5}.rpa-file-list{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.rpa-file-list span{display:flex;max-width:100%;align-items:center;gap:5px;padding:4px 7px;background:#f2f4f7;border-radius:4px;font-size:12px;overflow-wrap:anywhere}.rpa-file-list button{border:0;background:transparent;color:#b42318;cursor:pointer;font-size:16px}.rpa-result{font-weight:600}.rpa-result.success{color:#15803d}.rpa-result.failed{color:#c2413b}.rpa-result.running{color:#2563eb}.rpa-result.pending{color:#7b8494}.rpa-panel-title{display:flex;justify-content:space-between;align-items:center}.rpa-panel-title span{color:#2563eb;font-size:12px}.rpa-output-title{margin-bottom:12px;gap:12px}.rpa-output-title h3{margin:0}.rpa-output-title>div{display:flex;gap:8px;flex-wrap:wrap}.rpa-toolbar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}.rpa-log{height:280px;margin:0;padding:12px;overflow:auto;white-space:pre;font:12px/1.6 Consolas,"Courier New",monospace;background:#111827;color:#d1fae5;border-radius:4px}.rpa-output-list{display:flex;flex-direction:column}.rpa-output-list button{display:grid;grid-template-columns:minmax(0,1fr) auto 24px;align-items:center;gap:12px;width:100%;padding:9px 4px;border:0;border-top:1px solid #eef1f5;background:transparent;text-align:left;cursor:pointer}.rpa-output-list button:hover{background:#f8fafc}.rpa-output-list span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rpa-output-list small{color:#7b8494}@media(max-width:1100px){.rpa-layout{grid-template-columns:1fr}.rpa-left,.rpa-right{width:100%}}@media(max-width:640px){.rpa-form{grid-template-columns:1fr}.rpa-hint{margin-left:0}.rpa-step{grid-template-columns:45px minmax(0,1fr)}.rpa-step .el-button{grid-column:2}.rpa-output-list button{grid-template-columns:minmax(0,1fr) 24px}.rpa-output-list small{grid-row:2;grid-column:1}}
.rpa-result-title{margin-bottom:10px}.rpa-result-title h3{margin:0}.rpa-summary{display:grid;grid-template-columns:repeat(5,minmax(80px,1fr));gap:8px;margin-bottom:12px}.rpa-summary span{padding:8px;background:#f7f8fa;border:1px solid #e7eaf0;border-radius:4px;color:#667085;font-size:12px}.rpa-summary strong{display:block;margin-top:2px;color:#101828;font-size:18px}.rpa-summary .success strong{color:#15803d}.rpa-summary .failed strong{color:#c2413b}
.rpa-heading-actions{display:flex;align-items:center;gap:8px}.rpa-popup-drawer{display:flex;flex-direction:column;gap:24px}.rpa-popup-section{min-width:0}.rpa-popup-section+.rpa-popup-section{padding-top:20px;border-top:1px solid #e5e7eb}.rpa-popup-section .rpa-output-title{align-items:flex-start}.rpa-popup-section .rpa-output-title>div:first-child{display:block}.rpa-panel-note{margin:5px 0 0;color:#667085;font-size:12px;line-height:1.5}.rpa-popup-table-wrap{overflow-x:auto}.rpa-popup-table-wrap .el-table{min-width:1050px}.rpa-popup-table-wrap .el-input-number{width:125px}
</style>
