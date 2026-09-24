import { api, companyUrl } from './client'

export interface PitOverviewResponse { exists: boolean; period_id?: number; workpaper?: Record<string, unknown> & { data_status?: string; stage?: string; workflow_status?: string; last_calculated_at?: string | null }; counts?: Record<string, number> }
export interface PitReadinessItem { source_type: string; source_status: string; required: boolean; row_count: number | null; source_kind?: string | null; source_id?: number | null; source_ref?: string | null; issues_json?: Array<{ message?: string }> | null }
export interface PitOrgSummary { id: number; public_id: string; org_code: string; org_name: string; org_full_name?: string | null; declared_tax_amount: number | null; balance_tax_amount: number | null; difference_1: number | null; difference_1_manual_reason: string | null; scoped_declared_tax_amount: number | null; payroll_business_tax_amount: number | null; difference_2: number | null; difference_2_manual_reason: string | null; taxable_income_difference: number | null; difference_3_manual_reason: string | null; certificate_tax_amount: number | null; difference_4: number | null; difference_4_manual_reason: string | null; bank_tax_amount: number | null; difference_5: number | null; difference_5_manual_reason: string | null; broker_occurrence_difference: number | null; difference_6_manual_reason: string | null; other_income_difference: number | null; difference_7_manual_reason: string | null; remark: string | null; check_status: string }
export interface PitTaxAmountCheck { id: number; org_code: string; org_name: string; subject_code: string; subject_name: string; opening_balance: number | null; debit_amount: number | null; credit_amount: number | null; closing_balance: number | null; business_tax_amount: number | null; declared_tax_amount: number | null; current_difference: number | null; current_manual_reason: string | null; cumulative_difference: number | null; cumulative_manual_reason: string | null; scoped_declared_tax_amount: number | null; business_declared_difference: number | null; business_declared_manual_reason: string | null; remark: string | null; check_status: string }
export interface PitOccurrenceCheck { id: number; org_code: string; org_name: string; subject_code: string; subject_name: string; income_type: string; opening_balance: number | null; debit_amount: number | null; credit_amount: number | null; closing_balance: number | null; occurrence_amount: number | null; broker_payroll_amount: number | null; broker_occurrence_difference: number | null; broker_occurrence_manual_reason: string | null; expected_declared_income: number | null; expected_income_description: string | null; actual_declared_income: number | null; declared_income_difference: number | null; declared_income_manual_reason: string | null; remark: string | null; check_status: string }
export interface PitDeclarationSummary { id: number; org_code: string; org_name: string; declaration_type: string; income_item: string; person_count: number; income_amount: number | null; tax_amount: number | null }
export interface PitDifferenceDetail { id: number; detail_type: string; org_code: string; org_name: string; subject_code?: string | null; identity_key: string; person_or_customer_name: string; id_number?: string | null; source_amount: number | null; target_amount: number | null; difference: number | null; auto_reason?: string | null; manual_reason?: string | null; remark?: string | null; detail_json: Record<string, unknown> | null }
export interface PitBankTaxMatch { id: number; org_code: string; org_full_name: string; bank_account?: string | null; transaction_time?: string | null; transaction_summary?: string | null; debit_amount: number | null }
export interface PitSheetData { sheet_name: string; columns: string[]; column_labels?: string[]; rows: Array<Record<string, unknown>>; total: number; page: number; page_size: number }
export type PitListParams = { org_code?: string; subject_code?: string; only_differences?: boolean; detail_type?: string; search?: string }
export type PitStage = 'pre_payment' | 'post_payment'

