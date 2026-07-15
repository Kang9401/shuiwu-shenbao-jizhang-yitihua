<template>
  <section class="card workflow-card">
    <div class="card-header">
      <div>
        <strong>机构映射维护</strong>
        <p>全局长期复用，不随所属期间变化。实习生导入优先使用填写的5位机构代码。</p>
      </div>
      <a class="btn btn-sm btn-outline" :href="organizationMappingApi.exportUrl()" target="_blank">
        <el-icon><Download /></el-icon>导出映射
      </a>
    </div>
    <div class="card-body">
      <div class="master-controls">
        <label><span>营业部名称</span><input v-model.trim="draft.branch_name" class="text-input" placeholder="请输入营业部名称" /></label>
        <label><span>5位机构代码</span><input v-model.trim="draft.org_code" class="text-input" maxlength="5" placeholder="例如 10301" /></label>
        <label><span>状态</span><select v-model="draft.active" class="period-native-select"><option :value="true">启用</option><option :value="false">停用</option></select></label>
        <button class="btn btn-primary" :disabled="saving || !canSave" @click="saveDraft">{{ editingId ? '保存修改' : '新增映射' }}</button>
        <button v-if="editingId" class="btn btn-outline" @click="resetDraft">取消</button>
      </div>

      <div class="upload-item workflow-upload-item" :class="{ 'has-file': importFile }">
        <label>批量导入映射</label>
        <input type="file" accept=".xlsx,.xls" @change="onImportPicked" />
        <span class="upload-status" :class="importFile ? 'ready' : 'empty'">{{ importFile?.name || '需包含营业部名称、机构代码' }}</span>
        <button class="btn btn-sm btn-outline" :disabled="!importFile || saving" @click="importMappings">导入并覆盖</button>
      </div>

      <el-table :data="mappings" size="small" style="width: 100%" max-height="520">
        <el-table-column prop="org_code" label="机构代码" width="120" />
        <el-table-column prop="branch_name" label="营业部名称" min-width="260" />
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
const draft = reactive({ branch_name: '', org_code: '', active: true })
const canSave = computed(() => !!draft.branch_name && /^\d{5}$/.test(draft.org_code))

onMounted(loadMappings)

async function loadMappings() {
  const { data } = await organizationMappingApi.list()
  mappings.value = data
}

function resetDraft() {
  editingId.value = null
  Object.assign(draft, { branch_name: '', org_code: '', active: true })
}

function editRow(row: OrganizationMapping) {
  editingId.value = row.id
  Object.assign(draft, { branch_name: row.branch_name, org_code: row.org_code, active: row.active })
}

async function saveDraft() {
  if (!canSave.value) return
  saving.value = true
  try {
    const payload = { ...draft }
    if (editingId.value) await organizationMappingApi.update(editingId.value, payload)
    else await organizationMappingApi.create(payload)
    ElMessage.success('机构映射已保存')
    resetDraft()
    await loadMappings()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '机构映射保存失败')
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
    ElMessage.success(`已更新 ${data.updated} 条机构映射`)
    importFile.value = null
    await loadMappings()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '机构映射导入失败')
  } finally {
    saving.value = false
  }
}
</script>
