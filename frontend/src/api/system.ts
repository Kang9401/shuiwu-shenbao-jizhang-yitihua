import { api } from './client'

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

