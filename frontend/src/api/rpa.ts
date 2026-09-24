import { api } from './client'

export type RpaTaskKey = 'special_deduction' | 'import' | 'tax_certificate' | 'income_report' | 'extra_income_reports' | 'declaration_reports'

export interface RpaFile {
  name: string
  size: number
  modified_at: string
  download_url?: string
}

export interface RpaOrg {
  code: string
  name: string
  parent_branch?: string
  employee_count?: number
}


export interface RpaResultCell { status: 'pending' | 'running' | 'success' | 'failed' | 'skipped' | 'cancelled'; count: number | null; label: string; reason?: string | null; error_message?: string | null }

export interface RpaResult extends RpaOrg {
  month: string
  special_deduction: string
  import: string
  tax_certificate: string
  income_report: string
  extra_income_reports: string
  comprehensive_income_report?: RpaResultCell
  classified_income_report?: RpaResultCell
  restricted_stock_report?: RpaResultCell
}

export interface RpaStatus {
  config: { chrome_path: string; input_path: string; output_path: string; org_excel_name: string | null }
  chrome: { status: 'stopped' | 'starting' | 'ready' | 'unavailable'; message: string }
  current_run: {
    run_id: string | null
    task_key: RpaTaskKey | null
    month: string | null
    declaration_month?: string | null
    period_id?: number | null
    display_name?: string | null
    org_codes?: string[]
    status: 'idle' | 'starting' | 'running' | 'stopping' | 'succeeded' | 'failed' | 'cancelled'
    current_org_code: string | null
    current_org_name: string | null
  }
  results: RpaResult[]
  history: Array<{ task: string; started_at: string; finished_at: string; status: string }>
  last_failure: { task_key: RpaTaskKey | null; org_code: string | null; month: string | null }
  import_files: RpaFile[]
  can_start: boolean
  can_stop: boolean
  can_resume: boolean
}

export type RpaPopupTask = RpaTaskKey | 'all' | 'tax_certificate_or_income_report'
export type RpaPopupAction = 'keep' | 'close' | 'click'

export interface RpaPopupRule {
  id: string
  keyword: string
  task: RpaPopupTask
  step: 'all' | 'switch_org' | 'switch_month' | 'enter_menu' | 'clear_data' | 'import_file' | 'idle' | 'workflow'
  trigger: string
  action: RpaPopupAction
  button_text: string
  delay_ms: number
  enabled: boolean
}

export interface RpaPopupEvent {
  captured_at: string
  popup_type: 'dom' | 'browser' | string
  org_code: string
  month: string
  task: string
  step?: string
  trigger?: string
  url: string
  content: string
  close_action: string
  rule_id?: string
  keyword?: string
}

export const rpaApi = {
  getStatus: () => api.get<RpaStatus>('/rpa/status'),
  saveConfig: (chromePath: string, inputPath: string, outputPath: string) => api.put('/rpa/config', { chrome_path: chromePath, input_path: inputPath, output_path: outputPath }),
  getPopupRules: () => api.get<RpaPopupRule[]>('/rpa/popup-rules'),
  savePopupRules: (rules: RpaPopupRule[]) => api.put<RpaPopupRule[]>('/rpa/popup-rules', { rules }),
  resetPopupRules: () => api.post<RpaPopupRule[]>('/rpa/popup-rules/reset'),
  getPopupEvents: (limit = 100) => api.get<RpaPopupEvent[]>('/rpa/popup-events', { params: { limit } }),
  uploadOrgExcel: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post('/rpa/org-excel', form, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 })
  },
  uploadImportFiles: (files: File[], overwrite = false) => {
    const form = new FormData()
    files.forEach((file) => form.append('files', file))
    form.append('overwrite', String(overwrite))
    return api.post<RpaFile[]>('/rpa/import-files', form, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 300000 })
  },
  prepareFromPeriod: (periodId: number, overwrite = false) =>
    api.post<RpaFile[]>('/rpa/import-files/from-period', { period_id: periodId, overwrite }),
  clearImportFiles: (names: string[]) => api.delete<RpaFile[]>('/rpa/import-files', { data: { names } }),
  startChrome: (chromePath: string) => api.post('/rpa/chrome/start', { chrome_path: chromePath }),
  getChromeStatus: () => api.get<RpaStatus['chrome']>('/rpa/chrome/status'),
  previewOrgs: (payload: { all_orgs: boolean; org_code: string | null; start_org_code?: string | null }) =>
    api.post<{ count: number; items: RpaOrg[] }>('/rpa/orgs/preview', payload),
  startTask: (payload: { task_key: RpaTaskKey; month: string; all_orgs: boolean; org_code: string | null; resume_mode?: 'resume' | 'reset' | null }) =>
    api.post('/rpa/tasks/start', payload),
  organizations: (periodId: number) => api.get<{ items: RpaOrg[]; warnings: string[] }>('/rpa/organizations', { params: { period_id: periodId } }),
  previewOrganizations: (payload: { period_id: number; all_orgs: boolean; org_codes: string[]; start_org_code?: string | null }) =>
    api.post<{ count: number; items: RpaOrg[] }>('/rpa/orgs/preview', payload),
  startPeriodTask: (payload: { task_key: RpaTaskKey; period_id: number; declaration_month: string; all_orgs: boolean; org_codes: string[]; resume_mode?: 'resume' | 'reset' | null }) =>
    api.post('/rpa/tasks/start', payload),
  stopTask: () => api.post('/rpa/tasks/stop'),
  resetResults: (month: string) => api.delete<RpaStatus>('/rpa/results', { params: { month } }),
  resumeTask: () => api.post('/rpa/tasks/resume'),
  getLogs: (offset: number) => api.get<{ text: string; next_offset: number; finished: boolean }>('/rpa/logs', { params: { offset } }),
  listFiles: () => api.get<RpaFile[]>('/rpa/files'),
  downloadFile: (name: string) => api.get<Blob>('/rpa/files/download', { params: { name }, responseType: 'blob' }),
  downloadArchive: () => api.get<Blob>('/rpa/files/archive', { responseType: 'blob' }),
  clearOutputFiles: () => api.delete<RpaFile[]>('/rpa/files'),
}
