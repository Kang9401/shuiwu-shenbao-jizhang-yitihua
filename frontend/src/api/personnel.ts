import { api } from './client'

export type PersonType = 'employee' | 'intern' | 'broker' | 'part_time'
export type PersonnelScopeType = 'month' | 'org' | 'branch'
export type ReconciliationImportType = 'bank_statement' | 'declaration_result' | 'accounting_ledger' | 'balance_sheet' | 'pit_declaration' | 'tax_certificate'

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
  file_results?: Array<{ file_name: string; status: 'success' | 'failed'; organization?: string; period?: string; error?: string }>
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
  clear: (period_id: number, import_type: ReconciliationImportType, batch_ids: number[]) => api.post<{deleted_batches:number;deleted_rows:number}>('/reconciliation-imports/clear', {period_id, import_type, batch_ids}),
  importFiles: (files: File[], periodId: number, importType: ReconciliationImportType) => {
    const pathByType: Record<ReconciliationImportType, string> = {
      bank_statement: '/reconciliation-imports/bank-statement',
      declaration_result: '/reconciliation-imports/declaration-result',
      accounting_ledger: '/reconciliation-imports/accounting-ledger',
      balance_sheet: '/reconciliation-imports/balance-sheet',
      pit_declaration: '/reconciliation-imports/pit-declarations',
      tax_certificate: '/reconciliation-imports/tax-certificates',
    }
    const form = new FormData()
    const field = importType === 'tax_certificate' || importType === 'pit_declaration' ? 'files' : 'file'
    files.forEach((file) => form.append(field, file))
    return api.post<ReconciliationImportBatch>(pathByType[importType], form, {
      params: { period_id: periodId },
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
  importFile: (file: File, periodId: number, importType: ReconciliationImportType) => reconciliationImportApi.importFiles([file], periodId, importType),

  list: (periodId: number, importType?: ReconciliationImportType) =>
    api.get<ReconciliationImportBatch[]>('/reconciliation-imports', {
      params: { period_id: periodId, import_type: importType || undefined },
    }),
}

