<template>
  <el-dialog v-model="visible" title="人员身份映射" width="min(1280px, 96vw)" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving">
    <p>映射仅用于当前公司、当前月份的人员核对。支持身份证、港澳通行证和护照；姓名、机构或证件不同也可人工选择。请核实是同一人员后再保存，不能仅凭金额相同确认。原始机构和金额会保留。</p>
    <div class="mapping-filters">
      <el-input v-model="keyword" clearable placeholder="查找申报姓名、机构、证件或已选工资人员" />
      <el-checkbox v-model="onlyUnconfirmed">仅看待确认和人工映射</el-checkbox>
      <span>{{ filteredRows.length }} / {{ rows.length }} 条</span>
    </div>
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" />
    <el-table v-loading="loading" :data="filteredRows" border max-height="480" row-key="row_key" empty-text="没有符合条件的申报记录">
      <el-table-column prop="org_code" label="申报机构" width="90" />
      <el-table-column prop="name" label="申报姓名" width="135" />
      <el-table-column label="申报证件" width="175"><template #default="{ row }">{{ row.masked_id }}<small class="mapping-note">{{ row.document_type }}</small></template></el-table-column>
      <el-table-column label="申报来源" min-width="150"><template #default="{ row }">{{ row.file_name }} / {{ row.sheet_name }} / {{ row.source_row }}</template></el-table-column>
      <el-table-column prop="tax_amount" label="申报税额" width="100" />
      <el-table-column label="工资人员（人工选择）" min-width="340">
        <template #default="{ row }">
          <el-select-v2 v-model="row.selected_target" clearable filterable :options="selectOptions" :disabled="!editable || saving" :placeholder="automaticLabel(row)" style="width:100%" />
          <small v-if="selectedPayroll(row)" class="mapping-note">工资税额：{{ selectedPayroll(row)?.tax_amount }}，来源 {{ selectedPayroll(row)?.row_count }} 行</small>
          <small v-if="differenceLabels(row).length" class="mapping-warning">{{ differenceLabels(row).join('、') }}，请核实</small>
        </template>
      </el-table-column>
      <el-table-column label="匹配情况" width="110"><template #default="{ row }">{{ row.selected_target !== initialSelections[row.row_key] ? '待保存' : (statusLabels[row.status] || row.status) }}</template></el-table-column>
    </el-table>
    <template #footer>
      <el-button :disabled="saving" @click="visible = false">关闭</el-button>
      <el-button v-if="editable" type="primary" :loading="saving" :disabled="loading || Boolean(errorMessage) || !rows.length" @click="save">保存并重算</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, h, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { pitReconciliationApi, type PitIdentityMappingRow, type PitPayrollIdentityOption } from '../../api'

