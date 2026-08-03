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
})

export interface Company {
  id: number
  name: string
  code: string
  operator_name: string
  notes: string
  active: boolean
  created_at: string
  updated_at: string
}

export type CompanyPayload = Pick<Company, 'name' | 'code' | 'operator_name' | 'notes'>

export const companyApi = {
  list: (includeInactive = false) => api.get<Company[]>('/companies', { params: { include_inactive: includeInactive } }),
  create: (payload: CompanyPayload) => api.post<Company>('/companies', payload),
  update: (id: number, payload: CompanyPayload) => api.put<Company>(`/companies/${id}`, payload),
  updateStatus: (id: number, active: boolean) => api.patch<Company>(`/companies/${id}/status`, { active }),
  select: (id: number) => api.post<Company>(`/companies/${id}/select`),
}

export interface Period {
  id: number
  year: number
  month: number
  name: string
  status: string
}

export interface Workflow {
  code: string
  name: string
  domain: string
  description: string
  required_file_roles: string[]
}

export interface UploadedFile {
  id: number
  period_id: number | null
  file_role: string
  original_name: string
  size_bytes: number
  validation_status: string
}

export interface Job {
  id: number
  workflow_code: string
  period_id: number | null
  operation: 'generate' | 'reconcile'
  app_version: string
  ruleset_version: string
  status: string
  input_file_ids: number[]
  result_summary: Record<string, unknown> | null
  error_message: string | null
  created_at: string
  artifacts?: Artifact[]
}

export interface Artifact {
  id: number
  job_id: number
  artifact_type: string
  file_name: string
  created_at: string
}

export interface SystemInfo {
  product_name: string
  app_version: string
  ruleset_version: string
  schema_version: number
  expected_schema_version: number
  runtime_mode: string
  data_root: string
  backup_root: string
  storage_bytes: number
  free_bytes: number
}

export interface BackupInfo {
  file_name: string
  path: string
  size_bytes: number
  created_at: string
}

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

export type FinanceSkillKey = 'general' | 'accounting' | 'tax' | 'review'

export interface FinanceAIStatus {
  configured: boolean
  model: string | null
  skills: Array<{ key: FinanceSkillKey; name: string }>
}

export interface FinanceChatMessage {
  role: 'user' | 'assistant'
  content: string
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
    status: 'idle' | 'starting' | 'running' | 'succeeded' | 'failed' | 'cancelled'
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

export type PersonType = 'employee' | 'broker'
export type PersonnelScopeType = 'month' | 'org' | 'branch'
export type ReconciliationImportType = 'bank_statement' | 'declaration_result' | 'accounting_ledger' | 'balance_sheet'

export interface PersonnelMasterArtifact {
  id: number
  period_id: number
  person_type: PersonType
  scope_type: PersonnelScopeType
  scope_code: string
  file_name: string
  row_count: number
  validation_issues: any[]
  updated_at: string
  download_url: string
}

export interface PersonnelMasterBatch {
  id: number
  period_id: number
  person_type: PersonType
  scope_type: PersonnelScopeType
  scope_code: string
  original_name: string
  row_count: number
  validation_issues: any[]
  created_at: string
}

export interface ReconciliationImportBatch {
  id: number
  period_id: number
  import_type: ReconciliationImportType
  original_name: string
  row_count: number
  validation_issues: any[]
  created_at: string
  download_url: string
}

export interface OrganizationMapping {
  id: number
  branch_name: string
  org_code: string
  taxpayer_id: string
  active: boolean
  rpa_enabled: boolean
  rpa_org_name: string
  parent_branch: string
  updated_at: string
}

export interface TaxSession {
  id: number
  period_id: number
  status: string
  current_round: number
  confirmed_personnel: PersonnelChange[] | null
  created_at: string
  updated_at: string
}

export interface PersonnelChange {
  change_type: string
  name: string
  id_number: string
  cert_type?: string
  org_code_from: string
  org_code_to: string
  employee_id: string
  phone: string
  hire_date?: string
  leave_date?: string
  missing_fields?: string[]
  can_confirm?: boolean
  action_required?: string
  is_transfer_like?: boolean
  applied?: boolean
}

export interface TaxDiffItem {
  name: string
  org_code: string
  id_number: string
  payroll_tax: number
  declared_tax: number
  diff: number
}

export interface VerificationCheck {
  code: string
  title: string
  status: 'pass' | 'fail' | 'warn'
  issue_count: number
  message: string
}

export interface VerifyReport {
  summary: {
    total_employees: number
    total_orgs: number
    total_issues: number
    blocking_issues?: number
    has_blocking_issues?: boolean
  }
  checks: VerificationCheck[]
  tax_diff: { has_issues: boolean; items: TaxDiffItem[]; by_org: any[] }
  personnel_changes: { has_issues: boolean; items: PersonnelChange[] }
  employee_id_changes?: {
    has_issues: boolean
    items: Array<{ name: string; id_number: string; org_code: string; old_employee_id: string; new_employee_id: string; message: string }>
  }
  missing_cert: { has_issues: boolean; items: { name: string; org_code: string; employee_id: string }[] }
  deduction_warnings: { has_issues: boolean; duplicates: any[]; missing_orgs: string[] }
  deduction_match_quality?: { low_confidence: any[]; name_mismatches: any[] }
  personnel_change_review?: any[]
  payroll_org_format?: { has_issues: boolean; items: { payroll_type: string; name: string; employee_id: string; org_code: string; message: string }[] }
  taxpayer_org_mapping?: { has_issues: boolean; items: { payroll_type: string; name: string; employee_id: string; taxpayer_id: string; message: string }[] }
  data_quality?: { has_issues: boolean; items: any[] }
  key_field_missing?: { has_issues: boolean; items: any[] }
  personnel_update_issues?: { match_failures: any[]; duplicate_additions: any[]; multiple_matches: any[] }
  headcount_reconciliation?: { has_issues: boolean; items: any[] }
}

export interface GeneratedFile {
  name: string
  download_url: string
  file_type?: string
}

export interface VerifyResponse {
  session_id: number
  round_number: number
  status: string
  report: VerifyReport
  artifacts?: GeneratedFile[]
}

export const taxApi = {
  createSession: (periodId: number) =>
    api.post<TaxSession>('/tax/sessions', { period_id: periodId }),

  verify: (sessionId: number, formData: FormData) =>
    api.post<VerifyResponse>(`/tax/sessions/${sessionId}/verify`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    }),

