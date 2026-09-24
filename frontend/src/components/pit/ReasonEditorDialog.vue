<template>
  <el-dialog :model-value="modelValue" title="差异原因" width="680px" @update:model-value="emit('update:modelValue', $event)">
    <div class="reason-dialog-heading">
      <strong>{{ fieldLabel }}</strong>
      <span>来源：{{ sourceLabel }}</span>
    </div>
    <pre v-if="isAutomatic && !editingAsManual" class="reason-preview">{{ reasonBody }}</pre>
    <el-input v-else-if="editable" v-model="editingText" type="textarea" :rows="8" />
    <pre v-else class="reason-preview">{{ reasonBody }}</pre>
    <template #footer>
      <el-button v-if="isAutomatic && !editingAsManual && editable" type="warning" @click="convertToManual">转为人工编辑</el-button>
      <el-button @click="emit('update:modelValue', false)">{{ editable ? '取消' : '关闭' }}</el-button>
      <el-button v-if="editable && (!isAutomatic || editingAsManual)" type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { isGeneratedReason, stripAutoPrefix } from '../../features/pit/reasonDisplay'

const props = defineProps<{
  modelValue: boolean
  fieldLabel: string
  reason?: unknown
  editable: boolean
  saving?: boolean
}>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: [reason: string]
}>()

const editingAsManual = ref(false)
const editingText = ref('')
const isAutomatic = computed(() => isGeneratedReason(props.reason) && !editingAsManual.value)
const reasonBody = computed(() => stripAutoPrefix(props.reason))
const sourceLabel = computed(() => isAutomatic.value ? '自动汇总' : '人工填写')

function resetEditor() {
  editingAsManual.value = !isGeneratedReason(props.reason)
  editingText.value = stripAutoPrefix(props.reason)
}

function convertToManual() {
  editingAsManual.value = true
  editingText.value = stripAutoPrefix(props.reason)
}

function save() {
  emit('save', stripAutoPrefix(editingText.value))
}

watch(() => props.modelValue, (visible) => {
  if (visible) resetEditor()
})
watch(() => props.reason, () => {
  if (props.modelValue) resetEditor()
})
</script>

<style scoped>
.reason-dialog-heading { display:flex; align-items:center; gap:12px; margin-bottom:12px; }
.reason-dialog-heading span { color:var(--el-text-color-secondary); font-size:13px; }
.reason-preview { max-height:420px; min-height:180px; margin:0; overflow:auto; padding:14px; white-space:pre-wrap; font:13px/1.7 var(--el-font-family); background:var(--el-fill-color-lighter); border:1px solid var(--el-border-color-lighter); border-radius:4px; }
</style>
