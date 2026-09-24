import axios from 'axios'

export const COMPANY_STORAGE_KEY = 'tax-workbench-company-id'

export function currentCompanyId(): number | null {
  const value = Number(window.localStorage.getItem(COMPANY_STORAGE_KEY))
  return Number.isInteger(value) && value > 0 ? value : null
}

export function companyUrl(path: string): string {
  const companyId = currentCompanyId()
  if (!companyId) return path
  const separator = path.includes('?') ? '&' : '?'
  return `${path}${separator}company_id=${companyId}`
}

export function currentCompanyHeaders(): Record<string, string> {
  const companyId = currentCompanyId()
  return companyId ? { 'X-Company-ID': String(companyId) } : {}
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api'
})

api.interceptors.request.use((config) => {
  const companyId = currentCompanyId()
  if (companyId) config.headers.set('X-Company-ID', String(companyId))
  return config
})

function scopeDownloadUrls(value: any): void {
  if (!value || typeof value !== 'object') return
  if (Array.isArray(value)) {
    value.forEach(scopeDownloadUrls)
    return
  }
  for (const [key, child] of Object.entries(value)) {
    if (key === 'download_url' && typeof child === 'string') value[key] = companyUrl(child)
    else scopeDownloadUrls(child)
  }
}

api.interceptors.response.use((response) => {
  scopeDownloadUrls(response.data)
  return response
}, (error) => {
  const url = String(error?.config?.url || '')
  if (error?.response?.status === 401 && url.startsWith('/fmss')) {
    window.dispatchEvent(new CustomEvent('fmss-session-expired'))
  }
  return Promise.reject(error)
})