  latestResult: (sessionId: number) =>
    api.get<{
      status: string
      round_number: number | null
      report: VerifyReport | null
      artifacts: GeneratedFile[]
      generated_files: GeneratedFile[]
    }>(`/tax/sessions/${sessionId}/latest-result`),

  confirm: (sessionId: number, changes: {
    name: string
    id_number: string
    change_type: string
    cert_type?: string
    org_code_from?: string
    org_code_to?: string
    employee_id?: string
    phone?: string
    hire_date?: string
    leave_date?: string
    missing_fields?: string[]
    confirmed: boolean
    is_transfer_like?: boolean
  }[]) =>
    api.post(`/tax/sessions/${sessionId}/confirm`, { confirmed_changes: changes }),

  generate: (sessionId: number) =>
    api.post<{ status: string; files: GeneratedFile[] }>(`/tax/sessions/${sessionId}/generate`, {}, { timeout: 120000 }),
  clearGeneratedFiles: (sessionId: number) =>
    api.delete<{ status: string; files: GeneratedFile[] }>(`/tax/sessions/${sessionId}/generated-files`),
}

export const workflowApi = {
  list: () => api.get<Workflow[]>('/workflows'),

  uploadFile: (file: File, fileRole: string, periodId: number | null) => {
    const form = new FormData()
    form.append('file', file)
    form.append('file_role', fileRole)
    if (periodId) form.append('period_id', String(periodId))
    return api.post<UploadedFile>('/files', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },

  createJob: (workflowCode: string, inputFileIds: number[], periodId: number | null, operation?: string) =>
    api.post<Job>('/jobs', {
      workflow_code: workflowCode,
      input_file_ids: inputFileIds,
      period_id: periodId,
      operation,
    }, { timeout: 120000 }),

  listJobs: (periodId?: number | null, workflowCode?: string) =>
    api.get<Job[]>('/jobs', {
      params: { period_id: periodId || undefined, workflow_code: workflowCode || undefined },
    }),

  latestJob: (workflowCode: string, periodId: number, operation?: 'generate' | 'reconcile') =>
    api.get<Job>('/jobs/latest', {
      params: { workflow_code: workflowCode, period_id: periodId, operation },
    }),

  artifactDownloadUrl: (artifactId: number) => companyUrl(`/api/artifacts/${artifactId}/download`),
  batchDownloadUrl: (jobId: number) => companyUrl(`/api/jobs/${jobId}/download-all`),
  downloadArtifact: (artifactId: number) => api.get<Blob>(`/artifacts/${artifactId}/download`, { responseType: 'blob' }),
  internTemplateUrl: () => companyUrl('/api/workflows/intern-tax/template'),
}

export const systemApi = {
  info: () => api.get<SystemInfo>('/system/info'),
  backups: () => api.get<BackupInfo[]>('/system/backups'),
  createBackup: () => api.post<BackupInfo>('/system/backups', {}, { timeout: 120000 }),
  backupDownloadUrl: (fileName: string) => `/api/system/backups/${encodeURIComponent(fileName)}`,
  diagnosticsUrl: () => '/api/system/diagnostics',
  restore: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post('/system/restore', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,
    })
  },
}

