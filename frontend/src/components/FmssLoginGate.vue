<template>
  <section class="fmss-login-page">
    <div class="fmss-login-panel">
      <div class="fmss-login-mark">FMSS</div>
      <h1>FMSS DEV测试环境</h1>
      <p class="fmss-login-status">{{ status }}</p>
      <el-button type="primary" :loading="opening" @click="openLogin">登录 FMSS</el-button>
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
    status.value = '正在等待FMSS登录，请在新窗口完成OA登录'
    pollStartedAt = Date.now()
  } catch {
    status.value = 'FMSS登录窗口启动失败，请检查Chrome环境'
  } finally {
    opening.value = false
  }
}

async function checkSession() {
  if (pollStartedAt && Date.now() - pollStartedAt > 180000) {
    stopPolling()
    status.value = '当前登录状态：登录超时，请重新点击登录 FMSS'
    return
  }
  try {
    const { data } = await fmssApi.session(true)
    if (!data.connected) {
      const browser = await fmssApi.browserStatus()
      if (browser.data.status === 'error') {
        status.value = browser.data.message || 'FMSS登录失败，请重新登录'
        stopPolling()
      }
      return
    }
    await fmssApi.branches()
    stopPolling()
    emit('connected')
  } catch {
    status.value = '当前登录状态：FMSS登录已失效'
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
.fmss-login-page { min-height: 62vh; display: grid; place-items: center; padding: 32px; }
.fmss-login-panel { width: min(520px, 100%); padding: 36px; background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); border-radius: 8px; box-shadow: var(--el-box-shadow-light); }
.fmss-login-mark { width: 52px; height: 52px; display: grid; place-items: center; margin-bottom: 18px; border-radius: 8px; background: #8b1e2d; color: #fff; font-weight: 700; letter-spacing: 0; }
.fmss-login-panel h1 { margin: 0; font-size: 24px; color: var(--el-text-color-primary); }
.fmss-login-status { margin: 14px 0 22px; color: var(--el-text-color-secondary); }
</style>
