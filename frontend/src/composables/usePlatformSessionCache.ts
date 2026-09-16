import { computed, getCurrentInstance, onBeforeUnmount, ref } from 'vue'
import type { PlatformAccount } from '../features/pit/contracts'

export const MOCK_PLATFORM_ACCOUNTS: PlatformAccount[] = [
  { id: 'reviewer-a', displayName: '模拟复核员 A', role: '复核岗' },
  { id: 'reviewer-b', displayName: '模拟复核员 B', role: '复核岗（受限机构）' },
]

const platformPreviewEnabled = import.meta.env.DEV

export function usePlatformSessionCache() {
  const account = ref<PlatformAccount | null>(platformPreviewEnabled ? MOCK_PLATFORM_ACCOUNTS[0] : null)
  const epoch = ref(0)
  const controllers = new Set<AbortController>()
  const loggedIn = computed(() => account.value !== null)

  function createRequest() {
    const controller = new AbortController()
    controllers.add(controller)
    controller.signal.addEventListener('abort', () => controllers.delete(controller), { once: true })
    return { controller, sessionEpoch: epoch.value, accountId: account.value?.id ?? null }
  }

  function isCurrent(request: { sessionEpoch: number; accountId: string | null }) {
    return epoch.value === request.sessionEpoch && account.value?.id === request.accountId
  }

  function invalidate() {
    epoch.value += 1
    controllers.forEach((controller) => controller.abort())
    controllers.clear()
  }

  function clearOnlineCache() { invalidate() }
  function switchAccount(nextAccountId: string) { invalidate(); account.value = platformPreviewEnabled ? MOCK_PLATFORM_ACCOUNTS.find((item) => item.id === nextAccountId) ?? null : null }
  function logout() { invalidate(); account.value = null }
  function expire() { logout() }

  if (getCurrentInstance()) onBeforeUnmount(invalidate)
  return { account, epoch, loggedIn, createRequest, isCurrent, clearOnlineCache, switchAccount, logout, expire }
}
