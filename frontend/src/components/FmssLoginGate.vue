<template>
  <section class="fmss-login-page">
    <div class="fmss-login-panel">
      <div class="fmss-login-brand"><img src="/gf-logo.jpg" alt="广发证券" /><span>广发证券</span></div>
      <h1>智能税务平台</h1>
      <p class="fmss-login-description">登录后进入税务工作台</p>
      <p class="fmss-login-status">{{ status }}</p>
      <el-button class="fmss-login-button" type="primary" size="large" :loading="opening" @click="openLogin">登录智能税务平台</el-button>
      <p class="fmss-login-note">使用广发证券 OA 账号登录</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { fmssApi } from '../api'

const emit = defineEmits<{ connected: [] }>()
const opening = ref(false)
const status = ref('当前登录状态：未登录')
let pollTimer: number | undefined
let pollStartedAt = 0

async function openLogin() {
  opening.value = true
  try {
    await fmssApi.openBrowserLogin()
    status.value = '正在等待智能税务平台登录，请在新窗口完成OA登录'
    pollStartedAt = Date.now()
  } catch {
    status.value = '智能税务平台登录窗口启动失败，请检查Chrome环境'
  } finally {
    opening.value = false
  }
}

async function checkSession() {
  if (pollStartedAt && Date.now() - pollStartedAt > 180000) {
    stopPolling()
    status.value = '当前登录状态：登录超时，请重新点击登录智能税务平台'
    return
  }
  try {
    const { data } = await fmssApi.session(true)
    if (!data.connected) {
      const browser = await fmssApi.browserStatus()
      if (browser.data.status === 'error') {
        status.value = browser.data.message || '智能税务平台登录失败，请重新登录'
        stopPolling()
      }
      return
    }
    await fmssApi.branches()
    stopPolling()
    emit('connected')
  } catch {
    status.value = '当前登录状态：智能税务平台登录已失效'
  }
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(checkSession, 1200)
}

function stopPolling() {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
  pollTimer = undefined
}

onMounted(() => {
  void checkSession()
  startPolling()
})
onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
.fmss-login-page { min-height: 100vh; display: grid; place-items: center; padding: 32px 20px; background: linear-gradient(135deg, #eef5ff, #f8fafc 60%, #e8effa); }
.fmss-login-panel { width: min(460px, 100%); padding: 40px; background: var(--surface); border: 1px solid var(--line-soft); border-radius: 16px; box-shadow: var(--shadow-md); }
.fmss-login-brand { display: flex; align-items: center; gap: 12px; margin-bottom: 30px; color: var(--brand-dark); font-size: 19px; font-weight: 700; }
.fmss-login-brand img { width: 52px; height: 52px; object-fit: contain; border-radius: 8px; }
.fmss-login-panel h1 { margin: 0; font-size: 28px; color: var(--ink); }
.fmss-login-description { margin: 10px 0 26px; color: var(--muted); }
.fmss-login-status { min-height: 44px; margin: 0 0 20px; line-height: 1.6; color: var(--muted); }
.fmss-login-button { width: 100%; }
.fmss-login-note { margin: 18px 0 0; text-align: center; font-size: 13px; color: var(--muted); }
</style>
