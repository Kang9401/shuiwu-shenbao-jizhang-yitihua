<template>
  <section class="decision-panel">
    <div><strong>审批操作</strong><p>FMSS提交版本只读；退回原因必填。</p></div>
    <el-input v-if="allowReview" v-model="comment" type="textarea" :rows="3" maxlength="500" show-word-limit :disabled="loading" placeholder="通过意见可选；退回原因必填" />
    <div class="decision-panel__actions">
      <el-button v-if="allowReview" type="success" :loading="loading && pendingDecision === 'approved'" :disabled="loading" @click="emitDecision('approved')">复核通过</el-button>
      <el-button v-if="allowReview" type="danger" :loading="loading && pendingDecision === 'rejected'" :disabled="loading" @click="emitDecision('rejected')">退回</el-button>
      <el-button v-if="allowWithdraw" :loading="loading && pendingDecision === 'withdrawn'" :disabled="loading" @click="emitWithdraw">撤回</el-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
const props = defineProps<{ loading: boolean; allowReview?: boolean; allowWithdraw?: boolean }>()
const emit = defineEmits<{ decide: [decision: 'approved' | 'rejected', comment: string]; withdraw: [] }>()
const comment = ref('')
const pendingDecision = ref<'approved' | 'rejected' | 'withdrawn' | null>(null)
async function emitDecision(decision: 'approved' | 'rejected') {
  if (decision === 'rejected' && !comment.value.trim()) { ElMessage.warning('退回原因必填'); return }
  if (props.loading) return
  pendingDecision.value = decision
  emit('decide', decision, comment.value.trim())
}
function emitWithdraw() { if (props.loading) return; pendingDecision.value = 'withdrawn'; emit('withdraw') }
</script>

<style scoped>
.decision-panel { display:grid; gap:12px; padding:16px; border:1px solid var(--el-border-color); border-radius:6px; }.decision-panel p { margin:5px 0 0; color:var(--el-text-color-secondary); font-size:13px; }.decision-panel__actions { display:flex; gap:8px; }
</style>