export const organizationMappingApi = {
  list: () => api.get<OrganizationMapping[]>('/organization-mappings'),
  create: (payload: { branch_name: string; org_code: string; taxpayer_id: string; active: boolean; rpa_enabled: boolean; rpa_org_name: string; parent_branch: string }) =>
    api.post<OrganizationMapping>('/organization-mappings', payload),
  update: (id: number, payload: { branch_name: string; org_code: string; taxpayer_id: string; active: boolean; rpa_enabled: boolean; rpa_org_name: string; parent_branch: string }) =>
    api.put<OrganizationMapping>(`/organization-mappings/${id}`, payload),
  importFile: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<{ updated: number }>('/organization-mappings/import', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
  exportUrl: () => companyUrl('/api/organization-mappings/export'),
}

export const personnelMasterApi = {
  importFile: (
    file: File,
    periodId: number,
    personType: PersonType,
    scopeType: PersonnelScopeType,
    scopeCode: string
  ) => {
    const form = new FormData()
    form.append('file', file)
    form.append('period_id', String(periodId))
    form.append('person_type', personType)
    form.append('scope_type', scopeType)
    if (scopeCode) form.append('scope_code', scopeCode)
    return api.post<PersonnelMasterArtifact>('/personnel-masters/import', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },

  status: (periodId: number, personType: PersonType) =>
    api.get<PersonnelMasterArtifact[]>('/personnel-masters/status', {
      params: { period_id: periodId, person_type: personType },
    }),

  batches: (periodId: number, personType: PersonType) =>
    api.get<PersonnelMasterBatch[]>('/personnel-masters/batches', {
      params: { period_id: periodId, person_type: personType },
    }),
}

export const reconciliationImportApi = {
  importFile: (file: File, periodId: number, importType: ReconciliationImportType) => {
    const pathByType: Record<ReconciliationImportType, string> = {
      bank_statement: '/reconciliation-imports/bank-statement',
      declaration_result: '/reconciliation-imports/declaration-result',
      accounting_ledger: '/reconciliation-imports/accounting-ledger',
      balance_sheet: '/reconciliation-imports/balance-sheet',
    }
    const form = new FormData()
    form.append('file', file)
    return api.post<ReconciliationImportBatch>(pathByType[importType], form, {
      params: { period_id: periodId },
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },

  list: (periodId: number, importType?: ReconciliationImportType) =>
    api.get<ReconciliationImportBatch[]>('/reconciliation-imports', {
      params: { period_id: periodId, import_type: importType || undefined },
    }),
}

export const financeAIApi = {
  status: () => api.get<FinanceAIStatus>('/finance-ai/status'),
  chat: (payload: { skill: FinanceSkillKey; messages: FinanceChatMessage[]; period_context?: string }) =>
    api.post<{ content: string; model: string; usage?: Record<string, number> }>(
      '/finance-ai/chat',
      payload,
      { timeout: 90000 },
    ),
}

export const bankFetchApi = {
  start: (payload: { period_id: number; accounts: string; start_date: string; end_date: string }) => api.post('/bank-fetch/start', payload),
  status: () => api.get<{ status: string; message: string; batch_id: number | null; events: Array<{ id: number; at: string; message: string }> }>('/bank-fetch/status'),
  openLogin: () => api.post('/bank-fetch/open-login'),
  stop: () => api.post('/bank-fetch/stop'),
}

export const rpaApi = {
  getStatus: () => api.get<RpaStatus>('/rpa/status'),
  saveConfig: (chromePath: string, inputPath: string, outputPath: string) => api.put('/rpa/config', { chrome_path: chromePath, input_path: inputPath, output_path: outputPath }),
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
