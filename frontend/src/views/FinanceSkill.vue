<template>
  <div class="finance-skill-page">
    <aside class="finance-skill-sidebar">
      <div class="finance-skill-sidebar-heading">
        <span>能力模式</span>
        <small>每次会话独立生效</small>
      </div>
      <button
        v-for="item in skillOptions"
        :key="item.key"
        type="button"
        class="finance-skill-option"
        :class="{ active: selectedSkill === item.key }"
        :disabled="sending"
        @click="switchSkill(item.key)"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <span><strong>{{ item.name }}</strong><small>{{ item.description }}</small></span>
        <el-icon class="finance-skill-chevron"><ArrowRight /></el-icon>
      </button>

      <div class="finance-skill-boundary">
        <el-icon><Lock /></el-icon>
        <p>请对身份证号、银行卡号等敏感信息脱敏。模型建议须经业务人员复核后使用。</p>
      </div>
    </aside>

    <section class="finance-chat-shell">
      <header class="finance-chat-toolbar">
        <div>
          <strong>{{ activeSkill.name }}</strong>
          <span class="finance-model-state" :class="{ ready: modelStatus?.configured }">
            <i></i>{{ modelStatus?.configured ? modelStatus.model : '模型未配置' }}
          </span>
        </div>
        <el-tooltip content="清空当前会话" placement="bottom">
          <button class="finance-icon-button" type="button" aria-label="清空当前会话" :disabled="!messages.length || sending" @click="clearChat">
            <el-icon><Delete /></el-icon>
          </button>
        </el-tooltip>
      </header>

      <div ref="messageList" class="finance-message-list" aria-live="polite">
        <div v-if="!messages.length" class="finance-chat-empty">
          <div class="finance-empty-mark"><el-icon><ChatDotRound /></el-icon></div>
          <strong>{{ modelStatus?.configured ? '从一个具体财务问题开始' : '需要先配置模型服务' }}</strong>
          <p v-if="modelStatus?.configured">当前期间为 {{ periodLabel }}，选择下方常用任务或直接输入问题。</p>
          <p v-else>请在后端环境中设置 FINANCE_AI_BASE_URL、FINANCE_AI_API_KEY 和 FINANCE_AI_MODEL，重启服务后生效。</p>
          <div v-if="modelStatus?.configured" class="finance-prompt-grid">
            <button v-for="prompt in activeSkill.prompts" :key="prompt" type="button" @click="usePrompt(prompt)">{{ prompt }}</button>
          </div>
        </div>

        <article v-for="(message, index) in messages" :key="index" class="finance-message" :class="message.role">
          <div class="finance-message-role">{{ message.role === 'user' ? '我' : '财务 SKILL' }}</div>
          <div class="finance-message-content">{{ message.content }}</div>
        </article>

        <article v-if="sending" class="finance-message assistant pending">
          <div class="finance-message-role">财务 SKILL</div>
          <div class="finance-thinking"><span></span><span></span><span></span>正在分析</div>
        </article>
      </div>

      <div class="finance-composer">
        <textarea
          v-model="draft"
          rows="3"
          maxlength="12000"
          :disabled="sending || !modelStatus?.configured"
          :placeholder="modelStatus?.configured ? '输入业务背景、金额口径和希望解决的问题' : '模型服务配置完成后可用'"
          @keydown="handleKeydown"
        ></textarea>
        <div class="finance-composer-footer">
          <span>{{ draft.length }}/12000 · Enter 发送，Shift+Enter 换行</span>
          <button class="btn btn-primary finance-send-button" type="button" :disabled="!canSend" @click="sendMessage">
            <el-icon><Promotion /></el-icon>发送
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ArrowRight,
  ChatDotRound,
  Coin,
  Delete,
  DocumentChecked,
  Lock,
  Promotion,
  TrendCharts,
  Warning,
} from '@element-plus/icons-vue'
import { financeAIApi, type FinanceAIStatus, type FinanceChatMessage, type FinanceSkillKey } from '../api'

const props = defineProps<{ periodLabel: string }>()

const skillOptions = [
  { key: 'general' as const, name: '综合财务分析', description: '多口径拆解经营问题', icon: TrendCharts, prompts: ['分析本月毛利率变化原因', '帮我梳理一项新业务的财税影响', '列出月结异常的排查顺序'] },
  { key: 'accounting' as const, name: '会计处理', description: '确认、计量与分录建议', icon: Coin, prompts: ['判断这笔支出的会计处理', '给出收入确认所需判断条件', '复核一组会计分录是否合理'] },
  { key: 'tax' as const, name: '税务判断', description: '申报口径与资料留存', icon: DocumentChecked, prompts: ['分析该业务可能涉及的税种', '检查一项税务处理需要哪些资料', '梳理申报口径的待核实事项'] },
  { key: 'review' as const, name: '风险复核', description: '异常识别与检查程序', icon: Warning, prompts: ['复核这组数据有哪些风险信号', '设计一套应付账款检查步骤', '列出合同审核的财税关注点'] },
]

const selectedSkill = ref<FinanceSkillKey>('general')
const modelStatus = ref<FinanceAIStatus | null>(null)
const messages = ref<FinanceChatMessage[]>([])
const draft = ref('')
const sending = ref(false)
const messageList = ref<HTMLElement | null>(null)
const activeSkill = computed(() => skillOptions.find((item) => item.key === selectedSkill.value) || skillOptions[0])
const canSend = computed(() => Boolean(modelStatus.value?.configured && draft.value.trim() && !sending.value))

onMounted(loadStatus)

async function loadStatus() {
  try {
    modelStatus.value = (await financeAIApi.status()).data
  } catch {
    modelStatus.value = { configured: false, model: null, skills: [] }
    ElMessage.error('模型服务状态加载失败')
  }
}

function switchSkill(skill: FinanceSkillKey) {
  selectedSkill.value = skill
  messages.value = []
  draft.value = ''
}

function clearChat() {
  messages.value = []
  draft.value = ''
}

function usePrompt(prompt: string) {
  draft.value = prompt
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    if (canSend.value) sendMessage()
  }
}

async function scrollToBottom() {
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}

async function sendMessage() {
  const content = draft.value.trim()
  if (!content || !canSend.value) return
  messages.value.push({ role: 'user', content })
  draft.value = ''
  sending.value = true
  await scrollToBottom()
  try {
    const response = await financeAIApi.chat({
      skill: selectedSkill.value,
      messages: messages.value.slice(-20),
      period_context: props.periodLabel,
    })
    messages.value.push({ role: 'assistant', content: response.data.content })
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '财务 SKILL 响应失败')
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}
</script>