export const pitReconciliationApi = {
  getOverview: (periodId: number, stage: PitStage) => api.get<PitOverviewResponse>('/pit-reconciliations/overview', { params: { period_id: periodId, stage } }),
  getReadiness: (periodId: number, stage: PitStage) => api.get<PitReadinessItem[]>('/pit-reconciliations/readiness', { params: { period_id: periodId, stage } }),
  recalculate: (periodId: number, stage: 'pre_payment' | 'post_payment' = 'pre_payment') => api.post('/pit-reconciliations/recalculate', {}, { params: { period_id: periodId, stage }, timeout: 120000 }),
  aggregateReasons: (periodId: number, stage: 'pre_payment' | 'post_payment', mode: 'fill_empty' | 'refresh_generated') =>
    api.post('/pit-reconciliations/aggregate-reasons', { mode }, { params: { period_id: periodId, stage } }),
  getSummary: (periodId: number, stage: PitStage) => api.get<PitOrgSummary[]>('/pit-reconciliations/org-summaries', { params: { period_id: periodId, stage } }),
  getTaxAmountChecks: (periodId: number, stage: PitStage, params: PitListParams = {}) => api.get<PitTaxAmountCheck[]>('/pit-reconciliations/tax-amount-checks', { params: { period_id: periodId, stage, ...params } }),
  getOccurrenceChecks: (periodId: number, stage: PitStage, params: PitListParams = {}) => api.get<PitOccurrenceCheck[]>('/pit-reconciliations/occurrence-checks', { params: { period_id: periodId, stage, ...params } }),
  getDeclarationSummary: (periodId: number, stage: PitStage) => api.get<PitDeclarationSummary[]>('/pit-reconciliations/declaration-summaries', { params: { period_id: periodId, stage } }),
  getDifferences: (periodId: number, stage: PitStage, params: PitListParams) => api.get<PitDifferenceDetail[]>('/pit-reconciliations/difference-details', { params: { period_id: periodId, stage, ...params } }),
  getBankMatches: (periodId: number, stage: PitStage, params: PitListParams = {}) => api.get<PitBankTaxMatch[]>('/pit-reconciliations/bank-matches', { params: { period_id: periodId, stage, ...params } }),
  getSheetData: (periodId: number, stage: PitStage, sheetName: string, page = 1, pageSize = 100, filters: { keyword?: string; org_code?: string; display_mode?: 'all' | 'difference' | 'missing' } = {}) => api.get<PitSheetData>('/pit-reconciliations/sheet-data', { params: { period_id: periodId, stage, sheet_name: sheetName, page, page_size: pageSize, ...filters }, timeout: 120000 }),
  exportUrl: (periodId: number, stage: PitStage) => companyUrl(`/api/pit-reconciliations/export?period_id=${periodId}&stage=${stage}`),
  exportOccurrenceDescriptions: (periodId: number, stage: PitStage) => api.get<Blob>('/pit-reconciliations/occurrence-descriptions/export', { params: { period_id: periodId, stage }, responseType: 'blob' }),
  importOccurrenceDescriptions: (periodId: number, stage: PitStage, file: File) => { const data = new FormData(); data.append('file', file); return api.post<{ updated_count: number; unmatched_count: number; draft_revision: number }>('/pit-reconciliations/occurrence-descriptions/import', data, { params: { period_id: periodId, stage } }) },
  updateSummary: (periodId: number, stage: PitStage, id: number, payload: Partial<Pick<PitOrgSummary, 'difference_1_manual_reason' | 'difference_2_manual_reason' | 'difference_3_manual_reason' | 'difference_4_manual_reason' | 'difference_5_manual_reason' | 'difference_6_manual_reason' | 'difference_7_manual_reason' | 'remark'>>) => api.patch<PitOrgSummary>(`/pit-reconciliations/org-summaries/${id}`, payload, { params: { period_id: periodId, stage } }),
  updateTaxAmountCheck: (periodId: number, stage: PitStage, id: number, payload: Partial<Pick<PitTaxAmountCheck, 'current_manual_reason' | 'cumulative_manual_reason' | 'business_declared_manual_reason' | 'remark'>>) => api.patch<PitTaxAmountCheck>(`/pit-reconciliations/tax-amount-checks/${id}`, payload, { params: { period_id: periodId, stage } }),
  updateOccurrenceCheck: (periodId: number, stage: PitStage, id: number, payload: Partial<Pick<PitOccurrenceCheck, 'broker_occurrence_manual_reason' | 'declared_income_manual_reason' | 'remark'>>) => api.patch<PitOccurrenceCheck>(`/pit-reconciliations/occurrence-checks/${id}`, payload, { params: { period_id: periodId, stage } }),
  updateDifference: (periodId: number, stage: PitStage, id: number, payload: { manual_reason?: string; remark?: string }) => api.patch<PitDifferenceDetail>(`/pit-reconciliations/difference-details/${id}`, payload, { params: { period_id: periodId, stage } }),
}

export interface FmssSession { connected: boolean; environment: string; username: string | null; displayName: string | null }
export interface FmssBranch { branchCode?: string; branchName?: string; code?: string; name?: string }
export interface FmssSheetDefinition { key: string; title: string; headers: string[] }
export const fmssApi = {
  session: (validate = false) => api.get<FmssSession>('/fmss/session', { params: { validate: validate || undefined } }),
  logout: () => api.post<{ cleared: boolean }>('/fmss/logout'),
  openBrowserLogin: () => api.post<{ status: string; message: string | null }>('/fmss/browser/open'),
  browserStatus: () => api.get<{ status: string; message: string | null }>('/fmss/browser/status'),
  closeBrowserLogin: () => api.post<{ status: string; message: string | null }>('/fmss/browser/close'),
  branches: () => api.get<FmssBranch[] | { rows?: FmssBranch[] }>('/fmss/iit/branches'),
  sheets: (stage: 'PRE' | 'POST') => api.get<FmssSheetDefinition[]>('/fmss/iit/sheets', { params: { stage } }),
  declaration: (periodId: number, stage: PitStage) => api.get<{ status: string; declaration: unknown; declaration_id: string | null; double_review_completed?: boolean }>('/fmss/iit/declaration', { params: { period_id: periodId, stage } }),
  approvalLog: (periodId: number) => api.get<{ rows?: any[]; canManage?: boolean }>('/fmss/iit/approval-log', { params: { period_id: periodId } }),
  review: (declarationId: string) => api.get<any>(`/fmss/iit/review/${encodeURIComponent(declarationId)}`),
  reviewers: (periodId: number, stage: PitStage) => api.get<any>('/fmss/iit/reviewers', { params: { period_id: periodId, stage } }),
  submit: (periodId: number, reviewer: string, stage: PitStage) => api.post<any>('/fmss/iit/submit', { period_id: periodId, reviewer, stage }),
  decision: (declarationId: string, passed: boolean, comment: string) => api.post<any>('/fmss/iit/decision', { id: declarationId, passed, comment }),
  withdraw: (declarationId: string) => api.post<any>(`/fmss/iit/withdraw/${encodeURIComponent(declarationId)}`),
}