const props = defineProps<{ modelValue: boolean; periodId: number; editable: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const visible = computed({ get: () => props.modelValue, set: (value: boolean) => emit('update:modelValue', value) })
const rows = ref<PitIdentityMappingRow[]>([])
const options = ref<PitPayrollIdentityOption[]>([])
const initialSelections = ref<Record<string, string>>({})
const loading = ref(false)
const saving = ref(false)
const errorMessage = ref('')
const keyword = ref('')
const onlyUnconfirmed = ref(true)
const statusLabels: Record<string, string> = { manual_review: '待人工确认', manual_confirmed: '已人工映射', confirmed: '已自动匹配', unidentified: '身份待补充' }
const normalize = (value: string) => value.replace(/\s+/g, '').toUpperCase()
const optionByKey = computed(() => new Map(options.value.map(option => [option.target_key, option])))
const optionLabel = (option: PitPayrollIdentityOption) => `${option.org_code} / ${option.name} / ${option.id_number}`
const selectOptions = computed(() => options.value.map(option => ({ value: option.target_key, label: optionLabel(option) })))
const selectedPayroll = (row: PitIdentityMappingRow) => optionByKey.value.get(row.selected_target || row.resolved_target)
const automaticLabel = (row: PitIdentityMappingRow) => row.status === 'confirmed' && selectedPayroll(row) ? `自动：${optionLabel(selectedPayroll(row)!)}` : '搜索工资姓名、机构或证件后选择'
const filteredRows = computed(() => rows.value.filter(row => {
  // When the user asks for pending/manual mappings, hide every automatic
  // match.  Automatic matches may carry a resolved target, so checking
  // `!row.selected_target` would incorrectly leave them in the list.
  if (onlyUnconfirmed.value && row.status === 'confirmed') return false
  const option = selectedPayroll(row)
  return !keyword.value || normalize([row.org_code, row.name, row.masked_id, row.file_name, option ? optionLabel(option) : ''].join(' ')).includes(normalize(keyword.value))
}))

function differenceLabels(row: PitIdentityMappingRow): string[] {
  const option = selectedPayroll(row)
  if (!option) return []
  const labels: string[] = []
  if (option.org_code !== row.org_code) labels.push('机构不同')
  if (normalize(option.name) !== normalize(row.name)) labels.push('姓名不同')
  const declared = normalize(row.masked_id)
  const id = normalize(option.id_number)
  const masked = /[*＊]/.test(declared)
  if (masked ? declared[0] !== id[0] || declared.slice(-1) !== id.slice(-1) : declared !== id) labels.push('证件不同')
  return labels
}

let generation = 0
let mounted = true
onBeforeUnmount(() => { mounted = false; generation++ })
watch(() => props.modelValue, async (open) => {
  const request = ++generation
  if (!open) return
  rows.value = []
  options.value = []
  keyword.value = ''
  onlyUnconfirmed.value = true
  errorMessage.value = ''
  loading.value = true
  try {
    const [mappingResponse, optionResponse] = await Promise.all([pitReconciliationApi.getIdentityMappings(props.periodId), pitReconciliationApi.getIdentityMappingOptions(props.periodId)])
    if (request !== generation) return
    rows.value = mappingResponse.data
    options.value = optionResponse.data
    initialSelections.value = Object.fromEntries(rows.value.map(row => [row.row_key, row.selected_target]))
  } catch (error: any) {
    if (request === generation) errorMessage.value = error?.response?.data?.detail || '身份映射加载失败'
  } finally { if (request === generation) loading.value = false }
})

async function save() {
  if (!props.editable || saving.value) return
  const changed = rows.value.filter(row => row.selected_target !== initialSelections.value[row.row_key])
  if (!changed.length) { ElMessage.info('没有修改映射'); return }
  const periodId = props.periodId
  saving.value = true
  try {
    const descriptions = changed.map(row => {
      const option = optionByKey.value.get(row.selected_target)
      return `申报 ${row.org_code} / ${row.name} / ${row.masked_id}\n→ ${option ? `工资 ${optionLabel(option)}${differenceLabels(row).length ? `（${differenceLabels(row).join('、')}）` : ''}` : '清除人工映射，恢复自动判断'}`
    })
    await ElMessageBox.confirm(h('div', { style: { whiteSpace: 'pre-line', maxHeight: '400px', overflow: 'auto' } }, `请确认以下关系属于同一人员。映射不改变原始机构和金额。\n\n${descriptions.join('\n\n')}`), '确认人员映射', { type: 'warning', confirmButtonText: '确认保存并重算', cancelButtonText: '返回核对', closeOnClickModal: false })
    if (!mounted || !props.editable || props.periodId !== periodId) return
    await pitReconciliationApi.saveIdentityMappings(periodId, Object.fromEntries(changed.map(row => [row.row_key, row.selected_target || ''])))
    if (!mounted || props.periodId !== periodId) return
    visible.value = false
    ElMessage.success('身份映射已保存')
    emit('saved')
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close' && mounted) ElMessage.error(error?.response?.data?.detail || '身份映射保存失败')
  } finally { saving.value = false }
}
</script>

<style scoped>
.mapping-filters { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; }
.mapping-filters .el-input { max-width: 420px; }
.mapping-note, .mapping-warning { display: block; margin-top: 5px; }
.mapping-warning { color: var(--el-color-danger); }
</style>
