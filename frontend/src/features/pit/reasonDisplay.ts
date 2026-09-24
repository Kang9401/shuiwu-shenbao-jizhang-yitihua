export const AUTO_REASON_PREFIX = '【自动汇总】'

function text(value: unknown): string {
  return String(value ?? '').trim()
}

export function isGeneratedReason(reason: unknown): boolean {
  return text(reason).startsWith(AUTO_REASON_PREFIX)
}

export function stripAutoPrefix(reason: unknown): string {
  const value = text(reason)
  return isGeneratedReason(value) ? value.slice(AUTO_REASON_PREFIX.length).trimStart() : value
}

export function displayReason(reason: unknown): string {
  return stripAutoPrefix(reason)
}
