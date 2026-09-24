import { api, companyUrl } from './client'

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
  operation: 'generate' | 'reconcile' | 'initial' | 'recheck'
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
  retirement_welfare?: {
    items: Array<{
      name: string
      org_code: string
      id_number: string
      welfare_column: string
      welfare_amount: number
      payroll_exists: boolean
      personnel_status: string
      match_method: string
      payroll_taxable_adjustment: number
      status: string
      action: string
      blocking: boolean
    }>
  }
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
  listSessions: (periodId?: number | null) =>
    api.get<TaxSession[]>('/tax/sessions', { params: { period_id: periodId || undefined } }),

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
  partTimeTemplateUrl: () => companyUrl('/api/workflows/part-time-tax/template'),
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

  latestJob: (workflowCode: string, periodId: number, operation?: 'generate' | 'reconcile' | 'initial' | 'recheck') =>
    api.get<Job>('/jobs/latest', {
      params: { workflow_code: workflowCode, period_id: periodId, operation },
    }),

  artifactDownloadUrl: (artifactId: number) => companyUrl(`/api/artifacts/${artifactId}/download`),
  batchDownloadUrl: (jobId: number) => companyUrl(`/api/jobs/${jobId}/download-all`),
  downloadArtifact: (artifactId: number) => api.get<Blob>(`/artifacts/${artifactId}/download`, { responseType: 'blob' }),
  downloadAll: (jobId: number) => api.get<Blob>(`/jobs/${jobId}/download-all`, { responseType: 'blob' }),
  saveAll: (jobId: number, directory: string) => api.post<{ saved_count: number; directory: string; files: string[] }>(`/jobs/${jobId}/save-all`, { directory }),
  internTemplateUrl: () => companyUrl('/api/workflows/intern-tax/template'),
}

export const bankFetchApi = {
  start: (payload: { period_id: number; accounts: string; start_date: string; end_date: string }) => api.post('/bank-fetch/start', payload),
  status: () => api.get<{ status: string; message: string; batch_id: number | null; events: Array<{ id: number; at: string; message: string }> }>('/bank-fetch/status'),
  openLogin: () => api.post('/bank-fetch/open-login'),
  stop: () => api.post('/bank-fetch/stop'),
}

