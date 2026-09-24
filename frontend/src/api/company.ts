import { api, companyUrl } from './client'

export interface Company {
  id: number
  name: string
  code: string
  operator_name: string
  notes: string
  fmss_branch_code: string | null
  fmss_branch_name: string | null
  active: boolean
  created_at: string
  updated_at: string
}

export type CompanyPayload = Pick<Company, 'name' | 'code' | 'operator_name' | 'notes' | 'fmss_branch_code' | 'fmss_branch_name'>

export const companyApi = {
  list: (includeInactive = false) => api.get<Company[]>('/companies', { params: { include_inactive: includeInactive } }),
  create: (payload: CompanyPayload) => api.post<Company>('/companies', payload),
  update: (id: number, payload: CompanyPayload) => api.put<Company>(`/companies/${id}`, payload),
  updateStatus: (id: number, active: boolean) => api.patch<Company>(`/companies/${id}/status`, { active }),
  select: (id: number) => api.post<Company>(`/companies/${id}/select`),
}

export interface OrganizationMapping {
  id: number
  branch_name: string
  org_code: string
  taxpayer_id: string
  active: boolean
  rpa_enabled: boolean
  rpa_org_name: string
  rpa_search_result_index: number
  parent_branch: string
  bank_account: string
  bank_subaccount: string
  updated_at: string
}


export const organizationMappingApi = {
  list: () => api.get<OrganizationMapping[]>('/organization-mappings'),
  create: (payload: { branch_name: string; org_code: string; taxpayer_id: string; active: boolean; rpa_enabled: boolean; rpa_org_name: string; rpa_search_result_index: number; parent_branch: string; bank_subaccount: string }) =>
    api.post<OrganizationMapping>('/organization-mappings', payload),
  update: (id: number, payload: { branch_name: string; org_code: string; taxpayer_id: string; active: boolean; rpa_enabled: boolean; rpa_org_name: string; rpa_search_result_index: number; parent_branch: string; bank_subaccount: string }) =>
    api.put<OrganizationMapping>(`/organization-mappings/${id}`, payload),
  delete: (id: number) => api.delete<{ deleted: number }>(`/organization-mappings/${id}`),
  importFile: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<{ updated: number; deleted: number }>('/organization-mappings/import', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    })
  },
  exportUrl: () => companyUrl('/api/organization-mappings/export'),
}

