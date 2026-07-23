import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { rpaApi, type RpaStatus } from '../api'

export function useRpaMonitor() {
  const status = ref<RpaStatus | null>(null)
  const logText = ref('')
  const logOffset = ref(0)
  const logBox = ref<HTMLElement | null>(null)
  const loading = ref(false)
  let timer: number | undefined

  const running = computed(() => ['starting', 'running'].includes(status.value?.current_run.status || ''))

  async function refresh() {
    loading.value = true
    try {
      status.value = (await rpaApi.getStatus()).data
      const logs = (await rpaApi.getLogs(logOffset.value)).data
      if (logs.text) {
        logText.value += logs.text
        logOffset.value = logs.next_offset
        await nextTick(() => { if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight })
      }
    } finally {
      loading.value = false
    }
  }

  async function stop() {
    await rpaApi.stopTask()
    await refresh()
  }

  onMounted(async () => { await refresh(); timer = window.setInterval(refresh, 1500) })
  onBeforeUnmount(() => window.clearInterval(timer))
  return { status, logText, logBox, loading, running, refresh, stop }
}

