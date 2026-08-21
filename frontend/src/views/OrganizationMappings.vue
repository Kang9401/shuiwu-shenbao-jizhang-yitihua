<template>
  <section class="card workflow-card">
    <div class="card-header">
      <div>
        <strong>机构名称维护表</strong>
        <p>全局长期复用。启用 RPA 后，营业部全称将作为 RPA 原机构名称。</p>
      </div>
      <a class="btn btn-sm btn-outline" :href="organizationMappingApi.exportUrl()" target="_blank">
        <el-icon><Download /></el-icon>导出维护表
      </a>
    </div>
    <div class="card-body">
      <div class="master-controls">
        <label><span>营业部名称</span><input v-model.trim="draft.branch_name" class="text-input" placeholder="请输入营业部名称" /></label>
        <label><span>5位机构代码</span><input v-model.trim="draft.org_code" class="text-input" maxlength="5" placeholder="例如 10301" /></label>
        <label><span>机构纳税人识别号</span><input v-model.trim="draft.taxpayer_id" class="text-input" placeholder="用于匹配工资单扣缴义务人" /></label>
        <label><span>状态</span><select v-model="draft.active" class="period-native-select"><option :value="true">启用</option><option :value="false">停用</option></select></label>
        <label><span>是否启用 RPA</span><el-switch v-model="draft.rpa_enabled" inline-prompt active-text="是" inactive-text="否" /></label>
        <label><span>营业部全称</span><input v-model.trim="draft.rpa_org_name" class="text-input" :disabled="!draft.rpa_enabled" placeholder="RPA 原机构名称" /></label>
        <label><span>RPA 搜索结果序号</span><input v-model.number="draft.rpa_search_result_index" type="number" min="1" step="1" class="text-input" :disabled="!draft.rpa_enabled" placeholder="默认第 1 条" /></label>
        <label><span>所属分公司</span><input v-model.trim="draft.parent_branch" class="text-input" :disabled="!draft.rpa_enabled" placeholder="请输入所属分公司" /></label>
        <button class="btn btn-primary" :disabled="saving || !canSave" @click="saveDraft">{{ editingId ? '保存修改' : '新增机构' }}</button>
        <button v-if="editingId" class="btn btn-outline" @click="resetDraft">取消</button>
      </div>

      <div class="upload-item workflow-upload-item" :class="{ 'has-file': importFile }">
        <label>批量导入维护表</label>
        <input type="file" accept=".xlsx,.xls" @change="onImportPicked" />
        <span class="upload-status" :class="importFile ? 'ready' : 'empty'">{{ importFile?.name || '必填：营业部名称、机构代码；可选：机构纳税人识别号、RPA信息' }}</span>
        <button class="btn btn-sm btn-outline" :disabled="!importFile || saving" @click="importMappings">导入并覆盖</button>
      </div>

      <el-table :data="mappings" size="small" style="width: 100%" max-height="520">
        <el-table-column prop="org_code" label="机构代码" width="120" />
        <el-table-column prop="branch_name" label="营业部名称" min-width="260" />
        <el-table-column prop="taxpayer_id" label="机构纳税人识别号" min-width="210" show-overflow-tooltip />
        <el-table-column label="启用 RPA" width="110"><template #default="{ row }"><span class="tag" :class="row.rpa_enabled ? 'tag-success' : 'tag-info'">{{ row.rpa_enabled ? '是' : '否' }}</span></template></el-table-column>
        <el-table-column prop="rpa_org_name" label="营业部全称" min-width="260" show-overflow-tooltip />
        <el-table-column prop="rpa_search_result_index" label="搜索结果序号" width="120" />
        <el-table-column prop="parent_branch" label="所属分公司" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="100"><template #default="{ row }"><span class="tag" :class="row.active ? 'tag-success' : 'tag-info'">{{ row.active ? '启用' : '停用' }}</span></template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="{ row }"><button class="btn btn-xs btn-ghost" @click="editRow(row)">编辑</button></template></el-table-column>
      </el-table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { organizationMappingApi, type OrganizationMapping } from '../api'

const mappings = ref<OrganizationMapping[]>([])
const editingId = ref<number | null>(null)
const importFile = ref<File | null>(null)
const saving = ref(false)
const emptyDraft = () => ({ branch_name: '', org_code: '', taxpayer_id: '', active: true, rpa_enabled: false, rpa_org_name: '', rpa_search_result_index: 1, parent_branch: '' })
const draft = reactive(emptyDraft())
const canSave = computed(() => !!draft.branch_name && /^\d{5}$/.test(draft.org_code) && (!draft.rpa_enabled || (!!draft.rpa_org_name && !!draft.parent_branch && Number.isInteger(draft.rpa_search_result_index) && draft.rpa_search_result_index >= 1)))

onMounted(loadMappings)

async function loadMappings() {
  const { data } = await organizationMappingApi.list()
  mappings.value = data
}

function resetDraft() {
  editingId.value = null
  Object.assign(draft, emptyDraft())
}

function editRow(row: OrganizationMapping) {
  editingId.value = row.id
  Object.assign(draft, {
    branch_name: row.branch_name,
    org_code: row.org_code,
    taxpayer_id: row.taxpayer_id,
    active: row.active,
    rpa_enabled: row.rpa_enabled,
    rpa_org_name: row.rpa_org_name,
    rpa_search_result_index: row.rpa_search_result_index || 1,
    parent_branch: row.parent_branch,
  })
}

async function saveDraft() {
  if (!canSave.value) return
  saving.value = true
  try {
    const payload = { ...draft }
    if (editingId.value) await organizationMappingApi.update(editingId.value, payload)
    else await organizationMappingApi.create(payload)
    ElMessage.success('机构名称维护表已保存')
    resetDraft()
    await loadMappings()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '机构名称维护表保存失败')
  } finally {
    saving.value = false
  }
}

function onImportPicked(event: Event) {
  importFile.value = (event.target as HTMLInputElement).files?.[0] || null
}

async function importMappings() {
  if (!importFile.value) return
  saving.value = true
  try {
    const { data } = await organizationMappingApi.importFile(importFile.value)
    ElMessage.success(`已更新 ${data.updated} 条机构信息`)
    importFile.value = null
    await loadMappings()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '机构名称维护表导入失败')
  } finally {
    saving.value = false
  }
}
</script>
