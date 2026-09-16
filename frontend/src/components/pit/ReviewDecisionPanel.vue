<template>
  <section class="decision-panel">
    <div><strong>复核意见</strong><p>仅填写复核结论；提交版本中的金额和差异原因不可编辑。</p></div>
    <el-input v-model="comment" type="textarea" :rows="3" maxlength="500" show-word-limit :disabled="loading" placeholder="通过意见可选；退回原因必填" />
    <div class="decision-panel__actions">
      <el-button type="success" :loading="loading && pendingDecision === 'approved'" :disabled="loading" @click="emitDecision('approved')">通过</el-button>
      <el-button type="danger" :loading="loading && pendingDecision === 'rejected'" :disabled="loading" @click="emitDecision('rejected')">退回</el-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
const props = defineProps<{ loading: boolean }>()
const emit = defineEmits<{ decide: [decision: 'approved' | 'rejected', comment: string] }>()
const comment = ref('')
const pendingDecision = ref<'approved' | 'rejected' | null>(null)
async function emitDecision(decision: 'approved' | 'rejected') {
  if (decision === 'rejected' && !comment.value.trim()) { ElMessage.warning('退回原因必填'); return }
  if (props.loading) return
  pendingDecision.value = decision
  emit('decide', decision, comment.value.trim())
}
</script>

<style scoped>
.decision-panel { display:grid; gap:12px; padding:16px; border:1px solid var(--el-border-color); border-radius:6px; }.decision-panel p { margin:5px 0 0; color:var(--el-text-color-secondary); font-size:13px; }.decision-panel__actions { display:flex; gap:8px; }
</style>
